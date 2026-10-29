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


# A ruleset id names a folder of this pack: lower-case words joined by hyphens, never a path (Sonar pythonsecurity:S2083).
_RULESET_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _load_all(ruleset_id: str) -> list:
    if not isinstance(ruleset_id, str) or not _RULESET_ID.fullmatch(ruleset_id):
        raise RulesetNotFound(f"no ruleset '{ruleset_id}' is shipped with this pack")
    root = os.path.realpath(RULESETS_DIR)
    directory = os.path.realpath(os.path.join(root, ruleset_id))
    if os.path.dirname(directory) != root or not os.path.isdir(directory):
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
    """Every jurisdiction this pack ships, with its DEFAULT ruleset — the pack's own declaration.

    A ruleset marked ``optIn`` (a document type other than the jurisdiction's lease, such as an
    invoice) is never the default: it is applied only when a run names it (``ruleset``).
    """
    found = {}
    for entry in sorted(os.listdir(RULESETS_DIR)):
        if os.path.isdir(os.path.join(RULESETS_DIR, entry)):
            versions = _load_all(entry)
            if versions and not versions[0].get("optIn"):
                found[versions[0]["jurisdiction"]] = entry
    return found


def rulesets_by_jurisdiction() -> dict:
    """Every shipped ruleset id, by jurisdiction (defaults and opt-in alike)."""
    found = {}
    for entry in sorted(os.listdir(RULESETS_DIR)):
        if os.path.isdir(os.path.join(RULESETS_DIR, entry)):
            versions = _load_all(entry)
            if versions:
                found.setdefault(versions[0]["jurisdiction"], []).append(entry)
    return found


def _number(raw: str) -> float:
    """A euro amount as written by a human: '1 250,00' and '1.250,00' are the same number."""
    cleaned = raw.strip().replace(" ", "").replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    return float(cleaned)


# --- How a ruleset reads the layout of a document (orazaka-packs#81) -------------------------------------------------
#
# A rule is a regular expression over prose, and a real invoice is not prose: its text layer is aligned columns, a
# calculation in brackets between a label and its amount, a label on one line and its value on the next. The regexes
# of qc-invoice are written for « label : value » on one line; rather than loosen every one of them into something an
# auditor cannot read, the ruleset DECLARES how its text is to be read (`textLayout`) and the engine reads it that way,
# once, before any rule runs. Three steps, each a plain statement about layout and none about meaning:
#
#   collapseSpaces  a run of spaces or tabs is one space (a column of padding is not a gap in the sentence);
#   dropBracketed   a one-line [bracketed note] is not part of the sentence (« [Calcul : 3 500,00 $ * 0,05] »);
#   joinValueLines  a line that holds only a value (an amount, a date, a tax number) belongs to the label line above it.
#
# Nothing here invents text: every character of the read form comes from the document, and a finding's evidence is
# still the exact passage of the document as given — its offsets and its quote are mapped back through the rewrite.
# A ruleset that does not declare `textLayout` is read as given.

_BLANKS = re.compile(r"[ \t\u00a0\u2007\u2009\u202f]+")
_BRACKETED = re.compile(r"\[[^\[\]\n]{0,200}\]")
_VALUE_LINE = re.compile(
    r"^[ \t\u00a0\u202f]*(?:"
    r"[$€]?\s*-?\d[\d \u00a0\u202f.,]*(?:\s*(?:\$\s*CAD|\$|CAD|dollars?|€|EUR|%))?"  # an amount or a number
    r"|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}"  # a numeric date
    r"|\d{1,2}(?:er)?\s+[A-Za-zÀ-ÿ]+\.?\s+\d{4}|[A-Za-zÀ-ÿ]+\.?\s+\d{1,2},?\s+\d{4}"  # a date written out
    r"|\d{3}[ -]?\d{3}[ -]?\d{3}\s?RT\s?\d{4}|\d{10}\s?TQ\s?\d{4}"  # a registration number
    r")[ \t\u00a0\u202f]*$"
)
_LINE_BREAK = re.compile(r"[ \t\u00a0\u202f]*\n[ \t\u00a0\u202f]*")


