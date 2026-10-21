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
            for expected, fragments in (("PASS", fixtures["pass"]), ("FAIL", fixtures["fail"])):
                for fragment in _as_list(fragments):
                    got = rules.evaluate(ruleset, rule, fragment)["verdict"]
                    if got != expected:
                        failures.append(
                            f"{rule['ruleId']} expected {expected} and returned {got} on: "
                            f"{fragment[:72]}"
                        )
    assert checked > 0, "no deterministic rule was checked — this asserts nothing"
    assert not failures, "rules that do not discriminate their own pair:\n  " + "\n  ".join(failures)


QC_DEFECTIVE = """BAIL DE LOGEMENT
Entre le locateur Monsieur Marc Tremblay, domicilié à Montréal,
et la locataire Madame Sophie Gagnon.
Loyer mensuel : 1 450 $, payable le premier jour du mois.
La locataire verse un dépôt de sécurité de 1 450 $ à la signature.
La locataire remet douze chèques postdatés.
Il est interdit d'avoir des enfants dans le logement.
"""


def test_quebec_rules_catch_what_the_civil_code_forbids_and_say_they_await_a_lawyer():
    ruleset = rules.resolve("qc-residential-lease", "2026-10-15")
    assert ruleset["jurisdiction"] == "QC"
    assert ruleset["reviewStatus"] == "TO_REVIEW_BY_LAWYER"
    for rule in ruleset["rules"]:
        assert "C.c.Q." in rule["citation"], rule["ruleId"]
    found = _by_id(rules.screen(ruleset, QC_DEFECTIVE)[0])
    for rule_id in ("QC-LEASE-004", "QC-LEASE-005", "QC-LEASE-006", "QC-LEASE-008"):
        assert found[rule_id]["verdict"] == rules.FAIL, rule_id
    assert "1 450 $" in found["QC-LEASE-004"]["evidenceSpan"]["quote"]
    for rule_id in ("QC-LEASE-001", "QC-LEASE-002", "QC-LEASE-003", "QC-LEASE-007"):
        assert found[rule_id]["verdict"] == rules.PASS, rule_id


# A deposit is forbidden however the lease words it (C.c.Q., art. 1904, al. 1: only the first term of rent may be asked in
# advance). Written from the requirement — what a landlord actually writes — not from the pattern.
QC_DEPOSIT_FAIL = [
    "La locataire verse un dépôt de sécurité de 1 450 $ à la signature.",
    "Un dépôt de garantie équivalant à un mois de loyer est exigé à la signature.",
    "Dépôt de garantie : un mois de loyer.",
    "Un dépôt de 10 % du loyer annuel est requis à la signature.",
    "Le locataire verse, à titre de garantie, la somme de 500 $ à la signature.",
    "Le locataire remet un mois de loyer additionnel en garantie.",
    "Un cautionnement en argent de 800 $ est exigé.",
    "Des frais de clés remboursables de 50 $ sont exigés.",
    "Le locataire paie deux mois de loyer d'avance à la signature.",
    "Dépôt pour dommages : 300 $.",
]
QC_DEPOSIT_PASS = [
    "Le premier mois de loyer, 1 450 $, est payable à la signature.",
    "Aucun dépôt de garantie n'est exigé.",
    "Le locateur n'exige aucun dépôt de sécurité.",
    "Dépôt de garantie : néant.",
    "Le locateur ne peut exiger de dépôt de garantie (art. 1904).",
    "Le loyer est payé par dépôt direct dans le compte du locateur.",
    "Le locataire verse le loyer du premier mois à la signature.",
    "Le locateur détient une garantie légale de bon état du logement.",
]

QC_INCREASE_FAIL = [
    "Le locataire renonce à son droit de refuser toute augmentation de loyer.",
    "Le locataire accepte d'avance toute hausse du loyer décidée par le locateur.",
    "Le loyer sera augmenté de 5 % chaque année sans avis.",
]
QC_INCREASE_PASS = [
    "Le loyer pourra être modifié lors de la reconduction, sur avis donné au locataire dans les délais prévus par la loi.",
    "Le loyer de 1 450 $ est payable le premier jour du mois.",
    "Le locataire peut refuser toute augmentation de loyer dans le mois de la réception de l'avis.",
]


