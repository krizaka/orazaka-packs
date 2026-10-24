// ADR-089 §1 (orazaka-packs#129): the kinds of document are pack data. The Python suite
// (document-validation/worker/test_identify.py) tests what `identify` does with them; this one tests the data's
// shape, with the JSON schema the files declare, and the seam to the pack manifest.
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import YAML from "yaml";

const root = fileURLToPath(new URL("..", import.meta.url));
const kindsDir = join(root, "document-validation", "kinds");
const schema = JSON.parse(readFileSync(join(kindsDir, "kind.schema.json"), "utf8"));
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);
const kindFiles = readdirSync(kindsDir).filter((n) => n.endsWith(".json") && n !== "kind.schema.json");
const load = (name) => JSON.parse(readFileSync(join(kindsDir, name), "utf8"));

test("every kind file validates against kinds/kind.schema.json", () => {
  assert.ok(kindFiles.length >= 8, "the first kinds of ADR-089 §1 are shipped");
  for (const name of kindFiles) {
    assert.ok(validate(load(name)), `${name}: ${JSON.stringify(validate.errors)}`);
  }
});

test("the schema refuses a kind without signals, a status outside the closed list and an unknown key", () => {
  const good = load("qc-visit-notice.json");
  for (const bad of [
    { ...good, signals: [good.signals[0]] },
    { ...good, status: "BETA" },
    { ...good, invented: true },
    { ...good, declaredAs: ["BAIL"] },
    { ...good, signals: [{ ...good.signals[0], weight: 0 }, good.signals[1]] },
  ]) {
    assert.equal(validate(bad), false);
  }
});

test("a kind is named by its file, and every fixture it lists exists", () => {
  for (const name of kindFiles) {
    const kind = load(name);
    assert.equal(`${kind.kindId}.json`, name);
    for (const fixture of kind.fixtures) {
      assert.ok(existsSync(join(kindsDir, fixture.file)), `${name}: missing ${fixture.file}`);
      assert.ok(fixture.file.startsWith(`fixtures/${kind.kindId}/`), `${name}: a fixture lives under its kind`);
    }
    assert.ok(kind.fixtures.some((f) => f.expect === "MATCH") && kind.fixtures.some((f) => f.expect === "NO_MATCH"), `${name}: a pass and a fail fixture`);
  }
});

test("a PROMOTED kind names a shipped ruleset and a KNOWN one names none", () => {
  for (const name of kindFiles) {
    const kind = load(name);
    if (kind.status === "PROMOTED") assert.ok(existsSync(join(root, "document-validation", "rulesets", kind.ruleset)), `${name}: no ruleset ${kind.ruleset}`);
    if (kind.status === "KNOWN") assert.equal(kind.ruleset, null, name);
  }
});

test("the pack declares the identify capability on the routing key its worker serves", () => {
  const pack = YAML.parse(readFileSync(join(root, "document-validation", "pack.yaml"), "utf8"));
  const capability = pack.requires.capabilities.find((c) => c.key === "orazaka.validation.document.identify");
  assert.ok(capability, "orazaka.validation.document.identify");
  assert.equal(capability.routingKey, "job.validation.identify");
  assert.ok(pack.requires.workers.some((w) => w.bindings.includes("job.validation.*")), "the validation worker drains job.validation.*");
});

test("no kind quotes a real template: the fixtures are marked fictional", () => {
  for (const name of kindFiles) {
    for (const fixture of load(name).fixtures.filter((f) => f.expect === "MATCH")) {
      const text = readFileSync(join(kindsDir, fixture.file), "utf8");
      assert.match(text, /démonstration|demonstration|fictif|fictive|fictional/i, `${fixture.file}: say it is fictional`);
    }
  }
});
