#!/usr/bin/env python3
"""``compliance-check`` 2.0 (ADR-089 §4), run step by step from its own blueprint (orazaka-studio#80).

Run: python3 test_check.py   (or: python3 -m pytest test_check.py -q)

``run`` reads ``studios/compliance-check/blueprint.json`` and plays it the way the saga does: each step in order, its
``condition`` evaluated, its inputs rendered from the templates, its featureKey sent to the handler of the routing key
``pack.yaml`` declares — and the model steps answered by the test, which counts them. The report step's output is held
to the ``outputContract`` the blueprint declares, with the keywords the platform enforces (orazaka-studio#59).

Every document is fictional. The two leases are yomizaka#305's recordings: the demo generator's text and the report
dev returned under 1.x, kept here as they were recorded.
"""
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import citations  # noqa: E402
import compliance  # noqa: E402
import rules  # noqa: E402
import validation_worker as worker  # noqa: E402

PACK = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
KIND_FIXTURES = PACK / "kinds" / "fixtures"
BLUEPRINT = json.loads((PACK / "studios" / "compliance-check" / "blueprint.json").read_text(encoding="utf-8"))
ROUTES = {c["key"]: c["routingKey"] for c in yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))["requires"]["capabilities"]}
CHAT = "orazaka.core.chat.completion"
GROUNDED = "orazaka.core.research.grounded"
TEST_ARTICLES = citations.load_articles(str(FIXTURES / "law"))


# --- The saga, played from the blueprint -------------------------------------------------------------------------------

_REF = re.compile(r"^\{\{([^{}:]+)(?::([^{}]*))?}}$")
_CONDITION = re.compile(r"^\s*(\{\{[^{}]*}})\s*(==|!=)\s*(.+?)\s*$")


def _value(template: str, inputs: dict, steps: dict):
    match = _REF.match(template)
    assert match, f"not a single reference: {template}"
    path, default = match.group(1).split("."), match.group(2)
    scope = inputs if path[0] == "inputs" else steps.get(path[1]) if path[0] == "steps" else None
    keys = path[1:] if path[0] == "inputs" else path[2:]
    for key in keys:
        scope = scope.get(key) if isinstance(scope, dict) else None
    return scope if scope is not None else default


def _holds(condition: str, inputs: dict, steps: dict) -> bool:
    ref, operator, literal = _CONDITION.match(condition).groups()
    value = _value(ref, inputs, steps)
    rendered = None if value is None else (str(value).lower() if isinstance(value, bool) else str(value))
    return (rendered == literal.strip("'\"")) == (operator == "==")


def run(document: str, *, judge=None, classify=None, grounded=None, **inputs) -> tuple:
    """The 2.0 report of ``document`` and the model calls the run made, as ``[step id, …]``.

    ``grounded`` answers the lecture's grounded call (ADR-089 §6): a function of the step's inputs returning the claims.
    """
    inputs = {"document": document, **inputs}
    steps, calls, answers = {}, [], {"judge": judge, "classify": classify}
    for step in BLUEPRINT["definition"]["steps"]:
        if step.get("condition") and not _holds(step["condition"], inputs, steps):
            continue
        payload = {name: _value(t, inputs, steps) for name, t in step["inputs"].items()}
        if step["featureKey"] == GROUNDED:
            calls.append(step["id"])
            steps[step["out"]] = {"claims": json.dumps(grounded(payload) if callable(grounded) else (grounded or []), ensure_ascii=False)}
            continue
        if step["featureKey"] == CHAT:
            calls.append(step["id"])
            answer = answers[step["id"]]
            steps[step["out"]] = {"content": answer(payload["prompt"]) if callable(answer) else (answer or "")}
            continue
        result, _ = worker._handle(ROUTES[step["featureKey"]], {"payload": payload})
        if step.get("outputContract"):
            assert_conforms(step["outputContract"], json.loads(json.dumps(result)), "$")
        steps[step["out"]] = result
    return steps["report"]["report"], calls


