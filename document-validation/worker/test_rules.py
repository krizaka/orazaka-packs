#!/usr/bin/env python3
"""The rule engine's own suite. Run: python3 -m pytest test_rules.py -q  (or: python3 test_rules.py)

A compliance pack is a product whose output a user forwards to their counterparty. Its rules are
therefore the part that must be tested hardest, and they are testable precisely because the engine
is a pure function of (ruleset, text) with no broker and no model in it.
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules  # noqa: E402

RULESET_DIR = Path(__file__).resolve().parent.parent / "rulesets"

CLEAN = """CONTRAT DE LOCATION
Entre le bailleur Monsieur Jean Martin, propriétaire,
et le locataire Madame Claire Dubois.
Durée du bail : trois ans à compter du 1er septembre 2026.
Loyer mensuel : 850 € hors charges.
Dépôt de garantie : 850 €.
Un diagnostic de performance énergétique (DPE) classe C est annexé au présent contrat.
"""

DEFECTIVE = """CONTRAT DE LOCATION
Entre le bailleur Monsieur Jean Martin
et le locataire Madame Claire Dubois.
Durée du bail : trois ans.
Loyer mensuel : 850 € hors charges.
Dépôt de garantie : 2 550 €.
La solidarité du colocataire sortant se poursuit après le congé pendant vingt-quatre mois.
Il est interdit au locataire de recevoir des visites après 22 heures.
"""


def _by_id(findings):
    return {f["ruleId"]: f for f in findings}


def test_resolution_is_by_date_not_by_recency():
    assert rules.resolve("fr-residential-lease", "2025-03-01")["version"] == "2024-07-01"
    assert rules.resolve("fr-residential-lease", "2026-09-01")["version"] == "2026-07-01"


def test_a_date_no_version_covers_is_an_error_not_a_fallback():
    try:
        rules.resolve("fr-residential-lease", "2019-01-01")
    except rules.RulesetNotFound:
        return
    raise AssertionError("a date before every version must fail, never silently use the oldest")


def test_the_law_changing_changes_the_verdict_on_the_same_document():
    """The whole point of versioning: one document, two dates, two answers — both correct."""
    text = CLEAN.replace("classe C", "classe G")
    old = _by_id(rules.screen(rules.resolve("fr-residential-lease", "2025-03-01"), text)[0])
    new = _by_id(rules.screen(rules.resolve("fr-residential-lease", "2026-09-01"), text)[0])
    assert "FR-LEASE-009" not in old, "the class-G ban did not exist under the 2024 ruleset"
    assert new["FR-LEASE-009"]["verdict"] == rules.FAIL
    assert old["FR-LEASE-008"]["severity"] == "MAJOR"
    assert new["FR-LEASE-008"]["severity"] == "BLOCKING"


def test_a_clean_lease_passes_every_deterministic_rule():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    findings, judgments = rules.screen(ruleset, CLEAN)
    assert all(f["verdict"] == rules.PASS for f in findings), _by_id(findings)
    assert [j["ruleId"] for j in judgments] == ["FR-LEASE-020"]


def test_every_finding_carries_its_rule_and_its_evidence():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    findings, _ = rules.screen(ruleset, DEFECTIVE)
    for finding in findings:
        assert set(finding) == {
            "ruleId", "title", "severity", "verdict", "evidenceSpan",
            "explanation", "method", "citation",
        }
        assert finding["citation"], "a finding with no citation cannot be forwarded to a counterparty"
        if finding["verdict"] == rules.FAIL and finding["evidenceSpan"]:
            span = finding["evidenceSpan"]
            # The span must actually point at the document, not be decorative.
            assert DEFECTIVE[span["start"]:span["end"]].strip().startswith(span["quote"][:20])


def test_a_deposit_over_one_month_fails_with_the_amount_quoted():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    finding = _by_id(rules.screen(ruleset, DEFECTIVE)[0])["FR-LEASE-005"]
    assert finding["verdict"] == rules.FAIL
    assert "2 550" in finding["evidenceSpan"]["quote"]
    assert "3.00 mois" in finding["explanation"]


def test_a_clause_the_law_deems_unwritten_is_quoted_where_it_sits():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    found = _by_id(rules.screen(ruleset, DEFECTIVE)[0])
    assert found["FR-LEASE-006"]["verdict"] == rules.FAIL
    assert "solidarité" in found["FR-LEASE-006"]["evidenceSpan"]["quote"].lower()
    assert found["FR-LEASE-007"]["verdict"] == rules.FAIL


def test_a_missing_amount_is_insufficient_evidence_not_a_pass():
    """The failure that matters: a rule that cannot be evaluated must never read as compliant."""
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    text = "Le bailleur et le locataire conviennent d'une durée du bail de trois ans."
    finding = _by_id(rules.screen(ruleset, text)[0])["FR-LEASE-005"]
    assert finding["verdict"] == rules.INSUFFICIENT_EVIDENCE


def test_jurisdiction_selects_a_different_body_of_law_entirely():
    fr = rules.resolve("fr-residential-lease", "2026-09-01")
    be = rules.resolve("be-residential-lease", "2026-09-01")
    assert fr["jurisdiction"] == "FR" and be["jurisdiction"] == "BE-WAL"
    # Two months' deposit: unlawful in France, lawful in Wallonia. Same document, same date.
    text = CLEAN.replace("Dépôt de garantie : 850 €", "Dépôt de garantie : 1 700 €")
    assert _by_id(rules.screen(fr, text)[0])["FR-LEASE-005"]["verdict"] == rules.FAIL
    text_be = text.replace("Dépôt de garantie", "Garantie locative")
    assert _by_id(rules.screen(be, text_be)[0])["BE-WAL-002"]["verdict"] == rules.PASS


def test_the_model_is_asked_only_about_judgment_rules():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    _, judgments = rules.screen(ruleset, DEFECTIVE)
    deterministic = [r["ruleId"] for r in ruleset["rules"] if r["method"] == "DETERMINISTIC"]
    assert not set(j["ruleId"] for j in judgments) & set(deterministic)


def test_an_unparseable_model_answer_degrades_to_insufficient_evidence():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    merged = _by_id(rules.merge_judgments(ruleset, [], "Je pense que ce bail est plutôt correct."))
    assert merged["FR-LEASE-020"]["verdict"] == rules.INSUFFICIENT_EVIDENCE


def test_a_verdict_outside_the_enum_is_refused():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    answer = '[{"ruleId": "FR-LEASE-020", "verdict": "PROBABLEMENT_OK", "quote": "x"}]'
    merged = _by_id(rules.merge_judgments(ruleset, [], answer))
    assert merged["FR-LEASE-020"]["verdict"] == rules.INSUFFICIENT_EVIDENCE


def test_a_verdict_about_a_rule_nobody_asked_about_is_dropped():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    answer = '[{"ruleId": "FR-LEASE-999", "verdict": "FAIL", "quote": "inventé"}]'
    merged = rules.merge_judgments(ruleset, [], answer)
    assert [f["ruleId"] for f in merged] == ["FR-LEASE-020"]
    assert merged[0]["verdict"] == rules.INSUFFICIENT_EVIDENCE


def test_a_fenced_json_answer_is_still_read():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    answer = 'Voici:\n```json\n[{"ruleId":"FR-LEASE-020","verdict":"FAIL","quote":"pénalité de 5000 €"}]\n```'
    merged = _by_id(rules.merge_judgments(ruleset, [], answer))
    assert merged["FR-LEASE-020"]["verdict"] == rules.FAIL
    assert merged["FR-LEASE-020"]["evidenceSpan"]["quote"] == "pénalité de 5000 €"


def test_the_summary_counts_and_never_concludes():
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    findings, _ = rules.screen(ruleset, DEFECTIVE)
    summary = rules.summarise(findings)
    assert summary["blockingFailures"] >= 3
    assert "verdict" not in summary and "conclusion" not in summary


def test_an_amount_written_EUR_is_read_as_an_amount():
    """The false FAIL that phase H's first live run produced: 'EUR' is how a French lease is
    routinely written, and a compliance tool reporting 'no rent stated' on a lease that states it
    accuses an honest party. A false FAIL is worse than a missing verdict."""
    ruleset = rules.resolve("fr-residential-lease", "2025-03-01")
    text = ("Entre le bailleur et le locataire. Duree du bail : trois ans. "
            "Loyer mensuel : 850 EUR hors charges. Depot de garantie : 850 EUR.")
    found = _by_id(rules.screen(ruleset, text)[0])
    assert found["FR-LEASE-004"]["verdict"] == rules.PASS, found["FR-LEASE-004"]
    assert found["FR-LEASE-005"]["verdict"] == rules.PASS, found["FR-LEASE-005"]


def test_a_revision_is_the_pack_correcting_itself_a_version_is_the_law_changing():
    """A customer asking why last month's report differs must be able to tell the two apart."""
    corrected = rules.resolve("fr-residential-lease", "2025-03-01")
    assert corrected["revision"] == 2 and "revisionNote" in corrected
    assert rules.resolve("fr-residential-lease", "2026-09-01")["revision"] == 1


