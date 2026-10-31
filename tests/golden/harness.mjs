import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv from "ajv";

const ajv = new Ajv({ strict: false, validateFormats: false, allErrors: true });
const operators = ["equals", "includes", "nonEmpty", "type", "atLeast"];
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const canonical = (value) =>
  Array.isArray(value)
    ? value.map(canonical)
    : value && typeof value === "object"
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, canonical(value[key])]),
        )
      : value;

export function assertOutput(output, assertions) {
  for (const assertion of assertions) {
    assert.ok(Array.isArray(assertion.path) && assertion.path.length > 0, "an assertion needs an output path");
    const ops = Object.keys(assertion).filter((key) => key !== "path");
    assert.ok(ops.length === 1 && operators.includes(ops[0]), "exactly one supported assertion operator is required");
    let actual = output;
    for (const part of assertion.path) {
      if (typeof actual === "string") actual = JSON.parse(actual);
      assert.ok(
        actual !== null && typeof actual === "object" && Object.hasOwn(actual, part),
        `missing output path ${assertion.path.join(".")}`,
      );
      actual = actual[part];
    }
    const label = assertion.path.join(".");
    switch (ops[0]) {
      case "equals":
        assert.deepEqual(actual, assertion.equals, label);
        break;
      case "includes":
        assert.ok((typeof actual === "string" || Array.isArray(actual)) && actual.includes(assertion.includes), label);
        break;
      case "atLeast":
        assert.ok(Number.isFinite(actual) && Number.isFinite(assertion.atLeast) && actual >= assertion.atLeast, label);
        break;
      case "nonEmpty":
        assert.equal(assertion.nonEmpty, true, "nonEmpty must be true");
        assert.ok(
          (typeof actual === "string" && actual.trim().length > 0) || (Array.isArray(actual) && actual.length > 0),
          label,
        );
        if (typeof actual === "string")
          assert.doesNotMatch(actual, /^\s*\{\{[^}]*\}\}\s*$/, `${label}: unresolved output template`);
        break;
      case "type": {
        assert.ok(
          ["object", "array", "string", "number", "boolean"].includes(assertion.type),
          "unknown assertion type",
        );
        const type = Array.isArray(actual) ? "array" : actual === null ? "null" : typeof actual;
        assert.equal(type, assertion.type, label);
        break;
      }
    }
  }
}

export function validateCases(fixture, blueprint) {
  assert.ok(typeof fixture.studio === "string" && fixture.studio.length > 0, "missing Studio key");
  assert.ok(
    Array.isArray(fixture.cases) && fixture.cases.length >= 3 && fixture.cases.length <= 5,
    `${fixture.studio}: ship 3–5 golden cases`,
  );
  const validate = ajv.compile(blueprint.inputSchema);
  const ids = new Set();
  const inputs = new Set();
  const outputKeys = blueprint.definition.outputs.map((output) => output.key);
  for (const c of fixture.cases) {
    assert.match(c.id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    assert.ok(!ids.has(c.id), `duplicate case ${c.id}`);
    ids.add(c.id);
    assert.ok(validate(c.input), `${fixture.studio}/${c.id}: ${ajv.errorsText(validate.errors)}`);
    // Property order must not let an identical input count as a second case.
    const signature = JSON.stringify(canonical(c.input));
    assert.ok(!inputs.has(signature), `${c.id}: duplicate input`);
    inputs.add(signature);
    assert.ok(
      c.expected && typeof c.expected === "object" && !Array.isArray(c.expected),
      `${c.id}: expected output object required`,
    );
    for (const key of Object.keys(c.expected))
      assert.ok(outputKeys.includes(key), `${c.id}: undeclared expected output ${key}`);
    assert.ok(Array.isArray(c.assertions) && c.assertions.length > 0, `${c.id}: output assertions required`);
    for (const a of c.assertions) {
      assert.ok(outputKeys.includes(a.path?.[0]), `${c.id}: assertion does not address a declared output`);
    }
    assertOutput(c.expected, c.assertions);
  }
}

export function checkRatchet(current, previous) {
  assert.ok(Array.isArray(current) && Array.isArray(previous), "exceptions must be arrays");
  assert.equal(new Set(current).size, current.length, "duplicate exceptions");
  for (const key of current) assert.ok(previous.includes(key), `golden exceptions may only shrink: ${key}`);
}

export function discover(root) {
  const exceptions = readJson(join(root, "golden-ratchet.json")).exceptions;
  assert.ok(Array.isArray(exceptions) && new Set(exceptions).size === exceptions.length, "invalid golden exceptions");
  const known = new Set();
  const suites = [];
  let assets;
  const resolveAssets = (input) => {
    if (Array.isArray(input)) return input.map(resolveAssets);
    if (input && typeof input === "object") {
      return Object.fromEntries(Object.entries(input).map(([key, value]) => [key, resolveAssets(value)]));
    } else if (typeof input === "string" && /^(asset|base64):/.test(input)) {
      assets ??= readJson(join(root, "tests", "golden", "assets.json"));
      const name = input.split(":")[1];
      assert.ok(Object.hasOwn(assets, name), `missing synthetic asset ${input}`);
      return assets[name].base64;
    }
    return input;
  };
  for (const pack of readdirSync(root)
    .sort()
    .filter((name) => existsSync(join(root, name, "pack.yaml")))) {
    const studios = join(root, pack, "studios");
    const covered = [];
    for (const studio of readdirSync(studios).sort()) {
      const blueprintFile = join(studios, studio, "blueprint.json");
      if (!existsSync(blueprintFile)) continue;
      const key = `${pack}/${studio}`;
      known.add(key);
      const fixtureFile = join(root, pack, "tests", "golden", `${studio}.json`);
      if (exceptions.includes(key)) {
        assert.ok(!existsSync(fixtureFile), `${key}: remove the now-covered exception`);
        continue;
      }
      assert.ok(existsSync(fixtureFile), `${key}: missing tests/golden/${studio}.json`);
      const fixture = readJson(fixtureFile);
      const blueprint = readJson(blueprintFile);
      assert.equal(fixture.studio, studio);
      assert.equal(blueprint.definition.studioKey, studio);
      validateCases(fixture, blueprint);
      const resolvedInputs = fixture.cases.map((c) => JSON.stringify(canonical(resolveAssets(c.input))));
      assert.equal(
        new Set(resolvedInputs).size,
        fixture.cases.length,
        `${studio}: asset aliases do not count as distinct inputs`,
      );
      covered.push(studio);
      suites.push({ ...fixture, pack, studio, blueprint });
    }
    assert.ok(
      covered.length > 0 || exceptions.some((key) => key.startsWith(`${pack}/`)),
      `${pack}: no golden coverage`,
    );
  }
  for (const key of exceptions) assert.ok(known.has(key), `stale golden exception ${key}`);
  return suites;
}
