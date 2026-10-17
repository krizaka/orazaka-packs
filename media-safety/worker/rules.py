"""The safety verdict: pure rules over what two model steps answered. **A safety check fails closed.**

``looks`` are the vision model's JSON answers, one per sampled picture; ``heard`` is the chat model's JSON answer about a transcript
(absent when there was no audio). Every answer is checked for its shape: an answer that is not the expected JSON, or misses a
field, is **UNREADABLE** — and an unreadable answer is never a pass (the product holds the media for a person to look at, it does not
approve it). The report is codes; the pack words nothing.
"""

import glob
import json
import os
import re
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
RULESETS = os.path.join(HERE, "..", "rules", "media-safety")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def load_ruleset(as_of: Optional[str] = None) -> dict:
    files = sorted(glob.glob(os.path.join(RULESETS, "*.json")))
    if not files:
        raise FileNotFoundError("no ruleset for media safety")
    chosen = None
    for path in files:
        if as_of is None or os.path.basename(path)[: -len(".json")] <= as_of:
            chosen = path
    if chosen is None:
        raise LookupError(f"no ruleset in force on {as_of}")
    return json.load(open(chosen, encoding="utf-8"))


def parse(answer: object) -> Optional[dict]:
    """The JSON object a model answered (it may wrap it in a sentence or a fence), or None."""
    if isinstance(answer, dict):
        for key in ("analysis", "content", "text"):
            if isinstance(answer.get(key), str):
                return parse(answer[key])
        return answer
    if not isinstance(answer, str):
        return None
    text = _FENCE.sub("", answer.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _yes(value: object) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "oui"})


def _judge(checks: list, answer: object) -> Optional[list]:
    """The codes an answer raises, or None when the answer is unreadable (missing or not a boolean for some field)."""
    parsed = parse(answer)
    if parsed is None:
        return None
    codes = []
    for check in checks:
        value = parsed.get(check["field"])
        if not (isinstance(value, bool) or (isinstance(value, str) and value.strip().lower() in {"true", "false", "yes", "no", "oui", "non"})):
            return None
        if _yes(value):
            codes.append(check["id"])
    return codes


def assess(ruleset: dict, looks: Optional[list], frames: int, heard: object, expects_speech: bool) -> dict:
    """``frames`` pictures were sent, ``looks`` are the answers (a list of another length leaves the missing ones unread)."""
    answers = looks if isinstance(looks, list) else []
    findings: list[dict] = []
    unreadable = 0
    for index in range(frames):
        codes = _judge(ruleset["look"]["checks"], answers[index] if index < len(answers) else None)
        if codes is None:
            unreadable += 1
        else:
            findings += [{"code": code, "frame": index} for code in codes]
    if expects_speech:
        codes = _judge(ruleset["listen"]["checks"], heard)
        if codes is None:
            unreadable += 1
        else:
            findings += [{"code": code, "frame": None} for code in codes]
    if frames == 0 and not expects_speech:
        unreadable += 1  # nothing was examined: that is not a pass
    blockers = sorted({f["code"] for f in findings})
    verdict = "REJECTED" if blockers else ("UNREADABLE" if unreadable else "APPROVED")
    return {
        "rulesetId": ruleset["rulesetId"],
        "rulesetVersion": ruleset["version"],
        "rulesetRevision": ruleset.get("revision", 1),
        "verdict": verdict,
        "blockers": blockers,
        "findings": findings,
        "examined": {"frames": frames, "speech": bool(expects_speech)},
        "unreadable": unreadable,
        "limits": ruleset["limits"],
    }
