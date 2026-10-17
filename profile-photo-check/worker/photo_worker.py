#!/usr/bin/env python3
"""The profile-photo worker: the deterministic half of a profile-photo check.

Tier-W, like ``document-validation``: it links no Orazaka library and speaks only AMQP. Two routing keys around one
model call that the blueprint makes (so the inference is metered like any other — this worker calls no model):

``job.photo.inspect``
    Finds the faces in each photo (YuNet), says which photos are OF someone, and whether the people in them could be
    different (SFace). Returns counts and codes. The face vectors live for this one job, in memory, and are dropped.

``job.photo.assess``
    Folds the vision model's answers (text overlay, screenshot, a minor) and the caller's counts into one verdict made
    of codes (:mod:`rules`). It never words anything: the product that asked words it.
"""

import json
import os
import time

import pika
import yaml

import broker
import faces
import rules

HERE = os.path.dirname(os.path.abspath(__file__))
DECLARATION = yaml.safe_load(open(os.path.join(HERE, "worker.yaml"), encoding="utf-8"))

JOBS_EXCHANGE = "orazaka.jobs"
EVENTS_EXCHANGE = "orazaka.events"
DLX_EXCHANGE = "orazaka.dlx"
QUEUE = f"orazaka.jobs.{DECLARATION['family']}"
DLQ = f"{QUEUE}.dlq"

SEEN: set = set()
#: More than a profile can hold; the caller's own maximum is checked by the rules, this only bounds the work.
MAX_PHOTOS_PER_JOB = 12

GUARD_REFUSAL = "GUARD_REFUSAL"
INPUT_INVALID = "INPUT_INVALID"
EXECUTOR_FAULT = "EXECUTOR_FAULT"
PLATFORM_UNAVAILABLE = "PLATFORM_UNAVAILABLE"
TIMEOUT = "TIMEOUT"


class InvalidJobPayload(ValueError):
    """This worker checked the payload and found it unusable — the one cause that bills."""


_ENGINE = None


