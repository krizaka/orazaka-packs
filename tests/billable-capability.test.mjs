// Billing is declared, never inferred (orazaka-packs#162): every capability a pack contributes names what it bills as, NONE
// included for a step that only orchestrates or presents. An empty value used to reach the job service as a null and fail
// the registration with a 500.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import YAML from "yaml";

const root = new URL("../", import.meta.url).pathname;
const schema = JSON.parse(readFileSync(`${root}pack.schema.json`, "utf8"));
const allowed = schema.$defs.capability.properties.billableCapability.enum;
const packs = readdirSync(root).filter((d) => existsSync(`${root}${d}/pack.yaml`));

test("the schema offers NONE beside the billable capabilities", () => {
  assert.ok(allowed.includes("NONE"));
});

test("no handler of any pack leaves billableCapability empty", () => {
  assert.ok(packs.length > 0);
  for (const dir of packs) {
    const pack = YAML.parse(readFileSync(`${root}${dir}/pack.yaml`, "utf8"));
    for (const cap of pack.requires?.capabilities ?? []) {
      assert.ok(cap.billableCapability, `${dir}: ${cap.key} leaves billableCapability empty (declare NONE if it is not billable)`);
      assert.ok(allowed.includes(cap.billableCapability), `${dir}: ${cap.key}: ${cap.billableCapability}`);
    }
  }
});

test("a capability declared NONE carries no billable unit", () => {
  for (const dir of packs) {
    const pack = YAML.parse(readFileSync(`${root}${dir}/pack.yaml`, "utf8"));
    for (const cap of pack.requires?.capabilities ?? []) {
      if (cap.billableCapability === "NONE") assert.equal(cap.billableUnit, undefined, `${dir}: ${cap.key}`);
    }
  }
});
