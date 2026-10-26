import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import YAML from "yaml";

const root = fileURLToPath(new URL("..", import.meta.url));
const schema = JSON.parse(readFileSync(join(root, "pack.schema.json"), "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validate = ajv.compile(schema);

function assertManifest(raw, path) {
  let manifest;
  try {
    manifest = YAML.parse(raw);
  } catch (error) {
    assert.fail(`${path}: invalid YAML: ${error.message}`);
  }
  if (!validate(manifest)) {
    const errors = validate.errors
      .map((error) => `${error.instancePath || "/"} ${error.message}`)
      .join("; ");
    assert.fail(`${path} violates pack.schema.json: ${errors}`);
  }
}

const packs = readdirSync(root, { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && existsSync(join(root, entry.name, "pack.yaml")))
  .map((entry) => entry.name)
  .sort();

test("manifest discovery is not empty", () => {
  assert.ok(packs.length > 0);
});

for (const pack of packs) {
  test(`${pack}/pack.yaml validates against pack.schema.json`, () => {
    const path = `${pack}/pack.yaml`;
    assertManifest(readFileSync(join(root, path), "utf8"), path);
  });
}

const validManifest = {
  apiVersion: "orazaka.dev/v1",
  key: "test-pack",
  version: "1.0.0",
  studios: [{
    key: "test-studio",
    profession: "Testing",
    iconKey: "sparkles",
    pricing: "FREE",
    entitlementKey: "studio.test-studio",
    blueprint: "blueprints/test.json",
  }],
};

test("the validator accepts compliant YAML, including flow mappings and quoted scalars", () => {
  assertManifest(YAML.stringify(validManifest, { collectionStyle: "flow" }), "fixture/pack.yaml");
});

for (const [name, change, diagnostic] of [
  ["required fields", (pack) => { delete pack.apiVersion; }, /required property 'apiVersion'/],
  ["constants", (pack) => { pack.apiVersion = "orazaka.dev/v2"; }, /\/apiVersion.*constant/],
  ["types", (pack) => { pack.studios[0].sortWeight = "first"; }, /\/studios\/0\/sortWeight.*integer/],
  ["enums", (pack) => { pack.studios[0].status = "LIVE"; }, /\/studios\/0\/status.*allowed values/],
  ["patterns", (pack) => { pack.version = "latest"; }, /\/version.*pattern/],
  ["additional properties", (pack) => { pack.studios[0].unknown = true; }, /\/studios\/0.*additional properties/],
  ["array bounds", (pack) => { pack.studios = []; }, /\/studios.*fewer than 1/],
  ["numeric bounds", (pack) => {
    pack.requires = { workers: [{ name: "test-worker", bindings: ["job.test.run"], concurrency: 0 }] };
  }, /\/requires\/workers\/0\/concurrency.*>= 1/],
  ["conditional requirements", (pack) => { pack.studios[0].pricing = "PAID"; }, /required property 'catalog'/],
  ["conditional exclusions", (pack) => {
    pack.kind = "TOOLKIT";
    pack.regulatoryClass = "REGULATED";
  }, /\/regulatoryClass.*NOT be valid/],
]) {
  test(`schema validation rejects invalid ${name} with the manifest and property path`, () => {
    const manifest = structuredClone(validManifest);
    change(manifest);
    assert.throws(() => assertManifest(YAML.stringify(manifest), "fixture/pack.yaml"), (error) => {
      assert.match(error.message, /fixture\/pack\.yaml violates pack\.schema\.json:/);
      assert.match(error.message, diagnostic);
      return true;
    });
  });
}

test("schema validation reports all violations without coercing or removing data", () => {
  const manifest = structuredClone(validManifest);
  manifest.version = 1;
  manifest.studios[0].status = "LIVE";
  manifest.unknown = true;
  assert.throws(() => assertManifest(YAML.stringify(manifest), "fixture/pack.yaml"), (error) => {
    assert.match(error.message, /\/version.*string/);
    assert.match(error.message, /\/studios\/0\/status.*allowed values/);
    assert.match(error.message, /additional properties/);
    return true;
  });
});

for (const raw of ["key: [unterminated", "key: first\nkey: duplicate\n"]) {
  test(`invalid YAML is refused with its manifest path: ${JSON.stringify(raw)}`, () => {
    assert.throws(() => assertManifest(raw, "fixture/pack.yaml"), /fixture\/pack\.yaml: invalid YAML:/);
  });
}

test("CI installs locked dependencies and runs the manifest gate on every pull request", () => {
  const workflow = YAML.parse(readFileSync(join(root, ".github/workflows/ci.yml"), "utf8"));
  assert.ok(Object.hasOwn(workflow.on, "pull_request"));
  assert.equal(workflow.on.pull_request, null);
  const job = workflow.jobs["schema-tests"];
  assert.equal(job.if, undefined);
  // `npm ci --ignore-scripts`: locked, and no dependency's install script runs in CI.
  const install = job.steps.findIndex((step) => /^npm ci(\s|$)/.test(step.run ?? ""));
  const run = job.steps.findIndex((step) => step.run === "npm test");
  assert.ok(install >= 0 && run > install, "npm ci must precede npm test");
});
