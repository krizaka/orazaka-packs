#!/usr/bin/env python3
"""The safety rules fail closed. Run: python3 test_safety.py"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rules  # noqa: E402
import safety_worker as worker  # noqa: E402

R = rules.load_ruleset()
CLEAN = json.dumps({"sexual_or_nudity": False, "graphic_violence": False, "minor_in_unsafe_context": False})
DIRTY = json.dumps({"sexual_or_nudity": True, "graphic_violence": False, "minor_in_unsafe_context": False})
SPEECH_CLEAN = json.dumps({"threat_or_harassment": False, "sexual_content": False, "hate": False})
SPEECH_BAD = json.dumps({"threat_or_harassment": True, "sexual_content": False, "hate": False})


def test_clean_pictures_are_approved():
    assert rules.assess(R, [CLEAN, CLEAN], 2, None, False)["verdict"] == "APPROVED"


def test_one_bad_picture_rejects_and_names_the_code_and_the_frame():
    r = rules.assess(R, [CLEAN, DIRTY, CLEAN], 3, None, False)
    assert r["verdict"] == "REJECTED" and r["blockers"] == ["SEXUAL_CONTENT"] and r["findings"] == [{"code": "SEXUAL_CONTENT", "frame": 1}]


def test_an_answer_that_cannot_be_read_is_never_a_pass():
    for bad in ["I think it is fine", "", None, 3, "{nope", json.dumps({"sexual_or_nudity": False}), json.dumps({"sexual_or_nudity": "maybe", "graphic_violence": False, "minor_in_unsafe_context": False})]:
        r = rules.assess(R, [CLEAN, bad], 2, None, False)
        assert r["verdict"] == "UNREADABLE" and r["unreadable"] == 1, bad


def test_fewer_answers_than_pictures_leaves_the_missing_ones_unread():
    assert rules.assess(R, [CLEAN], 3, None, False)["verdict"] == "UNREADABLE"
    assert rules.assess(R, None, 2, None, False)["verdict"] == "UNREADABLE"


def test_nothing_examined_is_not_a_pass():
    assert rules.assess(R, [], 0, None, False)["verdict"] == "UNREADABLE"


def test_speech_is_judged_on_its_transcript_and_a_missing_judgement_is_unreadable():
    assert rules.assess(R, [], 0, SPEECH_CLEAN, True)["verdict"] == "APPROVED"
    assert rules.assess(R, [], 0, SPEECH_BAD, True)["blockers"] == ["THREAT_OR_HARASSMENT"]
    assert rules.assess(R, [], 0, "", True)["verdict"] == "UNREADABLE"


def test_a_rejection_wins_over_an_unreadable_one():
    assert rules.assess(R, [DIRTY, "garbage"], 2, None, False)["verdict"] == "REJECTED"


def test_fenced_and_wrapped_answers_are_read():
    assert rules.assess(R, ["```json\n" + CLEAN + "\n```", {"analysis": "Sure: " + CLEAN}], 2, None, False)["verdict"] == "APPROVED"


def test_the_worker_checks_its_payload_by_name():
    out = worker._assess({"looks": [CLEAN], "frames": 1, "expectsSpeech": "false"})
    assert out["verdict"] == "APPROVED" and json.loads(out["reportJson"]) == out["report"]
    assert worker._assess({"looks": [CLEAN, CLEAN], "frames": "2", "expectsSpeech": False})["verdict"] == "APPROVED"
    for payload in [{"frames": 99, "expectsSpeech": False}, {"frames": "one", "expectsSpeech": False}, {"frames": 1}, {"frames": 1, "expectsSpeech": "maybe"}]:
        try:
            worker._assess(payload)
        except worker.InvalidJobPayload:
            continue
        raise AssertionError(payload)


def test_the_log_and_the_protocol():
    src = open(os.path.join(worker.HERE, "safety_worker.py")).read()
    for line in re.findall(r"print\(f?\"\[safety\][^\n]*", src):
        assert not re.search(r"finding|transcript|heard|looks|report|verdict", line), line
    d = worker.DECLARATION
    assert d["bindings"] == ["job.safety.*"] and "job.safety.*" not in src and d["concurrency"] == 1
    assert not re.search(r"orazaka\.safety\.|featureKey", src.replace("`featureKey`", ""))


def test_one_picture_arrives_as_one_answer_not_a_list():
    """The studio publishes a fan-out of ONE item as the item itself (RunSagaService.buildScope): every photo message is that case."""
    one = {"analysis": CLEAN}
    assert rules.assess(R, one, 1, None, False)["verdict"] == "APPROVED"
    assert rules.assess(R, {"analysis": DIRTY}, 1, None, False)["blockers"] == ["SEXUAL_CONTENT"]
    assert rules.assess(R, {"analysis": "no idea"}, 1, None, False)["verdict"] == "UNREADABLE"
    # with several pictures a bare answer is still not a list: the missing ones stay unread
    assert rules.assess(R, one, 2, None, False)["verdict"] == "UNREADABLE"


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
