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
| Jurisdictions | `QC` (Québec — to be reviewed by a lawyer), `FR`, `BE-WAL` |
| Document types | the residential lease (every jurisdiction, the default) and, for `QC`, the supplier's **invoice** (`ruleset: qc-invoice`, opt-in) |

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

## Québec lease — what the ruleset covers, and what it does not (revision 2)

`QC-LEASE-004` catches a forbidden deposit however the lease words it — « dépôt de garantie / de sécurité / pour
dommages », « équivalant à un mois de loyer », a percentage, « deux mois de loyer d'avance », a surety in cash, refundable
key fees — with or without an amount (C.c.Q., art. 1904 al. 1). Negations pass (« aucun dépôt », « néant », « ne peut
exiger de dépôt »). Every wording is a fixture (ADR-072). `QC-LEASE-009` flags a clause that waives in advance the notice of,
or the tenant's right to refuse, a rent increase (art. 1942, 1943, 1945 ; 1893).

Not encoded, on purpose: the notice periods of art. 1942 and the content of the mandatory form's section F — their text could
not be checked at the source, and a compliance rule written from memory is worse than none. They wait for a lawyer's review
(`reviewStatus: TO_REVIEW_BY_LAWYER`).

## Québec invoice — `qc-invoice` (revision 1, opt-in)

A run names it with `ruleset: "qc-invoice"` (jurisdiction `QC`); without the name the jurisdiction's lease is used, as before.
Eight deterministic rules, no model question (the judge step is given nothing to read), each with its fixture pair and its
source. Written from the text of the **Input Tax Credit Information (GST/HST) Regulations, SOR/91-45, s. 3**, read on
laws-lois.justice.gc.ca (current to 2026-09-30, in force since 2024-06-20): every supporting document carries the supplier's
name, the date and the total; from **$100** the supplier's registration number, the tax or « tax included », (the rate); from **$500**
the buyer's name, the payment terms and a description. The thresholds were **$30 and $150 until June 2024** — a value that
would have been written from memory. Encoded: date, total, GST/HST number present and well formed (9 digits, `RT`, 4 digits —
CRA), QST number present and well formed (10 digits, `TQ`, 4 digits — Revenu Québec), taxes shown or included, payment terms.

Not encoded, and said so in the ruleset's `reviewNote`: the QST-specific requirement (the Québec regulation and Revenu
Québec's invoice page could not be read at the source), the supplier's and buyer's names and the description (no honest
lexical rule), the rate and the arithmetic of the taxes. The threshold rules do not read the amount; their finding says
« from $100 » / « from $500 ». A number is checked for its **form only**, never against the CRA or Revenu Québec registers.

## Québec service contract — `qc-service-contract` (revision 1, opt-in, first step)

Chosen by name like the invoice (`ruleset: "qc-service-contract"`). Four deterministic rules, **only from federal law read at its
source** (laws-lois.justice.gc.ca, 2026-10-19): interest on late payment stated per month, week or day without the yearly rate
(Interest Act s. 4: capped at 5 % a year then); a clause assigning moral rights (Copyright Act s. 14.1(2): they can only be waived);
assigning copyright in silence on moral rights (s. 14.1(3), advice); no mention of a signature (s. 13(4): an assignment is valid
only in writing signed by the owner, advice). **Not encoded** — the Civil Code of Québec could not be read at its source
(legisquebec.gouv.qc.ca and CanLII refuse automated reads): non-competition limits (art. 2089 is about employment contracts; for a
service contract the limit is case law), termination (art. 2125, 2129), penal clauses, payment deadlines (no statute requires one).

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

A TLS broker (the dev broker of Orazaka is TLS only, 5671): `RABBITMQ_SSL_ENABLED=true` (or the Java services'
`SPRING_RABBITMQ_SSL_ENABLED`), the private CA in `RABBITMQ_SSL_CA_FILE` (or `SPRING_RABBITMQ_SSL_CA_FILE`), and
`RABBITMQ_SSL_SERVER_NAME` when the address dialled is not the certificate's name. The certificate and the host name are
always verified (`worker/broker.py`, tested by `worker/test_broker.py`).

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
