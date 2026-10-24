#!/usr/bin/env python3
"""The screening saga, every path, on the mock: the real blueprint is interpreted step by step (its conditions, its templates)
and each step runs the real handler. The only stand-in is the connector, which is the mock and counts its calls.

    python test_screening.py
"""

import io
import json
import os
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import yaml

import connectors
import handlers
import screening

HERE = os.path.dirname(os.path.abspath(__file__))
BLUEPRINT = json.load(open(os.path.join(HERE, "..", "studios", "tenant-screening-qc", "blueprint.json"), encoding="utf-8"))
PACK = yaml.safe_load(open(os.path.join(HERE, "..", "pack.yaml"), encoding="utf-8"))
ROUTING = {c["key"]: c["routingKey"] for c in PACK["requires"]["capabilities"]}

PLACEHOLDER = re.compile(r"\{\{([^{}]*)}}")
LONE = re.compile(r"\s*\{\{([^{}]*)}}\s*")
CONDITION = re.compile(r"\s*(\{\{[^{}]*}})\s*(?:(==|!=)\s*(null|true|false|-?\d+|'[^']*'|\"[^\"]*\")|is\s+(not\s+)?null)\s*")


class RunFailed(Exception):
    """A step refused its payload: the run fails, nothing after it ran."""


class Run:
    def __init__(self, outputs, executed, consumption, connector):
        self.outputs, self.executed, self.consumption, self.connector = outputs, executed, consumption, connector

    @property
    def report(self):
        return self.outputs["report"]["report"]


def resolve(ref, inputs, config, steps):
    head, *rest = ref.split(".")
    node = {"inputs": inputs, "config": config, "steps": steps}[head]
    for part in rest:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def render(template, inputs, config, steps):
    if not isinstance(template, str):
        return template
    def value(expression):
        ref, _, default = expression.partition(":")
        found = resolve(ref.strip(), inputs, config, steps)
        return default if found is None else found
    lone = LONE.fullmatch(template)
    if lone:
        return value(lone.group(1))
    return PLACEHOLDER.sub(lambda m: str(value(m.group(1))), template)


def holds(condition, inputs, config, steps):
    match = CONDITION.fullmatch(condition)
    assert match, f"unsupported condition {condition}"
    ref, operator, literal, negated = match.groups()
    found = resolve(PLACEHOLDER.fullmatch(ref).group(1).split(":")[0], inputs, config, steps)
    if operator is None:
        return (found is not None) == bool(negated)
    expected = None if literal == "null" else literal.strip("'\"")
    equal = (found is None and expected is None) or (found is not None and str(found).lower() == str(expected).lower())
    return equal == (operator == "==")


def run(inputs, config=None, fixtures=None, blueprint=BLUEPRINT):
    config = config or {}
    shared = connectors.MockConnector(**({"fixtures": fixtures} if fixtures else {}))
    steps, executed, consumption = {}, [], {}
    seen = set()
    with mock.patch.object(connectors, "connector_for", lambda provider: shared):
        for step in blueprint["definition"]["steps"]:
            assert set(step["dependsOn"]) <= seen, f"{step['id']} depends on a step that comes later"
            seen.add(step["id"])
            if step.get("condition") and not holds(step["condition"], inputs, config, steps):
                continue
            payload = {k: render(v, inputs, config, steps) for k, v in step["inputs"].items()}
            try:
                result, used = handlers.handle(ROUTING[step["featureKey"]], payload)
            except (screening.InvalidInput, connectors.ProviderNotEnabled) as bad:
                raise RunFailed(f"{step['id']}: {bad}") from bad
            steps[step["out"]] = result
            executed.append(step["id"])
            consumption[step["id"]] = used
    outputs = {o["key"]: {"report": json.loads(resolve(PLACEHOLDER.fullmatch(o["from"]).group(1), {}, {}, steps))} if o["key"] == "report" else resolve(PLACEHOLDER.fullmatch(o["from"]).group(1), {}, {}, steps) for o in blueprint["definition"]["outputs"]}
    return Run(outputs, executed, consumption, shared)


