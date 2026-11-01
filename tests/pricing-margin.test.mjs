// Prices are data, and a price that loses money on compute does not ship (krizaka-internal#38). Every pack carries a list
// price; a pack with a PAID Studio is never free; and what a pack charges, net of the card processor, keeps the margin floor
// even if its included credits are all spent on the costliest unit the pricebook bills. The unit costs are data
// (tests/contracts/unit-costs.json): a rate under the floor fails unless it is listed in `belowFloor` with its issue.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import YAML from "yaml";

const root = new URL("../", import.meta.url).pathname;
const costs = JSON.parse(readFileSync(`${root}tests/contracts/unit-costs.json`, "utf8"));
const packs = readdirSync(root)
  .filter((d) => existsSync(`${root}${d}/pack.yaml`))
  .map((dir) => ({ dir, pack: YAML.parse(readFileSync(`${root}${dir}/pack.yaml`, "utf8")) }));

const sameRate = (a, b) => a.capability === b.capability && (a.model ?? null) === (b.model ?? null);
const rateMargin = (r) => 1 - r.costMillicentsPerUnit / (r.creditsPerUnit * costs.creditListPriceMillicents);
const processorCents = (cents) => Math.round((cents * costs.processor.percentBps) / 10000) + costs.processor.fixedCents;
/** The most a credit can cost Krizaka, on any rate: what a buyer who spends every credit on the dearest unit costs. */
const worstMillicentsPerCredit = Math.max(...costs.rates.map((r) => r.costMillicentsPerUnit / r.creditsPerUnit));

test("every unit cost is a positive figure with its source", () => {
  assert.ok(costs.rates.length > 0);
  for (const r of costs.rates) {
    const name = `${r.capability}/${r.model ?? "*"}`;
    assert.ok(r.creditsPerUnit > 0, `${name}: creditsPerUnit`);
    assert.ok(r.costMillicentsPerUnit >= 0, `${name}: costMillicentsPerUnit`);
    assert.ok(r.source?.length > 10, `${name}: a cost without its source is a guess`);
    assert.equal(typeof r.assumption, "boolean", `${name}: say whether the cost was measured`);
  }
});

test("a rate under the margin floor is listed with its issue, and only such a rate", () => {
  for (const r of costs.rates) {
    const listed = costs.belowFloor.some((b) => sameRate(b, r));
    const under = rateMargin(r) < costs.marginFloor;
    assert.equal(listed, under, `${r.capability}/${r.model ?? "*"} margin ${(rateMargin(r) * 100).toFixed(1)} %`);
  }
  for (const b of costs.belowFloor) assert.match(b.issue, /^krizaka-internal#\d+$/);
});

test("every pack has a price in whole CAD dollars, and a pack with a PAID Studio is never free", () => {
  for (const { dir, pack } of packs) {
    const paid = (pack.studios ?? []).some((s) => s.pricing === "PAID");
    if (!pack.pricing) {
      assert.ok(!paid && !pack.catalog, `${dir}: a catalogued or PAID pack needs pricing`);
      continue;
    }
    const { priceCents } = pack.pricing;
    assert.ok(Number.isInteger(priceCents) && priceCents >= 0, `${dir}: priceCents`);
    assert.equal(priceCents % 100, 0, `${dir}: list prices are whole dollars (taxes are extra)`);
    if (paid) assert.ok(priceCents > 0, `${dir}: sells a PAID Studio for nothing`);
  }
});

test("a paid pack keeps the margin floor, net of the processor, with every credit spent on the dearest unit", () => {
  for (const { dir, pack } of packs) {
    const price = pack.pricing?.priceCents ?? 0;
    if (price === 0) continue;
    const computeCents = (pack.pricing.includedCredits * worstMillicentsPerCredit) / 1000;
    const margin = (price - processorCents(price) - computeCents) / price;
    assert.ok(margin >= costs.marginFloor, `${dir}: margin ${(margin * 100).toFixed(1)} % under the floor`);
  }
});