def _qc_rule(rule_id):
    ruleset = rules.resolve("qc-residential-lease", "2026-10-15")
    return next(r for r in ruleset["rules"] if r["ruleId"] == rule_id)


def test_qc_deposit_is_caught_however_it_is_worded_and_lawful_wordings_pass():
    rule = _qc_rule("QC-LEASE-004")
    check = rules.CHECKS[rule["check"]["type"]]
    missed = [t for t in QC_DEPOSIT_FAIL if check(rule, t)["verdict"] != rules.FAIL]
    wrong = [t for t in QC_DEPOSIT_PASS if check(rule, t)["verdict"] != rules.PASS]
    assert not missed, "deposit wordings not caught:\n  " + "\n  ".join(missed)
    assert not wrong, "lawful wordings flagged:\n  " + "\n  ".join(wrong)


def test_qc_deposit_rule_ships_every_wording_as_a_fixture():
    fixtures = _qc_rule("QC-LEASE-004")["fixtures"]
    assert set(QC_DEPOSIT_FAIL) <= set(_as_list(fixtures["fail"]))
    assert set(QC_DEPOSIT_PASS) <= set(_as_list(fixtures["pass"]))


def test_qc_waiver_of_the_rent_increase_regime_is_flagged_and_the_lawful_clauses_pass():
    rule = _qc_rule("QC-LEASE-009")
    assert rule["method"] == "DETERMINISTIC" and "1942" in rule["citation"] and "1945" in rule["citation"]
    check = rules.CHECKS[rule["check"]["type"]]
    assert [t for t in QC_INCREASE_FAIL if check(rule, t)["verdict"] != rules.FAIL] == []
    assert [t for t in QC_INCREASE_PASS if check(rule, t)["verdict"] != rules.PASS] == []
    fixtures = rule["fixtures"]
    assert set(QC_INCREASE_FAIL) <= set(_as_list(fixtures["fail"]))
    assert set(QC_INCREASE_PASS) <= set(_as_list(fixtures["pass"]))


def test_qc_revision_records_the_correction_and_the_law_is_unchanged():
    ruleset = rules.resolve("qc-residential-lease", "2026-10-15")
    assert ruleset["version"] == "2024-02-21" and ruleset["revision"] == 2
    assert "dépôt" in ruleset["revisionNote"].lower() and "augmentation" in ruleset["revisionNote"].lower()


# --- qc-invoice: the mentions a supplier's invoice carries, from the federal regulation DORS/91-45 art. 3 -------------

QC_INVOICE_CLEAN = """FACTURE n° 2041
Date de la facture : 12 octobre 2026
Fournisseur : Atelier Boréal inc.
TPS : 123456789 RT0001
TVQ : 1234567890 TQ0001
Conception du site, 10 heures : 1 000,00 $
TPS (5 %) : 50,00 $
TVQ (9,975 %) : 99,75 $
Total : 1 149,75 $
Conditions de paiement : net 30 jours
"""

QC_INVOICE_DEFECTIVE = """FACTURE
Conception du site, 10 heures : 1 000,00 $
TPS : 12345678RT0001
TVQ : 123456789 TQ0001
Sous-total : 1 000,00 $
"""


def _invoice(text):
    return _by_id(rules.screen(rules.resolve("qc-invoice", "2026-10-19"), text)[0])


def test_a_complete_quebec_invoice_passes_every_rule():
    findings = _invoice(QC_INVOICE_CLEAN)
    assert all(f["verdict"] == rules.PASS for f in findings.values()), {k: v["verdict"] for k, v in findings.items()}


def test_a_defective_quebec_invoice_is_flagged_rule_by_rule():
    findings = _invoice(QC_INVOICE_DEFECTIVE)
    failed = {k for k, v in findings.items() if v["verdict"] == rules.FAIL}
    assert failed == {"QC-INV-001", "QC-INV-002", "QC-INV-003", "QC-INV-004", "QC-INV-005", "QC-INV-006", "QC-INV-007", "QC-INV-008"}
    assert findings["QC-INV-004"]["evidenceSpan"]["quote"].startswith("12345678RT0001")


