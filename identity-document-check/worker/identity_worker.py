#!/usr/bin/env python3
"""The identity-document worker: the deterministic half of an identity-document check.

Tier-W, like the other pack workers: it links no Orazaka library and speaks only AMQP. One routing key around one model
call that the blueprint makes (so the inference is metered like any other — this worker calls no model):

``job.identity.verify``
    Takes what the vision step *read* off the document (the zone's lines, the printed fields, the signs of tampering) and
    decides what can be decided by arithmetic: the check digits, the calendar, the agreement between the printed fields,
    the zone and the barcode (:mod:`rules`, :mod:`mrz`). It never receives the image and keeps nothing.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker-common"))
import worker_loop  # noqa: E402
from worker_loop import InvalidJobPayload  # noqa: E402

import rules  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_BARCODE_CHARS = 20000


def today() -> str:
    return dt.date.today().isoformat()


def _as_of(payload: dict) -> str:
    value = payload.get("asOf")
    if value in (None, ""):
        return today()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InvalidJobPayload("'asOf' must be a day, YYYY-MM-DD")
    try:
        dt.date.fromisoformat(value)
    except ValueError as bad:
        raise InvalidJobPayload("'asOf' is not a real day") from bad
    return value


def _minimum_age(payload: dict):
    value = payload.get("minimumAge")
    if value in (None, ""):
        return None
    if isinstance(value, str) and value.strip().isdigit():  # a blueprint renders a lone number as text
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 120:
        raise InvalidJobPayload("'minimumAge' must be a whole number of years between 0 and 120")
    return value


def _verify(payload: dict) -> dict:
    try:
        reading = rules.parse_reading(payload.get("reading"))
    except rules.InvalidReading as bad:
        raise InvalidJobPayload(str(bad)) from bad
    barcode = payload.get("barcodeText") or ""
    if not isinstance(barcode, str) or len(barcode) > MAX_BARCODE_CHARS:
        raise InvalidJobPayload(f"'barcodeText' must be text of at most {MAX_BARCODE_CHARS} characters")
    as_of = _as_of(payload)
    try:
        report = rules.assess(rules.load_ruleset(), reading, as_of, minimum_age=_minimum_age(payload), barcode_text=barcode)
    except rules.InvalidReading as bad:
        raise InvalidJobPayload(str(bad)) from bad
    return {"report": report, "reportJson": json.dumps(report), "status": report["status"]}


handle = worker_loop.make_handle({"job.identity.verify": _verify})


def main() -> None:
    worker_loop.run("identity", yaml.safe_load(open(os.path.join(HERE, "worker.yaml"), encoding="utf-8")), handle)


if __name__ == "__main__":
    main()
