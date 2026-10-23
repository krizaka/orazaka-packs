#!/usr/bin/env python3
"""Authenticity SIGNALS over a document — a PDF, an image or an office file. Facts about the file, and nothing else.

**There is no inference step in this module, and none in the Studio that calls it.** Detecting
forgery with a language model is the worst available use of one: asked whether a document was
tampered with, it will produce reasons that sound right for signals it never saw. The two errors
are not symmetric — a false "authentic" on a forged lease is an exposure, and a false "forged" on
an honest tenant is worse, because it accuses a person. Confabulation produces the second one most
readily. So every signal here is read off the bytes, and the sentence a reader sees was written by
a person, once, per signal type.

**No score, and that is deliberate.** "87 % probability of forgery" is a lie until it derives from
a measured base rate, and a number gets quoted in a dispute as though it were one. The scale is
three qualitative levels, each defined in `LEVELS` below.

**The signals are data** (orazaka-packs#88): `authenticity-signals.json` holds each case's id, level, thresholds and
the sentences (FR, EN); `producer-profiles.json` says what kind of software a declared producer is. This module only
reads facts off the bytes and picks the case.

**The value of this module is TRIAGE, not a verdict.** It tells a reader which points deserve a
question. What it is not, and what it did not look at, is stated by the report itself.
"""

import base64
import io
import json
import os
import re
import struct
import zipfile
import zlib
from collections import Counter
from datetime import datetime

try:  # pragma: no cover - import shape only
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


#: The scale. Three levels, each defined here in writing, because a level with no definition is a
#: number in disguise — and a reader will supply their own meaning for it.
LEVELS = {
    "observé": (
        "Un fait relevé dans le fichier, présent dans quantité de documents parfaitement "
        "ordinaires. Rapporté pour que vous sachiez qu'il a été regardé, pas parce qu'il suggère "
        "quoi que ce soit."
    ),
    "inhabituel": (
        "Un fait peu courant pour ce type de document, qui a des explications ordinaires — un "
        "logiciel qui réenregistre, un envoi par un intermédiaire. Mérite une question, pas une "
        "conclusion."
    ),
    "incohérent": (
        "Deux faits du fichier se contredisent. Ce n'est toujours pas une preuve : une "
        "contradiction a aussi des explications. C'est le genre de point qu'il vaut mieux "
        "éclaircir avant de se fier au document."
    ),
}

OBSERVED, UNUSUAL, INCONSISTENT = "observé", "inhabituel", "incohérent"

#: What this module does NOT look at. Printed by every report, because a report that hides its
#: limits is worse than no report: it is read as covering what it never examined.
NOT_EXAMINED = [
    "La véracité de ce que le document affirme — les montants, les noms et les dates ne sont pas vérifiés auprès de qui que ce soit.",
    "Les signatures, manuscrites comme électroniques : aucune n'est validée, et une signature électronique valide n'est pas vérifiée ici.",
    "L'existence de l'émetteur et le fait qu'il ait bien émis ce document.",
    "Les images au niveau du pixel : aucune analyse de retouche, de compression ou de bruit de capteur.",
    "Le contenu d'un document bureautique : ni son suivi des modifications ni ses commentaires ne sont lus.",
    "Les métadonnées elles-mêmes se réécrivent aussi facilement que le reste : leur présence ne garantit rien, leur absence ne prouve rien.",
    "L'original papier, s'il existe.",
    "La comparaison avec un exemplaire de référence, qui n'a pas été fourni.",
]

#: What a real examination would involve, named so a reader can decide whether to pay for one.
REAL_EXAMINATION = [
    "Un examen documentaire par un expert judiciaire, qui travaille sur l'original et non sur un fichier.",
    "Une demande de confirmation directe auprès de l'émetteur supposé.",
    "Une analyse d'image en laboratoire si le document est un scan et que l'enjeu le justifie.",
]

#: Stated once, at the top of the report, in full. Not a footer.
HEADER = (
    "Ce rapport n'est pas une expertise. Il relève des faits techniques sur le fichier fourni (PDF, image ou document "
    "bureautique) "
    "et signale ceux qui méritent une question. Il ne dit pas si le document est authentique ni "
    "s'il ne l'est pas — il n'en a pas les moyens, et personne ne devrait en tirer cette "
    "conclusion. Il ne porte aucune appréciation sur la personne qui a fourni le document."
)