def _as_list(fixture):
    """One fragment or several — a rule may ship a list on either side.

    The pair proves a rule CAN fail. It does not prove the rule catches the requirement when the
    document words it differently, and three rules in this ruleset match the effect of a clause by
    matching one phrasing of it (ADR-072 §2.1). A list is how a rule says which phrasings it claims,
    and every one of them is then checked — so broadening a pattern and proving the broadening are
    the same edit.

    PASS fixtures carry the near-misses on purpose: legitimate solidarity during the lease, a
    sublet restriction, a DPE of class F. A prohibition that fires on a lawful clause is a false
    FAIL, and widening a pattern is exactly when that gets introduced.
    """
    return [fixture] if isinstance(fixture, str) else list(fixture)


def _current_ruleset_versions():
    """The newest version file of each ruleset, and only that one.

    Superseded versions are exempt, and the reason is the pack's own guarantee: a run is replayed
    against the ruleset in force on its `asOf` date, so "a document judged against the rules of 2025
    reaches the same verdicts next year". Correcting a rule in a superseded version would change a
    verdict already delivered to someone — it rewrites history rather than fixing a rule. The three
    FR-2024 rules that do not discriminate are frozen for exactly that reason and are recorded in
    docs/evaluations/first-real-use.md rather than repaired.
    """
    for directory in sorted(RULESET_DIR.iterdir()):
        if not directory.is_dir():
            continue
        versions = sorted(directory.glob("*.json"))
        if versions:
            yield versions[-1]


