#!/usr/bin/env python3
"""The rules and the worker, without a model. Run: python3 test_authenticity.py"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import authenticity_worker as worker  # noqa: E402
import language  # noqa: E402
import rules  # noqa: E402

RULESET = rules.load_ruleset()
FR = "Salut ! J’ai vu que tu aimes la randonnée aussi, tu connais le sentier derrière le mont Royal et les petits restos du coin ?"
EN = "Hey! I saw that you love hiking too, do you know the trail behind the mountain and the little places to eat around there?"


class Fixed:
    def __init__(self, score):
        self.score = lambda text: score


def test_language_is_picked_from_the_words_or_not_at_all():
    assert language.detect(FR) == "fr" and language.detect(EN) == "en"
    assert language.detect("ok ok ok") == "other" and language.detect("") == "other" and language.detect("12345 678") == "other"
    assert language.detect("Das ist ein Satz über Wandern und Kochen mit Freunden am Wochenende") == "other"


def test_levels_follow_the_thresholds_of_the_language():
    t = RULESET["languages"]["fr"]
    assert rules.level(t["high"], t) == "HIGH" and rules.level(t["mid"], t) == "MID" and rules.level(t["mid"] - 0.01, t) == "LOW"


def test_a_short_text_or_an_unknown_language_is_unavailable_never_guessed():
    assert rules.report(RULESET, "fr", 5, 0.99)["detector"] == "UNAVAILABLE"
    assert rules.report(RULESET, "other", 40, 0.99)["detector"] == "UNAVAILABLE"
    assert rules.report(RULESET, "en", 40, None)["detector"] == "UNAVAILABLE"


def test_the_report_is_closed_and_carries_no_number():
    r = rules.report(RULESET, "fr", 40, 0.999)
    assert set(r) == {"detector", "language", "rulesetVersion", "limits"}
    assert not re.search(r"\d\.\d", json.dumps(r).replace(RULESET["version"], ""))
    assert "A_SIGNAL_NEVER_A_VERDICT" in r["limits"] and "UNRELIABLE_ON_SHORT_TEXTS" in r["limits"]


def test_the_worker_answers_a_level_and_hides_the_score():
    out = worker._read({"text": FR}, classifier=Fixed(0.9991))
    assert out["detector"] == "HIGH" and "0.999" not in json.dumps(out)
    assert worker._read({"text": EN}, classifier=Fixed(0.01))["detector"] == "LOW"


def test_the_classifier_is_not_even_run_on_what_it_may_not_judge():
    class Boom:
        def score(self, text):
            raise AssertionError("must not run")

    assert worker._read({"text": "Salut, ça va ?"}, classifier=Boom())["detector"] == "UNAVAILABLE"
    assert worker._read({"text": "ja nein vielleicht " * 10}, classifier=Boom())["detector"] == "UNAVAILABLE"


def test_a_payload_that_is_not_a_text_is_refused_by_name():
    for payload in [{}, {"text": ""}, {"text": "   "}, {"text": 7}, {"text": "x" * 6000}]:
        try:
            worker._read(payload, classifier=Fixed(0.5))
        except worker.InvalidJobPayload:
            continue
        raise AssertionError(f"{str(payload)[:30]} must be refused")


def test_the_log_never_carries_the_text_or_the_level():
    for line in re.findall(r"print\(f?\"\[authenticity\][^\n]*", open(os.path.join(worker.HERE, "authenticity_worker.py")).read()):
        assert not re.search(r"text|detector|level|score|result|payload", line), line


def test_protocol_conformance():
    d = worker.DECLARATION
    src = open(os.path.join(worker.HERE, "authenticity_worker.py")).read()
    assert d["bindings"] == ["job.authenticity.*"] and "job.authenticity.*" not in src
    assert d["concurrency"] == 1 and set(worker.HANDLERS) == {"job.authenticity.read"}
    assert not re.search(r"orazaka\.message\.|featureKey", src.replace("`featureKey`", ""))
    assert src.count('"cause": INPUT_INVALID') == 1


def test_the_worker_writes_nothing_for_anyone():
    src = open(os.path.join(worker.HERE, "authenticity_worker.py")).read() + open(os.path.join(worker.HERE, "classifier.py")).read()
    assert not re.search(r"\.generate\(|AutoModelForCausalLM|AutoModelForSeq2SeqLM|chat\.completions", src)


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