ALL = ["DOCUMENTS", "COURT_RECORDS", "CREDIT"]
CLEAN = {"signals": [{"signalId": "producer-known", "level": "observé"}, {"signalId": "font-mix", "level": "inhabituel"}]}
DOCTORED = {"signals": [{"signalId": "edited-after-issue", "level": "incohérent"}, {"signalId": "font-mix", "level": "inhabituel"}]}
LEASE = {"findings": [{"ruleId": "QC-LEASE-004", "verdict": "FAIL"}, {"ruleId": "QC-LEASE-001", "verdict": "PASS"}]}


def applicant(last="Gagnon", consents=ALL, report=CLEAN, **extra):
    inputs = {
        "subject": {"subjectId": "subj-0001", "lastName": last, "firstName": "Alex", "birthDate": "1990-01-01"},
        "consentedPurposes": list(consents),
        "authenticityReport": report,
        "leaseReport": LEASE,
    }
    return dict(inputs, **extra)


class AllPaths(unittest.TestCase):
    def test_all_clear_runs_the_three_stages_and_debits_each(self):
        r = run(applicant())
        self.assertEqual(r.report["status"], "COMPLETED")
        self.assertEqual([s["state"] for s in r.report["stages"]], ["RAN", "RAN", "RAN"])
        self.assertEqual(r.report["ledger"]["byStage"], {"documents": 10, "courts": 30, "credit": 20})
        self.assertEqual(r.report["ledger"]["total"], 60)
        self.assertEqual(r.connector.calls, ["COURT_RECORDS", "CREDIT"])
        self.assertEqual([r.consumption[s]["calls"] for s in ("documents", "courts", "credit")], [1, 1, 1])
        self.assertEqual(r.report["stages"][0]["facts"], {"majorSignals": 0, "unusualSignals": 1, "leaseFailures": 1})

    def test_a_stop_after_documents_never_reaches_a_provider(self):
        r = run(applicant(report=DOCTORED))
        self.assertEqual((r.report["status"], r.report["stoppedAt"], r.report["stopCode"], r.report["ruleId"]), ("STOPPED", "documents", "CUTOFF", "CUT-DOC-MAJOR-SIGNALS"))
        self.assertEqual([s["state"] for s in r.report["stages"]], ["RAN", "NOT_RUN", "NOT_RUN"])
        self.assertEqual(r.connector.calls, [])
        self.assertEqual(r.report["ledger"]["total"], 10)
        for later in ("consent_courts", "courts", "consent_credit", "credit"):
            self.assertNotIn(later, r.executed)

    def test_a_stop_after_court_records_never_calls_credit_and_never_charges_it(self):
        r = run(applicant("Tremblay"))
        self.assertEqual((r.report["status"], r.report["stoppedAt"], r.report["ruleId"]), ("STOPPED", "courts", "CUT-COURT-FILE-FOUND"))
        self.assertEqual(r.connector.calls, ["COURT_RECORDS"])
        credit = r.report["stages"][2]
        self.assertEqual((credit["state"], credit["charged"], credit["credits"]), ("NOT_RUN", False, 0))
        self.assertEqual(r.report["ledger"]["byStage"], {"documents": 10, "courts": 30, "credit": 0})
        self.assertNotIn("credit", r.executed)
        self.assertNotIn("consent_credit", r.executed)

    def test_a_provider_error_is_not_charged_and_stops_the_saga(self):
        r = run(applicant("Roy"))
        courts = r.report["stages"][1]
        self.assertEqual((courts["state"], courts["outcome"], courts["charged"], courts["credits"]), ("UNAVAILABLE", "PROVIDER_ERROR", False, 0))
        self.assertEqual((r.report["status"], r.report["stopCode"]), ("INCOMPLETE", "PROVIDER_ERROR"))
        self.assertEqual(r.consumption["courts"]["calls"], 0)
        self.assertEqual(r.report["ledger"]["total"], 10)
        self.assertEqual(r.connector.calls, ["COURT_RECORDS"])

    def test_a_timeout_is_not_charged_either(self):
        r = run(applicant("Bouchard"))
        self.assertEqual((r.report["stages"][1]["outcome"], r.report["stages"][1]["credits"], r.report["stopCode"]), ("TIMEOUT", 0, "TIMEOUT"))
        self.assertEqual(r.consumption["courts"]["calls"], 0)

    def test_a_missing_consent_stops_that_stage_visibly_before_any_call(self):
        r = run(applicant(consents=["DOCUMENTS", "CREDIT"]))
        courts = r.report["stages"][1]
        self.assertEqual((courts["state"], courts["consent"], courts["charged"]), ("REFUSED", "REFUSED", False))
        self.assertEqual((r.report["status"], r.report["stopCode"], r.report["stoppedAt"]), ("INCOMPLETE", "NO_CONSENT", "courts"))
        self.assertEqual(r.connector.calls, [])
        self.assertEqual(r.report["ledger"]["total"], 10)
        self.assertNotIn("courts", r.executed)

    def test_a_missing_consent_for_credit_stops_after_court_records(self):
        r = run(applicant(consents=["DOCUMENTS", "COURT_RECORDS"]))
        self.assertEqual((r.report["stages"][2]["state"], r.report["stopCode"], r.report["stoppedAt"]), ("REFUSED", "NO_CONSENT", "credit"))
        self.assertEqual(r.connector.calls, ["COURT_RECORDS"])
        self.assertEqual(r.report["ledger"]["total"], 40)

    def test_no_consent_at_all_charges_nothing(self):
        r = run(applicant(consents=[]))
        self.assertEqual(r.report["ledger"]["total"], 0)
        self.assertEqual(r.report["stopCode"], "NO_CONSENT")
        self.assertEqual(r.report["stoppedAt"], "documents")
        self.assertEqual(r.connector.calls, [])
        self.assertNotIn("documents", r.executed)

    def test_every_paid_stage_checks_consent_itself_so_no_route_skips_the_gate(self):
        shared = connectors.MockConnector()
        plan = screening.plan(dict(applicant(), applicantPaysFees=""))
        for fn in (screening.courts, screening.credit):
            result = fn({"plan": plan["planJson"], "subject": applicant()["subject"], "consentedPurposes": []}, shared)
            self.assertEqual((result["outcome"], result["charged"], result["credits"]), ("REFUSED", False, 0))
        self.assertEqual(shared.calls, [])
        refused = screening.documents({"plan": plan["planJson"], "authenticityReport": CLEAN, "consentedPurposes": None})
        self.assertEqual((refused["outcome"], refused["charged"]), ("REFUSED", False))


