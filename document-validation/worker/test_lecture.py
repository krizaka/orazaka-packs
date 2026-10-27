#!/usr/bin/env python3
"""The lecture of a document with no promoted ruleset (ADR-089 §6, orazaka-packs#130): never a verdict, never unaudited-looking.

What is pinned, each as a contract rather than a habit:

- **off by default**: no lecture without the switch and the caller's request, and no model call either;
- **no verdict field can appear**: the lecture is rebuilt from a closed list of fields, and the blueprint's contract
  refuses any other (``additionalProperties: false``), so a ``verdict`` a model adds is dropped and one that slips in
  breaks the contract;
- **``audit`` is always ``UNAUDITED``**, claims or none;
- **a claim whose document passage is absent is never ``VERIFIED``**; neither is one whose article is not verified;
- **``kindDemand`` counts without content**: the jurisdiction and the kind id, nothing of the document.

Fictional documents only. Run: python3 test_lecture.py
"""
import copy
import json
import os
import re
from pathlib import Path

import citations
import identify
import lecture
from test_check import BLUEPRINT, assert_conforms, kind_text, run

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HELD = citations.load_articles(str(FIXTURES / "law"))
(ARTICLE,) = HELD.values()

#: A kind that is known and has no ruleset (the notice of modification of the lease, art. 1942), and a document of no kind.
NOTICE = kind_text("qc-lease-modification-notice", "fr-filled.txt")
UNKNOWN_DOC = (Path(__file__).resolve().parent.parent / "kinds" / "fixtures" / "_unknown" / "unrelated.txt").read_text(encoding="utf-8")
PASSAGE = "Vous avez un mois pour répondre à cet avis"

#: Words that would make a lecture a judgment of the document. None may be a key of it.
VERDICT_KEYS = {"verdict", "score", "pass", "fail", "compliant", "conformity", "conforme", "passed", "failed", "result", "risk"}


class Switch:
    """The environment of the lecture: ``with Switch("true"):`` turns it on, ``Switch(None)`` removes it."""

    def __init__(self, value):
        self.value, self.saved = value, os.environ.get(lecture.ENV_SWITCH)

    def __enter__(self):
        if self.value is None:
            os.environ.pop(lecture.ENV_SWITCH, None)
        else:
            os.environ[lecture.ENV_SWITCH] = self.value

    def __exit__(self, *_):
        if self.saved is None:
            os.environ.pop(lecture.ENV_SWITCH, None)
        else:
            os.environ[lecture.ENV_SWITCH] = self.saved


def claim(*, text="Le préavis de modification est encadré par la loi.", status="VERIFIED", passage=PASSAGE, article_quote=None, content_hash=None, extra=None):
    """One claim as the grounded step returns it: the law's citation, then the document's."""
    cites = [{
        "url": "https://www.legisquebec.gouv.qc.ca/fr/version/lc/CCQ-1991?code=se:1942",
        "quote": article_quote if article_quote is not None else "un avis de modification",
        "contentHash": content_hash or "a" * 64,
        "fetchedAt": "2026-10-26T10:00:00Z",
    }]
    if passage is not None:
        cites.append({"url": lecture.DOCUMENT_URL, "quote": passage, "contentHash": "b" * 64, "fetchedAt": "2026-10-26T10:00:00Z"})
    return {"text": text, "status": status, "citations": cites, **(extra or {})}


