// A field with a known set of values is a choice, never typed text (Oussama, 2026-10-17: « il faut
// favoriser les listes déroulantes »). The set is either stated by the blueprint (`enum`, or `oneOf` of
// `const`) or fed by the catalogue (`x-options`, expanded by the Studio service from orazaka_models).
// A client that finds none of them would draw a text box where a person can type a model that does not exist.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const props = [];
for (const pack of readdirSync(root, { withFileTypes: true })) {
  const studios = join(root, pack.name, "studios");
  if (!pack.isDirectory() || !existsSync(studios)) continue;
  for (const s of readdirSync(studios)) {
    const file = join(studios, s, "blueprint.json");
    if (!existsSync(file)) continue;
    const bp = JSON.parse(readFileSync(file, "utf8"));
    for (const [key, def] of Object.entries(bp.inputSchema?.properties ?? {})) {
      props.push({ where: `${pack.name}/studios/${s}#${key}`, key, def });
    }
  }
}

/** Fields whose values are a known set, wherever they appear. */
const CLOSED = /(^model$|Model$|^voice$|^aspect$|^size$|^locale$|^language$|^platform$|^jurisdiction$|^category$|^status$)/;
/** The model categories orazaka_models carries and a form may be fed from. */
const MODEL_CATEGORIES = ["image", "video", "speech", "audio", "vision", "chat", "foley", "music"];

const isUpload = (def) => typeof def.format === "string" && def.format.startsWith("asset");
const isChoice = (def) =>
  isUpload(def) ||
  Array.isArray(def.enum) ||
  (Array.isArray(def.oneOf) && def.oneOf.every((o) => "const" in o)) ||
  def["x-options"]?.source === "models";

test("every field with a known set of values is a choice", () => {
  const typed = props.filter(({ key, def }) => CLOSED.test(key) && !isChoice(def)).map((p) => p.where);
  assert.deepEqual(typed, [], `typed where a list belongs: ${typed.join(", ")}`);
});

test("a catalogue-fed field names a real model category and carries no list of its own", () => {
  for (const { where, def } of props) {
    const options = def["x-options"];
    if (!options) continue;
    assert.equal(options.source, "models", `${where}: the only source is the model catalogue`);
    assert.ok(MODEL_CATEGORIES.includes(options.category), `${where}: unknown model category ${options.category}`);
    assert.equal(def.enum, undefined, `${where}: a hand-kept enum drifts from orazaka_models — let the catalogue feed it`);
    assert.equal(def.type, "string", `${where}: a model is a string`);
  }
});

test("a seed is a number with a random toggle, behind « more options »", () => {
  for (const { where, key, def } of props) {
    if (key !== "seed") continue;
    assert.equal(def["x-control"], "seed", `${where}: seed declares x-control: seed`);
    assert.equal(def["x-advanced"], true, `${where}: seed lives behind more options`);
  }
});

test("model and negative-prompt fields are advanced: most people never open them", () => {
  for (const { where, key, def } of props) {
    // The voice of speech synthesis and the model of video generation are the choices those Studios are about:
    // they stay in front.
    if (def["x-options"]?.category === "speech" || where.endsWith("video-generation#model")) continue;
    if (key === "model" || key === "negativePrompt") assert.equal(def["x-advanced"], true, `${where}: x-advanced`);
  }
});

// ── Every select says what it is, short, in English and in French (x-i18n) ──────────────────────────
// The catalogue feeds the models (orazaka_models, through the Studio service); the words of a field and of each
// of its choices live in the pack, in both languages, so a client never shows the blueprint's French on an
// English page and never needs a release to name a choice. A helper stays one line (≤ 140 characters); the long
// comparison of the models is drawn by the client from the catalogue's facts, never written in a helper.
const HELPER_MAX = 140;
const selects = props.filter(({ def }) => Array.isArray(def.enum) || def["x-options"]?.source === "models");

test("a select has at least one choice and a lowercase catalogue category", () => {
  assert.ok(selects.length >= 25, "the audit found the selects");
  for (const { where, def } of selects) {
    if (def.enum) assert.ok(def.enum.length >= 1, `${where}: an empty enum is an empty select`);
    const category = def["x-options"]?.category;
    if (category) assert.equal(category, category.toLowerCase(), `${where}: the catalogue's categories are lowercase (« CHAT » matched no model and drew an empty select)`);
  }
});

