# business-brief

The writer behind « Le point du lundi » (the duck of the Flock): the weekly brief of a small shop. One Studio today.

## `invitation-writer`

Writes the invitation of a brief action (fill the free slots of the week) in Québec French (OQLF vocabulary) or English, in the shop's
tone, sized for a text message (160 characters), a notification (90) or an email (a subject and about 60 words).

- **Aggregates only.** The inputs are the shop's name, a service and the free slots. There is no field for a client name or a history, and
  the prompt forbids a name, a greeting by name, a reference to a visit, a price, a discount or an invented deadline.
- **A port with a timeout.** The product calls it through a port with a 30 s timeout (the step's own timeout is `PT30S`, one attempt) and
  falls back to its bilingual template on a timeout, an error or an empty or oversized answer. The Studio never blocks a send.
- **The run id is kept.** The product stores the platform's run id with the sent message, so that any message can be traced to its run.
- **Contract test.** `tests/contracts/invitation-writer.contract.json` is the recorded request and response of the port (a fixture
  replayed by the product's contract test); `tests/business-brief.test.mjs` checks it against the Studio's schema and outputs.

## Next

A forecast Studio (vacancy, price elasticity) once there is history to learn from (krizaka/orazaka-packs#152, P2): the same shape as
orochia#226 — the product sends pseudonymous aggregates, Orazaka analyses, the product falls back to what it has.