class CutoffsAreData(unittest.TestCase):
    def test_the_manager_replaces_the_default_of_a_stage(self):
        rules = {"courts": [], "credit": [{"id": "CUT-CREDIT-FILE", "fact": "outcome", "op": "equals", "value": "MATCH"}]}
        r = run(applicant("Tremblay", cutoffs=rules))
        self.assertEqual((r.report["status"], r.report["stoppedAt"], r.report["ruleId"]), ("STOPPED", "credit", "CUT-CREDIT-FILE"))
        self.assertEqual(r.report["ledger"]["total"], 60)
        self.assertEqual(r.connector.calls, ["COURT_RECORDS", "CREDIT"])

    def test_a_manager_rule_can_stop_on_a_lease_finding(self):
        rules = {"documents": [{"id": "CUT-LEASE-FAILS", "fact": "leaseFailures", "op": "atLeast", "value": 1}]}
        r = run(applicant(cutoffs=rules))
        self.assertEqual((r.report["stoppedAt"], r.report["ruleId"]), ("documents", "CUT-LEASE-FAILS"))
        self.assertEqual(r.connector.calls, [])

    def test_an_empty_list_removes_the_default_cutoff(self):
        r = run(applicant(report=DOCTORED, cutoffs={"documents": []}))
        self.assertEqual(r.report["status"], "COMPLETED")

    def test_the_default_is_the_dated_ruleset_and_the_report_names_its_version(self):
        r = run(applicant())
        ruleset = screening.load_ruleset()
        self.assertEqual((r.report["rulesetId"], r.report["rulesetVersion"]), (ruleset["rulesetId"], ruleset["version"]))

    def test_an_invalid_rule_fails_the_run_at_the_plan_before_any_charge(self):
        bad = [
            {"nowhere": []},
            {"courts": [{"id": "CUT-X-1", "fact": "salary", "op": "equals", "value": "MATCH"}]},
            {"courts": [{"id": "CUT-X-1", "fact": "outcome", "op": "contains", "value": "MATCH"}]},
            {"courts": [{"id": "x", "fact": "outcome", "op": "equals", "value": "MATCH"}]},
            {"courts": [{"id": "CUT-X-1", "fact": "outcome", "op": "equals", "value": "MATCH", "then": "GO"}]},
            {"documents": [{"id": "CUT-X-1", "fact": "majorSignals", "op": "atLeast", "value": -1}]},
            {"courts": [{"id": "CUT-X-1", "fact": "outcome", "op": "in", "value": []}]},
            {"courts": [{"id": f"CUT-X-{i}", "fact": "outcome", "op": "equals", "value": "MATCH"} for i in range(9)]},
            {"courts": [{"id": "CUT-X-1", "fact": "outcome", "op": "equals", "value": "MATCH"}] * 2},
        ]
        for cutoffs in bad:
            with self.assertRaises(RunFailed, msg=str(cutoffs)[:60]):
                run(applicant(cutoffs=cutoffs))

    def test_a_failed_plan_ran_nothing_else(self):
        with mock.patch.object(connectors, "connector_for") as factory:
            with self.assertRaises(RunFailed):
                run(applicant(cutoffs={"courts": "x"}))
            factory.assert_not_called()

    def test_budget_stops_before_a_stage_the_cap_cannot_pay(self):
        r = run(applicant(creditCap=50))
        self.assertEqual((r.report["status"], r.report["stopCode"], r.report["stoppedAt"]), ("INCOMPLETE", "BUDGET", "courts"))
        self.assertEqual(r.report["ledger"]["total"], 40)
        self.assertEqual(r.connector.calls, ["COURT_RECORDS"])
        self.assertNotIn("credit", r.executed)

    def test_a_cap_that_cannot_pay_the_first_stage_is_refused_at_the_plan(self):
        with self.assertRaises(RunFailed):
            run(applicant(creditCap=5))

    def test_a_cap_that_pays_everything_changes_nothing(self):
        self.assertEqual(run(applicant(creditCap=60)).report["status"], "COMPLETED")