def test_an_invoice_without_a_number_is_not_accused_of_a_malformed_one():
    findings = _invoice(QC_INVOICE_CLEAN.replace("TPS : 123456789 RT0001\n", "").replace("TVQ : 1234567890 TQ0001\n", ""))
    assert findings["QC-INV-004"]["verdict"] == rules.PASS and findings["QC-INV-005"]["verdict"] == rules.PASS
    assert findings["QC-INV-003"]["verdict"] == rules.FAIL


def test_every_invoice_rule_cites_its_source_and_says_it_awaits_review():
    ruleset = rules.resolve("qc-invoice", "2026-10-19")
    assert ruleset["reviewStatus"] == "TO_REVIEW_BY_LAWYER" and "DORS/91-45" in ruleset["source"]
    assert all(r["citation"] for r in ruleset["rules"]) and not [r for r in ruleset["rules"] if r["method"] == "JUDGMENT"]
    # What could not be read at its source is said not to be encoded, never silently omitted.
    assert "TVQ" in ruleset["reviewNote"] and "non encodé" in ruleset["reviewNote"].lower()


def test_the_invoice_is_opt_in_the_lease_stays_the_default_of_quebec():
    assert rules.jurisdictions()["QC"] == "qc-residential-lease"
    assert set(rules.rulesets_by_jurisdiction()["QC"]) == {"qc-residential-lease", "qc-invoice", "qc-service-contract"}


# --- qc-service-contract: only what federal law, read at its source, says (Interest Act s. 4, Copyright Act s. 13(4), 14.1) ---

QC_CONTRACT_CLEAN = """CONTRAT DE SERVICES
Le prestataire conçoit le site du client pour 4 000 $.
Le prestataire cède au client ses droits d'auteur sur les livrables et renonce à ses droits moraux.
Intérêt de retard : 2 % par mois (26,8 % par année).
Signé à Montréal le 12 octobre 2026.
"""

QC_CONTRACT_DEFECTIVE = """CONTRAT DE SERVICES
Le prestataire conçoit le site du client pour 4 000 $.
Le prestataire cède au client tous ses droits d'auteur et ses droits moraux sur les livrables.
Intérêt de retard : 2 % par mois sur toute somme impayée.
"""


def _contract(text):
    return _by_id(rules.screen(rules.resolve("qc-service-contract", "2026-10-19"), text)[0])


def test_a_service_contract_stating_the_yearly_rate_and_waiving_moral_rights_passes():
    findings = _contract(QC_CONTRACT_CLEAN)
    assert all(f["verdict"] == rules.PASS for f in findings.values()), {k: v["verdict"] for k, v in findings.items()}


def test_a_service_contract_assigning_moral_rights_and_a_monthly_rate_is_flagged():
    findings = _contract(QC_CONTRACT_DEFECTIVE)
    failed = {k for k, v in findings.items() if v["verdict"] == rules.FAIL}
    assert failed == {"QC-SVC-001", "QC-SVC-002", "QC-SVC-004"}


def test_assigning_copyright_in_silence_on_moral_rights_is_only_advice():
    text = "Le prestataire cède au client tous les droits d'auteur sur les livrables. Signé à Montréal."
    findings = _contract(text)
    assert findings["QC-SVC-003"]["verdict"] == rules.FAIL and findings["QC-SVC-003"]["severity"] == "ADVISORY"
    assert findings["QC-SVC-002"]["verdict"] == rules.PASS


def test_the_contract_ruleset_says_what_it_does_not_encode_and_cites_the_federal_texts_only():
    ruleset = rules.resolve("qc-service-contract", "2026-10-19")
    assert "Code civil du Québec" in ruleset["reviewNote"] and "non-concurrence" in ruleset["reviewNote"]
    assert ruleset["reviewStatus"] == "TO_REVIEW_BY_LAWYER"
    assert all(("Loi sur l'intérêt" in r["citation"] or "droit d'auteur" in r["citation"]) for r in ruleset["rules"])
    assert not [r for r in ruleset["rules"] if r["method"] == "JUDGMENT"]