def _engine(ruleset: dict) -> "faces.FaceEngine":
    """One engine per process (loading the models costs more than a job)."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = faces.OpenCvEngine(ruleset)
    return _ENGINE


def _count(payload: dict, key: str, low: int, high: int) -> int:
    value = payload.get(key)
    if isinstance(value, str) and value.strip().isdigit():  # a blueprint renders a lone number as text
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidJobPayload(f"'{key}' must be an integer between {low} and {high}")
    return value


def _inspect(payload: dict, engine=None) -> dict:
    photos = payload.get("photosBase64")
    if not isinstance(photos, list) or not photos:
        raise InvalidJobPayload("'photosBase64' must be a non-empty list")
    if len(photos) > MAX_PHOTOS_PER_JOB:
        raise InvalidJobPayload(f"at most {MAX_PHOTOS_PER_JOB} photos per check")
    # A blueprint renders a lone boolean placeholder as text: "true" / "false" are read as the booleans they stand for.
    compare = payload.get("compareFaces", True)
    if isinstance(compare, str) and compare.strip().lower() in ("true", "false"):
        compare = compare.strip().lower() == "true"
    if not isinstance(compare, bool):
        raise InvalidJobPayload("'compareFaces' must be true or false")
    ruleset = rules.load_ruleset()
    try:
        facts = faces.inspect_photos(photos, engine or _engine(ruleset), ruleset, compare)
    except faces.UnreadableImage as bad:
        raise InvalidJobPayload(str(bad)) from bad
    # `factsJson` exists because a blueprint addresses a step's FIELDS, not its whole output as data (ADR-052 §6).
    return dict(facts, factsJson=json.dumps(facts))


def _assess(payload: dict) -> dict:
    raw = payload.get("facts")
    try:
        facts = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as bad:
        raise InvalidJobPayload(f"'facts' is not JSON ({bad}); received: {str(raw)[:120]!r}") from bad
    if not isinstance(facts, dict) or not isinstance(facts.get("photos"), list) or not isinstance(facts.get("identity"), dict):
        raise InvalidJobPayload("'facts' is not the output of the inspection step")
    counts = {
        "minPhotos": _count(payload, "minPhotos", 1, 12),
        "maxPhotos": _count(payload, "maxPhotos", 1, 12),
        "minFacePhotos": _count(payload, "minFacePhotos", 0, 12),
    }
    report = rules.assess(rules.load_ruleset(), facts, payload.get("looks"), counts)
    return {"report": report, "reportJson": json.dumps(report), "passes": report["passes"]}


HANDLERS = {
    "job.photo.inspect": _inspect,
    "job.photo.assess": _assess,
}


def _handle(routing_key: str, job: dict) -> tuple:
    """The work, chosen by the ROUTING KEY the broker delivered under — never by a capability name."""
    handler = HANDLERS.get(routing_key)
    if handler is None:
        raise ValueError(f"no handler for routing key '{routing_key}'")
    started = time.monotonic()
    result = handler(job.get("payload") or {})
    # Measurements only: this is CPU work, no tokens were spent and none are claimed.
    return result, {"tokens": 0, "gpuSeconds": round(time.monotonic() - started, 3)}


def _emit(channel, job_id: str, routing_suffix: str, body: dict) -> None:
    channel.basic_publish(
        exchange=EVENTS_EXCHANGE,
        routing_key=f"job.{job_id}.{routing_suffix}",
        body=json.dumps(body).encode(),
        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
    )


def _on_message(channel, method, properties, body) -> None:
    try:
        job = json.loads(body)
    except json.JSONDecodeError:
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return
    job_id = job.get("jobId")
    message_id = properties.message_id or job_id
    if message_id in SEEN:
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return
    # The log line is the job id and the routing key: never a photo, a vector or a count of faces.
    print(f"[photo] {method.routing_key} -> job {job_id}", flush=True)
    try:
        result, consumption = _handle(method.routing_key, job)
        _emit(channel, job_id, "done", {"jobId": job_id, "result": result, "consumption": consumption})
    except InvalidJobPayload as bad:
        print(f"[photo] job {job_id} rejected: {bad}", flush=True)
        _emit(channel, job_id, "error", {"jobId": job_id, "error": str(bad), "cause": INPUT_INVALID})
    except Exception as failure:  # noqa: BLE001 — any failure must reach the saga, not the log alone
        print(f"[photo] job {job_id} failed: {type(failure).__name__}", flush=True)
        _emit(channel, job_id, "error", {"jobId": job_id, "error": type(failure).__name__, "cause": EXECUTOR_FAULT})
    SEEN.add(message_id)
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _broker_credentials() -> "pika.PlainCredentials":
    password = os.environ.get("RABBITMQ_PASS") or os.environ.get("RABBITMQ_PASSWORD") or os.environ.get("SPRING_RABBITMQ_PASSWORD")
    return pika.PlainCredentials(os.environ.get("RABBITMQ_USER", "guest"), password or "guest")


def main() -> None:
    params = broker.connection_parameters(_broker_credentials())
    print(f"[photo] broker {broker.describe(params)}", flush=True)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.exchange_declare(exchange=JOBS_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=EVENTS_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=DLX_EXCHANGE, exchange_type="direct", durable=True)
    channel.queue_declare(queue=QUEUE, durable=True, arguments={"x-dead-letter-exchange": DLX_EXCHANGE, "x-dead-letter-routing-key": QUEUE})
    for binding in DECLARATION["bindings"]:
        channel.queue_bind(queue=QUEUE, exchange=JOBS_EXCHANGE, routing_key=binding)
    channel.queue_declare(queue=DLQ, durable=True)
    channel.queue_bind(queue=DLQ, exchange=DLX_EXCHANGE, routing_key=QUEUE)
    channel.basic_qos(prefetch_count=DECLARATION.get("concurrency", 1))
    channel.basic_consume(queue=QUEUE, on_message_callback=_on_message)
    print(f"[photo] consuming {QUEUE} ({' + '.join(DECLARATION['bindings'])})", flush=True)
    channel.start_consuming()


if __name__ == "__main__":
    main()