def keys_of(value):
    """Every key of every object in a value."""
    if isinstance(value, dict):
        return set(value) | set().union(*(keys_of(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(set(), *(keys_of(v) for v in value))
    return set()


# --- off by default --------------------------------------------------------------------------------------------------

def test_the_lecture_is_off_by_default_and_asked_for_twice():
    for switch, ask in ((None, True), ("false", True), ("TRUE", True), ("true", None), ("true", False)):
        with Switch(switch):
            report, calls = run(NOTICE, jurisdiction="QC", grounded=[claim()], **({} if ask is None else {"lecture": ask}))
            assert "lecture" not in report and calls == [], (switch, ask)
            assert report["outcome"] == "UNSUPPORTED_KIND" and report["findings"] == [], "the run says it plainly"


def test_the_switch_and_the_request_are_read_exactly():
    assert lecture.enabled({lecture.ENV_SWITCH: "true"}) and not lecture.enabled({}) and not lecture.enabled({lecture.ENV_SWITCH: "1"})
    assert lecture.wanted(True) and lecture.wanted("true") and not lecture.wanted(False) and not lecture.wanted("") and not lecture.wanted(None)


def test_a_checked_document_never_gets_a_lecture():
    with Switch("true"):
        lease = (FIXTURES / "qc-residential-lease" / "fr-compliant.txt").read_text(encoding="utf-8")
        report, calls = run(lease, judge="[]", jurisdiction="QC", asOf="2026-10-26", lecture=True, grounded=[claim()])
        assert report["outcome"] == "CHECKED" and "lecture" not in report and "kindDemand" not in report
        assert "lecture" not in calls


# --- the lecture ---------------------------------------------------------------------------------------------------------

def test_a_requested_lecture_asks_the_corpus_once_with_the_document_as_data_not_in_the_question():
    asked = []
    with Switch("true"):
        report, calls = run(NOTICE, jurisdiction="QC", lecture=True, grounded=lambda payload: asked.append(payload) or [claim()])
    assert calls == ["lecture"] and len(asked) == 1
    payload = asked[0]
    assert payload["sources"] == identify.LAW_CORPUS_SOURCE and payload["jurisdiction"] == "QC" and payload["language"] == "fr"
    assert payload["document"] == NOTICE and PASSAGE not in payload["question"], "the document is data, never part of the question"
    assert "verdict" in payload["question"].lower() and re.search(r"ne rends aucun verdict", payload["question"], re.I)
    assert report["outcome"] == "UNSUPPORTED_KIND" and report["lecture"]["claims"][0]["status"] == "VERIFIED"


def test_a_document_of_no_kind_gets_the_generic_question_and_counts_as_unknown():
    with Switch("true"):
        report, calls = run(UNKNOWN_DOC, jurisdiction="QC", lecture=True, grounded=[])
    assert report["outcome"] == "KIND_UNKNOWN" and calls == ["lecture"]
    assert report["lecture"]["claims"] == [] and report["lecture"]["audit"] == "UNAUDITED"
    assert report["kindDemand"] == {"jurisdiction": "QC", "kindId": "UNKNOWN"}


def test_a_claim_is_verified_only_when_both_quotes_are_found():
    document = NOTICE
    cases = {
        "both found": (claim(), "VERIFIED", None),
        "passage absent": (claim(passage=None), "TO_VALIDATE", "PASSAGE_ABSENT"),
        "passage blank": (claim(passage="   "), "TO_VALIDATE", "PASSAGE_ABSENT"),
        "passage not in the document": (claim(passage="Le locataire doit quitter le logement demain."), "TO_VALIDATE", "PASSAGE_NOT_IN_DOCUMENT"),
        "article not verified by the grounded step": (claim(status="TO_VALIDATE"), "TO_VALIDATE", "ARTICLE_NOT_VERIFIED"),
        "article quote missing": (claim(article_quote=""), "TO_VALIDATE", "ARTICLE_NOT_VERIFIED"),
        "article hash malformed": (claim(content_hash="abc"), "TO_VALIDATE", "ARTICLE_NOT_VERIFIED"),
    }
    for name, (item, status, reason) in cases.items():
        got = lecture.verify([item], document, HELD)["claims"][0]
        assert got["status"] == status and got.get("reason") == reason, (name, got)
        if got["status"] != "VERIFIED":
            assert got["passage"] == "" or got["checks"]["passage"] == "VERIFIED", name
    # A passage absent from the document is never VERIFIED, whatever else holds.
    assert lecture.verify([claim(passage=None)], document, HELD)["claims"][0]["checks"]["passage"] == "ABSENT"


def test_the_passage_is_read_the_way_the_pack_reads_every_quote():
    # Case, spacing and typography are not differences (quotes.contains); a word the document lacks is.
    shown = "VOUS AVEZ  UN MOIS pour répondre à cet avis"
    assert lecture.verify([claim(passage=shown)], NOTICE, HELD)["claims"][0]["status"] == "VERIFIED"
    assert lecture.verify([claim(passage="Vous avez deux mois pour répondre")], NOTICE, HELD)["claims"][0]["status"] == "TO_VALIDATE"


def test_an_article_this_pack_holds_is_checked_again_and_a_quote_it_does_not_say_is_not_verified():
    held = copy.deepcopy(HELD)
    good = claim(article_quote=ARTICLE["text"][:40], content_hash=ARTICLE["contentHash"])
    assert lecture.verify([good], NOTICE, held)["claims"][0]["status"] == "VERIFIED"
    wrong = claim(article_quote="Cette phrase n'est pas dans l'article.", content_hash=ARTICLE["contentHash"])
    got = lecture.verify([wrong], NOTICE, held)["claims"][0]
    assert got["status"] == "TO_VALIDATE" and got["reason"] == "QUOTE_NOT_IN_ARTICLE" and got["checks"]["article"] == "QUOTE_NOT_IN_ARTICLE"


def test_a_lecture_is_short_and_a_claim_without_text_is_dropped():
    many = [claim(text=f"Affirmation {i}") for i in range(20)] + [claim(text="  ")]
    got = lecture.verify(many, NOTICE, HELD)["claims"]
    assert len(got) == lecture.MAX_CLAIMS and all(c["text"] for c in got)
    assert all(len(c["text"]) <= lecture.MAX_TEXT for c in lecture.verify([claim(text="x" * 5000)], NOTICE, HELD)["claims"])
    for junk in (None, "", "not json", "{}", "[]", 42, [None, 3, "x"], {"claims": "x"}):
        assert lecture.verify(junk, NOTICE, HELD)["claims"] == [], junk


# --- no verdict field -----------------------------------------------------------------------------------------------

def test_no_verdict_field_can_appear_in_a_lecture():
    # A model that adds a verdict, a score or a conclusion to a claim, or to the answer: none of it survives.
    sly = claim(extra={"verdict": "FAIL", "score": 0.1, "compliant": False, "result": "PASS", "risk": "high"})
    sly["citations"][0]["verdict"] = "FAIL"
    raw = {"verdict": "FAIL", "claims": [sly], "answer": "Ce bail est illégal."}
    built = lecture.verify(raw, NOTICE, HELD)
    assert not (keys_of(built) & VERDICT_KEYS), keys_of(built)
    assert set(built) == {"audit", "notice", "claims"}
    for item in built["claims"]:
        assert set(item) <= {"text", "status", "reason", "article", "passage", "checks"}
        assert set(item["article"]) == {"url", "quote", "contentHash"}


def test_the_blueprints_contract_refuses_any_field_outside_the_list_and_names_no_verdict():
    contract = next(s for s in BLUEPRINT["definition"]["steps"] if s["id"] == "report")["outputContract"]
    schema = contract["properties"]["report"]["properties"]["lecture"]
    assert not (keys_of(schema["properties"]) & VERDICT_KEYS) and not (keys_of(schema["properties"]["claims"]["items"]["properties"]) & VERDICT_KEYS)
    nodes = [schema, schema["properties"]["claims"]["items"], schema["properties"]["claims"]["items"]["properties"]["article"],
             schema["properties"]["claims"]["items"]["properties"]["checks"], schema["properties"]["notice"]]
    assert all(node["additionalProperties"] is False for node in nodes)
    built = lecture.verify([claim()], NOTICE, HELD)
    assert_conforms(schema, json.loads(json.dumps(built)), "$.lecture")
    for tampered in (dict(built, verdict="FAIL"), dict(built, claims=[dict(built["claims"][0], score=1)])):
        try:
            assert_conforms(schema, json.loads(json.dumps(tampered)), "$.lecture")
        except AssertionError:
            continue
        raise AssertionError("the contract accepted a field outside the list")
    assert schema["properties"]["audit"]["enum"] == ["UNAUDITED"]


def test_the_report_of_a_lecture_run_conforms_to_the_blueprints_contract():
    with Switch("true"):
        report, _ = run(NOTICE, jurisdiction="QC", lecture=True, grounded=[claim(), claim(passage=None)])
    assert [c["status"] for c in report["lecture"]["claims"]] == ["VERIFIED", "TO_VALIDATE"]
    assert not (keys_of(report["lecture"]) & VERDICT_KEYS)


def test_audit_is_always_unaudited_with_claims_or_without_and_the_notice_says_what_it_is_not():
    for raw in ([], [claim()], [claim(passage=None)], None, "garbage"):
        built = lecture.verify(raw, NOTICE, HELD)
        assert built["audit"] == "UNAUDITED"
        assert "verdict" in built["notice"]["fr"] and "verdict" in built["notice"]["en"]
    with Switch("true"):
        report, _ = run(NOTICE, jurisdiction="QC", lecture=True, grounded=[])
    assert report["lecture"]["audit"] == "UNAUDITED"


# --- kind_demand ----------------------------------------------------------------------------------------------------

def test_kind_demand_counts_the_kind_and_the_jurisdiction_and_nothing_of_the_document():
    secret = "Thierry Imaginaire-Roy"
    document = NOTICE.replace("Karim Haddad", secret)
    for switch in (None, "true"):
        with Switch(switch):
            report, _ = run(document, jurisdiction="QC", lecture=True, grounded=[claim()])
        demand = report["kindDemand"]
        assert demand == {"jurisdiction": "QC", "kindId": "qc-lease-modification-notice"}
        assert set(demand) == {"jurisdiction", "kindId"}
        assert secret not in json.dumps(demand) and PASSAGE not in json.dumps(demand)
    assert lecture.kind_demand({"outcome": "KIND_UNKNOWN", "kindUsed": None, "jurisdiction": None}) == {"jurisdiction": "UNKNOWN", "kindId": "UNKNOWN"}
    assert lecture.kind_demand({"outcome": "KIND_UNKNOWN", "kindUsed": "qc-invoice", "jurisdiction": "QC"})["kindId"] == "UNKNOWN", "a tie names no kind"


def test_demand_is_counted_whether_or_not_a_lecture_is_asked():
    with Switch(None):
        report, calls = run(NOTICE, jurisdiction="QC")
    assert report["kindDemand"]["kindId"] == "qc-lease-modification-notice" and calls == [] and "lecture" not in report


def test_the_request_is_built_from_data_only_and_the_kind_without_retrieval_gets_the_generic_question():
    identification = identify.identify(UNKNOWN_DOC, today="2026-10-26", jurisdiction="QC")
    asked = lecture.request(identification)
    assert asked["sources"] == ["law-corpus"] and asked["targets"] == [] and asked["asOf"] == "2026-10-26"
    kind = {"kindId": "qc-visit-notice", "jurisdiction": "QC", "retrieval": {
        "targets": [{"instrument": "CCQ-1991", "refs": ["1931"]}], "question": {"fr": "Quelle question ?", "en": "Which question?"}}}
    identification = {"kindUsed": "qc-visit-notice", "asOf": "2026-10-26", "languages": ["en"], "jurisdiction": "QC"}
    asked = lecture.request(identification, kinds=[kind])
    assert asked["targets"] == [{"instrument": "CCQ-1991", "refs": ["1931"]}] and asked["question"].startswith("Which question?")
    assert "kindId" not in asked and asked["language"] == "en"


def test_the_lecture_step_is_optional_and_the_report_step_waits_for_it():
    steps = {s["id"]: s for s in BLUEPRINT["definition"]["steps"]}
    assert steps["lecture"]["onError"] == "SKIP" and steps["lecture"]["skipRationale"]
    assert steps["lecture"]["condition"] == "{{steps.resolved.needsLecture}} == true"
    assert "lecture" in steps["report"]["dependsOn"] and BLUEPRINT["inputSchema"]["properties"]["lecture"]["type"] == "boolean"
    assert "lecture" not in BLUEPRINT["inputSchema"].get("required", [])


if __name__ == "__main__":
    import sys

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
