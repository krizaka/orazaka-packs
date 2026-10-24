#!/usr/bin/env python3
"""The second quote of a finding: the article it cites, checked against the text the ruleset pins (ADR-089 §4).

A promoted rule carries ``law`` blocks — instrument, ref, language, ``inForceFrom``, ``contentHash``, the official URL
and the article's quote. The hash names one version of one article; the pack holds that version's text in ``law/``
(one JSON per article version: ``{instrument, ref, language, inForceFrom, contentHash, officialUrl, text}``), read from
the dated, hashed corpus (ADR-089 §2). A citation is ``VERIFIED`` only when the pack holds the article the hash names
and its quote is a passage of that text; anything else is said by name, and the finding it backs is not a verdict.

Pure data and pure functions: no model, no network, no clock.
"""

import hashlib
import json
import os
import re
import unicodedata

import quotes

LAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "law")

VERIFIED = "VERIFIED"
#: The rule cites its article in words only (a ruleset written before ADR-089): there is no pinned text to check.
NOT_PINNED = "NOT_PINNED"
#: The hash names no article version the pack holds, or one of another article.
ARTICLE_NOT_HELD = "ARTICLE_NOT_HELD"
QUOTE_NOT_IN_ARTICLE = "QUOTE_NOT_IN_ARTICLE"

#: What a finding's citation carries of a ``law`` block.
FIELDS = ("instrument", "ref", "language", "officialUrl", "inForceFrom", "contentHash", "quote")

_WHITESPACE = re.compile(r"[\s ]+")


def content_hash(text: str) -> str:
    """SHA-256 of an article's text once normalised: NFC, every run of whitespace one space, trimmed.

    The definition of the corpus (``ContentHash`` in orazaka-ai-engine): two layouts of one text have one hash.
    """
    normal = _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text or "")).strip()
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()


def load_articles(directory: str = LAW_DIR) -> dict:
    """Every article version the pack holds, by ``contentHash``. A file whose text does not hash to its name is refused.

    A missing directory holds nothing: every pinned citation is then ``ARTICLE_NOT_HELD``, never trusted.
    """
    held = {}
    if not os.path.isdir(directory):
        return held
    for root, _, files in os.walk(directory):
        for name in sorted(files):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(root, name), encoding="utf-8") as handle:
                article = json.load(handle)
            if content_hash(article["text"]) != article["contentHash"]:
                raise ValueError(f"{name}: its text does not hash to {article['contentHash']}")
            held[article["contentHash"]] = article
    return held


def check(block: dict, articles: dict) -> str:
    """The status of one ``law`` block against the articles held."""
    article = articles.get(block.get("contentHash"))
    if article is None or any(article.get(k) != block.get(k) for k in ("instrument", "ref", "language")):
        return ARTICLE_NOT_HELD
    return VERIFIED if quotes.contains(article["text"], block.get("quote") or "") else QUOTE_NOT_IN_ARTICLE


def cite(rule: dict, articles: dict) -> tuple:
    """``(citation, status)`` of a rule: what a finding shows of its article, and whether every pinned quote held.

    The citation keeps the rule's words (``reference``) and, when the rule pins articles, the first ``law`` block's
    fields; the other blocks follow in ``also``. The status is the first block's that is not ``VERIFIED``, else
    ``VERIFIED``; a rule with no ``law`` block is ``NOT_PINNED``.
    """
    blocks = rule.get("law") or []
    citation = {"reference": rule.get("citation")}
    if not blocks:
        return citation, NOT_PINNED
    citation.update({k: blocks[0].get(k) for k in FIELDS})
    if len(blocks) > 1:
        citation["also"] = [{k: b.get(k) for k in FIELDS} for b in blocks[1:]]
    statuses = [check(b, articles) for b in blocks]
    return citation, next((s for s in statuses if s != VERIFIED), VERIFIED)
