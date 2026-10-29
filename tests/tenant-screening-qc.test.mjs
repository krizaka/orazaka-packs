// tenant-screening-qc (krizaka/orazaka-packs#123): the manifest, the blueprint, the worker and the dated ruleset say the same thing,
// and the promises of the README are checked, not remembered. The saga itself is run, path by path, by worker/test_screening.py.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import YAML from "yaml";

const root = new URL("../tenant-screening-qc/", import.meta.url).pathname;
const text = (p) => readFileSync(`${root}${p}`, "utf8");
const pack = text("pack.yaml");
const blueprint = JSON.parse(text("studios/tenant-screening-qc/blueprint.json"));
const rulesets = readdirSync(`${root}rules/screening-cutoffs/`).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).sort();
const ruleset = JSON.parse(text(`rules/screening-cutoffs/${rulesets.at(-1)}`)); // the one in force: the latest date
const checks = JSON.parse(readFileSync(new URL("./contracts/orazaka-core-checks.json", import.meta.url), "utf8"));
// The engine's capabilities, as this pack's steps see them (the contract the job-service executor answers).
const engine = Object.fromEntries(Object.keys(checks.featureKeys).map((key) => [key, {
  key,
  inputSchema: { properties: Object.fromEntries(Object.keys(checks.inputs).map((k) => [k, {}])) },
  outputSchema: { properties: Object.fromEntries(checks.outputs.map((k) => [k, {}])) },
}]));
const golden = JSON.parse(text("tests/golden/tenant-screening-qc.json"));
const steps = blueprint.definition.steps;
const stepOf = (id) => steps.find((s) => s.id === id);
const walk = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((d) => (d.isDirectory() ? (d.name === ".venv" || d.name === "__pycache__" ? [] : walk(`${dir}${d.name}/`)) : [`${dir}${d.name}`]));

test("every capability the blueprint uses is contributed here or is the engine's, and the pack's own are drained by the worker", () => {
  const contributed = [...pack.matchAll(/^    - key: (orazaka\.[a-z.]+)$/gm)].map((m) => m[1]);
  assert.equal(contributed.length, 5);
  for (const s of steps) assert.ok(contributed.includes(s.featureKey) || Object.hasOwn(engine, s.featureKey), s.featureKey);
  assert.match(text("worker/worker.yaml"), /- "job\.screening\.\*"/);
  assert.match(pack, /name: orazaka-worker-screening\n\s+bindings:\n\s+- "job\.screening\.\*"/);
  const handlers = text("worker/handlers.py");
  for (const key of pack.matchAll(/routingKey: (job\.screening\.[a-z]+)/g)) assert.ok(handlers.includes(`"${key[1]}"`), key[1]);
});