test("every select carries its words in English and French, with a helper of at most 140 characters", () => {
  for (const { where, def } of selects) {
    for (const lang of ["en", "fr"]) {
      const words = def["x-i18n"]?.[lang];
      assert.ok(words, `${where}: x-i18n.${lang} is missing`);
      assert.ok(words.title?.trim(), `${where}: ${lang} title`);
      assert.ok(words.description?.trim(), `${where}: ${lang} helper`);
      assert.ok(words.description.length <= HELPER_MAX, `${where}: ${lang} helper is ${words.description.length} characters, the maximum is ${HELPER_MAX}`);
      for (const value of def.enum ?? []) {
        assert.ok(words.options?.[value]?.trim(), `${where}: ${lang} label of « ${value} »`);
      }
      for (const [id, option] of Object.entries(def["x-options"] ? (words.options ?? {}) : {})) {
        assert.ok(option.label?.trim() && option.hint?.trim(), `${where}: ${lang} label and hint of ${id}`);
        assert.ok(option.hint.length <= 100, `${where}: ${lang} hint of ${id} is one line (≤ 100 characters)`);
      }
    }
    assert.ok((def.description ?? "").length <= HELPER_MAX, `${where}: the base helper (read by older clients) is ${(def.description ?? "").length} characters`);
  }
});

test("the models of a field are the same in both languages and their facts name only those models", () => {
  for (const { where, def } of selects) {
    if (!def["x-options"]) continue;
    const en = Object.keys(def["x-i18n"].en.options ?? {}).sort();
    const fr = Object.keys(def["x-i18n"].fr.options ?? {}).sort();
    assert.deepEqual(en, fr, `${where}: the same models are described in English and French`);
    for (const id of Object.keys(def["x-options"].facts ?? {})) assert.ok(en.includes(id), `${where}: facts for ${id}, which has no words`);
  }
});

test("a long description of the models is never written into a helper", () => {
  for (const { where, def } of selects) {
    assert.doesNotMatch(def.description ?? "", /GPU|i\/s|[0-9]{3,4}×[0-9]{3,4}/, `${where}: resolutions and GPUs belong to the client's comparison, fed by the catalogue`);
  }
});

// ── Every field speaks both languages, not only the selects (x-i18n) ────────────────────────────────
// « Vos données », « Votre question » and a dozen helpers still showed French on the English page (dev, 2026-10-20):
// a free-text, numeric, boolean or file field is a field like the others. Each carries a title and a helper
// (≤ 140 characters) in English and French; a free-text field carries the example it shows (`placeholder`).
const isFreeText = ({ def }) =>
  (def.type === "string" || def.type === "array") &&
  !Array.isArray(def.enum) &&
  !def["x-options"] &&
  !def["x-control"] &&
  !isUpload(def) &&
  !(def.type === "array" && def.items && isUpload(def.items));

test("every field of every Studio has its title and helper in English and French, at most 140 characters", () => {
  assert.ok(props.length >= 80, "the audit found the fields");
  for (const { where, def } of props) {
    for (const lang of ["en", "fr"]) {
      const words = def["x-i18n"]?.[lang];
      assert.ok(words, `${where}: x-i18n.${lang} is missing`);
      assert.ok(words.title?.trim(), `${where}: ${lang} title`);
      assert.ok(words.description?.trim(), `${where}: ${lang} helper`);
      assert.ok(words.description.length <= HELPER_MAX, `${where}: ${lang} helper is ${words.description.length} characters, the maximum is ${HELPER_MAX}`);
    }
  }
});

test("a free-text field carries the example it shows, in English and French", () => {
  const typed = props.filter(isFreeText);
  assert.ok(typed.length >= 25, "the audit found the free-text fields");
  for (const { where, def } of typed) {
    for (const lang of ["en", "fr"]) {
      assert.ok(def["x-i18n"]?.[lang]?.placeholder?.trim(), `${where}: ${lang} placeholder`);
    }
  }
});

test("the English words are English: no French article or accent in an English title, helper or example", () => {
  const french = /[àâçéèêëîïôûùœ]|\b(vos|votre|le|la|les|un|une|des|du|ce|qui|est|sont|avec|sans|pour)\b/i;
  for (const { where, def } of props) {
    const en = def["x-i18n"]?.en;
    for (const part of ["title", "description", "placeholder"]) {
      // Québec and Montréal are the places, spelled as they are in English too.
      const text = (en?.[part] ?? "").replace(/Québec|Montréal/g, "");
      if (text) assert.doesNotMatch(text, french, `${where}: the English ${part} reads as French: « ${en[part]} »`);
    }
  }
});

