"""Which of the two languages a text is in — or neither. A coarse stopword count: enough to pick a threshold, never to claim more."""

import re

EN = frozenset("the and you your are was were have has with that this for not but what where when who how can will would about just really love like from they them there their been being than then too very also".split())
FR = frozenset("le la les un une des et est sont que qui quoi dans pour pas mais avec sur tu toi ton ta tes vous vos je j' il elle nous on ce cette ces au aux du de d' en y plus très aussi comme ça c' qu' t' m' l'".split())

_TOKEN = re.compile(r"[a-zà-ÿ’']+", re.IGNORECASE)


def detect(text: str) -> str:
    """``en``, ``fr`` or ``other`` — ``other`` when the words do not clearly lean one way."""
    tokens = [t.lower().replace("’", "'") for t in _TOKEN.findall(text)]
    if not tokens:
        return "other"
    en = sum(t in EN for t in tokens)
    fr = sum(t in FR or t.split("'")[0] + "'" in FR for t in tokens)
    if max(en, fr) < 2 or abs(en - fr) < max(1, int(0.25 * max(en, fr))):
        return "other"
    return "en" if en > fr else "fr"
