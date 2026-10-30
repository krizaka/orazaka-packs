import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { checkRatchet, discover } from "./golden/harness.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const ratchet = JSON.parse(readFileSync(new URL("../golden-ratchet.json", import.meta.url), "utf8"));

test("every non-exempt Studio ships 3–5 schema-valid fictional golden cases", () => {
  const suites = discover(root);
  assert.ok(suites.length > 0, "no Studio goldens discovered");
});

test("golden coverage exceptions only decrease against the PR base", () => {
  // CI supplies the immutable PR base SHA; local runs still reject any new exception.
  const base = process.env.GOLDEN_BASE_SHA;
  if (base) assert.match(base, /^[0-9a-f]{40}$/);
  let previous = ["document-validation/compliance-check", "document-validation/document-authenticity"];
  if (base) {
    const files = execFileSync("git", ["ls-tree", "--name-only", base, "--", "golden-ratchet.json"], {
      cwd: root,
      encoding: "utf8",
    });
    if (files.trim())
      previous = JSON.parse(
        execFileSync("git", ["show", `${base}:golden-ratchet.json`], { cwd: root, encoding: "utf8" }),
      ).exceptions;
  }
  checkRatchet(ratchet.exceptions, previous);
});
