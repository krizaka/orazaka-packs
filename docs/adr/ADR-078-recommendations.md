# ADR-078 — Recommendations: a two-stage recommender served by Orazaka, fed by the product

- **Status:** Accepted (2026-10-15)
- **Epic:** a former product's issue — related: a former product's issue (no personalisation
  today), orazaka-packs#22
- **Numbering:** the Orazaka ADR sequence (the last one in the workspace is ADR-077); recorded here because the
  `recommendations` pack and its Studios live in this repository.

## Context

a former product's Explore ignores the viewer: trending, new and "similar by tags" are the same for everyone (a former product's issue). The
rule of the house is that a product's AI runs **on Orazaka** — through a pack or Orazaka's API, with a tenant service
key, never a model called directly. a former product already calls Orazaka for one thing (`POST /api/v1/embeddings`, key scope
`ai:embed`, the Explorer) and keeps those vectors itself.

The market's answer to "a feed per person" is the **two-stage recommender** (YouTube 2016, TikTok Monolith, Pinterest
PinnerSage): an event stream feeds item and user representations; **retrieval** (candidate generation: approximate
nearest neighbours + co-engagement + fresh + follows) narrows millions to hundreds; **ranking** orders them with a
learned model, then a **re-ranker** adds diversity and business caps. We have tens of creators and hundreds of videos,
no logged outcomes, a 2 GB dev container and a budget rule (≤ 5 $/month of new recurring cost without a written yes).

## Decision

### 1. Where it runs — two halves with different clocks

| Half | Clock | Where | Why |
|---|---|---|---|
| **Serving** — events in, feeds out | synchronous, < 150 ms p95 | `orazaka-knowledge-service`, feature `recommendation`, its own tables in `orazaka_knowledge_db` (pgvector) | The knowledge context already *is* "retrieval over vectors in its own database". A Studio run is an asynchronous, metered saga — the wrong tool for a feed request. No new service, no new database, one more JVM in the dev `core` container (heap 128 MiB). |
| **Item understanding** — what a video is about | asynchronous, per READY video | text: the serving half embeds title · description · tags through the platform's embedding model (conversation service, service token) · frames and speech: **the `recommendations` pack's Studio `video-understanding`** (§6) | Understanding is a metered model run (vision on keyframes, Whisper on audio) — exactly what a pack Studio is. Its result is written back as the item's text facets, re-embedded by the serving half. |

The API is reached through the edge like every other Orazaka surface (`/api/v1/recommendations/**` → knowledge
service); the product never names a model or a provider.

### 2. The tenant and the key

- The caller is a **service account** of the product (`svc_<product>`), its `oz_` key minted by
  `scripts/dev-deploy.mjs service-account` and stored as a DO SECRET (`AI_ENGINE_API_KEY`).
- Two new **key scopes** at the edge (`ApiKeyScopes`, exact method + path, fail closed): `reco:sync` (events, items,
  erasures) and `reco:read` (for-you, similar, creator insights). a former product's key holds `ai:embed reco:sync reco:read`.
