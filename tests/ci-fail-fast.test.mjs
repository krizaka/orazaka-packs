// A list of test commands run by `bash -c` (the shared python-ci workflow) reports only the LAST command's status unless
// the script stops at the first failure. Every multi-line test/lint/setup command of the CI therefore opens with
// `set -e` (2026-10-26: three failing suites of test_check.py were hidden behind a green last command).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const ci = parse(readFileSync(fileURLToPath(new URL("../.github/workflows/ci.yml", import.meta.url)), "utf8"));

/** The first line of a multi-line command stops the script on the first failure. */
export const failsFast = (command) => {
  const lines = command
    .trim()
    .split("\n")
    .filter((l) => l.trim() && !l.trim().startsWith("#"));
  return lines.length < 2 || /^set -[a-z]*e[a-z]*(\s|$)/.test(lines[0]) || /^set -o errexit/.test(lines[0]);
};

test("every multi-line command passed to a reusable workflow stops at its first failure", () => {
  let seen = 0;
  for (const [job, def] of Object.entries(ci.jobs)) {
    for (const key of ["test-command", "lint-command", "setup-command"]) {
      const command = def.with?.[key];
      if (typeof command !== "string") continue;
      seen++;
      assert.ok(
        failsFast(command),
        `${job}.${key}: starts with 'set -euo pipefail' (a later command would hide a failure)`,
      );
    }
  }
  assert.ok(seen >= 7, `the Python worker jobs were found (${seen})`);
});

test("the check itself refuses a list whose first failure would be hidden", () => {
  assert.equal(failsFast("python a.py\npython b.py"), false);
  assert.equal(failsFast("set -euo pipefail\npython a.py\npython b.py"), true);
  assert.equal(failsFast("python a.py"), true);
});
