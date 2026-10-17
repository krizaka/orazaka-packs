// The Data & Analytics pack (ADR-078, orazaka discussion #174): the recommender served by the knowledge service is
// bought as a pack, its API scopes are declared in the manifest, and its Studios are data over existing capabilities.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const dir = join(root, "data-analytics");
const pack = () => readFileSync(join(dir, "pack.yaml"), "utf8");
const blueprint = (key) => JSON.parse(readFileSync(join(dir, "studios", key, "blueprint.json"), "utf8"));
const schema = JSON.parse(readFileSync(join(root, "pack.schema.json"), "utf8"));

const STUDIOS = ["data-driven-ui", "video-understanding", "creator-suggestions"];
// The edge's ApiKeyScopes (orazaka-edge): exact method + path, fail closed. Kept identical here.
const SCOPES = {
  "reco:sync": [
    "POST /api/v1/recommendations/events",
    "POST /api/v1/recommendations/items",
    "POST /api/v1/recommendations/erasures",
  ],
  "reco:read": [
    "GET /api/v1/recommendations/for-you",
    "GET /api/v1/recommendations/similar",
    "GET /api/v1/recommendations/insights",
  ],
  "analytics:sync": ["POST /api/v1/analytics/events", "POST /api/v1/analytics/erasures"],
  "analytics:read": ["GET /api/v1/analytics/insights", "GET /api/v1/analytics/funnel"],
};

/** The routes a scope lists under `requires.api.scopes` of a pack.yaml — read line by line. */
export function scopeRoutes(yaml) {
  const out = {};
  let current = null;
  for (const line of yaml.split("\n")) {
    const key = line.match(/^\s+- key: ([a-z]+:[a-z]+)\s*$/);
    if (key) {
      current = key[1];
      out[current] = [];
      continue;
    }
    const route = line.match(/^\s+- "?(GET|POST|PUT|PATCH|DELETE) (\/[^"\s]+)"?\s*$/);
    if (route && current) out[current].push(`${route[1]} ${route[2]}`);
  }
  return out;
}

test("the pack stands on the Data & Analytics shelf, sold, and published", () => {
  assert.ok(existsSync(join(dir, "pack.yaml")));
  const yaml = pack();
  assert.match(yaml, /^key: data-analytics$/m);
  assert.match(yaml, /^  categoryKey: data-analytics$/m);
  assert.match(yaml, /^  status: PUBLISHED$/m);
  assert.match(yaml, /^  priceCents: \d+/m);
  assert.match(yaml, /^  includedCredits: \d+/m);
});

test("the schema lets a pack declare the platform API scopes it needs", () => {
  const api = schema.properties.requires.properties.api;
  assert.ok(api, "requires.api is part of the manifest grammar");
  assert.equal(api.properties.scopes.items.additionalProperties, false);
  assert.match("reco:sync", new RegExp(api.properties.scopes.items.properties.key.pattern));
  assert.doesNotMatch("Reco Sync", new RegExp(api.properties.scopes.items.properties.key.pattern));
});

test("the declared scopes are exactly the edge's reco:* and analytics:*", () => {
  assert.deepEqual(scopeRoutes(pack()), SCOPES);
});

test("each Studio is a published blueprint over existing capabilities, labelled in EN and FR", () => {
  const yaml = pack();
  for (const key of STUDIOS) {
    assert.match(yaml, new RegExp(`key: ${key}\\n[\\s\\S]*?entitlementKey: studio\\.${key}`));
    const b = blueprint(key);
    assert.equal(b.definition.studioKey, key);
    assert.equal(b.status, "PUBLISHED");
    for (const step of b.definition.steps) assert.match(step.featureKey, /^orazaka\.core\./, `${key}: ${step.id}`);
    for (const lang of ["en", "fr"]) {
      const i18n = readFileSync(join(dir, "i18n", `${lang}.yaml`), "utf8");
      assert.match(i18n, new RegExp(`  ${key}:\\n    label:`), `${key} label in ${lang}`);
      assert.match(i18n, /^category:\n  label: /m, `category label in ${lang}`);
    }
  }
});

test("closed choices are chosen, never typed (no free-text model, languages are an enum)", () => {
  for (const key of STUDIOS) {
    const props = blueprint(key).inputSchema.properties;
    assert.equal(props.model, undefined, `${key}: no free-text model input`);
    assert.deepEqual(props.language.enum, ["en", "fr"]);
  }
});

test("video understanding looks at a keyframe, then answers in JSON with safety labels — never a takedown", () => {
  const [see, read] = blueprint("video-understanding").definition.steps;
  assert.equal(see.featureKey, "orazaka.core.media.vision");
  assert.equal(blueprint("video-understanding").inputSchema.properties.assetId.contentMediaType, "image/*");
  assert.equal(read.featureKey, "orazaka.core.chat.completion");
  assert.deepEqual(read.dependsOn, [see.id]);
  for (const word of ["JSON", "topics", "tags", "safetyLabels", "never decide"]) assert.ok(read.inputs.prompt.includes(word), word);
});

test("creator suggestions are proposals the creator approves, from the creator's own text", () => {
  const [step] = blueprint("creator-suggestions").definition.steps;
  assert.equal(step.featureKey, "orazaka.core.chat.completion");
  for (const word of ["JSON", "titles", "tags", "creator approves", "{{inputs.title}}"]) assert.ok(step.inputs.prompt.includes(word), word);
});

test("the pack never handles a raw identity: its docs state the pseudonym rule (Loi 25)", () => {
  const readme = readFileSync(join(dir, "README.md"), "utf8");
  for (const words of ["HMAC-SHA256", "pseudonym", "erasures", "retention"]) assert.ok(readme.includes(words), words);
});

test("data-driven UI (ADR-082): one LLM step that answers in A2UI v0.9 with the krizaka:genui/v1 catalog only", () => {
  const [step] = blueprint("data-driven-ui").definition.steps;
  assert.equal(step.featureKey, "orazaka.core.chat.completion");
  const prompt = step.inputs.prompt;
  for (const words of ["```a2ui", "\"version\":\"v0.9\"", "krizaka:genui/v1", "createSurface", "updateComponents", "updateDataModel", "\"id\":\"root\""]) {
    assert.ok(prompt.includes(words), words);
  }
  for (const component of ["Column", "Row", "Text", "Card", "Callout", "KpiStat", "ChartCard", "Table"]) assert.ok(prompt.includes(`- ${component} {`) || prompt.includes(`${component} {`), component);
  for (const rule of ["never invent", "No other component", "no HTML, no URL, no code"]) assert.ok(prompt.includes(rule), rule);
  const props = blueprint("data-driven-ui").inputSchema.properties;
  assert.equal(props.data.maxLength, 20000);
  assert.deepEqual(blueprint("data-driven-ui").inputSchema.required, ["data", "question"]);
});
