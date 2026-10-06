#!/usr/bin/env python3
"""The document-validation worker: the deterministic half of a compliance report.

Tier-W, like ``echo-toolkit``: it links no Orazaka library, implements no Java interface, and
speaks only AMQP. What it adds over the reference worker is the shape of a real pack — two handlers
around one model call, with the rules in :mod:`rules` where a test can reach them.

Two routing keys, and the split between them is the design:

``job.validation.screen``
    Resolves the ruleset in force for (jurisdiction, asOf), evaluates every DETERMINISTIC rule in
    code, and returns the findings plus the *questions* the JUDGMENT rules still need answered.
    No model is called here. A rule an auditor can read as a regex never costs an inference.

``job.validation.assemble``
    Takes the model's answer to those questions and folds it in, refusing anything that is not a
    verdict from the enum. Returns the report.

The model call sits BETWEEN them, as an ordinary chat step in the blueprint, so what it costs is
metered by the platform like any other inference. A worker that called a model itself would bill
nothing and nobody would notice — which is [BILL-001] in the one place it would be easiest to
reintroduce.
"""

import json
import os
import time

import pika
import yaml

import authenticity
import rules

HERE = os.path.dirname(os.path.abspath(__file__))
DECLARATION = yaml.safe_load(open(os.path.join(HERE, "worker.yaml"), encoding="utf-8"))

JOBS_EXCHANGE = "orazaka.jobs"
EVENTS_EXCHANGE = "orazaka.events"
DLX_EXCHANGE = "orazaka.dlx"
QUEUE = f"orazaka.jobs.{DECLARATION['family']}"
DLQ = f"{QUEUE}.dlq"

SEEN: set = set()

JUDGMENT_INSTRUCTIONS = (
    "Tu évalues des règles de conformité sur le document ci-dessous. Réponds UNIQUEMENT par un "
    'tableau JSON, un objet par règle, de la forme {"ruleId": "...", "verdict": "PASS|FAIL|'
    'INSUFFICIENT_EVIDENCE", "quote": "la phrase exacte du document qui justifie ton verdict"}. '
    "N'ajoute aucune phrase autour. Si le document ne permet pas de trancher une règle, réponds "
    "INSUFFICIENT_EVIDENCE pour cette règle — ne devine pas."
)


def _screen(payload: dict) -> tuple:
    """Deterministic pass. Returns the report so far and the prompt the model must be given."""
    text = str(payload.get("document") or "")
    jurisdiction = str(payload.get("jurisdiction") or "").strip()
    as_of = str(payload.get("asOf") or "").strip() or time.strftime("%Y-%m-%d")

    known = rules.jurisdictions()
    if jurisdiction not in known:
        # A jurisdiction this pack does not carry is refused by name. Falling back to another
        # country's law would produce a confident report against rules that do not apply.
        raise InvalidJobPayload(
            f"aucun corpus de règles pour la juridiction '{jurisdiction}'; "
            f"disponibles: {', '.join(sorted(known))}"
        )
    ruleset = rules.resolve(known[jurisdiction], as_of)
    findings, judgments = rules.screen(ruleset, text)

    questions = "\n".join(f"- {j['ruleId']}: {j['question']}" for j in judgments)
    prompt = (
        f"{JUDGMENT_INSTRUCTIONS}\n\nRègles à évaluer:\n{questions}\n\n"
        f"Document:\n---\n{text}\n---"
    )
    screened = {
        "rulesetId": ruleset["rulesetId"],
        "rulesetVersion": ruleset["version"],
        "rulesetRevision": ruleset.get("revision", 1),
        "jurisdiction": ruleset["jurisdiction"],
        "asOf": as_of,
        "source": ruleset["source"],
        "deterministicFindings": findings,
    }
    # `screenedJson` exists because a blueprint can address a step's FIELDS but not its whole
    # output as data: `{{steps.screened}}` interpolates the value's toString, which is a Java map
    # rendering no JSON parser accepts (ADR-052 §6). Carrying the structure across the model call
    # as a string is the pack's job, not the engine's — and it costs one field.
    return dict(
        screened,
        screenedJson=json.dumps(screened, ensure_ascii=False),
        judgmentPrompt=prompt,
        judgmentCount=len(judgments),
    )


