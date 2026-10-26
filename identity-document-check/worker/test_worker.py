#!/usr/bin/env python3
"""The identity worker: the payload checks and the handler, without a broker. Run: python3 test_worker.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import identity_worker as worker  # noqa: E402
from worker_loop import InvalidJobPayload  # noqa: E402

TD3 = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]
READING = {"documentType": "PASSPORT", "mrzLines": TD3, "printed": {}, "signals": [], "quality": {}, "confidence": {"mrz": 0.9}}


def _verify(**payload):
    return worker._verify(dict({"reading": json.dumps(READING), "asOf": "2011-06-01"}, **payload))


def test_the_routing_key_chooses_the_work_and_an_unknown_one_is_refused():
    result, consumption = worker.handle("job.identity.verify", {"payload": {"reading": json.dumps(READING), "asOf": "2011-06-01"}})
    assert result["report"]["status"] == "CONSISTENT" and result["status"] == "CONSISTENT"
    assert consumption["tokens"] == 0
    try:
        worker.handle("job.identity.other", {"payload": {}})
    except ValueError:
        return
    raise AssertionError("an unknown routing key must be refused")


def test_the_report_comes_back_as_an_object_and_as_json_for_the_next_step():
    result = _verify()
    assert json.loads(result["reportJson"]) == result["report"]


def test_numbers_and_flags_arrive_as_text_from_a_blueprint_and_are_read_as_what_they_stand_for():
    result = _verify(minimumAge="40")
    assert result["report"]["age"]["minimum"] == 40 and result["status"] == "REVIEW"
    assert _verify(minimumAge="")["report"]["age"]["minimum"] is None


def test_a_blank_reference_day_means_today_and_a_wrong_one_is_refused():
    assert _verify(asOf="")["report"]["asOf"] == worker.today()
    for bad in ("2026-13-01", "yesterday", 20260101):
        try:
            _verify(asOf=bad)
        except InvalidJobPayload:
            continue
        raise AssertionError(f"{bad!r} was not refused")


def test_an_unusable_payload_is_refused_as_input_never_as_a_fault():
    for payload in ({}, {"reading": "no json here"}, {"reading": "[]"}, {"reading": json.dumps(READING), "minimumAge": "abc"}, {"reading": json.dumps(READING), "minimumAge": "150"}):
        try:
            worker._verify(dict({"asOf": "2011-06-01"}, **payload))
        except InvalidJobPayload:
            continue
        raise AssertionError(f"{payload!r} was not refused")


def test_the_barcode_text_is_optional_and_bounded():
    assert _verify(barcodeText="")["report"]["barcode"]["present"] is False
    try:
        _verify(barcodeText="x" * 20001)
    except InvalidJobPayload:
        return
    raise AssertionError("an oversized barcode text must be refused")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print(f"\n{'FAILED' if failures else 'all green'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)
