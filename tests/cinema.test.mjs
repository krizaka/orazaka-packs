// A cinematic short (ADR-080, krizaka/orazaka): its two Studios are data, and the content rules are in the script's
// own prompt — original characters, no trademark, no real person, an AI anchor for news, nothing sexual.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../orazaka-media/", import.meta.url).pathname;
const read = (s) => JSON.parse(readFileSync(`${root}studios/${s}/blueprint.json`, "utf8"));
const pack = readFileSync(`${root}pack.yaml`, "utf8");

test("the script and the cut are Studios of the media pack", () => {
  for (const key of ["cinematic-script", "cinematic-cut"]) {
    assert.match(pack, new RegExp(`key: ${key}\\n[\\s\\S]*?entitlementKey: studio\\.${key}`));
    assert.equal(read(key).definition.studioKey, key);
    for (const lang of ["en", "fr"]) assert.match(readFileSync(`${root}i18n/${lang}.yaml`, "utf8"), new RegExp(`  ${key}:\\n    label:`));
  }
});

test("the script is one LLM step whose prompt carries the content rules", () => {
  const [step] = read("cinematic-script").definition.steps;
  assert.equal(step.featureKey, "orazaka.core.chat.completion");
  const prompt = step.inputs.prompt;
  for (const rule of ["ORIGINAL", "Marvel", "no real person", "clearly an AI presenter", "Nothing sexual", "No text"]) {
    assert.ok(prompt.includes(rule), `the prompt must say: ${rule}`);
  }
  const props = read("cinematic-script").inputSchema.properties;
  assert.deepEqual([props.durationSeconds.minimum, props.durationSeconds.maximum], [30, 60]);
  assert.deepEqual([props.shots.minimum, props.shots.maximum], [8, 12]);
});

test("the cut is the compose capability with clips and an edit list", () => {
  const [step] = read("cinematic-cut").definition.steps;
  assert.equal(step.featureKey, "orazaka.studio.media.compose");
  assert.deepEqual(Object.keys(step.inputs).sort(), ["clips", "edit"]);
});

test("video generation offers the 4-step I2V A14B for the shots", () => {
  assert.ok(read("video-generation").inputSchema.properties.model.enum.includes("wan2.2-i2v-a14b"));
});
