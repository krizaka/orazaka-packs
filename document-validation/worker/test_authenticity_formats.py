#!/usr/bin/env python3
"""The authenticity signals beyond the native PDF: the catalogue as data, XMP history, the /ID pair, images and office
files (orazaka-packs#88). Run: .venv/bin/python worker/test_authenticity_formats.py

Every fixture is built here, byte by byte, so what it contains is read in the test rather than trusted from a binary.
Each new signal has its PASS case (a file that raises it) and its FAIL case (a file that must not).
"""

import io
import json
import os
import re
import string
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import authenticity as a  # noqa: E402
from test_authenticity import VERDICT_WORDS, _conforms  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _ids(report):
    return [s["signalId"] for s in report["signals"]]


def _by_id(report):
    return {s["signalId"]: s for s in report["signals"]}


# ── builders ─────────────────────────────────────────────────────────────────
def _tiff(tags, exif_tags=None):
    """A big-endian TIFF block: IFD0 with ASCII tags, and an Exif IFD when ``exif_tags`` is given."""
    def ifd(entries, start, extra_pointer=None):
        items = sorted(entries.items())
        count = len(items) + (1 if extra_pointer is not None else 0)
        data_at = start + 2 + 12 * count + 4
        head, data = struct.pack(">H", count), b""
        for tag, text in items:
            value = text.encode() + b"\0"
            head += struct.pack(">HHII", tag, 2, len(value), data_at + len(data))
            data += value
        if extra_pointer is not None:
            head += struct.pack(">HHII", a.EXIF_IFD_POINTER, 4, 1, extra_pointer)
        return head + b"\0\0\0\0" + data

    first = ifd(tags, 8, extra_pointer=0)
    if exif_tags is None:
        return b"MM\0*" + struct.pack(">I", 8) + ifd(tags, 8)
    exif_at = 8 + len(first)
    first = ifd(tags, 8, extra_pointer=exif_at)
    return b"MM\0*" + struct.pack(">I", 8) + first + ifd(exif_tags, exif_at)


def _xmp(*events):
    items = "".join(f'<rdf:li stEvt:action="{action}" stEvt:softwareAgent="{agent}"/>' for action, agent in events)
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/" xmlns:stEvt="http://ns.adobe.com/xap/1.0/sType/ResourceEvent#">'
        f"<xmpMM:History><rdf:Seq>{items}</rdf:Seq></xmpMM:History></rdf:Description></rdf:RDF></x:xmpmeta>"
    ).encode()


def _jpeg(tiff=b"", xmp=b""):
    out = b"\xff\xd8"
    if tiff:
        payload = b"Exif\0\0" + tiff
        out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    if xmp:
        payload = b"http://ns.adobe.com/xap/1.0/\0" + xmp
        out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return out + b"\xff\xda\0\x02" + b"\0" * 16 + b"\xff\xd9"


def _png(chunks):
    out = b"\x89PNG\r\n\x1a\n"
    for kind, data in chunks + [(b"IEND", b"")]:
        out += struct.pack(">I", len(data)) + kind + data + b"\0\0\0\0"
    return out


def _webp(chunks):
    body = b"WEBP" + b"".join(kind + struct.pack("<I", len(d)) + d + (b"\0" if len(d) & 1 else b"") for kind, d in chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _docx(created, modified, revision="7"):
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "docProps/app.xml": "<Properties><Application>Microsoft Office Word</Application><AppVersion>16.0000</AppVersion></Properties>",
        "docProps/core.xml": (
            '<cp:coreProperties><dc:creator>Une Personne</dc:creator><cp:lastModifiedBy>Une Autre</cp:lastModifiedBy>'
            f'<cp:revision>{revision}</cp:revision><dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{modified}</dcterms:modified></cp:coreProperties>'
        ),
    })


CAMERA = {0x010F: "Apple", 0x0110: "iPhone 15", 0x0131: "17.5.1", 0x0132: "2026:01:03 14:15:00"}
TAKEN = {0x9003: "2026:01:03 14:15:00"}


