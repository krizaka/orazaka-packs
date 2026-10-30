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
| 2. `courts` | The TAL and the plumitifs: the engine's check `orazaka.core.checks.courtrecords`. | `COURT_RECORDS` | 30 |
| 3. `credit` | A credit report: the engine's check `orazaka.core.checks.credit`. | `CREDIT` | 20 |

## One door: the engine's checks

The court-records and credit stages are **the engine's capabilities** (orazaka-ai-engine#90, `ExternalCheckCapability`), not
this pack's: the pack declares no check capability, no handler and no connector of its own. Per call the engine does, in
order: HMAC subject ref → consent → key → one `CALL` held → provider (the mock) → audit → settle (answered) or release.

The step contract (`tests/contracts/orazaka-core-checks.json`, the one the job-service executor answers):

* **inputs** `subject` (`{subjectId, lastName, firstName, birthDate?, address?}`) and `consentedPurposes` (the same list the
  pack's consent steps read: the engine grants a purpose only when it is listed);
* **outputs** `outcome` (`MATCH`, `NO_MATCH`, `PROVIDER_ERROR`, `TIMEOUT`, `REFUSED`), `refusal` (`NO_CONSENT`, `NO_KEY`,
  `BUDGET_EXHAUSTED` or null), `category` (`TAL_NON_PAYMENT`, `TAL_OTHER`, `CRIMINAL`, `CIVIL`, `NONE`), `providerRef` (opaque),
  `calls` (0 or 1) and `resultJson` (the same object as JSON); consumption `{calls}`.

The cut-off and report steps read `resultJson` and keep only the closed codes: a stage is charged its credits only when
`calls` is 1, `providerRef` stays in the engine's audit, and an answer that does not hold together (a call without an answer, a
category without a match, a refusal without its reason) fails the run rather than being guessed.

A stage runs, and is charged, **only if the one before it passed its cut-off**. A stopped saga never charges a later stage,
and its steps never run: the blueprint skips them (`condition`), it does not charge and refund.

## Cut-offs are data

* The **default** cut-offs are the latest dated ruleset in `rules/screening-cutoffs/` (`2026-10-30.json`): stop on any
  court-records `MATCH`, whatever its category. **A document signal is never a default cut-off**: the signals (with their
  evidence) go to the report and a person reads them; no applicant is stopped by a forensic signal alone (Law 25 s. 12.1).
  A manager may still choose a rule on `majorSignals`; the report then says `ruleSource: "MANAGER"` (a default stop says
  `"PACK"`). Such a stop also says `decisionBy: "MANAGER"` and `humanReview: { available: true, basis: "LAW_25_S12_1" }`: the
  decision is the manager's own rule, and the applicant may ask for a human review (Law 25 s. 12.1). The worker's code names no rule.
* The **manager's** rules replace the default of a stage. They are the Studio input `cutoffs`, by stage; an empty list removes the
  cut-off of that stage:

  ```json
  { "courts": [], "credit": [{ "id": "CUT-CREDIT-FILE", "fact": "outcome", "op": "equals", "value": "MATCH" }] }
  ```

  A rule is exactly `{id, fact, op, value}`. Operators: `equals`, `atLeast`, `in`. Facts per stage: `documents` has `majorSignals`,
  `unusualSignals`, `leaseFailures`; `courts` has `outcome` and `category` (the engine's closed category of a file found, since the
  ruleset `2026-10-25`), `credit` has `outcome`. A rule on `outcome` or `category` names values from their closed set
  (`MATCH`/`NO_MATCH`; `TAL_NON_PAYMENT`, `TAL_OTHER`, `CRIMINAL`, `CIVIL`, `NONE`), so a typo fails the plan instead of never
  holding. At most 8 rules a stage. To stop only on a TAL non-payment file:

  ```json
  { "courts": [{ "id": "CUT-TAL-NON-PAYMENT", "fact": "category", "op": "equals", "value": "TAL_NON_PAYMENT" }] }
  ```
* A ruleset is **dated data**: a change is a new file (`2026-10-25.json` added `category`, `2026-10-30.json` removed the documents cut-off); the older ones are never rewritten. An invalid rule fails the
  run at the `plan` step, **before any charge**.
