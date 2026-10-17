// Catalogue categories are data (krizaka/orazaka-packs#16): the `catalog.categoryKey` of each pack.yaml, drawn from a
// closed list that the schema owns. Their labels are the packs' i18n (`category:` block, EN and FR), never code.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const CATEGORIES = ["business-compliance", "creativity-media", "wellbeing", "data-analytics"];

const schema = JSON.parse(readFileSync(join(root, "pack.schema.json"), "utf8"));

/** The `catalog.categoryKey` of a pack.yaml text; null when there is no catalog block or no key. */
export function categoryOf(yaml) {
  const block = yaml.match(/^catalog:[ \t]*\n((?:[ \t]+.*\n|[ \t]*\n)*)/m)?.[1];
  if (block === undefined) return { catalogued: false, key: null };
  return { catalogued: true, key: block.match(/^  categoryKey:[ \t]*([^\s#]+)/m)?.[1] ?? null };
}

/** The `label` under the top-level `category:` of an i18n file — read line by line, no backtracking. */
export function labelOf(text) {
  let inside = false;
  for (const line of text.split("\n")) {
    if (/^\S/.test(line)) inside = line.startsWith("category:");
    else if (inside && line.trim().startsWith("label:")) return line.trim().slice("label:".length).trim();
  }
  return null;
}

/** Why a category is refused, or null when the pack is fine. */
export function refusal(yaml) {
  const { catalogued, key } = categoryOf(yaml);
  if (!catalogued) return null; // a bundle with no catalog is a lone Studio, not a pack of the catalogue
  if (!key) return "missing category";
  if (!CATEGORIES.includes(key)) return `unknown category ${key}`;
  return null;
}

const packs = readdirSync(root, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(join(root, d.name, "pack.yaml")))
  .map((d) => ({ dir: d.name, yaml: readFileSync(join(root, d.name, "pack.yaml"), "utf8") }));

test("the schema closes the list of categories", () => {
  assert.deepEqual(schema.$defs ? schema.properties.catalog.properties.categoryKey.enum : null, CATEGORIES);
});

test("every catalogued pack declares a known category", () => {
  assert.ok(packs.length >= 7);
  for (const { dir, yaml } of packs) assert.equal(refusal(yaml), null, `${dir}: ${refusal(yaml)}`);
});

test("a missing or unknown category is refused", () => {
  assert.equal(refusal("catalog:\n  iconKey: x\n  status: PUBLISHED\n"), "missing category");
  assert.equal(refusal("catalog:\n  categoryKey: business\n"), "unknown category business");
  assert.equal(refusal("catalog:\n  categoryKey: lifestyle # old\n"), "unknown category lifestyle");
  assert.equal(refusal("catalog:\n  categoryKey: wellbeing\n"), null);
  assert.equal(refusal("key: lone-studio\n"), null);
});

test("the stated assignment of the catalogue", () => {
  const of = Object.fromEntries(packs.map((p) => [p.dir, categoryOf(p.yaml).key]));
  assert.equal(of["document-validation"], "business-compliance");
  assert.equal(of["outbound-prospection"], "business-compliance");
  assert.equal(of["orazaka-media"], "creativity-media");
  assert.equal(of["realestate-studio"], "creativity-media");
  assert.equal(of["wellbeing"], "wellbeing");
});

test("each shelf is labelled in EN and FR by the packs' i18n, one label per category", () => {
  const labels = new Map();
  for (const { dir, yaml } of packs) {
    const { key } = categoryOf(yaml);
    if (!key || !/^  category:[ \t]*$/m.test(yaml) || /^  status:[ \t]*DRAFT/m.test(yaml)) continue; // a DRAFT pack is off the shelf
    for (const lang of ["en", "fr"]) {
      const file = join(root, dir, "i18n", `${lang}.yaml`);
      assert.ok(existsSync(file), `${dir}: i18n/${lang}.yaml`);
      const label = labelOf(readFileSync(file, "utf8"));
      assert.ok(label, `${dir}: category.label in ${lang}`);
      const id = `${key}/${lang}`;
      assert.equal(labels.get(id) ?? label, label, `${dir}: ${id} is labelled differently by another pack`);
      labels.set(id, label);
    }
  }
});
