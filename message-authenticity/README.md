# message-authenticity

Reads **one message's text** with a small open classifier (`fakespot-ai/roberta-base-ai-text-detection-v1`, **Apache-2.0**, pinned by
revision, run in the worker's own process) and answers a **coarse level** — `LOW · MID · HIGH · UNAVAILABLE` — **never a score**.
The product combines it with what only it can measure (how the message arrived: typing time, pastes) and shows a *signal*, with a
tooltip saying it can be wrong. It never writes a message for anyone; it judges a text it is handed, and forgets it.

| | |
|:---|:---|
| Tier | `WORKER` (`orazaka-worker-authenticity`, drains `job.authenticity.*`) — a lone, FREE Studio, one step, no generative model |
| `regulatoryClass` | `SENSITIVE` (a private message): 30-day retention at most, append-only audit, data class, `scopeGuard` |
| Languages | `en`, `fr` (a stopword count picks the thresholds). Any other language, or fewer words than `minWords` (12), is `UNAVAILABLE` — never guessed |
| Ruleset | `rules/message-authenticity/<effectiveFrom>.json`, chosen by date: thresholds per language, the model and its revision |

## Why a signal, not a verdict — the numbers

AI-text detectors are unreliable, above all on **short texts** and on **non-native or French writing**. We measured, on a small set
(`calibration/`): 80 human texts and 80 generated texts per language, 14 to 70 words.

* **Human** texts: public user-generated text (French tweets and YouTube comments, English movie-review sentences). Their licences
  are not clear, so **they are not in this repository** — only the script that fetches them and their SHA-256 (`human-manifest.json`).
  This is not dating chat: the genre differs from what the product judges, which flatters or hurts a detector in ways we cannot
  measure without a corpus of real dating messages (which we neither have nor should).
* **Generated** texts (`generated.json`): first messages on a dating app, written through Orazaka's chat (one model family), in
  varied tones, lengths and « write like a real person » styles. Other models, and people who edit a generated text by hand, will
  fool it more.

| | AUC (can it rank at all?) | Threshold « HIGH » | False « HIGH » on humans | Generated texts recognised |
|:---|:---:|:---:|:---:|:---:|
| English | 0.62 | 0.998 | 0 of 80 (95 % upper bound 4.6 %) | 3 of 80 |
| French | 0.71 | 0.995 | 0 of 80 (95 % upper bound 4.6 %) | 10 of 80 |

Tuned on one half and measured on the other (`calibrate.py`, `results.json`), « HIGH » gave 0 of 40 false positives in each language
(upper bound 8.8 %) and recognised 2 of 40 (EN) and 11 of 40 (FR) generated texts; « MID » (the 95th percentile of humans) is wrong
about humans 3 of 40 (EN) and 2 of 40 (FR) times. **At the price of not accusing humans, the classifier alone recognises a small minority
of generated texts.** The other multilingual detector we tried (`bibbbu/multilingual-ai-human-detector_xlm-roberta-base`, MIT) ranked at
chance in English (AUC 0.50) and its labels are undocumented. A larger set, real dating messages and more generators would move
these numbers; until then they are an honest floor, not a promise.

So the pack's only job is to **corroborate**: the product shows « probably generated » only when the text reads as machine **and** the
message arrived pasted (or faster than a hand types) — two independent signs — and never blocks a message on any of it. A short
text (< 12 words) is « too short to judge ».

## What it keeps

Nothing. The score is computed, turned into a level and dropped (a test fails if a number appears in a report); the log is the job id
and the routing key. The platform keeps the run (`SENSITIVE`: purged within 30 days).

## Running

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd worker && ../.venv/bin/python authenticity_worker.py     # RABBITMQ_HOST / _USER / _PASS (+ _SSL_* for the TLS dev broker)
python3 test_authenticity.py && python3 test_broker.py      # no model needed
```
Recalibrate: `build_human_set.py`, `generate_set.py` (needs `AI_ENGINE_URL` / `AI_ENGINE_API_KEY`), `evaluate.py`, `calibrate.py`.
