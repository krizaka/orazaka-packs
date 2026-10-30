// profile-photo-check (krizaka/orazaka-packs): the manifest, the blueprint, the worker and the ruleset say the same thing,
// and the promises of the README are checked, not remembered.
import test from "node:test";
import assert from "node:assert/strict";
import { assertLinksResolve } from "./blueprint-links.mjs";
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../profile-photo-check/", import.meta.url).pathname;
const text = (p) => readFileSync(`${root}${p}`, "utf8");
const pack = text("pack.yaml");
const blueprint = JSON.parse(text("studios/profile-photo-check/blueprint.json"));
const worker = text("worker/worker.yaml");
const ruleset = JSON.parse(text("rules/profile-photo/2026-10-17.json"));
const steps = blueprint.definition.steps;

test("every capability the blueprint uses is contributed here or is a core one", () => {
  const contributed = [...pack.matchAll(/^    - key: (orazaka\.[a-z.]+)$/gm)].map((m) => m[1]);
  assert.deepEqual(contributed.sort(), ["orazaka.photo.profile.assess", "orazaka.photo.profile.inspect"]);
  for (const s of steps)
    assert.ok(contributed.includes(s.featureKey) || s.featureKey.startsWith("orazaka.core."), s.featureKey);
});

test("each routing key of the pack is drained by the worker's bindings, which live in worker.yaml only", () => {
  assert.match(worker, /- "job\.photo\.\*"/);
  for (const key of ["job.photo.inspect", "job.photo.assess"]) assert.ok(pack.includes(`routingKey: ${key}`));
  assert.match(pack, /name: orazaka-worker-photo\n\s+bindings:\n\s+- "job\.photo\.\*"/);
});

test("a step input only reads inputs the Studio declares and steps that come before it", () =>
  assertLinksResolve(blueprint));

test("the vision step runs once per photo and cannot fail the whole check", () => {
  const look = steps.find((s) => s.id === "look");
  assert.equal(look.featureKey, "orazaka.core.media.vision");
  assert.equal(look.forEach, "{{inputs.photos}}");
  assert.equal(look.onError, "SKIP");
  assert.ok(look.maxParallel <= 2, "the Mac's vision budget is the scarce resource");
});

test("the prompt asks for JSON only, three booleans, no description, no name, and false when unsure", () => {
  const prompt = steps.find((s) => s.id === "look").inputs.prompt;
  for (const must of [
    "ONE JSON object",
    "appears_under_18",
    "text_or_contact_overlay",
    "screenshot_or_photo_of_screen",
    "Do not describe",
    "Do not name anyone",
    "If unsure, answer false",
  ])
    assert.ok(prompt.includes(must), must);
  for (const field of ruleset.look.checks.map((c) => c.field))
    assert.ok(prompt.includes(field), `ruleset field ${field} is asked`);
});

test("the pack is sensitive, guarded, a lone Studio, and carries no product word", () => {
  assert.match(pack, /^regulatoryClass: SENSITIVE$/m);
  assert.match(pack, /^scopeGuard:/m);
  assert.doesNotMatch(pack, /^catalog:/m);
  const walk = (dir) =>
    readdirSync(dir, { withFileTypes: true }).flatMap((d) =>
      d.isDirectory()
        ? d.name === "models" || d.name === "__pycache__" || d.name === ".venv"
          ? []
          : walk(`${dir}${d.name}/`)
        : [`${dir}${d.name}`],
    );
  for (const file of walk(root).filter((f) => /\.(py|yaml|json)$/.test(f))) {
    const body = readFileSync(file, "utf8").replace(/^\s*#.*$/gm, ""); // a header comment may say who it was written for
    assert.doesNotMatch(body, /yomizaka|akinaza/i, `${file}: a pack names no product`);
  }
});

test("the thresholds lean to not accusing and the models' licences allow commercial use", () => {
  assert.ok(ruleset.recognizer.mismatchCosine < ruleset.recognizer.sameCosine);
  assert.ok(ruleset.recognizer.mismatchCosine <= 0.3);
  const lock = JSON.parse(text("worker/models.lock.json"));
  for (const m of Object.values(lock.models)) {
    assert.ok(["MIT", "Apache-2.0"].includes(m.license));
    assert.match(m.sha256, /^[0-9a-f]{64}$/);
  }
  assert.ok(ruleset.limits.includes("NO_CELEBRITY_RECOGNITION"));
});

test("the Studio is worded in both languages", () => {
  for (const lang of ["en", "fr"]) assert.match(text(`i18n/${lang}.yaml`), /^  profile-photo-check:\n    label:/m);
});

test("the counts are the caller's: they default in the schema, they are not baked into the rules", () => {
  const props = blueprint.inputSchema.properties;
  assert.deepEqual([props.minPhotos.default, props.maxPhotos.default, props.minFacePhotos.default], [4, 6, 2]);
  assert.equal(Object.keys(ruleset).includes("minPhotos"), false);
});
