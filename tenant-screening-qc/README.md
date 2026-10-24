# tenant-screening-qc

Screens a rental applicant in Québec, **one stage at a time**, and stops where the manager's rules say
([orazaka-packs#123](https://github.com/krizaka/orazaka-packs/issues/123), design in
[orazaka-ai-engine#74](https://github.com/krizaka/orazaka-ai-engine/issues/74), epic #73). A gated saga:

```
 plan ─ consent ─ documents ─ cut-off ┐
                                      ├─ (CONTINUE) consent ─ court records (TAL, plumitifs) ─ cut-off ┐
                                      │                                                                 ├─ (CONTINUE) consent ─ credit ─ cut-off ─ report
                       (STOP) ────────┴───────────────────── report ◄───────────────── (STOP) ──────────┘
```

| Stage | What it does | Purpose consented to | Credits (default ruleset) |
|:---|:---|:---|---:|
| 1. `documents` | Counts the signals of the evidence the two document Studios produced: `document-authenticity` (« signals ») and, optionally, `compliance-check` (the lease against the C.c.Q.). It re-runs and re-bills neither. | `DOCUMENTS` | 10 |
| 2. `courts` | The TAL and the plumitifs, through the engine's `ExternalCheckConnector` port (`verifyCourtRecords`). | `COURT_RECORDS` | 30 |
| 3. `credit` | A credit report, through the same port (`verifyCredit`). | `CREDIT` | 20 |

A stage runs, and is charged, **only if the one before it passed its cut-off**. A stopped saga never charges a later stage,
and its steps never run: the blueprint skips them (`condition`), it does not charge and refund.

## Cut-offs are data

* The **default** cut-offs are the dated ruleset `rules/screening-cutoffs/2026-10-24.json`: stop on a major document signal
  (level `incohérent`), stop on a court-records `MATCH`. The worker's code names no rule.
* The **manager's** rules replace the default of a stage. They are the Studio input `cutoffs`, by stage; an empty list removes the
  cut-off of that stage:

  ```json
  { "courts": [], "credit": [{ "id": "CUT-CREDIT-FILE", "fact": "outcome", "op": "equals", "value": "MATCH" }] }
  ```

  A rule is exactly `{id, fact, op, value}`. Operators: `equals`, `atLeast`, `in`. Facts per stage: `documents` has `majorSignals`,
  `unusualSignals`, `leaseFailures`; `courts` and `credit` have `outcome`. At most 8 rules a stage. An invalid rule fails the
  run at the `plan` step, **before any charge**.
* The first reason to stop wins, and the report says which: `CUTOFF` (with the `ruleId`), `NO_CONSENT`, `PROVIDER_ERROR`,
  `TIMEOUT`, `BUDGET`.
* A stop is a rule of the process, **not a verdict on the applicant**. The pack words nothing and decides nothing; the landlord
  decides.

## Consent per purpose

The product passes the purposes the applicant consented to (`consentedPurposes`). Consent is checked **before each paid
stage**, by one function used twice: the `consent` step (so the stage is skipped and the report shows `REFUSED`) and the stage
handler itself (so no route can skip the gate). A missing purpose stops that stage visibly (`NO_CONSENT`) and nothing is
called. The engine's `ConsentRegistry` stays the authority when the real connectors are wired.

## Credits, per stage, under the run budget

* Each paid stage is metered by the call (`billableUnit: CALL`); the control steps (plan, consent, cut-off, report) are not.
* A stage is charged only if it **answered**: `MATCH` or `NO_MATCH`. `PROVIDER_ERROR`, `TIMEOUT` and a refusal for lack of
  consent cost nothing (`charged: false`, `consumption.calls: 0`), and the saga stops as `INCOMPLETE` rather than spend on the
  next stage blind.
* The `report`'s `ledger` lists the credits per stage; it equals the stages that ran.
* The run budget is the engine's (ADR-088). The input `creditCap` adds a pack-level stop (`BUDGET`) before a stage the cap
  cannot pay; a cap that cannot pay the first stage is refused at the plan.

## The applicant never pays by default

`applicantPaysFees` is an **installation setting**, `false` by default, and never a run input (C.c.Q. art. 1904). When a
manager turns it on, the report says `payer: APPLICANT` and adds the limit `APPLICANT_PAYS_FEES_MAY_CONTRAVENE_CCQ_1904`.

## No raw personal data

The subject is its opaque `subjectId` (as in ai-engine#75). Names and birth date travel in the payload of the court-records and
credit steps and nowhere else: no step output, report, error message or log line carries them. The log is the job id and the
routing key. `SENSITIVE` (30-day retention at most, append-only audit, data class, scope guard).

## Mocks only

The connector is `MockConnector` (`worker/connectors.py`), recorded answers chosen by the last name, no network: `Tremblay`
matches, `Gagnon` does not, `Roy` is a provider error, `Bouchard` a timeout, anyone else has no match. Any other provider is
refused. The Studio is `DRAFT`. Spending starts when a pilot customer says go, and then the engine's `ExternalCheckService`
replaces `connectors.py`; the saga, the rules and the report do not change.

## Tests

```bash
cd worker && python3 test_screening.py      # the real blueprint, interpreted step by step, on every path
npm test                                    # manifest, blueprint, ruleset, goldens (tests/golden/tenant-screening-qc.json)
```

Paths covered on the mock: all clear; a stop after the documents (no provider call); a stop after the court records (credit never
called, never charged); a provider error (no charge for that stage); a timeout; a missing consent (per stage, and none at all);
the manager's rules; the budget; the fees setting; no personal data in any output or log.

## Not in this pack (needs another repository)

* The engine exposing the external checks as capabilities (`orazaka.core.checks.*`), the `calls` consumption key in the job service,
  a category in the port's result (to tell a TAL non-payment file from another file), and a provider reference that does not carry the
  last name (the engine's `MockConnector` puts it in `providerRef`): follow-ups in orazaka-ai-engine and orazaka-job-service.
