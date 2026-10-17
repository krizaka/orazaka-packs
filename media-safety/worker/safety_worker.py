#!/usr/bin/env python3
"""The media-safety worker: the deterministic half of a safety check. The two model steps are the blueprint's (metered like any step)."""

import json
import os
import time

import pika
import yaml

import broker
import rules

HERE = os.path.dirname(os.path.abspath(__file__))
DECLARATION = yaml.safe_load(open(os.path.join(HERE, "worker.yaml"), encoding="utf-8"))
JOBS_EXCHANGE, EVENTS_EXCHANGE, DLX_EXCHANGE = "orazaka.jobs", "orazaka.events", "orazaka.dlx"
QUEUE = f"orazaka.jobs.{DECLARATION['family']}"
DLQ = f"{QUEUE}.dlq"
SEEN: set = set()
INPUT_INVALID, EXECUTOR_FAULT = "INPUT_INVALID", "EXECUTOR_FAULT"


class InvalidJobPayload(ValueError):
    """The payload was checked and is unusable — the one cause that bills."""


def _assess(payload: dict) -> dict:
    frames = payload.get("frames")
    if isinstance(frames, str) and frames.strip().isdigit():  # a blueprint renders a lone number as text
        frames = int(frames)
    if isinstance(frames, bool) or not isinstance(frames, int) or not 0 <= frames <= 8:
        raise InvalidJobPayload("'frames' must be an integer from 0 to 8")
    expects_speech = payload.get("expectsSpeech")
    if isinstance(expects_speech, str) and expects_speech.strip().lower() in ("true", "false"):
        expects_speech = expects_speech.strip().lower() == "true"
    if not isinstance(expects_speech, bool):
        raise InvalidJobPayload("'expectsSpeech' must be true or false")
    report = rules.assess(rules.load_ruleset(), payload.get("looks"), frames, payload.get("heard"), expects_speech)
    return {"report": report, "reportJson": json.dumps(report), "verdict": report["verdict"]}


HANDLERS = {"job.safety.assess": _assess}


def _handle(routing_key: str, job: dict) -> tuple:
    handler = HANDLERS.get(routing_key)
    if handler is None:
        raise ValueError(f"no handler for routing key '{routing_key}'")
    started = time.monotonic()
    return handler(job.get("payload") or {}), {"tokens": 0, "gpuSeconds": round(time.monotonic() - started, 3)}


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
    print(f"[safety] {method.routing_key} -> job {job_id}", flush=True)  # job id and routing key only
    try:
        result, consumption = _handle(method.routing_key, job)
        _emit(channel, job_id, "done", {"jobId": job_id, "result": result, "consumption": consumption})
    except InvalidJobPayload as bad:
        _emit(channel, job_id, "error", {"jobId": job_id, "error": str(bad), "cause": INPUT_INVALID})
    except Exception as failure:  # noqa: BLE001
        print(f"[safety] job {job_id} failed: {type(failure).__name__}", flush=True)
        _emit(channel, job_id, "error", {"jobId": job_id, "error": type(failure).__name__, "cause": EXECUTOR_FAULT})
    SEEN.add(message_id)
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _broker_credentials() -> "pika.PlainCredentials":
    password = os.environ.get("RABBITMQ_PASS") or os.environ.get("RABBITMQ_PASSWORD") or os.environ.get("SPRING_RABBITMQ_PASSWORD")
    return pika.PlainCredentials(os.environ.get("RABBITMQ_USER", "guest"), password or "guest")


def main() -> None:
    params = broker.connection_parameters(_broker_credentials())
    print(f"[safety] broker {broker.describe(params)}", flush=True)
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
    print(f"[safety] consuming {QUEUE}", flush=True)
    channel.start_consuming()


if __name__ == "__main__":
    main()
