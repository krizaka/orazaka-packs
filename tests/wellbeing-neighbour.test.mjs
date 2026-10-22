// The wellbeing pack's system prompt in its neighbour persona (Yororis pivot of 2026-10-21, krizaka/yororis#99): « le voisin »,
// light alternative hypotheses, « Je ne sais pas, mais tu trouveras », encyclopedic anecdotes and light humour, no medical or
// therapeutic vocabulary, no advice, a warm close after the turn limit. The crisis behaviour is untouched (tests/wellbeing-listening
// and tests/wellbeing-consent keep it). No model runs here: the prompt must ask for each behaviour in both languages, and the
// examples in listening/neighbour-fixtures.json (what a reply obeying it looks like) must themselves keep to the rules.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const read = (p) => readFileSync(join(root, "wellbeing", p), "utf8");
const pack = read("pack.yaml");
const fixtures = JSON.parse(read("listening/neighbour-fixtures.json"));

const block = (key) => {
  const m = pack.match(new RegExp(`^  ${key}: >-\\n((?:    .*\\n|\\n)+)`, "m"));
  return m ? m[1].replace(/\n\s*/g, " ").trim() : "";
};
const prompt = block("systemPrompt");
const [fr, en] = prompt.split('You are "the neighbour"');

// The Yororis lexicon (company/prompts-yororis.md §2.1): none of these in a text, ours or a model's.
const FORBIDDEN = [/th[ée]rap/i, /\bpsy/i, /soigne|\bsoins?\b|\bcare\b|\bcure\b|gu[ée]ri/i, /\btreat/i, /traitement/i, /diagnos/i, /clinic/i, /m[ée]dic/i, /\bpatient/i, /s[ée]ance|\bsession/i, /coach/i, /bien-?[êe]tre|wellbeing/i];
const sentences = (t) => t.split(/(?<=[.!?…])\s+/).filter(Boolean);
const ADVICE = /\b(tu devrais|tu dois|il faut que tu|essaie de|you should|you must|you need to|try to|make sure you)\b/i;

test("the prompt is the neighbour's, in both languages, and says it is an AI", () => {
  assert.ok(fr && en, "a French half and an English half");
  assert.match(fr, /Tu es « le voisin » : un voisin de quartier bienveillant, une IA/);
  assert.match(en, /a kind neighbourhood neighbour, an AI/);
});

test("the three behaviours are asked for, in French and in English", () => {
  assert.match(fr, /autre piste avec\s+légèreté/);
  assert.match(fr, /Peut-être qu'il y a une autre piste\.\.\./);
  assert.match(fr, /« Je ne sais pas, mais tu trouveras »/);
  assert.match(fr, /anecdote factuelle et vérifiable/);
  assert.match(fr, /vanne\s+légère/);
  assert.match(en, /another angle lightly/);
  assert.match(en, /Maybe there is another angle\.\.\./);
  assert.match(en, /"I don't know, but\s+you'll find it"/);
  assert.match(en, /factual, checkable anecdote/);
  assert.match(en, /light joke/);
});

test("it never asks for advice, an analysis of the mood, a claim of health, or an invented fact", () => {
  assert.match(fr, /Tu ne donnes aucun conseil et tu ne dis jamais à la personne quoi faire/);
  assert.match(fr, /tu n'analyses ni son humeur ni ses émotions/);
  assert.match(fr, /Tu n'inventes jamais un fait/);
  assert.match(en, /You give no advice and never tell the person what to do/);
  assert.match(en, /never analyse their mood or feelings/);
  assert.match(en, /Never invent a fact/);
});

test("it closes warmly after the turn limit, without a new question and without holding the person back", () => {
  assert.match(fr, /Quand le contexte te dit que c'est le\s+dernier échange/);
  assert.match(fr, /un mot\s+chaleureux et un au revoir, sans poser de nouvelle question/);
  assert.match(fr, /Tu ne\s+retiens jamais la personne/);
  assert.match(en, /When the context tells you this is the last exchange/);
  assert.match(en, /close with a warm word and a goodbye, with no new\s+question/);
  assert.match(en, /never hold the person back/);
});

test("the prompt carries no medical or therapeutic vocabulary, in either language", () => {
  for (const re of FORBIDDEN) {
    assert.ok(!re.test(fr), `${re} in the French half`);
    assert.ok(!re.test(en), `${re} in the English half`);
  }
  assert.ok(!/\d{3}[- ]?\d{3,4}|\b988\b|\b811\b/.test(prompt), "never a number");
});

test("the deterministic behaviours stay: the guards, the fixed crisis reply, the lines", () => {
  assert.match(pack, /^  crisisTerms:/m);
  assert.match(pack, /^scopeGuard:/m);
  assert.match(pack, /Je m'arrête là, parce que ce que vous venez d'écrire compte plus que l'exercice en cours\./);
  assert.match(pack, /1 866 APPELLE/);
  assert.match(pack, /^version: 1\.6\.0$/m, "the prompt changed: the pack's version moved");
});

const groups = ["loop", "askForTheAnswer", "lastExchange", "healthQuestion"];

test("each behaviour has a French and an English fixture", () => {
  for (const g of groups) {
    assert.ok(fixtures[g].some((f) => f.locale.startsWith("fr")), `${g}: no French fixture`);
    assert.ok(fixtures[g].some((f) => f.locale === "en"), `${g}: no English fixture`);
  }
});

test("every example reply is short, free of advice, of the care vocabulary and of numbers", () => {
  for (const g of groups) {
    for (const { locale, reply } of fixtures[g]) {
      assert.ok(sentences(reply).length <= 4, `${g}/${locale}: too long`);
      assert.ok(!ADVICE.test(reply), `${g}/${locale}: advice in the example`);
      assert.ok(!/\d{3}/.test(reply), `${g}/${locale}: a number in the example`);
      for (const re of FORBIDDEN) assert.ok(!re.test(reply), `${g}/${locale}: ${re} in the example`);
    }
  }
});

test("the examples show the behaviours: another angle, « I don't know, but you'll find it » + an anecdote, a warm close", () => {
  for (const { locale, reply } of fixtures.loop) assert.match(reply, locale === "en" ? /Maybe there is another angle\.\.\./ : /Peut-être qu'il y a une autre piste\.\.\./);
  for (const { locale, reply } of fixtures.askForTheAnswer) {
    assert.match(reply, locale === "en" ? /^I don't know, but you'll find it\./ : /^Je ne sais pas, mais tu trouveras\./);
    assert.ok(sentences(reply).length >= 2, "an anecdote or a joke follows");
  }
  for (const { locale, reply, context } of fixtures.lastExchange) {
    assert.match(context, locale === "en" ? /Last exchange/ : /Dernier échange/);
    assert.match(reply, locale === "en" ? /goodbye|safe travels|pleasure/i : /bonne route|plaisir/i);
    assert.ok(!reply.includes("?"), `${locale}: the close asks nothing`);
  }
  for (const { locale, reply } of fixtures.healthQuestion) assert.match(reply, locale === "en" ? /not my department/ : /pas mon rayon/);
});
