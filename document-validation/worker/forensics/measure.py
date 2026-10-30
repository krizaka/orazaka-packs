#!/usr/bin/env python3
"""Measures ``authenticity.analyse`` over the forensic corpus and gates every signal (orazaka-packs#176).

    python forensics/measure.py [--write] [--per-type 10] [--per-workflow 35]

``results.json`` says, per signal and level, how many ordinary negatives it fired on (with the exact 95 % upper bound on
the false-positive rate), the recall per tamper type, and the CPU time per document. The gate: a signal whose
``incohérent`` case fires on ANY ordinary negative, or whose ``inhabituel`` case fires on more than 5 % of them, fails —
unless ``authenticity-signals.json`` has it ``"enabled": false``. A signal under the bar is switched off, never loosened.
"""

import json
import math
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import authenticity as a  # noqa: E402
import corpus  # noqa: E402

MIN_NEGATIVES = 200
INHABITUEL_BAR = 0.05
RESULTS = os.path.join(HERE, "results.json")


def upper_bound(failures: int, total: int, confidence: float = 0.95) -> float:
    """One-sided exact (Clopper-Pearson) upper bound on a rate: the p for which seeing ``<= failures`` has chance ``1 - confidence``."""
    if total == 0 or failures >= total:
        return 1.0
    alpha = 1 - confidence

    def cdf(p):
        return sum(math.comb(total, k) * p**k * (1 - p) ** (total - k) for k in range(failures + 1))

    low, high = 0.0, 1.0
    for _ in range(60):
        middle = (low + high) / 2
        low, high = (middle, high) if cdf(middle) > alpha else (low, middle)
    return high


def _fired(report):
    return {(s["signalId"], s["level"]) for s in report["signals"]}


def measure(data):
    """Runs ``analyse`` over ``data`` (``corpus.build()``) and returns the results structure."""
    def run(item):
        started = time.process_time()
        report = a.analyse(item["bytes"], locale="en")
        return report, time.process_time() - started

    negatives, tampered, cpu = data["negatives"], data["tampered"], []
    negative_hits, tamper_hits, per_type_any = {}, {}, {}
    for item in negatives:
        report, seconds = run(item)
        cpu.append(seconds)
        for key in _fired(report):
            negative_hits.setdefault(key, []).append(item["id"])
    for item in tampered:
        report, seconds = run(item)
        cpu.append(seconds)
        fired = _fired(report)
        counted = per_type_any.setdefault(item["variant"], {"documents": 0, "flagged": 0})
        counted["documents"] += 1
        counted["flagged"] += any(level in ("inhabituel", "incohérent") for _, level in fired)
        for key in fired:
            by_type = tamper_hits.setdefault(key, {})
            by_type[item["variant"]] = by_type.get(item["variant"], 0) + 1

    total = len(negatives)
    signals = []
    for key in sorted(set(negative_hits) | set(tamper_hits)):
        count = len(negative_hits.get(key, []))
        signals.append({
            "signalId": key[0], "level": key[1],
            "falsePositives": count, "negatives": total,
            "falsePositiveRate": round(count / total, 4) if total else None,
            "upperBound95": round(upper_bound(count, total), 4),
            "recallByTamperType": tamper_hits.get(key, {}),
        })
    ordered = sorted(cpu)
    return {
        "corpus": {"seed": corpus.SEED, "negatives": total, "tampered": len(tampered), "tools": data["tools"],
                   "negativeWorkflows": sorted({i["variant"] for i in negatives}), "tamperTypes": list(corpus.TAMPER_TYPES)},
        "signals": signals,
        "recallPerTamperType": {t: {**v, "recall": round(v["flagged"] / v["documents"], 3)} for t, v in sorted(per_type_any.items())},
        "cpuSeconds": {"median": round(statistics.median(ordered), 5), "p95": round(ordered[int(0.95 * (len(ordered) - 1))], 5)},
    }


def disabled_signals():
    """The signal ids every case of which is ``"enabled": false`` in the catalogue."""
    return set(a.DISABLED_SIGNALS)


def baseline():
    """Signals that shipped BEFORE the corpus existed and measure over the bar: ``{signalId: {level, maxRate}}``.
    A ratchet, like ``lint-ratchet.json``: the rate may only go down, a new signal is never added here, and the founder
    decides each one (switch off, or fix the detector until the entry can be deleted)."""
    with open(os.path.join(HERE, "gate-baseline.json"), encoding="utf-8") as handle:
        return json.load(handle)["signals"]


def gate(results, disabled=None, known=None):
    """The failures, as sentences; ``[]`` when every enabled signal is under the bar (or under its baseline)."""
    disabled = disabled_signals() if disabled is None else disabled
    known = baseline() if known is None else known
    failures = []
    if results["corpus"]["negatives"] < MIN_NEGATIVES:
        failures.append(f"only {results['corpus']['negatives']} ordinary negatives, at least {MIN_NEGATIVES} are needed")
    for signal in results["signals"]:
        if signal["signalId"] in disabled or not signal["negatives"]:
            continue
        pinned = known.get(signal["signalId"])
        if pinned and pinned["level"] == signal["level"]:
            if signal["falsePositiveRate"] > pinned["maxRate"]:
                failures.append(f"{signal['signalId']} ({signal['level']}) got worse: {signal['falsePositiveRate']:.1%} of ordinary documents > its baseline {pinned['maxRate']:.1%}")
            continue
        if signal["level"] == "incohérent" and signal["falsePositives"] > 0:
            failures.append(f"{signal['signalId']} (incohérent) fired on {signal['falsePositives']} of {signal['negatives']} ordinary documents: switch it off in authenticity-signals.json")
        elif signal["level"] == "inhabituel" and signal["falsePositives"] / signal["negatives"] > INHABITUEL_BAR:
            failures.append(f"{signal['signalId']} (inhabituel) fired on {signal['falsePositives']} of {signal['negatives']} ordinary documents ({signal['falsePositiveRate']:.1%} > 5 %): switch it off in authenticity-signals.json")
    return failures


def main(argv):
    def option(name, default):
        return int(argv[argv.index(name) + 1]) if name in argv else default
    results = measure(corpus.build(option("--per-type", 10), option("--per-workflow", 35)))
    if "--write" in argv:
        with open(RESULTS, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps({k: results[k] for k in ("corpus", "recallPerTamperType", "cpuSeconds")}, ensure_ascii=False, indent=1))
    for signal in results["signals"]:
        print(f"{signal['signalId']:18} {signal['level']:11} FP {signal['falsePositives']:3}/{signal['negatives']} ub95 {signal['upperBound95']:.3f}  {signal['recallByTamperType']}")
    failures = gate(results)
    for failure in failures:
        print("GATE:", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
