#!/usr/bin/env python3
"""The screening saga, every path, on the mock: the real blueprint is interpreted step by step (its conditions, its templates)
and each of the pack's steps runs the real handler. The court-records and credit steps are the engine's checks
(``orazaka.core.checks.*``, orazaka-packs#138): the only stand-in is ``FakeEngine``, which answers them exactly as the
job-service executor does (the contract ``tests/contracts/orazaka-core-checks.json``, the fixtures of the engine's
``MockConnector``) and counts its provider calls.

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

import handlers
import screening

HERE = os.path.dirname(os.path.abspath(__file__))
BLUEPRINT = json.load(open(os.path.join(HERE, "..", "studios", "tenant-screening-qc", "blueprint.json"), encoding="utf-8"))
BLUEPRINT_STEPS = {s["id"]: s for s in BLUEPRINT["definition"]["steps"]}
PACK = yaml.safe_load(open(os.path.join(HERE, "..", "pack.yaml"), encoding="utf-8"))
ROUTING = {c["key"]: c["routingKey"] for c in PACK["requires"]["capabilities"]}
CONTRACT = json.load(open(os.path.join(HERE, "..", "..", "tests", "contracts", "orazaka-core-checks.json"), encoding="utf-8"))

PLACEHOLDER = re.compile(r"\{\{([^{}]*)}}")
LONE = re.compile(r"\s*\{\{([^{}]*)}}\s*")
CONDITION = re.compile(r"\s*(\{\{[^{}]*}})\s*(?:(==|!=)\s*(null|true|false|-?\d+|'[^']*'|\"[^\"]*\")|is\s+(not\s+)?null)\s*")


class RunFailed(Exception):
    """A step refused its payload: the run fails, nothing after it ran."""


class FakeEngine:
    """The engine's checks as a step sees them: consent from ``consentedPurposes``, then the key, then one provider call.

    The answers are the engine's ``MockConnector`` fixtures, chosen by the last name (orazaka-ai-engine#90): Tremblay has a TAL
    non-payment file, Côté another TAL file, Morin a criminal one, Lavoie a civil one, Gagnon none, Roy is a provider error,
    Bouchard a timeout; anyone else has no match. Only court records answer a category. ``calls`` lists the purposes that
    reached the provider, so a test proves a stage was never called.
    """

    FIXTURES = {
        "Tremblay": ("MATCH", "TAL_NON_PAYMENT", "mock-fixture-01"),
        "Côté": ("MATCH", "TAL_OTHER", "mock-fixture-02"),
        "Morin": ("MATCH", "CRIMINAL", "mock-fixture-03"),
        "Lavoie": ("MATCH", "CIVIL", "mock-fixture-04"),
        "Gagnon": ("NO_MATCH", "NONE", "mock-fixture-05"),
        "Roy": ("PROVIDER_ERROR", "NONE", "mock-fixture-06"),
        "Bouchard": ("TIMEOUT", "NONE", "mock-fixture-07"),
    }

    def __init__(self, refusal=None):
        self.calls, self.refusal = [], refusal

    def __call__(self, feature_key, payload):
        purpose = CONTRACT["featureKeys"][feature_key]
        assert set(payload) == set(CONTRACT["inputs"]), f"{feature_key} called with {sorted(payload)}"
        subject = payload["subject"]
        assert isinstance(subject, dict) and {"subjectId", "lastName", "firstName"} <= set(subject)
        consented = payload["consentedPurposes"]
        refusal = "NO_CONSENT" if not (isinstance(consented, list) and purpose in consented) else self.refusal
        if refusal:
            result = {"outcome": "REFUSED", "refusal": refusal, "category": "NONE", "providerRef": None, "calls": 0}
        else:
            self.calls.append(purpose)
            outcome, category, ref = self.FIXTURES.get(subject["lastName"], ("NO_MATCH", "NONE", None))
            matched = outcome == "MATCH"
            result = {
                "outcome": outcome,
                "refusal": None,
                "category": category if matched and purpose == "COURT_RECORDS" else "NONE",
                "providerRef": ref if matched else None,
                "calls": 1 if outcome in CONTRACT["answered"] else 0,
            }
        out = dict(result, resultJson=json.dumps(result))
        assert sorted(out) == sorted(CONTRACT["outputs"])
        return out, {"calls": result["calls"]}


class Run:
    def __init__(self, outputs, executed, consumption, engine):
        self.outputs, self.executed, self.consumption, self.engine = outputs, executed, consumption, engine

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


def run(inputs, config=None, engine=None, blueprint=BLUEPRINT):
    config = config or {}
    engine = engine or FakeEngine()
    steps, executed, consumption = {}, [], {}
    seen = set()
    for step in blueprint["definition"]["steps"]:
        assert set(step["dependsOn"]) <= seen, f"{step['id']} depends on a step that comes later"
        seen.add(step["id"])
        if step.get("condition") and not holds(step["condition"], inputs, config, steps):
            continue
        payload = {k: render(v, inputs, config, steps) for k, v in step["inputs"].items()}
        try:
            if step["featureKey"] in CONTRACT["featureKeys"]:
                result, used = engine(step["featureKey"], payload)
            else:
                result, used = handlers.handle(ROUTING[step["featureKey"]], payload)
        except screening.InvalidInput as bad:
            raise RunFailed(f"{step['id']}: {bad}") from bad
        steps[step["out"]] = result
        executed.append(step["id"])
        consumption[step["id"]] = used
    outputs = {o["key"]: {"report": json.loads(resolve(PLACEHOLDER.fullmatch(o["from"]).group(1), {}, {}, steps))} if o["key"] == "report" else resolve(PLACEHOLDER.fullmatch(o["from"]).group(1), {}, {}, steps) for o in blueprint["definition"]["outputs"]}
    return Run(outputs, executed, consumption, engine)


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
        self.assertEqual(r.engine.calls, ["COURT_RECORDS", "CREDIT"])
        self.assertEqual([r.consumption[s]["calls"] for s in ("documents", "courts", "credit")], [1, 1, 1])
        self.assertEqual(r.report["stages"][0]["facts"], {"majorSignals": 0, "unusualSignals": 1, "leaseFailures": 1})
        self.assertEqual(r.report["stages"][1]["facts"], {"outcome": "NO_MATCH", "category": "NONE"})
        self.assertEqual(r.report["stages"][2]["facts"], {"outcome": "NO_MATCH"})

    def test_a_stop_after_documents_never_reaches_a_provider(self):
        r = run(applicant(report=DOCTORED))
        self.assertEqual((r.report["status"], r.report["stoppedAt"], r.report["stopCode"], r.report["ruleId"]), ("STOPPED", "documents", "CUTOFF", "CUT-DOC-MAJOR-SIGNALS"))
        self.assertEqual([s["state"] for s in r.report["stages"]], ["RAN", "NOT_RUN", "NOT_RUN"])
        self.assertEqual(r.engine.calls, [])
        self.assertEqual(r.report["ledger"]["total"], 10)
        for later in ("consent_courts", "courts", "consent_credit", "credit"):
            self.assertNotIn(later, r.executed)

    def test_a_stop_after_court_records_never_calls_credit_and_never_charges_it(self):
        r = run(applicant("Tremblay"))
        self.assertEqual((r.report["status"], r.report["stoppedAt"], r.report["ruleId"]), ("STOPPED", "courts", "CUT-COURT-FILE-FOUND"))
        self.assertEqual(r.engine.calls, ["COURT_RECORDS"])
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
        self.assertEqual(r.engine.calls, ["COURT_RECORDS"])

    def test_a_timeout_is_not_charged_either(self):
        r = run(applicant("Bouchard"))
        self.assertEqual((r.report["stages"][1]["outcome"], r.report["stages"][1]["credits"], r.report["stopCode"]), ("TIMEOUT", 0, "TIMEOUT"))
        self.assertEqual(r.consumption["courts"]["calls"], 0)

    def test_a_missing_consent_stops_that_stage_visibly_before_any_call(self):
        r = run(applicant(consents=["DOCUMENTS", "CREDIT"]))
        courts = r.report["stages"][1]
        self.assertEqual((courts["state"], courts["consent"], courts["charged"]), ("REFUSED", "REFUSED", False))
        self.assertEqual((r.report["status"], r.report["stopCode"], r.report["stoppedAt"]), ("INCOMPLETE", "NO_CONSENT", "courts"))
        self.assertEqual(r.engine.calls, [])
        self.assertEqual(r.report["ledger"]["total"], 10)
        self.assertNotIn("courts", r.executed)

    def test_a_missing_consent_for_credit_stops_after_court_records(self):
        r = run(applicant(consents=["DOCUMENTS", "COURT_RECORDS"]))
        self.assertEqual((r.report["stages"][2]["state"], r.report["stopCode"], r.report["stoppedAt"]), ("REFUSED", "NO_CONSENT", "credit"))
        self.assertEqual(r.engine.calls, ["COURT_RECORDS"])
        self.assertEqual(r.report["ledger"]["total"], 40)

    def test_no_consent_at_all_charges_nothing(self):
        r = run(applicant(consents=[]))
        self.assertEqual(r.report["ledger"]["total"], 0)
        self.assertEqual(r.report["stopCode"], "NO_CONSENT")
        self.assertEqual(r.report["stoppedAt"], "documents")
        self.assertEqual(r.engine.calls, [])
        self.assertNotIn("documents", r.executed)

    def test_every_paid_stage_is_gated_on_consent_where_it_runs_so_no_route_skips_the_gate(self):
        plan = screening.plan(dict(applicant(), applicantPaysFees=""))
        refused = screening.documents({"plan": plan["planJson"], "authenticityReport": CLEAN, "consentedPurposes": None})
        self.assertEqual((refused["outcome"], refused["charged"]), ("REFUSED", False))
        # the engine's checks receive the consents and refuse on their own: the pack's consent step is not the only gate
        for stage in ("courts", "credit"):
            self.assertEqual(BLUEPRINT_STEPS[stage]["inputs"]["consentedPurposes"], "{{inputs.consentedPurposes}}")
        engine = FakeEngine()
        out, used = engine("orazaka.core.checks.courtrecords", {"subject": applicant()["subject"], "consentedPurposes": []})
        self.assertEqual((out["outcome"], out["refusal"], used), ("REFUSED", "NO_CONSENT", {"calls": 0}))
        self.assertEqual(engine.calls, [])

    def test_an_engine_refusal_for_consent_stays_no_consent_even_when_the_pack_saw_one(self):
        plan = screening.plan(applicant())["planJson"]
        engine = {"outcome": "REFUSED", "refusal": "NO_CONSENT", "category": "NONE", "providerRef": None, "calls": 0}
        gate = screening.cutoff({"plan": plan, "stage": "courts", "consent": "GRANTED", "result": json.dumps(engine), "spentCredits": 10})
        self.assertEqual((gate["decision"], gate["code"], gate["spentCredits"]), ("STOP", "NO_CONSENT", 10))
        body = screening.report({"plan": plan, "courtsResult": json.dumps(engine), "courtsGate": gate["decisionJson"], "courtsConsent": "GRANTED"})["report"]
        courts = body["stages"][1]
        self.assertEqual((courts["state"], courts["charged"], courts["credits"], body["stopCode"]), ("REFUSED", False, 0, "NO_CONSENT"))


class TheEnginesAnswer(unittest.TestCase):
    """The gates and the report read the engine's ``CheckStepResult``: credits only when ``calls == 1``, a closed category."""

    def plan(self, **extra):
        return screening.plan(applicant(**extra))["planJson"]

    def gate(self, engine, stage="courts", plan=None):
        return screening.cutoff({"plan": plan or self.plan(), "stage": stage, "consent": "GRANTED", "result": json.dumps(engine), "spentCredits": 10})

    def answer(self, outcome="NO_MATCH", category="NONE", calls=1, refusal=None, ref=None):
        return {"outcome": outcome, "refusal": refusal, "category": category, "providerRef": ref, "calls": calls}

    def test_a_key_or_a_budget_the_engine_refuses_is_charged_nothing_and_says_why(self):
        for refusal, code in (("NO_KEY", "NO_KEY"), ("BUDGET_EXHAUSTED", "BUDGET")):
            r = run(applicant(), engine=FakeEngine(refusal=refusal))
            courts = r.report["stages"][1]
            self.assertEqual((courts["state"], courts["charged"], courts["credits"]), ("UNAVAILABLE", False, 0), refusal)
            self.assertEqual((r.report["status"], r.report["stopCode"], r.report["stoppedAt"]), ("INCOMPLETE", code, "courts"))
            self.assertEqual((r.engine.calls, r.consumption["courts"]), ([], {"calls": 0}))
            self.assertEqual(r.report["ledger"]["total"], 10)

    def test_credits_are_charged_only_for_the_call_the_engine_made(self):
        gate = self.gate(self.answer())
        self.assertEqual((gate["decision"], gate["spentCredits"]), ("CONTINUE", 40))
        for outcome in ("PROVIDER_ERROR", "TIMEOUT"):
            gate = self.gate(self.answer(outcome, calls=0))
            self.assertEqual((gate["code"], gate["spentCredits"]), (outcome, 10))

    def test_an_answer_that_does_not_hold_together_is_refused_never_charged_or_guessed(self):
        bad = [
            self.answer(calls=0),                                         # an answer that made no call
            self.answer("PROVIDER_ERROR", calls=1),                       # a failure that charged a call
            self.answer("NO_MATCH", category="TAL_OTHER"),                # a category without a match
            self.answer("MATCH", category="A NAME"),                      # a category outside the closed set
            self.answer("REFUSED", calls=0),                              # a refusal without its reason
            self.answer("NO_MATCH", refusal="NO_KEY"),                    # a reason without a refusal
            self.answer("FOUND"),                                         # an outcome outside the closed set
            self.answer(calls=2),                                         # a check is one call or none
            self.answer(calls=True),
        ]
        for engine in bad:
            with self.assertRaises(screening.InvalidInput, msg=json.dumps(engine)):
                self.gate(engine)
        with self.assertRaises(screening.InvalidInput):
            screening.report({"plan": self.plan(), "courtsResult": json.dumps(bad[0]), "courtsGate": json.dumps({"decision": "STOP", "code": "CUTOFF", "ruleId": None})})

    def test_the_default_still_stops_on_any_court_file_whatever_its_category(self):
        for last, category in (("Tremblay", "TAL_NON_PAYMENT"), ("Côté", "TAL_OTHER"), ("Morin", "CRIMINAL"), ("Lavoie", "CIVIL")):
            r = run(applicant(last))
            self.assertEqual((r.report["stoppedAt"], r.report["ruleId"]), ("courts", "CUT-COURT-FILE-FOUND"), last)
            self.assertEqual(r.report["stages"][1]["facts"], {"outcome": "MATCH", "category": category})

    def test_a_manager_can_stop_on_a_tal_non_payment_file_only(self):
        rules = {"courts": [{"id": "CUT-TAL-NON-PAYMENT", "fact": "category", "op": "equals", "value": "TAL_NON_PAYMENT"}]}
        stopped = run(applicant("Tremblay", cutoffs=rules))
        self.assertEqual((stopped.report["status"], stopped.report["ruleId"]), ("STOPPED", "CUT-TAL-NON-PAYMENT"))
        self.assertEqual(stopped.engine.calls, ["COURT_RECORDS"])
        went_on = run(applicant("Côté", cutoffs=rules))
        self.assertEqual((went_on.report["status"], went_on.report["ledger"]["total"]), ("COMPLETED", 60))
        self.assertEqual(went_on.engine.calls, ["COURT_RECORDS", "CREDIT"])
        either = {"courts": [{"id": "CUT-TAL-ANY", "fact": "category", "op": "in", "value": ["TAL_NON_PAYMENT", "TAL_OTHER"]}]}
        self.assertEqual(run(applicant("Côté", cutoffs=either)).report["ruleId"], "CUT-TAL-ANY")
        self.assertEqual(run(applicant("Morin", cutoffs=either)).report["status"], "COMPLETED")

    def test_a_category_rule_must_name_a_category_the_engine_answers(self):
        for rule in (
            {"id": "CUT-X-1", "fact": "category", "op": "equals", "value": "TAL_NONPAYMENT"},
            {"id": "CUT-X-1", "fact": "category", "op": "in", "value": ["TAL_OTHER", "EVICTION"]},
            {"id": "CUT-X-1", "fact": "category", "op": "atLeast", "value": 1},
            {"id": "CUT-X-1", "fact": "outcome", "op": "equals", "value": "TIMEOUT"},
        ):
            with self.assertRaises(RunFailed, msg=json.dumps(rule)):
                run(applicant(cutoffs={"courts": [rule]}))
        with self.assertRaises(RunFailed):  # credit answers no category
            run(applicant(cutoffs={"credit": [{"id": "CUT-X-1", "fact": "category", "op": "equals", "value": "NONE"}]}))


