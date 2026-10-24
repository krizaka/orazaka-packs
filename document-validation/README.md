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
| Document types | the residential lease (every jurisdiction, the default) and, for `QC`, the supplier's **invoice** (`ruleset: qc-invoice`, opt-in), the **service contract** (`qc-service-contract`), the **visit notice** (`qc-visit-notice`) and the **état des lieux** (`qc-premises-condition`), all three opt-in |

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

## Known limits (demo documents under `worker/fixtures/`)

- The **lease** rules read French wording (the language of the mandatory form). An English lease is not read: it comes
  back with blocking failures (parties, rent) and must never be taken for a clean one (`fixtures/qc-residential-lease/en-not-read.txt`).
  The invoice and the service contract rules read both languages.
- The **service contract** does not encode the Civil Code (art. 2098 and following), among them the client's right to
  terminate (art. 2125): the text could not be read at its source. The report must say « non vérifié : droit de résiliation,
  art. 2125 C.c.Q., à faire relire par un avocat ».

## Québec visit notice and état des lieux — `qc-visit-notice`, `qc-premises-condition` (opt-in, orazaka-packs#125)

Chosen by name (`ruleset: "qc-visit-notice"` or `"qc-premises-condition"`); both in force from 2023-06-01, the date of the Charter's art. 55 that the language rule reads. Sources: the consolidated Code civil du Québec read in the open-data XML of Données Québec (snapshot 2026-10-21, read 2026-10-23), each rule pinning the SHA-256 of its article and its official Légis Québec URL. Légis Québec and CanLII are not read by this pack.

- **Visit notice**: a 24-hour notice (art. 1931, numeric, in hours); the intention stated (art. 1931); no visit fixed outside 9 h to 21 h (art. 1932); no works fixed outside 7 h to 19 h unless urgent (art. 1933); no waiver of the tenant's right to refuse a visit (art. 1932, void under art. 1893).
- **État des lieux**: no statute prescribes its form, so the rules check only what a clause cannot do: no acknowledgement of habitability (art. 1910, al. 2), no cleaning after the landlord's works charged to the tenant (art. 1911, al. 2), no acceptance of a dwelling delivered without its cleanliness (art. 1911, al. 1), no exoneration of the landlord on habitability (art. 1900).
- A blank form never PASSes a rule of these kinds: the rules read sentences, not labels, and a notice period with no figure is INSUFFICIENT_EVIDENCE.

Not encoded: urgency (the document does not establish it), the mode of delivery of the notice, computing hours from a signature date, the content of the état (no article requires it), and arts. 1912–1913 (safety and unfit dwelling), whose content is a matter of fact.

## Language — `QC-LANG-001`, shared by the three Québec document kinds (orazaka-packs#126)

The same rule is in the lease (revision 4 of `qc-residential-lease`), the visit notice and the état des lieux. It is a `REQUIRED_PATTERN`: a French contractual passage (« le locateur », « la locataire »…), or a sentence stating that a French version was handed over (« version française remise »), passes it. An English-only document fails it: the Charter's art. 55 requires French for an adhesion contract and the documents attached to it, and another language binds only after the French version was given to the adherent and the parties' express will is stated (art. 55, al. 2; C.c.Q. art. 1897 for the lease). The rule does not verify the express will: that stays with a human. A bilingual document passes.

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
