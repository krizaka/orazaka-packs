// An input that takes an uploaded file must say so: a client renders a picker for it, never a text field
// expecting an asset id (krizaka/orazaka-web-client#95, orazaka-mobile-client#33, orazaka-packs#30).
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const blueprints = [];
for (const pack of readdirSync(root, { withFileTypes: true })) {
  const studios = join(root, pack.name, "studios");
  if (!pack.isDirectory() || !existsSync(studios)) continue;
  for (const s of readdirSync(studios)) {
    const file = join(studios, s, "blueprint.json");
    if (existsSync(file))
      blueprints.push({ file: `${pack.name}/studios/${s}`, bp: JSON.parse(readFileSync(file, "utf8")) });
  }
}

const KINDS = { image: "image/*", video: "video/*", audio: "audio/*" };
const props = blueprints.flatMap(({ file, bp }) =>
  Object.entries(bp.inputSchema?.properties ?? {}).map(([key, def]) => ({ where: `${file}#${key}`, key, def })),
);

test("blueprints are found", () => assert.ok(blueprints.length >= 8 && props.length > 0));

test("every file input declares an asset format and a matching contentMediaType", () => {
  for (const { where, def } of props) {
    const f = def.format;
    if (f === "asset-id") {
      assert.ok(
        Object.values(KINDS).includes(def.contentMediaType),
        `${where}: asset-id needs contentMediaType image/*|video/*|audio/*`,
      );
    } else if (typeof f === "string" && f.startsWith("asset:")) {
      const kind = f.slice("asset:".length);
      assert.ok(KINDS[kind], `${where}: unknown asset kind ${f}`);
      assert.equal(def.contentMediaType, KINDS[kind], `${where}: contentMediaType must be ${KINDS[kind]}`);
    } else {
      assert.equal(def.contentMediaType, undefined, `${where}: contentMediaType without an asset format`);
    }
    if (f?.startsWith("asset")) assert.equal(def.type, "string", `${where}: an asset input is a string`);
  }
});

test("an input that takes an uploaded file is never left as plain text", () => {
  for (const { where, key, def } of props) {
    const takesFile =
      /fichiers? envoy|identifiant d'un (de vos )?fichier|l'identifiant du fichier/i.test(def.description ?? "") ||
      (key === "image" && def.maxLength);
    if (!takesFile) continue;
    assert.ok(def.format?.startsWith("asset"), `${where}: declares no asset format`);
  }
});

test("the image seed of the video studios is asset:image", () => {
  for (const s of ["video-generation", "video-with-sound"]) {
    const bp = blueprints.find((b) => b.file.endsWith(`/${s}`)).bp;
    assert.equal(bp.inputSchema.properties.image.format, "asset:image");
  }
});
