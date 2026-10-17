// media-safety: the manifest, the blueprint, the worker and the ruleset agree, and the safety check FAILS CLOSED.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../media-safety/", import.meta.url).pathname;
const text = (p) => readFileSync(`${root}${p}`, "utf8");
const pack = text("pack.yaml");
const blueprint = JSON.parse(text("studios/media-safety/blueprint.json"));
const ruleset = JSON.parse(text("rules/media-safety/2026-10-17.json"));
const steps = blueprint.definition.steps;

test("every capability the blueprint uses is contributed here or is a core one", () => {
  const mine = [...pack.matchAll(/^    - key: (orazaka\.[a-z.]+)$/gm)].map((m) => m[1]);
  assert.deepEqual(mine, ["orazaka.safety.media.assess"]);
  for (const s of steps) assert.ok(mine.includes(s.featureKey) || s.featureKey.startsWith("orazaka.core."), s.featureKey);
  assert.match(text("worker/worker.yaml"), /- "job\.safety\.\*"/);
});

test("a safety check never skips a model step: onError is FAIL everywhere (an unreadable run is not an approval)", () => {
  for (const s of steps) assert.notEqual(s.onError, "SKIP", s.id);
  assert.ok(steps.filter((s) => s.onError === "FAIL").length === steps.length);
});

test("the vision prompt asks JSON only, three booleans, no description and « true » when unsure; the ruleset reads the same fields", () => {
  const prompt = steps.find((s) => s.id === "look").inputs.prompt;
  for (const must of ["ONE JSON object", "Do not describe", "Do not name anyone", "If unsure, answer true"]) assert.ok(prompt.includes(must), must);
  for (const c of ruleset.look.checks) assert.ok(prompt.includes(c.field), c.field);
  const read = steps.find((s) => s.id === "read").inputs.prompt;
  for (const c of ruleset.listen.checks) assert.ok(read.includes(c.field), c.field);
  assert.ok(read.includes("If unsure, answer true"));
});

test("the audio steps only run when there is audio, and the assessment waits for all of them", () => {
  for (const id of ["listen", "read"]) assert.equal(steps.find((s) => s.id === id).condition, "{{inputs.audio}} is not null");
  assert.deepEqual(steps.find((s) => s.id === "assess").dependsOn.sort(), ["look", "read"]);
});

test("sensitive, a lone Studio, identifies no one, carries no product word, fails closed in its limits", () => {
  assert.match(pack, /^regulatoryClass: SENSITIVE$/m);
  assert.match(pack, /identify this person/);
  assert.doesNotMatch(pack, /^catalog:/m);
  assert.ok(ruleset.limits.includes("FAILS_CLOSED_WHEN_UNREADABLE"));
  const walk = (d) => readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? (e.name === ".venv" || e.name === "__pycache__" ? [] : walk(`${d}${e.name}/`)) : [`${d}${e.name}`]));
  for (const f of walk(root).filter((f) => /\.(py|yaml|json)$/.test(f))) assert.doesNotMatch(readFileSync(f, "utf8").replace(/^\s*#.*$/gm, ""), /yasakia/i, f);
});

test("the Studio is worded in both languages", () => {
  for (const lang of ["en", "fr"]) assert.match(text(`i18n/${lang}.yaml`), /^  media-safety:\n    label:/m);
});
