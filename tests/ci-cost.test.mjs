// node --test — GitHub Actions minutes guard (krizaka/.github CI-COST; same file in every repository, only WORKFLOWS differs).
// A run that sleeps, a job without a timeout, a Scorecard on every push, or a skip gate that does not fail open costs
// minutes (or a check) for nothing: each is refused here, not found on the bill.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

const WORKFLOWS = join(import.meta.dirname, "..", ".github", "workflows");

/** The jobs of a workflow: { name, text } for each two-space-indented key under `jobs:`. */
export function jobsOf(text) {
  const i = text.search(/^jobs:\s*$/m);
  if (i < 0) return [];
  const body = text.slice(i).split("\n").slice(1);
  const jobs = [];
  for (const line of body) {
    const m = /^ {2}([A-Za-z0-9_-]+):\s*$/.exec(line);
    if (m) jobs.push({ name: m[1], text: "" });
    else if (jobs.length) jobs[jobs.length - 1].text += `${line}\n`;
  }
  return jobs;
}

describe("the parser", () => {
  it("splits jobs", () => {
    const j = jobsOf("name: x\njobs:\n  a:\n    runs-on: u\n  b:\n    uses: o/r/.github/workflows/w.yml@abc\n");
    assert.deepEqual(j.map((x) => x.name), ["a", "b"]);
  });
});

for (const file of readdirSync(WORKFLOWS).filter((n) => /\.ya?ml$/.test(n))) {
  const text = readFileSync(join(WORKFLOWS, file), "utf8");
  describe(file, () => {
    it("never sleeps for minutes on a billed runner", () => {
      assert.doesNotMatch(text.replace(/#.*$/gm, ""), /\bsleep\s+\d{3,}\b/, "poll for the condition instead of sleeping");
    });
    it("every job that runs on a runner has a timeout-minutes", () => {
      for (const job of jobsOf(text).filter((j) => /^\s{4}runs-on:/m.test(j.text))) {
        assert.match(job.text, /^\s{4}timeout-minutes:\s*\d+/m, `${file}: job ${job.name} has no timeout-minutes`);
      }
    });
    it("Scorecard is not run on every push", () => {
      if (!/^name:\s*Scorecard/m.test(text)) return;
      assert.doesNotMatch(text.slice(0, text.search(/^jobs:/m)), /^\s{2}push:/m);
    });
    it("a gated job or step runs unless the gate said exactly false (fail open)", () => {
      for (const job of jobsOf(text).filter((j) => /^\s{4}needs:.*\bchanges\b/m.test(j.text))) {
        assert.match(job.text, /!cancelled\(\)/, `${file}: ${job.name} needs the gate, so its if must start with !cancelled()`);
        assert.doesNotMatch(job.text, /outputs\.[a-z-]+\s*==\s*'true'/, `${file}: ${job.name} must test != 'false', never == 'true'`);
      }
    });
    it("a reusable workflow is pinned by SHA", () => {
      for (const m of text.matchAll(/^\s*uses:\s*(krizaka\/\S+)/gm)) assert.match(m[1], /@[0-9a-f]{40}\b/, `${file}: ${m[1]}`);
    });
  });
}
