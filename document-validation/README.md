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
| Studios | `compliance-check` · `document-authenticity` |
| Jurisdictions | `QC` (Québec — to be reviewed by a lawyer), `FR`, `BE-WAL` |
| Document kinds | `kinds/*.json`, recognised by `identify` before any ruleset (below) |
| Document types | the residential lease (every jurisdiction, the default) and, for `QC`, the supplier's **invoice**, the **service contract**, the **visit notice** and the **état des lieux** (named rulesets, opt-in) |

## Deterministic first, model second

Each rule declares its `method`. `DETERMINISTIC` rules are evaluated in `worker/rules.py` by a
regex an auditor can read. `JUDGMENT` rules — the ones where judgement is genuinely required — are
asked of a model, **by a blueprint step**, so the inference is metered like any other. The worker
never calls a model itself.

An answer the model gets wrong in shape — unparseable, a verdict outside the enum, or about a rule
nobody asked about — becomes `INSUFFICIENT_EVIDENCE` for that rule. Guessing would be worse.

A PASS always quotes a passage of the document, and that passage is found in its text (orazaka-packs#124). A rule the
document gives no passage for is never a PASS: it is `NOT_APPLICABLE` when the document does not address the rule's
`subject` (the regex naming what the law is about: a deposit, the children, a penalty), and `INSUFFICIENT_EVIDENCE`
otherwise. A quote the model gives that the document does not contain is discarded, and the evidence field is never a
sentence written about the document.

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

## Québec lease — what the ruleset covers, and what it does not (revision 3)

`QC-LEASE-004` catches a required sum other than rent, whether called a deposit or otherwise — « dépôt de garantie / de sécurité / pour
dommages », « somme d'argent autre que le loyer », « équivalant à un mois de loyer », a percentage, « deux mois de loyer d'avance »,
a surety in cash, refundable key fees — with or without an amount (C.c.Q., art. 1904). Negations pass (« aucun dépôt », « néant »,
« aucune somme d'argent autre que le loyer », « ne peut exiger de dépôt »). Every wording is a fixture (ADR-072). `QC-LEASE-009` flags a clause that waives in advance the notice of,
or the tenant's right to refuse, a rent increase (art. 1942, 1943, 1945 ; 1893).

`QC-LEASE-010` asks for a contextual review of penalties and late fees under [C.c.Q., art. 1901](https://www.legisquebec.gouv.qc.ca/fr/version/lc/CCQ-1991?code=se:1901): the article concerns a penalty exceeding the landlord's actual loss or an unreasonable obligation. A fixed fee alone is not treated as a legal conclusion; its amount and circumstances require human review. `QC-LEASE-011` asks whether an applicable building regulation is described as delivered before the lease is concluded and as part of the lease, as required by [art. 1894](https://www.legisquebec.gouv.qc.ca/fr/version/lc/CCQ-1991?code=se:1894). The text check cannot establish that a copy was physically delivered. Both are advisory model questions with PASS/FAIL examples for review, not automatic legal determinations; the examples and a fictional sample annex are under `worker/fixtures/qc-residential-lease/`.

The articles were read from the official Légis Québec text: [art. 1894](https://www.legisquebec.gouv.qc.ca/fr/version/lc/CCQ-1991?code=se:1894) requires, where applicable, delivery of the regulation before the lease is concluded and states that it forms part of the lease; [art. 1901](https://www.legisquebec.gouv.qc.ca/fr/version/lc/CCQ-1991?code=se:1901) addresses a penalty exceeding actual loss and unreasonable obligations. The sample-annex golden case records the worker's deterministic findings and the judgment questions it queues, not the result of a legal review.

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

## Québec visit notice and état des lieux, and the language rule (orazaka-packs#125, #126)

Two rulesets, promoted kinds (`kinds/qc-visit-notice.json`, `kinds/qc-condition-report.json`): a document that `identify` recognises as one of them is judged by **its own** rules, never the lease's (no rent rule fires on a form with no rent). Both are opt-in, dated `2023-06-01` (the Charter's art. 55 in force), revision 1, `TO_REVIEW_BY_LAWYER`.

| Ruleset | Rules | Cited (names only) |
|:---|:---|:---|
| `qc-visit-notice` | `QC-VISIT-001` a notice of at least 24 hours, read in hours · `002` the intention stated (verify, work, show) · `003` no visit fixed outside 9 h to 21 h · `004` no works fixed outside 7 h to 19 h unless urgent · `005` no waiver of the right to refuse a visit | C.c.Q. art. 1931, 1932, 1933, 1893 |
| `qc-condition-report` | `QC-COND-001` no acknowledgement that the dwelling is habitable · `002` no cleaning after the landlord's works charged to the tenant · `003` no acceptance of a dwelling delivered unclean · `004` no exoneration of the landlord on habitability | C.c.Q. art. 1900, 1910, 1911, 1893 |
| the lease, both rulesets above | `QC-LANG-001` (the lease gets it in revision 5): the document is in French, or says a French version was handed over | Charter of the French language art. 55; C.c.Q. art. 1897 |

**The language rule is informative.** Another language is allowed when the French version was handed over and the parties expressly will it, so an English-only document is `INSUFFICIENT_EVIDENCE` (`check.onAbsent`), « à confirmer » by a person, never a `FAIL` on language alone. A bilingual document, or one that says the French version was handed over, passes. The express will itself is not read: it is a human check.

No article is prescribed for the *form* of an état des lieux, so the rules judge only what a clause cannot do. A blank form never passes a rule of its kind (each rule's `subject` is a sentence, not a label). **Law is cited, never reproduced**: each rule's `lawRef` carries the instrument, article, official Légis Québec address, the in-force date of the version read, the SHA-256 of the article and the date it was read (Données Québec, snapshot 2026-10-21); the text stays in the corpus. The pin (`law` block with a verified quote) comes with the promotion through the corpus (ADR-089 §5), so these citations read « unpinned » until then. Not encoded, and listed in each `reviewNote` for the lawyer checklist (krizaka/.github#250): urgency, the delivery mode of a notice, hours counted from a signature date, the content of an état des lieux, arts. 1912 and 1913, the express will of the parties.

Goldens: `worker/fixtures/qc-visit-notice/` and `qc-condition-report/` (compliant, defective, blank, English-only), and `qc-residential-lease/bilingual-compliant`. Tests: `worker/test_rules.py`, `test_golden.py`, `test_screening.py`, `test_identify.py`, `test_check.py`.

## Facts — the figures a ruleset reads (yomizaka#554)

A ruleset may declare `facts`: `{ id, kind: "money", pattern, label }`, the pattern's first group an amount. The report (1.x and 2.0) carries `facts.<id>` = `{ status: "found", cents, evidenceSpan }`, `{ status: "blank", evidenceSpan }` when the `label` is there with no amount behind it, or `{ status: "absent" }`. Nothing is inferred and the evidence is the document's own passage. `qc-residential-lease` declares `rentCents` (Loyer mensuel) and `lowestRentCents` (the Section G notice of the lowest rent paid in the last twelve months), so a consumer can compare the new rent against the previous one. The key is optional and only a ruleset that declares facts has it; the recorded 1.x reports were re-recorded for it (`fixtures/compliance-check/rerecord.py`).

## Kinds and `identify` — what a document is, before any ruleset (ADR-089 §1)

Until now the jurisdiction's default ruleset (the lease) judged every document. A visit notice or an état des lieux came
back with rent failures it can never satisfy. The first stage of [ADR-089](https://github.com/krizaka/orazaka/blob/main/docs/adr/ADR-089-rules-from-the-law.md)
reads **what the document is** and only then picks the ruleset.

**Kinds are pack data**: `kinds/<kindId>.json`, validated by `kinds/kind.schema.json`, beside the document profiles. One file per
kind, with its `signals` (a weight and a regular expression an auditor can read), its `jurisdictionHints` (a tribunal, a code,
a postal code), what it `excludes`, its `dateSignals` (and which one gives the `asOf`), the declared kinds it agrees with
(`declaredAs`), its `ruleset` and its fixtures. Adding a kind is adding a file and its fixtures, no code.

| `status` | Meaning |
|:---|:---|
| `PROMOTED` | a ruleset exists (`ruleset`): the check runs it |
| `KNOWN` | recognised, no ruleset yet: the run says `UNSUPPORTED_KIND` with the kind's label, and **no ruleset runs, never the lease's** |
| `RETIRED` | no longer detected |

Shipped: `qc-residential-lease`, `qc-invoice`, `qc-service-contract`, `fr-residential-lease`, `be-residential-lease` (`PROMOTED`),
`qc-visit-notice`, `qc-condition-report` (état des lieux), `qc-lease-modification-notice` (`KNOWN`: their rulesets are
[#125](https://github.com/krizaka/orazaka-packs/issues/125) and [#126](https://github.com/krizaka/orazaka-packs/issues/126)).

**`identify`** (`worker/identify.py`, capability `orazaka.validation.document.identify`, routing key `job.validation.identify`, the
validation worker) has **no model and no clock**: a pure function of the text, the declared kind, the jurisdiction, `asOf` and today. It returns:

| Field | |
|:---|:---|
| `detectedKind`, `kindUsed`, `kindSource` | what the text is; the kind that judges; `DETECTED` · `DECLARED` · `RULESET_INPUT` |
| `kindEvidence` | the passages of the document behind it, each checked to be in the text |
| `declaredKind`, `kindMismatch` | what the user said; true when the text is another kind. **Always surfaced, never silently resolved** |
| `jurisdiction`, `jurisdictionSource` | `DECLARED` or `DETECTED` (from the kind, else from the hints) |
| `documentDate`, `dateEvidence`, `asOf`, `asOfSource` | `INPUT` (the caller's) · `DOCUMENT` (the kind's date signal, with its passage) · `TODAY`. A blank form has no date |
| `languages` | `fr`, `en` or both, a fact for the language rules and never a verdict |
| `outcome` | `CHECK` · `UNSUPPORTED_KIND` · `KIND_UNKNOWN` |

A kind is a candidate when its signals weigh at least `min_signal_weight` (setting `law.identify.min-signal-weight`, default 2) and
none of its `excludes` matches; the jurisdiction hints add to its weight but never make it a candidate alone. The candidate with
the highest weight wins **if it is alone at the top**; a tie is not broken by a guess: the declared kind is used if it names exactly one
of the **tied** kinds, else the model may choose among them (`classifyAmong`, the `classify` step of `compliance-check` 2.0: its answer
is kept only if it names a tied kind or `OTHER` and its quote is in the document — `kindSource: CLASSIFIED`), else `KIND_UNKNOWN`. With
no candidate at all, the declared kind is used if it names exactly one kind of the scope. A declared jurisdiction restricts the kinds to
its own, never another country's. An explicit `ruleset` still overrides everything (`RULESET_INPUT`). There is no default kind in 2.0:
judging an unrecognised text by the jurisdiction's lease is **legacy 1.x behaviour**, kept only by installations pinned on a 1.x
blueprint.

```bash
cd worker && python3 test_identify.py     # each kind's fixtures (filled, blank, a document that must not match), every signal's pass/fail,
                                          # the mismatch, the ambiguous and the unknown document, the worker's capability
cd .. && node --test ../tests/document-kinds.test.mjs   # the files against kinds/kind.schema.json
```

Every fixture under `kinds/fixtures/` is fictional and written for this suite; no real template is quoted or copied.

## Retrieval — which articles a kind is judged by (ADR-089 §2)

A kind may carry a `retrieval` block (optional, `kinds/kind.schema.json`): the **`targets`** — instrument codes of the law corpus
and the articles of each, such as `CCQ-1991` art. 1931 to 1933 for `qc-visit-notice` — and the **`question`** in French and English
the grounded call is asked. `identify.retrieval_request(kind, language, asOf)` turns it into the input of the grounded step
(`orazaka.core.research.grounded` with `sources: ["law-corpus"]`): the engine
([orazaka-ai-engine](https://github.com/krizaka/orazaka-ai-engine), `LawRetrievalService`) reads **those articles only**, at `asOf`,
from the dated corpus — a visit notice brings art. 1931 to 1933 and no rent article — has the model write claims, checks every
quote with the ADR-087 verifier, and caches the result per (jurisdiction, kind, as-of bucket) until a cited article changes. The
engine never names an article: this file does. A kind without the block retrieves nothing; a language other than `fr`/`en` or an
`asOf` that is not an ISO date is refused by name. Tested in `worker/test_identify.py` (the golden case) and
`tests/document-kinds.test.mjs` (the schema). Every switch is off as seeded (`law.corpus.enabled`, `research.enabled`, the
`law-corpus` source).

## Derivation — proposed rules from the law (ADR-089 §3)

The engine proposes the checks of a kind from its law; nothing it proposes judges a document until it is promoted into
`rulesets/` (stage 5, through a pull request here). The derivation runs in [orazaka-ai-engine](https://github.com/krizaka/orazaka-ai-engine)
(`RuleDerivationService`, krizaka/orazaka-ai-engine#82): the retrieval above, its **verified** claims only, one model call per
article under `law.derive.max-credits`, then `vet` (`RuleProposalVet`, no model) and `rule_proposal` (`PROPOSED` or
`REJECTED_AUTO` with its reasons). `derivation/` holds what this pack owns of it:

| File | |
|:---|:---|
| `proposed-ruleset.schema.json` | The answer of the propose step: rules in the shape of a ruleset rule, each with its `law` blocks (instrument, ref, language, `contentHash`, quote) and a fixture pair. A derived rule uses `REQUIRED_PATTERN`, `FORBIDDEN_PATTERN` or `JUDGMENT` (always `ADVISORY`); the numeric checks stay written by hand. |
| `qc-visit-notice.fr.answers.json` | The golden case: recorded answers for art. 1931, 1932 and 1933 (no model was called). Four rules, all pass `vet`, none cites a rent article. |
| `qc-visit-notice.fr.outside-corpus.answer.json` | A recorded answer citing an article the corpus does not hold: `REJECTED_AUTO`, `LAW_VERSION_UNKNOWN`. |
| `planted/*.json` | One planted proposal per reason of `vet`: `SCHEMA_INVALID`, `REGEX_INVALID` (twice: an unclosed group, and a `(?<name>)` group Java compiles and this worker does not), `REGEX_MATCHES_EMPTY`, `QUOTE_NOT_IN_ARTICLE`, `UNSUPPORTED_NUMBER`, `FIXTURES_INDISTINCT`, `SUBJECT_MISSING`, `LAW_VERSION_UNKNOWN`, `OVER_RULE_LIMIT`. |
| `law/` | Art. 1931 to 1933 (French), the public text read from the Données Québec XML, each file hashed as the corpus hashes it (`citations.content_hash`). |

The engine's tests mirror these files and reject each plant for exactly its reason. `worker/test_derivation.py` shows the
same verdicts with this worker's own code: the golden rules discriminate their fixtures under `rules.evaluate` and their
quotes are `VERIFIED` by `citations.check`, and each plant fails here for the engine's reason. A derived rule is therefore
promotable through this pack's own tests. `tests/rule-derivation.test.mjs` checks the files against the schema.

```bash
cd worker && python3 test_derivation.py
node --test ../tests/rule-derivation.test.mjs
```

## `compliance-check` 2.0 — identify, then the ruleset of that kind (ADR-089 §4)

`identify` → `classify` (only on a tie) → `resolve` → `screen` → `judge` (only when a rule asks the model) → `report`. Inputs:
`document`, `jurisdiction` (now optional), `declaredKind` (`LEASE`, `NOTICE`, `CONDITION_REPORT`, `INVOICE`, `SERVICE_CONTRACT`,
`OTHER`), `asOf`, `ruleset` (override). `resolve` (`job.validation.resolve`) keeps or discards the model's choice and resolves the
ruleset in force at `asOf` **for the kind used**; a kind with no promoted ruleset never runs another kind's rules.

The report (`job.validation.report`), held by the platform to the `outputContract` of the `report` step (orazaka-studio#59):

| Field | |
|:---|:---|
| `contract` | `2.0` |
| `outcome` | `CHECKED` · `UNSUPPORTED_KIND` (a known kind without a ruleset: no rule runs) · `KIND_UNKNOWN` (no rule runs) |
| `identification` | the object of `identify`, the model's choice and why it was kept or not included |
| `ruleset` | `{id, version, revision, reviewStatus}`, when one ran |
| `findings[]` | as 1.x, with `citation: {reference, instrument, ref, language, officialUrl, inForceFrom, contentHash, quote}` and `checks: {passage, citation}` |

**Both quotes are checked.** `checks.passage` is `VERIFIED` (the passage is in the document), `ABSENT` or `NOT_IN_DOCUMENT`;
`checks.citation` is `VERIFIED` (the rule's `law` quote is in the article text the pack holds for its `contentHash`, `law/` — one JSON per
article version, refused at load if its text does not hash to it), `NOT_PINNED` (a rule written before ADR-089 that cites its article in
words only: the verdict is kept for now, and the finding says so — `citation.pinned: false` and the notice « citation non épinglée »;
pinning the shipped rules is packs#125/#126), `ARTICLE_NOT_HELD` or `QUOTE_NOT_IN_ARTICLE`. `law/` is a **snapshot for offline
verification, not a second corpus**: with `AI_LAW_CORPUS_ENABLED=true` and `AI_LAW_LOOKUP_URL` (off by default; the engine's
`GET /api/v1/law/articles?jurisdiction&instrument&ref&language&asOf`, orazaka-ai-engine#89, with the `oz_` key in `AI_LAW_LOOKUP_KEY`), `test_check.py` also
requires each held hash to be the corpus row `lookupStatute` returns (ADR-089 cut 3). A PASS or FAIL whose passage or citation fails is `INSUFFICIENT_EVIDENCE`,
and no passage is never a PASS. A 1.x installation stays pinned on its 1.x blueprint, and the worker answers `screen` and `assemble` as
before: yomizaka#305's recordings replay byte for byte (`worker/fixtures/compliance-check/`). The Studio is listed in
`run.result-cache.studios`: an identical run answers from the recorded report — **only when its day was given (`asOf`) or read in the
document**. The report step returns `resultCacheable: false` when the day came from the clock (`asOfSource: TODAY`), and so does a 1.x
`screen` without `asOf`; the platform never reuses such a run.

```bash
cd worker && python3 test_check.py   # plays the blueprint step by step: the recordings, each outcome, a 1.x call, both quotes
```

## Known limits (demo documents under `worker/fixtures/`)

- The **lease** rules read French wording (the language of the mandatory form). An English lease is not read: it comes
  back with blocking failures (parties, rent) and must never be taken for a clean one (`fixtures/qc-residential-lease/en-not-read.txt`).
  The invoice and the service contract rules read both languages.
- The **service contract** does not encode the Civil Code (art. 2098 and following), among them the client's right to
  terminate (art. 2125): the text could not be read at its source. The report must say « non vérifié : droit de résiliation,
  art. 2125 C.c.Q., à faire relire par un avocat ».

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
always verified (`worker/broker.py` re-exporting `worker-common/worker_broker.py`, tested once by `worker-common/test_worker_broker.py`).

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

Reads **facts about a file** — a PDF, an image (JPEG, PNG, WebP, TIFF, HEIC) or an office document (Word, Excel,
PowerPoint, OpenDocument), recognised by its bytes — and reports which ones deserve a question. Same pack, same worker
process, one more routing key — `job.validation.signals`.

**It has no model call.** Not a constrained one. A model asked to explain a tampering signal will
explain signals it never received, and the error it makes most readily is the one that accuses an
honest person. The explanations are written by hand, once, per signal case — in a data file, not in code:
`worker/authenticity-signals.json` (each case's id, level, thresholds, sentences FR/EN) and
`worker/producer-profiles.json` (what kind of software a producer is: editor, OCR, scanner, generator), and
`worker/document_profiles/<type>.json` (expected issuers and fields, accepted producers/classes, and page/font ranges,
validated against `worker/document-profile.schema.json`). The authenticity Studio accepts an optional `documentType`
(`pay-stub`, `bank-statement`, or `employment-letter`). A mismatch is an informational `inhabituel` signal, never a
verdict; without a matching profile, the report follows its prior behavior. Profiles are examples to review and tune
for the organization's document sources; the worker does not extract their listed content fields.
A new signal
is an entry there, its detector in `authenticity.py` and its PASS/FAIL case in `test_authenticity_formats.py`.

| Family | Signals | Read from |
| :--- | :--- | :--- |
| PDF | `PDF-META-001…004`, `PDF-REV-001`, `PDF-ID-001`, `PDF-TEXT-001`, `PDF-FONT-001`, `PDF-OBJ-001` | info dictionary, `%%EOF`, trailer `/ID`, fonts, objects |
| Any file with XMP | `XMP-HIST-001` | `xmpMM:History` (saves and conversions, and by which software) |
| Images | `IMG-META-001…005` | EXIF device, software, capture and modification dates (never GPS nor owner) |
| Office | `OFF-META-001…002` | the package's application, dates and revision (never author fields: they name a person) |

An editor is reported as what it is — a tool people use every day — never as proof of anything.

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
.venv/bin/python worker/test_golden.py              # golden cases: whole documents, every rule's verdict (--update to rewrite)
.venv/bin/python worker/test_authenticity.py        # the gate
.venv/bin/python worker/test_authenticity_formats.py # the catalogue, XMP, /ID, images, office files
```