def assert_conforms(schema: dict, value, path: str) -> None:
    """The keywords the platform enforces on a step output (orazaka-studio OutputContract), and only those."""
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}
    if "type" in schema:
        assert isinstance(value, kinds[schema["type"]]), f"{path}: must be {schema['type']}"
    if "enum" in schema:
        assert value in schema["enum"], f"{path}: {value!r} is not one of the declared values"
    if isinstance(value, str) and "minLength" in schema:
        assert len(value) >= schema["minLength"], f"{path}: minLength"
    if isinstance(value, list):
        for i, item in enumerate(value):
            assert_conforms(schema.get("items", {}), item, f"{path}[{i}]")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            assert name in value, f"{path}.{name}: required"
        for name, item in value.items():
            if name in schema.get("properties", {}):
                assert_conforms(schema["properties"][name], item, f"{path}.{name}")
            elif schema.get("additionalProperties") is False:
                raise AssertionError(f"{path}.{name}: not declared and additionalProperties is false")
            else:
                assert schema.get("additionalProperties", True) is not False, f"{path}.{name}: not declared"


def recording(name: str) -> dict:
    return json.loads((FIXTURES / "compliance-check" / f"yomizaka-305-{name}.json").read_text(encoding="utf-8"))


def recorded_judge(report: dict) -> str:
    """The judge's answer that gave the recorded report: its JUDGMENT findings, as the model's JSON."""
    answer = [
        {"ruleId": f["ruleId"], "verdict": f["verdict"] if f["verdict"] != rules.NOT_APPLICABLE else rules.INSUFFICIENT_EVIDENCE,
         "quote": (f["evidenceSpan"] or {}).get("quote", "")}
        for f in report["findings"] if f["method"] == "JUDGMENT"
    ]
    return json.dumps(answer, ensure_ascii=False)


def kind_text(kind_id: str, name: str) -> str:
    return (KIND_FIXTURES / kind_id / name).read_text(encoding="utf-8")


def verdicts(report: dict) -> dict:
    return {f["ruleId"]: f["verdict"] for f in report["findings"]}


# --- yomizaka#305: the recordings stay green ------------------------------------------------------------------------

def test_the_clean_lease_raises_only_014_and_the_errors_lease_exactly_004_005_006_014_020():
    # The reports were re-recorded against revision 5 (fixtures/compliance-check/rerecord.py, 2026-10-26; no model). The
    # rule added since, QC-LEASE-014 (the Tribunal administratif du logement's mandatory form, art. 1895), correctly
    # fails yomizaka's demo "clean" text, which never mentions that form: the text stays as generated (yomizaka follow-up).
    for name, expected in (("clean", {"QC-LEASE-014"}),
                           ("errors", {"QC-LEASE-004", "QC-LEASE-005", "QC-LEASE-006", "QC-LEASE-014", "QC-LEASE-020"})):
        rec = recording(name)
        report, _ = run(rec["document"], judge=recorded_judge(rec["report"]), **rec["inputs"])
        assert report["outcome"] == compliance.CHECKED, name
        assert report["identification"]["kindUsed"] == "qc-residential-lease", name
        assert {f["ruleId"] for f in report["findings"] if f["verdict"] == rules.FAIL} == expected, name
        assert verdicts(report) == verdicts(rec["report"]), f"{name}: 2.0 gives the verdicts 1.x recorded"
        assert rec["report"]["rulesetRevision"] == 5, f"{name}: the recording is against the shipped revision"
        for finding in report["findings"]:
            if finding["evidenceSpan"]:
                assert finding["evidenceSpan"]["quote"] in rec["document"], finding["ruleId"]
            assert finding["citation"]["reference"] == next(
                r["citation"] for r in rec["report"]["findings"] if r["ruleId"] == finding["ruleId"]
            )


