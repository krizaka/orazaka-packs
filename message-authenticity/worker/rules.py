"""From a classifier score to a coarse level — the score itself never leaves this module's caller.

``LOW · MID · HIGH`` by the thresholds of the ruleset in force (per language), ``UNAVAILABLE`` when the engine should not guess:
a language it was not calibrated on, or a text under the ruleset's minimum number of words. The report is a closed shape
(``detector``, ``language``, ``rulesetVersion``, ``limits``): a test fails if a number or a probability appears in it.
"""

import glob
import json
import os
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
RULESETS = os.path.join(HERE, "..", "rules", "message-authenticity")
LEVELS = ("LOW", "MID", "HIGH", "UNAVAILABLE")


def load_ruleset(as_of: Optional[str] = None) -> dict:
    """The ruleset in force on ``as_of`` (``YYYY-MM-DD``; the newest when omitted)."""
    files = sorted(glob.glob(os.path.join(RULESETS, "*.json")))
    if not files:
        raise FileNotFoundError("no ruleset for message authenticity")
    chosen = None
    for path in files:
        if as_of is None or os.path.basename(path)[: -len(".json")] <= as_of:
            chosen = path
    if chosen is None:
        raise LookupError(f"no ruleset in force on {as_of}")
    with open(chosen, encoding="utf-8") as handle:
        return json.load(handle)


def level(score: float, thresholds: dict) -> str:
    if score >= thresholds["high"]:
        return "HIGH"
    if score >= thresholds["mid"]:
        return "MID"
    return "LOW"


def report(ruleset: dict, language: str, words: int, score: Optional[float]) -> dict:
    """The closed report. ``score`` is None when the classifier was not run."""
    thresholds = ruleset["languages"].get(language)
    if thresholds is None or words < ruleset["minWords"] or score is None:
        detector = "UNAVAILABLE"
    else:
        detector = level(score, thresholds)
    return {"detector": detector, "language": language, "rulesetVersion": ruleset["version"], "limits": ruleset["limits"]}
