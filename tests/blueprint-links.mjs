// Shared by the pack tests: a step input only reads inputs the Studio declares and steps that come before it.
import assert from "node:assert/strict";

export function assertLinksResolve(blueprint) {
  const steps = blueprint.definition.steps;
  const declared = new Set(Object.keys(blueprint.inputSchema.properties));
  const outs = new Map(steps.map((s) => [s.out, s.id]));
  for (const s of steps) {
    for (const value of Object.values(s.inputs)) {
      for (const m of String(value).matchAll(/\{\{inputs\.([A-Za-z0-9]+)/g)) assert.ok(declared.has(m[1]), `${s.id}: unknown input ${m[1]}`);
      for (const m of String(value).matchAll(/\{\{steps\.([A-Za-z0-9]+)/g)) {
        const producer = outs.get(m[1]);
        assert.ok(producer, `${s.id}: nothing produces ${m[1]}`);
        assert.ok(s.dependsOn.includes(producer), `${s.id} must depend on ${producer}`);
      }
    }
  }
}