class ApplicantPays(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(BLUEPRINT["configSchema"]["properties"]["applicantPaysFees"]["default"], False)
        r = run(applicant())
        self.assertEqual(r.report["ledger"]["payer"], "LANDLORD")
        self.assertNotIn("APPLICANT_PAYS_FEES_MAY_CONTRAVENE_CCQ_1904", r.report["limits"])

    def test_it_is_the_installation_setting_never_a_run_input(self):
        self.assertNotIn("applicantPaysFees", BLUEPRINT["inputSchema"]["properties"])
        plan = BLUEPRINT["definition"]["steps"][0]["inputs"]["applicantPaysFees"]
        self.assertEqual(plan, "{{config.applicantPaysFees:false}}")
        # a run input of that name is ignored: the plan reads the configuration only
        r = run(dict(applicant(), applicantPaysFees=True))
        self.assertEqual(r.report["ledger"]["payer"], "LANDLORD")

    def test_when_the_manager_turns_it_on_the_report_says_so_and_cites_the_article(self):
        r = run(applicant(), config={"applicantPaysFees": "true"})
        self.assertEqual(r.report["ledger"]["payer"], "APPLICANT")
        self.assertIn("APPLICANT_PAYS_FEES_MAY_CONTRAVENE_CCQ_1904", r.report["limits"])

    def test_a_setting_that_is_not_a_boolean_is_refused(self):
        with self.assertRaises(RunFailed):
            run(applicant(), config={"applicantPaysFees": "yes"})


class NoRawPersonalData(unittest.TestCase):
    NAMES = ("Gagnon", "Tremblay", "Roy", "Bouchard", "Alex", "1990-01-01")

    def test_no_step_output_carries_a_name_or_a_birth_date(self):
        for last in ("Gagnon", "Tremblay", "Roy", "Bouchard"):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                r = run(applicant(last))
            text = json.dumps(r.outputs) + json.dumps(r.consumption) + out.getvalue() + err.getvalue()
            for name in self.NAMES:
                self.assertNotIn(name, text, f"{name} leaked for {last}")
            self.assertIn("subj-0001", r.outputs["report"]["report"]["subjectRef"])

    def test_the_provider_reference_is_derived_from_the_opaque_id_not_from_a_name(self):
        answer = connectors.MockConnector().verify_court_records(connectors.Subject("subj-0001", "Tremblay", "Alex"))
        self.assertTrue(answer.provider_ref.startswith("mock-"))
        self.assertNotIn("Tremblay", answer.provider_ref)

    def test_a_subject_never_prints_its_names(self):
        subject = connectors.Subject("subj-0001", "Tremblay", "Alex", "1990-01-01")
        for text in (repr(subject), str(subject), f"{subject}"):
            for name in self.NAMES:
                self.assertNotIn(name, text)

    def test_an_error_message_never_repeats_a_value(self):
        try:
            run(applicant(cutoffs={"courts": [{"id": "CUT-X-1", "fact": "Tremblay", "op": "equals", "value": "MATCH"}]}))
        except RunFailed as bad:
            self.assertNotIn("Tremblay", str(bad).replace("this stage knows", ""))
        else:
            self.fail("an unknown fact must fail the plan")


class Providers(unittest.TestCase):
    def test_only_the_mock_exists(self):
        self.assertIsInstance(connectors.connector_for("mock"), connectors.MockConnector)
        for provider in ("soquij", "trustii", "certn", ""):
            with self.assertRaises(connectors.ProviderNotEnabled):
                connectors.connector_for(provider)

    def test_the_ruleset_names_the_mock_and_says_so_in_its_limits(self):
        ruleset = screening.load_ruleset()
        self.assertEqual(ruleset["provider"], "mock")
        self.assertIn("MOCK_PROVIDER_ONLY", ruleset["limits"])

    def test_the_fixtures_cover_a_match_no_match_an_error_and_a_timeout(self):
        subject = lambda last: connectors.Subject("s", last, "A")  # noqa: E731
        outcomes = {name: connectors.MockConnector().verify_credit(subject(name)).outcome for name in ("Tremblay", "Gagnon", "Roy", "Bouchard", "Unknown")}
        self.assertEqual(outcomes, {"Tremblay": "MATCH", "Gagnon": "NO_MATCH", "Roy": "PROVIDER_ERROR", "Bouchard": "TIMEOUT", "Unknown": "NO_MATCH"})

    def test_a_stage_that_is_not_a_handler_is_refused(self):
        with self.assertRaises(ValueError):
            handlers.handle("job.screening.nothing", {})


class Blueprint(unittest.TestCase):
    def test_the_conditions_gate_each_paid_step_on_the_previous_cutoff(self):
        steps = {s["id"]: s for s in BLUEPRINT["definition"]["steps"]}
        self.assertEqual(steps["consent_courts"]["condition"], "{{steps.gate_documents.decision}} == 'CONTINUE'")
        self.assertEqual(steps["consent_credit"]["condition"], "{{steps.gate_courts.decision}} == 'CONTINUE'")
        for stage in ("documents", "courts", "credit"):
            self.assertEqual(steps[stage]["condition"], f"{{{{steps.consent_{stage}.status}}}} == 'GRANTED'")

    def test_no_step_may_fail_silently(self):
        for step in BLUEPRINT["definition"]["steps"]:
            self.assertEqual(step["onError"], "FAIL", step["id"])

    def test_every_capability_of_the_blueprint_is_contributed_and_routed(self):
        for step in BLUEPRINT["definition"]["steps"]:
            self.assertIn(step["featureKey"], ROUTING)
            self.assertIn(ROUTING[step["featureKey"]], handlers.HANDLERS)


class FakeChannel:
    def __init__(self):
        self.published, self.acked, self.nacked = [], [], []

    def basic_publish(self, exchange, routing_key, body, properties=None):
        self.published.append((exchange, routing_key, json.loads(body)))

    def basic_ack(self, delivery_tag):
        self.acked.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacked.append((delivery_tag, requeue))


class Shell(unittest.TestCase):
    """The AMQP shell: done and error events, the cause of each, the replay of a message, and what the log says."""

    def setUp(self):
        import screening_worker
        self.channel = FakeChannel()
        self.consumer = screening_worker.Consumer(self.channel)

    def deliver(self, key, job, message_id="m-1", tag=1):
        method = type("M", (), {"routing_key": key, "delivery_tag": tag})()
        self.consumer(self.channel, method, type("P", (), {"message_id": message_id})(), json.dumps(job).encode())

    def test_a_job_is_answered_with_its_result_and_what_it_cost(self):
        plan = screening.plan(applicant())
        payload = {"plan": plan["planJson"], "subject": applicant()["subject"], "consentedPurposes": ALL}
        with mock.patch.object(connectors, "connector_for", lambda provider: connectors.MockConnector()):
            self.deliver("job.screening.courts", {"jobId": "j-1", "payload": payload})
        exchange, key, body = self.channel.published[0]
        self.assertEqual((exchange, key, body["jobId"], body["consumption"]), ("orazaka.events", "job.j-1.done", "j-1", {"tokens": 0, "calls": 1}))
        self.assertEqual(self.channel.acked, [1])

    def test_a_refused_payload_is_input_invalid_and_a_crash_is_an_executor_fault(self):
        self.deliver("job.screening.plan", {"jobId": "j-2", "payload": {}})
        self.deliver("job.screening.nothing", {"jobId": "j-3", "payload": {}}, "m-3", 2)
        causes = [body["cause"] for _, _, body in self.channel.published]
        self.assertEqual(causes, ["INPUT_INVALID", "EXECUTOR_FAULT"])
        self.assertEqual(self.channel.acked, [1, 2])

    def test_a_replayed_message_is_acknowledged_and_not_run_twice(self):
        job = {"jobId": "j-4", "payload": {"purpose": "CREDIT", "consentedPurposes": ["CREDIT"]}}
        self.deliver("job.screening.consent", job)
        self.deliver("job.screening.consent", job, tag=2)
        self.assertEqual(len(self.channel.published), 1)
        self.assertEqual(self.channel.acked, [1, 2])

    def test_unreadable_bytes_are_dead_lettered_not_requeued(self):
        method = type("M", (), {"routing_key": "job.screening.plan", "delivery_tag": 9})()
        self.consumer(self.channel, method, type("P", (), {"message_id": None})(), b"not json")
        self.assertEqual(self.channel.nacked, [(9, False)])

    def test_the_log_carries_the_job_id_and_the_routing_key_only(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.deliver("job.screening.plan", {"jobId": "j-5", "payload": dict(applicant("Tremblay"), cutoffs={"nowhere": []})})
            self.deliver("job.screening.nothing", {"jobId": "j-6", "payload": applicant("Tremblay")}, "m-6", 2)
        for name in NoRawPersonalData.NAMES:
            self.assertNotIn(name, out.getvalue())
        self.assertIn("job j-5", out.getvalue())


if __name__ == "__main__":
    unittest.main()
