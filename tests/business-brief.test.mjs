// business-brief (krizaka/orazaka-packs#103): the invitation writer takes aggregates only, answers within a short timeout, and its
// recorded port contract matches the Studio's schema and outputs.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Ajv from "ajv";

const root = new URL("../business-brief/", import.meta.url).pathname;
const read = (p) => readFileSync(`${root}${p}`, "utf8");
const blueprint = JSON.parse(read("studios/invitation-writer/blueprint.json"));
const contract = JSON.parse(read("tests/contracts/invitation-writer.contract.json"));
const step = blueprint.definition.steps[0];
const props = blueprint.inputSchema.properties;

test("the inputs are aggregates only: no client, no history, no price", () => {
  assert.deepEqual(Object.keys(props).sort(), ["channel", "freeSlots", "language", "service", "shopName", "tone"]);
  for (const key of Object.keys(props)) assert.doesNotMatch(key, /client|customer|history|visit|price|discount/i, key);
  assert.deepEqual(blueprint.inputSchema.required, ["shopName", "service", "freeSlots"]);
});

test("the prompt forbids names, history, prices and invented deadlines, and uses OQLF vocabulary", () => {
  const prompt = step.inputs.prompt;
  for (const must of [
    "aggregates only",
    "Never include a client name",
    "a greeting by name",
    "history",
    "a price, a discount or an invented deadline",
    "OQLF",
    "Output only the message",
  ])
    assert.ok(prompt.includes(must), must);
  assert.match(prompt, /sms: at most 160 characters/);
  assert.match(prompt, /push: at most 90 characters/);
});

test("one step, one attempt, a short timeout, so the product's port can wait for it and fall back", () => {
  assert.equal(blueprint.definition.steps.length, 1);
  assert.equal(step.maxAttempts, 1);
  assert.equal(step.timeout, "PT30S");
  assert.equal(contract.timeoutMs, 30000);
  assert.match(contract.fallback, /bilingual template/);
  const declared = Object.keys(props);
  for (const m of String(step.inputs.prompt).matchAll(/\{\{inputs\.([A-Za-z0-9]+)/g))
    assert.ok(declared.includes(m[1]), `unknown input ${m[1]}`);
});

test("the recorded contract request is valid for the Studio and its response carries the output and the run id the product keeps", () => {
  const validate = new Ajv({ strict: false, validateFormats: false }).compile(blueprint.inputSchema);
  assert.ok(validate(contract.request.input), JSON.stringify(validate.errors));
  assert.deepEqual(
    Object.keys(contract.response.outputs),
    blueprint.definition.outputs.map((o) => o.key),
  );
  assert.match(contract.response.runId, /^run_[A-Za-z0-9]+$/);
  assert.match(contract.kept, /runId is stored with the sent message/);
  const message = contract.response.outputs.invitation;
  assert.ok(message.length <= 160, "the recorded sms fits 160 characters");
  assert.doesNotMatch(message, /\d+\s?\$|%|rabais|discount/i);
});

test("every golden message fits its channel and carries no price", () => {
  const golden = JSON.parse(read("tests/golden/invitation-writer.json"));
  const limit = { sms: 160, push: 90, email: 600 };
  for (const c of golden.cases) {
    const text = c.expected.invitation;
    assert.ok(text.length <= limit[c.input.channel], `${c.id}: ${text.length} characters on ${c.input.channel}`);
    assert.doesNotMatch(text, /\d+\s?\$|%|rabais|discount/i, c.id);
  }
});
