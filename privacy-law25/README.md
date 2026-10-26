# privacy-law25

Privacy governance for a Québec firm (Law 25), prepared on the client's own Orazaka: law and accounting practices, clinics and
agencies that cannot send their files to a US cloud. Category **Business & compliance**.

These are **matrices for extracting information from documents and parameterizable technology templates**, technical tools validated
by the client's legal counsel. They **prepare**; the person in charge of the protection of personal information, or a lawyer,
**validates** — every output begins with that sentence, in the language of the output. Nothing here is legal advice, and nothing is
decided for the person in charge.

| Studio | Prepares | Leaves to the person in charge |
| :--- | :--- | :--- |
| `personal-information-inventory` | A table: kind of information, where, why, who accesses it, retention, what to confirm; then the questions to settle. | Answering the questions. |
| `privacy-impact-assessment` | An EFVP draft: purpose, information, flows and hosting (a communication outside Québec is flagged), risks, mitigations. | The decision, its date and the signature. |
| `confidentiality-incident` | A reading of the three serious-injury criteria, the register entry, and the drafts of the notices when the criteria point that way. | Whether a notice is sent, its date and signature. |
| `privacy-governance-policy` | A public policy in plain language, in French and in English. | Checking every « À confirmer » point. |

## Guardrails

- `regulatoryClass: SENSITIVE` and a scope guard: requests for legal advice, a guarantee of compliance or anything outside privacy
  governance are refused.
- A fact the firm did not give is marked « À confirmer » / « To confirm », never invented.
- **Sources are references, never quoted text** (`sources.json`: the Act, section numbers, the CAI guides). No wording of a Québec
  section is pinned in this public repository (licence question, krizaka/orazaka#393). The references await the client's counsel
  (`verifiedBy: null`; krizaka/.github#22 tracks the lawyer).
- Data never leaves the machine: the pack runs on the client's Orazaka.

## Tests

`tests/privacy-law25.test.mjs` (the manifest, the draft-and-validate sentence in every prompt, decisions left empty, references only,
wording) and `tests/golden/` (three fictional cases per Studio: a firm, a clinic, an agency).