class CutoffsAreData(unittest.TestCase):
    def test_the_manager_replaces_the_default_of_a_stage(self):
        rules = {"courts": [], "credit": [{"id": "CUT-CREDIT-FILE", "fact": "outcome", "op": "equals", "value": "MATCH"}]}
        r = run(applicant("Tremblay", cutoffs=rules))
        self.assertEqual((r.report["status"], r.report["stoppedAt"], r.report["ruleId"]), ("STOPPED", "credit", "CUT-CREDIT-FILE"))
        self.assertEqual(r.report["ledger"]["total"], 60)
        self.assertEqual(r.engine.calls, ["COURT_RECORDS", "CREDIT"])

    def test_a_manager_rule_can_stop_on_a_lease_finding(self):
        rules = {"documents": [{"id": "CUT-LEASE-FAILS", "fact": "leaseFailures", "op": "atLeast", "value": 1}]}
        r = run(applicant(cutoffs=rules))
        self.assertEqual((r.report["stoppedAt"], r.report["ruleId"]), ("documents", "CUT-LEASE-FAILS"))
        self.assertEqual(r.engine.calls, [])

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
        engine = FakeEngine()
        with self.assertRaises(RunFailed):
            run(applicant(cutoffs={"courts": "x"}), engine=engine)
        self.assertEqual(engine.calls, [])

    def test_budget_stops_before_a_stage_the_cap_cannot_pay(self):
        r = run(applicant(creditCap=50))
        self.assertEqual((r.report["status"], r.report["stopCode"], r.report["stoppedAt"]), ("INCOMPLETE", "BUDGET", "courts"))
        self.assertEqual(r.report["ledger"]["total"], 40)
        self.assertEqual(r.engine.calls, ["COURT_RECORDS"])
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
    NAMES = ("Gagnon", "Tremblay", "Roy", "Bouchard", "Côté", "Morin", "Lavoie", "Alex", "1990-01-01")

    def test_no_step_output_carries_a_name_or_a_birth_date(self):
        for last in ("Gagnon", "Tremblay", "Roy", "Bouchard", "Côté", "Morin", "Lavoie"):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                r = run(applicant(last))
            text = json.dumps(r.outputs) + json.dumps(r.consumption) + out.getvalue() + err.getvalue()
            for name in self.NAMES:
                self.assertNotIn(name, text, f"{name} leaked for {last}")
            self.assertIn("subj-0001", r.outputs["report"]["report"]["subjectRef"])

    def test_the_report_keeps_codes_only_not_the_providers_reference(self):
        r = run(applicant("Tremblay"))
        self.assertNotIn("mock-fixture", json.dumps(r.outputs))  # the engine's audit keeps the reference, the report does not
        for stage in r.report["stages"]:
            self.assertLessEqual(set(stage), {"stage", "purpose", "state", "outcome", "facts", "consent", "charged", "credits"})

    def test_nothing_the_engine_adds_to_its_answer_reaches_a_result_or_the_report(self):
        plan = screening.plan(applicant())["planJson"]
        smuggled = {"outcome": "MATCH", "refusal": None, "category": "CIVIL", "providerRef": "mock-fixture-04", "calls": 1,
                    "lastName": "Tremblay", "record": "Tremblay c. Alex, 1990-01-01"}
        gate = screening.cutoff({"plan": plan, "stage": "courts", "consent": "GRANTED", "result": json.dumps(smuggled), "spentCredits": 10})
        body = screening.report({"plan": plan, "courtsResult": json.dumps(smuggled), "courtsGate": gate["decisionJson"], "courtsConsent": "GRANTED"})
        text = json.dumps(gate) + json.dumps(body)
        for name in self.NAMES + ("mock-fixture",):
            self.assertNotIn(name, text)
        self.assertEqual(body["report"]["stages"][1]["facts"], {"outcome": "MATCH", "category": "CIVIL"})

    def test_an_error_message_never_repeats_a_value(self):
        try:
            run(applicant(cutoffs={"courts": [{"id": "CUT-X-1", "fact": "Tremblay", "op": "equals", "value": "MATCH"}]}))
        except RunFailed as bad:
            self.assertNotIn("Tremblay", str(bad).replace("this stage knows", ""))
        else:
            self.fail("an unknown fact must fail the plan")