def test_the_errors_lease_fails_on_the_passages_yomizaka_expects():
    rec = recording("errors")
    report, _ = run(rec["document"], judge=recorded_judge(rec["report"]), **rec["inputs"])
    by_id = {f["ruleId"]: f for f in report["findings"]}
    assert by_id["QC-LEASE-004"]["evidenceSpan"]["quote"] == "dépôt de sécurité de 950,00 $"
    assert by_id["QC-LEASE-005"]["evidenceSpan"]["quote"] == "chèques postdatés"
    assert by_id["QC-LEASE-006"]["evidenceSpan"]["quote"] == "interdit d'avoir des enfants"
    assert by_id["QC-LEASE-020"]["evidenceSpan"]["quote"] == "Il est interdit d'avoir des enfants dans le logement."
    assert "1901" in by_id["QC-LEASE-020"]["citation"]["reference"]


# --- A 1.x call ---------------------------------------------------------------------------------------------------

def test_a_1x_request_answers_the_1x_shape_exactly_as_recorded():
    # The 1.x blueprint calls screen then assemble with the jurisdiction: the same worker answers it as before.
    for name in ("clean", "errors"):
        rec = recording(name)
        screened = worker._screen({"document": rec["document"], **rec["inputs"]})
        report = worker._assemble({"screened": screened["screenedJson"], "judgment": recorded_judge(rec["report"])})["report"]
        assert report == rec["report"], f"{name}: the 1.x report changed"
        assert "contract" not in report and "identification" not in report and isinstance(report["findings"][0]["citation"], str)


def test_2x_has_no_default_kind_the_lease_by_jurisdiction_is_legacy_1x_only():
    # jurisdiction QC, no kind, a text no kind recognises: 2.0 says KIND_UNKNOWN; only a pinned 1.x blueprint judges it
    # by the jurisdiction's lease (CTO, orazaka-studio#80, point 4).
    text = "Entre le locateur Monsieur Marc Tremblay, domicilié à Montréal, et la locataire Madame Léa Roy."
    report, calls = run(text, jurisdiction="QC", asOf="2026-10-22")
    assert report["outcome"] == "KIND_UNKNOWN" and report["findings"] == [] and calls == []
    assert worker._screen({"document": text, "jurisdiction": "QC", "asOf": "2026-10-22"})["rulesetId"] == "qc-residential-lease"
    # A recognised notice is never the lease's: the mismatch with a declared lease shows.
    notice, _ = run(kind_text("qc-visit-notice", "fr-filled.txt"), jurisdiction="QC", declaredKind="LEASE")
    assert notice["outcome"] == compliance.CHECKED and notice["identification"]["kindMismatch"] is True
    assert notice["ruleset"]["id"] == "qc-visit-notice", "judged as a notice, never as the declared lease"


def test_a_citation_that_pins_no_article_says_so_on_every_finding():
    rec = recording("errors")
    report, _ = run(rec["document"], judge=recorded_judge(rec["report"]), **rec["inputs"])
    for finding in report["findings"]:
        assert finding["checks"]["citation"] == "NOT_PINNED" and finding["citation"]["pinned"] is False
        assert finding["citation"]["notice"]["fr"].startswith("Citation non épinglée"), finding["ruleId"]
        assert finding["citation"]["notice"]["en"].startswith("Unpinned citation")


def test_the_2x_blueprint_is_versioned_so_pinned_1x_installations_keep_their_steps():
    assert BLUEPRINT["version"] == BLUEPRINT["definition"]["version"] == "2.1.0"
    assert ROUTES["orazaka.validation.document.screen"] == "job.validation.screen"
    assert ROUTES["orazaka.validation.document.assemble"] == "job.validation.assemble", "1.x installations still call it"


# --- Each outcome -------------------------------------------------------------------------------------------------

def test_checked_carries_identification_outcome_and_ruleset():
    rec = recording("clean")
    report, _ = run(rec["document"], judge=recorded_judge(rec["report"]), **rec["inputs"])
    assert report["contract"] == "2.0"
    assert report["ruleset"] == {"id": "qc-residential-lease", "version": "2024-02-21", "revision": 5, "reviewStatus": "TO_REVIEW_BY_LAWYER"}
    assert report["identification"]["kindSource"] == "DETECTED" and report["identification"]["asOfSource"] == "INPUT"


