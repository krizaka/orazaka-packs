# identity-document-check

Is this identity document consistent with itself? A Studio for Yomizaka (verifying an applicant's documents), usable by any product
that checks an identity document. It returns **structured fields** and **findings**, each with its **evidence** (source, field,
value, region of the document) and a **confidence**.

## How it works

1. **Read** — a vision model routed by Orazaka transcribes the document: the machine-readable zone (MRZ) character by character, the
   printed fields, and what it can *see* (signs of tampering, a poor capture). One strict JSON answer; the model is told not to
   describe the person, not to say who they are and not to judge whether the document is genuine.
2. **Verify** — a worker (`worker/`, no model, no network, it never receives the image) decides by arithmetic:
   - the MRZ **check digits** of ICAO Doc 9303 (TD1, TD2, TD3; weights 7-3-1 modulo 10, document number, birth, expiry, optional data and
     the composite digit);
   - the **calendar**: real days only, the century of a two-digit year, expiry, birth in the future, expiry before birth, optional minimum age;
   - the **agreement** of the printed fields with the zone (names compared as the zone writes them; the document number without spaces
     or dashes) and with a decoded **barcode** (AAMVA elements `DAQ DCS DAC DBB DBA`, when the product has decoded the PDF417).

MRZ checksums and date logic are code, never left to the model (`worker/mrz.py`, `worker/rules.py`).

## The status

| Status | Meaning |
| :--- | :--- |
| `CONSISTENT` | Nothing to report. This is not a statement that the document is genuine. |
| `REVIEW` | A person should look: an expired document, a minimum age not met, a poor capture, a vision signal of tampering above the threshold, or a failed check that may be the transcription's fault (the model's confidence in the zone is low). |
| `INCONSISTENT` | The document disagrees with itself: a failed check digit, a printed field that differs from the zone or the barcode, an impossible date. |
| `UNREADABLE` | Nothing usable was read. |

A vision signal **never fails a document alone**: it asks for a look. A failed check digit on a doubtful transcription asks for a new
capture instead of accusing the document.

## Limits, said where they can be read

- `NAME_LINE_HAS_NO_CHECK_DIGIT` — no check digit covers the names of a zone; "all checksums hold" is not "the names are right".
- `VISION_READING_CAN_BE_WRONG` — every finding rests on a reading; the confidence says how much.
- `NO_DATABASE_LOOKUP` — nothing is looked up anywhere: no issuer database, no watch list.
- `NOT_A_LEGAL_IDENTITY_DECISION` — the pack identifies no one and decides nothing; the product and the person in charge do.

This version reads **images** (`image/*`: the platform's file kinds are image, video and audio). A **PDF** is not accepted as an
upload yet: the product renders the page to an image first. The barcode is **not decoded here**: the product passes the decoded text
of the PDF417 (`barcodeText`), the pack parses its data elements and checks them.

## Privacy

`regulatoryClass: SENSITIVE`: the controls of ADR-051 (data class, shortened retention, append-only audit, scope guard). The worker
keeps nothing and logs a job id and a routing key, never a field.

## Tests

- `worker/test_mrz.py` — the ICAO Doc 9303 specimens (the fictional Anna Maria Eriksson of « Utopia », TD1, TD2, TD3), a changed digit in
  each field, a tampered field whose own digit was recomputed (caught by the composite digit), the shapes, the calendar.
- `worker/test_rules.py` — every finding, evidence and confidence, the doubtful-transcription rule, signals, quality, barcode, age.
- `worker/test_worker.py` — payload checks, text-typed numbers from a blueprint, the reference day.
- `tests/golden/identity-document-check.json` — five golden cases; `tests/identity-document-check.test.mjs` — the manifest, blueprint
  and worker say the same thing.

Run: `cd worker && python3 test_mrz.py && python3 test_rules.py && python3 test_worker.py` (needs `pika` and `pyyaml`).