# --- qc-invoice reads layouts as they come out of a PDF or a table (orazaka-packs#81) -----------------------------------
#
# The false FAILs of the Krizaka review (2026-10-21): a total or a tax amount separated from its label by a column of
# spaces or a bracketed calculation, and a label and its value on separate lines (the text layer of a table). The
# fixtures are the layouts themselves, reproduced with demo values: the bilingual template's aligned block and Akinaza's
# own invoice KZ-00004. The finding's evidence stays the exact passage of the document.

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "qc-invoice"


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_a_total_after_a_column_of_spaces_and_a_tax_after_a_bracketed_calculation_are_found():
    total = "TOTAL À PAYER / TOTAL AMOUNT DUE ($CAD) :" + " " * 37 + "4 024,13 $CAD"
    tax = "TPS / GST (5,000 %) [Calcul : 3 500,00 $ * 0,05] :" + " " * 30 + "175,00 $CAD"
    found = _invoice(total + "\n" + tax + "\n")
    assert found["QC-INV-002"]["verdict"] == rules.PASS and found["QC-INV-007"]["verdict"] == rules.PASS
    # The evidence is the exact passage, spaces and brackets included, with offsets into the document as given.
    document = total + "\n" + tax + "\n"
    for rule_id, passage, amount in (("QC-INV-002", total, "4 024,13 $"), ("QC-INV-007", tax, "175,00 $")):
        span = found[rule_id]["evidenceSpan"]
        assert document[span["start"]:span["end"]].strip() == span["quote"]
        assert span["quote"] in passage and span["quote"].endswith(amount)
    # The column of padding and the bracketed calculation are in the quote: it is the document's own words, not the read form.
    assert " " * 30 in found["QC-INV-007"]["evidenceSpan"]["quote"] and "[Calcul : 3 500,00 $ * 0,05]" in found["QC-INV-007"]["evidenceSpan"]["quote"]


# Cases of layout, per rule. They live here and not in the ruleset's `fixtures`: the installer reads those raw, with no
# knowledge of `textLayout`, to prove each pattern can both pass and fail; these are how the engine READS a layout.
LAYOUT_CASES = {
    "QC-INV-001": (["Date\n27 août 2026", "Date de la facture\n2026-10-21"], ["Date\nà confirmer", "Date d'échéance\n2026-11-11"]),
    "QC-INV-002": (["TOTAL À PAYER / TOTAL AMOUNT DUE ($CAD) :" + " " * 37 + "4 024,13 $CAD", "Total (CAD)\n6 093,68 $"], ["Sous-total\n1 000,00 $", "Total des taxes\n149,75 $"]),
    "QC-INV-007": (["TPS / GST (5,000 %) [Calcul : 3 500,00 $ * 0,05] :" + " " * 30 + "175,00 $CAD", "TPS (5 %)\n265,00 $"], ["TPS\nà calculer", "TPS\n123456789 RT0001"]),
}


def test_every_layout_case_passes_or_fails_as_the_requirement_says():
    ruleset = rules.resolve("qc-invoice", "2026-10-19")
    by_id = {r["ruleId"]: r for r in ruleset["rules"]}
    for rule_id, (passing, failing) in LAYOUT_CASES.items():
        for text in passing:
            assert rules.evaluate(ruleset, by_id[rule_id], text)["verdict"] == rules.PASS, (rule_id, text)
        for text in failing:
            assert rules.evaluate(ruleset, by_id[rule_id], text)["verdict"] == rules.FAIL, (rule_id, text)


def test_the_installer_reads_fixtures_raw_so_they_stay_readable_without_the_layout():
    """The platform's installer (RulesetFixtureValidator) evaluates `fixtures` with the bare pattern: every fixture of this
    ruleset must keep discriminating that way, whatever `textLayout` adds on top."""
    import re
    ruleset = rules.resolve("qc-invoice", "2026-10-19")
    for rule in ruleset["rules"]:
        pattern = re.compile(rule["check"]["pattern"])
        required = rule["check"]["type"] == "REQUIRED_PATTERN"
        for text in _as_list(rule["fixtures"]["pass"]):
            assert (pattern.search(text) is not None) == required, (rule["ruleId"], text)
        for text in _as_list(rule["fixtures"]["fail"]):
            assert (pattern.search(text) is not None) != required, (rule["ruleId"], text)


