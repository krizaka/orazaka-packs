#!/usr/bin/env python3
"""Stage 1 of ADR-089: what a document IS — kind, jurisdiction, date, language — before any ruleset judges it.

Deterministic and free of any model: a pure function of ``(text, declared kind, jurisdiction, asOf, today)`` over the
kinds shipped as data in ``kinds/*.json`` (``kinds/kind.schema.json``). Kept in its own module, free of AMQP, for the
reason ``rules.py`` is: it is the part with decisions in it, so a test must reach it without a broker.

The decisions, in the order ADR-089 §1 gives them:

* **Each kind is scored by its signals.** A signal is a regular expression an auditor can read, with a weight; the
  passage it matched is kept as the evidence. A kind needs signals of at least ``min_signal_weight`` (setting
  ``law.identify.min-signal-weight``, default 2) to be a candidate; its jurisdiction hints (a tribunal, a code, a
  postal code) add to its weight and name the jurisdiction, but never make a kind a candidate on their own. A text that
  matches one of the kind's ``excludes`` is never that kind.
* **The detected kind wins** when exactly one candidate has the highest weight. Two candidates with the same highest
  weight are ambiguous: the declared kind is used if it names exactly one kind, else the outcome is ``KIND_UNKNOWN``
  — a tie is never broken by a guess.
* **A mismatch is always surfaced**, never silently resolved: ``kindMismatch`` is true when the text is a kind the
  declared one does not agree with, and the detected kind is the one that judges.
* **A kind with no promoted ruleset says so** (``UNSUPPORTED_KIND``): no ruleset runs, and never the lease's.
* **The date** is the caller's ``asOf`` (``INPUT``), else the kind's date signal with its passage (``DOCUMENT``), else
  ``today`` (``TODAY``) — passed in, so two runs of the same document read the same ruleset.
* **The language** is a fact for the language rules (``fr``, ``en``, both), never a verdict by itself.

The model step of §1 (a ``classify`` choice among the closed list of kinds when the signals are ambiguous) is not
here: it is a blueprint step, so it is metered like any other inference, and it arrives with ``compliance-check`` 2.0.
"""

import json
import os
import re
import unicodedata
from datetime import date

KINDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kinds")

#: The default of ``law.identify.min-signal-weight`` (ADR-089 §10).
MIN_SIGNAL_WEIGHT = 2
MAX_QUOTE = 160

CHECK = "CHECK"
KIND_UNKNOWN = "KIND_UNKNOWN"
UNSUPPORTED_KIND = "UNSUPPORTED_KIND"

PROMOTED = "PROMOTED"
KNOWN = "KNOWN"
RETIRED = "RETIRED"


class UnknownRuleset(Exception):
    """The caller named a ruleset no kind carries — say so, do not fall back."""


def load_kinds() -> list:
    """Every kind of the pack, from ``kinds/*.json`` (the schema file excluded), in a stable order."""
    found = []
    for name in sorted(os.listdir(KINDS_DIR)):
        if name.endswith(".json") and name != "kind.schema.json":
            with open(os.path.join(KINDS_DIR, name), encoding="utf-8") as handle:
                found.append(json.load(handle))
    return found


# --- Dates -----------------------------------------------------------------------------------------------------------

_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DAY_FIRST = re.compile(r"^(\d{1,2})(?:er)?\s+([^\W\d_]+)\s+(\d{4})$")
_MONTH_FIRST = re.compile(r"^([^\W\d_]+)\s+(\d{1,2}),?\s+(\d{4})$")


def _ascii(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word.lower()) if not unicodedata.combining(c))


def parse_date(written: str):
    """A date as a human writes it (``2026-10-20``, ``20 octobre 2026``, ``October 20, 2026``) → ISO, or ``None``.

    An impossible date (month 13) is not a date: ``None``, never a guess.
    """
    written = " ".join(written.split())
    try:
        match = _ISO.match(written)
        if match:
            return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
        match = _DAY_FIRST.match(written)
        if match and _ascii(match[2]) in _MONTHS:
            return date(int(match[3]), _MONTHS[_ascii(match[2])], int(match[1])).isoformat()
        match = _MONTH_FIRST.match(written)
        if match and _ascii(match[1]) in _MONTHS:
            return date(int(match[3]), _MONTHS[_ascii(match[1])], int(match[2])).isoformat()
    except ValueError:
        return None
    return None


# --- Language --------------------------------------------------------------------------------------------------------

