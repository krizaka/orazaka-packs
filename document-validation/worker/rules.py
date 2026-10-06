#!/usr/bin/env python3
"""Ruleset resolution and deterministic evaluation — the half of this pack that is not a model.

Kept in its own module, and free of AMQP, because it is the part with rules in it: it is
importable by a test, and a compliance product whose rule engine cannot be tested without a
broker is one whose rules are never tested.

Three things this module exists to guarantee.

**A finding is a record, never prose.** Every evaluation returns
``(ruleId, severity, verdict, evidenceSpan, explanation, method, citation)``. The user forwards
this output to their counterparty; a paragraph cannot be forwarded, disputed, or diffed against
the next run.

**Deterministic first.** A rule that can be decided by reading the document is decided here, in
code, by a regex an auditor can read. The model is asked only about rules whose ``method`` is
``JUDGMENT`` — and it is asked by a separate step, so what it costs is metered like any other
inference (BILL-001).

**The ruleset in force is resolved from a date, not from today.** ``resolve`` picks the version
whose window contains ``asOf`` and returns it with its version string, which every finding then
carries. Replaying a run with the same ``asOf`` therefore re-runs the same rules, whatever the law
has since become.
"""

import json
import os
import re
from datetime import date

RULESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rulesets")

# A verdict is one of these four and nothing else. INSUFFICIENT_EVIDENCE is not a failure mode of
# the product: it is the honest answer when the document does not carry what the rule needs, and
# it is what an unparseable model answer degrades to rather than a guess.
PASS = "PASS"
FAIL = "FAIL"
NOT_APPLICABLE = "NOT_APPLICABLE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

MAX_QUOTE = 240


class RulesetNotFound(Exception):
    """No published ruleset covers this (jurisdiction, date) pair — say so, do not fall back."""


def _load_all(ruleset_id: str) -> list:
    directory = os.path.join(RULESETS_DIR, ruleset_id)
    if not os.path.isdir(directory):
        raise RulesetNotFound(f"no ruleset '{ruleset_id}' is shipped with this pack")
    out = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                out.append(json.load(handle))
    return out


def resolve(ruleset_id: str, as_of: str) -> dict:
    """The ruleset version in force on ``as_of`` (ISO date), or an explicit failure.

    Never "the newest one": a lease signed in 2024 is judged against the rules of 2024, and a run
    replayed next year must reach the same verdicts. A date that no version covers is an error,
    not an invitation to use the closest one.
    """
    day = date.fromisoformat(as_of)
    for candidate in _load_all(ruleset_id):
        start = date.fromisoformat(candidate["effectiveFrom"])
        end = candidate.get("effectiveTo")
        if start <= day and (end is None or day <= date.fromisoformat(end)):
            return candidate
    raise RulesetNotFound(f"ruleset '{ruleset_id}' has no version in force on {as_of}")


def jurisdictions() -> dict:
    """Every ruleset this pack ships, by jurisdiction — the pack's own declaration."""
    found = {}
    for entry in sorted(os.listdir(RULESETS_DIR)):
        if os.path.isdir(os.path.join(RULESETS_DIR, entry)):
            versions = _load_all(entry)
            if versions:
                found[versions[0]["jurisdiction"]] = entry
    return found


def _span(match, text: str) -> dict:
    """Where in the document the evidence sits, and what it says. Offsets are into ``text``."""
    quote = match.group(0).strip()
    return {
        "start": match.start(),
        "end": match.end(),
        "quote": quote[:MAX_QUOTE] + ("…" if len(quote) > MAX_QUOTE else ""),
    }


def _number(raw: str) -> float:
    """A euro amount as written by a human: '1 250,00' and '1.250,00' are the same number."""
    cleaned = raw.strip().replace(" ", "").replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    return float(cleaned)