def test_unsupported_kind_runs_no_rule_and_never_the_lease():
    for name in ("fr-filled.txt", "en-filled.txt"):
        for kind in ("qc-lease-modification-notice",):
            report, calls = run(kind_text(kind, name), judge="[]", jurisdiction="QC")
            assert report["outcome"] == "UNSUPPORTED_KIND", (kind, name)
            assert report["identification"]["kindUsed"] == kind and report["findings"] == [], (kind, name)
            assert calls == [], "no model is asked about a kind with no ruleset"


def test_a_visit_notice_and_a_condition_report_are_checked_by_their_own_ruleset_with_a_language_finding():
    for kind in ("qc-visit-notice", "qc-condition-report"):
        for name in ("fr-filled.txt", "en-filled.txt"):
            report, calls = run(kind_text(kind, name), judge="[]", jurisdiction="QC")
            assert report["outcome"] == compliance.CHECKED and report["ruleset"]["id"] == kind, (kind, name)
            assert calls == [] and "QC-LANG-001" in {f["ruleId"] for f in report["findings"]}, (kind, name)


def test_kind_unknown_runs_no_rule():
    report, calls = run(kind_text("_unknown", "unrelated.txt"))
    assert report["outcome"] == "KIND_UNKNOWN" and report["findings"] == [] and calls == []


def test_a_tie_asks_the_model_and_keeps_its_answer_only_with_a_quote_from_the_document():
    text = kind_text("_unknown", "ambiguous.txt")
    prompts = []

    def choose(kind_id, quote):
        def answer(prompt):
            prompts.append(prompt)
            return json.dumps({"kindId": kind_id, "quote": quote})
        return answer

    kept, calls = run(text, classify=choose("qc-service-contract", "Contrat de services"), judge="[]", jurisdiction="QC", asOf="2026-10-22")
    assert calls[0] == "classify" and "qc-invoice" in prompts[0] and "OTHER" in prompts[0]
    assert kept["outcome"] == compliance.CHECKED and kept["identification"]["kindSource"] == "CLASSIFIED"
    assert kept["ruleset"]["id"] == "qc-service-contract"
    invented, _ = run(text, classify=choose("qc-service-contract", "Contrat de location d'auto"), jurisdiction="QC")
    assert invented["outcome"] == "KIND_UNKNOWN", "a quote that is not in the document is discarded"
    assert invented["identification"]["classification"]["reason"] == "QUOTE_NOT_IN_DOCUMENT"
    offered, _ = run(text, classify=choose("qc-residential-lease", "Facture"), jurisdiction="QC")
    assert offered["outcome"] == "KIND_UNKNOWN", "a kind outside the tie is never taken"
    other, _ = run(text, classify=choose("OTHER", ""), jurisdiction="QC")
    assert other["outcome"] == "KIND_UNKNOWN"
    silent, _ = run(text, classify=None, jurisdiction="QC")
    assert silent["outcome"] == "KIND_UNKNOWN", "a skipped classify step leaves the tie a tie"


def test_a_declared_kind_breaks_a_tie_only_when_it_names_one_of_the_tied_kinds():
    text = kind_text("_unknown", "ambiguous.txt")
    lease, calls = run(text, declaredKind="LEASE", jurisdiction="QC")
    assert lease["outcome"] == "KIND_UNKNOWN" and calls == ["classify"], "the lease is not one of the tied kinds"
    contract, calls = run(text, declaredKind="SERVICE_CONTRACT", jurisdiction="QC", asOf="2026-10-22", judge="[]")
    assert contract["identification"]["kindSource"] == "DECLARED" and "classify" not in calls


# --- No passage, no PASS; both quotes checked ---------------------------------------------------------------------

