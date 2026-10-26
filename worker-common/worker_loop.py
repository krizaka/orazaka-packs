"""The job loop every pack worker shares: declare the queue, consume, run the handler, publish ``done`` or ``error``.

A worker used to carry its own copy of this (queue declaration, dead-lettering, de-duplication by message id, the
``done`` / ``error`` events). New workers import it: they bring a ``handle(routing_key, job) -> (result, consumption)``
and their ``worker.yaml`` declaration, nothing else.

``handle`` raises :class:`InvalidJobPayload` when it checked the payload and found it unusable (the one cause that
bills); any other exception is an executor fault. The log lines are the job id and the routing key — never a payload.
"""
from __future__ import annotations

import json
import os
import time
from typing import Callable

import pika

from worker_broker import connection_parameters, describe

JOBS_EXCHANGE = "orazaka.jobs"
EVENTS_EXCHANGE = "orazaka.events"
DLX_EXCHANGE = "orazaka.dlx"

INPUT_INVALID = "INPUT_INVALID"
EXECUTOR_FAULT = "EXECUTOR_FAULT"


class InvalidJobPayload(ValueError):
    """The worker checked the payload and found it unusable — the one cause that bills."""


def make_handle(handlers: dict) -> Callable[[str, dict], tuple]:
    """``handle(routing_key, job)`` from a table of handlers: the work is chosen by the ROUTING KEY the broker delivered under,
    never by a capability name. The consumption is a measurement only (CPU time): no tokens were spent and none are claimed."""

    def handle(routing_key: str, job: dict) -> tuple:
        handler = handlers.get(routing_key)
        if handler is None:
            raise ValueError(f"no handler for routing key '{routing_key}'")
        started = time.monotonic()
        result = handler(job.get("payload") or {})
        return result, {"tokens": 0, "gpuSeconds": round(time.monotonic() - started, 3)}

    return handle


def emit(channel, job_id: str, suffix: str, body: dict) -> None:
    channel.basic_publish(
        exchange=EVENTS_EXCHANGE,
        routing_key=f"job.{job_id}.{suffix}",
        body=json.dumps(body).encode(),
        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
    )


def make_on_message(label: str, handle: Callable[[str, dict], tuple], seen: set) -> Callable:
    """The consumer callback. ``seen`` is the set of message ids already answered (a redelivery is acknowledged, not rerun)."""

    def on_message(channel, method, properties, body) -> None:
        try:
            job = json.loads(body)
        except json.JSONDecodeError:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        job_id = job.get("jobId")
        message_id = properties.message_id or job_id
        if message_id in seen:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return
        print(f"[{label}] {method.routing_key} -> job {job_id}", flush=True)
        try:
            result, consumption = handle(method.routing_key, job)
            emit(channel, job_id, "done", {"jobId": job_id, "result": result, "consumption": consumption})
        except InvalidJobPayload as bad:
            print(f"[{label}] job {job_id} rejected: {bad}", flush=True)
            emit(channel, job_id, "error", {"jobId": job_id, "error": str(bad), "cause": INPUT_INVALID})
        except Exception as failure:  # noqa: BLE001 — any failure must reach the saga, not the log alone
            print(f"[{label}] job {job_id} failed: {type(failure).__name__}", flush=True)
            emit(channel, job_id, "error", {"jobId": job_id, "error": type(failure).__name__, "cause": EXECUTOR_FAULT})
        seen.add(message_id)
        channel.basic_ack(delivery_tag=method.delivery_tag)

    return on_message


def credentials_from_environment() -> "pika.PlainCredentials":
    password = os.environ.get("RABBITMQ_PASS") or os.environ.get("RABBITMQ_PASSWORD") or os.environ.get("SPRING_RABBITMQ_PASSWORD")
    return pika.PlainCredentials(os.environ.get("RABBITMQ_USER", "guest"), password or "guest")


def run(label: str, declaration: dict, handle: Callable[[str, dict], tuple]) -> None:
    """Connect, declare ``orazaka.jobs.<family>`` with its dead-letter queue, and consume until stopped."""
    queue = f"orazaka.jobs.{declaration['family']}"
    dead = f"{queue}.dlq"
    params = connection_parameters(credentials_from_environment())
    print(f"[{label}] broker {describe(params)}", flush=True)
    channel = pika.BlockingConnection(params).channel()
    channel.exchange_declare(exchange=JOBS_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=EVENTS_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=DLX_EXCHANGE, exchange_type="direct", durable=True)
    channel.queue_declare(queue=queue, durable=True, arguments={"x-dead-letter-exchange": DLX_EXCHANGE, "x-dead-letter-routing-key": queue})
    for binding in declaration["bindings"]:
        channel.queue_bind(queue=queue, exchange=JOBS_EXCHANGE, routing_key=binding)
    channel.queue_declare(queue=dead, durable=True)
    channel.queue_bind(queue=dead, exchange=DLX_EXCHANGE, routing_key=queue)
    channel.basic_qos(prefetch_count=declaration.get("concurrency", 1))
    channel.basic_consume(queue=queue, on_message_callback=make_on_message(label, handle, set()))
    print(f"[{label}] consuming {queue} ({' + '.join(declaration['bindings'])})", flush=True)
    channel.start_consuming()
