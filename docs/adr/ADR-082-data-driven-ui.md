# ADR-082 — Data-driven UI: models answer with A2UI v0.9 surfaces, rendered by Krizaka UI

- **Status:** Accepted (2026-10-17)
- **Epic:** [krizaka/orazaka#207](https://github.com/krizaka/orazaka/issues/207) (slice 1) — related:
  krizaka/orazaka-web-client#48 (chat streaming), krizaka/krizaka-ui#200 (generative primitives), ADR-079 (actions with
  approval, slice 2), [ADR-081](ADR-081-analytics-service.md) (the analytics a dashboard reads)
- **Numbering:** the Orazaka ADR sequence; recorded here because the Studio that produces these answers is the
  `data-analytics` pack's.

## Context

Assistants now answer with interfaces — a table to sort, a chart, a figure with its trend — not only prose. Orazaka must
do the same with its own catalogue, its own safety rules and on its own infrastructure. A model must **never** answer
with code the client runs (HTML, script, a component it imports): one prompt injection would become a script on a
customer's page. The open options:

| Option | What it is | Verdict |
|---|---|---|
| **A2UI** (Google, v0.9) | A declarative, flat, streamable JSON description of a UI: `createSurface` · `updateComponents` · `updateDataModel` · `deleteSurface`; components as an adjacency list (`id`, `component`, `children` by id); data bound by JSON pointer (`{"path": "/rows"}`); only components of a **catalog the client declares** | **chosen** — a UI *spec*, no code, the catalog is ours |
| **AG-UI** (CopilotKit) | An event protocol between an agent and a front end (run, text, tool and state events over SSE) | not a UI spec; it can carry A2UI later — our chat already streams over SSE, so it adds nothing today |
| **MCP Apps / MCP-UI**, OpenAI Apps SDK | UI resources as HTML served by a tool and run in a sandboxed iframe | refused for model answers — it is code, sandboxed or not; kept in mind for third-party tools |
| Vercel AI SDK generative UI | React components returned by server tool calls | ties the model's output to our React tree and to one framework; no portable spec |

## Decision

### 1. The spec: A2UI v0.9, a strict subset

- Every message is an A2UI v0.9 envelope (`"version": "v0.9"` and exactly one of `createSurface`, `updateComponents`,
  `updateDataModel`, `deleteSurface`). A model writes them as **JSON Lines** inside a fenced block marked `a2ui` in its
  answer; each complete line is one message, so the surface renders while the answer streams.
- `createSurface.catalogId` must be **`krizaka:genui/v1`**; anything else is refused.
- The catalog v1 (the slice-1 subset of orazaka#207): layout `Column`, `Row`; content `Text` (`variant`: body ·
  heading · caption), `Card` (`title`, `child`), `Callout` (`tone`: info · success · warning · danger, `title`, `text`);
  data `Table` (`columns` [{`key`, `label`, `format`?}], `rows` bound to a path), `KpiStat` (`label`, `value`,
  `previous`?, `format`?, `good`?), `ChartCard` (`title`, `kind`: line · bar · area · pie, `x`, `series`
  [{`key`, `label`}], `data` bound to a path). Formats are a closed list (number · percent · currency · compact ·
  duration).
- Forms, buttons and actions are **slice 2** (with ADR-079's approval loop); Map, Timeline, MediaGrid slice 4.

### 2. Safety — validated twice, rendered as data

- **Strict validation** of every message, in the renderer (the client) and in the Studio's tests: unknown keys,
  components or catalog refused; ids `[A-Za-z0-9_-]{1,64}`; at most 300 components, depth 12, 1 000 table rows, 50
  series points × 12 series, strings 4 000 characters; children must exist and form a **tree** (a cycle, a component
  under two parents or a missing `root` refuses the surface).
- **Data paths** are JSON pointers whose segments may not be `__proto__`, `prototype` or `constructor`; the data model
  is plain JSON (no function, no class), copied, size-capped.
- **No raw HTML, no script, no URL** in v1: `Text` renders text nodes only (React escapes), no `Image`, no link — a URL
  arrives with slice 4, through an allow-list.
- A message that fails validation is **dropped and reported** (`onError`), the surface keeps what was valid, and the
  chat shows the answer's text (**fallback to markdown**). The renderer never throws into the page.

### 3. Where each piece lives (Krizaka UI placement)

| Piece | Package | Why |
|---|---|---|
| The v0.9 subset: types, the validator, the surface store (apply messages, stream line by line), `GenUiSurface`, the base catalog (`Column`, `Row`, `Text`, `Card`, `Callout`, `Table`) | `@krizaka/ui/genui` | a primitive without product vocabulary (level 1) |
| The data entries `KpiStat`, `ChartCard` | `@krizaka/charts/genui` (`chartsCatalog`) | `@krizaka/charts` depends on `@krizaka/ui`, never the reverse |
| Rendering inside the chat (detect the `a2ui` fence, feed the store as tokens arrive) | `orazaka-web-client` | the chat is the product's |
| Producing the answer | the `data-driven-ui` Studio of the `data-analytics` pack | a metered model run, like every Studio |

### 4. The Studio

`data-driven-ui` (pack `data-analytics`): a CSV (or a JSON export of the product's own analytics — ADR-081 insights)
and a question go to the chat model with the catalog and the rules; it answers with an `a2ui` block (the data
summarised into the data model, never invented: every number must come from the input) and one sentence of prose.
Asking the tenant's analytics directly from the Studio is slice 1b (an analytics read capability with the tenant's own
scope).

## Consequences

- One spec for web now, native (slice 3) and the Mac later — the catalog changes, not the protocol.
- The model can only draw what we ship; a new component is a krizaka-ui release and a catalog version (`krizaka:genui/v2`).
- Cost: zero infrastructure; tokens of the answer (a dashboard is ~1–3 k tokens).
- What would make us revisit: A2UI v1.0 stabilising its action messages (slice 2 aligns with it), or AG-UI becoming the
  transport our clients already speak.

## Proof (2026-10-17, dev)

- Renderer: `@krizaka/ui` 3.22.0 `genui` + `@krizaka/charts` 0.6.0 `genui` (krizaka/krizaka-ui#314); chat:
  krizaka/orazaka-web-client#139; Studio: `data-driven-ui` 1.2.0 (#46, #47, #48), launchable from the chat bar.
- Measured: with the first prompt, the default model wrote objects over several lines and forgot `"component"` — the
  renderer refused the surface and the chat fell back to the text, as designed. The prompt now gives the exact three
  lines and a complete example; a stray closing brace is tolerated (krizaka/krizaka-ui#317).
- Recording: run `186125cd-f9f3-47ed-8976-db52e9ac3d06`, the chat answering with a live dashboard over Orochia's real
  activity — [video](https://krizaka-assets.b-cdn.net/site/products/orazaka/video/genui-chat.fa80de9821.mp4)
  ([webm](https://krizaka-assets.b-cdn.net/site/products/orazaka/video/genui-chat.fe6a22927c.webm)).
