#!/usr/bin/env python3
"""The validation worker's screening: a ruleset awaiting a lawyer says so; a named ruleset stays in its jurisdiction.
Run: python3 -m pytest test_screening.py -q  (or: python3 test_screening.py). The broker connection is tested once, in ../../worker-common.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The worker itself (it imports pika, hence here, after the CI installs it): a ruleset awaiting a lawyer says so.
def test_a_quebec_report_carries_its_review_status():
    import test_rules
    import validation_worker
    screened = validation_worker._screen({"document": test_rules.QC_DEFECTIVE, "jurisdiction": "QC", "asOf": "2026-10-15"})
    assert screened["reviewStatus"] == "TO_REVIEW_BY_LAWYER"
    report = validation_worker._assemble({"screened": screened["screenedJson"], "judgment": "[]"})["report"]
    assert report["reviewStatus"] == "TO_REVIEW_BY_LAWYER"


def test_a_named_ruleset_is_applied_only_within_its_jurisdiction():
    import test_rules
    import validation_worker
    named = validation_worker._screen({"document": test_rules.QC_INVOICE_CLEAN, "jurisdiction": "QC", "ruleset": "qc-invoice", "asOf": "2026-10-19"})
    assert named["rulesetId"] == "qc-invoice" and named["judgmentCount"] == 0
    assert "JSON vide" in named["judgmentPrompt"]  # no question for a model: nothing to read
    contract = validation_worker._screen({"document": test_rules.QC_CONTRACT_CLEAN, "jurisdiction": "QC", "ruleset": "qc-service-contract", "asOf": "2026-10-19"})
    assert contract["rulesetId"] == "qc-service-contract"
    default = validation_worker._screen({"document": test_rules.QC_DEFECTIVE, "jurisdiction": "QC", "ruleset": "", "asOf": "2026-10-19"})
    assert default["rulesetId"] == "qc-residential-lease"
    for jurisdiction in ("FR", "BE-WAL"):
        try:
            validation_worker._screen({"document": "x", "jurisdiction": jurisdiction, "ruleset": "qc-invoice"})
        except validation_worker.InvalidJobPayload:
            continue
        raise AssertionError("an invoice ruleset of Québec must never be applied to another jurisdiction")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as error:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {error!r}")
    sys.exit(1 if failures else 0)