* The first reason to stop wins, and the report says which: `CUTOFF` (with the `ruleId`), `NO_CONSENT` (the pack's consent
  step or the engine's refusal), `PROVIDER_ERROR`, `TIMEOUT`, `NO_KEY` (the engine has no key for the provider), `BUDGET` (the
  pack's cap, or the engine's `BUDGET_EXHAUSTED`).
* A stop is a rule of the process, **not a verdict on the applicant**. The pack words nothing and decides nothing; the landlord
  decides.

## Consent per purpose

The product passes the purposes the applicant consented to (`consentedPurposes`). Consent is checked **before each paid
stage**, twice: by the pack's `consent` step (so the stage is skipped and the report shows `REFUSED`), and where the stage runs
— the documents handler itself, and the engine's checks, which receive the same `consentedPurposes` and refuse with
`NO_CONSENT` before any key or call. No route skips the gate. A missing purpose stops that stage visibly (`NO_CONSENT`) and
nothing is called.

## Credits, per stage, under the run budget

* Each paid stage is metered by the call (`billableUnit: CALL`); the control steps (plan, consent, cut-off, report) are not.
* A stage is charged only if it **answered**: `MATCH` or `NO_MATCH` (the engine's `calls: 1`). `PROVIDER_ERROR`, `TIMEOUT` and
  a refusal (consent, key, budget) cost nothing (`charged: false`, `consumption.calls: 0`: the engine releases its hold), and the saga stops as `INCOMPLETE` rather than spend on the
  next stage blind.
* The `report`'s `ledger` lists the credits per stage; it equals the stages that ran.
* The run budget is the engine's (ADR-088). The input `creditCap` adds a pack-level stop (`BUDGET`) before a stage the cap
  cannot pay; a cap that cannot pay the first stage is refused at the plan.

## The applicant never pays by default

`applicantPaysFees` is an **installation setting**, `false` by default, and never a run input (C.c.Q. art. 1904). When a
manager turns it on, the report says `payer: APPLICANT` and adds the limit `APPLICANT_PAYS_FEES_MAY_CONTRAVENE_CCQ_1904`.

## No raw personal data

The subject is its opaque `subjectId` (as in ai-engine#75). Names and birth date travel in the payload of the engine's
court-records and credit checks and nowhere else: no step output, report, error message or log line carries them, and only the
closed codes of the engine's answer are read (whatever else it carried never reaches a result). The log is the job id and the
routing key. `SENSITIVE` (30-day retention at most, append-only audit, data class, scope guard).

## Mocks only

Still on mocks until the pilot's go. The connector is the engine's `MockConnector`, recorded answers chosen by the last name,
no network: `Tremblay` has a TAL non-payment file, `Côté` another TAL file, `Morin` a criminal one, `Lavoie` a civil one,
`Gagnon` none, `Roy` is a provider error, `Bouchard` a timeout, anyone else has no match. The ruleset names the mock, and a
ruleset naming any other provider fails the plan. The Studio is `DRAFT`. The saga's tests answer the engine's steps with
`FakeEngine` (`worker/test_screening.py`), the same contract and fixtures.

## Tests

```bash
cd worker && python3 test_screening.py      # the real blueprint, interpreted step by step, on every path (engine faked)
npm test                                    # manifest, blueprint, ruleset, goldens (tests/golden/tenant-screening-qc.json)
```

Paths covered on the mock: all clear; a stop after the documents (no provider call); a stop after the court records (credit never
called, never charged); a provider error (no charge for that stage); a timeout; a missing consent (per stage, none at all, and
refused by the engine); the engine refusing for lack of key or budget; a cut-off on the category; an engine answer that does not
hold together; the manager's rules; the budget; the fees setting; no personal data in any output or log.

## Not in this pack (needs another repository)

* orazaka-job-service: the executor and capability rows of `orazaka.core.checks.*`, answering the contract above
  (orazaka-packs#138). Until they exist, the courts and credit steps have no executor and the Studio cannot run end to end.
* orazaka-ai-engine: the meter (pricebook hold) and pepper (sealed settings) adapters; krizaka-billing: an `EXTERNAL_CHECK`
  billable capability (orazaka-packs#138).