def _pdf_rewritten_with_history():
    """The clean fixture opened in an editor and saved again: an XMP history naming it, and a new second /ID."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, ByteStringObject, NameObject, StreamObject

    writer = PdfWriter(clone_from=PdfReader(os.path.join(HERE, "fixtures", "clean.pdf")))
    stream = StreamObject()
    stream.set_data(_xmp(("created", "Agence Meridien"), ("saved", "Adobe Photoshop 25.0"), ("converted", "Sejda PDF")))
    stream.update({NameObject("/Type"): NameObject("/Metadata"), NameObject("/Subtype"): NameObject("/XML")})
    writer._root_object[NameObject("/Metadata")] = writer._add_object(stream)
    writer._ID = ArrayObject([ByteStringObject(b"first-writing-id"), ByteStringObject(b"later-writing-id")])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _clean():
    with open(os.path.join(HERE, "fixtures", "clean.pdf"), "rb") as handle:
        return handle.read()


def _profile_fixture(name):
    if name != "reportlab-generated":
        with open(os.path.join(HERE, "fixtures", name), "rb") as handle:
            return handle.read()
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_clean())))
    writer.add_metadata({"/Producer": "ReportLab", "/Creator": "ReportLab"})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


# ── the catalogue is data ────────────────────────────────────────────────────
def test_every_case_is_written_in_both_languages_with_the_same_facts():
    fields = string.Formatter()
    for case, entry in a.CATALOGUE["signals"].items():
        assert entry["level"] in a.LEVELS, case
        assert case.split(".")[0] == entry["signalId"], case
        for part in ("observation", "mayIndicate", "where"):
            fr = {f for _, f, _, _ in fields.parse(entry["fr"][part]) if f}
            en = {f for _, f, _, _ in fields.parse(entry["en"][part]) if f}
            assert fr == en, f"{case}.{part}: {fr} vs {en}"
            assert entry["fr"][part].strip() and entry["en"][part].strip(), f"{case}.{part}"


def _profile_schema_errors(schema, value, path="$"):
    types = {"object": dict, "array": list, "string": str, "integer": int}
    expected = schema.get("type")
    if expected and (
        not isinstance(value, types[expected])
        or (expected == "integer" and isinstance(value, bool))
    ):
        return [f"{path}: expected {expected}"]
    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not in enum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: too short")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern")
    if isinstance(value, int) and not isinstance(value, bool) and value < schema.get("minimum", value):
        errors.append(f"{path}: below minimum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: too few items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += _profile_schema_errors(schema["items"], item, f"{path}[{i}]")
    if isinstance(value, dict):
        errors += [f"{path}.{key}: missing" for key in schema.get("required", []) if key not in value]
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors += [f"{path}.{key}: unexpected" for key in value if key not in properties]
        for key, child in properties.items():
            if key in value:
                errors += _profile_schema_errors(child, value[key], f"{path}.{key}")
    return errors


def test_document_profiles_match_their_schema_and_profile_goldens():
    schema = json.load(open(os.path.join(HERE, "document-profile.schema.json"), encoding="utf-8"))
    profile_dir = os.path.join(HERE, "document_profiles")
    fixture_dir = os.path.join(HERE, "fixtures", "document-profiles")
    blueprint = json.load(open(os.path.join(HERE, "..", "studios", "document-authenticity", "blueprint.json"), encoding="utf-8"))
    profile_input = blueprint["inputSchema"]["properties"]["documentType"]
    assert profile_input["enum"] == ["pay-stub", "bank-statement", "employment-letter"]
    assert "documentType" not in blueprint["inputSchema"]["required"]
    signal_schema = {
        output["key"]: output["schema"]
        for output in blueprint["definition"]["outputs"]
        if "schema" in output
    }["signals"]
    assert blueprint["definition"]["steps"][0]["inputs"]["documentType"] == "{{inputs.documentType:}}"
    profile_types = set()
    for profile_file in sorted(os.listdir(profile_dir)):
        if not profile_file.endswith(".json"):
            continue
        profile = json.load(open(os.path.join(profile_dir, profile_file), encoding="utf-8"))
        assert _profile_schema_errors(schema, profile) == [], profile_file
        assert profile["pageCount"]["min"] <= profile["pageCount"]["max"], profile_file
        assert profile["fontCount"]["min"] <= profile["fontCount"]["max"], profile_file
        assert profile["documentType"] not in profile_types, profile_file
        profile_types.add(profile["documentType"])
        golden = json.load(open(os.path.join(fixture_dir, f"{profile['documentType']}.expected.json"), encoding="utf-8"))
        assert golden["documentType"] == profile["documentType"]
        for key in ("acceptedFixture", "mismatchFixture"):
            raw = _profile_fixture(golden[key])
            report = a.analyse(raw, document_type=golden["documentType"])
            assert _conforms(signal_schema, report) == []
            signal = _by_id(report).get(golden["signalId"])
            if key == "acceptedFixture":
                assert signal is None, (golden["documentType"], signal)
            else:
                assert signal and signal["level"] == golden["level"], (golden["documentType"], signal)
                assert report["profileId"] == profile["profileId"]
                assert report["profileVersion"] == profile["version"]
                for word in VERDICT_WORDS + ("forged", "fake", "fraud", "tampered"):
                    assert word not in f"{signal['observation']} {signal['mayIndicate']}".lower()
    assert profile_types == {"pay-stub", "bank-statement", "employment-letter"}


def test_a_profile_mismatch_reads_in_the_report_language():
    fields = string.Formatter()
    entry = a.CATALOGUE["signals"]["DOC-PROFILE-001"]
    assert entry["fr"]["mismatches"].keys() == entry["en"]["mismatches"].keys()
    for key in entry["fr"]["mismatches"]:
        fr = {f for _, f, _, _ in fields.parse(entry["fr"]["mismatches"][key]) if f}
        en = {f for _, f, _, _ in fields.parse(entry["en"]["mismatches"][key]) if f}
        assert fr == en, key
    profile = a.DOCUMENT_PROFILES["pay-stub"]
    english = a._document_profile_signal(profile, "en", ("SomeEditor 1.0",), 9, 40)
    assert english["observation"].startswith("The file differs")
    for french in ("polices", "producteur", "logiciel"):
        assert french not in english["observation"], english["observation"]
    assert "9 page(s)" in english["observation"] and "40 distinct fonts" in english["observation"]
    french = a._document_profile_signal(profile, "fr", ("SomeEditor 1.0",), 9, 40)
    assert "40 polices distinctes" in french["observation"]


def test_an_absent_or_unknown_document_profile_preserves_the_current_report():
    raw = _clean()
    baseline = a.analyse(raw)
    assert a.analyse(raw, document_type="") == baseline
    assert a.analyse(raw, document_type="unknown-type") == baseline


def test_the_catalogue_never_asserts_a_verdict_and_every_profile_has_a_known_class():
    for case, entry in a.CATALOGUE["signals"].items():
        text = json.dumps(entry, ensure_ascii=False).lower()
        for word in VERDICT_WORDS + ("forged", "fake", "fraud", "tampered"):
            assert word not in text, f"{case} asserts '{word}'"
    classes = set(a.PROFILES["classes"])
    assert all(p["class"] in classes for p in a.PROFILES["profiles"])
    assert a.producer_class("Tesseract OCR 5.3") == "ocr" and a.producer_class("PDFescape Online") == "editor"
    assert a.producer_class("Agence Meridien - chaine documentaire") == ""


def test_the_signals_speak_english_when_asked():
    report = a.analyse(_clean(), locale="en")
    assert _by_id(report)["PDF-META-001"]["observation"].startswith("The file declares it was produced by")


# ── PDF: editor producer, XMP history, /ID pair ──────────────────────────────
def test_a_pdf_saved_again_in_an_editor_raises_its_history_and_ids_never_as_proof():
    report = a.analyse(_pdf_rewritten_with_history())
    found = _by_id(report)
    assert found["XMP-HIST-001"]["level"] == a.UNUSUAL
    assert "Adobe Photoshop 25.0, Sejda PDF" in found["XMP-HIST-001"]["observation"]
    assert "2 enregistrement(s)" in found["XMP-HIST-001"]["observation"], "created is the first writing, not a rewrite"
    assert found["PDF-ID-001"]["level"] == a.UNUSUAL
    # FAIL case: the clean file has one writing, the same /ID twice and no history.
    assert not {"XMP-HIST-001", "PDF-ID-001", "PDF-META-004"} & set(_ids(a.analyse(_clean())))


def test_an_editor_producer_is_worded_as_an_ordinary_tool():
    with open(os.path.join(HERE, "fixtures", "modified.pdf"), "rb") as handle:
        signal = _by_id(a.analyse(handle.read()))["PDF-META-004"]
    assert signal["level"] == a.UNUSUAL, "an editor is a question, never an inconsistency on its own"
    assert "tous les jours" in signal["mayIndicate"]


# ── images ───────────────────────────────────────────────────────────────────
def test_a_phone_photo_reports_its_device_and_raises_nothing():
    report = a.analyse(_jpeg(_tiff(CAMERA, TAKEN)))
    assert (report["documentType"], report["mediaType"], report["pages"]) == ("image", "image/jpeg", 1)
    assert _ids(report) == ["IMG-META-001"]
    assert _by_id(report)["IMG-META-001"]["level"] == a.OBSERVED
    assert "iPhone 15" in report["signals"][0]["observation"]


def test_a_photo_reworked_in_an_editor_after_it_was_taken():
    tags = {**CAMERA, 0x0131: "Adobe Photoshop 25.0 (Macintosh)", 0x0132: "2026:01:05 09:00:00"}
    xmp = _xmp(("saved", "Adobe Photoshop 25.0 (Macintosh)"))
    found = _by_id(a.analyse(_jpeg(_tiff(tags, TAKEN), xmp)))
    assert found["IMG-META-002"]["level"] == a.UNUSUAL
    assert "2026-01-03 14:15" in found["IMG-META-003"]["observation"] and "2026-01-05 09:00" in found["IMG-META-003"]["observation"]
    assert found["XMP-HIST-001"]["level"] == a.UNUSUAL


def test_a_modification_before_the_capture_is_an_inconsistency():
    tags = {**CAMERA, 0x0132: "2025:12:01 08:00:00"}
    assert _by_id(a.analyse(_jpeg(_tiff(tags, TAKEN))))["IMG-META-004"]["level"] == a.INCONSISTENT


def test_an_image_without_metadata_is_unusual_and_says_messaging_apps_do_it():
    signal = _by_id(a.analyse(_jpeg()))["IMG-META-001"]
    assert signal["level"] == a.UNUSUAL and "messageries" in signal["mayIndicate"]


def test_a_png_screenshot_names_its_software_and_no_device():
    report = a.analyse(_png([(b"tEXt", b"Software\0macOS Screenshot")]))
    assert report["mediaType"] == "image/png"
    assert _ids(report) == ["IMG-META-001", "IMG-META-005"]
    assert "macOS Screenshot" in report["signals"][0]["observation"]


def test_webp_and_heic_carry_their_exif_too():
    tiff = _tiff({**CAMERA, 0x0131: "Snapseed 2.0"}, TAKEN)
    webp = a.analyse(_webp([(b"VP8 ", b"\0" * 10), (b"EXIF", b"Exif\0\0" + tiff)]))
    assert webp["mediaType"] == "image/webp" and "IMG-META-002" in _ids(webp)
    heic = a.analyse(b"\0\0\0\x18ftypheic\0\0\0\0mif1heic" + b"\0" * 8 + b"Exif\0\0" + _tiff(CAMERA, TAKEN))
    assert heic["mediaType"] == "image/heic" and _ids(heic) == ["IMG-META-001"]


def test_a_truncated_image_is_read_as_far_as_it_goes():
    report = a.analyse(_jpeg(_tiff(CAMERA, TAKEN))[:40])
    assert report["documentType"] == "image" and report["signals"]


# ── office documents ─────────────────────────────────────────────────────────
def test_a_word_file_reports_its_application_and_its_later_edit_never_a_person():
    report = a.analyse(_docx("2026-01-01T09:00:00Z", "2026-01-04T10:30:00Z"))
    assert (report["documentType"], report["pages"]) == ("office", 0)
    found = _by_id(report)
    assert "Microsoft Office Word 16.0000" in found["OFF-META-001"]["observation"]
    assert "révision 7" in found["OFF-META-002"]["observation"]
    text = json.dumps(report, ensure_ascii=False)
    assert "Une Personne" not in text and "Une Autre" not in text, "the author fields name a person: never read"
    assert "OFF-META-002" not in _ids(a.analyse(_docx("2026-01-01T09:00:00Z", "2026-01-01T09:00:30Z")))


def test_an_opendocument_file_is_read_from_its_meta():
    meta = ("<office:document-meta><meta:generator>LibreOffice/24.2</meta:generator><meta:creation-date>2026-01-01T09:00:00"
            "</meta:creation-date><dc:date>2026-02-01T09:00:00</dc:date><meta:editing-cycles>3</meta:editing-cycles></office:document-meta>")
    found = _by_id(a.analyse(_zip({"mimetype": "application/vnd.oasis.opendocument.text", "meta.xml": meta})))
    assert "LibreOffice/24.2" in found["OFF-META-001"]["observation"] and "révision 3" in found["OFF-META-002"]["observation"]


# ── what is refused, and the contract ────────────────────────────────────────
def test_an_unknown_type_is_refused_by_its_bytes_and_says_what_is_read():
    for raw in (b"GIF89a\0\0", b"hello", _zip({"notes.txt": "x"})):
        try:
            a.analyse(raw)
        except a.UnreadableDocument as refused:
            assert "PDF" in str(refused) or "bureautique" in str(refused), str(refused)
        else:
            raise AssertionError(f"{raw[:8]!r} must be refused")
    assert a.UnreadablePdf is a.UnreadableDocument


def test_every_new_report_meets_the_declared_signals_contract():
    blueprint = json.load(open(os.path.join(HERE, "..", "studios", "document-authenticity", "blueprint.json"), encoding="utf-8"))
    schema = {o["key"]: o for o in blueprint["definition"]["outputs"]}["signals"]["schema"]
    for raw in (_pdf_rewritten_with_history(), _jpeg(), _jpeg(_tiff(CAMERA, TAKEN), _xmp(("saved", "GIMP 2.10"))),
                _png([(b"tEXt", b"Software\0x")]), _docx("2026-01-01T09:00:00Z", "2026-01-04T10:30:00Z")):
        report = a.analyse(raw)
        assert _conforms(schema, report) == [], _conforms(schema, report)
        assert not re.search(r"\d\s*%(?!%)", a.render(report)), "no percentage"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {str(exc)[:300]}")
    print(f"\n{'FAILED' if failures else 'all green'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)