_WORDS = re.compile(r"[a-zàâçéèêëîïôûùüÿœ]+")
_FR = frozenset("le la les des du et est pour dans une au aux par sur avec qui que sont ce cette ou de".split())
_EN = frozenset("the and of to is for that this with are be by shall will from has have not".split())


def languages(text: str) -> list:
    """``["fr"]``, ``["en"]``, ``["en", "fr"]`` (both) or ``[]`` (too little text), from function words only.

    A language is present when it has at least 3 function words and at least a quarter of the other's count.
    """
    words = _WORDS.findall(text.lower())
    counts = {"fr": sum(w in _FR for w in words), "en": sum(w in _EN for w in words)}
    top = max(counts.values())
    return sorted(code for code, n in counts.items() if n >= 3 and n * 4 >= top)


# --- Signals ---------------------------------------------------------------------------------------------------------

def _quote(match) -> str:
    return match.group(0)[:MAX_QUOTE]


def _hits(signals: list, text: str) -> list:
    """The signals that match, each with the passage it matched. ``verified``: the passage is in the text."""
    found = []
    for signal in signals:
        match = re.search(signal["pattern"], text)
        if match:
            quote = _quote(match)
            found.append({"signal": signal["id"], "weight": signal["weight"], "quote": quote, "verified": quote in text})
    return found


def _score(kind: dict, text: str) -> dict:
    content = _hits(kind["signals"], text)
    hints = _hits(kind["jurisdictionHints"], text)
    excluded = any(re.search(pattern, text) for pattern in kind["excludes"])
    return {
        "kind": kind, "content": content, "hints": hints, "excluded": excluded,
        "contentWeight": sum(h["weight"] for h in content),
        "weight": sum(h["weight"] for h in content) + sum(h["weight"] for h in hints),
    }


def _date_of(kind: dict, text: str):
    """(ISO date, evidence) of the kind's date signal that names the ``asOf``, else its first readable one."""
    signals = sorted(kind["dateSignals"], key=lambda s: s["id"] != kind["asOfFrom"])
    for signal in signals:
        for match in re.finditer(signal["pattern"], text):
            written = next((g for g in match.groups() if g), None)
            parsed = parse_date(written) if written else None
            if parsed:
                return parsed, {"signal": signal["id"], "quote": _quote(match), "verified": _quote(match) in text}
    return None, None


def _evidence(scored: dict) -> list:
    return [{k: e[k] for k in ("signal", "quote", "verified")} for e in scored["content"] + scored["hints"]]


def _candidate(scored: dict, min_weight: int) -> dict:
    return {
        "kindId": scored["kind"]["kindId"], "weight": scored["weight"], "signals": [e["signal"] for e in scored["content"]],
        "hints": [e["signal"] for e in scored["hints"]], "excluded": scored["excluded"],
        "eligible": not scored["excluded"] and scored["contentWeight"] >= min_weight,
    }


