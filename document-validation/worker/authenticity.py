#!/usr/bin/env python3
"""Authenticity SIGNALS over a PDF. Facts about the file, and nothing else.

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

**The value of this module is TRIAGE, not a verdict.** It tells a reader which points deserve a
question. What it is not, and what it did not look at, is stated by the report itself.
"""

import base64
import io
import re
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

#: Producers that name an OCR stage. Their presence explains a text layer over an image; it is not
#: a tampering signal, and conflating the two would make every scanned document suspect.
OCR_PRODUCERS = ("tesseract", "abbyy", "finereader", "ocrmypdf", "readiris", "omnipage", "acrobat capture")

#: What this module does NOT look at. Printed by every report, because a report that hides its
#: limits is worse than no report: it is read as covering what it never examined.
NOT_EXAMINED = [
    "La véracité de ce que le document affirme — les montants, les noms et les dates ne sont pas vérifiés auprès de qui que ce soit.",
    "Les signatures, manuscrites comme électroniques : aucune n'est validée, et une signature électronique valide n'est pas vérifiée ici.",
    "L'existence de l'émetteur et le fait qu'il ait bien émis ce document.",
    "Les images au niveau du pixel : aucune analyse de retouche, de compression ou de bruit de capteur.",
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
    "Ce rapport n'est pas une expertise. Il relève des faits techniques sur le fichier PDF fourni "
    "et signale ceux qui méritent une question. Il ne dit pas si le document est authentique ni "
    "s'il ne l'est pas — il n'en a pas les moyens, et personne ne devrait en tirer cette "
    "conclusion. Il ne porte aucune appréciation sur la personne qui a fourni le document."
)


class UnreadablePdf(Exception):
    """The bytes are not a PDF this module can parse. Said plainly, never guessed around."""


def _signal(signal_id, level, observation, may_indicate, where):
    """One signal: what was seen, what it can be an indication of, and where in the file.

    ``may_indicate`` is deliberately phrased as a possibility and written by hand per signal type.
    It is never generated, and it never names a person.
    """
    return {
        "signalId": signal_id,
        "level": level,
        "observation": observation,
        "mayIndicate": may_indicate,
        "where": where,
    }


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


