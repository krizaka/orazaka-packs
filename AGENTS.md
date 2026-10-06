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
