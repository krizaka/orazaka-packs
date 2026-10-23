# orazaka-packs — Governance scope (agent-neutral)

> This repository is one component of the **Orazaka platform**. The normative contract is
> [`AGENTS.md`](https://github.com/krizaka/orazaka/blob/main/AGENTS.md) at the root of the Orazaka workspace
> ([`krizaka/orazaka`](https://github.com/krizaka/orazaka)), together with its `.agent/rules/*`. When this repository
> is cloned inside the workspace (`orazaka-packs`), that contract is loaded first and applies
> without exception. **No rule lives here** — this file only scopes it.

## Scope of this repository

- **Role:** Reference packs for the Orazaka Studio marketplace (document validation, media, prospection, real-estate, wellbeing…) and the pack manifest schema.
- **Layer:** Content
- **Depends on:** nothing — never on another repository's Tier-3 implementation (AGENTS.md §2, [SEAM-002]).
- **Workspace path:** `orazaka-packs`

## Definition of done

1. Every `pack.yaml` validates against `pack.schema.json` (`orazaka pack validate --offline`).
2. The workspace build is green (pack coherence rules read this repository).
3. A new or changed pack ships with its tests — its schema and coherence rules, and the end-to-end journey that
   runs it; a fix starts with a failing test. CI runs them and must be green; no test = not done (workspace
   [`AGENTS.md` §9](https://github.com/krizaka/orazaka/blob/main/AGENTS.md#9-testing)).

## Before you open or update a pull request (coding agents)

These are the defects code review found most often on 2026-10-23. Check them yourself before you open or update a pull request:
1. **Checks:** run the repository's full check (lint, typecheck, tests, build) and fix it. Never push a red check.
2. **Concurrency:** any « count then insert » or « check then write » runs in one transaction with a lock, and has a concurrency test.
3. **One gate:** a rule (limit, permission, validation) is enforced in the service, so no route can skip it. Test every route.
4. **Errors:** a cleanup (ROLLBACK, DROP, close) never masks the original error. Rethrow it, or throw an `AggregateError` with the original first.
5. **Validation:** validate the original input, never a truncated or pre-trimmed copy. Server and client reject the same inputs.
6. **Accessibility:**
   - every control has a unique label, and FR/EN pairs say their language;
   - focus rings are never clipped by `overflow`;
   - text never overflows its box at 360 px.
7. **Naming:** environment variables follow `<CONTEXT>_<THING>` (`APP_`, `DATABASE_`, `AUTH_`, `MEDIA_`, `MAIL_`, `PAYMENTS_`, `AI_`…) and are declared once.
8. **Words:** every user-facing string is in the FR and EN messages, and no colour is hard-coded.
9. **Review threads:** answer every one. Fix it test-first, or reply with the reason, then resolve it.
