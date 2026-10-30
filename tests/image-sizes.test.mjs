// orazaka#307: the image Studio offers sizes a hosted engine refuses (stable-diffusion-3.5-large only makes 512x512 and
// 1024x1024 of them): the run started, held credits, then failed. The blueprint now declares what each model makes
// (`x-options.aspectField` + `aspects`, the mechanism the video Studio uses) so the server refuses or fills before any hold.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const bp = JSON.parse(
  readFileSync(new URL("../orazaka-media/studios/image-generation/blueprint.json", import.meta.url), "utf8"),
);
const props = bp.inputSchema.properties;

test("the model field names the size field and what each known model makes", () => {
  const options = props.model["x-options"];
  assert.equal(options.aspectField, "size");
  assert.deepEqual(options.aspects["stable-diffusion-3.5-large"], ["1024x1024", "512x512"]);
  assert.deepEqual(options.aspects["v1-5-pruned-emaonly"], ["512x512"]);
});

test("every declared size is one the Studio offers, and the default size is made by every declared model", () => {
  const offered = props.size.enum;
  for (const [model, sizes] of Object.entries(props.model["x-options"].aspects)) {
    for (const size of sizes) assert.ok(offered.includes(size), `${model}: ${size} is not an option of the size field`);
  }
  // A blank size is filled with the first size of the chosen model: the default must not be refused for a declared model.
  const first = (m) => props.model["x-options"].aspects[m][0];
  assert.ok(Object.keys(props.model["x-options"].aspects).every((m) => offered.includes(first(m))));
});

test("the version moved and the changelog says why", () => {
  assert.match(bp.version, /^1\.([6-9]|\d{2})\.\d+$/);
  assert.equal(bp.definition.version, bp.version);
  assert.match(bp.changelog, /1\.6\.0/);
});