class _Document:
    """The text a rule reads, and the way back to the document as given.

    ``chars`` is the read form, one entry per character: ``(character, start, end)`` where ``start:end`` is the stretch
    of the original it comes from (a collapsed run of spaces is one character standing for the whole run).
    """

    def __init__(self, original: str, layout: dict | None = None):
        self.original = original
        chars = [(c, i, i + 1) for i, c in enumerate(original)]
        layout = layout or {}
        if layout.get("dropBracketed"):
            chars = self._rewrite(chars, _BRACKETED, lambda m, t: "")
        if layout.get("joinValueLines"):
            chars = self._rewrite(chars, _LINE_BREAK, self._join_if_value)
        if layout.get("collapseSpaces"):
            chars = self._rewrite(chars, _BLANKS, lambda m, t: " ")
        self.chars = chars
        self.text = "".join(c for c, _, _ in chars)

    @staticmethod
    def _rewrite(chars: list, pattern, replacement) -> list:
        """A regex substitution that remembers where every character came from.

        ``replacement(match, text)`` returns the new text of the stretch, ``""`` to drop it, or ``None`` to keep it as it is.
        """
        text = "".join(c for c, _, _ in chars)
        out, position = [], 0
        for match in pattern.finditer(text):
            out.extend(chars[position : match.start()])
            replaced = replacement(match, text)
            if replaced is None:
                out.extend(chars[match.start() : match.end()])
            elif replaced:
                start, end = chars[match.start()][1], chars[match.end() - 1][2]
                out.extend((c, start, end) for c in replaced)
            position = match.end()
        out.extend(chars[position:])
        return out

    @staticmethod
    def _join_if_value(match, text: str):
        """A single line break becomes a space when the line after it holds only a value and the line before holds a label."""
        end = text.find("\n", match.end())
        following = text[match.end() : end if end != -1 else len(text)]
        before_start = text.rfind("\n", 0, match.start()) + 1
        preceding = text[before_start : match.start()]
        # Two breaks in a row are a paragraph; a value line under a value line is a column, not a label and its value.
        if text[match.start() : match.end()].count("\n") != 1 or not preceding.strip() or not following.strip():
            return None
        if _VALUE_LINE.match(following) and not _VALUE_LINE.match(preceding):
            return " "
        return None

    def span(self, match) -> dict:
        """Where in the document as given the evidence sits, and what it says. Offsets are into the original text."""
        start, end = self.chars[match.start()][1], self.chars[match.end() - 1][2]
        quote = self.original[start:end].strip()
        return {"start": start, "end": end, "quote": quote[:MAX_QUOTE] + ("…" if len(quote) > MAX_QUOTE else "")}


def _document(source, layout: dict | None = None) -> "_Document":
    """What an evaluator is handed: a ready document, or plain text read as given (the engine's own tests do the latter)."""
    return source if isinstance(source, _Document) else _Document(source, layout)


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


def _required_pattern(rule: dict, source) -> dict:
    doc = _document(source)
    match = re.search(rule["check"]["pattern"], doc.text)
    if match:
        return _finding(rule, PASS, doc.span(match), rule["onPass"])
    # An absence has no span, and saying so is information rather than a gap: the reader learns
    # that nothing was found, not that the tool forgot to look.
    # A rule the law does not make absolute (the language rule: another language is allowed by the parties' express
    # will) declares ``onAbsent: INSUFFICIENT_EVIDENCE``: the absence is then a point to confirm, never a FAIL.
    absent = rule["check"].get("onAbsent", FAIL)
    return _finding(rule, absent, None, rule["onFail"])


def _subject_match(rule: dict, doc: "_Document"):
    """The first passage of the document that addresses the rule's subject (a deposit, the children, a penalty), or None.

    The subject is what the law is about, not the wording it forbids: a document that never mentions it has nothing to
    pass or fail on, and that is NOT_APPLICABLE, never a PASS (orazaka-packs#124).
    """
    subject = rule.get("subject")
    return re.search(subject, doc.text) if subject else None


def _without_passage(rule: dict, doc: "_Document", explanation: str) -> dict:
    """The verdict of a rule the document gives no passage for. It is never PASS, and its evidence is always empty.

    NOT_APPLICABLE when the document does not address the rule's subject; INSUFFICIENT_EVIDENCE otherwise. A rule that
    declares no subject cannot say whether the document addresses it, so it is INSUFFICIENT_EVIDENCE: a gap in the pack,
    not a finding about the document.
    """
    if rule.get("subject") and _subject_match(rule, doc) is None:
        return _finding(rule, NOT_APPLICABLE, None, "Le document n'aborde pas ce sujet ; la règle ne s'applique pas.")
    return _finding(rule, INSUFFICIENT_EVIDENCE, None, explanation)


