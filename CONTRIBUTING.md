# Writing an Orazaka pack

A pack is a **directory**. It does not live in this repository, it is not compiled, and installing
one changes no code. If you can write YAML and JSON, you can ship a Studio.

This guide was written by installing a pack from outside the repository and writing down every
place it went wrong. Each **⚠** below is a mistake that actually happened, in the order it happened.

---

## 1. The shape

```
my-pack/
  pack.yaml                          # the manifest — the only required file
  i18n/
    en.yaml                          # one file per locale, discovered by convention
    fr.yaml
  studios/
    my-studio/
      blueprint.json                 # the workflow
  worker/                            # Tier-W only: your worker process
    worker.yaml
    …
```

Nothing here names a path inside Orazaka. Put the directory anywhere you like — `~/packs/my-pack`
is fine.

## 2. The manifest

```yaml
apiVersion: orazaka.dev/v1
key: my-pack                          # kebab-case, globally unique
version: 1.0.0                        # semver
tier: DATA                            # DATA | CAPABILITY | WORKER
distribution: OSS                     # OSS | CLOUD | PARTNER
regulatoryClass: STANDARD             # STANDARD | SENSITIVE | REGULATED

requires:
  capabilities: []                    # empty for DATA: you reuse orazaka.core.*

catalog:
  categoryKey: business
  iconKey: sparkles

pricing:
  priceCents: 0
  includedCredits: 0

studios:
  - key: my-studio
    profession: general
    iconKey: studio
    pricing: FREE                     # FREE | INCLUDED | PAID
    entitlementKey: studio.my-studio  # by convention studio.<key>
    blueprint: studios/my-studio/blueprint.json
```

> ⚠ **`tier` is `DATA`, not `D`.** The tiers are spelled out: `DATA`, `CAPABILITY`, `WORKER`.
>
> ⚠ **`regulatoryClass` has no `NONE`.** The floor is `STANDARD`.
>
> ⚠ **`blueprint` is a path, not an inline object.** The manifest names files; it does not embed
> them.
>
> ⚠ **There is no `i18n:` key.** The `i18n/` directory is found by convention. The manifest rejects
> unknown properties outright, so an invented key fails validation rather than being ignored.
>
> ⚠ **`pricing` is `priceCents` + `includedCredits`.** Not `bundledCredits`.

Everything else is optional and has a default. `orazaka pack validate` names the exact line when
something is wrong, so run it before you run anything else.

### 2.1 Declaring `SENSITIVE`

Raise `regulatoryClass` above `STANDARD` and the engine applies four controls to every run of your
pack. You do not implement them and you cannot opt out of them; you declare one thing, and the
platform owes you the rest.

```yaml
regulatoryClass: SENSITIVE

scopeGuard:                           # REQUIRED once regulatoryClass is not STANDARD
  refusedTerms:                       # the domain your pack does NOT serve
    - conseil juridique
    - avocat
  refusal: >-                         # what a refused turn is told, verbatim
    Je rédige et relis des documents. Je ne donne pas de conseil juridique —
    pour cela, adressez-vous à un professionnel du droit.
```

What you get:

| Control | What the engine does | What you declare |
|:---|:---|:---|
| Data class | every run, input and artefact is stamped `SENSITIVE`; it is excluded from analytics and never used for training | nothing |
| Shortened retention | runs are purged after 30 days instead of the platform's 180 | nothing; an installation may set `retentionDays` in its config to go **lower**, never higher |
| Audit log | `RUN_STARTED` and a terminal row per run, append-only, `UPDATE` and `DELETE` refused by the database | nothing |
| Scope guard | a turn naming a refused term is stopped before any inference, and answered with your sentence | `scopeGuard` |

The publish gate is code, not a checklist: a pack that declares a regulatory class above `STANDARD`
without a `scopeGuard` **fails to install**, naming the missing key. A second condition is not yours
to satisfy: your pack is also refused by a **platform** that stores assets in the clear. That is the
platform operator's declaration, not yours, and the error names the key they must set. On a local
developer machine it is already satisfied. A pack that refuses nothing has
not stated a domain, and a legal-drafting Studio with no scope guard is one that answers legal
questions.

`refusedTerms` is matched on whole words, accent- and case-insensitively, against the turn as the
user wrote it. Name the *domain you decline*, not every phrasing of it — the list is a declaration,
not a filter, and the engine never adds terms of its own.

## 3. The blueprint

```json
{
  "version": "1.0.0",
  "status": "PUBLISHED",
  "estimatedCredits": 40,
  "createdBy": "you",
  "definition": {
    "studioKey": "my-studio",
    "version": "1.0.0",
    "steps": [
      { "id": "brief", "kind": "CAPABILITY",
        "featureKey": "orazaka.core.chat.completion",
        "dependsOn": [],
        "inputs": { "prompt": "Write about {{inputs.subject}}." },
        "out": "brief", "onError": "FAIL", "maxAttempts": 1, "timeout": "PT2M" }
    ],
    "outputs": [
      { "key": "brief", "label": "Your brief", "from": "{{steps.brief.content}}", "type": "TEXT" }
    ]
  },
  "inputSchema": { "type": "object", "required": ["subject"],
                   "properties": { "subject": { "type": "string", "title": "Subject" } } },
  "configSchema": { "type": "object", "properties": {} }
}
```

> ⚠ **An output needs `label` and `type`, not just `key` and `from`.** A missing label is a `400`
> on the first run, not at install.

