"""The photo rules: turning facts (faces, identity, what a vision model saw) into a verdict made of codes.

Pure functions of ``(ruleset, facts, model answers, the caller's counts)`` — no broker, no model, no OpenCV — so the
part that decides whether someone may continue is the part that is tested hardest. A word of French or English never
appears here: the report is **codes**; the product that asked words them in its own language and register.

Three kinds of finding, by who found them:

* counts the caller asked for (``TOO_FEW_PHOTOS``, ``TOO_MANY_PHOTOS``, ``TOO_FEW_FACE_PHOTOS``);
* what the face models measured (``NO_FACE`` is not a finding — a landscape is welcome — but ``FACE_MISMATCH`` is);
* what a vision model *said* it saw (``MINOR_LIKELY``, ``TEXT_OR_CONTACT``, ``SCREENSHOT``). A model that answers in the
  wrong shape produces ``UNVERIFIED`` for that photo and blocks nothing: guessing would be worse in both directions.

The pack never recognises a celebrity and says so in the report's ``limits``.
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
RULESETS = os.path.join(HERE, "..", "rules", "profile-photo")

BLOCK = "BLOCK"
INFO = "INFO"


def load_ruleset(as_of: Optional[str] = None) -> dict:
    """The ruleset in force on ``as_of`` (``YYYY-MM-DD``; today when omitted) — never the newest file by default."""
    files = sorted(glob.glob(os.path.join(RULESETS, "*.json")))
    if not files:
        raise FileNotFoundError("no ruleset for profile photos")
    chosen = None
    for path in files:
        effective = os.path.basename(path)[: -len(".json")]
        if as_of is None or effective <= as_of:
            chosen = path
    if chosen is None:
        raise LookupError(f"no ruleset in force on {as_of}")
    with open(chosen, encoding="utf-8") as handle:
        return json.load(handle)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_look(answer: object) -> Optional[dict]:
    """The JSON object a vision model answered, or None when it is not one (never an exception, never a guess).

    A step's output may arrive as the text itself or wrapped (``{"analysis": "<text>"}``); both are read.
    """
    if isinstance(answer, dict):
        for key in ("analysis", "text", "content"):
            if isinstance(answer.get(key), str):
                return parse_look(answer[key])
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
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in {"true", "yes", "oui"}


def look_findings(ruleset: dict, answer: object) -> list[dict]:
    """The findings of one photo from the vision model's answer; ``UNVERIFIED`` when the answer is unusable."""
    parsed = parse_look(answer)
    checks = ruleset["look"]["checks"]
    if parsed is None or not all(c["field"] in parsed for c in checks):
        return [{"code": "UNVERIFIED", "severity": INFO}]
    return [{"code": c["id"], "severity": c["severity"]} for c in checks if _yes(parsed[c["field"]])]


def assess(ruleset: dict, faces: dict, looks: Optional[list], counts: dict) -> dict:
    """The verdict for a set of photos.

    ``faces`` is :func:`faces.inspect_photos`'s answer; ``looks`` the vision model's answers in photo order (``None`` or
    a list of a different length than the photos means no photo can be attributed an answer: all ``UNVERIFIED``);
    ``counts`` is ``{minPhotos, maxPhotos, minFacePhotos}`` from the product.
    """
    photos = faces["photos"]
    n = len(photos)
    aligned = looks if isinstance(looks, list) and len(looks) == n else [None] * n
    mismatch = set(faces["identity"]["mismatch"])
    report_photos = []
    for fact, answer in zip(photos, aligned):
        findings = look_findings(ruleset, answer)
        if fact["index"] in mismatch:
            findings.append({"code": "FACE_MISMATCH", "severity": BLOCK})
        if fact["kind"] == "GROUP":
            findings.append({"code": "GROUP_PHOTO", "severity": INFO})
        report_photos.append({"index": fact["index"], "kind": fact["kind"], "faceCount": fact["faceCount"], "findings": findings})

    face_photos = [p for p in report_photos if p["kind"] == "FACE" and not any(f["code"] == "FACE_MISMATCH" for f in p["findings"])]
    blockers: list[dict] = []
    if n < counts["minPhotos"]:
        blockers.append({"code": "TOO_FEW_PHOTOS", "photos": []})
    if n > counts["maxPhotos"]:
        blockers.append({"code": "TOO_MANY_PHOTOS", "photos": []})
    if len(face_photos) < counts["minFacePhotos"]:
        blockers.append({"code": "TOO_FEW_FACE_PHOTOS", "photos": []})
    for code in sorted({f["code"] for p in report_photos for f in p["findings"] if f["severity"] == BLOCK}):
        blockers.append({"code": code, "photos": [p["index"] for p in report_photos if any(f["code"] == code for f in p["findings"])]})

    return {
        "rulesetId": ruleset["rulesetId"],
        "rulesetVersion": ruleset["version"],
        "rulesetRevision": ruleset.get("revision", 1),
        "photos": report_photos,
        "identity": {"status": faces["identity"]["status"], "compared": faces["identity"]["compared"]},
        "counts": {"photos": n, "facePhotos": len(face_photos), "required": counts},
        "passes": not blockers,
        "blockers": blockers,
        "limits": ruleset["limits"],
    }
