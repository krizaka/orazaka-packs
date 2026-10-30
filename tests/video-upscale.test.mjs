// The video Studio's optional super-resolution step (orazaka-worker-media `upscale`): one input, never on by default,
// forwarded to the video step, versioned in the blueprint's changelog.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const bp = JSON.parse(
  readFileSync(new URL("../orazaka-media/studios/video-generation/blueprint.json", import.meta.url), "utf8"),
);

test("`upscale` is an optional input: none by default, 1080p or 2160p (4K)", () => {
  const upscale = bp.inputSchema.properties.upscale;
  assert.deepEqual(upscale.enum, ["none", "1080p", "2160p"]);
  assert.equal(upscale.default, "none");
  assert.ok(!bp.inputSchema.required.includes("upscale"));
});

test("the video step forwards it, empty when the caller says nothing", () => {
  const step = bp.definition.steps.find((s) => s.id === "video");
  assert.equal(step.inputs.upscale, "{{inputs.upscale:}}");
});

test("the version moved and the changelog says what the step is: SeedVR2 3B, Apache-2.0, a longer run", () => {
  assert.match(bp.version, /^1\.([7-9]|\d{2})\.\d+$/);
  assert.equal(bp.definition.version, bp.version);
  assert.match(bp.changelog, /SeedVR2/);
});

test("the kit: LTX-Video 0.9.8 is a choice of `model`, and the prompt and image say the rule (motion only, the still at the video's aspect)", () => {
  const props = bp.inputSchema.properties;
  assert.ok(Object.keys(props.model["x-i18n"].en.options).includes("ltx-video-0.9.8-13b-distilled"));
  assert.ok(Object.keys(props.model["x-i18n"].en.options).includes("wan2.2-i2v-a14b-hq"));
  assert.match(props.prompt.description, /MOUVEMENT et la CAMÉRA/);
  assert.match(props.image.description, /1360×768/);
  assert.match(props.image.description, /768×1360/);
  assert.match(bp.changelog, /1\.7\.0 — le kit cinématographique Krizaka/);
});
