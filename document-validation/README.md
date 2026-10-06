# document-validation

Checks a document against a **versioned body of rules** and returns findings — never prose.

```
(ruleId, severity, verdict, evidenceSpan, explanation, method, citation)
```

The user forwards this output to their counterparty. That single fact decides everything below.

## What it is

| | |
|:---|:---|
| Tier | `WORKER` — it brings its own worker; the deterministic rules are code, not a prompt |
| `regulatoryClass` | `SENSITIVE` — it receives the five controls of ADR-051 and declares a `scopeGuard` |
| Studios | `compliance-check` |
| Jurisdictions | `FR`, `BE-WAL` |

## Deterministic first, model second

Each rule declares its `method`. `DETERMINISTIC` rules are evaluated in `worker/rules.py` by a
regex an auditor can read. `JUDGMENT` rules — the ones where judgement is genuinely required — are
asked of a model, **by a blueprint step**, so the inference is metered like any other. The worker
never calls a model itself.

An answer the model gets wrong in shape — unparseable, a verdict outside the enum, or about a rule
nobody asked about — becomes `INSUFFICIENT_EVIDENCE` for that rule. Guessing would be worse.

## Rulesets

```
rulesets/<rulesetId>/<effectiveFrom>.json
```

`asOf` selects the version **in force on that date**, never the newest: a lease signed in 2025 is
judged against the rules of 2025, and replaying a run reaches the same verdicts.

Two numbers, and they answer different questions:

- **`version`** — the date the *law* takes effect. A new one means the law changed.
- **`revision`** — how many times this pack has corrected its own reading of that law, with a
  `revisionNote`. A new one means *we* were wrong, not the legislature.

Both appear in every report.

## Adding a jurisdiction

Add `rulesets/<id>/<effectiveFrom>.json` and its code to the blueprint's `jurisdiction` enum. No
platform change, no engine code. A jurisdiction the pack does not carry is **refused by name** —
falling back to another country's law would produce a confident report against rules that do not
apply.

## Running the worker

```bash
pip install pika pyyaml
cd worker && python3 validation_worker.py     # reads RABBITMQ_HOST / _USER / _PASS
```

## Testing the rules

The rule engine is a pure function of `(ruleset, text)` — no broker, no model — so it is testable
on its own, which for a compliance product is the part that must be tested hardest:

```bash
cd worker && python3 test_rules.py
```

## What it does not do

**Authenticity.** It says nothing about whether a document is genuine. When that ships it will be a
separate Studio emitting *signals with confidence and never a verdict* — see ADR-052 §7.

## The authenticity Studio — `document-authenticity`

Reads **facts about a PDF file** and reports which ones deserve a question. Same pack, same worker
process, one more routing key — `job.validation.signals`.

**It has no model call.** Not a constrained one. A model asked to explain a tampering signal will
explain signals it never received, and the error it makes most readily is the one that accuses an
honest person. The seven signal explanations are written by hand, once, per signal type.

**Triage, not a verdict.** It tells a reader *"these three points deserve a question"* or *"nothing
stands out"*. It is not an examination, the report says so in full at the top, and it names what a
real examination would involve — because the honest product is the one that helps someone decide
whether to pay for the real thing.

**No score.** Three qualitative levels, each defined in writing in `LEVELS`: `observé`,
`inhabituel`, `incohérent`. A percentage would be a lie without a measured base rate, and it gets
quoted in a dispute as though it were one.

Three prohibitions, enforced by tests rather than remembered: no verdict anywhere a signal is
produced, no signal that names a person, and every report states what it did not examine.

```bash
.venv/bin/python worker/fixtures/make_fixtures.py   # rebuild the three gate documents
.venv/bin/python worker/test_authenticity.py        # the gate
```