def _finding(rule: dict, verdict: str, span, explanation: str) -> dict:
    return {
        "ruleId": rule["ruleId"],
        "title": rule["title"],
        "severity": rule["severity"],
        "verdict": verdict,
        "evidenceSpan": span,
        "explanation": explanation,
        "method": rule["method"],
        "citation": rule["citation"],
    }


def _required_pattern(rule: dict, text: str) -> dict:
    match = re.search(rule["check"]["pattern"], text)
    if match:
        return _finding(rule, PASS, _span(match, text), rule["onPass"])
    # An absence has no span, and saying so is information rather than a gap: the reader learns
    # that nothing was found, not that the tool forgot to look.
    return _finding(rule, FAIL, None, rule["onFail"])


def _forbidden_pattern(rule: dict, text: str) -> dict:
    match = re.search(rule["check"]["pattern"], text)
    if match:
        return _finding(rule, FAIL, _span(match, text), rule["onFail"])
    return _finding(rule, PASS, None, rule["onPass"])


def _numeric_ratio_max(rule: dict, text: str) -> dict:
    check = rule["check"]
    top = re.search(check["numerator"], text)
    bottom = re.search(check["denominator"], text)
    if not top or not bottom:
        missing = "le montant garanti" if not top else "le loyer de référence"
        return _finding(
            rule,
            INSUFFICIENT_EVIDENCE,
            _span(top or bottom, text) if (top or bottom) else None,
            f"Le document ne chiffre pas {missing} ; la règle ne peut pas être évaluée.",
        )
    try:
        ratio = _number(top.group(1)) / _number(bottom.group(1))
    except (ValueError, ZeroDivisionError):
        return _finding(
            rule,
            INSUFFICIENT_EVIDENCE,
            _span(top, text),
            "Les montants trouvés ne sont pas exploitables ; la règle ne peut pas être évaluée.",
        )
    if ratio <= check["max"] + 1e-9:
        return _finding(rule, PASS, _span(top, text), rule["onPass"])
    return _finding(
        rule,
        FAIL,
        _span(top, text),
        f"{rule['onFail']} Constaté : {ratio:.2f} mois.",
    )


_WORDED_NUMBERS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
    "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "douze": 12,
}


def _numeric_min(rule: dict, text: str) -> dict:
    """A quantity the law sets a FLOOR under, not a clause whose presence is enough.

    Added because FR-LEASE-003 was a REQUIRED_PATTERN looking for the words "durée du bail", for a
    requirement that is a term of at least three years (art. 10). That shape failed twice in one
    pass on a real document: a false FAIL, because the lease said "pour une durée de deux ans" and
    the pattern wanted another phrasing — and the real violation missed, because two years IS the
    breach and a presence check cannot see a number. A lexical check where the law states a
    quantity is the same defect as a lexical check where it states a fact.

    French leases write the term in words as often as in digits, so both are read.
    """
    check = rule["check"]
    match = re.search(check["quantity"], text)
    if not match:
        return _finding(
            rule,
            INSUFFICIENT_EVIDENCE,
            None,
            "Le document n'énonce aucune durée exploitable ; la règle ne peut pas être évaluée.",
        )
    raw = match.group(1).strip().lower()
    try:
        value = _WORDED_NUMBERS.get(raw)
        if value is None:
            value = _number(raw)
    except ValueError:
        return _finding(
            rule,
            INSUFFICIENT_EVIDENCE,
            _span(match, text),
            "La durée trouvée n'est pas exploitable ; la règle ne peut pas être évaluée.",
        )
    if value >= check["min"] - 1e-9:
        return _finding(rule, PASS, _span(match, text), rule["onPass"])
    return _finding(
        rule,
        FAIL,
        _span(match, text),
        f"{rule['onFail']} Constaté : {value:g} an(s).",
    )


CHECKS = {
    "REQUIRED_PATTERN": _required_pattern,
    "FORBIDDEN_PATTERN": _forbidden_pattern,
    "NUMERIC_RATIO_MAX": _numeric_ratio_max,
    "NUMERIC_MIN": _numeric_min,
}