test("a step input only reads inputs the Studio declares, the configuration it declares, and steps that come before it", () => {
  const declared = new Set(Object.keys(blueprint.inputSchema.properties));
  const config = new Set(Object.keys(blueprint.configSchema.properties));
  const outs = new Map(steps.map((s) => [s.out, s.id]));
  const earlier = new Set();
  for (const s of steps) {
    for (const value of [...Object.values(s.inputs), s.condition ?? ""]) {
      for (const m of String(value).matchAll(/\{\{inputs\.([A-Za-z0-9]+)/g)) assert.ok(declared.has(m[1]), `${s.id}: unknown input ${m[1]}`);
      for (const m of String(value).matchAll(/\{\{config\.([A-Za-z0-9]+)/g)) assert.ok(config.has(m[1]), `${s.id}: unknown setting ${m[1]}`);
      for (const m of String(value).matchAll(/\{\{steps\.([A-Za-z0-9_]+)/g)) {
        const producer = outs.get(m[1]);
        assert.ok(producer && earlier.has(producer), `${s.id}: ${m[1]} is not produced by an earlier step`);
        assert.ok(s.dependsOn.includes(producer), `${s.id} must depend on ${producer}`);
      }
    }
    earlier.add(s.id);
  }
});

test("a step passes only inputs its capability declares, and reads only output fields the producer declares (the Studio service's fitness test)", () => {
  const caps = { ...engine, ...Object.fromEntries(YAML.parse(pack).requires.capabilities.map((c) => [c.key, c])) };
  for (const s of steps) {
    const declared = Object.keys(caps[s.featureKey].inputSchema.properties);
    for (const key of Object.keys(s.inputs)) assert.ok(declared.includes(key), `${s.id} passes '${key}', which ${s.featureKey} does not declare`);
    for (const value of Object.values(s.inputs)) {
      for (const m of String(value).matchAll(/\{\{steps\.([A-Za-z0-9_]+)\.([A-Za-z0-9]+)/g)) {
        const producer = steps.find((t) => t.out === m[1]);
        assert.ok(Object.hasOwn(caps[producer.featureKey].outputSchema.properties, m[2]), `${s.id} reads ${m[1]}.${m[2]}, which ${producer.featureKey} does not declare`);
      }
    }
  }
});

test("a stage runs only if the cut-off before it said CONTINUE, and only with consent: the order is documents, courts, credit", () => {
  assert.deepEqual(ruleset.stages.map((s) => s.id), ["documents", "courts", "credit"]);
  assert.equal(stepOf("consent-courts").condition, "{{steps.gate_documents.decision}} == 'CONTINUE'");
  assert.equal(stepOf("consent-credit").condition, "{{steps.gate_courts.decision}} == 'CONTINUE'");
  for (const stage of ["documents", "courts", "credit"]) {
    assert.equal(stepOf(stage).condition, `{{steps.consent_${stage}.status}} == 'GRANTED'`);
    assert.ok(stepOf(stage).dependsOn.includes(`consent-${stage}`));
    assert.equal(stepOf(`gate-${stage}`).inputs.stage, stage);
  }
  const order = steps.map((s) => s.id);
  for (const [a, b] of [["gate-documents", "consent-courts"], ["gate-courts", "consent-credit"], ["gate-credit", "report"]]) assert.ok(order.indexOf(a) < order.indexOf(b), `${a} before ${b}`);
});

test("no step is skipped on error: a failed step fails the run and the hold is refunded, never a silent pass", () => {
  for (const s of steps) assert.equal(s.onError, "FAIL", s.id);
});

test("one door: the court records and the credit are the engine's checks, called with its contract, never the pack's own", () => {
  assert.equal(stepOf("courts").featureKey, "orazaka.core.checks.courtrecords");
  assert.equal(stepOf("credit").featureKey, "orazaka.core.checks.credit");
  for (const stage of ["courts", "credit"]) {
    assert.deepEqual(stepOf(stage).inputs, { subject: "{{inputs.subject}}", consentedPurposes: "{{inputs.consentedPurposes}}" });
    const purpose = ruleset.stages.find((s) => s.id === stage).purpose;
    assert.equal(checks.featureKeys[stepOf(stage).featureKey], purpose, `${stage} is consented to as ${purpose}`);
  }
  assert.doesNotMatch(pack, /orazaka\.screening\.(courts|credit)\.check|job\.screening\.(courts|credit)\b/);
  assert.doesNotMatch(text("worker/handlers.py"), /job\.screening\.(courts|credit)|screening\.(courts|credit)\b/);
  assert.equal(walk(`${root}worker/`).some((f) => f.endsWith("/connectors.py")), false, "the pack keeps no connector of its own");
});

test("the paid stages are metered by the call, the control steps are declared not billable", () => {
  const block = pack.split("- key: orazaka.screening.documents.assess")[1].split("      inputSchema:")[0];
  assert.match(block, /billableUnit: CALL/);
  for (const key of ["plan", "consent.check", "cutoff.decide", "report.assemble"]) {
    const block = pack.split(new RegExp(`- key: orazaka\\.screening\\.${key.replace(".", "\\.")}\\n`))[1].split("      inputSchema:")[0];
    assert.match(block, /billableCapability: NONE\n/);
    assert.doesNotMatch(block, /billableUnit/);
  }
});

test("the cut-offs are data: the ruleset holds them, the worker's code names no rule", () => {
  for (const stage of ruleset.stages) {
    assert.ok(Number.isInteger(stage.credits) && stage.credits >= 0);
    for (const rule of stage.cutoffs) {
      assert.ok(stage.facts.includes(rule.fact), `${rule.id}: ${rule.fact}`);
      assert.ok(ruleset.operators.includes(rule.op));
      for (const v of [rule.value].flat()) if (stage.values?.[rule.fact]) assert.ok(stage.values[rule.fact].includes(v), `${rule.id}: ${v}`);
    }
  }
  assert.deepEqual(ruleset.stages[0].cutoffs.map((r) => r.id), ["CUT-DOC-MAJOR-SIGNALS"]);
  assert.deepEqual(ruleset.stages[1].cutoffs.map((r) => r.id), ["CUT-COURT-FILE-FOUND"]);
  for (const f of ["screening.py", "handlers.py", "screening_worker.py"]) assert.doesNotMatch(text(`worker/${f}`), /CUT-[A-Z]/, f);
  assert.ok(blueprint.inputSchema.properties.cutoffs, "the manager's rules are an input");
});

test("mocks only: the ruleset names the mock, the worker has no network client and names no provider endpoint", () => {
  assert.equal(ruleset.provider, "mock");
  assert.ok(ruleset.limits.includes("MOCK_PROVIDER_ONLY"));
  for (const f of ["screening.py", "handlers.py", "screening_worker.py"]) {
    const body = text(`worker/${f}`).replace(/^\s*#.*$/gm, "");
    assert.doesNotMatch(body, /\b(requests|urllib|http\.client|httpx|aiohttp|socket)\b|https?:\/\//, f);
  }
  assert.match(pack, /status: DRAFT/m);
  assert.equal(blueprint.status, "DRAFT");
});

test("the applicant does not pay by default, and it is a setting, never a run input", () => {
  assert.equal(blueprint.configSchema.properties.applicantPaysFees.default, false);
  assert.equal(blueprint.inputSchema.properties.applicantPaysFees, undefined);
  assert.equal(stepOf("plan").inputs.applicantPaysFees, "{{config.applicantPaysFees:false}}");
  assert.ok(ruleset.limits.includes("APPLICANT_DOES_NOT_PAY_BY_DEFAULT"));
});

test("sensitive, guarded, decides nothing, a lone Studio, and carries no product word", () => {
  assert.match(pack, /^regulatoryClass: SENSITIVE$/m);
  assert.match(pack, /^scopeGuard:/m);
  assert.doesNotMatch(pack, /^catalog:/m);
  assert.ok(ruleset.limits.includes("NO_DECISION_ON_THE_APPLICANT"));
  assert.ok(ruleset.limits.includes("A_STOP_IS_A_CUTOFF_NOT_A_VERDICT"));
  for (const file of walk(root).filter((f) => /\.(py|yaml|json)$/.test(f))) {
    const body = readFileSync(file, "utf8").replace(/^\s*#.*$/gm, "");
    assert.doesNotMatch(body, /yomizaka|akinaza/i, `${file}: a pack names no product`);
  }
});

test("the worker never logs more than the job id and the routing key", () => {
  const worker = text("worker/screening_worker.py");
  for (const line of worker.split("\n").filter((l) => l.includes("print("))) assert.doesNotMatch(line, /payload|subject|lastName|firstName|result|outcome/i, line.trim());
});

test("the goldens cover the five paths and are all fictional", () => {
  assert.deepEqual(golden.cases.map((c) => c.id), [
    "clean-applicant-runs-all-three-stages",
    "doctored-pay-stub-stops-at-documents",
    "tal-file-found-stops-before-credit",
    "provider-error-is-not-charged",
    "missing-court-consent-stops-visibly",
  ]);
  const by = Object.fromEntries(golden.cases.map((c) => [c.id, c.expected.report]));
  assert.equal(by["doctored-pay-stub-stops-at-documents"].stoppedAt, "documents");
  assert.equal(by["doctored-pay-stub-stops-at-documents"].ledger.byStage.courts, 0);
  assert.equal(by["tal-file-found-stops-before-credit"].ledger.byStage.credit, 0);
  assert.equal(by["clean-applicant-runs-all-three-stages"].ledger.total, ruleset.stages.reduce((n, s) => n + s.credits, 0));
  assert.equal(by["provider-error-is-not-charged"].stages[1].credits, 0);
  assert.deepEqual(by["tal-file-found-stops-before-credit"].stages[1].facts, { outcome: "MATCH", category: "TAL_NON_PAYMENT" });
  for (const c of golden.cases) assert.equal(c.expected.report.rulesetVersion, ruleset.version, `${c.id} reads the ruleset in force`);
  for (const c of golden.cases) assert.match(c.input.subject.subjectId, /^fictional-/);
});

test("the Studio is worded in both languages", () => {
  for (const lang of ["en", "fr"]) assert.match(text(`i18n/${lang}.yaml`), /^  tenant-screening-qc:\n    label:/m);
});

test("a ruleset is dated data: a change is a new dated file, the older ones stay as they were", () => {
  assert.deepEqual(rulesets, ["2026-10-24.json", "2026-10-25.json"]);
  for (const file of rulesets) assert.equal(JSON.parse(text(`rules/screening-cutoffs/${file}`)).version, file.slice(0, 10));
  const first = JSON.parse(text("rules/screening-cutoffs/2026-10-24.json"));
  assert.deepEqual(first.stages.find((s) => s.id === "courts").facts, ["outcome"], "2026-10-24 is never rewritten");
});

test("the engine's court-records category is a fact a cut-off can read, from the engine's closed set", () => {
  const courts = ruleset.stages.find((s) => s.id === "courts");
  assert.deepEqual(courts.facts, ["outcome", "category"]);
  assert.deepEqual(courts.values.category, checks.category);
  assert.deepEqual(courts.values.outcome, checks.answered, "a cut-off reads an answer; the rest stops before any rule");
  const credit = ruleset.stages.find((s) => s.id === "credit");
  assert.deepEqual(credit.facts, ["outcome"], "credit answers no category");
});

test("the versions say what changed: the pack lost two capabilities (major), the Studio is still a DRAFT on mocks", () => {
  assert.match(pack, /^version: 2\.0\.0$/m);
  assert.match(text("worker/worker.yaml"), /^version: "2\.0\.0"$/m);
  assert.equal(blueprint.version, "1.1.0");
  assert.equal(blueprint.definition.version, blueprint.version);
  assert.match(blueprint.changelog, /^1\.1\.0 — /);
  assert.match(blueprint.changelog, /orazaka\.core\.checks/);
});
