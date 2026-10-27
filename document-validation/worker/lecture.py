#!/usr/bin/env python3
"""The « lecture » of a document whose kind has no promoted ruleset (ADR-089 §6): what the law says near it, never a verdict.

A document of a ``KNOWN`` kind with no ruleset (``UNSUPPORTED_KIND``) or of no kind (``KIND_UNKNOWN``) is never judged.
The run says so. When the caller asks (``lecture: true``) and the switch is on (``AI_LAW_LECTURE_ENABLED``, the
environment form of ``law.lecture.enabled``, off as seeded), it may add a lecture: claims that **pair an article of the
law corpus with a passage of the document**, written by one grounded call and re-checked here by code.

* A claim is ``VERIFIED`` only when **both** quotes are found: the article (the grounded step verified it in the corpus,
  and this pack re-checks it when it holds that article's text) **and** the passage in the document. Anything else is
  ``TO_VALIDATE`` with the reason by name; a claim whose document passage is absent is never ``VERIFIED``.
* There is **no verdict field**: the lecture is rebuilt from a closed list of fields, so nothing a model adds (a
  ``verdict``, a ``score``) can reach the report, and the blueprint's contract refuses any other key.
* ``audit`` is always ``"UNAUDITED"``: no one has checked these claims, and the product must say so.
* ``kind_demand`` is the one thing counted: the jurisdiction and the kind id (or ``UNKNOWN``), never a word of the
  document (ADR-064). The review queue reads it to decide what to derive next; demand alone starts nothing.

Free of AMQP like ``rules`` and ``identify``, so a test reaches every decision without a broker.
"""

import json
import os
import re

import identify
import quotes

#: Always set. The lecture is not audited by anyone; this is the word the product shows.
AUDIT = "UNAUDITED"

#: The environment form of the setting ``law.lecture.enabled`` (ADR-089 §10), beside ``AI_LAW_CORPUS_ENABLED``. Off by default.
ENV_SWITCH = "AI_LAW_LECTURE_ENABLED"

#: Where a kind id would be when the document has none.
UNKNOWN = "UNKNOWN"

VERIFIED = "VERIFIED"
TO_VALIDATE = "TO_VALIDATE"

#: Why a claim stays ``TO_VALIDATE``, by name. The article leg, then the document leg.
ARTICLE_NOT_VERIFIED = "ARTICLE_NOT_VERIFIED"
QUOTE_NOT_IN_ARTICLE = "QUOTE_NOT_IN_ARTICLE"
PASSAGE_ABSENT = "PASSAGE_ABSENT"
PASSAGE_NOT_IN_DOCUMENT = "PASSAGE_NOT_IN_DOCUMENT"

#: What the lecture shows beside its claims, in both languages (the product shows it).
NOTICE = {
    "fr": "Lecture non auditée : des extraits de la loi rapprochés de passages du document. Ce n'est ni un verdict ni un contrôle de conformité.",
    "en": "Unaudited reading: extracts of the law set beside passages of the document. It is neither a verdict nor a compliance check.",
}

#: At most this many claims are kept, and each text this long: a lecture is short.
MAX_CLAIMS = 8
MAX_TEXT = 500

#: The url of the citation that points at the document the caller sent, not at the law.
DOCUMENT_URL = "document://input"

_HASH = re.compile(r"^[0-9a-f]{64}$")

#: Questions of the grounded call, by language, when the kind brings none of its own.
_QUESTION = {
    "fr": "Quels articles du corpus de lois se rapportent au document fourni ? Pour chaque article, cite le passage du document qu'il éclaire. Ne rends aucun verdict.",
    "en": "Which articles of the law corpus relate to the document provided? For each article, quote the passage of the document it bears on. Give no verdict.",
}


def enabled(environ=None) -> bool:
    """Whether the lecture may run at all: off unless the switch is exactly ``true``."""
    return (environ if environ is not None else os.environ).get(ENV_SWITCH) == "true"