def test_an_english_sub_total_is_not_the_total():
    # The bilingual block's « SUB-TOTAL (EXCLUDING TAXES) » line satisfied QC-INV-002 by itself: a document with no total passed.
    no_total = _fixture("krizaka-bilingual-aligned.txt").replace("TOTAL À PAYER / TOTAL AMOUNT DUE ($CAD) :" + " " * 37 + "4 024,13 $CAD", "")
    assert _invoice(no_total)["QC-INV-002"]["verdict"] == rules.FAIL
    assert _invoice(_fixture("krizaka-bilingual-aligned.txt"))["QC-INV-002"]["evidenceSpan"]["quote"].startswith("TOTAL À PAYER")


def test_the_bilingual_template_block_passes_every_rule_as_laid_out():
    found = _invoice(_fixture("krizaka-bilingual-aligned.txt"))
    assert {k: v["verdict"] for k, v in found.items()} == {f"QC-INV-00{n}": rules.PASS for n in range(1, 9)}


def test_akinaza_kz_00004_is_read_label_over_value_and_fails_only_on_its_real_gap():
    found = _invoice(_fixture("akinaza-kz-00004-tabular.txt"))
    failed = {k for k, v in found.items() if v["verdict"] == rules.FAIL}
    # The date, the total and the taxes are printed: the layout must not hide them. The invoice had no payment terms
    # (krizaka/akinaza#113): that one is a real gap, and the only one.
    assert failed == {"QC-INV-008"}, {k: v["verdict"] for k, v in found.items()}
    assert found["QC-INV-001"]["evidenceSpan"]["quote"].replace("\n", " ") == "Date 27 août 2026"
    assert found["QC-INV-002"]["evidenceSpan"]["quote"].replace("\n", " ") == "Total (CAD) 6 093,68 $"


def test_akinaza_with_its_payment_terms_passes_every_rule():
    found = _invoice(_fixture("akinaza-with-terms-tabular.txt"))
    assert {k: v["verdict"] for k, v in found.items()} == {f"QC-INV-00{n}": rules.PASS for n in range(1, 9)}


def test_reading_a_layout_never_turns_an_absence_into_a_pass():
    # A label with nothing to it, or with the wrong kind of value, must still fail; joining lines is not inventing evidence.
    for text, rule_id in (
        ("Date\nà confirmer\n", "QC-INV-001"),
        ("Date d'échéance\n2026-11-11\n", "QC-INV-001"),
        ("Sous-total\n1 000,00 $\n", "QC-INV-002"),
        ("Total des taxes\n149,75 $\n", "QC-INV-002"),
        ("Total\nà venir\n", "QC-INV-002"),
        ("TPS\nà calculer\n", "QC-INV-007"),
        ("TPS\n123456789 RT0001\n", "QC-INV-007"),
        ("Total\n\n1 149,75 $\n", "QC-INV-002"),  # a blank line is a paragraph, not a table cell
    ):
        assert _invoice(text)[rule_id]["verdict"] == rules.FAIL, text


def test_a_bracketed_placeholder_is_not_evidence_and_does_not_hide_one():
    # « [NE 9 chiffres] RT 0001 » is a template placeholder: the number is still missing.
    assert _invoice("TPS : [NE 9 chiffres] RT 0001\n")["QC-INV-003"]["verdict"] == rules.FAIL
    # A calculation in brackets must not be taken for the tax amount itself.
    assert _invoice("TPS [Calcul : 3 500,00 $ * 0,05]\n")["QC-INV-007"]["verdict"] == rules.FAIL


def test_the_layout_reading_is_the_invoice_rulesets_and_says_so_in_its_revision():
    ruleset = rules.resolve("qc-invoice", "2026-10-19")
    assert ruleset["revision"] == 2 and "81" in ruleset["revisionNote"]
    assert ruleset["textLayout"] == {"collapseSpaces": True, "dropBracketed": True, "joinValueLines": True}
    # Other rulesets read the text as given: a lease clause is not a table.
    assert "textLayout" not in rules.resolve("qc-residential-lease", "2026-10-15")


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
