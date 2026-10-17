#!/usr/bin/env python3
"""The verdict is a pure function. Run: python3 -m pytest test_rules.py -q  (or: python3 test_rules.py)"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rules  # noqa: E402

RULESET = rules.load_ruleset()
COUNTS = {"minPhotos": 4, "maxPhotos": 6, "minFacePhotos": 2}
GOOD_LOOK = json.dumps({"appears_under_18": False, "text_or_contact_overlay": False, "screenshot_or_photo_of_screen": False})


def facts(kinds, mismatch=(), status=None):
    photos = [{"index": i, "kind": k, "faceCount": {"FACE": 1, "GROUP": 3, "NO_FACE": 0}[k]} for i, k in enumerate(kinds)]
    verdict = status or ("MISMATCH" if mismatch else "CONSISTENT")
    return {"photos": photos, "identity": {"status": verdict, "mismatch": list(mismatch), "compared": sum(k == "FACE" for k in kinds)}}


def codes(report):
    return [b["code"] for b in report["blockers"]]


def test_four_photos_two_faces_pass():
    report = rules.assess(RULESET, facts(["FACE", "FACE", "NO_FACE", "NO_FACE"]), [GOOD_LOOK] * 4, COUNTS)
    assert report["passes"] is True and report["blockers"] == []
    assert report["counts"]["facePhotos"] == 2


def test_three_photos_are_too_few_and_seven_too_many():
    assert "TOO_FEW_PHOTOS" in codes(rules.assess(RULESET, facts(["FACE", "FACE", "NO_FACE"]), None, COUNTS))
    assert "TOO_MANY_PHOTOS" in codes(rules.assess(RULESET, facts(["FACE"] * 7), None, COUNTS))


def test_one_face_photo_is_not_enough():
    report = rules.assess(RULESET, facts(["FACE", "NO_FACE", "NO_FACE", "NO_FACE"]), None, COUNTS)
    assert codes(report) == ["TOO_FEW_FACE_PHOTOS"] and report["passes"] is False


def test_a_group_photo_is_not_a_face_photo_but_blocks_nothing_by_itself():
    report = rules.assess(RULESET, facts(["FACE", "FACE", "GROUP", "NO_FACE"]), None, COUNTS)
    assert report["passes"] is True
    assert report["counts"]["facePhotos"] == 2
    assert {"code": "GROUP_PHOTO", "severity": "INFO"} in report["photos"][2]["findings"]


def test_a_photo_that_may_show_someone_else_is_flagged_and_not_counted():
    report = rules.assess(RULESET, facts(["FACE", "FACE", "FACE", "NO_FACE"], mismatch=[2]), None, COUNTS)
    assert report["passes"] is False and report["counts"]["facePhotos"] == 2
    assert {"code": "FACE_MISMATCH", "severity": "BLOCK"} in report["photos"][2]["findings"]
    blocker = next(b for b in report["blockers"] if b["code"] == "FACE_MISMATCH")
    assert blocker["photos"] == [2]


def test_two_face_photos_that_differ_fail_the_face_count_and_say_which():
    report = rules.assess(RULESET, facts(["FACE", "FACE", "NO_FACE", "NO_FACE"], mismatch=[0, 1]), None, COUNTS)
    assert "FACE_MISMATCH" in codes(report) and "TOO_FEW_FACE_PHOTOS" in codes(report)


def test_the_vision_model_can_block_for_a_minor_a_contact_overlay_or_a_screenshot():
    bad = json.dumps({"appears_under_18": True, "text_or_contact_overlay": True, "screenshot_or_photo_of_screen": True})
    looks = [GOOD_LOOK, GOOD_LOOK, bad, GOOD_LOOK]
    report = rules.assess(RULESET, facts(["FACE", "FACE", "NO_FACE", "NO_FACE"]), looks, COUNTS)
    assert sorted(codes(report)) == ["MINOR_LIKELY", "SCREENSHOT", "TEXT_OR_CONTACT"]
    assert all(b["photos"] == [2] for b in report["blockers"])


def test_an_answer_in_the_wrong_shape_is_unverified_and_never_blocks():
    for answer in ["I think it is fine!", "", None, 7, "{not json", json.dumps({"appears_under_18": True})]:
        report = rules.assess(RULESET, facts(["FACE", "FACE", "NO_FACE", "NO_FACE"]), [answer, GOOD_LOOK, GOOD_LOOK, GOOD_LOOK], COUNTS)
        assert report["passes"] is True, answer
        assert report["photos"][0]["findings"] == [{"code": "UNVERIFIED", "severity": "INFO"}], answer


def test_looks_that_cannot_be_attributed_to_photos_are_all_unverified():
    report = rules.assess(RULESET, facts(["FACE", "FACE", "NO_FACE", "NO_FACE"]), [GOOD_LOOK], COUNTS)
    assert all(p["findings"] == [{"code": "UNVERIFIED", "severity": "INFO"}] for p in report["photos"])


def test_fenced_and_wrapped_answers_are_read():
    fenced = "```json\n" + GOOD_LOOK + "\n```"
    wrapped = {"analysis": "Here you go: " + GOOD_LOOK + " Hope it helps."}
    assert rules.parse_look(fenced)["appears_under_18"] is False
    assert rules.parse_look(wrapped)["text_or_contact_overlay"] is False


def test_a_report_is_codes_not_words_and_states_its_limits():
    report = rules.assess(RULESET, facts(["FACE", "FACE", "NO_FACE", "NO_FACE"]), None, COUNTS)
    text = json.dumps(report)
    for forbidden in ("score", "similarity", "cosine", "embedding", "vector"):
        assert forbidden not in text.lower(), forbidden
    assert "NO_CELEBRITY_RECOGNITION" in report["limits"]
    assert report["rulesetVersion"] == RULESET["version"]


def test_the_ruleset_in_force_is_chosen_by_date_not_by_newest():
    assert rules.load_ruleset("2026-10-17")["version"] == "2026-10-17"
    try:
        rules.load_ruleset("2001-01-01")
    except LookupError:
        return
    raise AssertionError("a date before every ruleset must be refused")


def test_thresholds_stay_on_the_side_of_not_accusing():
    r = RULESET["recognizer"]
    assert r["mismatchCosine"] < r["sameCosine"]
    assert r["mismatchCosine"] <= 0.3


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as error:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {error!r}")
    sys.exit(1 if failed else 0)