class UnreadableDocument(Exception):
    """The bytes are not a document this module can read. Said plainly, never guessed around."""


#: The worker and older callers name it after the only format it used to read.
UnreadablePdf = UnreadableDocument

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as handle:
        return json.load(handle)


CATALOGUE = _load("authenticity-signals.json")
PROFILES = _load("producer-profiles.json")
THRESHOLDS = CATALOGUE["thresholds"]

#: What this module reads, said in the refusal of anything else.
SUPPORTED = "les PDF, les images (JPEG, PNG, WebP, TIFF, HEIC) et les documents bureautiques (Word, Excel, PowerPoint, OpenDocument)"


def producer_class(*names) -> str:
    """The class of the first declared software that a profile knows (``editor``, ``ocr``…), or ``""``."""
    for name in names:
        lowered = str(name or "").lower()
        if not lowered:
            continue
        for profile in PROFILES["profiles"]:
            if profile["pattern"] in lowered:
                return profile["class"]
    return ""


def _first_of_class(cls, *names) -> str:
    return next((str(n) for n in names if n and producer_class(n) == cls), "")


def _emit(case, locale="fr", **facts):
    """One signal from its catalogue case: what was seen, what it can be an indication of, and where.

    ``mayIndicate`` is phrased as a possibility and written by hand per case, in the catalogue. It is never generated,
    and it never names a person.
    """
    entry = CATALOGUE["signals"][case]
    texts = entry[locale]
    return {
        "signalId": entry["signalId"],
        "level": entry["level"] if "level" not in facts else facts.pop("level"),
        "observation": texts["observation"].format(**facts),
        "mayIndicate": texts["mayIndicate"].format(**facts),
        "where": texts["where"].format(**facts),
    }


def _stamp(moment) -> str:
    return f"{moment:%Y-%m-%d %H:%M}"


# ── PDF ──────────────────────────────────────────────────────────────────────
def _pdf_date(value):
    """A PDF date string (``D:YYYYMMDDHHmmSS``) as a datetime, or None."""
    if not value:
        return None
    text = str(value).strip()
    match = re.match(r"D?:?(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", text)
    if not match:
        return None
    parts = [int(p) if p else 0 for p in match.groups()]
    try:
        return datetime(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5])
    except ValueError:
        return None


def _count_revisions(raw: bytes) -> int:
    """How many times this file was written.

    A PDF saved once ends with one ``%%EOF``. Every incremental update appends a new body, a new
    cross-reference section and another ``%%EOF`` — which is how a PDF records that it was edited
    after it was first written, and is also how a great many ordinary tools save.
    """
    return raw.count(b"%%EOF")


def _fonts_per_page(reader) -> list:
    """The BaseFont names each page references, in page order."""
    per_page = []
    for page in reader.pages:
        names = set()
        try:
            resources = page.get("/Resources")
            fonts = resources.get("/Font") if resources else None
            if fonts:
                for key in list(fonts.keys()):
                    font = fonts[key]
                    base = font.get("/BaseFont") if hasattr(font, "get") else None
                    if base:
                        names.add(str(base).lstrip("/"))
        except Exception:  # noqa: BLE001 — a page whose resources will not resolve is reported as empty
            pass
        per_page.append(names)
    return per_page


def _has_image(page) -> bool:
    try:
        resources = page.get("/Resources")
        xobjects = resources.get("/XObject") if resources else None
        if not xobjects:
            return False
        for key in list(xobjects.keys()):
            obj = xobjects[key]
            if hasattr(obj, "get") and str(obj.get("/Subtype")) == "/Image":
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _invisible_text(raw_page: bytes) -> bool:
    """Text render mode 3 — drawn invisibly, which is how OCR puts a text layer over a scan."""
    return b" 3 Tr" in raw_page or b"\n3 Tr" in raw_page


def _pdf_xmp(reader, raw: bytes) -> bytes:
    """The document's XMP packet: the catalog's /Metadata stream (often compressed), else a packet in the raw bytes."""
    try:
        stream = reader.trailer["/Root"].get("/Metadata")
        if stream is not None:
            return stream.get_object().get_data()
    except Exception:  # noqa: BLE001 — an unreadable stream is the same as none
        pass
    return _xmp_packet(raw)


def _pdf_ids_differ(reader) -> bool:
    """The trailer's /ID pair: the first is set when the file is created, the second each time it is rewritten."""
    try:
        ids = reader.trailer.get("/ID")
        return bool(ids) and len(ids) == 2 and bytes(str(ids[0]), "latin-1", "replace") != bytes(str(ids[1]), "latin-1", "replace")
    except Exception:  # noqa: BLE001
        return False