def wanted(value) -> bool:
    """Whether the caller asked for a lecture: ``true`` (a boolean, or the word a template renders). Anything else is no."""
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def kind_demand(identification: dict) -> dict:
    """What is counted when a document has no promoted ruleset: where it is from and which kind it is, nothing else.

    Never the document, a quote of it, its date or its language (ADR-064). A document of no kind counts under ``UNKNOWN``.
    """
    unsupported = identification.get("outcome") == identify.UNSUPPORTED_KIND
    return {
        "jurisdiction": identification.get("jurisdiction") or UNKNOWN,
        "kindId": (identification.get("kindUsed") or UNKNOWN) if unsupported else UNKNOWN,
    }


def request(identification: dict, kinds=None) -> dict:
    """The input of the grounded call that reads the law near the document (ADR-089 §6), built from data only.

    The kind's own retrieval (its articles and question) is used when it has one; otherwise the corpus is asked the
    generic question. The document is passed as data by the blueprint, never put in the question.
    """
    languages = identification.get("languages") or []
    language = "en" if languages[:1] == ["en"] else "fr"
    kind = next((k for k in (kinds if kinds is not None else identify.load_kinds()) if k["kindId"] == identification.get("kindUsed")), None)
    if kind and kind.get("retrieval"):
        built = identify.retrieval_request(kind, language, identification["asOf"])
        built.pop("kindId", None)
        built["question"] = f'{built["question"]} {_QUESTION[language]}'
        return built
    return {
        "sources": [identify.LAW_CORPUS_SOURCE],
        "jurisdiction": identification.get("jurisdiction") or "",
        "asOf": identification["asOf"],
        "language": language,
        "question": _QUESTION[language],
        "targets": [],
    }


def verify(raw, document: str, articles: dict) -> dict:
    """The lecture: every claim of the grounded answer re-checked on both legs, rebuilt from a closed list of fields.

    ``raw`` is the claims of the grounded answer (a list, a ``{"claims": […]}`` object or either as JSON text). A claim
    pairs a citation of the law (an article: url, quote, content hash) with a citation of the document
    (``document://input`` and the passage). Nothing is read from a claim beyond those fields.
    """
    claims = []
    for item in _claims(raw)[:MAX_CLAIMS]:
        claim = _claim(item, document, articles)
        if claim:
            claims.append(claim)
    return {"audit": AUDIT, "notice": dict(NOTICE), "claims": claims}


def _claims(raw) -> list:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        raw = raw.get("claims")
    return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []


def _claim(item: dict, document: str, articles: dict):
    text = str(item.get("text") or "").strip()[:MAX_TEXT]
    if not text:
        return None
    cites = [c for c in item.get("citations") or [] if isinstance(c, dict)]
    article = next((c for c in cites if not str(c.get("url") or "").startswith("document:")), None)
    passage_cite = next((c for c in cites if str(c.get("url") or "").startswith("document:")), None)
    passage = str((passage_cite or {}).get("quote") or "")
    article_leg = _article_leg(item, article, articles)
    passage_leg = "ABSENT" if not passage.strip() else VERIFIED if quotes.contains(document, passage) else "NOT_IN_DOCUMENT"
    reason = None
    if article_leg != VERIFIED:
        reason = QUOTE_NOT_IN_ARTICLE if article_leg == QUOTE_NOT_IN_ARTICLE else ARTICLE_NOT_VERIFIED
    elif passage_leg != VERIFIED:
        reason = PASSAGE_ABSENT if passage_leg == "ABSENT" else PASSAGE_NOT_IN_DOCUMENT
    out = {
        "text": text,
        "status": TO_VALIDATE if reason else VERIFIED,
        "article": {k: str((article or {}).get(k) or "") for k in ("url", "quote", "contentHash")},
        "passage": passage if passage_leg == VERIFIED else "",
        "checks": {"article": article_leg, "passage": passage_leg},
    }
    if reason:
        out["reason"] = reason
    return out


def _article_leg(item: dict, article, articles: dict) -> str:
    """VERIFIED when the grounded step verified the article quote and this pack, holding the text, agrees."""
    if not article or item.get("status") != VERIFIED:
        return ARTICLE_NOT_VERIFIED
    quote, content_hash = str(article.get("quote") or ""), str(article.get("contentHash") or "")
    if not quote.strip() or not _HASH.match(content_hash):
        return ARTICLE_NOT_VERIFIED
    held = articles.get(content_hash)
    if held is not None and not quotes.contains(held["text"], quote):
        return QUOTE_NOT_IN_ARTICLE
    return VERIFIED
