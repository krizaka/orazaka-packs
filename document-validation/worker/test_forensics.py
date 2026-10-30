#!/usr/bin/env python3
"""The forensic corpus and its gate (orazaka-packs#176). Run: python test_forensics.py (needs pikepdf, reportlab, Pillow, pypdf).

The gate is the point: a signal that fires on ordinary documents fails the build, a signal under the bar is switched off
in the catalogue and never loosened, and the corpus that decides is deterministic and says what each tampered file changed.
"""

import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "forensics"))
import authenticity as a  # noqa: E402
import corpus  # noqa: E402
import measure  # noqa: E402


def _digest(items):
    return [(i["id"], hashlib.sha256(i["bytes"]).hexdigest()) for i in items]


def _results(negatives=210, hits=None):
    """A results structure with the given false-positive counts: ``{(signalId, level): count}``."""
    return {
        "corpus": {"negatives": negatives},
        "signals": [{"signalId": k[0], "level": k[1], "falsePositives": n, "negatives": negatives,
                     "falsePositiveRate": round(n / negatives, 4)} for k, n in (hits or {}).items()],
    }


def test_same_seed_same_bytes():
    assert _digest(corpus.tampered_set(2)) == _digest(corpus.tampered_set(2))
    # Ghostscript writes its own file id, so its two workflows are compared by what they measure, not by bytes.
    python_only = lambda items: [i for i in items if not corpus.NEGATIVE_WORKFLOWS[i["variant"]]]  # noqa: E731
    assert _digest(python_only(corpus.negatives_set(3))) == _digest(python_only(corpus.negatives_set(3)))


def test_every_tamper_type_has_its_ground_truth():
    items = corpus.tampered_set(2)
    assert {i["variant"] for i in items} == set(corpus.TAMPER_TYPES)
    for item in items:
        assert item["role"] == "tampered" and item["truth"]["changed"] and item["truth"]["box"], item["id"]
        assert item["truth"]["tool"], item["id"]
        if item["media"] == "pdf":
            assert item["truth"]["page"] == 1, item["id"]


def test_negatives_are_ordinary_and_at_least_200():
    negatives = corpus.negatives_set(35)
    assert len(negatives) >= measure.MIN_NEGATIVES
    assert all(i["role"] == "negative" and i["truth"] is None for i in negatives)
    assert set(i["variant"] for i in negatives) >= {k for k, tool in corpus.NEGATIVE_WORKFLOWS.items() if not tool}


def test_nothing_real_in_the_corpus():
    for name in corpus.EMPLOYERS + corpus.BANKS:
        assert name.endswith("(fictif)"), name
    assert all(person.endswith("-Demo") for person in corpus.PEOPLE)


def test_incremental_save_is_really_a_second_revision():
    item = next(i for i in corpus.tampered_set(1) if i["variant"] == "incremental-amount")
    assert a._count_revisions(item["bytes"]) == 2
    ids = {s["signalId"] for s in a.analyse(item["bytes"])["signals"]}
    assert "PDF-REV-001" in ids


def test_upper_bound_is_the_exact_one():
    assert abs(measure.upper_bound(0, 100) - (1 - 0.05 ** (1 / 100))) < 1e-4
    assert measure.upper_bound(5, 100) > 0.05
    assert measure.upper_bound(3, 3) == 1.0


def test_gate_refuses_an_incoherent_signal_firing_on_one_ordinary_document():
    failures = measure.gate(_results(hits={("X-001", "incohérent"): 1}), disabled=set(), known={})
    assert failures and "X-001" in failures[0]


def test_gate_refuses_an_unusual_signal_over_five_percent_and_accepts_under():
    assert measure.gate(_results(hits={("X-002", "inhabituel"): 11}), disabled=set(), known={})
    assert not measure.gate(_results(hits={("X-002", "inhabituel"): 10}), disabled=set(), known={})


def test_gate_accepts_a_switched_off_signal_never_a_loosened_one():
    results = _results(hits={("X-003", "incohérent"): 9})
    assert measure.gate(results, disabled={"X-003"}, known={}) == []
    assert measure.gate(results, disabled=set(), known={"X-003": {"level": "incohérent", "maxRate": 0.0}}), "a baseline never excuses an incohérent that got worse"


def test_baseline_only_goes_down():
    known = {"X-004": {"level": "inhabituel", "maxRate": 0.10}}
    assert not measure.gate(_results(hits={("X-004", "inhabituel"): 21}), disabled=set(), known=known)
    assert measure.gate(_results(hits={("X-004", "inhabituel"): 22}), disabled=set(), known=known)


def test_gate_needs_enough_negatives():
    assert measure.gate(_results(negatives=50), disabled=set(), known={})


def test_a_switched_off_signal_is_never_emitted():
    item = next(i for i in corpus.tampered_set(1) if i["variant"] == "incremental-amount")
    assert any(s["signalId"] == "PDF-REV-001" for s in a.analyse(item["bytes"])["signals"])
    saved = a.DISABLED_SIGNALS
    a.DISABLED_SIGNALS = frozenset({"PDF-REV-001"})
    try:
        assert not any(s["signalId"] == "PDF-REV-001" for s in a.analyse(item["bytes"])["signals"])
    finally:
        a.DISABLED_SIGNALS = saved


def test_the_baseline_lists_only_signals_the_catalogue_knows():
    known_ids = {entry["signalId"] for entry in a.CATALOGUE["signals"].values()}
    for signal in measure.baseline():
        assert signal in known_ids, signal


def test_the_real_corpus_passes_the_gate():
    """The measurement itself: every enabled signal is under the bar or under its baseline."""
    results = measure.measure(corpus.build(per_type=4, per_workflow=35))
    assert measure.gate(results) == [], measure.gate(results)
    assert results["cpuSeconds"]["p95"] < 1.0


if __name__ == "__main__":
    failed = 0
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                print("ok  ", name)
            except Exception as error:  # noqa: BLE001
                failed += 1
                print("FAIL", name, repr(error))
    sys.exit(1 if failed else 0)