def _analyse_pdf(pdf_bytes: bytes, expected_issuer: str, locale: str):
    if PdfReader is None:  # pragma: no cover
        raise UnreadableDocument("la bibliothèque PDF n'est pas disponible dans ce worker")
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        info = reader.metadata or {}
        pages = reader.pages
    except Exception as broken:  # noqa: BLE001
        raise UnreadableDocument(f"le PDF n'a pas pu être ouvert : {broken}") from broken

    signals = []
    producer = str(info.get("/Producer") or "").strip()
    creator = str(info.get("/Creator") or "").strip()
    created = _pdf_date(info.get("/CreationDate"))
    modified = _pdf_date(info.get("/ModDate"))

    if creator:
        signals.append(_emit("PDF-META-001.producerAndCreator", locale, producer=producer or "—", creator=creator))
    elif producer:
        signals.append(_emit("PDF-META-001.producer", locale, producer=producer))
    else:
        signals.append(_emit("PDF-META-001.absent", locale))

    if expected_issuer and producer and expected_issuer.lower() not in f"{producer} {creator}".lower():
        signals.append(_emit("PDF-META-002", locale, producer=producer, expectedIssuer=expected_issuer))

    editor = _first_of_class("editor", producer, creator)
    if editor:
        signals.append(_emit("PDF-META-004", locale, software=editor))

    if created and modified and modified > created:
        signals.append(_emit("PDF-META-003", locale, created=_stamp(created), modified=_stamp(modified),
                             days=(modified - created).days))

    revisions = _count_revisions(pdf_bytes)
    if revisions > 1:
        level = "incohérent" if revisions >= THRESHOLDS["PDF-REV-001"]["inconsistentFrom"] else "inhabituel"
        signals.append(_emit("PDF-REV-001", locale, level=level, revisions=revisions, later=revisions - 1))

    if _pdf_ids_differ(reader):
        signals.append(_emit("PDF-ID-001", locale))

    signals += _xmp_signals(_pdf_xmp(reader, pdf_bytes), locale)

    ocr_producer = producer_class(producer, creator) == "ocr"
    scanned_pages = []
    for index, page in enumerate(pages, start=1):
        try:
            raw_page = page.get_contents().get_data() if page.get_contents() else b""
        except Exception:  # noqa: BLE001
            raw_page = b""
        if _has_image(page) and (_invisible_text(raw_page) or ocr_producer):
            scanned_pages.append(index)
    if scanned_pages:
        signals.append(_emit("PDF-TEXT-001", locale, pages=", ".join(map(str, scanned_pages))))

    per_page = _fonts_per_page(reader)
    if len(per_page) >= THRESHOLDS["PDF-FONT-001"]["minPages"]:
        counts = Counter(font for names in per_page for font in names)
        for index, names in enumerate(per_page, start=1):
            lonely = sorted(font for font in names if counts[font] == 1)
            if lonely:
                signals.append(_emit("PDF-FONT-001", locale, page=index, fonts=", ".join(lonely)))

    declared = len(set(re.findall(rb"(?m)^\s*(\d+)\s+\d+\s+obj\b", pdf_bytes)))
    referenced = len(set(re.findall(rb"\b(\d+)\s+\d+\s+R\b", pdf_bytes)))
    limits = THRESHOLDS["PDF-OBJ-001"]
    if declared and referenced and declared - referenced > max(limits["minUnreferenced"], int(declared * limits["unreferencedShare"])):
        signals.append(_emit("PDF-OBJ-001", locale, declared=declared, unreferenced=declared - referenced))

    return len(pages), signals


# ── XMP (any format) ─────────────────────────────────────────────────────────
#: History actions that mean the file was written again. ``created`` is its first writing, not a later one.
REWRITE_ACTIONS = ("saved", "converted", "derived", "edited", "produced")


def _xmp_packet(raw: bytes) -> bytes:
    match = re.search(rb"<x:xmpmeta[\s\S]*?</x:xmpmeta>", raw)
    return match.group(0) if match else b""


def _xmp_value(text: str, name: str) -> str:
    match = re.search(rf'{name}\s*=\s*"([^"]*)"|<{name}>([^<]*)</{name}>', text)
    return (match.group(1) or match.group(2) or "").strip() if match else ""


