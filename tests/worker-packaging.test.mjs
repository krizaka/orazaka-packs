// The workers share worker-common/ (broker connection). A worker is deployed from a COPY of this whole repository
// (orazaka infra/deploy/Dockerfile: `cp -r orazaka-packs /out/orazaka-packs`, the worker started from
// /app/orazaka-packs/<pack>/worker). This test builds that packaged form in a temp folder - the repository copied as a whole,
// nothing else on the Python path but a stub of pika - and imports each worker's `broker` from its own directory.
import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

const ROOT = new URL("..", import.meta.url).pathname;
const workers = readdirSync(ROOT, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(join(ROOT, d.name, "worker", "broker.py")))
  .map((d) => d.name);

function packaged() {
  const dir = mkdtempSync(join(tmpdir(), "packs-"));
  const copy = join(dir, "orazaka-packs");
  cpSync(ROOT, copy, { recursive: true, filter: (src) => !/[\\/](\.git|node_modules)([\\/]|$)/.test(src) });
  mkdirSync(join(dir, "stubs", "pika"), { recursive: true });
  writeFileSync(join(dir, "stubs", "pika", "__init__.py"), "# stub: the broker module only needs the name at import time\n");
  return { dir, copy };
}

const python = (cwd, dir, code) =>
  spawnSync("python3", ["-c", code], { cwd, env: { PATH: process.env.PATH, PYTHONPATH: join(dir, "stubs"), PYTHONDONTWRITEBYTECODE: "1" }, encoding: "utf8" });

test("there are pack workers to check", () => {
  assert.ok(workers.length >= 4, `found ${workers.join(", ")}`);
});

test("every worker's broker resolves worker_broker from the packaged repository copy", () => {
  const { dir, copy } = packaged();
  try {
    for (const pack of workers) {
      const run = python(join(copy, pack, "worker"), dir, "import broker, worker_broker; assert broker.connection_parameters is worker_broker.connection_parameters");
      assert.equal(run.status, 0, `${pack}/worker/broker.py does not find worker-common/worker_broker.py in the packaged form:\n${run.stderr}`);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a pack directory copied alone (without worker-common) fails loudly, not silently", () => {
  const { dir, copy } = packaged();
  try {
    rmSync(join(copy, "worker-common"), { recursive: true });
    const run = python(join(copy, workers[0], "worker"), dir, "import broker");
    assert.notEqual(run.status, 0);
    assert.match(run.stderr, /worker_broker/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
