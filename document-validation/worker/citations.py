#!/usr/bin/env python3
"""The second quote of a finding: the article it cites, checked against the text the ruleset pins (ADR-089 §4).

A promoted rule carries ``law`` blocks — instrument, ref, language, ``inForceFrom``, ``contentHash``, the official URL
and the article's quote. The hash names one version of one article; the pack holds that version's text in ``law/``
(one JSON per article version: ``{instrument, ref, language, inForceFrom, contentHash, officialUrl}`` — the reference
only, never a Québec article's text in a public repository), read from the dated, hashed corpus (ADR-089 §2). The text
a quote is checked against comes from ``text_of`` (the engine, from the official source or a private store); an article
file may carry a ``text`` only when it is fictional (the tests' own), and then it must hash to its name. A citation is ``VERIFIED`` only when the pack holds the article the hash names
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
#: The pack holds the reference of the article, but no text to check the quote against (none given, none fictional).
TEXT_NOT_HELD = "TEXT_NOT_HELD"

#: What a finding whose rule pins no article shows beside its citation, in both languages.
UNPINNED_NOTICE = {
    "fr": "Citation non épinglée : l'article est cité en toutes lettres, sans texte daté ni empreinte à vérifier.",
    "en": "Unpinned citation: the article is cited in words, with no dated, hashed text to check.",
}

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
            if "text" in article and content_hash(article["text"]) != article["contentHash"]:
                raise ValueError(f"{name}: its text does not hash to {article['contentHash']}")
            held[article["contentHash"]] = article
    return held


def check(block: dict, articles: dict, text_of=None) -> str:
    """The status of one ``law`` block against the articles held.

    ``text_of(article)`` returns the article's text (or ``None``); without it, only a fictional article's own ``text``
    counts. An article held by reference with no text is ``TEXT_NOT_HELD``: the quote is not verified, never trusted.
    """
    article = articles.get(block.get("contentHash"))
    if article is None or any(article.get(k) != block.get(k) for k in ("instrument", "ref", "language")):
        return ARTICLE_NOT_HELD
    text = (text_of(article) if text_of else None) or article.get("text")
    if text is None:
        return TEXT_NOT_HELD
    return VERIFIED if quotes.contains(text, block.get("quote") or "") else QUOTE_NOT_IN_ARTICLE


def cite(rule: dict, articles: dict, text_of=None) -> tuple:
    """``(citation, status)`` of a rule: what a finding shows of its article, and whether every pinned quote held.

    The citation keeps the rule's words (``reference``) and, when the rule pins articles, the first ``law`` block's
    fields; the other blocks follow in ``also``. The status is the first block's that is not ``VERIFIED``, else
    ``VERIFIED``; a rule with no ``law`` block is ``NOT_PINNED``.
    """
    blocks = rule.get("law") or []
    citation = {"reference": rule.get("citation"), "pinned": bool(blocks)}
    if not blocks:
        # Never silent (CTO, orazaka-studio#80): the finding says its article is cited in words only.
        return dict(citation, notice=UNPINNED_NOTICE), NOT_PINNED
    citation.update({k: blocks[0].get(k) for k in FIELDS})
    if len(blocks) > 1:
        citation["also"] = [{k: b.get(k) for k in FIELDS} for b in blocks[1:]]
    statuses = [check(b, articles, text_of) for b in blocks]
    return citation, next((s for s in statuses if s != VERIFIED), VERIFIED)


def corpus_mismatches(articles: dict, lookup) -> list:
    """The held article versions whose hash is not the corpus row's (ADR-089 cut 3, ``lookupStatute``).

    ``law/`` is a snapshot for offline verification, never a second corpus: when the corpus is reachable, each held
    version must be the row in force on its ``inForceFrom``. ``lookup(article)`` returns the corpus answer
    (``{contentHash, …}``) or ``None`` for ``LAW_VERSION_UNKNOWN``; each mismatch is named, never repaired.
    """
    found = []
    for content_hash, article in sorted(articles.items()):
        row = lookup(article)
        if row is None or row.get("contentHash") != content_hash:
            corpus = row["contentHash"][:12] if row and row.get("contentHash") else "LAW_VERSION_UNKNOWN"
            found.append(f"{article['instrument']} art. {article['ref']} ({article['language']}, {article['inForceFrom']}): "
                         f"held {content_hash[:12]}, corpus {corpus}")
    return found
