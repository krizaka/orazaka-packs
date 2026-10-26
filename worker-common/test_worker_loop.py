#!/usr/bin/env python3
"""The shared job loop (worker_loop.py). Run: python3 test_worker_loop.py — a fake channel, no broker."""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker_loop as loop  # noqa: E402


class FakeChannel:
    def __init__(self):
        self.published, self.acked, self.nacked = [], [], []

    def basic_publish(self, exchange, routing_key, body, properties):
        self.published.append((exchange, routing_key, json.loads(body)))

    def basic_ack(self, delivery_tag):
        self.acked.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacked.append((delivery_tag, requeue))


def _deliver(handle, body, seen=None, message_id=None):
    channel = FakeChannel()
    on_message = loop.make_on_message("test", handle, set() if seen is None else seen)
    on_message(channel, SimpleNamespace(delivery_tag=7, routing_key="job.test.do"), SimpleNamespace(message_id=message_id), body)
    return channel


def test_the_routing_key_chooses_the_handler_and_an_unknown_key_is_refused():
    handle = loop.make_handle({"job.t.do": lambda payload: {"echo": payload}})
    result, consumption = handle("job.t.do", {"payload": {"a": 1}})
    assert result == {"echo": {"a": 1}} and consumption["tokens"] == 0 and consumption["gpuSeconds"] >= 0
    try:
        handle("job.t.other", {})
    except ValueError:
        return
    raise AssertionError("an unknown routing key must be refused")


def test_a_handled_job_publishes_done_with_its_consumption_and_is_acknowledged():
    channel = _deliver(lambda key, job: ({"ok": True}, {"tokens": 0}), json.dumps({"jobId": "j1", "payload": {}}).encode())
    assert channel.published == [("orazaka.events", "job.j1.done", {"jobId": "j1", "result": {"ok": True}, "consumption": {"tokens": 0}})]
    assert channel.acked == [7] and channel.nacked == []


def test_an_unusable_payload_is_the_billable_cause_and_the_message_is_still_acknowledged():
    def refuse(key, job):
        raise loop.InvalidJobPayload("'reading' is not JSON")

    channel = _deliver(refuse, json.dumps({"jobId": "j2"}).encode())
    assert channel.published[0][2] == {"jobId": "j2", "error": "'reading' is not JSON", "cause": "INPUT_INVALID"}
    assert channel.acked == [7]


def test_any_other_failure_reaches_the_saga_without_its_message():
    def crash(key, job):
        raise RuntimeError("secret document text")

    channel = _deliver(crash, json.dumps({"jobId": "j3"}).encode())
    body = channel.published[0][2]
    assert body["cause"] == "EXECUTOR_FAULT" and body["error"] == "RuntimeError" and "secret" not in json.dumps(body)


def test_a_redelivered_message_is_acknowledged_and_not_run_twice():
    calls = []
    seen = set()
    handle = lambda key, job: (calls.append(1) or {}, {})  # noqa: E731
    body = json.dumps({"jobId": "j4"}).encode()
    _deliver(handle, body, seen)
    channel = _deliver(handle, body, seen)
    assert len(calls) == 1 and channel.published == [] and channel.acked == [7]


def test_a_message_that_is_not_json_is_dead_lettered_not_requeued():
    channel = _deliver(lambda key, job: ({}, {}), b"{nope")
    assert channel.nacked == [(7, False)] and channel.published == []


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
