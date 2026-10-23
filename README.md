<!-- krizaka-header -->
<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/krizaka/.github/main/profile/assets/orazaka-dark.svg">
  <img src="https://raw.githubusercontent.com/krizaka/.github/main/profile/assets/orazaka-light.svg" alt="Orazaka" width="96">
</picture>

# Orazaka Packs

**The AI that never leaves home.**

Reference packs for the Orazaka Studio marketplace (document validation, media, prospection, real-estate, wellbeing…) and the pack manifest schema.

[![CI](https://github.com/krizaka/orazaka-packs/actions/workflows/ci.yml/badge.svg)](https://github.com/krizaka/orazaka-packs/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/krizaka/orazaka-packs/badge)](https://scorecard.dev/viewer/?uri=github.com/krizaka/orazaka-packs)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Orazaka](https://img.shields.io/badge/part%20of-Orazaka-f67e23)](https://github.com/krizaka/orazaka#repositories)
[![Docs](https://img.shields.io/badge/docs-krizaka.com-f67e23)](https://www.krizaka.com/en/products/orazaka)

[Documentation](https://www.krizaka.com/en/products/orazaka) · [Website](https://www.krizaka.com) · [Krizaka on GitHub](https://github.com/krizaka)

</div>
<!-- /krizaka-header -->

**Layer:** Content · **Version:** `1.0.0-SNAPSHOT` · **License:** Apache-2.0 ·
part of the [Orazaka platform](https://github.com/krizaka/orazaka) by [Krizaka](https://krizaka.com)

## What it provides

Reference **packs** for the Orazaka Studio marketplace. A pack is a directory with a `pack.yaml`
manifest validated against [`pack.schema.json`](pack.schema.json): i18n, studios (semver'd blueprint
DAGs) and, optionally, its own worker.

| Pack | Content |
|:---|:---|
| `data-analytics` | Recommendations & insights — the recommender of ADR-078 (API scopes `reco:sync` / `reco:read`) and product analytics (ADR-081), served by the knowledge service; Data-driven UI (ADR-082), Video understanding and Creator suggestions Studios |
| `document-validation` | Document Verification — Compliance Check (rules, sources, passages) and Document Authenticity (a PDF's signals of tampering), with its worker |
| `echo-toolkit` | The Tier-W reference used by the platform tests — `DRAFT`, never on the marketplace shelf |
| `orazaka-media` | Media generation studios |
| `outbound-prospection` | Prospection workflows |
| `realestate-studio` | Real-estate reels |
| `trade-showcase` | Trade showcase studio |
| `wellbeing` | Wellbeing — guided journaling, session preparation, mood tracking (`REGULATED`; never "therapy": what a person brings to a professional, not a care); `wellbeing/listening/` holds the listening moment's data — presences, voices, the ear — and the risk fixtures the crisis guard is tested with) |

```bash
orazaka pack validate ./orazaka-packs/<bundle> --offline
orazaka pack install --all ./orazaka-packs
```

See [CONTRIBUTING.md](CONTRIBUTING.md) to write a pack.

## Position in the platform

| | |
|:---|:---|
| Depends on | _none — this repository is a root of the dependency graph._ |
| Used by | _no other Orazaka repository._ |
| Workspace path | `orazaka-packs` |

## Build

With Node.js 22, run the repository's validation suite:

```bash
npm ci
npm test
```

On every pull request, CI runs this suite, including `tests/schema.test.mjs`: every
`*/pack.yaml` (including DRAFT packs) is parsed as YAML and validated against the complete
[`pack.schema.json`](pack.schema.json) using Ajv's JSON Schema 2020-12 validator and
`ajv-formats`. Failures name the manifest and the JSON Pointer path of each schema violation;
malformed YAML is rejected too. No platform services or network access are needed after
installing dependencies.

Platform validation remains complementary: `orazaka pack validate` (shape, offline) and the
Studio service's catalogue/coherence tests inside the
[Orazaka workspace](https://github.com/krizaka/orazaka) check runtime integration, blueprint
links and referenced i18n files beyond the manifest schema.

## Governance

This repository follows the Orazaka governance contract — [AGENTS.md](https://github.com/krizaka/orazaka/blob/main/AGENTS.md)
in the workspace is normative; the local [AGENTS.md](AGENTS.md) only scopes it to this repository.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

---

<sub>A Krizaka product · [krizaka.com](https://www.krizaka.com) · Apache-2.0</sub>
