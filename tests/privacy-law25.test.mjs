// privacy-law25 (krizaka/orazaka-packs#14): the four Studios prepare, a person validates; sources are references, never quoted text;
// the wording is the technical-tool wording (no « legal rules », no escrow); every output says it is a draft.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import YAML from "yaml";

const root = new URL("../privacy-law25/", import.meta.url).pathname;
const read = (p) => readFileSync(`${root}${p}`, "utf8");
const manifest = YAML.parse(read("pack.yaml"));
const sources = JSON.parse(read("sources.json"));
const STUDIOS = ["personal-information-inventory", "privacy-impact-assessment", "confidentiality-incident", "privacy-governance-policy"];
const blueprints = Object.fromEntries(STUDIOS.map((k) => [k, JSON.parse(read(`studios/${k}/blueprint.json`))]));
const prompts = (bp) => bp.definition.steps.map((s) => s.inputs.prompt);

test("the manifest ships the four Studios, in the business-compliance shelf, sensitive and guarded", () => {
  assert.deepEqual(manifest.studios.map((s) => s.key), STUDIOS);
  assert.equal(manifest.catalog.categoryKey, "business-compliance");
  assert.equal(manifest.regulatoryClass, "SENSITIVE");
  assert.ok(manifest.scopeGuard.refusedTerms.includes("legal advice") && manifest.scopeGuard.refusedTerms.includes("avis juridique"));
  assert.ok(manifest.pricing.priceCents > 0 && manifest.pricing.includedCredits > 0);
  for (const s of manifest.studios) assert.equal(s.pricing, "PAID");
});

test("every Studio's prompts make the output a draft that a person validates, in both languages", () => {
  for (const key of ["personal-information-inventory", "privacy-impact-assessment", "confidentiality-incident"]) {
    for (const prompt of prompts(blueprints[key])) {
      assert.match(prompt, /not legal advice/, `${key}: English validation sentence`);
      assert.match(prompt, /pas un avis juridique/, `${key}: French validation sentence`);
      assert.match(prompt, /You prepare, you never decide/, key);
    }
  }
  const policy = prompts(blueprints["privacy-governance-policy"]);
  assert.match(policy[0], /pas un avis juridique/);
  assert.match(policy[1], /not legal advice/);
});

test("the person in charge decides: decisions, dates and signatures are left empty, never filled", () => {
  assert.match(prompts(blueprints["privacy-impact-assessment"])[1], /EMPTY/);
  assert.match(prompts(blueprints["confidentiality-incident"])[0], /the person in charge decides/);
  assert.match(prompts(blueprints["confidentiality-incident"])[2], /Leave every decision, date and signature EMPTY/);
});

test("sources are cited by reference only: the prompts forbid quoting a section and sources.json holds no text", () => {
  for (const bp of Object.values(blueprints)) for (const step of bp.definition.steps.filter((x) => x.id !== "policyEn")) assert.match(step.inputs.prompt, /Never reproduce the wording of a section|never by quoting a text/i, `${step.id}: cite by reference only`);
  for (const ref of sources.references) {
    assert.deepEqual(Object.keys(ref).sort(), ["citation", "id", "sections", "title", "usedFor"]);
  }
  assert.match(sources.note, /not pinned here/);
  assert.equal(sources.verifiedBy, null, "no reference is claimed as verified by a lawyer before the lawyer has answered");
});

test("no public wording of a legal rule, no escrow, no hosted model", () => {
  const all = JSON.stringify([manifest, blueprints]) + read("i18n/en.yaml") + read("i18n/fr.yaml");
  assert.doesNotMatch(all, /règles juridiques|legal rules|séquestre|escrow/i);
  assert.doesNotMatch(JSON.stringify(blueprints), /gpt-|claude-|gemini-/i);
});

test("the incident Studio reads three criteria and drafts no notice when they do not point to serious injury", () => {
  const [assess, , notices] = prompts(blueprints["confidentiality-incident"]);
  for (const criterion of ["sensitivity", "anticipated consequences", "likelihood"]) assert.match(assess, new RegExp(criterion));
  assert.match(notices, /If the reading is NO, write only one line saying that no notice is drafted/);
});

test("the catalogue names the same Studios in English and French", () => {
  const en = YAML.parse(read("i18n/en.yaml")), fr = YAML.parse(read("i18n/fr.yaml"));
  assert.deepEqual(Object.keys(en.studios).sort(), [...STUDIOS].sort());
  assert.deepEqual(Object.keys(fr.studios).sort(), [...STUDIOS].sort());
});

test("each Studio has its golden cases", () => {
  assert.deepEqual(readdirSync(`${root}tests/golden`).sort(), STUDIOS.map((k) => `${k}.json`).sort());
});
