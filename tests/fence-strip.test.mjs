// The model's answer may come in a ```json fence; the worker strips it with a linear scan (Sonar S8786: a regex
// `\s*```$` backtracks quadratically on long runs of spaces).
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

const root = new URL("../", import.meta.url).pathname;

const strip = (pack, text) => {
  const code = `import importlib.util,sys\ns=importlib.util.spec_from_file_location('r','${root}${pack}/worker/rules.py')\nm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nsys.stdout.write(m._strip_fences(sys.argv[1]))`;
  const run = spawnSync("python3", ["-c", code, text], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stderr);
  return run.stdout;
};

for (const pack of ["media-safety", "profile-photo-check"]) {
  test(`${pack}: opening and closing fences are dropped, the JSON is kept`, () => {
    assert.equal(strip(pack, '```json\n{"a": 1}\n```'), '{"a": 1}');
    assert.equal(strip(pack, '{"a": 1}'), '{"a": 1}');
  });

  test(`${pack}: a long run of spaces is stripped in linear time`, () => {
    const started = Date.now();
    strip(pack, `{"a": 1}${" ".repeat(200000)}x`);
    assert.ok(Date.now() - started < 3000);
  });
}
