#!/usr/bin/env python3
"""Golden cases (orazaka-packs#106): whole fictional documents and the verdict every deterministic rule must give them.

Run: .venv/bin/python worker/test_golden.py            check every case
     .venv/bin/python worker/test_golden.py --update   rewrite the expected files (review the diff before committing)

A rule's own fixtures prove it tells a pass from a fail on a sentence; a golden case proves the whole ruleset on a whole
document — the rules that must fire, the ones that must not, and the ones left to judgment — so a change of a rule, a
revision or the parser shows as a diff of verdicts. Deterministic only: no model, no broker, so CI runs it always.

Layout: worker/fixtures/<ruleset>/<case>.txt — the document (fictional, never a real one);
        worker/fixtures/<ruleset>/<case>.expected.json — {"asOf", "findings": {ruleId: verdict}, "judgments": [ruleId]}.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
#: The day the law is read as of: a case pins its own `asOf` in its expected file; a new case takes this one, the first
#: day every shipped ruleset is in force (qc-service-contract starts on 2026-10-19).
DEFAULT_AS_OF = "2026-10-22"


def cases():
    for ruleset_dir in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        for doc in sorted(ruleset_dir.glob("*.txt")):
            yield ruleset_dir.name, doc, doc.with_suffix(".expected.json")


def verdicts(ruleset_id: str, text: str, as_of: str) -> dict:
    findings, judgments = rules.screen(rules.resolve(ruleset_id, as_of), text)
    return {"asOf": as_of, "findings": {f["ruleId"]: f["verdict"] for f in findings}, "judgments": [j["ruleId"] for j in judgments]}


def test_every_golden_case_gives_its_recorded_verdicts():
    seen = 0
    for ruleset_id, doc, expected_file in cases():
        assert expected_file.exists(), f"{doc.relative_to(FIXTURES)} has no expected file: run test_golden.py --update and review it"
        expected = json.loads(expected_file.read_text(encoding="utf-8"))
        actual = verdicts(ruleset_id, doc.read_text(encoding="utf-8"), expected.get("asOf", DEFAULT_AS_OF))
        assert actual == expected, f"{doc.relative_to(FIXTURES)}: the verdicts changed\n  expected {expected}\n  actual   {actual}"
        seen += 1
    assert seen >= 9, f"only {seen} golden cases: every ruleset ships its own"


def test_a_defective_document_fails_somewhere_and_a_compliant_one_nowhere():
    # The names say the intent; the verdicts must agree with them, or a fixture lies.
    for ruleset_id, doc, expected_file in cases():
        found = json.loads(expected_file.read_text(encoding="utf-8"))["findings"].values()
        if "defective" in doc.stem:
            assert rules.FAIL in found, f"{doc.name} is called defective and fails no rule"
        if "compliant" in doc.stem:
            assert rules.FAIL not in found, f"{doc.name} is called compliant and fails a rule"


if __name__ == "__main__":
    if "--update" in sys.argv:
        for ruleset_id, doc, expected_file in cases():
            previous = json.loads(expected_file.read_text(encoding="utf-8")) if expected_file.exists() else {}
            data = verdicts(ruleset_id, doc.read_text(encoding="utf-8"), previous.get("asOf", DEFAULT_AS_OF))
            expected_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  wrote {expected_file.relative_to(FIXTURES)}")
        sys.exit(0)
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {str(exc)[:400]}")
    print(f"\n{'FAILED' if failures else 'all green'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)