**Step kinds**: `CAPABILITY` (runs a model), `TRANSFORM` (reshapes values), `APPROVAL` (parks for a
human), `CONNECTOR` (calls out), `KNOWLEDGE`. **`onError`**: `FAIL` | `SKIP` | `RETRY` — and a
`SKIP` needs a written `skipRationale`, which a fitness function checks.

**Templates.** `{{inputs.x}}`, `{{config.x}}`, `{{steps.<out>}}`, `{{item}}` inside a `forEach`. A
template that is *exactly one placeholder* over a list stays a list; anywhere else it renders as
text. That is what lets a step take a list of asset ids.

**`estimatedCredits` is a hold, not a price.** Size it for your blueprint's *worst legal input* —
the maximum `forEach` fan-out, every optional step firing. It is released, not charged: a run
settles what it measured.

## 4. Install it

```bash
orazaka pack validate ~/packs/my-pack     # shape, then the platform's own checks
orazaka pack install  ~/packs/my-pack
```

`validate` checks your manifest against **the platform's** schema — the one the CLI carries, not
one you ship — and then asks the running platform whether every `featureKey` you name resolves.

> ⚠ **A published version is immutable.** Re-installing `1.0.0` after editing the blueprint does
> nothing and reports success. Bump the version. Editing means minting a version (ADR-034 §4).

## 5. Make it runnable

Installing puts a Studio in the catalogue; it does not entitle anyone to it. Your pack's
`entitlementKey` is granted to whoever holds the pack:

```bash
curl -X POST localhost:8088/api/v1/billing/pack-subscriptions/me/my-pack \
     -H "Authorization: Bearer $TOKEN"
```

> ⚠ **The entitlement cache is 60 seconds.** A pack subscription does not evict it today, so a
> Studio you just bought can stay `REQUIRES_PLAN` for up to a minute. Wait, do not re-install.

Plans are the platform's commercial offer, so bundling your Studio into `free`/`premium` is a
deployment decision, not something a pack can do to itself.

## 6. Tier-W: bringing your own worker

Declare it in the manifest —

```yaml
requires:
  capabilities:
    - key: orazaka.echo.text.reverse   # your namespace, your key
      label: Reverse text
      routingKey: job.echo.reverse     # job.<family>.<action>
      handlerKey: echo.reverse
      billableCapability: CHAT
      billableUnit: KILOTOKEN
  workers:
    - name: orazaka-worker-echo
      bindings: ["job.echo.*"]
```

— and write a process that honours [`docs/WORKER_PROTOCOL.md`](docs/WORKER_PROTOCOL.md). **The
broker is the plugin boundary**: your worker links no Orazaka library and implements no interface.
It must

1. **declare its own topology** — exchange, queue, bindings, DLQ — so installing your pack needs no
   change to the platform's broker configuration;
2. **decide from the routing key**, never from a capability name;
3. answer `job.{jobId}.done` or `job.{jobId}.error` on `orazaka.events`;
4. report **measurements** (`tokens`, `frames`, `gpuSeconds`, …), never units or prices;
5. be **idempotent by `messageId`** — delivery is at-least-once.

> ⚠ **The success key is `result`, not `output`.** Getting it wrong gives you a `SUCCEEDED` run
> with an empty output and no error anywhere.

The worked example is [`orazaka-packs/echo-toolkit`](orazaka-packs/echo-toolkit) — a manifest, a
Studio and a ~120-line Python worker that reverses a string. It is deliberately trivial: everything
in it that is not about the extension point would hide the extension point.

### 6.1 Three things that would otherwise cost you an hour

Found by shipping `document-validation` (ADR-052 §6), and none of them visible from reading the code.

**The broker credentials are the `RABBITMQ_*` family** — `RABBITMQ_HOST`, `RABBITMQ_PORT`,
`RABBITMQ_USER`, `RABBITMQ_PASS`. They used to have two names each depending on how your `.env`
was generated, and picking the wrong one got you `ACCESS_REFUSED (403)` with no diagnosis; ADR-053
§8 settled it. The old `SPRING_RABBITMQ_*` and `RABBITMQ_PASSWORD` names are still read for one
version, with a warning naming what to rename — so an older `.env` keeps working and tells you.

**Re-installing at the same blueprint version keeps the stored one.** A `PUBLISHED` blueprint
version is immutable by design — shipping a change means shipping a new version. `pack install`
still says *"Installed"*, and your edit is not what runs. Bump `version` in the blueprint (and in
`definition.version`) every time you change it. The installer logs what it kept, so check the
studio service's log if a change seems to have no effect.

**`{{steps.out}}` is for prompts, `{{steps.out.field}}` is for data.** A whole-step reference
interpolates the value's `toString` — fine inside a prompt, useless to a JSON parser. If your step
must hand structured data to a later step, emit it as an explicit JSON string field and reference
that field.

## 7. Where packs come from

One property decides, and it is the only difference between an open-source deployment and a hosted
one:

```bash
ORAZAKA_PACKS_SOURCES=orazaka-packs                       # OSS: this repo's reference packs
ORAZAKA_PACKS_SOURCES=orazaka-packs,~/packs               # plus your own
ORAZAKA_PACKS_SOURCES=~/packs,registry:https://…          # plus a hosted registry
```

`orazaka pack list` shows the configured sources and what they offer. A registry source is listed
and marked unavailable on a local deployment rather than silently ignored.

## 8. Licence

Your pack is yours. See [docs/LICENSING.md](docs/LICENSING.md).
