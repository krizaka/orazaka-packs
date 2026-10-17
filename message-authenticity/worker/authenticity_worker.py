#!/usr/bin/env python3
"""The message-authenticity worker: reads the TEXT of one message and answers a coarse level — never a score, never a verdict.

Tier-W like ``profile-photo-check``: speaks only AMQP, calls no model service (a small classifier runs in this process), one routing
key. It never writes a message for anyone — it judges a text it is handed, and forgets it: nothing is logged but the job id.
"""

import json
import os
import time

import pika
import yaml

import broker
import language
import rules

HERE = os.path.dirname(os.path.abspath(__file__))
DECLARATION = yaml.safe_load(open(os.path.join(HERE, "worker.yaml"), encoding="utf-8"))

JOBS_EXCHANGE = "orazaka.jobs"
EVENTS_EXCHANGE = "orazaka.events"
DLX_EXCHANGE = "orazaka.dlx"
QUEUE = f"orazaka.jobs.{DECLARATION['family']}"
DLQ = f"{QUEUE}.dlq"
SEEN: set = set()
MAX_CHARS = 5000

INPUT_INVALID = "INPUT_INVALID"
EXECUTOR_FAULT = "EXECUTOR_FAULT"


class InvalidJobPayload(ValueError):
    """The payload was checked and is unusable — the one cause that bills."""


_CLASSIFIER = None


def _classifier(ruleset: dict):
    global _CLASSIFIER
    if _CLASSIFIER is None:
        import classifier

        _CLASSIFIER = classifier.TransformersClassifier(ruleset["classifier"])
    return _CLASSIFIER


def _read(payload: dict, classifier=None) -> dict:
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise InvalidJobPayload("'text' must be a non-empty string")
    if len(text) > MAX_CHARS:
        raise InvalidJobPayload(f"'text' is longer than {MAX_CHARS} characters")
    ruleset = rules.load_ruleset()
    lang = language.detect(text)
    words = len(text.split())
    score = None
    if lang in ruleset["languages"] and words >= ruleset["minWords"]:
        score = (classifier or _classifier(ruleset)).score(text)  # the score ends here: only its level is reported
    out = rules.report(ruleset, lang, words, score)
    return {"report": out, "reportJson": json.dumps(out), "detector": out["detector"]}


HANDLERS = {"job.authenticity.read": _read}


def _handle(routing_key: str, job: dict) -> tuple:
    handler = HANDLERS.get(routing_key)
    if handler is None:
        raise ValueError(f"no handler for routing key '{routing_key}'")
    started = time.monotonic()
    result = handler(job.get("payload") or {})
    return result, {"tokens": 0, "gpuSeconds": round(time.monotonic() - started, 3)}


def _emit(channel, job_id: str, suffix: str, body: dict) -> None:
    channel.basic_publish(exchange=EVENTS_EXCHANGE, routing_key=f"job.{job_id}.{suffix}", body=json.dumps(body).encode(), properties=pika.BasicProperties(content_type="application/json", delivery_mode=2))


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
    # The log is the job id and the routing key: never the text, never the level.
    print(f"[authenticity] {method.routing_key} -> job {job_id}", flush=True)
    try:
        result, consumption = _handle(method.routing_key, job)
        _emit(channel, job_id, "done", {"jobId": job_id, "result": result, "consumption": consumption})
    except InvalidJobPayload as bad:
        _emit(channel, job_id, "error", {"jobId": job_id, "error": str(bad), "cause": INPUT_INVALID})
    except Exception as failure:  # noqa: BLE001 — any failure must reach the saga
        print(f"[authenticity] job {job_id} failed: {type(failure).__name__}", flush=True)
        _emit(channel, job_id, "error", {"jobId": job_id, "error": type(failure).__name__, "cause": EXECUTOR_FAULT})
    SEEN.add(message_id)
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _broker_credentials() -> "pika.PlainCredentials":
    password = os.environ.get("RABBITMQ_PASS") or os.environ.get("RABBITMQ_PASSWORD") or os.environ.get("SPRING_RABBITMQ_PASSWORD")
    return pika.PlainCredentials(os.environ.get("RABBITMQ_USER", "guest"), password or "guest")


def main() -> None:
    params = broker.connection_parameters(_broker_credentials())
    print(f"[authenticity] broker {broker.describe(params)}", flush=True)
    channel = pika.BlockingConnection(params).channel()
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
    print(f"[authenticity] consuming {QUEUE}", flush=True)
    channel.start_consuming()


if __name__ == "__main__":
    main()