def _forbidden_pattern(rule: dict, source) -> dict:
    doc = _document(source)
    match = re.search(rule["check"]["pattern"], doc.text)
    if match:
        return _finding(rule, FAIL, doc.span(match), rule["onFail"])
    # Nothing forbidden. A PASS still needs a passage of the document that addresses the subject: the absence of the
    # wording is not a passage to quote.
    addressed = _subject_match(rule, doc)
    if addressed is not None:
        return _finding(rule, PASS, doc.span(addressed), rule["onPass"])
    return _without_passage(rule, doc, "La règle ne déclare pas son sujet ; elle ne peut pas être évaluée.")


def _numeric_ratio_max(rule: dict, source) -> dict:
    doc = _document(source)
    text = doc.text
    check = rule["check"]
    top = re.search(check["numerator"], text)
    bottom = re.search(check["denominator"], text)
    if not top or not bottom:
        missing = "le montant garanti" if not top else "le loyer de référence"
        return _finding(
            rule,
            INSUFFICIENT_EVIDENCE,
            doc.span(top or bottom) if (top or bottom) else None,
            f"Le document ne chiffre pas {missing} ; la règle ne peut pas être évaluée.",
        )
    try:
        ratio = _number(top.group(1)) / _number(bottom.group(1))
    except (ValueError, ZeroDivisionError):
        return _finding(
            rule,
            INSUFFICIENT_EVIDENCE,
            doc.span(top),
            "Les montants trouvés ne sont pas exploitables ; la règle ne peut pas être évaluée.",
        )
    if ratio <= check["max"] + 1e-9:
        return _finding(rule, PASS, doc.span(top), rule["onPass"])
    return _finding(
        rule,
        FAIL,
        doc.span(top),
        f"{rule['onFail']} Constaté : {ratio:.2f} mois.",
    )


_WORDED_NUMBERS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
    "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "douze": 12,
}


def _numeric_min(rule: dict, source) -> dict:
    """A quantity the law sets a FLOOR under, not a clause whose presence is enough.

    Added because FR-LEASE-003 was a REQUIRED_PATTERN looking for the words "durée du bail", for a
    requirement that is a term of at least three years (art. 10). That shape failed twice in one
    pass on a real document: a false FAIL, because the lease said "pour une durée de deux ans" and
    the pattern wanted another phrasing — and the real violation missed, because two years IS the
    breach and a presence check cannot see a number. A lexical check where the law states a
    quantity is the same defect as a lexical check where it states a fact.

    French leases write the term in words as often as in digits, so both are read.
    """
    doc = _document(source)
    text = doc.text
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
            doc.span(match),
            "La durée trouvée n'est pas exploitable ; la règle ne peut pas être évaluée.",
        )
    if value >= check["min"] - 1e-9:
        return _finding(rule, PASS, doc.span(match), rule["onPass"])
    return _finding(
        rule,
        FAIL,
        doc.span(match),
        f"{rule['onFail']} Constaté : {value:g} {check.get('unit', 'an(s)')}.",
    )


CHECKS = {
    "REQUIRED_PATTERN": _required_pattern,
    "FORBIDDEN_PATTERN": _forbidden_pattern,
    "NUMERIC_RATIO_MAX": _numeric_ratio_max,
    "NUMERIC_MIN": _numeric_min,
}


def evaluate(ruleset: dict, rule: dict, text: str) -> dict:
    """One deterministic rule of a ruleset on a text, read the way the ruleset declares (its ``textLayout``)."""
    return CHECKS[rule["check"]["type"]](rule, _Document(text, ruleset.get("textLayout")))


def screen(ruleset: dict, text: str) -> tuple:
    """Every deterministic rule, plus the questions the model still has to be asked.

    Returns ``(findings, judgments)``. ``judgments`` carries one entry per JUDGMENT rule, and it
    is the ONLY thing that reaches a model — a rule that code can decide never costs an inference.
    """
    findings = []
    judgments = []
    doc = _Document(text, ruleset.get("textLayout"))
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
        findings.append(evaluator(rule, doc))
    return findings, judgments