def test_no_report_has_a_pass_without_a_passage_of_the_document():
    documents = [recording("clean")["document"], recording("errors")["document"]]
    documents += [kind_text(k, n) for k in ("qc-residential-lease", "qc-invoice", "qc-service-contract") for n in ("fr-blank.txt",)]
    for text in documents:
        report, _ = run(text, judge="[]", jurisdiction="QC", asOf="2026-10-22")
        for finding in report["findings"]:
            if finding["verdict"] == rules.PASS:
                assert finding["checks"]["passage"] == compliance.PASSAGE_VERIFIED, finding["ruleId"]


def test_a_pass_whose_quote_is_not_in_the_document_is_withdrawn():
    rec = recording("errors")
    answer = [{"ruleId": "QC-LEASE-020", "verdict": "PASS", "quote": "Les enfants sont les bienvenus."}]
    report, _ = run(rec["document"], judge=json.dumps(answer), **rec["inputs"])
    finding = next(f for f in report["findings"] if f["ruleId"] == "QC-LEASE-020")
    assert finding["verdict"] != rules.PASS and finding["checks"]["passage"] == compliance.PASSAGE_ABSENT


def _pinned(quote: str, content_hash=None) -> dict:
    """A ruleset whose one rule pins the fictional article of fixtures/law with ``quote``."""
    article = next(iter(TEST_ARTICLES.values()))
    block = {k: article[k] for k in ("instrument", "ref", "language", "inForceFrom", "officialUrl")}
    block.update(contentHash=content_hash or article["contentHash"], quote=quote)
    rule = {
        "ruleId": "TEST-001", "title": "Préavis écrit", "severity": "BLOCKING", "method": "DETERMINISTIC",
        "citation": "TEST-1, art. 9999", "law": [block],
        "check": {"type": "REQUIRED_PATTERN", "pattern": "(?i)avis\\s+écrit"},
        "onPass": "Un avis écrit est donné.", "onFail": "Aucun avis écrit.",
    }
    return {"rulesetId": "test", "version": "2020-01-01", "jurisdiction": "QC", "source": "fictional", "rules": [rule]}


def _report_with(ruleset: dict, text: str) -> dict:
    findings, _ = rules.screen(ruleset, text)
    screened = {"deterministicFindings": findings, "documentText": text}
    resolved = {"outcome": "CHECK", "identification": {"asOf": "2026-01-01"}, "ruleset": {"id": "test"}}
    return compliance.report(resolved, ruleset, screened, "", TEST_ARTICLES)


def test_a_citation_is_verified_against_the_article_text_the_ruleset_pins():
    text = "Le bailleur remet un avis écrit la veille."
    good = _report_with(_pinned("remet à son locataire, avant la visite, un avis écrit"), text)["findings"][0]
    assert good["verdict"] == rules.PASS and good["checks"] == {"passage": "VERIFIED", "citation": "VERIFIED"}
    assert good["citation"]["contentHash"] == next(iter(TEST_ARTICLES)) and good["citation"]["ref"] == "9999"
    # Typography is not a difference: a straight apostrophe and other spacing still verify.
    assert _report_with(_pinned("Le bailleur d'un  logement imaginaire"), text)["findings"][0]["checks"]["citation"] == "VERIFIED"


def test_a_citation_quote_altered_by_one_word_gives_insufficient_evidence():
    finding = _report_with(_pinned("remet à son locataire, après la visite, un avis écrit"), "Un avis écrit est remis.")["findings"][0]
    assert finding["verdict"] == rules.INSUFFICIENT_EVIDENCE and finding["checks"]["citation"] == "QUOTE_NOT_IN_ARTICLE"


def test_a_hash_the_pack_does_not_hold_gives_insufficient_evidence():
    finding = _report_with(_pinned("un avis écrit", content_hash="0" * 64), "Un avis écrit est remis.")["findings"][0]
    assert finding["verdict"] == rules.INSUFFICIENT_EVIDENCE and finding["checks"]["citation"] == "ARTICLE_NOT_HELD"