// ── Outputs speak both languages too, and a model declares the aspects it can make ────────────────────
const blueprints = [];
for (const pack of readdirSync(root, { withFileTypes: true })) {
  const studios = join(root, pack.name, "studios");
  if (!pack.isDirectory() || !existsSync(studios)) continue;
  for (const s of readdirSync(studios)) {
    const file = join(studios, s, "blueprint.json");
    if (existsSync(file)) blueprints.push({ where: `${pack.name}/studios/${s}`, studio: s, bp: JSON.parse(readFileSync(file, "utf8")) });
  }
}

test("every output of every Studio has its label in English and French (« Votre image », « Graine… » showed on the English page)", () => {
  const outputs = blueprints.flatMap(({ where, bp }) => (bp.definition.outputs ?? []).map((o) => ({ where: `${where}#${o.key}`, o })));
  assert.ok(outputs.length >= 55, "the audit found the outputs");
  const french = /[àâçéèêëîïôûùœ]|\b(votre|vos|le|la|les|un|une|des|du|ce|qui|est|avec|sans|pour)\b/i;
  for (const { where, o } of outputs) {
    for (const lang of ["en", "fr"]) assert.ok(o["x-i18n"]?.[lang]?.label?.trim(), `${where}: x-i18n.${lang}.label`);
    assert.equal(o["x-i18n"].fr.label, o.label, `${where}: the base label (older clients) is the French one`);
    assert.doesNotMatch(o["x-i18n"].en.label.replace(/Québec|Montréal/g, ""), french, `${where}: the English label reads as French: « ${o["x-i18n"].en.label} »`);
  }
});

test("a pack's English and French catalogue name the same Studios, each with a label and a tagline", () => {
  for (const pack of readdirSync(root, { withFileTypes: true })) {
    const dir = join(root, pack.name, "i18n");
    if (!pack.isDirectory() || !existsSync(dir)) continue;
    const read = (lang) => {
      const text = readFileSync(join(dir, `${lang}.yaml`), "utf8");
      const studios = text.slice(text.indexOf("\nstudios:"));
      const found = {};
      let key = null;
      for (const line of studios.split("\n")) {
        const k = /^  ([a-z0-9-]+):\s*$/.exec(line);
        if (k) { key = k[1]; found[key] = {}; continue; }
        const f = /^    (label|tagline):\s*(.+)$/.exec(line);
        if (f && key) found[key][f[1]] = f[2].trim();
      }
      return found;
    };
    const en = read("en");
    const fr = read("fr");
    assert.deepEqual(Object.keys(en).sort(), Object.keys(fr).sort(), `${pack.name}: the same Studios in both languages`);
    for (const [studio, words] of Object.entries(en)) {
      for (const lang of ["en", "fr"]) {
        const w = (lang === "en" ? en : fr)[studio];
        assert.ok(w.label && w.tagline, `${pack.name}/${studio}: ${lang} label and tagline`);
      }
      assert.notEqual(words.tagline, fr[studio].tagline, `${pack.name}/${studio}: the French tagline is not the English one`);
    }
  }
});

test("the video Studios' model field declares the aspects each model can make, the hosted Wan 16:9 only", () => {
  for (const studio of ["video-generation", "video-with-sound"]) {
    const bp = blueprints.find((b) => b.studio === studio).bp;
    const model = bp.inputSchema.properties.model;
    const aspects = bp.inputSchema.properties.aspect.enum;
    const opt = model["x-options"];
    assert.equal(opt.aspectField, "aspect", `${studio}: the field the aspects govern`);
    assert.deepEqual(Object.keys(opt.aspects).sort(), Object.keys(opt.facts).sort(), `${studio}: every model with facts declares its aspects`);
    for (const [id, list] of Object.entries(opt.aspects)) {
      assert.ok(list.length >= 1 && list.every((a) => aspects.includes(a)), `${studio}/${id}: aspects within the field's enum`);
    }
    assert.deepEqual(opt.aspects["wan2-2-t2v-a14b"], ["16:9"], `${studio}: the hosted Wan makes 16:9 only (run 6567e02a)`);
  }
});
