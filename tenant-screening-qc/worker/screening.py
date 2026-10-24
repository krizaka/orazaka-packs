"""The screening saga's rules: pure functions over what the blueprint's steps pass along.

Three stages, in order: ``documents`` (the evidence of the two document Studios), ``courts`` (the TAL and the plumitifs),
``credit``. A stage runs, and is charged, only if the one before it passed its **cut-off**. A cut-off is data: the dated
default ruleset (``rules/screening-cutoffs``), replaced stage by stage by the manager's own rules. A stop is a rule of the
process, never a verdict on the applicant: the pack words nothing and decides nothing, it returns codes.

Nothing here logs, and no result carries a name: the subject is its opaque id.
"""

import glob
import json
import os
import re
from typing import Optional

import connectors

HERE = os.path.dirname(os.path.abspath(__file__))
RULESETS = os.path.join(HERE, "..", "rules", "screening-cutoffs")

CONTINUE, STOP = "CONTINUE", "STOP"
GRANTED, REFUSED_CONSENT = "GRANTED", "REFUSED"
#: What a stage that did not answer is called. It is never charged.
UNAVAILABLE = (connectors.PROVIDER_ERROR, connectors.TIMEOUT, "REFUSED")
MAX_RULES_PER_STAGE = 8
RULE_ID = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,39}$")


class InvalidInput(ValueError):
    """The payload was checked and is unusable. Raised before any paid stage whenever it can be."""


# ── data ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def load_ruleset(as_of: Optional[str] = None) -> dict:
    files = sorted(glob.glob(os.path.join(RULESETS, "*.json")))
    chosen = None
    for path in files:
        if as_of is None or os.path.basename(path)[: -len(".json")] <= as_of:
            chosen = path
    if chosen is None:
        raise LookupError("no screening ruleset in force")
    with open(chosen, encoding="utf-8") as handle:
        return json.load(handle)


def _obj(value: object, name: str, required: bool = True) -> Optional[dict]:
    """A JSON object, given as an object or as JSON text (a blueprint passes a step's fields as text)."""
    if value is None or value == "":
        if required:
            raise InvalidInput(f"'{name}' is required")
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as bad:
            raise InvalidInput(f"'{name}' is not JSON ({bad.msg})") from bad
    if not isinstance(value, dict):
        raise InvalidInput(f"'{name}' must be an object")
    return value


def _bool(value: object, name: str, default: bool = False) -> bool:
    """A blueprint renders a lone boolean as text; anything but true/false is refused, never guessed."""
    if value is None or value == "":
        return default
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    if isinstance(value, bool):
        return value
    raise InvalidInput(f"'{name}' must be true or false")