def test_an_article_whose_text_does_not_hash_to_its_name_is_refused():
    article = copy.deepcopy(next(iter(TEST_ARTICLES.values())))
    article["text"] += " Une phrase ajoutée."
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "bad.json").write_text(json.dumps(article), encoding="utf-8")
        try:
            citations.load_articles(directory)
        except ValueError as refused:
            assert "does not hash" in str(refused)
            return
    raise AssertionError("a changed article text must not be trusted under its old hash")


def test_every_law_block_the_pack_ships_pins_an_article_it_holds_and_quotes_it():
    held = citations.load_articles()
    for ruleset_dir in sorted(p for p in (PACK / "rulesets").iterdir() if p.is_dir()):
        for version in sorted(ruleset_dir.glob("*.json")):
            for rule in json.loads(version.read_text(encoding="utf-8"))["rules"]:
                for block in rule.get("law") or []:
                    assert citations.check(block, held) == citations.VERIFIED, f"{version.name} {rule['ruleId']} {block.get('ref')}"


# --- Two identical runs -------------------------------------------------------------------------------------------

def test_two_identical_runs_give_the_same_report():
    # The premise of the result cache (orazaka-studio#61): the run is a function of its inputs and its version.
    rec = recording("errors")
    first, _ = run(rec["document"], judge=recorded_judge(rec["report"]), **rec["inputs"])
    second, _ = run(rec["document"], judge=recorded_judge(rec["report"]), **rec["inputs"])
    assert first == second


def _report_step(document: str, **inputs) -> dict:
    """The output of the report step itself (what the platform reads ``resultCacheable`` from)."""
    ident = worker._identify({"document": document, **inputs})
    resolved = worker._resolve({"identification": ident["identificationJson"], "document": document})
    screened = worker._screen({"resolved": resolved["resolvedJson"], "document": document}) if resolved["outcome"] == "CHECK" else None
    return worker._report({"resolved": resolved["resolvedJson"], "screened": screened["screenedJson"] if screened else "", "judgment": "[]"})


def test_a_run_whose_day_came_from_the_clock_is_never_cacheable():
    lease = kind_text("qc-residential-lease", "fr-filled.txt")  # signed on 2026-06-12: a date the document gives
    assert _report_step(lease, asOf="2026-10-22")["resultCacheable"] is True, "explicit asOf"
    dated = _report_step(lease)
    assert dated["report"]["identification"]["asOfSource"] == "DOCUMENT" and dated["resultCacheable"] is True
    undated = _report_step(kind_text("qc-residential-lease", "fr-blank.txt"))
    assert undated["report"]["identification"]["asOfSource"] == "TODAY" and undated["resultCacheable"] is False
    unknown = _report_step(kind_text("_unknown", "unrelated.txt"))
    assert unknown["resultCacheable"] is False, "no kind, no date: today's day is not an input"
    # 1.x: a call without asOf is judged on today's law and never reused; with asOf it may be.
    assert worker._screen({"document": lease, "jurisdiction": "QC"})["resultCacheable"] is False
    assert worker._screen({"document": lease, "jurisdiction": "QC", "asOf": "2026-10-22"})["resultCacheable"] is True


def test_the_held_articles_are_a_snapshot_whose_hash_must_be_the_corpus_row():
    held = TEST_ARTICLES
    assert citations.corpus_mismatches(held, lambda a: {"contentHash": a["contentHash"]}) == []
    changed = citations.corpus_mismatches(held, lambda a: {"contentHash": "f" * 64})
    assert len(changed) == 1 and "TEST-1 art. 9999" in changed[0] and "corpus ffffffffffff" in changed[0]
    assert "LAW_VERSION_UNKNOWN" in citations.corpus_mismatches(held, lambda a: None)[0]