class Providers(unittest.TestCase):
    def test_only_the_mock_is_enabled_a_ruleset_naming_another_fails_the_plan(self):
        ruleset = screening.load_ruleset()
        for provider in ("soquij", "trustii", "certn", ""):
            with mock.patch.object(screening, "load_ruleset", lambda as_of=None, p=provider: dict(ruleset, provider=p)):
                with self.assertRaises(screening.ProviderNotEnabled):
                    screening.plan(applicant())
        self.assertTrue(issubclass(screening.ProviderNotEnabled, screening.InvalidInput))

    def test_the_ruleset_names_the_mock_and_says_so_in_its_limits(self):
        ruleset = screening.load_ruleset()
        self.assertEqual(ruleset["provider"], "mock")
        self.assertIn("MOCK_PROVIDER_ONLY", ruleset["limits"])

    def test_the_closed_sets_of_the_worker_are_the_engines_contract(self):
        self.assertEqual(list(screening.ENGINE_OUTCOMES), CONTRACT["outcome"])
        self.assertEqual(list(screening.ENGINE_ANSWERED), CONTRACT["answered"])
        self.assertEqual(list(screening.ENGINE_REFUSALS), CONTRACT["refusal"])
        self.assertEqual(list(screening.ENGINE_CATEGORIES), CONTRACT["category"])
        self.assertEqual(set(screening.ENGINE_PURPOSES), set(CONTRACT["featureKeys"].values()))

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

    def test_every_capability_of_the_blueprint_is_the_engines_or_contributed_and_routed(self):
        for step in BLUEPRINT["definition"]["steps"]:
            if step["featureKey"] in CONTRACT["featureKeys"]:
                self.assertNotIn(step["featureKey"], ROUTING, "one door: the pack never declares an engine key")
                continue
            self.assertIn(step["featureKey"], ROUTING)
            self.assertIn(ROUTING[step["featureKey"]], handlers.HANDLERS)

    def test_court_records_and_credit_are_the_engines_checks(self):
        self.assertEqual(BLUEPRINT_STEPS["courts"]["featureKey"], "orazaka.core.checks.courtrecords")
        self.assertEqual(BLUEPRINT_STEPS["credit"]["featureKey"], "orazaka.core.checks.credit")
        for stage in ("courts", "credit"):
            self.assertEqual(set(BLUEPRINT_STEPS[stage]["inputs"]), set(CONTRACT["inputs"]))
        self.assertNotIn("job.screening.courts", handlers.HANDLERS)
        self.assertNotIn("job.screening.credit", handlers.HANDLERS)


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
        payload = {"plan": plan["planJson"], "authenticityReport": CLEAN, "consentedPurposes": ALL}
        self.deliver("job.screening.documents", {"jobId": "j-1", "payload": payload})
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
