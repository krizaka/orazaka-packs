// ADR-089 §3 (krizaka/orazaka-ai-engine#82): the data of the derivation — the contract of the propose step, the recorded
// answers of the visit notice and one planted proposal per reason of vet. The engine vets (RuleProposalVet); the Python
// suite (document-validation/worker/test_derivation.py) proves with the worker's own code that each planted case fails
// for its reason. This one tests the shape of the data against the schema it declares.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const dir = join(root, "document-validation", "derivation");
const load = (...parts) => JSON.parse(readFileSync(join(dir, ...parts), "utf8"));
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(load("proposed-ruleset.schema.json"));
const planted = readdirSync(join(dir, "planted"))
  .filter((n) => n.endsWith(".json"))
  .map((name) => ({ name, ...load("planted", name) }));

// The reasons of orazaka-ai-engine VetReason, in its order.
const REASONS = [
  "SCHEMA_INVALID",
  "REGEX_INVALID",
  "REGEX_MATCHES_EMPTY",
  "QUOTE_NOT_IN_ARTICLE",
  "UNSUPPORTED_NUMBER",
  "FIXTURES_INDISTINCT",
  "SUBJECT_MISSING",
  "LAW_VERSION_UNKNOWN",
  "OVER_RULE_LIMIT",
];

test("every recorded answer of the visit notice is in the contract of the propose step", () => {
  const { answers } = load("qc-visit-notice.fr.answers.json");
  assert.deepEqual(Object.keys(answers), ["1931", "1932", "1933"]);
  for (const [ref, answer] of Object.entries(answers)) {
    assert.ok(validate(answer), `${ref}: ${JSON.stringify(validate.errors)}`);
    for (const rule of answer.rules) {
      assert.deepEqual([...new Set(rule.law.map((b) => b.ref))], [ref], `${rule.ruleId} cites its own article only`);
    }
  }
  const outside = load("qc-visit-notice.fr.outside-corpus.answer.json");
  assert.ok(validate(outside), JSON.stringify(validate.errors));
});

test("every reason of vet has its planted proposal, and nothing else is planted", () => {
  assert.deepEqual([...new Set(planted.map((p) => p.reason))].sort(), [...REASONS].sort());
  for (const p of planted) {
    assert.ok(p.why && p.why.length > 10, `${p.name} says why it is planted`);
    assert.equal(p.rules.filter((r) => r.ruleId === p.plantedRuleId).length, 1, `${p.name} plants one rule`);
  }
});

test("only the SCHEMA_INVALID plant breaks the contract: the other reasons are vet's, not the schema's", () => {
  for (const p of planted) {
    const ok = validate({ rules: p.rules });
    assert.equal(ok, p.reason !== "SCHEMA_INVALID", `${p.name}: ${JSON.stringify(validate.errors)}`);
  }
});

test("the contract refuses a numeric check, a rule with no law and a JUDGMENT rule that is not ADVISORY", () => {
  const sound = load("qc-visit-notice.fr.answers.json").answers["1931"].rules[0];
  const judgment = load("qc-visit-notice.fr.answers.json").answers["1933"].rules[0];
  for (const bad of [
    { ...sound, check: { type: "NUMERIC_MIN", pattern: "(\\d+)" } },
    { ...sound, law: [] },
    { ...sound, law: [{ ...sound.law[0], contentHash: "abc" }] },
    { ...sound, fixtures: { pass: [], fail: ["x"] } },
    { ...judgment, severity: "BLOCKING" },
    { ...sound, ruleId: "qc visit 1" },
  ]) {
    assert.equal(validate({ rules: [bad] }), false, JSON.stringify(bad).slice(0, 80));
  }
});
