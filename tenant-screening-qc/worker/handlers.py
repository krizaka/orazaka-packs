"""Routing key → handler, with no broker in sight: the worker's shell and the saga tests both call this."""

import screening

HANDLERS = {
    "job.screening.plan": screening.plan,
    "job.screening.consent": screening.consent,
    "job.screening.documents": screening.documents,
    "job.screening.cutoff": screening.cutoff,
    "job.screening.report": screening.report,
}


def consumption(result: dict) -> dict:
    """The pack's paid stage (documents) says whether it was charged: one call, or none when it was refused.

    The court-records and credit stages are the engine's checks: their consumption is the engine's own ``{calls}``."""
    if "charged" in result:
        return {"tokens": 0, "calls": 1 if result["charged"] else 0}
    return {"tokens": 0}


def handle(routing_key: str, payload: dict) -> tuple:
    handler = HANDLERS.get(routing_key)
    if handler is None:
        raise ValueError(f"no handler for routing key '{routing_key}'")
    result = handler(payload or {})
    return result, consumption(result)
