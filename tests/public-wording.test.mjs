// public-wording: the packs' descriptions say what they do as technical tools — never « legal rules » nor an escrow,
// and the pack about legal documents says its tools are validated by the client's legal counsel (krizaka/orazaka#418).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import YAML from "yaml";

const root = new URL("../", import.meta.url).pathname;
const packs = readdirSync(root, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(`${root}${d.name}/pack.yaml`))
  .map((d) => d.name);
const FORBIDDEN = /règles juridiques|legal rules|séquestre|escrow/i;
const COUNSEL = { fr: "outils techniques validés par le conseiller juridique du client", en: "technical tools validated by the client's legal counsel" };
const LEGAL_PACKS = ["document-validation"];

const words = (v) => (typeof v === "string" ? [v] : v && typeof v === "object" ? Object.values(v).flatMap(words) : []);

for (const pack of packs) {
  test(`${pack}: no forbidden wording in the manifest or the catalogues`, () => {
    const files = [`${pack}/pack.yaml`, ...["en", "fr"].map((l) => `${pack}/i18n/${l}.yaml`).filter((f) => existsSync(root + f))];
    for (const f of files) {
      const hits = words(YAML.parse(readFileSync(root + f, "utf8"))).filter((s) => FORBIDDEN.test(s));
      assert.deepEqual(hits, [], f);
    }
  });
}

for (const pack of LEGAL_PACKS) {
  for (const lang of ["fr", "en"]) {
    test(`${pack}: the ${lang} description says its tools are validated by the client's legal counsel`, () => {
      const cat = YAML.parse(readFileSync(`${root}${pack}/i18n/${lang}.yaml`, "utf8"));
      assert.ok(cat.pack.description.replace(/\s+/g, " ").includes(COUNSEL[lang]));
    });
  }
}
