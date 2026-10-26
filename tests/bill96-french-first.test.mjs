// bill96-french-first (krizaka/orazaka-packs#15): not a certified translation, terminology sources named, no legal term invented,
// statutes referred to by name only, the firm glossary reusable by the other Studios.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import YAML from "yaml";

const root = new URL("../bill96-french-first/", import.meta.url).pathname;
const read = (p) => readFileSync(`${root}${p}`, "utf8");
const manifest = YAML.parse(read("pack.yaml"));
const sources = JSON.parse(read("sources.json"));
const STUDIOS = ["french-version", "bilingual-consistency-check", "french-first-copy", "firm-glossary"];
const blueprints = Object.fromEntries(STUDIOS.map((k) => [k, JSON.parse(read(`studios/${k}/blueprint.json`))]));
const steps = Object.values(blueprints).flatMap((bp) => bp.definition.steps);

test("the manifest ships the four Studios in the business-compliance shelf, sensitive, guarded, priced", () => {
  assert.deepEqual(manifest.studios.map((s) => s.key), STUDIOS);
  assert.equal(manifest.catalog.categoryKey, "business-compliance");
  assert.equal(manifest.regulatoryClass, "SENSITIVE");
  for (const term of ["traduction certifiée", "certified translation", "legal advice"]) assert.ok(manifest.scopeGuard.refusedTerms.includes(term), term);
  assert.ok(manifest.pricing.priceCents > 0 && manifest.pricing.includedCredits > 0);
});

test("every prompt opens with the not-certified sentence in both languages and asks for a professional review", () => {
  for (const step of steps) {
    assert.match(step.inputs.prompt, /Traduction automatisée non certifiée/, `${step.id}: French sentence`);
    assert.match(step.inputs.prompt, /Automated, uncertified translation/, `${step.id}: English sentence`);
    assert.match(step.inputs.prompt, /reviewed by a professional|à faire réviser par un professionnel/, step.id);
  }
});

test("terminology sources are named and a legal term is never invented, nor a statute quoted", () => {
  for (const step of steps) {
    assert.match(step.inputs.prompt, /OQLF/, `${step.id}: names its terminology source`);
    assert.match(step.inputs.prompt, /Never invent a legal term/, step.id);
    assert.match(step.inputs.prompt, /Never quote a statute/, step.id);
  }
  for (const ref of sources.references) assert.deepEqual(Object.keys(ref).sort(), ["citation", "id", "sections", "title", "usedFor"]);
  assert.equal(sources.verifiedBy, null);
});

test("the firm glossary is the plain form the other Studios take as their glossary input", () => {
  assert.match(blueprints["firm-glossary"].definition.steps[0].inputs.prompt, /English \| French \| Source \| Note/);
  for (const k of ["french-version", "french-first-copy"]) {
    assert.ok(blueprints[k].inputSchema.properties.glossary, `${k} takes the glossary`);
    assert.ok(JSON.stringify(blueprints[k].definition.steps).includes("{{inputs.glossary}}"), `${k} uses it`);
  }
});

test("the consistency check never decides which version prevails", () => {
  assert.match(blueprints["bilingual-consistency-check"].definition.steps[1].inputs.prompt, /Do not decide which version prevails/);
});

test("French leads where Bill 96 asks it: the copy Studio writes French first, English kept after", () => {
  assert.match(blueprints["french-first-copy"].definition.steps[0].inputs.prompt, /write the French first, then keep the English equivalent/);
});

test("no public wording of a legal rule, no escrow, no hosted model", () => {
  const all = JSON.stringify([manifest, blueprints]) + read("i18n/en.yaml") + read("i18n/fr.yaml");
  assert.doesNotMatch(all, /règles juridiques|legal rules|séquestre|escrow/i);
  assert.doesNotMatch(JSON.stringify(blueprints), /gpt-|claude-|gemini-/i);
});

test("the catalogue and the golden cases cover the same Studios", () => {
  for (const lang of ["en", "fr"]) assert.deepEqual(Object.keys(YAML.parse(read(`i18n/${lang}.yaml`)).studios).sort(), [...STUDIOS].sort());
  assert.deepEqual(readdirSync(`${root}tests/golden`).sort(), STUDIOS.map((k) => `${k}.json`).sort());
});
