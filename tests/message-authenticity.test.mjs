// message-authenticity: the manifest, the blueprint, the worker and the ruleset say the same thing, and the promises of the
// README are checked: a signal never a verdict, no score, nothing that writes.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../message-authenticity/", import.meta.url).pathname;
const text = (p) => readFileSync(`${root}${p}`, "utf8");
const pack = text("pack.yaml");
const blueprint = JSON.parse(text("studios/message-authenticity/blueprint.json"));
const ruleset = JSON.parse(text("rules/message-authenticity/2026-10-17.json"));
const results = JSON.parse(text("calibration/results.json"));

test("one capability, drained by the worker declared in worker.yaml; the blueprint uses it and only it", () => {
  assert.match(pack, /key: orazaka\.message\.authenticity\.read/);
  assert.match(pack, /routingKey: job\.authenticity\.read/);
  assert.match(text("worker/worker.yaml"), /- "job\.authenticity\.\*"/);
  assert.deepEqual(
    blueprint.definition.steps.map((s) => s.featureKey),
    ["orazaka.message.authenticity.read"],
  );
});

test("no generative step: a model that writes has nothing to do in an authenticity check", () => {
  for (const s of blueprint.definition.steps) assert.ok(!/chat\.completion|generate|script/.test(s.featureKey));
  assert.doesNotMatch(
    text("worker/authenticity_worker.py") + text("worker/classifier.py"),
    /\.generate\(|CausalLM|Seq2SeqLM/,
  );
});

test("sensitive, guarded against writing for anyone, a lone Studio, no product word", () => {
  assert.match(pack, /^regulatoryClass: SENSITIVE$/m);
  assert.match(pack, /écris à ma place/);
  assert.doesNotMatch(pack, /^catalog:/m);
  const walk = (d) =>
    readdirSync(d, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory()
        ? e.name === ".venv" || e.name === "__pycache__"
          ? []
          : walk(`${d}${e.name}/`)
        : [`${d}${e.name}`],
    );
  for (const f of walk(root).filter((f) => /\.(py|yaml|json)$/.test(f) && !f.includes("calibration/")))
    assert.doesNotMatch(readFileSync(f, "utf8").replace(/^\s*#.*$/gm, ""), /yomizaka|akinaza/i, f);
});

test("the ruleset: a pinned open model, thresholds in order, the limits said", () => {
  assert.match(ruleset.classifier.revision, /^[0-9a-f]{40}$/);
  assert.equal(ruleset.classifier.license, "Apache-2.0");
  for (const [lang, t] of Object.entries(ruleset.languages)) assert.ok(t.mid < t.high && t.high < 1, lang);
  assert.ok(ruleset.minWords >= 6);
  for (const must of [
    "CAN_BE_WRONG",
    "UNRELIABLE_ON_SHORT_TEXTS",
    "UNRELIABLE_ON_NON_NATIVE_AND_FRENCH_WRITING",
    "A_SIGNAL_NEVER_A_VERDICT",
  ])
    assert.ok(ruleset.limits.includes(must));
});

test("the calibration is recorded, honest and not flattering: false « HIGH » is zero and the ruleset says what that costs", () => {
  assert.equal(results.set.human.en, 80);
  for (const lang of ["en", "fr"]) assert.equal(results.holdout[lang].high_test.false_positive.split("/")[0], "0");
  assert.match(ruleset.revisionNote, /minority of generated texts/);
  assert.match(text("README.md"), /small minority\s+of generated texts/);
});

test("no raw human text is committed — only the manifest of hashes", () => {
  const manifest = JSON.parse(text("calibration/human-manifest.json"));
  for (const items of Object.values(manifest)) for (const it of items) assert.match(it.sha256, /^[0-9a-f]{64}$/);
  assert.equal(readdirSync(`${root}calibration/`).includes("human.json"), false);
});

test("the Studio is worded in both languages", () => {
  for (const lang of ["en", "fr"]) assert.match(text(`i18n/${lang}.yaml`), /^  message-authenticity:\n    label:/m);
});
