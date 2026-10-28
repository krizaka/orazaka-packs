// code-contributor (krizaka/orazaka#450, ADR-093): two Studios that carry the Mac app's model turns. Billing sells their
// entitlement keys; every turn is AGENT; the consent is a versioned statement; the pack is not REGULATED; the model is routing data.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import YAML from "yaml";

const root = new URL("../code-contributor/", import.meta.url).pathname;
const pack = YAML.parse(readFileSync(`${root}pack.yaml`, "utf8"));
const blueprint = (key) => JSON.parse(readFileSync(`${root}studios/${key}/blueprint.json`, "utf8"));

test("two Studios with the entitlement keys billing sells", () => {
  assert.deepEqual(pack.studios.map((s) => [s.key, s.entitlementKey]), [
    ["code-issue-to-pr", "studio.code-issue-to-pr"],
    ["code-read-write", "studio.code-read-write"],
  ]);
  for (const s of pack.studios) assert.equal(s.pricing, "PAID");
});

test("every model turn bills as AGENT and names no provider; each Studio is one SESSION step", () => {
  const [cap] = pack.requires.capabilities;
  assert.equal(cap.billableCapability, "AGENT");
  assert.doesNotMatch(JSON.stringify(pack), /openai|anthropic|ollama|gpt|claude/i);
  for (const s of pack.studios) {
    // The turns themselves are posted to the session, which the capability routes and bills.
    const steps = blueprint(s.key).definition.steps;
    assert.equal(steps.length, 1);
    assert.equal(steps[0].kind, "SESSION");
    assert.equal(steps[0].featureKey, undefined);
  }
});

test("not regulated; a versioned consent in French and English says nothing is written or pushed without approval", () => {
  assert.notEqual(pack.regulatoryClass, "REGULATED");
  assert.match(pack.consent.version, /^\d+\.\d+$/);
  assert.match(pack.consent.statement, /sans votre approbation/);
  assert.match(pack.consent.statements.en, /reads the repositories you grant and sends the excerpts it needs to the model your workspace routes to/);
  assert.match(pack.consent.statements.en, /without your approval/);
});
