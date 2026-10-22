# media-safety

Is this **photo**, **video** or **voice message** safe to show to the person it is sent to? Written for a dating product's
conversations (the pack names no product); a **safety check that fails closed**.

```
frames[assetId]  ──look (vision, per picture) ──┐
audio?[assetId]  ──listen (transcript) ── read (chat model judges the transcript) ──┤
                                                                                    └─ assess (worker, closed rules) → { verdict, blockers[], findings[] }
```

* **Pictures**: three yes/no questions to a vision model — nudity or sexual content, graphic violence, a minor in an unsafe context.
  A video is judged on **frames the caller samples** (the pack never sees the video), a photo on itself.
* **Sound**: Orazaka transcribes it (`orazaka.core.media.audio.analysis`), and a chat model judges the transcript on threats or
  harassment, sexual content, hate. Sound is judged **on its words only** — not on tone.
* **Fails closed**: a model answer that is not the expected JSON, a missing field, fewer answers than pictures, or nothing examined is
  **`UNREADABLE`, never `APPROVED`** — the product holds the media for a person to look at. A step that errors fails the run (nothing is
  skipped silently), and the product treats a failed run as « not approved ».
* Codes only (`SEXUAL_CONTENT`, `GRAPHIC_VIOLENCE`, `MINOR_UNSAFE`, `THREAT_OR_HARASSMENT`, `SEXUAL_SPEECH`, `HATE`), with the frame each was
  found in. The pack words nothing.

`SENSITIVE`: 30-day retention at most, append-only audit, data class, `scopeGuard` (it identifies no one). Its limits are in every
report: model answers can be wrong (both ways), a video is only its sampled frames, a sound only its transcript. It never claims more.

```bash
cd worker && python3 test_safety.py
```