def test_the_shipped_snapshot_matches_the_corpus_when_it_is_reachable():
    # Behind the corpus switch, off by default (ADR-089 cut 3): AI_LAW_CORPUS_ENABLED=true and AI_LAW_LOOKUP_URL, the
    # engine's read API (orazaka-ai-engine#89: GET /api/v1/law/articles?jurisdiction&instrument&ref&language&asOf,
    # JSON {contentHash, …}, 404 for LAW_VERSION_UNKNOWN), with the oz_ key of AI_LAW_LOOKUP_KEY as its bearer.
    if os.environ.get("AI_LAW_CORPUS_ENABLED") != "true" or not os.environ.get("AI_LAW_LOOKUP_URL"):
        print("    (skipped: the law corpus switch is off)")
        return
    import urllib.error
    import urllib.parse
    import urllib.request

    def lookup(article):
        query = urllib.parse.urlencode({"jurisdiction": "QC", "instrument": article["instrument"], "ref": article["ref"],
                                        "language": article["language"], "asOf": article["inForceFrom"]})
        try:
            request = urllib.request.Request(f"{os.environ['AI_LAW_LOOKUP_URL']}?{query}")
            if os.environ.get("AI_LAW_LOOKUP_KEY"):
                request.add_header("Authorization", f"Bearer {os.environ['AI_LAW_LOOKUP_KEY']}")
            with urllib.request.urlopen(request, timeout=10) as answer:
                return json.load(answer)
        except urllib.error.HTTPError as missing:
            if missing.code == 404:
                return None
            raise

    assert citations.corpus_mismatches(citations.load_articles(), lookup) == []


def test_the_corpus_lookup_asks_the_read_api_by_ref_with_its_key():
    # A local stand-in for GET /api/v1/law/articles (orazaka-ai-engine#89): it answers the held hash for the asked
    # article, and records what it was asked, so the query names `ref` (never `reference`) and carries the key.
    import http.server
    import threading
    import urllib.parse

    # The pack holds no article yet on every branch: one known article stands in for the snapshot.
    held = {"a" * 64: {"instrument": "CCQ-1991", "ref": "1931", "language": "fr", "inForceFrom": "1994-01-01"},
            "b" * 64: {"instrument": "CCQ-1991", "ref": "9999", "language": "fr", "inForceFrom": "1994-01-01"}}
    by_key = {(a["instrument"], a["ref"], a["language"], a["inForceFrom"]): h for h, a in held.items()}
    asked = []

    class Api(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the http.server name
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            asked.append((sorted(query), self.headers.get("Authorization")))
            key = tuple(query.get(name, [""])[0] for name in ("instrument", "ref", "language", "asOf"))
            found = by_key.get(key)
            self.send_response(200 if found else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"contentHash": found} if found else {"code": "law-version-unknown"}).encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    del by_key[("CCQ-1991", "9999", "fr", "1994-01-01")]  # the corpus does not know this one: 404
    load_articles = citations.load_articles
    citations.load_articles = lambda directory=None: held
    saved = {k: os.environ.get(k) for k in ("AI_LAW_CORPUS_ENABLED", "AI_LAW_LOOKUP_URL", "AI_LAW_LOOKUP_KEY")}
    try:
        os.environ.update({"AI_LAW_CORPUS_ENABLED": "true", "AI_LAW_LOOKUP_KEY": "oz_test",
                           "AI_LAW_LOOKUP_URL": f"http://127.0.0.1:{server.server_port}/api/v1/law/articles"})
        try:
            test_the_shipped_snapshot_matches_the_corpus_when_it_is_reachable()
            raise AssertionError("the unknown article must be reported")
        except AssertionError as mismatch:
            if "must be reported" in str(mismatch):
                raise
    finally:
        citations.load_articles = load_articles
        server.shutdown()
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    assert len(asked) == len(held)
    assert citations.corpus_mismatches(held, lambda a: None)  # a 404 is LAW_VERSION_UNKNOWN, never a match
    assert all(params == ["asOf", "instrument", "jurisdiction", "language", "ref"] for params, _ in asked)
    assert all(auth == "Bearer oz_test" for _, auth in asked)


def test_the_judge_is_asked_only_when_a_rule_needs_it():
    invoice = kind_text("qc-invoice", "fr-filled.txt")
    report, calls = run(invoice, jurisdiction="QC", asOf="2026-10-22")
    assert report["ruleset"]["id"] == "qc-invoice" and calls == [], "every invoice rule is deterministic"


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
