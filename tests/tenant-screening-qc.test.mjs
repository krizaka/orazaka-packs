// tenant-screening-qc (krizaka/orazaka-packs#123): the manifest, the blueprint, the worker and the dated ruleset say the same thing,
// and the promises of the README are checked, not remembered. The saga itself is run, path by path, by worker/test_screening.py.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../tenant-screening-qc/", import.meta.url).pathname;
const text = (p) => readFileSync(`${root}${p}`, "utf8");
const pack = text("pack.yaml");
const blueprint = JSON.parse(text("studios/tenant-screening-qc/blueprint.json"));
const ruleset = JSON.parse(text("rules/screening-cutoffs/2026-10-24.json"));
const golden = JSON.parse(text("tests/golden/tenant-screening-qc.json"));
const steps = blueprint.definition.steps;
const stepOf = (id) => steps.find((s) => s.id === id);
const walk = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((d) => (d.isDirectory() ? (d.name === ".venv" || d.name === "__pycache__" ? [] : walk(`${dir}${d.name}/`)) : [`${dir}${d.name}`]));

test("every capability the blueprint uses is contributed here, and drained by the worker", () => {
  const contributed = [...pack.matchAll(/^    - key: (orazaka\.[a-z.]+)$/gm)].map((m) => m[1]);
  assert.equal(contributed.length, 7);
  for (const s of steps) assert.ok(contributed.includes(s.featureKey), s.featureKey);
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

test("a stage runs only if the cut-off before it said CONTINUE, and only with consent: the order is documents, courts, credit", () => {
  assert.deepEqual(ruleset.stages.map((s) => s.id), ["documents", "courts", "credit"]);
  assert.equal(stepOf("consent_courts").condition, "{{steps.gate_documents.decision}} == 'CONTINUE'");
  assert.equal(stepOf("consent_credit").condition, "{{steps.gate_courts.decision}} == 'CONTINUE'");
  for (const stage of ["documents", "courts", "credit"]) {
    assert.equal(stepOf(stage).condition, `{{steps.consent_${stage}.status}} == 'GRANTED'`);
    assert.ok(stepOf(stage).dependsOn.includes(`consent_${stage}`));
    assert.equal(stepOf(`gate_${stage}`).inputs.stage, stage);
  }
  const order = steps.map((s) => s.id);
  for (const [a, b] of [["gate_documents", "consent_courts"], ["gate_courts", "consent_credit"], ["gate_credit", "report"]]) assert.ok(order.indexOf(a) < order.indexOf(b), `${a} before ${b}`);
});

test("no step is skipped on error: a failed step fails the run and the hold is refunded, never a silent pass", () => {
  for (const s of steps) assert.equal(s.onError, "FAIL", s.id);
});

test("the paid stages are metered by the call, the control steps are not", () => {
  for (const key of ["documents.assess", "courts.check", "credit.check"]) {
    const block = pack.split(`- key: orazaka.screening.${key}`)[1].split("      inputSchema:")[0];
    assert.match(block, /billableUnit: CALL/);
  }
  for (const key of ["plan", "consent.check", "cutoff.decide", "report.assemble"]) {
    const block = pack.split(new RegExp(`- key: orazaka\\.screening\\.${key.replace(".", "\\.")}\\n`))[1].split("      inputSchema:")[0];
    assert.doesNotMatch(block, /billable/);
  }
});

test("the cut-offs are data: the ruleset holds them, the worker's code names no rule", () => {
  for (const stage of ruleset.stages) {
    assert.ok(Number.isInteger(stage.credits) && stage.credits >= 0);
    for (const rule of stage.cutoffs) {
      assert.ok(stage.facts.includes(rule.fact), `${rule.id}: ${rule.fact}`);
      assert.ok(ruleset.operators.includes(rule.op));
    }
  }
  assert.deepEqual(ruleset.stages[0].cutoffs.map((r) => r.id), ["CUT-DOC-MAJOR-SIGNALS"]);
  assert.deepEqual(ruleset.stages[1].cutoffs.map((r) => r.id), ["CUT-COURT-FILE-FOUND"]);
  for (const f of ["screening.py", "handlers.py", "connectors.py", "screening_worker.py"]) assert.doesNotMatch(text(`worker/${f}`), /CUT-[A-Z]/, f);
  assert.ok(blueprint.inputSchema.properties.cutoffs, "the manager's rules are an input");
});

test("mocks only: the ruleset names the mock, the worker has no network client and names no provider endpoint", () => {
  assert.equal(ruleset.provider, "mock");
  assert.ok(ruleset.limits.includes("MOCK_PROVIDER_ONLY"));
  for (const f of ["screening.py", "handlers.py", "connectors.py", "screening_worker.py"]) {
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
    assert.doesNotMatch(body, /yomizaka|yasakia|orochia|akinaza/i, `${file}: a pack names no product`);
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
  for (const c of golden.cases) assert.match(c.input.subject.subjectId, /^fictional-/);
});

test("the Studio is worded in both languages", () => {
  for (const lang of ["en", "fr"]) assert.match(text(`i18n/${lang}.yaml`), /^  tenant-screening-qc:\n    label:/m);
});
