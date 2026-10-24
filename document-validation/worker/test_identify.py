#!/usr/bin/env python3
"""Stage 1 of ADR-089, tested: what a document IS, before any ruleset judges it (orazaka-packs#129).

Run: python3 test_identify.py   (or: python3 -m pytest test_identify.py -q)

`identify` is a pure function of (text, declared kind, jurisdiction, asOf, today) over the kinds in
`kinds/*.json`: no model, no broker, no clock of its own. Every document below is fictional and written for this
suite; no real template, form or agreement is quoted.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import identify  # noqa: E402
import rules  # noqa: E402

KINDS = Path(__file__).resolve().parent.parent / "kinds"
TODAY = "2026-10-24"


def read(kind_id: str, name: str) -> str:
    return (KINDS / "fixtures" / kind_id / name).read_text(encoding="utf-8")


def ident(text, **kwargs):
    kwargs.setdefault("today", TODAY)
    return identify.identify(text, **kwargs)


def all_kinds():
    return identify.load_kinds()


# --- The kinds, as data ------------------------------------------------------------------------------------------

def test_the_kinds_the_adr_names_are_shipped():
    ids = {k["kindId"] for k in all_kinds()}
    assert ids >= {
        "qc-residential-lease", "qc-visit-notice", "qc-condition-report", "qc-lease-modification-notice",
        "qc-invoice", "qc-service-contract", "fr-residential-lease", "be-residential-lease",
    }


def test_each_kind_file_is_named_by_its_kind_and_is_coherent():
    for path in sorted(KINDS.glob("*.json")):
        if path.name == "kind.schema.json":
            continue
        kind = json.loads(path.read_text(encoding="utf-8"))
        assert path.stem == kind["kindId"], f"{path.name}: the file is named by its kindId"
        assert kind["kindId"].startswith(kind["jurisdiction"].split("-")[0].lower() + "-"), f"{path.name}: kindId starts with its jurisdiction"
        ids = [s["id"] for s in kind["signals"] + kind["jurisdictionHints"]]
        assert len(ids) == len(set(ids)), f"{path.name}: signal ids are unique"
        for pattern in [s["pattern"] for s in kind["signals"] + kind["jurisdictionHints"] + kind["dateSignals"]] + kind["excludes"]:
            re.compile(pattern)  # a pattern that does not compile fails here, not on a user's document
        for date_signal in kind["dateSignals"]:
            assert re.compile(date_signal["pattern"]).groups >= 1, f"{path.name}: {date_signal['id']} captures the date"
        if kind["asOfFrom"] is not None:
            assert kind["asOfFrom"] in [d["id"] for d in kind["dateSignals"]], f"{path.name}: asOfFrom names a date signal"


def test_a_promoted_kind_has_a_ruleset_that_exists_and_a_known_kind_has_none():
    for kind in all_kinds():
        if kind["status"] == "PROMOTED":
            assert kind["ruleset"], kind["kindId"]
            assert (Path(rules.RULESETS_DIR) / kind["ruleset"]).is_dir(), f"{kind['kindId']}: no ruleset {kind['ruleset']}"
            assert rules.rulesets_by_jurisdiction()[kind["jurisdiction"]].count(kind["ruleset"]) == 1
        elif kind["status"] == "KNOWN":
            assert kind["ruleset"] is None, f"{kind['kindId']} is only KNOWN: no ruleset yet"


def test_no_ruleset_is_orphaned_by_the_kinds():
    shipped = {r for ids in rules.rulesets_by_jurisdiction().values() for r in ids}
    used = {k["ruleset"] for k in all_kinds() if k["ruleset"]}
    assert shipped <= used, f"rulesets with no kind: {sorted(shipped - used)}"


# --- ADR-072 applied to kinds: every kind's own fixtures, and every signal's pass/fail pair ------------------------

def test_every_declared_fixture_gives_its_recorded_identification():
    seen = 0
    for kind in all_kinds():
        for fixture in kind["fixtures"]:
            text = (KINDS / fixture["file"]).read_text(encoding="utf-8")
            got = ident(text)
            where = f"{kind['kindId']} / {fixture['file']}"
            if fixture["expect"] == "MATCH":
                assert got["detectedKind"] == kind["kindId"], f"{where}: detected {got['detectedKind']} ({got['candidates']})"
                assert got["jurisdiction"] == kind["jurisdiction"], where
                assert got["documentDate"] == fixture["documentDate"], f"{where}: date {got['documentDate']}"
                assert got["asOfSource"] == ("DOCUMENT" if fixture["documentDate"] else "TODAY"), where
                if fixture.get("language"):
                    assert fixture["language"] in got["languages"], f"{where}: {got['languages']}"
                assert got["outcome"] == ("CHECK" if kind["status"] == "PROMOTED" else "UNSUPPORTED_KIND"), where
            else:
                assert got["detectedKind"] != kind["kindId"], f"{where}: must not be {kind['kindId']}"
            seen += 1
    assert seen >= 25, seen


def test_every_signal_hits_a_fixture_of_its_kind_and_misses_another_document():
    corpus, owner = {}, {}
    for kind in all_kinds():
        for fixture in kind["fixtures"]:
            corpus[fixture["file"]] = (KINDS / fixture["file"]).read_text(encoding="utf-8")
            if fixture["expect"] == "MATCH":
                owner[fixture["file"]] = kind["kindId"]
    for kind in all_kinds():
        own = [corpus[f["file"]] for f in kind["fixtures"] if f["expect"] == "MATCH"]
        for signal in kind["signals"]:
            compiled = re.compile(signal["pattern"])
            assert any(compiled.search(t) for t in own), f"{kind['kindId']}.{signal['id']}: no fixture of the kind carries it"
            assert not all(compiled.search(t) for t in corpus.values()), f"{kind['kindId']}.{signal['id']}: carried by every document, it tells nothing"
            foreign = [t for f, t in corpus.items() if f in owner and owner[f] != kind["kindId"]]
            if signal["weight"] >= 2:
                assert not any(compiled.search(t) for t in foreign), f"{kind['kindId']}.{signal['id']}: a title found in another kind's document"


# --- The documents of the issue ----------------------------------------------------------------------------------

def test_a_filled_visit_notice_is_a_visit_notice_in_both_languages_and_never_a_lease():
    for name, lang in (("fr-filled.txt", "fr"), ("en-filled.txt", "en")):
        got = ident(read("qc-visit-notice", name))
        assert got["detectedKind"] == got["kindUsed"] == "qc-visit-notice"
        assert got["kindSource"] == "DETECTED" and got["kindMismatch"] is False
        assert got["documentDate"] == "2026-10-20" == got["asOf"] and got["asOfSource"] == "DOCUMENT"
        assert got["languages"] == [lang]
        assert got["jurisdiction"] == "QC" and got["jurisdictionSource"] == "DETECTED"


def test_the_blank_forms_are_their_kind_not_a_lease_and_have_no_date():
    blanks = [("qc-visit-notice", "fr-blank.txt"), ("qc-visit-notice", "en-blank.txt"),
              ("qc-condition-report", "fr-blank.txt"), ("qc-condition-report", "en-blank.txt"),
              ("qc-residential-lease", "fr-blank.txt"), ("qc-invoice", "fr-blank.txt"), ("qc-service-contract", "fr-blank.txt")]
    for kind_id, name in blanks:
        got = ident(read(kind_id, name))
        assert got["kindUsed"] == kind_id, f"{kind_id}/{name}: {got['kindUsed']}"
        assert got["documentDate"] is None and got["asOfSource"] == "TODAY" and got["asOf"] == TODAY, f"{kind_id}/{name}: an unfilled date is not a date"


def test_a_notice_or_a_condition_report_is_never_judged_by_the_lease():
    for kind_id in ("qc-visit-notice", "qc-condition-report"):
        for name in ("fr-filled.txt", "en-filled.txt", "fr-blank.txt", "en-blank.txt"):
            got = ident(read(kind_id, name), declared_kind="LEASE", jurisdiction="QC")
            assert got["kindUsed"] == kind_id and got["ruleset"] is None and got["outcome"] == "UNSUPPORTED_KIND", f"{kind_id}/{name}"


def test_a_condition_report_is_a_condition_report_in_both_languages():
    for name in ("fr-filled.txt", "en-filled.txt"):
        got = ident(read("qc-condition-report", name))
        assert got["kindUsed"] == "qc-condition-report" and got["documentDate"] == "2026-09-01"


def test_a_filled_lease_invoice_and_service_contract_are_found_and_promoted():
    cases = [("qc-residential-lease", "fr-filled.txt", "2026-06-12"), ("qc-residential-lease", "en-filled.txt", "2026-06-12"),
             ("qc-invoice", "fr-filled.txt", "2026-10-14"), ("qc-invoice", "en-filled.txt", "2026-10-14"),
             ("qc-service-contract", "fr-filled.txt", "2026-10-14"), ("qc-service-contract", "en-filled.txt", "2026-10-14")]
    for kind_id, name, day in cases:
        got = ident(read(kind_id, name))
        assert got["kindUsed"] == kind_id and got["outcome"] == "CHECK" and got["ruleset"] == kind_id, f"{kind_id}/{name}"
        assert got["documentDate"] == day and got["asOf"] == day


def test_the_other_jurisdictions_leases_are_their_own_kind():
    fr = ident(read("fr-residential-lease", "filled.txt"))
    be = ident(read("be-residential-lease", "filled.txt"))
    assert (fr["kindUsed"], fr["jurisdiction"], fr["ruleset"]) == ("fr-residential-lease", "FR", "fr-residential-lease")
    assert (be["kindUsed"], be["jurisdiction"], be["ruleset"]) == ("be-residential-lease", "BE-WAL", "be-residential-lease")


def test_the_existing_ruleset_fixtures_are_identified_as_the_kind_their_ruleset_judges():
    fixtures = Path(__file__).resolve().parent / "fixtures"
    for ruleset_dir in sorted(p for p in fixtures.iterdir() if p.is_dir() and p.name != "document-profiles"):
        for doc in sorted(ruleset_dir.glob("*.txt")):
            got = ident(doc.read_text(encoding="utf-8"))
            assert got["kindUsed"] == ruleset_dir.name, f"{ruleset_dir.name}/{doc.name}: {got['kindUsed']} {got['candidates']}"


# --- The declared kind -------------------------------------------------------------------------------------------

def test_a_declared_lease_on_a_visit_notice_is_a_surfaced_mismatch_and_judges_as_a_notice():
    got = ident(read("qc-visit-notice", "en-filled.txt"), declared_kind="LEASE")
    assert got["declaredKind"] == "LEASE" and got["detectedKind"] == "qc-visit-notice"
    assert got["kindMismatch"] is True
    assert got["kindUsed"] == "qc-visit-notice" and got["kindSource"] == "DETECTED"
    assert got["outcome"] == "UNSUPPORTED_KIND" and got["ruleset"] is None, "a notice is never judged by the lease"
    assert got["kindEvidence"] and all(e["verified"] for e in got["kindEvidence"])


def test_a_declared_kind_that_agrees_is_no_mismatch():
    got = ident(read("qc-residential-lease", "fr-filled.txt"), declared_kind="LEASE")
    assert got["kindMismatch"] is False and got["kindUsed"] == "qc-residential-lease"
    got = ident(read("qc-visit-notice", "fr-filled.txt"), declared_kind="NOTICE")
    assert got["kindMismatch"] is False
    got = ident(read("qc-visit-notice", "fr-filled.txt"), declared_kind="OTHER")
    assert got["kindMismatch"] is False, "the kind lists OTHER among what it agrees with"


def test_a_declared_invoice_on_a_lease_is_a_mismatch_too():
    got = ident(read("qc-residential-lease", "fr-filled.txt"), declared_kind="INVOICE")
    assert got["kindMismatch"] is True and got["kindUsed"] == "qc-residential-lease" and got["outcome"] == "CHECK"


def test_the_evidence_is_the_passage_of_the_document():
    text = read("qc-visit-notice", "fr-filled.txt")
    got = ident(text)
    quotes = [e["quote"] for e in got["kindEvidence"]]
    assert any("AVIS DE VISITE" in q for q in quotes)
    assert all(q in text and e["verified"] for q, e in zip(quotes, got["kindEvidence"]))


# --- Ambiguity and unknown ---------------------------------------------------------------------------------------

def test_a_document_matching_two_kinds_equally_is_kind_unknown_not_a_guess():
    got = ident(read("_unknown", "ambiguous.txt"))
    assert got["outcome"] == "KIND_UNKNOWN" and got["kindUsed"] is None and got["detectedKind"] is None
    tied = {c["kindId"] for c in got["candidates"] if c["eligible"]}
    assert tied >= {"qc-invoice", "qc-service-contract"}
    assert got["ruleset"] is None


def test_an_ambiguous_document_takes_the_declared_kind_when_it_names_exactly_one_kind():
    text = read("_unknown", "ambiguous.txt")
    got = ident(text, declared_kind="SERVICE_CONTRACT")
    assert got["kindUsed"] == "qc-service-contract" and got["kindSource"] == "DECLARED" and got["outcome"] == "CHECK"
    assert got["kindMismatch"] is False
    assert ident(text, declared_kind="OTHER")["outcome"] == "KIND_UNKNOWN", "OTHER names no single kind"
    assert ident(text, declared_kind="LEASE")["outcome"] == "KIND_UNKNOWN", "LEASE names three kinds when no jurisdiction is declared"
    # The declared kind breaks a tie only when it names one of the TIED kinds (packs#129, point 1): a lease declared on
    # a text that ties an invoice and a service contract is never judged as a lease.
    assert ident(text, declared_kind="LEASE", jurisdiction="QC")["outcome"] == "KIND_UNKNOWN"
    assert ident("Bail.", declared_kind="LEASE", jurisdiction="QC")["kindUsed"] == "qc-residential-lease", "no candidate: the declared kind"


def test_a_text_that_is_none_of_the_kinds_is_kind_unknown():
    got = ident(read("_unknown", "unrelated.txt"))
    assert got["outcome"] == "KIND_UNKNOWN" and got["kindUsed"] is None and got["jurisdiction"] is None
    assert ident("")["outcome"] == "KIND_UNKNOWN"


def test_a_weak_signal_alone_does_not_detect_a_kind():
    assert ident("Rappel : la visite a lieu dans 24 heures.")["outcome"] == "KIND_UNKNOWN"
    only_hints = "Montréal (Québec) H2X 1Y4, selon le C.c.Q."
    assert ident(only_hints)["outcome"] == "KIND_UNKNOWN", "jurisdiction hints alone never name a kind"


def test_the_minimum_weight_is_a_parameter():
    text = read("qc-visit-notice", "fr-blank.txt")
    assert ident(text, min_signal_weight=2)["kindUsed"] == "qc-visit-notice"
    assert ident(text, min_signal_weight=9)["outcome"] == "KIND_UNKNOWN"


def test_an_exclusion_disqualifies_the_kind():
    with_rent = read("qc-visit-notice", "fr-filled.txt") + "\nLoyer mensuel : 1 120 $\n"
    got = ident(with_rent)
    assert got["detectedKind"] != "qc-visit-notice"
    excluded = {c["kindId"] for c in got["candidates"] if c["excluded"]}
    assert "qc-visit-notice" in excluded


def test_a_lease_that_mentions_a_visit_is_still_a_lease():
    got = ident(read("qc-visit-notice", "no-match-lease-with-visit-clause.txt"))
    assert got["kindUsed"] == "qc-residential-lease"


# --- Jurisdiction ------------------------------------------------------------------------------------------------

def test_a_declared_jurisdiction_restricts_the_kinds_and_is_reported_as_declared():
    got = ident(read("qc-visit-notice", "fr-filled.txt"), jurisdiction="QC")
    assert got["jurisdiction"] == "QC" and got["jurisdictionSource"] == "DECLARED" and got["kindUsed"] == "qc-visit-notice"


def test_a_declared_jurisdiction_never_borrows_another_countrys_kinds():
    got = ident(read("qc-visit-notice", "fr-filled.txt"), jurisdiction="FR")
    assert got["outcome"] == "KIND_UNKNOWN" and got["jurisdiction"] == "FR" and got["kindUsed"] is None
    unknown = ident(read("qc-visit-notice", "fr-filled.txt"), jurisdiction="ZZ")
    assert unknown["outcome"] == "KIND_UNKNOWN"


def test_the_jurisdiction_hints_name_the_jurisdiction_of_a_text_no_kind_decided():
    got = ident("Document sans titre.\nTribunal administratif du logement, Montréal (Québec) H2X 1Y4, C.c.Q.")
    assert got["kindUsed"] is None and got["jurisdiction"] == "QC" and got["jurisdictionSource"] == "DETECTED"


# --- asOf --------------------------------------------------------------------------------------------------------

def test_an_as_of_given_by_the_caller_wins_over_the_document_date():
    got = ident(read("qc-visit-notice", "fr-filled.txt"), as_of="2026-01-15")
    assert got["asOf"] == "2026-01-15" and got["asOfSource"] == "INPUT"
    assert got["documentDate"] == "2026-10-20", "the date of the document is still reported"


def test_dates_are_read_in_french_and_english_wording_and_an_impossible_date_is_not_a_date():
    assert ident(read("qc-residential-lease", "fr-filled.txt"))["documentDate"] == "2026-06-12"
    assert ident(read("qc-residential-lease", "en-filled.txt"))["documentDate"] == "2026-06-12"
    bad = read("qc-visit-notice", "fr-filled.txt").replace("2026-10-20", "2026-13-45")
    got = ident(bad)
    assert got["documentDate"] is None and got["asOfSource"] == "TODAY"


def test_the_date_comes_with_its_passage():
    got = ident(read("qc-invoice", "fr-filled.txt"))
    assert got["dateEvidence"]["signal"] == "invoice-date" and "2026-10-14" in got["dateEvidence"]["quote"]
    assert ident(read("qc-visit-notice", "fr-blank.txt"))["dateEvidence"] is None


# --- Language ----------------------------------------------------------------------------------------------------

def test_the_language_is_a_fact_french_english_or_both():
    assert ident(read("qc-invoice", "fr-filled.txt"))["languages"] == ["fr"]
    assert ident(read("qc-invoice", "en-filled.txt"))["languages"] == ["en"]
    both = read("qc-visit-notice", "fr-filled.txt") + "\n" + read("qc-visit-notice", "en-filled.txt")
    assert ident(both)["languages"] == ["en", "fr"]
    assert ident("12 345")["languages"] == []


def test_an_english_lease_is_reported_in_english_so_the_language_rules_can_see_it():
    got = ident(read("qc-residential-lease", "en-filled.txt"))
    assert got["kindUsed"] == "qc-residential-lease" and got["languages"] == ["en"]


# --- An explicit ruleset, determinism, no model --------------------------------------------------------------------

def test_an_explicit_ruleset_overrides_everything_and_is_reported_as_such():
    got = ident(read("qc-visit-notice", "fr-filled.txt"), declared_kind="LEASE", ruleset="qc-residential-lease", jurisdiction="QC")
    assert got["kindSource"] == "RULESET_INPUT" and got["kindUsed"] == "qc-residential-lease" and got["outcome"] == "CHECK"
    assert got["ruleset"] == "qc-residential-lease" and got["kindMismatch"] is False
    assert got["detectedKind"] == "qc-visit-notice", "what the text is stays reported"


def test_an_unknown_ruleset_name_is_refused_by_name():
    try:
        ident("x", ruleset="qc-nothing", jurisdiction="QC")
    except identify.UnknownRuleset as bad:
        assert "qc-nothing" in str(bad)
    else:
        raise AssertionError("an unknown ruleset must not fall back to anything")


def test_the_same_input_gives_the_same_identification():
    text = read("qc-visit-notice", "en-filled.txt")
    assert ident(text, declared_kind="LEASE") == ident(text, declared_kind="LEASE")


def test_identify_calls_no_model_and_reads_no_clock_without_being_asked():
    source = Path(identify.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M))
    # `quotes` is this pack's own pure comparison of a quote with a text (no model, no clock, no network).
    assert imported <= {"json", "os", "re", "unicodedata", "datetime", "__future__", "quotes"}, imported
    assert "time.time" not in source and "now()" not in source


# --- The worker's capability ---------------------------------------------------------------------------------------

def test_the_worker_serves_identify_under_its_routing_key_and_the_pack_declares_it():
    import yaml
    import validation_worker
    assert validation_worker.HANDLERS["job.validation.identify"] is validation_worker._identify
    pack = yaml.safe_load((KINDS.parent / "pack.yaml").read_text(encoding="utf-8"))
    capability = next(c for c in pack["requires"]["capabilities"] if c["key"] == "orazaka.validation.document.identify")
    assert capability["routingKey"] == "job.validation.identify" and capability["handlerKey"] == "validation.identify"
    assert capability["inputSchema"]["required"] == ["document"]
    produced = set(capability["outputSchema"]["properties"])
    result = validation_worker._identify({"document": read("qc-visit-notice", "en-filled.txt"), "declaredKind": "LEASE", "asOf": ""})
    assert produced >= set(result), set(result) - produced
    assert json.loads(result["identificationJson"])["kindMismatch"] is True
    assert set(capability["outputSchema"]["required"]) <= set(result)


def test_the_worker_refuses_an_empty_document_and_a_malformed_date_by_name():
    import validation_worker
    for payload in ({"document": ""}, {"document": "x", "asOf": "yesterday"}):
        try:
            validation_worker._identify(payload)
        except validation_worker.InvalidJobPayload:
            continue
        raise AssertionError(f"{payload} must be refused as INPUT_INVALID")


# --- Stage 2: the retrieval a kind asks for (ADR-089 §2, orazaka-ai-engine#81) -------------------------------------

def _kind(kind_id):
    return next(k for k in all_kinds() if k["kindId"] == kind_id)


def test_a_visit_notice_asks_for_art_1931_to_1933_and_no_rent_article():
    request = identify.retrieval_request(_kind("qc-visit-notice"), "fr", "2026-10-20")
    assert request["sources"] == ["law-corpus"]
    assert request["jurisdiction"] == "QC" and request["asOf"] == "2026-10-20" and request["language"] == "fr"
    assert request["targets"] == [{"instrument": "CCQ-1991", "refs": ["1931", "1932", "1933"]}]
    assert request["question"] == "Quels articles régissent un avis de visite d'un logement au Québec ?"
    refs = {int(r) for t in request["targets"] for r in t["refs"]}
    assert not refs & (set(range(1903, 1909)) | set(range(1936, 1956))), "no rent article"


def test_the_question_is_in_the_language_asked():
    en = identify.retrieval_request(_kind("qc-visit-notice"), "en", "2026-10-20")
    assert en["question"].startswith("Which articles govern a notice of visit")


def test_a_retrieval_is_refused_by_name_not_guessed():
    for kind, language, as_of in (
        (_kind("qc-invoice"), "fr", "2026-10-20"),                  # no retrieval block
        (_kind("qc-visit-notice"), "de", "2026-10-20"),             # not fr/en
        (_kind("qc-visit-notice"), "fr", "yesterday"),              # not ISO
        (_kind("qc-visit-notice"), "fr", ""),
    ):
        try:
            identify.retrieval_request(kind, language, as_of)
        except ValueError:
            continue
        raise AssertionError(f"{kind['kindId']} {language} {as_of!r} must be refused")


def test_every_retrieval_names_only_what_the_kind_is_judged_by():
    for kind in all_kinds():
        retrieval = kind.get("retrieval")
        if not retrieval:
            continue
        assert kind["jurisdiction"] == "QC", "the corpus holds Québec and federal law; a kind targets its own"
        for target in retrieval["targets"]:
            assert target["refs"] and len(set(target["refs"])) == len(target["refs"]), kind["kindId"]


def test_the_request_has_exactly_the_keys_the_engine_reads():
    # orazaka-ai-engine LawRetrievalRequest: jurisdiction, kindId, question, language, asOf, targets{instrument, refs}.
    request = identify.retrieval_request(_kind("qc-condition-report"), "fr", "2026-10-20", run_id="r-1")
    assert set(request) == {"sources", "jurisdiction", "kindId", "asOf", "language", "question", "targets", "runId"}
    assert set(request["targets"][0]) == {"instrument", "refs"}


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL {name}: {exc!r}")
    print(f"\n{'FAILED' if failures else 'all green'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)
