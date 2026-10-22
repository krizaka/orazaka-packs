// Sovereignty (Loi 25): no Studio names a hosted vendor's model in its definition. A step's model comes from the person's
// choice or the platform's default (`{{inputs.model:}}` empty = Auto), which the platform routes to a model it runs; a
// blueprint never sends data to OpenAI, Anthropic, Google or the like by default (audit 2026-10-22, data-driven-ui).
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const files = [];
for (const pack of readdirSync(root, { withFileTypes: true })) {
  const studios = join(root, pack.name, "studios");
  if (!pack.isDirectory() || !existsSync(studios)) continue;
  for (const s of readdirSync(studios)) {
    const file = join(studios, s, "blueprint.json");
    if (existsSync(file)) files.push({ where: `${pack.name}/studios/${s}`, bp: JSON.parse(readFileSync(file, "utf8")) });
  }
}
const HOSTED = /\b(gpt-[0-9o][\w.-]*|o[1-4](-mini)?|chatgpt[\w.-]*|claude-[\w.-]+|gemini-[\w.-]+|text-embedding-3[\w-]*|dall-e[\w-]*|whisper-1)\b/i;

test("blueprints are found", () => assert.ok(files.length >= 8));

test("no step names a hosted vendor's model", () => {
  for (const { where, bp } of files) {
    for (const step of bp.definition?.steps ?? []) {
      const model = step.inputs?.model;
      if (typeof model === "string") assert.doesNotMatch(model, HOSTED, `${where}#${step.id}: model « ${model} »`);
    }
  }
});

test("no model input defaults to a hosted vendor's model", () => {
  for (const { where, bp } of files) {
    const def = bp.inputSchema?.properties?.model?.default;
    if (def !== undefined) assert.doesNotMatch(String(def), HOSTED, `${where}: model default « ${def} »`);
  }
});

test("data-driven-ui leaves the model to the person or the platform (Auto)", () => {
  const ddui = files.find((f) => f.where === "data-analytics/studios/data-driven-ui").bp;
  assert.equal(ddui.definition.steps[0].inputs.model, "{{inputs.model:}}");
  assert.equal(ddui.inputSchema.properties.model.default, undefined);
});
