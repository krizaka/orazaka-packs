#!/usr/bin/env python3
"""The identity-document rules: a reading (what a vision model transcribed) turned into findings and a status.

Run: python3 test_rules.py. Pure functions: no broker, no model. The specimens are ICAO Doc 9303's fictional Anna Maria
Eriksson of « Utopia »; the tampered variants are generated from them.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "worker-common"))
import testkit  # noqa: E402
import mrz  # noqa: E402
import rules  # noqa: E402

AS_OF = "2011-06-01"  # the specimen's expiry (2012-04-15) is still ahead
TD3 = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]

READ = {
    "documentType": "PASSPORT",
    "issuer": "UTO",
    "mrzLines": TD3,
    "printed": {"surname": "Eriksson", "givenNames": "Anna Maria", "documentNumber": "L898902C3", "dateOfBirth": "1974-08-12", "dateOfExpiry": "2012-04-15", "sex": "F"},
    "signals": [],
    "quality": {"blur": False, "glare": False, "cropped": False, "lowResolution": False},
    "confidence": {"mrz": 0.95, "printed": 0.9},
}


def _read(**changes):
    out = copy.deepcopy(READ)
    for key, value in changes.items():
        out[key] = value
    return out


def _report(read=READ, as_of=AS_OF, **options):
    return rules.assess(rules.load_ruleset(), read, as_of, **options)


def _codes(report, severity=None):
    return sorted(f["code"] for f in report["findings"] if severity is None or f["severity"] == severity)


def test_the_specimen_is_consistent_and_says_what_it_cannot_know():
    report = _report()
    assert report["status"] == "CONSISTENT", report["findings"]
    assert _codes(report, "FAIL") == [] and _codes(report, "WARN") == []
    assert report["fields"]["dateOfBirth"] == "1974-08-12" and report["fields"]["dateOfExpiry"] == "2012-04-15"
    assert "NAME_LINE_HAS_NO_CHECK_DIGIT" in report["limits"] and "NO_DATABASE_LOOKUP" in report["limits"]
    assert report["mrz"]["format"] == "TD3" and report["mrz"]["checksumsValid"] is True


def test_the_ruleset_is_chosen_by_date_never_by_recency():
    assert rules.load_ruleset("2026-10-26")["version"] == "2026-10-26"
    try:
        rules.load_ruleset("2020-01-01")
    except FileNotFoundError:
        return
    raise AssertionError("a date before the first ruleset must fail, never fall back")


def test_a_changed_mrz_digit_fails_with_the_value_and_the_region_as_evidence():
    lines = [TD3[0], TD3[1][:3] + "9" + TD3[1][4:]]
    report = _report(_read(mrzLines=lines))
    assert report["status"] == "INCONSISTENT"
    finding = next(f for f in report["findings"] if f["code"] == "MRZ_CHECKSUM_FAILED" and f["field"] == "documentNumber")
    assert finding["severity"] == "FAIL" and finding["basis"] == "DETERMINISTIC"
    assert finding["evidence"]["source"] == "mrz" and finding["evidence"]["value"] == "L899902C3"
    assert finding["evidence"]["region"] == "mrz.line2[0:9]"
    assert finding["confidence"] == 0.95


def test_the_same_failure_on_a_doubtful_transcription_asks_for_a_new_capture_instead_of_accusing():
    lines = [TD3[0], TD3[1][:3] + "9" + TD3[1][4:]]
    report = _report(_read(mrzLines=lines, confidence={"mrz": 0.3, "printed": 0.9}))
    assert report["status"] == "REVIEW"
    finding = next(f for f in report["findings"] if f["code"] == "MRZ_CHECKSUM_FAILED" and f["field"] == "documentNumber")
    assert finding["severity"] == "WARN" and finding["maybeTranscription"] is True


def test_a_printed_field_that_differs_from_the_zone_fails_and_cites_both_values():
    printed = dict(READ["printed"], dateOfBirth="1976-08-12")
    report = _report(_read(printed=printed))
    assert report["status"] == "INCONSISTENT"
    finding = next(f for f in report["findings"] if f["code"] == "PRINTED_MRZ_MISMATCH")
    assert finding["field"] == "dateOfBirth"
    assert finding["evidence"]["value"] == "1976-08-12" and finding["evidence"]["against"] == "1974-08-12"
    assert finding["evidence"]["source"] == "printed"


def test_names_are_compared_the_way_the_zone_writes_them():
    printed = dict(READ["printed"], surname="ÉRIKSSON", givenNames="Anna-Maria")
    assert _codes(_report(_read(printed=printed)), "FAIL") == []
    printed = dict(READ["printed"], surname="Ericsson")
    assert "PRINTED_MRZ_MISMATCH" in _codes(_report(_read(printed=printed)), "FAIL")


def test_the_document_number_is_compared_without_spaces_or_dashes():
    printed = dict(READ["printed"], documentNumber="l898 902-c3")
    assert _codes(_report(_read(printed=printed)), "FAIL") == []


def test_date_logic_expired_future_birth_and_impossible_days():
    assert "DOCUMENT_EXPIRED" in _codes(_report(as_of="2013-01-01"), "WARN")
    assert _report(as_of="2013-01-01")["status"] == "REVIEW"
    future_birth = _read(mrzLines=None, printed=dict(READ["printed"], dateOfBirth="2030-01-01"))
    assert "BIRTH_IN_FUTURE" in _codes(_report(future_birth), "FAIL")
    reversed_dates = _read(mrzLines=None, printed=dict(READ["printed"], dateOfBirth="2012-01-01", dateOfExpiry="2005-01-01"))
    assert "EXPIRY_BEFORE_BIRTH" in _codes(_report(reversed_dates), "FAIL")
    impossible = _read(mrzLines=None, printed=dict(READ["printed"], dateOfBirth="1974-02-30"))
    assert "DATE_INVALID" in _codes(_report(impossible), "FAIL")


def test_the_minimum_age_is_a_review_not_an_accusation():
    report = _report(minimum_age=40)
    assert report["age"] == {"years": 36, "minimum": 40, "meets": False}
    assert report["status"] == "REVIEW" and "AGE_BELOW_MINIMUM" in _codes(report, "WARN")
    assert _report(minimum_age=18)["age"]["meets"] is True
    assert "age" not in _report() or _report()["age"]["minimum"] is None


def test_a_vision_signal_asks_for_a_look_and_never_convicts_alone():
    strong = [{"kind": "PHOTO_REPLACED", "region": "photo", "confidence": 0.95}]
    report = _report(_read(signals=strong))
    assert report["status"] == "REVIEW" and _codes(report, "FAIL") == []
    finding = next(f for f in report["findings"] if f["code"] == "TAMPERING_SIGNAL")
    assert finding["basis"] == "MODEL" and finding["evidence"]["region"] == "photo" and finding["confidence"] == 0.95
    weak = [{"kind": "FONT_MISMATCH", "region": "surname", "confidence": 0.2}]
    report = _report(_read(signals=weak))
    assert report["status"] == "CONSISTENT" and "TAMPERING_SIGNAL" in _codes(report, "INFO")


def test_unknown_signal_kinds_and_malformed_signals_are_dropped_and_counted():
    mixed = [{"kind": "ALIEN", "region": "x", "confidence": 1}, "nonsense", {"kind": "TEXT_OVERLAY", "region": "dob", "confidence": 2}]
    report = _report(_read(signals=mixed))
    assert [f["evidence"]["region"] for f in report["findings"] if f["code"] == "TAMPERING_SIGNAL"] == ["dob"]
    assert next(f for f in report["findings"] if f["code"] == "TAMPERING_SIGNAL")["confidence"] == 1.0  # clamped
    assert report["ignoredSignals"] == 2


def test_quality_problems_say_what_to_recapture():
    report = _report(_read(quality={"blur": True, "glare": False, "cropped": True, "lowResolution": False}))
    quality = [f for f in report["findings"] if f["code"] == "QUALITY_POOR"]
    assert sorted(f["field"] for f in quality) == ["blur", "cropped"]
    assert report["status"] == "REVIEW"


def test_a_document_without_a_zone_is_judged_on_what_is_printed():
    report = _report(_read(mrzLines=[]))
    assert report["mrz"]["present"] is False and "MRZ_ABSENT" in _codes(report, "INFO")
    assert report["status"] == "CONSISTENT"


def test_lines_that_are_not_a_zone_are_a_warning_not_a_crash():
    report = _report(_read(mrzLines=["not a zone", "at all"]))
    assert "MRZ_UNREADABLE" in _codes(report, "WARN") and report["status"] == "REVIEW"


def test_the_barcode_is_compared_with_the_printed_fields():
    text = "@\n\x1e\rANSI 636026\nDAQ L8989-02C3\nDCSERIKSSON\nDACANNA\nDBB19740812\nDBA20120415\n"
    ok = _report(barcode_text=text)
    assert ok["barcode"]["present"] is True and _codes(ok, "FAIL") == []
    bad = _report(barcode_text=text.replace("19740812", "19760812"))
    finding = next(f for f in bad["findings"] if f["code"] == "BARCODE_MISMATCH")
    assert finding["field"] == "dateOfBirth" and finding["evidence"]["source"] == "barcode"
    assert bad["status"] == "INCONSISTENT"


def test_nothing_readable_is_unreadable_never_consistent():
    report = _report({"documentType": "OTHER", "mrzLines": [], "printed": {}, "signals": [], "quality": {}, "confidence": {}})
    assert report["status"] == "UNREADABLE"


def test_a_malformed_reading_is_refused_as_input_not_judged():
    for bad in (None, [], "x", {"mrzLines": "oops"}, {"printed": []}):
        try:
            _report(bad)
        except rules.InvalidReading:
            continue
        raise AssertionError(f"{bad!r} was not refused")


def test_the_reading_may_arrive_as_text_with_a_markdown_fence():
    wrapped = "```json\n" + __import__("json").dumps(READ) + "\n```"
    assert rules.parse_reading(wrapped) == READ
    try:
        rules.parse_reading("I cannot read this image.")
    except rules.InvalidReading:
        return
    raise AssertionError("prose is not a reading")


def test_the_report_carries_no_image_and_no_more_than_the_fields_it_needs():
    report = _report()
    dumped = __import__("json").dumps(report)
    assert "base64" not in dumped
    assert set(report) >= {"rulesetId", "rulesetVersion", "rulesetRevision", "status", "fields", "findings", "mrz", "limits"}


if __name__ == "__main__":
    testkit.main(globals())
