import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { setTimeout } from "node:timers/promises";
import { assertOutput } from "./harness.mjs";

const terminal = new Set(["SUCCEEDED", "FAILED", "CANCELLED"]);

/** Execute a fictional case through the public Studio API, never directly through a worker. */
export async function runCase(suite, golden, config) {
  const base = new URL(config.baseUrl);
  assert.ok(base.protocol === "https:" || (base.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname)), "use HTTPS outside loopback");
  assert.ok(!base.username && !base.password && base.pathname === "/" && !base.search && !base.hash, "baseUrl must be an origin");
  for (const key of ["timeoutMs", "pollIntervalMs"]) assert.ok(Number.isSafeInteger(config[key]) && config[key] > 0, `${key} must be a positive integer`);
  assert.ok(typeof config.token === "string" && config.token.trim(), "an authenticated test account is required");
  const deadline = Date.now() + config.timeoutMs;
  const uploaded = new Map();
  let run;

  const request = async (path, method = "GET", body, expectedStatus = 200, cleanup = false) => {
    const remaining = cleanup ? config.timeoutMs : deadline - Date.now();
    assert.ok(remaining > 0, "golden run deadline exceeded");
    const response = await fetch(new URL(path, base), {
      method, redirect: "error", signal: AbortSignal.timeout(remaining),
      headers: {
        Authorization: ["Bearer", config.token].join(" "),
        ...(body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(method === "POST" && path.endsWith("/runs") ? { "Idempotency-Key": randomUUID() } : {}),
      },
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    });
    // Do not log response bodies: an error can echo private input or credentials.
    assert.equal(response.status, expectedStatus, `${method} ${path}: HTTP ${response.status}`);
    assert.notEqual(response.headers.get("Idempotent-Replayed"), "true", "goldens must not reuse an idempotent replay");
    return response.status === 204 ? undefined : response.json();
  };
  const resolve = async (value) => {
    if (Array.isArray(value)) return Promise.all(value.map(resolve));
    if (value && typeof value === "object") {
      return Object.fromEntries(await Promise.all(Object.entries(value).map(async ([key, child]) => [key, await resolve(child)])));
    }
    if (typeof value !== "string" || !/^(asset|base64):/.test(value)) return value;
    const [kind, name] = value.split(":");
    assert.ok(Object.hasOwn(config.assets ?? {}, name), `missing synthetic asset ${name}`);
    const asset = config.assets[name];
    if (kind === "base64") return asset.base64;
    if (!uploaded.has(name)) {
      // Store the promise before awaiting it: repeated references share one upload.
      uploaded.set(name, (async () => {
        const form = new FormData();
        form.set("file", new Blob([Buffer.from(asset.base64, "base64")], { type: asset.mediaType }), asset.filename);
        const result = await request("/api/v1/media/upload", "POST", form, 201);
        assert.match(result.assetId, /^[a-zA-Z0-9-]+$/);
        return result.assetId;
      })());
    }
    return uploaded.get(name);
  };

  try {
    const inputs = await resolve(golden.input);
    const installation = config.installations?.[suite.studio];
    if (installation) assert.match(installation, /^[a-zA-Z0-9-]+$/);
    const resource = installation ? `installations/${installation}` : encodeURIComponent(suite.studio);
    run = await request(`/api/v1/studios/${resource}/runs`, "POST", { inputs }, 202);
    assert.match(run.id, /^[a-zA-Z0-9-]+$/);
    while (!terminal.has(run.status)) {
      assert.ok(!["PENDING_APPROVAL", "AWAITING_INPUT"].includes(run.status), `golden run requires operator action: ${run.status}`);
      assert.ok(Date.now() + config.pollIntervalMs < deadline, "golden run deadline exceeded");
      await setTimeout(config.pollIntervalMs);
      run = await request(`/api/v1/studios/runs/${run.id}`);
    }
    assert.equal(run.status, "SUCCEEDED", `${suite.studio}/${golden.id}: ${run.status}`);
    assert.equal(run.studioKey, suite.studio, "wrong Studio executed");
    assert.equal(run.blueprintVersion, suite.blueprint.version, "install the blueprint under test, not a stale published version");
    assert.equal(run.cachedFrom ?? null, null, "goldens must execute rather than reuse a cached run");
    assert.ok(Array.isArray(run.outputs), "missing Studio output artefacts");
    const output = {};
    for (const artifact of run.outputs) {
      assert.ok(!Object.hasOwn(output, artifact.key), `duplicate output ${artifact.key}`);
      Object.defineProperty(output, artifact.key, {
        value: artifact.type === "JSON" ? JSON.parse(artifact.value) : artifact.value, enumerable: true,
      });
    }
    assertOutput(output, golden.assertions);
    return output;
  } finally {
    if (run?.id && !terminal.has(run.status)) {
      await request(`/api/v1/studios/runs/${encodeURIComponent(run.id)}/cancel`, "POST", undefined, 204, true);
    }
    for (const pending of uploaded.values()) {
      const id = await pending.catch(() => null);
      if (id) await request(`/api/v1/media/assets/${id}`, "DELETE", undefined, 204, true);
    }
  }
}
