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
  for (const rule of ["ORIGINAL", "Marvel", "no real person", "clearly an AI presenter", "Nothing sexual", "No text", "KRIZAKA CINEMATIC KIT", "LENS in mm", "speed ramp", '"lens": focal length', '"lighting"', '"atmosphere"', '"ambience": the sound bed']) {
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
  assert.ok(Object.keys(read("video-generation").inputSchema.properties.model["x-i18n"].en.options).includes("wan2.2-i2v-a14b"));
});

// The treatment stage (orazaka#289): a short brief becomes a story — an arc, intentions, living purposeful shots,
// directed lines, music cues and a sound list — and a critique reads it like a director before any shot is planned.
test("the treatment and the critique are Studios of the media pack, in both languages", () => {
  for (const key of ["cinematic-treatment", "cinematic-critique"]) {
    assert.match(pack, new RegExp(`key: ${key}\\n[\\s\\S]*?entitlementKey: studio\\.${key}`));
    assert.equal(read(key).definition.studioKey, key);
    assert.equal(read(key).definition.steps[0].featureKey, "orazaka.core.chat.completion");
    for (const lang of ["en", "fr"]) assert.match(readFileSync(`${root}i18n/${lang}.yaml`, "utf8"), new RegExp(`  ${key}:\\n    label:`));
  }
});

test("the treatment's prompt asks for a story that transports, living characters, directed sound — and keeps the content rules", () => {
  const prompt = read("cinematic-treatment").definition.steps[0].inputs.prompt;
  for (const rule of [
    "ORIGINAL", "no real person", "Nothing sexual", "No text",
    "hook", "journey", "turn", "payoff", "INTENTION", "PURPOSE", "never decoration",
    "never 'the bird moves'", "GAZE", "PHYSICS", "INTERACTION", "chainFrom",
    "DIRECTION: emotion, pace", "intensity from 0 to 0.85", "never an artist", "a character's action is always heard",
    "{{inputs.notes:}}",
  ]) {
    assert.ok(prompt.includes(rule), `the treatment prompt must say: ${rule}`);
  }
  const props = read("cinematic-treatment").inputSchema.properties;
  assert.deepEqual(Object.keys(props).sort(), ["aspect", "brief", "durationSeconds", "language", "model", "notes"]);
  assert.equal(props.notes["x-advanced"], true);
});

test("the critique Studio takes the rubric and the story orazaka cinema writes, and answers JSON", () => {
  const [step] = read("cinematic-critique").definition.steps;
  assert.equal(step.inputs.prompt, "{{inputs.treatment}}");
  assert.deepEqual(read("cinematic-critique").inputSchema.required, ["treatment"]);
});