- **Tenant = the JWT subject** (the service account's user id). Every row carries `tenant_id`; no query reads across
  tenants. Rate limit: the edge's per-key daily quota (`AUTH_API_KEY_DAILY_REQUESTS`) — batches keep it far below.

### 3. Data — pseudonymous, purpose-limited (Loi 25)

- **Users are pseudonyms**: a former product sends `HMAC-SHA256(AI_PSEUDONYM_KEY, userId)`, never its user id, an e-mail, a
  name or a message. Items are public video ids; creators are public profile ids.
- **Events** (`reco_event`): `id` (the product's idempotency key, a duplicate is ignored), `user`, `item`, `kind`
  (`VIEW · LIKE · SAVE · SHARE · TIP · UNLOCK · FOLLOW · SKIP · REPORT`), optional `watchedPct`, `at`.
- **Retention**: events older than the tenant's `retentionDays` (setting, default 180) are purged daily; the request log
  after 30 days.
- **Erasure**: `POST /api/v1/recommendations/erasures {users:[…], items:[…]}` deletes a pseudonym's events and profile,
  or an item with its events — a former product sends it when an account is deleted or a video leaves discovery.
- Purpose: ranking and creator analytics only — never training of a shared model, never resold, never joined with
  another tenant.

### 4. Retrieval and ranking — transparent first

**User profile**: the decayed, weighted mean of the item vectors a user interacted with —
`w(kind) · 2^(−age/halfLife)` (negative weights for `SKIP` and `REPORT`), recomputed when their events arrive, stored in
`reco_user_profile`.

**Candidates** (each tagged with its source, then merged):

1. **ANN**: pgvector HNSW (cosine) nearest items to the user profile;
2. **co-engagement**: items positively engaged by users who engaged the same items ("people who watched X…"), computed
   in SQL on read — a nightly table is deferred until a query plan says so;
3. **fresh**: the newest items;
4. **follows**: recent items of followed creators;
5. **popular**: positive events of the last week, decayed.

Items the user already engaged, skipped or reported are excluded. **a former product's access rules are a former product's**: it only
sends discoverable items (and withdraws the rest), and it re-filters every answer through its own discovery query
before showing it — Orazaka never decides who may see what.

**Ranking** — a weighted score, every weight a **setting** (§5), every term returned as a **reason**:
`score = similarity·wSim + coEngagement·wCo + freshness·wFresh + followed·wFollow + popularity·wPop`.
**Re-ranking**: MMR (`λ·score − (1−λ)·max cos(item, picked)`) and a **creator cap** per page.
**Cold start**: no profile → fresh + popular through the same re-ranker.

### 5. Parameters are data

`reco_settings` (per tenant, **versioned**: a new version is a new row with a reason; the newest active one is read,
cached one minute; version 1 seeded by the migration; bounds checked in code): `enabled`, the five weights, `mmrLambda`,
`creatorCap`, `halfLifeHours`, the event-kind weights, `candidatePool`, `retentionDays`. On a former product's side the shelves are
behind its own setting (`recommendations.enabled`, versioned, off by default) — the switch is the product's.

### 6. Serving contract (v1)

| Method · path | Scope | What |
|---|---|---|
| `POST /api/v1/recommendations/events` | `reco:sync` | ≤ 500 events, idempotent by `id` → `{accepted, duplicates}` |
| `POST /api/v1/recommendations/items` | `reco:sync` | ≤ 100 items upserted (`id, creator, title, description, tags, language, durationSeconds, publishedAt`) — embedded when their text hash changed |
| `POST /api/v1/recommendations/erasures` | `reco:sync` | users and/or items forgotten |
| `GET /api/v1/recommendations/for-you?user=&limit=&exclude=` | `reco:read` | `{requestId, strategy, items:[{id, score, reasons}]}` |
| `GET /api/v1/recommendations/similar?item=&limit=` | `reco:read` | items nearest to an item, MMR + creator cap |
| `GET /api/v1/recommendations/insights?creator=` | `reco:read` | creator analytics v1 (§7) |

Every answer carries a `requestId`, also in the header `X-Orazaka-Request-Id` and in one log line
(`recommendation.served requestId=… tenant=… strategy=… candidates=… returned=… ms=…` — ids and counts, never a title).
The **contract test** is a recorded fixture (`recommendations-contract.json`), kept identical in both repositories: the
knowledge service's test checks it parses and renders the same shapes; a former product's client test parses it.

**a former product's side**: an **outbox** table written in the same transaction as the interaction, drained by a background
loop (`FOR UPDATE SKIP LOCKED`, batches, exponential backoff, at-least-once — no broker); an item **reconciler** (the
discoverable videos whose text hash changed are upserted, the ones that left discovery erased); the shelves call Orazaka
server-side with a short timeout behind the existing **circuit breaker** (`lib/orazaka.ts`) and fall back to trending /
tags — a slow or absent engine never empties a page.

### 7. Creator analytics v1

From the events Orazaka already holds, per creator: per video positive-event rate and engagement counts, the tags whose
videos perform best, the hour of the week when the creator's audience engages, and "your audience also watches"
(co-engaged creators, counts only). Retention curves need watch-time events (§ Deferred).

## Deferred — and what would bring each back

| Deferred | Until |
|---|---|
| **Learning-to-rank** (LightGBM / XGBoost on logged outcomes) | ≥ ~10 k served impressions with outcomes (`reco_request` log + click/watch events) — then offline NDCG must beat the weighted score before it replaces it |
| **Keyframes** (vision model) and **transcript** (Whisper) in the item vector | the `video-understanding` Studio of the `recommendations` pack: a vision model on the dev catalogue (local today: Ollama `llava` on the Mac) and keyframe URLs from a former product's CDN; until then the item vector is text only |
| Safety labels → moderation assist queue | the same Studio; never an automatic takedown |
| `/next` (up next) and `/search` (hybrid BM25 + vector) | a former product already fuses full-text and meaning locally (RRF); `/next` = `similar` blended with for-you once watch-time exists |
| Watch-time % and `SKIP` from the player | a player progress beacon in a former product (web and mobile) |
| Nightly co-engagement table, A/B buckets, offline recall@k / NDCG dashboards | data volume: the on-read SQL is fine below ~1 M events per tenant |
| Title / description / tag **suggestions** for creators | a Studio of the same pack (chat completion), approved by the creator |

## Consequences

- One more JVM in the dev `core` container (≈ 200 MB resident): measured after deploy; `basic-m` (+20 $) remains the
  lever and needs Oussama's yes.
- The recommender is **explainable** from day one: each item says why it is there, each weight is a row with a reason.
- A second product (a former product, Yomizaka) gets recommendations with a key and its own settings — no code names a product.

## Amendment (2026-10-17) — the pack is `data-analytics`

The `recommendations` pack named above ships as **`data-analytics`** ("Recommendations & insights"), the first pack on
the Data & Analytics shelf (orazaka-packs#16, RFC orazaka#174): the shelf will also carry the analytics and data-driven
UI Studios, and a pack key is a primary key in three databases, so it is named once for what it will hold. The serving
contract of §6 is unchanged; the manifest declares it under `requires.api` (service, scopes, exact routes), kept
identical to the edge's `ApiKeyScopes` by `tests/data-analytics.test.mjs`. The two deferred Studios of the table above
— keyframes (`video-understanding`) and title / tag suggestions (`creator-suggestions`) — ship as blueprints over the
engine's vision and chat capabilities; transcripts (Whisper) stay deferred.
