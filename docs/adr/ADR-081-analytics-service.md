# ADR-081 — Product analytics on Orazaka: events in, KPIs · cohorts · funnels · top items out, per tenant

- **Status:** Accepted (2026-10-17)
- **RFC:** [krizaka/orazaka discussion #174](https://github.com/krizaka/orazaka/discussions/174) — consumers:
  krizaka/orochia#226 (creator `/insights`), krizaka/yasakia#86 (admin analytics)
- **Builds on:** [ADR-078](ADR-078-recommendations.md) (the recommender, its tenant key, pseudonyms and settings)
- **Numbering:** the Orazaka ADR sequence (ADR-079 automations and ADR-080 cinema are open in krizaka/orazaka); recorded
  here, like ADR-078, because it is the serving half of the `data-analytics` pack.

## Context

Products need to know what their users do, and they must not each build an analytics stack: the rule of the house is
that a product's intelligence runs on Orazaka. Orochia already sends its recommender events (`VIEW` with `watchedPct`,
`LIKE`, `TIP`, `SKIP`…) and reads per-creator insights (ADR-078 §7). Yasakia waits for a place to send what is not a
recommendation at all — a voice talk, an answered batch, an intro (yasakia#86). The RFC asks for KPIs, cohorts, funnels
and top items, multi-tenant, Loi 25-compliant, and cheap. The dev budget allows no new recurring cost without a written
yes, and the dev PostgreSQL cluster allows **22 connections** in all.

## Decision

### 1. Where it lives — a feature of `orazaka-knowledge-service`, not a new service

| Option | Cost | Connections | Verdict |
|---|---|---|---|
| New `orazaka-analytics-service` (JVM, its own DB) | +1 JVM (≈ 200 MB in the dev `core` container) or +5 $/month for a component, a new role and DB | +5 (pool) of 22 | refused — a second copy of what knowledge already does |
| A columnar store (ClickHouse, DuckDB server, Timescale) | a new stateful service | +n | refused — unmeasured need; nothing here is beyond PostgreSQL at our volume |
| **Feature `analytics` of the knowledge service, same `orazaka_knowledge_db`** | 0 $, 0 JVM | **0** (same pool of 5) | **chosen** |

The knowledge context already is "a tenant's data, read back for that tenant", and it already holds the recommender's
events. Analytics reads them where they are: one write, two reads.

### 2. Events — one table for what is not a recommendation, one view over both

- **`analytics_event`** (`tenant_id, event_id, subject_id, kind, item_id?, owner_id?, value?, occurred_at, received_at`),
  idempotent by `(tenant_id, event_id)`. `subject_id` is a **pseudonym** (§4); `item_id` / `owner_id` are the product's
  public ids (a video and its creator; nothing for a talk); `value` is the measure of the kind (seconds talked, cents
  tipped, percent watched).
- **Kinds are data**: `analytics_event_kind` (`tenant_id` or `'*'`, `kind`, `unit` — enum `none · percent · seconds ·
  cents · count`, `source` — enum `analytics · recommender`, `description`). Seeded for every tenant: the recommender's
  kinds (`view` in percent, `like`, `save`, `share`, `tip`, `unlock`, `follow`, `unfollow`, `skip`, `report`) and
  `talk` (seconds), `batch_open`, `batch_answer`, `intro_start`, `report_filed`, `session_start`, `purchase` (cents). A
  tenant's own kind is a row, not a release.
- A kind whose source is `recommender` is **refused** at `POST /api/v1/analytics/events` with the endpoint to use
  instead: a product sends each event once, so nothing is counted twice.
- **`analytics_event_all`** is a view: `analytics_event` ∪ `reco_event` (kind lower-cased, `watched_pct` as the value,
  the item's creator as the owner). Every insight reads the view, so Orochia's existing outbox feeds analytics with **no
  change on its side**, history included.

### 3. Insights — computed on read, in SQL, bounded

| Method · path | Scope | What |
|---|---|---|
| `POST /api/v1/analytics/events` | `analytics:sync` | ≤ 500 events, idempotent by `id` → `{accepted, duplicates}`; an unknown or recommender kind → 400 naming it |
| `POST /api/v1/analytics/erasures` | `analytics:sync` | `{subjects:[…], items:[…]}` — forgets them in **both** tables (analytics and recommender) |
| `GET /api/v1/analytics/insights?from=&to=&owner=` | `analytics:read` | KPIs with the previous period, a daily series, top items, weekly cohorts |
| `GET /api/v1/analytics/funnel?steps=a,b,c&from=&to=&owner=` | `analytics:read` | ordered funnel: subjects at each step within the window after the previous one |

- **KPIs**: events, active subjects, and per kind its count, distinct subjects and value sum / mean — for `[from, to)`
  and the period of the same length before it, so each figure carries its delta.
- **Series**: per day, active subjects and events per kind (the chart).
- **Top items**: by distinct subjects engaging positively (the kinds marked positive in the settings), with views and
  the mean value of `view` (watched %).
- **Cohorts**: subjects grouped by the ISO week they were first seen, and the share still active each following week
  (up to `cohortWeeks`).
- **Funnel**: 2 to 6 kinds; a subject reaches step *k* when it does kind *k* after its step *k−1*, within
  `funnelWindowHours`.
- `owner=` narrows everything to one owner's items (a creator's own analytics); without it the tenant's whole product.
- **Bounds**: the range is at most `maxRangeDays`; queries hit `(tenant_id, occurred_at)` indexes on both tables. On-read
  SQL is fine below ~1 M events per tenant; a nightly daily-rollup table comes back with a query plan that needs it.

### 4. Personal data (Loi 25)

- **Pseudonymous only.** The product sends `HMAC-SHA256(AI_PSEUDONYM_KEY, userId)` (Orochia already does); the service
  refuses a subject that is not 16–128 characters of `[A-Za-z0-9_-]`, so an e-mail or a name never fits. Orazaka holds
  no key to reverse it.
- **k-anonymity.** No figure is returned for fewer than `minAudience` distinct subjects (default 3): a range, an owner, a
  cohort, a top item or a funnel step under the threshold is reported as `suppressed`, never as a small number.
- **Retention.** `analytics_event` rows older than the tenant's `retentionDays` (default 180) are purged daily
  (03:27 UTC); recommender events keep their own retention (ADR-078 §3).
- **Erasure** propagates to both tables (§3). **Purpose**: the tenant's own product analytics — never joined across
  tenants, never used to train a shared model, never resold.

### 5. Parameters are data

`analytics_settings` (per tenant, versioned like `reco_settings`: a new version is a new row with a reason; version 1
seeded by the migration; read through a one-minute cache; bounds checked in code): `retentionDays`, `minAudience`,
`maxRangeDays` (366), `cohortWeeks` (8), `funnelWindowHours` (168), `topItems` (10), `positiveKinds`.

### 6. Scopes and the pack

Two new key scopes at the edge (`ApiKeyScopes`, exact method + path, fail closed): `analytics:sync` and
`analytics:read`; `/api/v1/analytics` routes to the knowledge service. `reco:*` stay as they are (Orochia's live key);
the RFC's unification is not worth breaking a working contract. The `data-analytics` pack declares the four routes
under `requires.api`, tested identical to the edge.

## Consequences

- **Cost: 0 $/month, 0 new connection, 0 new JVM.** Storage ≈ 250 bytes per event with its indexes: one million events
  ≈ 250 MB of the dev cluster's 10 GB; 180-day retention bounds it.
- Orochia's creator page gains KPIs, cohorts and a funnel from events it already sends; watch-time arrives the day its
  player sends `watchedPct` (ADR-078 Deferred), with no change here.
- Yasakia gets a place for its events with a key holding `analytics:sync analytics:read` and nothing else.
- Deferred — and what brings each back: daily rollups (a query over 1 s in the request log), per-tenant custom funnels
  saved as rows (a second consumer asking for one), anomaly detection on report spikes (yasakia#86's safety view, once
  a baseline of weeks exists), geospatial heatmaps (never on precise positions; coarse cells only, with a written
  decision).
