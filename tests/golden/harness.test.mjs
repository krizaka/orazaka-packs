import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { assertOutput, checkRatchet, discover, validateCases } from "./harness.mjs";

const blueprint = {
  inputSchema: { type: "object", required: ["text"], properties: { text: { type: "string", minLength: 1 } } },
  definition: { outputs: [{ key: "report", type: "JSON" }] },
};
const fixture = {
  studio: "example",
  cases: ["plain", "bilingual", "multiline"].map((id) => ({
    id, input: { text: id },
    expected: { report: { verdict: "PASS" } },
    assertions: [{ path: ["report", "verdict"], equals: "PASS" }],
  })),
};

test("goldens require three distinct, schema-valid inputs and non-vacuous output assertions", () => {
  validateCases(fixture, blueprint);
  for (const mutate of [
    (f) => f.cases.pop(),
    (f) => { f.cases[1].input = f.cases[0].input; },
    (f) => { f.cases[0].input.text = ""; },
    (f) => { f.cases[0].assertions = []; },
    (f) => { f.cases[0].assertions[0].path = ["missing"]; },
    (f) => { f.cases[0].expected.undeclared = "stale"; },
    (f) => { f.cases[0].expected.report.verdict = "FAIL"; },
  ]) {
    const invalid = structuredClone(fixture);
    mutate(invalid);
    assert.throws(() => validateCases(invalid, blueprint));
  }
});

test("assertions reject missing paths, changed verdicts, malformed JSON, and empty artifacts", () => {
  assertOutput({ report: '{"verdict":"PASS"}' }, fixture.cases[0].assertions);
  for (const output of [{}, { report: {} }, { report: "not JSON" }, { report: { verdict: "FAIL" } }]) {
    assert.throws(() => assertOutput(output, fixture.cases[0].assertions));
  }
  assert.throws(() => assertOutput({ image: "" }, [{ path: ["image"], nonEmpty: true }]));
  assert.throws(() => assertOutput({ image: "{{steps.image.url}}" }, [{ path: ["image"], nonEmpty: true }]));
  assertOutput({ explanation: "A template such as {{name}} is literal prose." }, [{ path: ["explanation"], nonEmpty: true }]);
  assert.throws(() => assertOutput({ report: { verdict: "PASS" } }, [{ path: ["report"], typo: true }]));
  assertOutput({ frames: 1 }, [{ path: ["frames"], atLeast: 1 }]);
  for (const frames of [0, "1", null]) {
    assert.throws(() => assertOutput({ frames }, [{ path: ["frames"], atLeast: 1 }]));
  }
});

test("the exceptions ratchet can only remove existing debt, never add or rename it", () => {
  checkRatchet(["legacy"], ["legacy", "retired"]);
  checkRatchet([], []);
  assert.throws(() => checkRatchet(["new"], []));
  assert.throws(() => checkRatchet(["new"], ["legacy"]));
  assert.throws(() => checkRatchet(["legacy", "legacy"], ["legacy"]));
});

test("discovery fails closed for a new pack, a missing Studio, and stale exceptions", () => {
  const root = mkdtempSync(join(tmpdir(), "pack-golden-"));
  try {
    const dir = join(root, "example", "studios", "example");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(root, "example", "pack.yaml"), "key: example\n");
    writeFileSync(join(dir, "blueprint.json"), JSON.stringify({
      ...blueprint, definition: { ...blueprint.definition, studioKey: "example" },
    }));
    writeFileSync(join(root, "golden-ratchet.json"), '{"exceptions":[]}');
    assert.throws(() => discover(root), /missing tests\/golden/);
    const golden = join(root, "example", "tests", "golden");
    mkdirSync(golden, { recursive: true });
    writeFileSync(join(golden, "example.json"), JSON.stringify(fixture));
    assert.equal(discover(root).length, 1);
    const invalidAsset = structuredClone(fixture);
    invalidAsset.cases[0].input.text = "asset:missing";
    mkdirSync(join(root, "tests", "golden"), { recursive: true });
    writeFileSync(join(root, "tests", "golden", "assets.json"), "{}");
    writeFileSync(join(golden, "example.json"), JSON.stringify(invalidAsset));
    assert.throws(() => discover(root), /missing synthetic asset/);
    invalidAsset.cases[1].input.text = "asset:alias";
    writeFileSync(join(root, "tests", "golden", "assets.json"), JSON.stringify({ missing: { base64: "same" }, alias: { base64: "same" } }));
    writeFileSync(join(golden, "example.json"), JSON.stringify(invalidAsset));
    assert.throws(() => discover(root), /aliases do not count/);
    writeFileSync(join(golden, "example.json"), JSON.stringify(fixture));
    writeFileSync(join(root, "golden-ratchet.json"), '{"exceptions":["removed/studio"]}');
    assert.throws(() => discover(root), /stale golden exception/);
    writeFileSync(join(root, "golden-ratchet.json"), '{"exceptions":["example/example"]}');
    assert.throws(() => discover(root), /remove the now-covered exception/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