def _xmp_history(packet: bytes) -> list:
    """The (action, softwareAgent) events of ``xmpMM:History``, in order."""
    text = packet.decode("utf-8", "replace")
    block = re.search(r"<xmpMM:History>([\s\S]*?)</xmpMM:History>", text)
    if not block:
        return []
    events = []
    for item in re.split(r"<rdf:li\b", block.group(1))[1:]:
        action = _xmp_value(item, "stEvt:action")
        if action:
            events.append((action, _xmp_value(item, "stEvt:softwareAgent")))
    return events


def _xmp_signals(packet: bytes, locale: str) -> list:
    rewrites = [(action, agent) for action, agent in _xmp_history(packet) if action.lower() in REWRITE_ACTIONS]
    if not rewrites:
        return []
    agents = list(dict.fromkeys(agent for _action, agent in rewrites if agent)) or ["—"]
    case = "XMP-HIST-001.editor" if _first_of_class("editor", *agents) else "XMP-HIST-001.plain"
    return [_emit(case, locale, events=len(rewrites), agents=", ".join(agents))]


# ── images ───────────────────────────────────────────────────────────────────
#: The EXIF tags this module reads, and nothing else (no GPS, no owner name: they say nothing about the file's history
#: and something about a person).
EXIF_TAGS = {0x010F: "make", 0x0110: "model", 0x0131: "software", 0x0132: "modified", 0x9003: "taken"}
EXIF_IFD_POINTER = 0x8769
ASCII, LONG = 2, 4


def _tiff_tags(tiff: bytes) -> dict:
    """The few ASCII tags of IFD0 and the Exif IFD, read straight off a TIFF structure (EXIF is one)."""
    order = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if not order or len(tiff) < 8:
        return {}
    found, pending, seen = {}, [struct.unpack(order + "I", tiff[4:8])[0]], set()
    try:
        while pending:
            offset = pending.pop()
            if offset in seen or offset + 2 > len(tiff):
                continue
            seen.add(offset)
            (count,) = struct.unpack(order + "H", tiff[offset:offset + 2])
            for n in range(count):
                entry = offset + 2 + 12 * n
                tag, kind, length, value = struct.unpack(order + "HHII", tiff[entry:entry + 12])
                if tag == EXIF_IFD_POINTER and kind == LONG:
                    pending.append(value)
                elif tag in EXIF_TAGS and kind == ASCII:
                    data = tiff[entry + 8:entry + 8 + length] if length <= 4 else tiff[value:value + length]
                    text = data.split(b"\0")[0].decode("utf-8", "replace").strip()
                    if text:
                        found[EXIF_TAGS[tag]] = text
    except struct.error:  # a truncated directory: keep what was read
        pass
    return found


