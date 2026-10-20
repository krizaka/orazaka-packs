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

test("each presence has its own voice in each language", () => {
  for (const lang of ["fr-FR", "en"]) assert.equal(new Set(listening.presences.map((p) => p.voices[lang])).size, listening.presences.length, `two presences share a ${lang} voice`);
});

test("every voice names a licence, and a copyleft one is flagged for review", () => {
  for (const [name, v] of Object.entries(listening.voices)) {
    assert.ok(v.licence, `${name}: no licence`);
    if (/AGPL|GPL|non-commercial/.test(v.licence)) assert.ok(v.licenceReview, `${name}: copyleft without a review note`);
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

// ── The English path (2026-10-18): one prompt and one fixed reply that serve both languages ──
const block = (key) => {
  const m = pack.match(new RegExp(`^  ${key}: >-\\n((?:    .*\\n|\\n)+)`, "m"));
  return m ? m[1].replace(/\n\s*/g, " ").trim() : "";
};

test("the system prompt tells the model to answer in the person's language, in both languages", () => {
  const prompt = block("systemPrompt");
  assert.match(prompt, /If they speak English, answer in English from start to\s+finish|answer in English from start to finish/);
  assert.match(prompt, /si elle t'écrit ou te parle en anglais, tu réponds en anglais/);
  assert.match(prompt, /I'm an AI\. I'm neither a therapist nor an emergency service/);
  assert.match(prompt, /You never diagnose/);
  assert.match(prompt, /never give a phone number/);
});

test("the English half of the prompt keeps every refusal of the French half", () => {
  const en = block("systemPrompt").split("You are an AI presence.")[1] ?? "";
  for (const rule of [/never diagnose/, /medication/, /never interpret the person's mood/, /never promise an improvement/, /never present yourself as a person/, /never give a phone number/, /one question at a time/]) assert.match(en, rule);
  assert.ok(!/\d{3}[- ]?\d{3,4}|\b988\b|\b811\b/.test(en), "the prompt never carries a number");
});

test("the fixed crisis reply speaks both languages: the original French first, then the English, then the region's line", () => {
  const reply = block("response");
  assert.ok(reply.startsWith("Je m'arrête là, parce que ce que vous venez d'écrire compte plus que l'exercice en cours."));
  assert.match(reply, /Des personnes formées écoutent, gratuitement et tout de suite :/);
  assert.match(reply, /I'm stopping here, because what you just wrote matters more than the exercise we were doing\./);
  assert.match(reply, /Trained people listen, for free and right away:$/);
  assert.ok(reply.indexOf("Je m'arrête") < reply.indexOf("I'm stopping here"));
  assert.ok(!/\d{3}/.test(reply), "the reply carries no number: the line is the region's, verified at its source");
});

test("the English reply says no more than the French one: no advice, no diagnosis, no promise", () => {
  const en = block("response").split("I'm stopping here")[1] ?? "";
  assert.ok(!/(diagnos|treat|therap|medic|will be fine|get better|everything will)/i.test(en), en);
});

test("the review note says the English is not yet read by a person", () => {
  assert.match(pack, /traduction anglaise à relire par une personne/);
});

// ── session-summary 1.0.1: what the person keeps follows their language and invents nothing ──
test("session-summary 1.0.1 writes in the person's language and never quotes what was not said", () => {
  const bp = JSON.parse(readFileSync(join(root, "wellbeing/studios/session-summary/blueprint.json"), "utf8"));
  // 1.1.0 introduced it; later versions keep it (a bump for the field words, 1.2.0, changed nothing here)
  assert.match(bp.version, /^1\.[1-9]\d*\.\d+$/);
  assert.equal(bp.definition.version, bp.version);
  const prompt = bp.definition.steps[0].inputs.prompt;
  assert.match(prompt, /LANGUAGE: write EVERY value in the language of code \{\{inputs\.locale\}\}/);
  assert.match(prompt, /never quote a sentence that does not appear word for word/);
  assert.match(prompt, /tu n'interprètes pas son humeur/, "the earlier refusals are kept");
  assert.match(prompt, /aucun diagnostic/);
  assert.deepEqual(bp.definition.outputs[0].schema.required, ["themes", "whatHelped", "smallStep", "bringToTherapist", "locale"]);
});
