// One door per capability (orazaka-packs#138). A blueprint step names a capability by its feature key, and that key must
// exist somewhere the platform reads it: declared by the step's own pack (`requires.capabilities`), in the engine's own
// namespace (`orazaka.core.*`, ADR-037), or one of the few registry rows the job service seeds itself
// (tests/contracts/platform-capabilities.json, each with its source). A key that is none of these is a step nothing runs.
// The other way round, a pack never declares a key in the engine's namespace: it would be a second door to an engine
// capability. The engine's check keys are called with the contract tests/contracts/orazaka-core-checks.json, nothing else.
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import YAML from "yaml";

const ROOT = new URL("..", import.meta.url).pathname;
const contract = (name) => JSON.parse(readFileSync(join(ROOT, "tests", "contracts", name), "utf8"));
const platform = Object.keys(contract("platform-capabilities.json").keys);
const checks = contract("orazaka-core-checks.json");

export function packs(root = ROOT) {
  return readdirSync(root, { withFileTypes: true })
    .filter((d) => d.isDirectory() && existsSync(join(root, d.name, "pack.yaml")))
    .map((d) => {
      const manifest = YAML.parse(readFileSync(join(root, d.name, "pack.yaml"), "utf8"));
      const studios = (manifest.studios ?? []).filter((s) => s.blueprint).map((s) => ({
        key: s.key,
        blueprint: JSON.parse(readFileSync(join(root, d.name, s.blueprint), "utf8")),
      }));
      return { name: d.name, declared: (manifest.requires?.capabilities ?? []).map((c) => c.key), studios };
    });
}

const stepsOf = (steps) => (steps ?? []).flatMap((s) => [s, ...stepsOf(s.steps)]);

/** The problems of one pack: an undeclared key in a blueprint, or a pack key in the engine's namespace. */
export function featureKeyProblems(pack, known = platform) {
  const problems = [];
  for (const key of pack.declared) if (key.startsWith("orazaka.core.")) problems.push(`${pack.name} declares ${key}: the orazaka.core namespace is the engine's`);
  for (const studio of pack.studios) {
    for (const step of stepsOf(studio.blueprint.definition?.steps)) {
      const key = step.featureKey;
      if (key === undefined) continue; // TRANSFORM, APPROVAL, CONNECTOR: no capability
      if (pack.declared.includes(key) || key.startsWith("orazaka.core.") || known.includes(key)) continue;
      problems.push(`${pack.name}/${studio.key} step ${step.id} names ${key}, which no pack, engine or registry row declares`);
    }
  }
  return problems;
}

/** The problems of a step calling an engine check: an unknown check key, an input outside the contract, a missing one. */
export function checkStepProblems(step, steps) {
  if (!String(step.featureKey).startsWith("orazaka.core.checks.")) return [];
  if (!Object.hasOwn(checks.featureKeys, step.featureKey)) return [`step ${step.id} names ${step.featureKey}, which is not an engine check`];
  const problems = [];
  const inputs = Object.keys(step.inputs ?? {});
  for (const key of inputs) if (!Object.hasOwn(checks.inputs, key)) problems.push(`step ${step.id} passes '${key}', which the engine's checks do not read`);
  for (const key of Object.keys(checks.inputs)) if (!inputs.includes(key)) problems.push(`step ${step.id} does not pass '${key}'`);
  for (const other of steps) {
    for (const value of Object.values(other.inputs ?? {}).concat(other.condition ?? [])) {
      for (const m of String(value).matchAll(/\{\{steps\.([A-Za-z0-9_]+)\.([A-Za-z0-9]+)/g)) {
        if (m[1] === step.out && !checks.outputs.includes(m[2])) problems.push(`step ${other.id} reads ${m[1]}.${m[2]}, which the engine's checks do not answer`);
      }
    }
  }
  return problems;
}

test("every feature key of every blueprint is its pack's, the engine's or a seeded registry row; no pack declares an engine key", () => {
  const all = packs();
  assert.ok(all.length >= 10, `found ${all.length} packs`);
  assert.deepEqual(all.flatMap((p) => featureKeyProblems(p)), []);
});

test("a step that calls an engine check passes exactly the contract's inputs and reads only its outputs", () => {
  const callers = [];
  for (const pack of packs()) {
    for (const studio of pack.studios) {
      const steps = stepsOf(studio.blueprint.definition?.steps);
      for (const step of steps) {
        if (String(step.featureKey).startsWith("orazaka.core.checks.")) callers.push(step.id);
        assert.deepEqual(checkStepProblems(step, steps), [], `${pack.name}/${studio.key}`);
      }
    }
  }
  assert.ok(callers.length >= 2, "the tenant screening calls the engine's checks");
});

test("the rule catches what it is for", () => {
  const pack = (declared, steps) => ({ name: "p", declared, studios: [{ key: "s", blueprint: { definition: { steps } } }] });
  assert.equal(featureKeyProblems(pack([], [{ id: "a", featureKey: "orazaka.screening.courts.check" }])).length, 1, "an undeclared key");
  assert.equal(featureKeyProblems(pack(["orazaka.core.checks.credit"], [])).length, 1, "a pack shadowing the engine");
  assert.equal(featureKeyProblems(pack(["orazaka.x.y"], [{ id: "a", featureKey: "orazaka.x.y" }, { id: "b", featureKey: "orazaka.core.chat.completion" }, { id: "c", kind: "APPROVAL" }])).length, 0);
  assert.equal(featureKeyProblems(pack([], [{ id: "n", steps: [{ id: "m", featureKey: "orazaka.nowhere.at.all" }] }])).length, 1, "a nested step");
  assert.equal(featureKeyProblems(pack([], [{ id: "a", featureKey: "orazaka.studio.media.compose" }])).length, 0, "a seeded registry row");
  const call = { id: "c", featureKey: "orazaka.core.checks.credit", out: "c", inputs: { subject: "{{inputs.subject}}", consentedPurposes: "{{inputs.consentedPurposes}}" } };
  assert.deepEqual(checkStepProblems(call, [call]), []);
  assert.equal(checkStepProblems({ ...call, featureKey: "orazaka.core.checks.criminal" }, [call]).length, 1, "an unknown check");
  assert.equal(checkStepProblems({ ...call, inputs: { ...call.inputs, plan: "x" } }, [call]).length, 1, "an input outside the contract");
  assert.equal(checkStepProblems({ ...call, inputs: { subject: "x" } }, [call]).length, 1, "a missing input");
  const reader = { id: "r", inputs: { x: "{{steps.c.lastName}}" } };
  assert.equal(checkStepProblems(call, [call, reader]).length, 1, "a field the engine never answers");
});

test("every registry row of the exceptions says where it is seeded", () => {
  for (const [key, source] of Object.entries(contract("platform-capabilities.json").keys)) {
    assert.match(key, /^orazaka\.[a-z]+(\.[a-z]+)+$/);
    assert.ok(!key.startsWith("orazaka.core."), `${key} needs no exception`);
    assert.match(source, /^krizaka\/[a-z-]+ /, key);
  }
});
