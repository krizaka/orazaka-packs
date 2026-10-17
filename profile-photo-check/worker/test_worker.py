#!/usr/bin/env python3
"""The worker's handlers and its conformance to the worker protocol (WORKER_PROTOCOL.md §8).

Run: python3 -m pytest test_worker.py -q  (or: python3 test_worker.py)
"""

import base64
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import faces  # noqa: E402
import photo_worker as worker  # noqa: E402
import rules  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = open(os.path.join(HERE, "photo_worker.py"), encoding="utf-8").read()


class Engine:
    def decode(self, data):
        return data.decode()

    def detect(self, image):
        return [faces.Face(score=0.95, height_ratio=0.5, area=0.25, handle=None)] if image.startswith("face") else []

    def embed(self, image, f):
        return [1.0, 0.0] if image == "face-a" else [0.0, 1.0]


def photos(*names):
    return [base64.b64encode(n.encode()).decode() for n in names]


def test_inspect_answers_counts_and_a_json_copy_for_the_next_step():
    out = worker._inspect({"photosBase64": photos("face-a", "face-a", "none", "none")}, engine=Engine())
    assert [p["kind"] for p in out["photos"]] == ["FACE", "FACE", "NO_FACE", "NO_FACE"]
    assert json.loads(out["factsJson"]) == {"photos": out["photos"], "identity": out["identity"]}


def test_compare_faces_false_or_the_text_false_means_no_comparison():
    for flag in (False, "false", "False"):
        out = worker._inspect({"photosBase64": photos("face-a", "face-b"), "compareFaces": flag}, engine=Engine())
        assert out["identity"]["status"] == "NOT_COMPARED", flag
    assert worker._inspect({"photosBase64": photos("face-a", "face-b")}, engine=Engine())["identity"]["status"] == "MISMATCH"
    assert worker._inspect({"photosBase64": photos("face-a", "face-b"), "compareFaces": "true"}, engine=Engine())["identity"]["status"] == "MISMATCH"
    try:
        worker._inspect({"photosBase64": photos("face-a"), "compareFaces": "maybe"}, engine=Engine())
    except worker.InvalidJobPayload:
        return
    raise AssertionError("a flag that is not a boolean must be refused")


def test_inspect_refuses_an_unusable_payload_by_name():
    for payload in [{}, {"photosBase64": []}, {"photosBase64": "x"}, {"photosBase64": ["!!"]}, {"photosBase64": ["QQ=="] * 13}]:
        try:
            worker._inspect(payload, engine=Engine())
        except worker.InvalidJobPayload:
            continue
        raise AssertionError(f"{str(payload)[:40]} must be refused")


def test_assess_makes_the_verdict_from_the_facts_and_the_counts():
    facts = worker._inspect({"photosBase64": photos("face-a", "face-a", "none", "none")}, engine=Engine())["factsJson"]
    out = worker._assess({"facts": facts, "looks": [], "minPhotos": 4, "maxPhotos": 6, "minFacePhotos": 2})
    assert out["passes"] is True
    assert json.loads(out["reportJson"]) == out["report"]
    out = worker._assess({"facts": facts, "looks": [], "minPhotos": 5, "maxPhotos": 6, "minFacePhotos": 2})
    assert out["passes"] is False and out["report"]["blockers"][0]["code"] == "TOO_FEW_PHOTOS"


def test_assess_refuses_facts_that_are_not_the_inspection_output():
    for facts in ["{nope", "{}", json.dumps({"photos": 1}), None]:
        try:
            worker._assess({"facts": facts, "minPhotos": 4, "maxPhotos": 6, "minFacePhotos": 2})
        except worker.InvalidJobPayload:
            continue
        raise AssertionError(f"{facts!r} must be refused")


def test_assess_refuses_counts_out_of_range():
    facts = json.dumps({"photos": [], "identity": {"status": "NOT_COMPARABLE", "mismatch": [], "compared": 0}})
    for counts in [{"minPhotos": 0, "maxPhotos": 6, "minFacePhotos": 2}, {"minPhotos": "4", "maxPhotos": 6, "minFacePhotos": 2}, {"minPhotos": 4, "maxPhotos": 99, "minFacePhotos": 2}, {"minPhotos": True, "maxPhotos": 6, "minFacePhotos": 2}]:
        try:
            worker._assess(dict(counts, facts=facts))
        except worker.InvalidJobPayload:
            continue
        raise AssertionError(f"{counts} must be refused")


def test_handlers_are_chosen_by_routing_key_and_report_measurements_only():
    worker._ENGINE = Engine()
    try:
        result, consumption = worker._handle("job.photo.inspect", {"payload": {"photosBase64": photos("none")}})
    finally:
        worker._ENGINE = None
    assert result["photos"][0]["kind"] == "NO_FACE"
    assert consumption["tokens"] == 0 and set(consumption) == {"tokens", "gpuSeconds"}
    try:
        worker._handle("job.photo.unknown", {})
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown routing key must be refused")


def test_the_log_never_carries_a_photo_a_vector_or_a_face_count():
    prints = re.findall(r"print\(f?\"\[photo\][^\n]*", SOURCE)
    assert prints
    for line in prints:
        assert not re.search(r"photos|vector|embed|faceCount|facts|result", line), line


def test_protocol_conformance():
    declaration = worker.DECLARATION
    assert declaration["bindings"] == ["job.photo.*"]  # bindings come from worker.yaml, not from source literals
    assert "job.photo.*" not in SOURCE
    assert declaration.get("concurrency") == 1  # prefetch 1 for CPU/GPU-bound work
    assert not re.search(r"orazaka\.photo\.|featureKey", SOURCE.replace("`featureKey`", ""))  # never branches on a capability name
    assert set(worker.HANDLERS) == {"job.photo.inspect", "job.photo.assess"}
    assert {worker.GUARD_REFUSAL, worker.INPUT_INVALID, worker.EXECUTOR_FAULT, worker.PLATFORM_UNAVAILABLE, worker.TIMEOUT} == {"GUARD_REFUSAL", "INPUT_INVALID", "EXECUTOR_FAULT", "PLATFORM_UNAVAILABLE", "TIMEOUT"}
    assert "INPUT_INVALID" in SOURCE and SOURCE.count("cause\": INPUT_INVALID") == 1  # only from the checked-payload branch


def test_the_embedding_vectors_are_not_in_any_output_key():
    out = worker._inspect({"photosBase64": photos("face-a", "face-b")}, engine=Engine())
    assert "[1.0" not in out["factsJson"] and "0.0, 1.0" not in out["factsJson"]


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
