// A step id must match what the Studio accepts (orazaka-studio's blueprint validator): the packs CI checks it here, so a
// bad id fails in this repository instead of in another repository's integration test (it once did: `policyFr`).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const STEP_ID = /^[a-z][a-z0-9-]{0,59}$/;
// Known violations, fixed by a tracked issue (empty since #159). This list may only shrink:
// a new bad id fails, and a fixed one must be removed from here.
const KNOWN = new Set([]);
const root = new URL("..", import.meta.url).pathname;

function blueprints(dir) {
  return readdirSync(dir).flatMap((name) => {
    if (name === "node_modules" || name.startsWith(".")) return [];
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return blueprints(path);
    return name === "blueprint.json" ? [path] : [];
  });
}

test("every blueprint step id matches the Studio's rule", () => {
  const files = blueprints(root);
  assert.ok(files.length > 0, "found the blueprints");
  for (const file of files) {
    const doc = JSON.parse(readFileSync(file, "utf8"));
    const steps = (doc.definition ?? doc).steps ?? [];
    for (const step of steps) {
      const key = `${file.replace(root, "")} ${step.id}`;
      if (KNOWN.has(key)) {
        assert.doesNotMatch(step.id, STEP_ID, `${key} is fixed: remove it from KNOWN`);
        continue;
      }
      assert.match(step.id, STEP_ID, `${key}: step id must match ${STEP_ID}`);
    }
  }
});
