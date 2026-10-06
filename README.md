# Orazaka Packs

> Reference packs for the Orazaka Studio marketplace (document validation, media, prospection, real-estate, wellbeing…) and the pack manifest schema.

**Layer:** Content · **Version:** `1.0.0-SNAPSHOT` · **License:** Apache-2.0 ·
part of the [Orazaka platform](https://github.com/krizaka/orazaka) by [Krizaka](https://krizaka.com)

## What it provides

Reference **packs** for the Orazaka Studio marketplace. A pack is a directory with a `pack.yaml`
manifest validated against [`pack.schema.json`](pack.schema.json): i18n, studios (semver'd blueprint
DAGs) and, optionally, its own worker.

| Pack | Content |
|:---|:---|
| `document-validation` | Rule engine + worker for document checks |
| `echo-toolkit` | Minimal toolkit used by the platform tests |
| `orazaka-media` | Media generation studios |
| `outbound-prospection` | Prospection workflows |
| `realestate-studio` | Real-estate reels |
| `trade-showcase` | Trade showcase studio |
| `wellbeing` | Wellbeing (sensitive / regulated pack example) |

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

Packs are validated by the platform: `orazaka pack validate` (shape, offline) and the Studio
service's catalogue tests inside the [Orazaka workspace](https://github.com/krizaka/orazaka).

## Governance

This repository follows the Orazaka governance contract — [AGENTS.md](https://github.com/krizaka/orazaka/blob/main/AGENTS.md)
in the workspace is normative; the local [AGENTS.md](AGENTS.md) only scopes it to this repository.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