def screen(ruleset: dict, text: str) -> tuple:
    """Every deterministic rule, plus the questions the model still has to be asked.

    Returns ``(findings, judgments)``. ``judgments`` carries one entry per JUDGMENT rule, and it
    is the ONLY thing that reaches a model — a rule that code can decide never costs an inference.
    """
    findings = []
    judgments = []
    for rule in ruleset["rules"]:
        if rule["method"] == "JUDGMENT":
            judgments.append(
                {"ruleId": rule["ruleId"], "question": rule["question"], "severity": rule["severity"]}
            )
            continue
        evaluator = CHECKS.get(rule["check"]["type"])
        if evaluator is None:
            # An unknown check type is this pack's own defect. It must not read as a clean pass.
            findings.append(
                _finding(
                    rule,
                    INSUFFICIENT_EVIDENCE,
                    None,
                    f"Type de contrôle inconnu ({rule['check']['type']}) — règle non évaluée.",
                )
            )
            continue
        findings.append(evaluator(rule, text))
    return findings, judgments


def merge_judgments(ruleset: dict, deterministic: list, model_answer: str) -> list:
    """Fold the model's answers into the report, refusing anything that is not a verdict.

    The model is given one job and can fail it three ways: unparseable output, a verdict outside
    the enum, or an answer about a rule nobody asked about. All three degrade to
    ``INSUFFICIENT_EVIDENCE`` for the rule concerned. A wrong verdict on a compliance report is
    worse than an absent one — the user forwards this to their counterparty.
    """
    by_id = {rule["ruleId"]: rule for rule in ruleset["rules"] if rule["method"] == "JUDGMENT"}
    if not by_id:
        return deterministic

    answers = {}
    parsed = _first_json_array(model_answer)
    for item in parsed:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("ruleId")
        if rule_id in by_id and item.get("verdict") in (PASS, FAIL, INSUFFICIENT_EVIDENCE):
            answers[rule_id] = item

    out = list(deterministic)
    for rule_id, rule in by_id.items():
        answer = answers.get(rule_id)
        if answer is None:
            out.append(
                _finding(
                    rule,
                    INSUFFICIENT_EVIDENCE,
                    None,
                    "Le modèle n'a pas rendu de verdict exploitable pour cette règle.",
                )
            )
            continue
        quote = str(answer.get("quote") or "").strip()
        span = {"start": None, "end": None, "quote": quote[:MAX_QUOTE]} if quote else None
        verdict = answer["verdict"]
        explanation = rule["onPass"] if verdict == PASS else rule["onFail"]
        if verdict == INSUFFICIENT_EVIDENCE:
            explanation = "Le modèle n'a pas trouvé dans le document de quoi trancher cette règle."
        out.append(_finding(rule, verdict, span, explanation))
    return out


def _first_json_array(raw: str) -> list:
    """The first JSON array in whatever the model returned, or nothing.

    Models wrap JSON in prose and fences no matter how the prompt is worded. Reaching past that is
    not leniency about the format — an answer that parses to the wrong shape is still rejected
    downstream — it is refusing to lose a correct verdict to a code fence.
    """
    if not raw:
        return []
    start = raw.find("[")
    while start != -1:
        depth = 0
        for index in range(start, len(raw)):
            if raw[index] == "[":
                depth += 1
            elif raw[index] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(raw[start : index + 1])
                    except json.JSONDecodeError:
                        break
                    return value if isinstance(value, list) else []
        start = raw.find("[", start + 1)
    return []


def summarise(findings: list) -> dict:
    """Counts, so a caller can act without re-reading the list. Not a verdict on the document."""
    counts = {}
    for finding in findings:
        counts[finding["verdict"]] = counts.get(finding["verdict"], 0) + 1
    blocking = [f for f in findings if f["verdict"] == FAIL and f["severity"] == "BLOCKING"]
    return {
        "byVerdict": counts,
        "blockingFailures": len(blocking),
        "rulesEvaluated": len(findings),
    }
