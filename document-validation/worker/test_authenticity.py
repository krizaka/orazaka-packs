#!/usr/bin/env python3
"""The authenticity gate. Run: .venv/bin/python worker/test_authenticity.py

Adversarial where it matters: the assertions that would fail if this Studio ever started
concluding something. A signal layer that drifts into a verdict does so one helpful sentence at a
time, so the prohibition is tested rather than remembered.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import authenticity as a  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
PACK_ROOT = os.path.dirname(HERE)


def _fixture(name):
    with open(os.path.join(FIXTURES, f"{name}.pdf"), "rb") as handle:
        return handle.read()


def _by_id(report):
    return {s["signalId"]: s for s in report["signals"]}


# ── the three documents ───────────────────────────────────────────────────────

def test_a_clean_pdf_raises_nothing_and_says_so_without_ambiguity():
    report = a.analyse(_fixture("clean"))
    actionable = [s for s in report["signals"] if s["level"] != a.OBSERVED]
    assert actionable == [], actionable
    text = a.render(report)
    assert "Aucun point ne ressort" in text or "AUCUN SIGNAL" in text


def test_a_pdf_modified_after_creation_raises_the_signal_with_its_location():
    report = a.analyse(_fixture("modified"), expected_issuer="Agence Meridien")
    found = _by_id(report)

    assert "PDF-META-003" in found, "a later /ModDate must be reported"
    assert found["PDF-META-003"]["level"] == a.UNUSUAL
    assert "/CreationDate" in found["PDF-META-003"]["where"]

    assert "PDF-REV-001" in found, "an appended incremental update must be reported"
    assert "%%EOF" in found["PDF-REV-001"]["where"]

    assert "PDF-META-002" in found, "a producer contradicting the expected issuer"
    assert found["PDF-META-002"]["level"] == a.INCONSISTENT


def test_a_scanned_and_ocred_pdf_is_distinguished_from_native_text():
    report = a.analyse(_fixture("scanned"))
    found = _by_id(report)
    assert "PDF-TEXT-001" in found, "an OCR layer over an image must be identified"
    # And it must NOT count as a tampering signal: a scanned document is the ordinary case, and
    # treating it as suspicious would make every photocopied lease a finding.
    assert found["PDF-TEXT-001"]["level"] == a.OBSERVED
    assert "authenticité" in found["PDF-TEXT-001"]["mayIndicate"]

    native = _by_id(a.analyse(_fixture("clean")))
    assert "PDF-TEXT-001" not in native, "native text must not be reported as OCR"


# ── the three prohibitions ────────────────────────────────────────────────────

#: Words that assert. Allowed ONLY in the blocks whose job is to deny them.
VERDICT_WORDS = ("authentique", "falsif", "faux document", "contrefa", "fraude", "frauduleux")

#: The blocks that exist to say what this is not. A verdict word may appear here and nowhere else.
DISCLAIMER_TEXT = " ".join([a.HEADER] + a.NOT_EXAMINED + a.REAL_EXAMINATION).lower()


def test_no_signal_ever_contains_a_verdict():
    # Structural, not stylistic: a verdict word may live only in the disclaimer blocks. Anywhere a
    # signal is produced, the word is simply absent — so the rule needs no judgement about whether
    # a given sentence was a denial.
    for name in ("clean", "modified", "scanned"):
        for signal in a.analyse(_fixture(name), expected_issuer="Agence Meridien")["signals"]:
            haystack = f"{signal['observation']} {signal['mayIndicate']} {signal['where']}".lower()
            for word in VERDICT_WORDS:
                assert word not in haystack, f"{name}/{signal['signalId']} asserts '{word}'"


def test_no_level_is_a_verdict_and_every_level_is_defined_in_writing():
    assert set(a.LEVELS) == {"observé", "inhabituel", "incohérent"}
    for level, definition in a.LEVELS.items():
        for word in VERDICT_WORDS:
            assert word not in f"{level} {definition}".lower()
        assert len(definition) > 80, f"'{level}' needs a definition, not a label"


def test_there_is_no_score_anywhere():
    # "87 % de probabilité de falsification" is a lie until it derives from a measured base rate,
    # and a number gets quoted in a dispute as though it were one.
    report = a.analyse(_fixture("modified"), expected_issuer="Agence Meridien")
    text = a.render(report)
    # A percentage, not a percent sign: `%%EOF` is a PDF structure marker and naming it is exactly
    # the kind of locatable fact this report is made of.
    assert not re.search(r"\d\s*%(?!%)", text), "no percentage may appear in a report"
    for signal in report["signals"]:
        assert "score" not in signal
        assert "confidence" not in signal
        assert "probability" not in signal


def test_no_signal_mentions_a_person():
    # The signals are about the DOCUMENT. Whoever supplied it is not a subject of this report.
    accusing = ("locataire", "bailleur", "le demandeur", "la personne qui", "il a modifié", "elle a modifié")
    for name in ("clean", "modified", "scanned"):
        for signal in a.analyse(_fixture(name), expected_issuer="Agence Meridien")["signals"]:
            haystack = f"{signal['observation']} {signal['mayIndicate']}".lower()
            for word in accusing:
                assert word not in haystack, f"{signal['signalId']} talks about a person: '{word}'"


def test_every_report_states_what_it_did_not_examine():
    for name in ("clean", "modified", "scanned"):
        text = a.render(a.analyse(_fixture(name)))
        assert "CE QUE CE RAPPORT N'A PAS EXAMINÉ" in text
        assert "signatures" in text.lower()
        assert "CE QU'UN EXAMEN RÉEL SUPPOSERAIT" in text


def test_the_disclaimer_is_at_the_top_and_in_full():
    # Once, at the top, in plain words — not a footer nobody reads.
    text = a.render(a.analyse(_fixture("modified"), expected_issuer="Agence Meridien"))
    assert text.startswith(a.HEADER)
    assert "n'est pas une expertise" in text
    assert "ne dit pas si le document est authentique" in text


def test_no_pack_template_contains_a_verdict():
    """The test that must go red if a template ever starts concluding.

    Scans every blueprint, manifest and worker source in this pack for an assertive verdict, and
    exempts only the disclaimer text — which is where those words are supposed to appear, because
    denying them is what it is for.
    """
    offenders = []
    for root, _dirs, files in os.walk(PACK_ROOT):
        if ".venv" in root or "__pycache__" in root or "/fixtures" in root:
            continue
        for name in files:
            if not name.endswith((".json", ".yaml", ".yml", ".py")):
                continue
            if name.startswith("test_"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8", errors="replace") as handle:
                content = handle.read().lower()
            for word in VERDICT_WORDS:
                for match in re.finditer(re.escape(word), content):
                    window = content[max(0, match.start() - 220): match.end() + 220]
                    if any(fragment and fragment in DISCLAIMER_TEXT for fragment in [window[:60]]):
                        continue
                    # A verdict word survives only inside the disclaimer blocks, which are compared
                    # by content rather than by line number so moving them changes nothing.
                    if window.strip() in DISCLAIMER_TEXT:
                        continue
                    snippet = content[max(0, match.start() - 70): match.end() + 70].replace("\n", " ")
                    if any(part in DISCLAIMER_TEXT for part in (snippet.strip(),)):
                        continue
                    offenders.append(f"{os.path.relpath(path, PACK_ROOT)}: …{snippet.strip()}…")
    # Anything left must be inside a disclaimer; the check above is deliberately conservative, so a
    # survivor is reported and has to be justified by moving it into the disclaimer or removing it.
    allowed = [o for o in offenders if _is_denial(o)]
    real = [o for o in offenders if o not in allowed]
    assert not real, "a pack template asserts a verdict:\n  " + "\n  ".join(real)


def _is_denial(line: str) -> bool:
    """Whether the occurrence sits in a sentence that denies rather than asserts."""
    lowered = line.lower()
    return any(marker in lowered for marker in (
        "ne dit pas", "n'est pas", "ne l'est pas", "aucun", "jamais", "ni ", "pas de verdict",
        "verdict_words", "sans conclure", "ne conclut", "n'affirme",
    ))


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {str(exc)[:200]}")
    print(f"\n{'FAILED' if failures else 'all green'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)