def test_every_deterministic_rule_distinguishes_its_own_fixtures():
    """Every deterministic rule must DISTINGUISH a pair of fixtures it ships itself.

    The property every governance rule in the platform has had for twelve phases — plant it, see it
    red, revert — applied to a ruleset, which is a suite of assertions pointed at the user's
    document and had never been held to it because it was treated as content.

    FR-LEASE-001 checked that the word *bailleur* appears, for a requirement that is the identity of
    the parties. Every lease contains that word: an assertion that runs, over a real subject, and
    cannot fail — and its output told a user a BLOCKING requirement was met.

    A rule that always passes fails its negative fixture; a rule that always fails fails its
    positive one. Run against this ruleset the first time, FOUR of nine could not distinguish their
    own pair, including one nobody suspected: FR-LEASE-009 returned PASS for a property advertised
    as class G, which it is illegal to rent.

    Fixtures are written from the REQUIREMENT, never from the pattern: one written by reading the
    regex proves the regex matches itself, which is the same defect one level up.

    JUDGMENT rules are exempt and say so — their verdict comes from a model, and a model call here
    would make this check as unreliable as the thing it checks.
    """
    failures = []
    checked = 0
    for ruleset_path in _current_ruleset_versions():
        ruleset = json.loads(ruleset_path.read_text())
        for rule in ruleset["rules"]:
            if rule.get("method") == "JUDGMENT":
                continue
            fixtures = rule.get("fixtures")
            if not fixtures or "pass" not in fixtures or "fail" not in fixtures:
                failures.append(f"{rule['ruleId']} ships no fixture pair")
                continue
            checked += 1
            check = rules.CHECKS[rule["check"]["type"]]
            for expected, fragments in (("PASS", fixtures["pass"]), ("FAIL", fixtures["fail"])):
                for fragment in _as_list(fragments):
                    got = check(rule, fragment)["verdict"]
                    if got != expected:
                        failures.append(
                            f"{rule['ruleId']} expected {expected} and returned {got} on: "
                            f"{fragment[:72]}"
                        )
    assert checked > 0, "no deterministic rule was checked — this asserts nothing"
    assert not failures, "rules that do not discriminate their own pair:\n  " + "\n  ".join(failures)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print(f"\n{'FAILED' if failures else 'all green'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)