def _assemble(payload: dict) -> dict:
    """Fold the model's answer into the deterministic report and emit the whole thing."""
    screened = payload.get("screened")
    if isinstance(screened, str):
        try:
            screened = json.loads(screened)
        except json.JSONDecodeError as bad:
            # Say what arrived. A parse error whose message is only "line 1 column 1" tells the
            # pack author nothing about which side of the seam failed.
            raise InvalidJobPayload(
                f"le champ 'screened' n'est pas du JSON ({bad}); reçu: {screened[:200]!r}"
            ) from bad
    screened = screened or {}
    ruleset = rules.resolve(screened["rulesetId"], screened["asOf"])
    findings = rules.merge_judgments(
        ruleset,
        screened.get("deterministicFindings") or [],
        str(payload.get("judgment") or ""),
    )
    findings.sort(key=lambda f: f["ruleId"])
    report = {
        "rulesetId": screened["rulesetId"],
        "rulesetVersion": screened["rulesetVersion"],
        "rulesetRevision": screened.get("rulesetRevision", 1),
        "jurisdiction": screened["jurisdiction"],
        "asOf": screened["asOf"],
        "source": screened["source"],
        "summary": rules.summarise(findings),
        "findings": findings,
    }
    # A JSON string, not a rendered paragraph. The user forwards this to their counterparty; what
    # is forwarded must be diffable against the next run, not re-read for meaning.
    return {"report": report, "reportJson": json.dumps(report, ensure_ascii=False, indent=2)}


def _signals(payload: dict) -> dict:
    """Authenticity SIGNALS over a PDF. No model, and no verdict (ADR-056).

    Deliberately the whole of this capability: a deterministic pass and the sentences the pack
    author wrote per signal type. There is no judgement step, and adding one would be the worst
    available use of a model — asked whether a document was tampered with it produces reasons that
    sound right for signals it never saw, and the error it makes most readily is the one that
    accuses an honest person.
    """
    encoded = str(payload.get("documentBase64") or "")
    if not encoded:
        raise InvalidJobPayload("aucun document fourni : documentBase64 est vide")
    try:
        report = authenticity.analyse_base64(encoded, str(payload.get("expectedIssuer") or ""))
    except authenticity.UnreadablePdf as unreadable:
        raise InvalidJobPayload(str(unreadable)) from unreadable
    return {
        "report": report,
        "reportText": authenticity.render(report),
        "signalCount": len(report["signals"]),
        "actionableCount": sum(
            1 for s in report["signals"] if s["level"] != authenticity.OBSERVED
        ),
    }


HANDLERS = {
    "job.validation.screen": _screen,
    "job.validation.assemble": _assemble,
    # The same worker process, one more routing key. No new worker: this pack already ships one,
    # and the authenticity Studio is drained by it (ADR-056 §2).
    "job.validation.signals": _signals,
}


def _handle(routing_key: str, job: dict) -> tuple:
    """(2) The work, chosen by the ROUTING KEY the broker delivered under — never by a name."""
    handler = HANDLERS.get(routing_key)
    if handler is None:
        raise ValueError(f"no handler for routing key '{routing_key}'")
    started = time.monotonic()
    payload = job.get("payload") or {}
    result = handler(payload)
    # (4) Measurements only. Deterministic work spends CPU, not tokens; reporting a token count it
    # did not spend would put a number in the ledger that nothing measured.
    consumption = {"tokens": 0, "gpuSeconds": round(time.monotonic() - started, 3)}
    return result, consumption


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

    print(f"[validation] {method.routing_key} -> job {job_id}", flush=True)
    try:
        result, consumption = _handle(method.routing_key, job)
        _emit(channel, job_id, "done", {"jobId": job_id, "result": result, "consumption": consumption})
    except InvalidJobPayload as bad:
        # A jurisdiction this pack does not carry, or a date no ruleset covers: the pack checked
        # and says so. This is the one category that bills for the steps that already ran.
        print(f"[validation] job {job_id} rejected: {bad}", flush=True)
        _emit(channel, job_id, "error",
              {"jobId": job_id, "error": str(bad), "cause": INPUT_INVALID})
    except Exception as failure:  # noqa: BLE001 — any failure must reach the saga, not the log alone
        print(f"[validation] job {job_id} failed: {failure}", flush=True)
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

    # (1) Declare your own topology: installing this pack touches no platform configuration.
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
    print(f"[validation] consuming {QUEUE} ({' + '.join(DECLARATION['bindings'])})", flush=True)
    channel.start_consuming()


if __name__ == "__main__":
    main()