def _jpeg_parts(raw: bytes):
    exif, xmp, at = b"", b"", 2
    while at + 4 <= len(raw) and raw[at] == 0xFF:
        marker = raw[at + 1]
        if marker in (0xD9, 0xDA):  # end of image, start of scan: no metadata after this
            break
        (length,) = struct.unpack(">H", raw[at + 2:at + 4])
        segment = raw[at + 4:at + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\0\0"):
            exif = segment[6:]
        elif marker == 0xE1 and segment.startswith(b"http://ns.adobe.com/xap/1.0/\0"):
            xmp = segment
        at += 2 + length
    return exif, xmp


def _png_parts(raw: bytes):
    exif, xmp, text, at = b"", b"", {}, 8
    while at + 8 <= len(raw):
        length, kind = struct.unpack(">I4s", raw[at:at + 8])
        data = raw[at + 8:at + 8 + length]
        if kind == b"eXIf":
            exif = data
        elif kind in (b"tEXt", b"iTXt"):
            keyword, _, rest = data.partition(b"\0")
            if kind == b"iTXt":
                compressed = rest[:1] == b"\1"
                rest = rest[2:].split(b"\0", 2)[-1]
                rest = zlib.decompress(rest) if compressed else rest
            text[keyword.decode("latin-1")] = rest
        elif kind == b"IEND":
            break
        at += 12 + length
    software = text.get("Software", b"").decode("utf-8", "replace").strip()
    return exif, text.get("XML:com.adobe.xmp", b""), software


def _webp_parts(raw: bytes):
    exif, xmp, at = b"", b"", 12
    while at + 8 <= len(raw):
        kind, length = struct.unpack("<4sI", raw[at:at + 8])
        data = raw[at + 8:at + 8 + length]
        if kind == b"EXIF":
            exif = data[6:] if data.startswith(b"Exif\0\0") else data
        elif kind == b"XMP ":
            xmp = data
        at += 8 + length + (length & 1)
    return exif, xmp


def _isobmff_exif(raw: bytes) -> bytes:
    """HEIC/AVIF keep EXIF as an item whose data starts with the TIFF header: found by its signature."""
    marker = raw.find(b"Exif\0\0")
    if marker >= 0:
        return raw[marker + 6:]
    for signature in (b"MM\0*", b"II*\0"):
        found = raw.find(signature)
        if found >= 0:
            return raw[found:]
    return b""


def _exif_date(text: str):
    try:
        return datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _analyse_image(raw: bytes, media_type: str, locale: str):
    software = ""
    if media_type == "image/jpeg":
        exif, xmp = _jpeg_parts(raw)
    elif media_type == "image/png":
        exif, xmp, software = _png_parts(raw)
    elif media_type == "image/webp":
        exif, xmp = _webp_parts(raw)
    elif media_type == "image/tiff":
        exif, xmp = raw, _xmp_packet(raw)
    else:
        exif, xmp = _isobmff_exif(raw), _xmp_packet(raw)
    xmp = xmp or _xmp_packet(raw)
    tags = _tiff_tags(exif)
    software = tags.get("software") or software or _xmp_value(xmp.decode("utf-8", "replace"), "xmp:CreatorTool")
    make, model = tags.get("make", ""), tags.get("model", "")
    device = model if make and model.lower().startswith(make.lower()) else " ".join(p for p in (make, model) if p)
    taken, modified = _exif_date(tags.get("taken")), _exif_date(tags.get("modified"))

    signals = []
    if not (software or device or taken or modified):
        signals.append(_emit("IMG-META-001.absent", locale))
    else:
        signals.append(_emit("IMG-META-001.declared", locale, device=device or "—", software=software or "—"))
        if not device:
            signals.append(_emit("IMG-META-005", locale))
    if producer_class(software) == "editor":
        signals.append(_emit("IMG-META-002", locale, software=software))
    if taken and modified:
        gap = (modified - taken).total_seconds()
        margin = THRESHOLDS["IMG-META-003"]["minSeconds"]
        if gap < -margin:
            signals.append(_emit("IMG-META-004", locale, taken=_stamp(taken), modified=_stamp(modified)))
        elif gap > margin:
            signals.append(_emit("IMG-META-003", locale, taken=_stamp(taken), modified=_stamp(modified)))
    signals += _xmp_signals(xmp, locale)
    return 1, signals


# ── office documents ─────────────────────────────────────────────────────────
def _xml_value(text: str, name: str) -> str:
    match = re.search(rf"<{name}\b[^>]*>([^<]*)</{name}>", text)
    return match.group(1).strip() if match else ""


def _iso_date(text: str):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None) if text else None
    except ValueError:
        return None


def _analyse_office(archive, locale: str):
    """Who wrote it and when, from the package's properties. Never the author or last-modified-by fields: they name a person."""
    names = set(archive.namelist())

    def read(name):
        return archive.read(name).decode("utf-8", "replace") if name in names else ""

    if "meta.xml" in names:  # OpenDocument
        meta = read("meta.xml")
        application = _xml_value(meta, "meta:generator")
        created, modified = _iso_date(_xml_value(meta, "meta:creation-date")), _iso_date(_xml_value(meta, "dc:date"))
        revision = _xml_value(meta, "meta:editing-cycles")
    else:  # Office Open XML
        app, core = read("docProps/app.xml"), read("docProps/core.xml")
        application = " ".join(p for p in (_xml_value(app, "Application"), _xml_value(app, "AppVersion")) if p)
        created, modified = _iso_date(_xml_value(core, "dcterms:created")), _iso_date(_xml_value(core, "dcterms:modified"))
        revision = _xml_value(core, "cp:revision")

    signals = [_emit("OFF-META-001", locale, application=application or "—")]
    if created and modified and (modified - created).total_seconds() > THRESHOLDS["OFF-META-002"]["minSeconds"]:
        signals.append(_emit("OFF-META-002", locale, created=_stamp(created), modified=_stamp(modified), revision=revision or "—"))
    return 0, signals