def _int(value: object, name: str, low: int, high: int, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidInput(f"'{name}' must be an integer from {low} to {high}")
    return value


def _stage(plan: dict, stage_id: str) -> dict:
    for stage in plan["stages"]:
        if stage["id"] == stage_id:
            return stage
    raise InvalidInput(f"unknown stage '{stage_id}'")


# ── the manager's rules ─────────────────────────────────────────────────────────────────────────────────────────────
def _validate_rule(ruleset: dict, stage: dict, rule: object) -> dict:
    where = f"cutoffs.{stage['id']}"
    if not isinstance(rule, dict) or set(rule) - {"id", "fact", "op", "value"} or not {"id", "fact", "op", "value"} <= set(rule):
        raise InvalidInput(f"{where}: a rule is exactly {{id, fact, op, value}}")
    if not isinstance(rule["id"], str) or not RULE_ID.match(rule["id"]):
        raise InvalidInput(f"{where}: a rule id is 3 to 40 upper-case letters, digits or dashes")
    if rule["fact"] not in stage["facts"]:
        raise InvalidInput(f"{where}.{rule['id']}: this stage knows the facts {', '.join(stage['facts'])}")
    if rule["op"] not in ruleset["operators"]:
        raise InvalidInput(f"{where}.{rule['id']}: operators are {', '.join(ruleset['operators'])}")
    value = rule["value"]
    if rule["op"] == "atLeast" and not (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
        raise InvalidInput(f"{where}.{rule['id']}: atLeast takes a whole number from 0")
    if rule["op"] == "equals" and (isinstance(value, (dict, list)) or value is None):
        raise InvalidInput(f"{where}.{rule['id']}: equals takes a string, a number or a boolean")
    if rule["op"] == "in" and not (isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
        raise InvalidInput(f"{where}.{rule['id']}: in takes a non-empty list of strings")
    return {key: rule[key] for key in ("id", "fact", "op", "value")}


def effective_cutoffs(ruleset: dict, manager: Optional[dict]) -> dict:
    """The cut-offs in force per stage: the manager's list replaces the default of that stage (an empty list removes it)."""
    manager = manager or {}
    known = {stage["id"]: stage for stage in ruleset["stages"]}
    for stage_id in manager:
        if stage_id not in known:
            raise InvalidInput(f"cutoffs: unknown stage '{stage_id}'")
    chosen = {}
    for stage_id, stage in known.items():
        rules = manager[stage_id] if stage_id in manager else stage["cutoffs"]
        if not isinstance(rules, list) or len(rules) > MAX_RULES_PER_STAGE:
            raise InvalidInput(f"cutoffs.{stage_id}: a list of at most {MAX_RULES_PER_STAGE} rules")
        validated = [_validate_rule(ruleset, stage, rule) for rule in rules]
        if len({rule["id"] for rule in validated}) != len(validated):
            raise InvalidInput(f"cutoffs.{stage_id}: rule ids are unique")
        chosen[stage_id] = validated
    return chosen


def rule_holds(rule: dict, facts: dict) -> bool:
    actual = facts.get(rule["fact"])
    if rule["op"] == "equals":
        return actual == rule["value"]
    if rule["op"] == "atLeast":
        return isinstance(actual, int) and not isinstance(actual, bool) and actual >= rule["value"]
    return actual in rule["value"]


# ── the consent gate (one place, used by the step that shows it and by every paid stage) ───────────────────────────
def consent_granted(purpose: str, consented: object) -> bool:
    """Fails closed: a purpose is granted only if it is listed. Anything else, including nothing, is a refusal."""
    return isinstance(consented, list) and purpose in consented


# ── the steps ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _evidence(payload: dict) -> tuple:
    authenticity = _obj(payload.get("authenticityReport"), "authenticityReport")
    if not isinstance(authenticity.get("signals"), list):
        raise InvalidInput("'authenticityReport' is not the signals output of document-authenticity")
    lease = _obj(payload.get("leaseReport"), "leaseReport", required=False)
    if lease is not None and not isinstance(lease.get("findings"), list):
        raise InvalidInput("'leaseReport' is not the report of compliance-check")
    return authenticity, lease


def plan(payload: dict) -> dict:
    """Validates everything that can be validated before the first paid stage, and freezes the run's rules."""
    ruleset = load_ruleset()
    connectors.connector_for(ruleset["provider"])
    subject = _obj(payload.get("subject"), "subject")
    for key in ("subjectId", "lastName", "firstName"):
        if not isinstance(subject.get(key), str) or not subject[key].strip():
            raise InvalidInput(f"'subject.{key}' is required")
    _evidence(payload)
    cutoffs = effective_cutoffs(ruleset, _obj(payload.get("cutoffs"), "cutoffs", required=False))
    cap = _int(payload.get("creditCap"), "creditCap", 0, 1_000_000, 0)
    first = ruleset["stages"][0]
    if cap and first["credits"] > cap:
        raise InvalidInput("'creditCap' cannot pay the first stage")
    applicant_pays = _bool(payload.get("applicantPaysFees"), "applicantPaysFees")
    stages = [
        {"id": s["id"], "purpose": s["purpose"], "credits": s["credits"], "facts": s["facts"], "cutoffs": cutoffs[s["id"]]}
        for s in ruleset["stages"]
    ]
    result = {
        "rulesetId": ruleset["rulesetId"],
        "rulesetVersion": ruleset["version"],
        "rulesetRevision": ruleset.get("revision", 1),
        "provider": ruleset["provider"],
        "subjectRef": subject["subjectId"],
        "payer": "APPLICANT" if applicant_pays else "LANDLORD",
        "creditCap": cap,
        "worstCaseCredits": sum(s["credits"] for s in stages),
        "stages": stages,
        "limits": list(ruleset["limits"]),
    }
    return dict(result, planJson=json.dumps(result), status="READY")


def consent(payload: dict) -> dict:
    purpose = payload.get("purpose")
    if purpose not in ("DOCUMENTS", "COURT_RECORDS", "CREDIT"):
        raise InvalidInput("'purpose' is DOCUMENTS, COURT_RECORDS or CREDIT")
    granted = consent_granted(purpose, payload.get("consentedPurposes"))
    return {"purpose": purpose, "status": GRANTED if granted else REFUSED_CONSENT, "reason": None if granted else "NO_CONSENT"}


def _stage_result(stage: dict, subject_ref: str, outcome: str, facts: dict, credits: int, provider_ref: Optional[str] = None) -> dict:
    charged = credits > 0 and outcome not in UNAVAILABLE
    result = {
        "stage": stage["id"],
        "purpose": stage["purpose"],
        "outcome": outcome,
        "facts": facts,
        "charged": charged,
        "credits": credits if charged else 0,
        "subjectRef": subject_ref,
    }
    if provider_ref:
        result["providerRef"] = provider_ref
    return dict(result, resultJson=json.dumps(result))


def documents(payload: dict) -> dict:
    """Stage 1: counts the signals of the evidence. Reads the evidence it is given; it re-runs and re-bills nothing."""
    ruleset = load_ruleset()
    plan_ = _obj(payload.get("plan"), "plan")
    stage = _stage(plan_, "documents")
    if not consent_granted(stage["purpose"], payload.get("consentedPurposes")):
        return _stage_result(stage, plan_["subjectRef"], "REFUSED", {}, 0)
    authenticity, lease = _evidence(payload)
    levels = [s.get("level") for s in authenticity["signals"] if isinstance(s, dict)]
    facts = {
        "majorSignals": sum(1 for level in levels if level in ruleset["documents"]["majorLevels"]),
        "unusualSignals": sum(1 for level in levels if level in ruleset["documents"]["unusualLevels"]),
        "leaseFailures": 0 if lease is None else sum(1 for f in lease["findings"] if isinstance(f, dict) and f.get("verdict") == "FAIL"),
    }
    return _stage_result(stage, plan_["subjectRef"], "SIGNALS" if facts["majorSignals"] else "CLEAR", facts, stage["credits"])


def _external(stage_id: str, payload: dict, connector) -> dict:
    plan_ = _obj(payload.get("plan"), "plan")
    stage = _stage(plan_, stage_id)
    if not consent_granted(stage["purpose"], payload.get("consentedPurposes")):
        return _stage_result(stage, plan_["subjectRef"], "REFUSED", {"outcome": "REFUSED"}, 0)  # before any provider call
    raw = _obj(payload.get("subject"), "subject")
    if raw.get("subjectId") != plan_["subjectRef"]:
        raise InvalidInput("'subject' is not the subject of the plan")
    subject = connectors.Subject(raw["subjectId"], raw["lastName"], raw["firstName"], raw.get("birthDate"))
    connector = connector or connectors.connector_for(plan_["provider"])
    answer = connector.verify_court_records(subject) if stage_id == "courts" else connector.verify_credit(subject)
    return _stage_result(stage, plan_["subjectRef"], answer.outcome, {"outcome": answer.outcome}, stage["credits"], answer.provider_ref)


def courts(payload: dict, connector=None) -> dict:
    return _external("courts", payload, connector)


def credit(payload: dict, connector=None) -> dict:
    return _external("credit", payload, connector)


def cutoff(payload: dict) -> dict:
    """After a stage: does the saga go on? The first reason to stop wins, and the decision says which."""
    plan_ = _obj(payload.get("plan"), "plan")
    stage_id = payload.get("stage")
    stage = _stage(plan_, stage_id)
    spent = _int(payload.get("spentCredits"), "spentCredits", 0, 10_000_000, 0)
    result = _obj(payload.get("result"), "result", required=False)
    index = [s["id"] for s in plan_["stages"]].index(stage_id)
    following = plan_["stages"][index + 1] if index + 1 < len(plan_["stages"]) else None
    stops = {"decision": STOP, "ruleId": None}
    if payload.get("consent") != GRANTED:
        stops["code"] = "NO_CONSENT"
    elif result is None:
        stops["code"] = "STAGE_NOT_RUN"
    elif result["outcome"] in UNAVAILABLE:
        stops["code"] = result["outcome"]
    else:
        spent += result["credits"]
        hit = next((rule for rule in stage["cutoffs"] if rule_holds(rule, dict(result["facts"], outcome=result["outcome"]))), None)
        if hit:
            stops.update(code="CUTOFF", ruleId=hit["id"])
        elif following and plan_["creditCap"] and spent + following["credits"] > plan_["creditCap"]:
            stops["code"] = "BUDGET"
        else:
            stops = {"decision": CONTINUE, "code": "NONE", "ruleId": None}
    decision = dict(stops, stage=stage_id, spentCredits=spent, next=None if stops["decision"] == STOP or not following else following["id"])
    return dict(decision, decisionJson=json.dumps(decision))


def report(payload: dict) -> dict:
    """The closed report: what ran, why it stopped, and what each stage cost. Codes and counts, no name, no record."""
    plan_ = _obj(payload.get("plan"), "plan")
    entries, stop = [], None
    for stage in plan_["stages"]:
        sid = stage["id"]
        result = _obj(payload.get(f"{sid}Result"), f"{sid}Result", required=False)
        gate = _obj(payload.get(f"{sid}Gate"), f"{sid}Gate", required=False)
        consented = payload.get(f"{sid}Consent")
        if gate is None:
            state, outcome, facts = "NOT_RUN", None, {}
        else:
            outcome = result["outcome"] if result else None
            facts = result["facts"] if result else {}
            if gate["code"] == "NO_CONSENT":
                state = "REFUSED"
            elif outcome is None:
                state = "NOT_RUN"
            elif outcome in UNAVAILABLE:
                state = "UNAVAILABLE"
            else:
                state = "RAN"
            if gate["decision"] == STOP and stop is None:
                stop = dict(gate, stage=sid)
        entries.append({
            "stage": sid,
            "purpose": stage["purpose"],
            "state": state,
            "outcome": outcome,
            "facts": facts,
            "consent": consented if consented else None,
            "charged": bool(result and result["charged"]),
            "credits": result["credits"] if result and result["charged"] else 0,
        })
    total = sum(e["credits"] for e in entries)
    if stop is None:
        status = "COMPLETED"
    elif stop["code"] in ("CUTOFF",):
        status = "STOPPED"
    else:
        status = "INCOMPLETE"
    limits = list(plan_["limits"])
    if plan_["payer"] == "APPLICANT":
        limits.append("APPLICANT_PAYS_FEES_MAY_CONTRAVENE_CCQ_1904")
    body = {
        "rulesetId": plan_["rulesetId"],
        "rulesetVersion": plan_["rulesetVersion"],
        "rulesetRevision": plan_["rulesetRevision"],
        "subjectRef": plan_["subjectRef"],
        "status": status,
        "stoppedAt": stop["stage"] if stop else None,
        "stopCode": stop["code"] if stop else None,
        "ruleId": stop["ruleId"] if stop else None,
        "stages": entries,
        "ledger": {"unit": "credits", "payer": plan_["payer"], "creditCap": plan_["creditCap"], "total": total, "byStage": {e["stage"]: e["credits"] for e in entries}},
        "limits": limits,
    }
    return {"report": body, "reportJson": json.dumps(body), "status": status}
