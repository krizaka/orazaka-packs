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
const MODEL_CATEGORIES = ["image", "video", "speech", "audio", "vision", "chat"];

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
    // The voice of speech synthesis is the choice the Studio is about, so it stays in front.
    if (def["x-options"]?.category === "speech") continue;
    if (key === "model" || key === "negativePrompt") assert.equal(def["x-advanced"], true, `${where}: x-advanced`);
  }
});
