#!/usr/bin/env python3
"""Re-records the ``report`` of the yomizaka#305 recordings against the lease ruleset the pack ships now.

No model and no network: the document and the judge's answers are the recordings' own (the JUDGMENT findings of the
report already there), the deterministic rules run in this worker. Run from document-validation/worker:
``python3 fixtures/compliance-check/rerecord.py`` and read the diff — a verdict that changed is the new rules' doing.
"""
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import rules  # noqa: E402
import validation_worker as worker  # noqa: E402


def judge(report: dict) -> str:
    return json.dumps([
        {"ruleId": f["ruleId"], "verdict": f["verdict"] if f["verdict"] != rules.NOT_APPLICABLE else rules.INSUFFICIENT_EVIDENCE,
         "quote": (f["evidenceSpan"] or {}).get("quote", "")}
        for f in report["findings"] if f["method"] == "JUDGMENT"], ensure_ascii=False)


for name in ("clean", "errors"):
    path = HERE / f"yomizaka-305-{name}.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    screened = worker._screen({"document": rec["document"], **rec["inputs"]})
    report = worker._assemble({"screened": screened["screenedJson"], "judgment": judge(rec["report"])})["report"]
    rec["report"] = report
    rec["source"] = (rec["source"].split("; re-recorded")[0] + f"; report re-recorded {date.today().isoformat()} against ruleset "
                     f"revision {report['rulesetRevision']} with the recorded judge answers (no model, no paid call)")
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(name, report["summary"])
