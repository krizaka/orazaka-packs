# Data & Analytics — Recommendations & insights

The first pack on the **Data & Analytics** shelf ([orazaka-packs#16](https://github.com/krizaka/orazaka-packs/issues/16),
[RFC #174](https://github.com/krizaka/orazaka/discussions/174)). It packages the recommender of
[ADR-078](../docs/adr/ADR-078-recommendations.md): a product sends what its users do, Orazaka serves a feed per person
and analytics per creator, and every item it returns says why it is there.

## What you get

| Part | Where it runs | How you reach it |
|---|---|---|
| **Serving** — events, items, erasures in; for-you, similar, insights out | `orazaka-knowledge-service` (pgvector), synchronous, < 150 ms p95 | your product's **service key** with the scopes below, server to server |
| **Video understanding** (Studio) | a run: a keyframe through the vision model, then a JSON reading — summary, topics, tags, language, safety labels | the Studios tab, or a run through the API |
| **Creator suggestions** (Studio) | a run: three titles, a description and tags from the creator's own words | the Studios tab |

Pricing: 49 $ CA, 300 credits included (the Studios' runs are metered; the serving API is covered by the key's daily
quota).

## API scopes

A scope the edge does not know grants nothing; a key with scopes may only make the exact requests they name
(`ApiKeyScopes` in orazaka-edge — `tests/data-analytics.test.mjs` keeps this manifest identical to it).

| Scope | Requests |
|---|---|
| `reco:sync` | `POST /api/v1/recommendations/events` (≤ 500, idempotent by `id`) · `POST /api/v1/recommendations/items` (≤ 100) · `POST /api/v1/recommendations/erasures` |
| `reco:read` | `GET /api/v1/recommendations/for-you?user=&limit=&exclude=` · `GET /api/v1/recommendations/similar?item=&limit=` · `GET /api/v1/recommendations/insights?creator=` |

The tenant is the service account the key belongs to (`svc_<product>`): every row carries it and no query reads across
tenants.

## Personal data (Loi 25)

- **Users are pseudonyms.** The product sends `HMAC-SHA256(AI_PSEUDONYM_KEY, userId)` — a key only the product holds —
  never its user id, an e-mail, a name or a message. Orazaka cannot reverse a pseudonym.
- **Purpose-limited.** Ranking and creator analytics for that tenant only: never training a shared model, never joined
  with another tenant, never resold.
- **Retention.** Events older than the tenant's `retentionDays` setting (default 180, a versioned database row) are
  purged daily; the request log after 30 days.
- **Erasure.** `POST /api/v1/recommendations/erasures {users:[…], items:[…]}` deletes a pseudonym's events and profile,
  or an item with its events — the product sends it when an account is deleted or an item leaves discovery.
- **Access stays the product's.** It only sends items its users may discover, and re-filters every answer through its
  own rules before showing it.

## Using it from a product

1. Create the service account and its key with the scopes above (`scripts/dev-deploy.mjs service-account` in the
   workspace), store it as a secret (`AI_ENGINE_API_KEY`), and a pseudonym key (`AI_PSEUDONYM_KEY`).
2. Write interactions to an **outbox** in the same transaction as the interaction; drain it in batches to `/events`
   (at-least-once — duplicates are ignored by `id`).
3. Upsert the discoverable items to `/items` when their text changes; erase the ones that leave discovery.
4. Read `/for-you` server-side with a short timeout behind a circuit breaker, and fall back to your own trending list —
   a slow engine never empties a page.

Orochia is the first consumer (krizaka/orochia#226): For you, More like this, and the creator's `/insights` page.