def _quoted_passage(quote: str, doc: "_Document"):
    """The span of the document that a model's quote is, or None when the document does not say it.

    Case, line breaks, runs of spaces and the apostrophe's form are not differences; any other word is. The offsets are
    into the document as given, and the quote is read back from it, so an evidence field is always a passage of the text
    and never a sentence the model wrote.
    """
    words = quote.split()
    if not words:
        return None
    pattern = r"\s+".join("".join("['’]" if c in "'’" else re.escape(c) for c in word) for word in words)
    match = re.search(pattern, doc.original, re.IGNORECASE)
    if match is None:
        return None
    passage = doc.original[match.start() : match.end()]
    return {
        "start": match.start(),
        "end": match.end(),
        "quote": passage[:MAX_QUOTE] + ("…" if len(passage) > MAX_QUOTE else ""),
    }


def merge_judgments(ruleset: dict, deterministic: list, model_answer: str, text: str) -> list:
    """Fold the model's answers into the report, refusing anything that is not a verdict.

    The model is given one job and can fail it three ways: unparseable output, a verdict outside
    the enum, or an answer about a rule nobody asked about. All three degrade to
    ``INSUFFICIENT_EVIDENCE`` for the rule concerned (or ``NOT_APPLICABLE`` when the document does
    not address the rule's subject). A wrong verdict on a compliance report is worse than an absent
    one — the user forwards this to their counterparty.

    A PASS is kept only when the quote the model gave is a passage of ``text``. Without one it is not a
    PASS: the verdict falls back as for any rule with no passage (orazaka-packs#124).
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

    doc = _Document(text, ruleset.get("textLayout"))
    out = list(deterministic)
    for rule_id, rule in by_id.items():
        answer = answers.get(rule_id)
        if answer is None:
            out.append(
                _without_passage(
                    rule, doc, "Le modèle n'a pas rendu de verdict exploitable pour cette règle."
                )
            )
            continue
        verdict = answer["verdict"]
        span = _quoted_passage(str(answer.get("quote") or ""), doc)
        if verdict == FAIL:
            out.append(_finding(rule, FAIL, span, rule["onFail"]))
        elif span is not None and verdict == PASS:
            out.append(_finding(rule, PASS, span, rule["onPass"]))
        elif span is not None:
            out.append(
                _finding(
                    rule,
                    INSUFFICIENT_EVIDENCE,
                    span,
                    "Le modèle n'a pas trouvé dans le document de quoi trancher cette règle.",
                )
            )
        else:
            reason = (
                "Le modèle a répondu PASS sans citer de passage du document : le verdict n'est pas retenu."
                if verdict == PASS
                else "Le modèle n'a pas trouvé dans le document de quoi trancher cette règle."
            )
            out.append(_without_passage(rule, doc, reason))
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


def extract_facts(ruleset: dict, text: str) -> dict:
    """The figures a ruleset DECLARES it reads (`facts`), with the passage each one comes from.

    A rule says whether the lease has a rent; a check downstream (Section G of the Québec form: the new rent against the
    previous one) needs the rent itself. Nothing is inferred: a fact is a declared pattern whose first group is an amount,
    read through the same ``_Document`` the rules read, so its evidence is the document's own passage.

    Each fact is `{"status": "found", "cents": int, "evidenceSpan": {...}}`; `{"status": "blank", "evidenceSpan": ...}`
    when its `label` is there with no amount behind it (a form left empty); `{"status": "absent"}` otherwise. A ruleset
    without `facts` exposes none, and a figure that cannot be read as an amount is absent, never a guess.
    """
    declared = ruleset.get("facts") or []
    if not declared:
        return {}
    doc = _Document(text, ruleset.get("textLayout"))
    facts: dict = {}
    for fact in declared:
        found = re.search(fact["pattern"], doc.text)
        cents = None
        if found:
            try:
                cents = int(round(_number(found.group(1)) * 100))
            except ValueError:
                cents = None
        if cents is not None and cents > 0:
            facts[fact["id"]] = {"status": "found", "cents": cents, "evidenceSpan": doc.span(found)}
            continue
        label = re.search(fact["label"], doc.text) if fact.get("label") else None
        facts[fact["id"]] = {"status": "blank", "evidenceSpan": doc.span(label)} if label else {"status": "absent"}
    return facts


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
