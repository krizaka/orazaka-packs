# bill96-french-first

French-first documents for a Québec business (Bill 96), prepared on the client's own Orazaka: every Québec SME and every company
selling into Québec needs it every week, and generic machine translation misses Québec terminology and the legal register. Category
**Business & compliance** (language).

These are **matrices for extracting information from documents and parameterizable technology templates**, technical tools validated
by the client's legal counsel. **Not a certified translation**: every output opens with the sentence that says so and asks for a
professional review, above all for a legal document.

| Studio | Does |
| :--- | :--- |
| `french-version` | A contract, policy, terms or product sheet in French, in Québec usage; a table of the terms chosen with their source; the doubtful passages flagged. |
| `bilingual-consistency-check` | Compares an English and a French version: differences in meaning, numbers, dates, obligations, omissions, with a severity; says which section to review first; never decides which version prevails. |
| `french-first-copy` | Site and product copy turned into French-first copy that keeps the brand voice, the English equivalent kept right after. |
| `firm-glossary` | Builds and extends the firm's own FR/EN glossary from its documents, in a plain « English \| French \| Source \| Note » form the other Studios take as their `glossary` input. |

## Guardrails

- Terminology sources are named (the OQLF's recommended usage and its Grand dictionnaire terminologique where one applies, otherwise
  « usage courant »); a legal term is **never invented** — without an established Québec term the source term stays in brackets and
  the passage is flagged.
- Statutes are referred to by name, never quoted (`sources.json`; no text pinned, orazaka#393). The references await the client's
  counsel (`verifiedBy: null`; krizaka/.github#22).
- `regulatoryClass: SENSITIVE` and a scope guard: certified or sworn translation, legal advice and any guarantee of compliance are refused.
- Documents stay home: the pack runs on the client's Orazaka.

## Tests

`tests/bill96-french-first.test.mjs` (manifest, the not-certified sentence in every prompt, terminology and invention rules, glossary
reuse, wording) and `tests/golden/` (three fictional cases per Studio).
