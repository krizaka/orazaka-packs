#!/usr/bin/env python3
"""``compliance-check`` 2.0 (ADR-089 §4): the fixed run between what a document is and the report on it.

identify → classify (only on a tie) → **resolve** → screen → judge → **report**. This module is the two steps in bold,
free of AMQP like ``rules`` and ``identify``, so a test reaches every decision without a broker.

* **resolve** keeps or discards the model's choice of kind (``identify``, quote checked), then resolves the ruleset
  from ``(kindUsed, asOf)`` — never today's newest, never the lease's for another kind. A kind with no promoted
  ruleset is ``UNSUPPORTED_KIND``; no kind is ``KIND_UNKNOWN``. Neither runs a rule.
* **report** folds the judge's answer in (``rules.merge_judgments``) and then checks **both quotes** of every finding:
  the passage is in the document, the citation's quote is in the article text the ruleset pins (``citations``). A
  verdict whose passage or citation fails is ``INSUFFICIENT_EVIDENCE``, and no passage is never a PASS.

The report's contract (``CONTRACT``) is declared on the blueprint's ``report`` step, so the platform refuses a report
outside it (orazaka-studio#59).
"""

import json

import citations
import identify
import lecture
import quotes
import rules

CONTRACT = "2.0"

CHECKED = "CHECKED"

#: What the run did with the document.
OUTCOMES = (CHECKED, identify.UNSUPPORTED_KIND, identify.KIND_UNKNOWN)

#: The passage of a finding: in the document, absent (a FAIL on an absence, or no verdict), or quoted wrongly.
PASSAGE_VERIFIED = "VERIFIED"
PASSAGE_ABSENT = "ABSENT"
PASSAGE_NOT_IN_DOCUMENT = "NOT_IN_DOCUMENT"

CLASSIFY_INSTRUCTIONS = (
    "Tu identifies le type d'un document. Réponds UNIQUEMENT par un objet JSON de la forme "
    '{"kindId": "...", "quote": "la phrase exacte du document qui le montre"}. kindId est l\'une des valeurs '
    "ci-dessous, et rien d'autre ; OTHER si aucune ne convient. Ne devine pas."
)


def classify_prompt(identification: dict, text: str) -> str:
    """The question of the ``classify`` step: one kind among the tied ones, or OTHER, with a quote. Empty: no question."""
    among = identification.get("classifyAmong") or []
    if not among:
        return ""
    choices = "\n".join(f"- {kind_id}" for kind_id in [*among, identify.OTHER])
    return f"{CLASSIFY_INSTRUCTIONS}\n\nValeurs possibles:\n{choices}\n\nDocument:\n---\n{text}\n---"


def resolve(identification: dict, classification: str, text: str) -> dict:
    """The identification the run keeps, the outcome, and the ruleset in force at ``asOf`` for the kind used.

    The model's answer is re-read through ``identify`` with the inputs the first identification recorded, so the kept
    kind, its date and the mismatch are decided by the same function, never patched in.
    """
    answer = _first_object(classification) if identification.get("classifyAmong") else None
    if answer is not None:
        identification = identify.identify(
            text,
            today=identification["asOf"],
            declared_kind=identification.get("declaredKind"),
            jurisdiction=identification["jurisdiction"] if identification.get("jurisdictionSource") == "DECLARED" else None,
            as_of=identification["asOf"] if identification.get("asOfSource") == "INPUT" else None,
            classified=answer,
        )
    resolved = {"outcome": identification["outcome"], "identification": identification}
    if identification["outcome"] == identify.CHECK:
        ruleset = rules.resolve(identification["ruleset"], identification["asOf"])
        resolved["ruleset"] = {
            "id": ruleset["rulesetId"],
            "version": ruleset["version"],
            "revision": ruleset.get("revision", 1),
            "reviewStatus": ruleset.get("reviewStatus"),
        }
    return resolved


def report(resolved: dict, ruleset, screened: dict, judgment: str, articles: dict) -> dict:
    """The 2.0 report: the identification, the outcome, the ruleset, and findings whose two quotes were checked.

    ``ruleset`` is the version ``resolve`` named (``None`` when no ruleset applies); ``articles`` the texts it pins.
    """
    identification = resolved["identification"]
    if resolved["outcome"] != identify.CHECK:
        return {
            "contract": CONTRACT,
            "outcome": resolved["outcome"],
            "identification": identification,
            "asOf": identification["asOf"],
            "summary": rules.summarise([]),
            "findings": [],
            # The one thing counted about a document with no promoted ruleset: where from and which kind, never content.
            "kindDemand": lecture.kind_demand(identification),
        }
    text = str(screened.get("documentText") or "")
    by_id = {rule["ruleId"]: rule for rule in ruleset["rules"]}
    merged = rules.merge_judgments(ruleset, screened.get("deterministicFindings") or [], judgment, text)
    findings = sorted((_checked(f, by_id[f["ruleId"]], text, articles) for f in merged), key=lambda f: f["ruleId"])
    out = {
        "contract": CONTRACT,
        "outcome": CHECKED,
        "identification": identification,
        "ruleset": resolved["ruleset"],
        "jurisdiction": ruleset["jurisdiction"],
        "asOf": identification["asOf"],
        "source": ruleset["source"],
        "summary": rules.summarise(findings),
        "findings": findings,
    }
    if screened.get("facts"):
        out["facts"] = screened["facts"]
    if ruleset.get("reviewNote"):
        out["reviewNote"] = ruleset["reviewNote"]
    return out


def cacheable(identification: dict) -> bool:
    """Whether a run may answer again from the cache: its day was given or read in the document, never the clock's."""
    return identification.get("asOfSource") in ("INPUT", "DOCUMENT")


def _checked(finding: dict, rule: dict, text: str, articles: dict) -> dict:
    """One finding with both of its quotes checked, and its verdict withdrawn when either fails."""
    passage = _passage(finding.get("evidenceSpan"), text)
    citation, cited = citations.cite(rule, articles)
    checked = dict(finding, citation=citation, checks={"passage": passage, "citation": cited})
    verdict = finding["verdict"]
    if verdict == rules.PASS and passage != PASSAGE_VERIFIED:
        return dict(checked, verdict=rules.INSUFFICIENT_EVIDENCE, explanation="Aucun passage du document ne fonde ce verdict : il n'est pas retenu.")
    if verdict in (rules.PASS, rules.FAIL) and passage == PASSAGE_NOT_IN_DOCUMENT:
        return dict(checked, verdict=rules.INSUFFICIENT_EVIDENCE, explanation="Le passage cité n'est pas dans le document : le verdict n'est pas retenu.")
    if verdict in (rules.PASS, rules.FAIL) and cited not in (citations.VERIFIED, citations.NOT_PINNED):
        return dict(checked, verdict=rules.INSUFFICIENT_EVIDENCE, explanation="La citation de l'article ne se vérifie pas dans le texte que le corpus fixe : le verdict n'est pas retenu.")
    return checked


def _passage(span, text: str) -> str:
    if not span or not span.get("quote"):
        return PASSAGE_ABSENT
    # A long passage is shown cut, with an ellipsis the document does not hold: the part shown is what is checked.
    shown = span["quote"].removesuffix("…")
    return PASSAGE_VERIFIED if quotes.contains(text, shown) else PASSAGE_NOT_IN_DOCUMENT


def _first_object(raw: str):
    """The first JSON object in a model's answer, or None. A fence or a sentence around it is packaging."""
    raw = raw or ""
    start = raw.find("{")
    while start != -1:
        try:
            value, _ = json.JSONDecoder().raw_decode(raw[start:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        start = raw.find("{", start + 1)
    return None
