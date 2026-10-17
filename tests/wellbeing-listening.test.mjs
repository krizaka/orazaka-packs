// The wellbeing pack's listening moment (Yororis, ADR-076): the data a client draws a presence from, and the
// proof that the crisis guard's cues catch what a person says aloud. Pure data, no engine: the folding below is
// SafetyInterceptor.fold's (NFD, combining marks dropped, lower case) and a term matches when the turn contains it.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const read = (p) => readFileSync(join(root, "wellbeing", p), "utf8");
const pack = read("pack.yaml");
const listening = JSON.parse(read("listening/listening.json"));
const fixtures = JSON.parse(read("listening/risk-fixtures.json"));

const fold = (v) => v.normalize("NFD").replace(/\p{M}+/gu, "").toLowerCase();

/** The crisisTerms of pack.yaml: the list items under `crisisTerms:` until the next key. */
export function crisisTerms(yaml) {
  const out = [];
  let inside = false;
  for (const line of yaml.split("\n")) {
    if (/^  crisisTerms:/.test(line)) inside = true;
    else if (inside && /^  \S/.test(line)) inside = false;
    else if (inside) {
      const m = line.match(/^    - (.+?)\s*$/);
      if (m) out.push(m[1]);
    }
  }
  return out;
}

const terms = crisisTerms(pack);
const caught = (text) => terms.some((t) => fold(text).includes(fold(t)));

test("the pack still declares its original crisis terms and the spoken ones", () => {
  assert.ok(terms.includes("suicide") && terms.includes("en finir"));
  assert.ok(terms.length >= 35, `only ${terms.length} terms`);
  assert.equal(new Set(terms).size, terms.length, "a term is declared twice");
});

test("an apostrophe cue is written with both apostrophes", () => {
  for (const t of terms.filter((x) => /['’]/.test(x))) {
    const other = t.includes("'") ? t.replace(/'/g, "’") : t.replace(/’/g, "'");
    assert.ok(terms.includes(other), `${t} has no twin with the other apostrophe`);
  }
});

test("every risk fixture is caught, in both languages", () => {
  assert.ok(fixtures.mustTrigger.length >= 10);
  for (const { text, locale } of fixtures.mustTrigger) assert.ok(caught(text), `${locale}: not caught: ${text}`);
  assert.ok(fixtures.mustTrigger.some((f) => f.locale === "en") && fixtures.mustTrigger.some((f) => f.locale.startsWith("fr")));
});

test("an ordinary spoken turn does not raise the crisis panel", () => {
  for (const { text, locale } of fixtures.mustNotTrigger) assert.ok(!caught(text), `${locale}: false alarm: ${text}`);
});

test("the guard cannot be walked around by an accent or a capital", () => {
  assert.ok(caught("ENVIE DE MOURIR"));
  assert.ok(caught("j'ai envie de mourir".normalize("NFD")));
});

test("the crisis reply and the lines are untouched: the fixed text is the pack's, never generated", () => {
  assert.match(pack, /Je m'arrête là, parce que ce que vous venez d'écrire compte plus que l'exercice en cours\./);
  for (const region of ["CA-QC", "CA", "FR"]) assert.match(pack, new RegExp(`^    ${region}:`, "m"));
  assert.match(pack, /1 866 APPELLE/);
  assert.match(pack, /Info-Social 811/);
});

test("a presence is stylised, says it is an AI, and has a catalogued voice for each language", () => {
  assert.equal(listening.face.photorealistic, false);
  assert.equal(listening.face.ofARealPerson, false);
  assert.equal(listening.face.aiMark, "permanent");
  assert.equal(listening.face.lipSync.source, "ENERGY");
  assert.ok(listening.presences.length >= 3);
  const ids = new Set();
  for (const p of listening.presences) {
    assert.ok(!ids.has(p.id), `duplicate presence ${p.id}`);
    ids.add(p.id);
    assert.equal(p.portrait.kind, "stylised");
    for (const lang of ["fr-FR", "en"]) {
      const voice = p.voices[lang];
      assert.ok(voice && listening.voices[voice], `${p.id}: no catalogued voice for ${lang}`);
      assert.equal(listening.voices[voice].locale, lang);
    }
  }
});

test("every voice names a licence, and a copyleft one is flagged for review", () => {
  for (const [name, v] of Object.entries(listening.voices)) {
    assert.ok(v.licence, `${name}: no licence`);
    if (/AGPL|GPL/.test(v.licence)) assert.ok(v.licenceReview, `${name}: copyleft without a review note`);
  }
  assert.equal(listening.ear.stt.model, "whisper-base");
  assert.ok(listening.ear.stt.maxSeconds <= 30);
});

test("the ear and the mouth are Orazaka's: the door is the voice turn under an installation", () => {
  assert.equal(listening.door.endpoint, "/api/v1/voice/turns");
  assert.equal(listening.door.under, "installation");
  assert.equal(listening.conversation.systemPrompt, "safety.systemPrompt");
  assert.match(pack, /^  systemPrompt: >-/m);
  assert.equal(listening.conversation.closesWith, "session-summary");
  assert.match(pack, /key: session-summary/);
  assert.ok(listening.conversation.never.includes("a phone number given by the model"));
});

test("the words of the data stay clear of the care vocabulary", () => {
  const never = /\b(therap|psycholog|patient|clinic|diagnos(?!is\b)|treatment|session(?!-)|coach)/i;
  const strings = JSON.stringify({ ...listening, voices: undefined, conversation: { ...listening.conversation, never: undefined } });
  assert.ok(!never.test(strings), `care vocabulary in listening.json: ${strings.match(never)?.[0]}`);
});
