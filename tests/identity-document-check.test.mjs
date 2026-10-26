// identity-document-check (krizaka/orazaka-packs#22): the manifest, the blueprint, the worker and the ruleset say the same thing,
// and the promises of the README are checked, not remembered.
import test from "node:test";
import assert from "node:assert/strict";
import { assertLinksResolve } from "./blueprint-links.mjs";
import { readFileSync } from "node:fs";

const root = new URL("../identity-document-check/", import.meta.url).pathname;
const text = (p) => readFileSync(`${root}${p}`, "utf8");
const pack = text("pack.yaml");
const blueprint = JSON.parse(text("studios/identity-document-check/blueprint.json"));
const worker = text("worker/worker.yaml");
const ruleset = JSON.parse(text("rules/identity-document/2026-10-26.json"));
const steps = blueprint.definition.steps;
const readme = text("README.md");

test("the one capability the blueprint uses is the pack's, drained by the worker's binding", () => {
  const contributed = [...pack.matchAll(/^    - key: (orazaka\.[a-z.]+)$/gm)].map((m) => m[1]);
  assert.deepEqual(contributed, ["orazaka.identity.document.verify"]);
  for (const s of steps) assert.ok(contributed.includes(s.featureKey) || s.featureKey.startsWith("orazaka.core."), s.featureKey);
  assert.match(worker, /- "job\.identity\.\*"/);
  assert.ok(pack.includes("routingKey: job.identity.verify"));
  assert.match(pack, /name: orazaka-worker-identity\n\s+bindings:\n\s+- "job\.identity\.\*"/);
});

test("a step input only reads inputs the Studio declares and steps that come before it", () => assertLinksResolve(blueprint));

test("the worker reads the pack's own output fields and the verification passes every input the capability declares", () => {
  const verify = steps.find((s) => s.featureKey === "orazaka.identity.document.verify");
  const declared = [...pack.matchAll(/^          (\w+): \{ type: /gm)].map((m) => m[1]);
  for (const key of Object.keys(verify.inputs)) assert.ok(declared.includes(key), `capability does not declare ${key}`);
  for (const output of blueprint.definition.outputs) assert.match(output.from, /^\{\{steps\.verdict\.(reportJson|status)\}\}$/);
});

test("the vision step is one strict JSON reading that transcribes and never identifies or judges", () => {
  const read = steps.find((s) => s.id === "read");
  assert.equal(read.featureKey, "orazaka.core.media.vision");
  assert.equal(read.onError, "FAIL", "without a reading there is nothing to verify");
  const prompt = read.inputs.prompt;
  for (const must of ["ONE JSON object", "mrzLines", "character by character", "never correct a character", "signals", "quality", "confidence", "Do not describe the person", "Do not say who the person is", "Do not judge whether the document is genuine"]) {
    assert.ok(prompt.includes(must), must);
  }
  for (const kind of ruleset.signalKinds) assert.ok(prompt.includes(kind), `the prompt names the signal ${kind}`);
  for (const kind of ruleset.qualityKinds) assert.ok(prompt.includes(kind), `the prompt names the quality ${kind}`);
  for (const type of ruleset.documentTypes) assert.ok(prompt.includes(type), `the prompt names the type ${type}`);
});

test("the upload is an image, nothing in the manifest identifies a person or names a hosted model", () => {
  const doc = blueprint.inputSchema.properties.document;
  assert.equal(doc.format, "asset:image");
  assert.equal(doc.contentMediaType, "image/*");
  assert.match(pack, /^regulatoryClass: SENSITIVE$/m);
  assert.match(pack, /^scopeGuard:/m);
  assert.doesNotMatch(pack, /^catalog:/m);
  assert.doesNotMatch(JSON.stringify(blueprint), /gpt-|claude-|gemini-/i);
});

test("the ruleset says what the pack cannot do, and the README repeats it", () => {
  for (const limit of ruleset.limits) assert.ok(readme.includes(limit), `README names the limit ${limit}`);
  assert.match(readme, /identifies no one/i);
  assert.match(readme, /PDF/);
});

test("the CI runs every Python suite of the worker", () => {
  const ci = readFileSync(new URL("../.github/workflows/ci.yml", import.meta.url), "utf8");
  for (const suite of ["test_mrz.py", "test_rules.py", "test_worker.py"]) assert.ok(ci.includes(`python ${suite}`), suite);
  assert.ok(ci.includes("python test_worker_loop.py"));
});
