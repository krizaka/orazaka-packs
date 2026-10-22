# profile-photo-check

Looks at a set of profile photos and says whether they hold together as **one real adult's profile**: enough photos,
enough of them with a face, the same person from one face photo to the next, nothing written over the picture, no
screenshot. It answers in **codes** — the product that asked words them in its own language and register.

Written for Yasakia, whose rule is « real people »; the pack knows nothing of Yasakia. The numbers (at least 4 photos,
at most 6, at least 2 with a face) are **inputs of each run**, owned by the product — here they only default.

```
(photosBase64, photos[assetId], minPhotos, maxPhotos, minFacePhotos)
        │
        ├─ faces  ── worker, job.photo.inspect ── YuNet + SFace (OpenCV) ── counts, kinds, identity   (no model call)
        ├─ look   ── vision model, once per photo ── three yes/no questions, JSON only             (metered like any step)
        └─ assess ── worker, job.photo.assess  ── rules → { passes, blockers[code, photos[]], photos[], limits[] }
```

| | |
|:---|:---|
| Tier | `WORKER` (`orazaka-worker-photo`, drains `job.photo.*`) — a lone Studio, like `trade-showcase`, run by its key |
| `regulatoryClass` | `SENSITIVE`: 30-day retention at most, append-only audit, data class stamped, a `scopeGuard` |
| Models | YuNet 2023mar (**MIT**), SFace 2021dec (**Apache-2.0**), both from the OpenCV Zoo, pinned by SHA-256 in `worker/models.lock.json` |
| Vision | whichever vision model the platform's catalogue picks (`orazaka.core.media.vision`) |

## What a photo can be

`FACE` — one face dominates the frame (its area is at least twice the next face's): a photo **of** someone.
`GROUP` — several faces of similar size: nobody in particular is the subject; allowed, but it does not count as a face
photo. `NO_FACE` — no face worth the name (a landscape, a pet, the back of someone's head, a face too small to be the
point): welcome, it just does not count.

## The checks, and who makes them

| Code | Who | Blocks |
|:---|:---|:---|
| `TOO_FEW_PHOTOS`, `TOO_MANY_PHOTOS`, `TOO_FEW_FACE_PHOTOS` | the rules, from the product's counts | yes |
| `FACE_MISMATCH` | SFace: the photo is *clearly different* from the reference group | yes |
| `MINOR_LIKELY`, `TEXT_OR_CONTACT`, `SCREENSHOT` | the vision model, as a yes/no | yes |
| `UNVERIFIED` | the vision model answered something unreadable | **no** — guessing would be worse in both directions |
| `GROUP_PHOTO` | the detector | no |

The rules and thresholds are **data** (`rules/profile-photo/<effectiveFrom>.json`, picked by date like the
document-validation rulesets): a new file is a new version, never an edit.

## Privacy, said plainly

* **Comparing faces is biometric processing** (Québec Law 25, GDPR art. 9). The caller decides with `compareFaces`: `false` — the
  product has not the person's explicit, separate consent, or has not had the processing reviewed — and faces are only
  *counted*: no vector is even computed and the identity is `NOT_COMPARED`. The consent, its wording and its withdrawal are the
  product's to hold; the pack only refuses to compare when it is told not to.

* A face vector is a biometric template. Here it exists **for one job, in memory**, to answer « could these photos be of
  different people? », and is dropped when the job ends. It is never returned, logged, stored or sent anywhere — the
  report holds counts and codes, and a test fails if a vector-shaped value appears in an output.
* The worker logs the job id and the routing key. No photo, no face count, no code.
* The photos reach the platform as thumbnails of about 512 px, inside the run's inputs (and as assets for the vision
  step). Because the pack is `SENSITIVE`, the platform purges them after 30 days at most; the caller deletes the assets as
  soon as the run is done and sets a shorter `retentionDays` on its installation if it can.
* No model is trained on them; no photo is compared with anything but the other photos of the same set.

## What it does not do — and how it can be wrong

* **It identifies no one.** No search of a face against anything, no celebrity recognition (refused by the `scopeGuard`
  and listed in every report's `limits`). A « screenshot of a celebrity » is caught only as a *screenshot* or as
  *text over the photo* when it looks like one — not by who is in it.
* **Face matching is a mismatch detector, not an identity proof.** Face-recognition models are known to perform unevenly
  across skin tones, ages, make-up and lighting, and to be fooled by a lookalike. So the thresholds lean to not
  accusing: two photos are called different only below a cosine of 0.25 (the model's published « same person »
  operating point is 0.363, and the band between is never held against anyone). It has **not** been calibrated on
  Yasakia's own population, and the product must treat `FACE_MISMATCH` as « the photos may not show the same person —
  choose others, or ask for a review », never as an accusation.
* **A vision model answers yes/no questions and is sometimes wrong** (a small model can see a minor in an adult who looks
  young, or miss a watermark). Its three answers block a photo only when the answer is a clear `true`; the product keeps a
  human review path.
* It says nothing about whether a photo is *flattering*, *edited* or *AI-generated*.

## Running the worker

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python worker/fetch_models.py            # YuNet + SFace into worker/models/ (SHA-256 checked)
cd worker && ../.venv/bin/python photo_worker.py   # RABBITMQ_HOST / _USER / _PASS (+ _SSL_* for the TLS dev broker)
```

## Tests

```bash
cd worker && python3 test_rules.py && python3 test_faces.py && python3 test_worker.py
npm test    # from the repository root: the manifest ↔ blueprint ↔ worker coherence
```

`test_faces.py` also runs the real models on `worker/fixtures/astronaut.jpg` (NASA's public-domain portrait of Eileen
Collins) when the model files are present. No photograph of a private person is ever committed.
