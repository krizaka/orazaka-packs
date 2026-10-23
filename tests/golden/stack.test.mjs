import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import { runCase } from "./stack.mjs";

const suite = { studio: "echo-reverse", blueprint: { version: "1.2.0" } };
const golden = { id: "fictional", input: { text: "Bonjour" }, assertions: [{ path: ["reversed"], equals: "ruojnoB" }] };

async function withStack(handler, fn) {
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const config = {
    baseUrl: `http://127.0.0.1:${server.address().port}`,
    token: "fictional-test-account", timeoutMs: 1000, pollIntervalMs: 1, assets: {},
  };
  try { await fn(config); } finally { await new Promise((resolve) => server.close(resolve)); }
}

const completed = (overrides = {}) => ({
  id: "run-1", studioKey: "echo-reverse", blueprintVersion: "1.2.0", status: "SUCCEEDED",
  outputs: [{ key: "reversed", type: "TEXT", value: "ruojnoB" }], ...overrides,
});

test("the live adapter sends authenticated inputs, polls compensation, and asserts actual public outputs", async () => {
  const calls = [];
  await withStack(async (req, res) => {
    assert.equal(req.headers.authorization, ["Bearer", "fictional-test-account"].join(" "));
    calls.push(`${req.method} ${req.url}`);
    if (req.method === "POST") {
      assert.ok(req.headers["idempotency-key"]);
      let body = "";
      for await (const chunk of req) body += chunk;
      assert.deepEqual(JSON.parse(body), { inputs: golden.input });
      res.writeHead(202).end(JSON.stringify({ id: "run-1", status: "RUNNING" }));
    } else {
      res.end(JSON.stringify(calls.length === 2 ? { id: "run-1", status: "COMPENSATING" } : completed()));
    }
  }, async (config) => {
    assert.deepEqual(await runCase(suite, golden, config), { reversed: "ruojnoB" });
  });
  assert.deepEqual(calls, ["POST /api/v1/studios/echo-reverse/runs", "GET /api/v1/studios/runs/run-1", "GET /api/v1/studios/runs/run-1"]);
});

test("live execution rejects failed runs, stale blueprints, and changed output verdicts", async () => {
  for (const result of [
    completed({ status: "FAILED" }),
    completed({ status: "CANCELLED" }),
    completed({ blueprintVersion: "stale" }),
    completed({ cachedFrom: "previous-run" }),
    completed({ outputs: [{ key: "reversed", type: "TEXT", value: "wrong" }] }),
    completed({ outputs: [{ key: "reversed", type: "JSON", value: "not JSON" }] }),
  ]) {
    await withStack((req, res) => res.writeHead(202).end(JSON.stringify(result)), async (config) => {
      await assert.rejects(runCase(suite, golden, config));
    });
  }
});

test("idempotent replays cannot count as fresh model execution", async () => {
  await withStack((req, res) => {
    res.writeHead(202, { "Idempotent-Replayed": "true" }).end(JSON.stringify(completed()));
  }, async (config) => {
    await assert.rejects(runCase(suite, golden, config), /idempotent replay/);
  });
});

test("synthetic assets upload once, substitute recursively, and are deleted after assertion failure", async () => {
  const calls = [];
  await withStack(async (req, res) => {
    calls.push(`${req.method} ${req.url}`);
    if (req.url === "/api/v1/media/upload") {
      assert.match(req.headers["content-type"], /multipart\/form-data/);
      req.resume();
      res.writeHead(201).end('{"assetId":"asset-1"}');
    } else if (req.method === "DELETE") {
      res.writeHead(204).end();
    } else {
      let body = "";
      for await (const chunk of req) body += chunk;
      assert.deepEqual(JSON.parse(body).inputs, { photos: ["asset-1", "asset-1"], encoded: "c3ludGhldGlj" });
      res.writeHead(202).end(JSON.stringify(completed()));
    }
  }, async (config) => {
    config.assets.scene = { filename: "synthetic.png", mediaType: "image/png", base64: "c3ludGhldGlj" };
    await assert.rejects(runCase(suite, {
      ...golden, input: { photos: ["asset:scene", "asset:scene"], encoded: "base64:scene" },
      assertions: [{ path: ["reversed"], equals: "deliberate-mismatch" }],
    }, config));
  });
  assert.deepEqual(calls, ["POST /api/v1/media/upload", "POST /api/v1/studios/echo-reverse/runs", "DELETE /api/v1/media/assets/asset-1"]);
});

test("operator-action states cancel rather than auto-approving a regulated run", async () => {
  const calls = [];
  await withStack((req, res) => {
    calls.push(`${req.method} ${req.url}`);
    if (req.url.endsWith("/cancel")) res.writeHead(204).end();
    else res.writeHead(202).end('{"id":"run-1","status":"PENDING_APPROVAL"}');
  }, async (config) => {
    await assert.rejects(runCase(suite, golden, config), /operator action/);
  });
  assert.equal(calls.at(-1), "POST /api/v1/studios/runs/run-1/cancel");
});

test("credentials are never sent over non-local HTTP or followed to another origin", async () => {
  await assert.rejects(runCase(suite, golden, { baseUrl: "http://example.com" }), /HTTPS/);
  await withStack((req, res) => res.writeHead(302, { Location: "https://example.com" }).end(), async (config) => {
    await assert.rejects(runCase(suite, golden, config));
  });

});

test("a run that never completes hits its configured deadline and is cancelled", async () => {
  let cancelled = false;
  await withStack((req, res) => {
    if (req.url.endsWith("/cancel")) {
      cancelled = true;
      res.writeHead(204).end();
    } else res.writeHead(req.method === "POST" ? 202 : 200).end('{"id":"run-1","status":"RUNNING"}');
  }, async (config) => {
    await assert.rejects(runCase(suite, golden, { ...config, timeoutMs: 1000, pollIntervalMs: 1000 }), /deadline/);
  });
  assert.ok(cancelled);
});

test("the CI lane audits every PR but never runs PR code against the credentialed stack", async () => {
  const { readFileSync } = await import("node:fs");
  const workflow = readFileSync(new URL("../../.github/workflows/ci.yml", import.meta.url), "utf8");
  const lane = workflow.slice(workflow.indexOf("  golden-stack:"), workflow.indexOf("  py-photo:"));
  assert.match(lane, /github\.ref == 'refs\/heads\/main'/);
  assert.match(lane, /github\.event_name == 'workflow_dispatch'/);
  assert.match(lane, /github\.event_name == 'push'/);
  assert.match(lane, /environment: golden-stack/);
  assert.match(lane, /npm run golden:run/);
  assert.match(workflow, /GOLDEN_BASE_SHA: \$\{\{ github\.event\.pull_request\.base\.sha \}\}/);
});