# ── the file's type, from its bytes ──────────────────────────────────────────
IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"II*\0", "image/tiff"),
    (b"MM\0*", "image/tiff"),
)
HEIF_BRANDS = (b"heic", b"heix", b"heif", b"mif1", b"msf1", b"avif")


def detect(raw: bytes):
    """``(documentType, mediaType)`` read from the first bytes — never from a file name, which says what the sender chose."""
    if raw.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    for signature, media_type in IMAGE_SIGNATURES:
        if raw.startswith(signature):
            return "image", media_type
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image", "image/webp"
    if raw[4:8] == b"ftyp" and raw[8:12] in HEIF_BRANDS:
        return "image", "image/heic" if raw[8:12] != b"avif" else "image/avif"
    if raw.startswith(b"PK\x03\x04"):
        return "office", "application/zip"
    return None, None


def analyse(document: bytes, expected_issuer: str = "", locale: str = "fr") -> dict:
    """Every signal this module can read off ``document``.

    :param document: the file, as bytes — a PDF, an image or an office document
    :param expected_issuer: who the reader believes issued it, optional. Supplied, it turns a
        producer mismatch from an observation into an inconsistency — because a contradiction
        needs two facts, and without this there is only one.
    :param locale: the language of the signals' sentences (``fr`` or ``en``, both in the catalogue)
    :returns: the report structure, with no verdict in it
    """
    kind, media_type = detect(document)
    if kind == "pdf":
        pages, signals = _analyse_pdf(document, expected_issuer, locale)
    elif kind == "image":
        pages, signals = _analyse_image(document, media_type, locale)
    elif kind == "office":
        try:
            archive = zipfile.ZipFile(io.BytesIO(document))
        except zipfile.BadZipFile as broken:
            raise UnreadableDocument("l'archive fournie n'a pas pu être ouverte") from broken
        if not ({"docProps/core.xml", "meta.xml"} & set(archive.namelist())):
            raise UnreadableDocument(f"cette archive n'est pas un document bureautique : ce module lit {SUPPORTED}")
        pages, signals = _analyse_office(archive, locale)
    else:
        raise UnreadableDocument(f"type de fichier non examiné : ce module lit {SUPPORTED}")
    return {
        "header": HEADER,
        "documentType": kind,
        "mediaType": media_type,
        "pages": pages,
        "signals": signals,
        "levels": LEVELS,
        "notExamined": NOT_EXAMINED,
        "realExamination": REAL_EXAMINATION,
        "catalogueVersion": CATALOGUE["version"],
    }


def analyse_base64(encoded: str, expected_issuer: str = "", locale: str = "fr") -> dict:
    """:func:`analyse` over a base64 payload, which is how the document reaches this worker."""
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as bad:  # noqa: BLE001
        raise UnreadableDocument("le contenu fourni n'est pas du base64 valide") from bad
    return analyse(raw, expected_issuer, locale)


def render(report: dict) -> str:
    """The report as a person reads it. No verdict, no score, and its limits stated at the top."""
    lines = [report["header"], ""]
    signals = report["signals"]
    if not signals:
        lines.append(
            "AUCUN SIGNAL. Rien ne ressort de l'examen technique de ce fichier : ni date de "
            "modification postérieure, ni écriture successive, ni incohérence de police ou de "
            "métadonnée. Cela ne dit pas que le document est en règle — voir ce qui n'a pas été "
            "examiné, plus bas."
        )
    else:
        actionable = [s for s in signals if s["level"] != OBSERVED]
        if actionable:
            lines.append(
                f"{len(actionable)} point(s) méritent une question ; "
                f"{len(signals) - len(actionable)} autre(s) fait(s) sont rapportés pour information."
            )
        else:
            lines.append(
                f"Aucun point ne ressort. {len(signals)} fait(s) sont rapportés pour information."
            )
        lines.append("")
        for signal in signals:
            lines.append(f"[{signal['level'].upper()}] {signal['signalId']}")
            lines.append(f"  Constat      : {signal['observation']}")
            lines.append(f"  Peut indiquer: {signal['mayIndicate']}")
            lines.append(f"  Où           : {signal['where']}")
            lines.append("")
    lines.append("CE QUE CE RAPPORT N'A PAS EXAMINÉ")
    lines += [f"  - {item}" for item in report["notExamined"]]
    lines.append("")
    lines.append("CE QU'UN EXAMEN RÉEL SUPPOSERAIT")
    lines += [f"  - {item}" for item in report["realExamination"]]
    return "\n".join(lines)
