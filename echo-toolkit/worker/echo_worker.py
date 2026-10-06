#!/usr/bin/env python3
"""The Tier-W reference worker: everything a third-party worker must do, and nothing else.

It links no Orazaka library and implements no interface. It speaks AMQP, which is
the whole claim of ADR-037 §6 — *the broker is the plugin boundary*. Read this file
as the executable half of docs/WORKER_PROTOCOL.md.

Five obligations, each marked below:
  1. declare your own topology — queue, bindings, DLQ — so installing a pack needs
     no change to the platform's broker configuration;
  2. decide from the ROUTING KEY, never from a capability name;
  3. answer on ``job.{jobId}.done`` with ``output``, or ``job.{jobId}.error``;
  4. report MEASUREMENTS, never units or prices — the pricebook owns those;
  5. be idempotent by ``messageId``: at-least-once delivery is the contract.

Run: python3 echo_worker.py    (env: RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER,
RABBITMQ_PASS — see _broker_credentials for why the password has three names.)
"""

import json
import os
import time

import pika
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DECLARATION = yaml.safe_load(open(os.path.join(HERE, "worker.yaml"), encoding="utf-8"))

JOBS_EXCHANGE = "orazaka.jobs"
EVENTS_EXCHANGE = "orazaka.events"
DLX_EXCHANGE = "orazaka.dlx"
QUEUE = f"orazaka.jobs.{DECLARATION['family']}"
DLQ = f"{QUEUE}.dlq"

# (5) Idempotency. A real worker persists this; a reference one shows where it goes.
SEEN: set = set()


def _handle(job: dict) -> tuple:
    """(2) The work, chosen by the routing key the broker delivered under."""
    payload = job.get("payload") or {}
    text = str(payload.get("text") or "")
    started = time.monotonic()
    reversed_text = text[::-1]
    # (4) Measurements only. This worker says how much text it moved; whether that
    # bills in KILOTOKEN, GPU_SECOND or anything else is the pricebook's decision.
    consumption = {"tokens": max(1, len(text) // 4), "gpuSeconds": round(time.monotonic() - started, 3)}
    return {"text": reversed_text, "metrics": consumption}, consumption


# The closed vocabulary of ADR-053, mirrored from `FailureCause` on the platform side. A worker
# MUST declare one: the saga reads this category and never the message. INPUT_INVALID is the only
# one that BILLS the actor for work already done, so it is raised deliberately and never from a
# bare `except`. Anything unrecognised or absent degrades to EXECUTOR_FAULT — release, blame nobody.
GUARD_REFUSAL = "GUARD_REFUSAL"
INPUT_INVALID = "INPUT_INVALID"
EXECUTOR_FAULT = "EXECUTOR_FAULT"
PLATFORM_UNAVAILABLE = "PLATFORM_UNAVAILABLE"
TIMEOUT = "TIMEOUT"


class InvalidJobPayload(ValueError):
    """This worker checked the payload and found it unusable — the one cause that bills."""


def _emit(channel, job_id: str, routing_suffix: str, body: dict) -> None:
    """(3) The answer the saga is waiting for, on the events exchange."""
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

    print(f"[echo] {method.routing_key} -> job {job_id}", flush=True)
    try:
        result, consumption = _handle(job)
        # "result", not "output": the key the saga reads (docs/WORKER_PROTOCOL.md). Getting it
        # wrong costs you a SUCCEEDED run with an empty output and no error anywhere — which is
        # what this reference worker did on its first run, and why it says so here.
        _emit(channel, job_id, "done", {"jobId": job_id, "result": result, "consumption": consumption})
    except InvalidJobPayload as bad:
        _emit(channel, job_id, "error",
              {"jobId": job_id, "error": str(bad), "cause": INPUT_INVALID})
    except Exception as failure:  # noqa: BLE001 — any failure must reach the saga, not the log alone
        _emit(channel, job_id, "error",
              {"jobId": job_id, "error": str(failure), "cause": EXECUTOR_FAULT})
    SEEN.add(message_id)
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _broker_credentials() -> "pika.PlainCredentials":
    """The broker password.

    **The name is `RABBITMQ_PASS`.** It was three names — the CLI wrote `RABBITMQ_PASSWORD` into
    a generated compose and `SPRING_RABBITMQ_PASSWORD` into its own — and a third-party worker
    author picking the wrong one got `ACCESS_REFUSED (403)` with no diagnosis. ADR-053 §8 settled
    it on the `RABBITMQ_*` family that the services, the infra compose and this worker already
    used.

    The two old names are still read, loudly, for one version: a `.env` written before the rename
    keeps working, and its owner is told what to change rather than discovering it at a 403.
    """
    password = os.environ.get("RABBITMQ_PASS")
    if not password:
        for legacy in ("RABBITMQ_PASSWORD", "SPRING_RABBITMQ_PASSWORD"):
            password = os.environ.get(legacy)
            if password:
                print(
                    f"[warn] {legacy} is deprecated and will stop being read after 1.1.0; "
                    "rename it to RABBITMQ_PASS.",
                    flush=True,
                )
                break
    return pika.PlainCredentials(
        os.environ.get("RABBITMQ_USER", "guest"), password or "guest"
    )


def main() -> None:
    host = os.environ.get("RABBITMQ_HOST", "localhost")
    port = int(os.environ.get("RABBITMQ_PORT", "5672"))
    credentials = _broker_credentials()
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=host, port=port, credentials=credentials)
    )
    channel = connection.channel()

    # (1) Declare your own topology. This is what makes a Tier-W pack installable
    # without touching the platform: nothing in the engine knows this queue exists.
    channel.exchange_declare(exchange=JOBS_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=EVENTS_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=DLX_EXCHANGE, exchange_type="direct", durable=True)
    channel.queue_declare(
        queue=QUEUE,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX_EXCHANGE, "x-dead-letter-routing-key": QUEUE},
    )
    for binding in DECLARATION["bindings"]:
        channel.queue_bind(queue=QUEUE, exchange=JOBS_EXCHANGE, routing_key=binding)
    channel.queue_declare(queue=DLQ, durable=True)
    channel.queue_bind(queue=DLQ, exchange=DLX_EXCHANGE, routing_key=QUEUE)

    channel.basic_qos(prefetch_count=DECLARATION.get("concurrency", 1))
    channel.basic_consume(queue=QUEUE, on_message_callback=_on_message)
    print(f"[echo] consuming {QUEUE} ({' + '.join(DECLARATION['bindings'])})", flush=True)
    channel.start_consuming()


if __name__ == "__main__":
    main()
