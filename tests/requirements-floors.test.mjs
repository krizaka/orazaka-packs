// OpenSSF Scorecard (Vulnerabilities) resolves an open range like `torch>=2.2` to its lowest version, so a floor below
// the first patched release reports every advisory of the versions in between. Floors never go under these minimums.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const MINIMUM = { torch: [2, 13], transformers: [5, 10] }; // first releases with no OSV advisory (2026-10-19)
const root = new URL("..", import.meta.url).pathname;
const parse = (v) => v.split(".").map(Number);
const atLeast = (a, b) => a[0] > b[0] || (a[0] === b[0] && (a[1] ?? 0) >= b[1]);

test("requirements floors stay at or above the patched releases", () => {
  let seen = 0;
  for (const pack of readdirSync(root, { withFileTypes: true })) {
    const file = join(root, pack.name, "requirements.txt");
    if (!pack.isDirectory() || !existsSync(file)) continue;
    for (const line of readFileSync(file, "utf8").split("\n")) {
      const m = /^([A-Za-z0-9_.-]+)\s*(?:>=|==|~=)\s*([0-9][0-9.]*)/.exec(line.trim());
      if (!m || !MINIMUM[m[1].toLowerCase()]) continue;
      seen++;
      assert.ok(atLeast(parse(m[2]), MINIMUM[m[1].toLowerCase()]), `${pack.name}: ${line.trim()} is below ${MINIMUM[m[1].toLowerCase()].join(".")}`);
    }
  }
  assert.ok(seen >= 2, "torch and transformers are declared by message-authenticity");
});
