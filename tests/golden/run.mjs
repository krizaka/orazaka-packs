import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { discover } from "./harness.mjs";
import { runCase } from "./stack.mjs";

const { values } = parseArgs({ options: { config: { type: "string" }, pack: { type: "string" } } });
assert.ok(values.config, "Usage: npm run golden:run -- --config /absolute/path/stack.json [--pack pack-key]");
const configPath = resolve(values.config);
const config = JSON.parse(readFileSync(configPath, "utf8"));
config.token = readFileSync(resolve(dirname(configPath), config.tokenFile), "utf8").trim();
config.assets = JSON.parse(
  readFileSync(
    config.assetsFile ? resolve(dirname(configPath), config.assetsFile) : new URL("./assets.json", import.meta.url),
    "utf8",
  ),
);
const suites = discover(fileURLToPath(new URL("../..", import.meta.url))).filter(
  (suite) => !values.pack || suite.pack === values.pack,
);
assert.ok(suites.length > 0, "no matching golden suites");
let failed = 0;
for (const suite of suites) {
  for (const golden of suite.cases) {
    const label = `${suite.pack}/${suite.studio}/${golden.id}`;
    try {
      await runCase(suite, golden, config);
      console.log(`ok ${label}`);
    } catch (error) {
      // Assertion messages may contain outputs; only report the case and error class.
      console.error(`FAIL ${label} (${error.name})`);
      failed++;
    }
  }
}
console.log(`${failed ? "FAILED" : "all green"} — ${failed} failure(s)`);
process.exitCode = failed ? 1 : 0;
