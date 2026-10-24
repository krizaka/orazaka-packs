#!/usr/bin/env python3
"""Whether a quote is a passage of a text — the one comparison every check of this pack makes (ADR-087 §3).

A model's quote, a classify answer's quote, an article's quote: each is kept only when the text it claims to come from
really says it. Typography never decides that: the comparison is made on the normal form of ``QuoteNormalizer``
(orazaka-ai-engine), mirrored here because a Tier-W worker links no Orazaka library.
"""

import re
import unicodedata

_DOUBLE_QUOTES = re.compile("[«»“”„‟″]")
_SINGLE_QUOTES = re.compile("[‘’‚‛′`´]")
_DASHES = re.compile("[‐‑‒–—―−]")
_SPACES = re.compile(r"[\s     -    　]+")


def normalise(text: str) -> str:
    """NFC, case folded, « » “ ” to ", ’ to ', œ/æ to oe/ae, dashes to -, the ellipsis to three dots, every space
    (no-break and narrow ones included) to one, and the spaces inside French quotation marks dropped."""
    s = unicodedata.normalize("NFC", text or "").lower().replace("œ", "oe").replace("æ", "ae").replace("…", "...")
    s = _SPACES.sub(" ", _DASHES.sub("-", _SINGLE_QUOTES.sub("'", _DOUBLE_QUOTES.sub('"', s))))
    return s.replace('" ', '"').replace(' "', '"').strip()


def contains(text: str, quote: str) -> bool:
    """Whether ``quote`` appears in ``text`` once both are normalised. An empty quote is never found."""
    needle = normalise(quote)
    return bool(needle) and needle in normalise(text)
