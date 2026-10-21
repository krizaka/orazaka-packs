// The wellbeing consent (orazaka#301): the statement is served in both languages and says only what the
// system does; every region has an official, dated crisis line. Pure data, no engine.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const yaml = readFileSync(join(root, "wellbeing/pack.yaml"), "utf8");
const schema = JSON.parse(readFileSync(join(root, "pack.schema.json"), "utf8"));

/** The folded scalar under a key, joined on spaces. */
function folded(key, indent) {
  const lines = yaml.split("\n");
  const start = lines.findIndex((l) => l === `${" ".repeat(indent)}${key}: >-`);
  assert.ok(start >= 0, `${key} not found`);
  const out = [];
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].trim() !== "" && !lines[i].startsWith(" ".repeat(indent + 2))) break;
    if (lines[i].trim() !== "") out.push(lines[i].trim());
  }
  return out.join(" ");
}

const fr = folded("statement", 2);
const en = folded("en", 4);

test("the consent version is 2.1 and the schema accepts translations", () => {
  assert.match(yaml, /consent:\n(?:  #.*\n)*  version: "2\.1"/);
  assert.equal(schema.properties.consent.properties.statements.type, "object");
});

test("both statements promise the erase and the withdrawal, with the retention the platform applies", () => {
  assert.match(fr, /Supprimer toutes mes données de bien-être/);
  assert.match(fr, /30 jours/);
  assert.match(fr, /retirer votre consentement/);
  assert.match(en, /Delete all my wellbeing data/);
  assert.match(en, /30 days/);
  assert.match(en, /withdraw your consent/);
  assert.doesNotMatch(fr + en, /\d{1,3}[ -]?\d{3}/, "a statement carries no phone number: the lines are served apart");
});

test("the statement says what is encrypted, where, and how long backups keep a deletion (ADR-055 section 8)", () => {
  assert.match(fr, /TLS/);
  assert.match(fr, /une clé par fichier/);
  assert.match(fr, /disques sont chiffrés par l'hébergeur/);
  assert.match(fr, /champ par champ/);
  assert.match(fr, /sauvegardes techniques chiffrées .* conservées 7 jours/);
  assert.match(en, /TLS/);
  assert.match(en, /one key per file/);
  assert.match(en, /disks are encrypted by the host/);
  assert.match(en, /field-by-field/);
  assert.match(en, /backups of the database are kept for 7 days/);
  // It must not claim the columns themselves are encrypted by the application.
  assert.doesNotMatch(fr, /colonnes? chiffrées?|champs? chiffrés?/);
});

test("the statement covers spoken exchanges and says the sound is not kept", () => {
  assert.match(fr, /écrivez ou dites/);
  assert.match(fr, /le texte, pas le son/);
  assert.match(fr, /échanges écrits ou parlés/);
  assert.match(en, /write or say/);
  assert.match(en, /the text, not the sound/);
  assert.match(en, /written or spoken exchanges/);
});

test("the English statement says what the French one says: same figures, same promises", () => {
  const figures = (t) => (t.match(/\b\d+\b/g) ?? []).sort().join(",");
  assert.equal(figures(fr), figures(en));
  for (const [f, e] of [[/RGPD/, /GDPR/], [/Loi 25/, /Law 25/], [/jamais utilisés pour entraîner/, /never used to train/], [/n'est pas un service d'urgence/, /not an emergency service/]]) {
    assert.match(fr, f);
    assert.match(en, e);
  }
});

test("every supported region has an official https source and the date it was read there", () => {
  const regions = ["FR", "BE-FR", "BE-NL", "CA", "CA-QC"];
  for (const region of regions) {
    const block = yaml.split(`    ${region}:\n`)[1];
    assert.ok(block, `${region} missing`);
    const head = block.split("\n").slice(0, 8).join("\n");
    assert.match(head, /sourceUrl: "https:\/\/[^"]+"/, `${region}: no https source`);
    assert.match(head, /verifiedOn: "2026-10-20"/, `${region}: not verified on 2026-10-20`);
  }
  assert.match(yaml, /contact: "3114"/);
  assert.match(yaml, /contact: "0800 32 123"/);
  assert.match(yaml, /contact: "1813"/);
  assert.match(yaml, /contact: "9-8-8 \(appel ou texto\)"/);
  assert.match(yaml, /1 866 APPELLE \(1 866 277-3553\)/);
});