def identify(text: str, *, today: str, declared_kind=None, jurisdiction=None, as_of=None, ruleset=None,
             min_signal_weight: int = MIN_SIGNAL_WEIGHT, kinds=None) -> dict:
    """Identify ``text``: the kind, the jurisdiction, the date and the language, compared with what was declared.

    ``today`` (ISO date) is given, never read: the caller owns the clock. ``as_of`` is validated as an ISO date
    (``ValueError`` otherwise). ``ruleset`` is the explicit 1.x override and wins over everything.
    """
    text = unicodedata.normalize("NFC", text or "")
    declared = (declared_kind or "").strip() or None
    jurisdiction = (jurisdiction or "").strip() or None
    as_of = (as_of or "").strip() or None
    ruleset = (ruleset or "").strip() or None
    if as_of:
        date.fromisoformat(as_of)
    date.fromisoformat(today)

    live = [k for k in (kinds if kinds is not None else load_kinds()) if k["status"] != RETIRED]
    scope = [k for k in live if jurisdiction is None or k["jurisdiction"] == jurisdiction]
    scored = [_score(k, text) for k in scope]
    candidates = [_candidate(s, min_signal_weight) for s in scored]
    eligible = [s for s in scored if not s["excluded"] and s["contentWeight"] >= min_signal_weight]
    top = max((s["weight"] for s in eligible), default=None)
    leaders = [s for s in eligible if s["weight"] == top]
    detected = leaders[0] if len(leaders) == 1 else None

    used, source = None, None
    if ruleset:
        carrying = [k for k in scope if k["ruleset"] == ruleset]
        if not carrying:
            raise UnknownRuleset(f"no kind uses the ruleset '{ruleset}'" + (f" in '{jurisdiction}'" if jurisdiction else ""))
        used, source = carrying[0], "RULESET_INPUT"
    elif detected:
        used, source = detected["kind"], "DETECTED"
    elif declared:
        agreeing = [k for k in scope if declared in k["declaredAs"]]
        if len(agreeing) == 1:
            used, source = agreeing[0], "DECLARED"

    mismatch = bool(detected and declared and not ruleset and declared not in detected["kind"]["declaredAs"])

    if used is None:
        outcome = KIND_UNKNOWN
    elif used["status"] == PROMOTED:
        outcome = CHECK
    else:
        outcome = UNSUPPORTED_KIND

    evidence = []
    if source == "RULESET_INPUT" or source == "DETECTED":
        used_scored = next(s for s in scored if s["kind"] is used)
        evidence = _evidence(used_scored)

    if jurisdiction:
        jurisdiction_out, jurisdiction_source = jurisdiction, "DECLARED"
    elif used:
        jurisdiction_out, jurisdiction_source = used["jurisdiction"], "DETECTED"
    else:
        jurisdiction_out, jurisdiction_source = _jurisdiction_from_hints(scored, min_signal_weight)

    document_date, date_evidence = _date_of(used, text) if used else (None, None)
    if as_of:
        as_of_out, as_of_source = as_of, "INPUT"
    elif document_date:
        as_of_out, as_of_source = document_date, "DOCUMENT"
    else:
        as_of_out, as_of_source = today, "TODAY"

    return {
        "declaredKind": declared,
        "detectedKind": detected["kind"]["kindId"] if detected else None,
        "kindUsed": used["kindId"] if used else None,
        "kindLabel": used["label"] if used else None,
        "kindStatus": used["status"] if used else None,
        "kindSource": source,
        "kindEvidence": evidence,
        "kindMismatch": mismatch,
        "ruleset": used["ruleset"] if used and outcome == CHECK else None,
        "jurisdiction": jurisdiction_out,
        "jurisdictionSource": jurisdiction_source,
        "documentDate": document_date,
        "dateEvidence": date_evidence,
        "asOf": as_of_out,
        "asOfSource": as_of_source,
        "languages": languages(text),
        "outcome": outcome,
        "candidates": candidates,
    }


def _jurisdiction_from_hints(scored: list, min_weight: int):
    """No kind decided: the jurisdiction whose hints weigh most (each distinct hint once), if one leads clearly."""
    weights = {}
    seen = set()
    for s in scored:
        for hint in s["hints"]:
            key = (s["kind"]["jurisdiction"], hint["signal"], hint["quote"])
            if key not in seen:
                seen.add(key)
                weights[s["kind"]["jurisdiction"]] = weights.get(s["kind"]["jurisdiction"], 0) + hint["weight"]
    ranked = sorted(weights.items(), key=lambda item: -item[1])
    if ranked and ranked[0][1] >= min_weight and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
        return ranked[0][0], "DETECTED"
    return None, None


# --- Stage 2: what the retrieval of the law is asked ---------------------------------------------------------------

#: The research source of the corpus (``research_source.source_key``): grounded research reads the law through it.
LAW_CORPUS_SOURCE = "law-corpus"


def retrieval_request(kind: dict, language: str, as_of: str, *, run_id=None) -> dict:
    """The input of the grounded step that retrieves the law of a kind (ADR-089 §2), built from the kind's data.

    ``orazaka.core.research.grounded`` is called with ``sources: ["law-corpus"]``, the jurisdiction, ``asOf`` and a
    question; ``targets`` names the instruments and articles the engine reads in the corpus, and nothing else is read:
    a visit notice brings art. 1931 to 1933 and no rent article. Pure data: no model, no clock, no network.

    A kind with no ``retrieval`` block (or a language other than ``fr``/``en``, or a date that is not ISO) is refused
    by name, never answered with a guess.
    """
    retrieval = kind.get("retrieval")
    if not retrieval:
        raise ValueError(f"{kind.get('kindId')}: this kind declares no retrieval")
    if language not in ("fr", "en"):
        raise ValueError("language must be fr or en")
    if not _ISO.match(as_of or ""):
        raise ValueError("asOf must be an ISO date (YYYY-MM-DD)")
    request = {
        "sources": [LAW_CORPUS_SOURCE],
        "jurisdiction": kind["jurisdiction"],
        "kindId": kind["kindId"],
        "asOf": as_of,
        "language": language,
        "question": retrieval["question"][language],
        "targets": [{"instrument": t["instrument"], "refs": list(t["refs"])} for t in retrieval["targets"]],
    }
    if run_id:
        request["runId"] = run_id
    return request