def analyse(pdf_bytes: bytes, expected_issuer: str = "") -> dict:
    """Every signal this module can read off ``pdf_bytes``.

    :param pdf_bytes: the file, as bytes
    :param expected_issuer: who the reader believes issued it, optional. Supplied, it turns a
        producer mismatch from an observation into an inconsistency — because a contradiction
        needs two facts, and without this there is only one.
    :returns: the report structure, with no verdict in it
    """
    if PdfReader is None:  # pragma: no cover
        raise UnreadablePdf("la bibliothèque PDF n'est pas disponible dans ce worker")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise UnreadablePdf("le fichier fourni ne commence pas par %PDF- : ce n'est pas un PDF")
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        info = reader.metadata or {}
        pages = reader.pages
    except Exception as broken:  # noqa: BLE001
        raise UnreadablePdf(f"le PDF n'a pas pu être ouvert : {broken}") from broken

    signals = []
    producer = str(info.get("/Producer") or "").strip()
    creator = str(info.get("/Creator") or "").strip()
    created = _pdf_date(info.get("/CreationDate"))
    modified = _pdf_date(info.get("/ModDate"))

    # ── PDF-META-001 — the producer, always reported ──────────────────────────
    if producer or creator:
        signals.append(_signal(
            "PDF-META-001", OBSERVED,
            f"Le fichier déclare avoir été produit par « {producer or '—'} »"
            + (f" et créé avec « {creator} »." if creator else "."),
            "Rien en soi. Le producteur est le logiciel qui a écrit le fichier, pas son auteur.",
            "Métadonnées du document (/Producer, /Creator)",
        ))
    else:
        signals.append(_signal(
            "PDF-META-001", UNUSUAL,
            "Le fichier ne déclare aucun logiciel producteur.",
            "Des métadonnées retirées, ce que font certains outils de nettoyage — et aussi "
            "certaines chaînes de production légitimes.",
            "Métadonnées du document (/Producer, /Creator absents)",
        ))

    # ── PDF-META-002 — producer vs the issuer the reader expects ──────────────
    if expected_issuer:
        haystack = f"{producer} {creator}".lower()
        if producer and expected_issuer.lower() not in haystack:
            signals.append(_signal(
                "PDF-META-002", INCONSISTENT,
                f"Le producteur déclaré (« {producer} ») ne correspond pas à l'émetteur que vous "
                f"attendiez (« {expected_issuer} »).",
                "Un document réenregistré ou recomposé après émission. C'est aussi ce que fait un "
                "intermédiaire qui réimprime en PDF, ou une boîte mail qui convertit une pièce jointe.",
                "Métadonnées du document (/Producer)",
            ))

    # ── PDF-META-003 — modified after creation ────────────────────────────────
    if created and modified and modified > created:
        delta = modified - created
        signals.append(_signal(
            "PDF-META-003", UNUSUAL,
            f"Le fichier déclare avoir été modifié après sa création : créé le "
            f"{created:%Y-%m-%d %H:%M}, modifié le {modified:%Y-%m-%d %H:%M} "
            f"({delta.days} jour(s) plus tard).",
            "Une modification postérieure à l'émission. Un réenregistrement, l'ajout d'une "
            "annotation ou une signature produisent exactement la même trace.",
            "Métadonnées du document (/CreationDate vs /ModDate)",
        ))

    # ── PDF-REV-001 — stacked revisions ───────────────────────────────────────
    revisions = _count_revisions(pdf_bytes)
    if revisions > 1:
        signals.append(_signal(
            "PDF-REV-001", UNUSUAL if revisions == 2 else INCONSISTENT,
            f"Le fichier contient {revisions} écritures successives : il a été enregistré une "
            f"première fois, puis modifié et réenregistré {revisions - 1} fois par-dessus, sans "
            "que les versions précédentes soient effacées.",
            "Des modifications apportées après le premier enregistrement. Les formulaires remplis "
            "et les signatures électroniques procèdent ainsi normalement.",
            f"Structure du fichier ({revisions} marqueurs %%EOF)",
        ))

    # ── PDF-TEXT-001 — an OCR text layer over an image ────────────────────────
    ocr_producer = any(tool in f"{producer} {creator}".lower() for tool in OCR_PRODUCERS)
    scanned_pages = []
    for index, page in enumerate(pages, start=1):
        try:
            raw_page = page.get_contents().get_data() if page.get_contents() else b""
        except Exception:  # noqa: BLE001
            raw_page = b""
        if _has_image(page) and (_invisible_text(raw_page) or ocr_producer):
            scanned_pages.append(index)
    if scanned_pages:
        signals.append(_signal(
            "PDF-TEXT-001", OBSERVED,
            f"La couche texte des pages {', '.join(map(str, scanned_pages))} a été produite par "
            "reconnaissance de caractères par-dessus une image : ce document est un scan, pas un "
            "texte natif.",
            "Rien quant à l'authenticité. C'est l'état normal d'un document imprimé puis numérisé. "
            "Noté parce que les autres signaux se lisent différemment sur un scan.",
            f"Pages {', '.join(map(str, scanned_pages))} (image + texte en mode de rendu invisible)",
        ))

    # ── PDF-FONT-001 — a font appearing on one page only ──────────────────────
    per_page = _fonts_per_page(reader)
    if len(per_page) > 1:
        counts = Counter(font for names in per_page for font in names)
        for index, names in enumerate(per_page, start=1):
            lonely = sorted(font for font in names if counts[font] == 1)
            if lonely and len(per_page) > 2:
                signals.append(_signal(
                    "PDF-FONT-001", UNUSUAL,
                    f"La page {index} utilise une police que l'on ne retrouve sur aucune autre "
                    f"page : {', '.join(lonely)}.",
                    "Une page composée séparément du reste, puis insérée. Les en-têtes, les "
                    "annexes et les pages de signature produisent aussi cet écart.",
                    f"Page {index} (/Resources /Font)",
                ))

    # ── PDF-OBJ-001 — objects present but referenced by nothing ───────────────
    declared = len(set(re.findall(rb"(?m)^\s*(\d+)\s+\d+\s+obj\b", pdf_bytes)))
    referenced = len(set(re.findall(rb"\b(\d+)\s+\d+\s+R\b", pdf_bytes)))
    if declared and referenced and declared - referenced > max(5, declared // 4):
        signals.append(_signal(
            "PDF-OBJ-001", UNUSUAL,
            f"Le fichier définit {declared} objets dont environ {declared - referenced} ne sont "
            "référencés nulle part.",
            "Des éléments retirés d'une version antérieure sans que le fichier soit reconstruit. "
            "Beaucoup d'outils laissent ce genre de résidu en enregistrant.",
            "Structure du fichier (objets déclarés vs référencés)",
        ))

    return {
        "header": HEADER,
        "pages": len(pages),
        "signals": signals,
        "levels": LEVELS,
        "notExamined": NOT_EXAMINED,
        "realExamination": REAL_EXAMINATION,
    }


def analyse_base64(encoded: str, expected_issuer: str = "") -> dict:
    """:func:`analyse` over a base64 payload, which is how the PDF reaches this worker."""
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as bad:  # noqa: BLE001
        raise UnreadablePdf("le contenu fourni n'est pas du base64 valide") from bad
    return analyse(raw, expected_issuer)


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
