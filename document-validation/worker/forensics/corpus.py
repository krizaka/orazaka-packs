#!/usr/bin/env python3
"""A deterministic corpus of fictitious documents, tampered and ordinary (orazaka-packs#176, Yomizaka ADR-0014 O1).

Everything is invented: the employers, banks and people below do not exist, no real issuer's template or logo is used,
nothing is sent to an online editor. The same seed gives the same bytes (no clock, no ambient randomness): every date
written into a file is fixed, every choice goes through one ``random.Random(seed)``.

Two sets, each item carrying its ground truth:

* ``tampered``: a clean document altered by script with local tools (pypdf, pikepdf, Pillow); ``truth`` says what was
  changed and where (page, box in PDF points or image pixels).
* ``negatives``: the same clean documents through ORDINARY workflows (merged, compressed, annotated, form-filled,
  re-saved, scanned, photographed). They are the false-positive set: nothing in them is forged.

Ghostscript workflows run only where ``gs`` is on the PATH (the measurement container); every other workflow is
Python, so CI measures without it. ``tools()`` says which were available, and ``results.json`` records it.
"""

import functools
import io
import os
import random
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

import pikepdf
from PIL import Image, ImageDraw, ImageFilter
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

SEED = 176
KINDS = ("pay-stub", "bank-statement", "employment-letter", "invoice")

EMPLOYERS = ("Maison Verdoyante (fictif)", "Atelier des Trois Rivières (fictif)", "Groupe Bellerive (fictif)", "Cuisines du Nord (fictif)",
             "Studio Pivoine (fictif)", "Transports Lac-Argent (fictif)", "Boulangerie Soleil Levant (fictif)", "Clinique Étoile (fictif)")
BANKS = ("Banque des Cantons (fictif)", "Caisse du Plateau (fictif)", "Banque Rive-Sud (fictif)")
PEOPLE = ("Alex Tremblay-Demo", "Camille Roy-Demo", "Sam Gagnon-Demo", "Jordan Lavoie-Demo", "Maxime Côté-Demo", "Charlie Bouchard-Demo")
FIXED_DATE = datetime(2026, 1, 15, 9, 0, 0)

# The ordinary workflows and the tools they need ("" = Python only). Tools: pikepdf and pypdf are libraries; gs is Ghostscript.
NEGATIVE_WORKFLOWS = {
    "merged": "",
    "annotated": "",
    "form-filled": "",
    "qpdf-resaved": "",
    "scanned-from-print": "",
    "photographed": "",
    "printed-to-pdf": "gs",
    "compressed": "gs",
}
TAMPER_TYPES = ("incremental-amount", "rewritten-amount", "white-rectangle-text", "other-font-figure", "pasted-image",
                "jpeg-copy-move", "jpeg-resaved-after-edit")


def tools() -> dict:
    return {"ghostscript": shutil.which("gs") is not None}


# ── the clean documents ──────────────────────────────────────────────────────
def _seeded(seed):
    """The corpus' one generator: seeded so the same seed gives the same bytes. Test data only, never a secret or a token."""
    return random.Random(seed)


def _money(rng) -> str:
    return f"{rng.randrange(1200, 9800)}.{rng.randrange(0, 100):02d}"


def _lines(kind, person, issuer, rng):
    """``[(text, is_amount)]`` for one page; the amount line is the one a forger would change."""
    base = [(issuer, False), (f"{person}", False), ("Date: 2026-01-15", False)]
    if kind == "pay-stub":
        body = [("Releve de paie - periode du 2026-01-01 au 2026-01-14", False), ("Heures: 80", False),
                (f"Salaire brut: {_money(rng)} $", True), ("Retenues: voir detail", False)]
    elif kind == "bank-statement":
        body = [("Releve de compte - janvier 2026", False), ("Depot salaire", False),
                (f"Solde de cloture: {_money(rng)} $", True), ("Frais mensuels: 0.00 $", False)]
    elif kind == "employment-letter":
        body = [("Lettre d'emploi", False), ("Cette personne est employee depuis 2024-03-04.", False),
                (f"Salaire annuel: {_money(rng)} $", True), ("Poste: a temps plein", False)]
    else:
        body = [("Facture no. 2026-0042", False), ("Prestation de services", False),
                (f"Total a payer: {_money(rng)} $", True), ("Echeance: 30 jours", False)]
    return base + body


def clean_pdf(kind, person, issuer, rng, pages=1, producer="ReportLab PDF Library"):
    """A clean PDF (uncompressed streams, fixed dates and ids). Returns ``(bytes, amount_text, amount_box)``."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter, invariant=1, pageCompression=0)
    pdf.setProducer(producer)
    pdf.setCreator(issuer)
    pdf.setTitle(f"{kind} {person}")
    amount_text, amount_box = "", None
    for page in range(pages):
        y = 720
        for text, is_amount in _lines(kind, person, issuer, rng):
            pdf.setFont("Helvetica-Bold" if y == 720 else "Helvetica", 12)
            pdf.drawString(72, y, text)
            if is_amount and page == 0:
                amount_text = text
                amount_box = [72, y - 3, 72 + pdf.stringWidth(text, "Helvetica", 12), y + 11]
            y -= 28
        pdf.setFont("Helvetica", 9)
        pdf.drawString(72, 40, f"Page {page + 1} / {pages}")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue(), amount_text, amount_box


def _overlay(draw, size=letter):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=size, invariant=1, pageCompression=0)
    draw(pdf)
    pdf.showPage()
    pdf.save()
    return PdfReader(io.BytesIO(buffer.getvalue())).pages[0]


def _stamp_overlay(pdf_bytes, draw):
    """The first page with an overlay merged on top, written by pypdf (a full rewrite, as a PDF editor would)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter(clone_from=reader)
    writer.pages[0].merge_page(_overlay(draw))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ── a page as a picture (scan, photograph, image forgeries) ───────────────────
def page_image(kind, person, issuer, rng, size=(850, 1100)):
    image = Image.new("RGB", size, (250, 250, 247))
    draw = ImageDraw.Draw(image)
    y, amount_box, amount_text = 90, None, ""
    for text, is_amount in _lines(kind, person, issuer, rng):
        draw.text((90, y), text, fill=(20, 20, 20))
        if is_amount:
            amount_text = text
            amount_box = [90, y - 4, 90 + 8 * len(text), y + 16]
        y += 70
    return image, amount_text, amount_box


def _jpeg(image, exif=None, quality=88):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, **({"exif": exif} if exif else {}))
    return buffer.getvalue()


def _exif(make="Fabricant-Demo", model="Telephone-Demo", software="Camera 1.0", when="2026:01:15 09:00:00"):
    exif = Image.Exif()
    exif[0x010F], exif[0x0110], exif[0x0131], exif[0x0132] = make, model, software, when
    return exif.tobytes()


# ── tampered variants ────────────────────────────────────────────────────────
def _incremental_amount(pdf_bytes, old, new):
    """A genuine incremental save: the amount's page content is rewritten in a NEW revision appended after %%EOF."""
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        contents = page.obj["/Contents"]
        objgen = contents.objgen
        data = contents.read_bytes()
        root_ref = pdf.trailer["/Root"].objgen
        size = int(pdf.trailer["/Size"])
    changed = data.replace(f"({old})".encode("latin-1"), f"({new})".encode("latin-1"))
    previous = int(re.findall(rb"startxref\s+(\d+)", pdf_bytes)[-1])
    body = b"\n%d %d obj\n<< /Length %d >>\nstream\n" % (objgen[0], objgen[1], len(changed)) + changed + b"\nendstream\nendobj\n"
    offset = len(pdf_bytes) + 1
    xref_at = len(pdf_bytes) + len(body)
    xref = b"xref\n%d 1\n%010d %05d n \n" % (objgen[0], offset, objgen[1])
    trailer = b"trailer\n<< /Size %d /Root %d %d R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (size, root_ref[0], root_ref[1], previous, xref_at)
    return pdf_bytes + body + xref + trailer


def _rewritten_amount(pdf_bytes, old, new):
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        stream = pdf.pages[0].obj["/Contents"]
        stream.write(stream.read_bytes().replace(f"({old})".encode("latin-1"), f"({new})".encode("latin-1")))
        out = io.BytesIO()
        pdf.save(out, deterministic_id=True)
    return out.getvalue()


OVERLAY_TOOL = "pypdf overlay"


def tampered_set(per_type=10, seed=SEED):
    rng = _seeded(seed)
    items = []
    for index in range(per_type):
        kind, person, issuer = KINDS[index % 4], rng.choice(PEOPLE), rng.choice(EMPLOYERS if index % 4 != 1 else BANKS)
        pages = 3 if kind == "bank-statement" else 1
        pdf_bytes, amount, box = clean_pdf(kind, person, issuer, rng, pages=pages)
        label, _, old_figure = amount.rpartition(": ")
        figure = old_figure.replace(" $", "")
        forged_figure = f"{int(float(figure)) + rng.randrange(900, 4000)}.{rng.randrange(0, 100):02d}"
        forged = f"{label}: {forged_figure} $"
        truth = {"changed": "amount", "page": 1, "box": [round(v, 1) for v in box]}

        def over(pdf, font):
            pdf.setFillColorRGB(1, 1, 1)
            pdf.rect(box[0] - 2, box[1] - 2, box[2] - box[0] + 6, box[3] - box[1] + 4, stroke=0, fill=1)
            pdf.setFillColorRGB(0, 0, 0)
            pdf.setFont(font, 12)
            pdf.drawString(box[0], box[1] + 3, forged)

        def logo(pdf):
            image = Image.new("RGB", (160, 50), (30, 60, 140))
            ImageDraw.Draw(image).text((20, 18), "LOGO-DEMO", fill=(255, 255, 255))
            holder = io.BytesIO()
            image.save(holder, format="PNG")
            from reportlab.lib.utils import ImageReader
            pdf.drawImage(ImageReader(io.BytesIO(holder.getvalue())), 380, 640, width=160, height=50)

        tag = f"{index:02d}-{kind}"
        items.append(_item(f"incremental-amount-{tag}", "tampered", "incremental-amount", "pdf", _incremental_amount(pdf_bytes, amount, forged), kind,
                           {**truth, "tool": "append-only revision"}, issuer))
        items.append(_item(f"rewritten-amount-{tag}", "tampered", "rewritten-amount", "pdf", _rewritten_amount(pdf_bytes, amount, forged), kind,
                           {**truth, "tool": "pikepdf"}, issuer))
        items.append(_item(f"white-rectangle-text-{tag}", "tampered", "white-rectangle-text", "pdf",
                           _stamp_overlay(pdf_bytes, functools.partial(over, font="Helvetica")), kind, {**truth, "tool": OVERLAY_TOOL}, issuer))
        items.append(_item(f"other-font-figure-{tag}", "tampered", "other-font-figure", "pdf",
                           _stamp_overlay(pdf_bytes, functools.partial(over, font="Courier-Bold")), kind, {**truth, "tool": OVERLAY_TOOL}, issuer))
        items.append(_item(f"pasted-image-{tag}", "tampered", "pasted-image", "pdf", _stamp_overlay(pdf_bytes, logo), kind,
                           {"changed": "logo-or-signature", "page": 1, "box": [380, 640, 540, 690], "tool": OVERLAY_TOOL}, issuer))

        picture, _, image_box = page_image(kind, person, issuer, rng)
        x0, y0, x1, y1 = image_box
        copy = picture.copy()
        copy.paste(picture.crop((x0, y0 + 70, x1 + 40, y1 + 70)), (x0, y0))
        items.append(_item(f"jpeg-copy-move-{tag}", "tampered", "jpeg-copy-move", "image", _jpeg(copy, _exif()), kind,
                           {"changed": "region-copied", "box": [x0, y0, x1 + 40, y1], "tool": "Pillow"}, issuer))
        edited = picture.copy()
        ImageDraw.Draw(edited).rectangle([x0, y0, x1, y1], fill=(250, 250, 247))
        ImageDraw.Draw(edited).text((x0, y0 + 4), forged, fill=(20, 20, 20))
        items.append(_item(f"jpeg-resaved-after-edit-{tag}", "tampered", "jpeg-resaved-after-edit", "image",
                           _jpeg(edited, _exif(software="Editeur d'images 25.0", when="2026:02:20 18:30:00")), kind,
                           {"changed": "amount", "box": [x0, y0, x1, y1], "tool": "Pillow"}, issuer))
    return items


# ── ordinary negatives ───────────────────────────────────────────────────────
def _merged(pdf_bytes, other_bytes):
    writer = PdfWriter()
    for blob in (pdf_bytes, other_bytes):
        for page in PdfReader(io.BytesIO(blob)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _annotated(pdf_bytes):
    from pypdf.annotations import FreeText
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    writer.add_annotation(0, FreeText(text="Recu - signe", rect=(380, 60, 540, 90), font_size="10pt"))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _form_filled(kind, person, issuer, rng):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter, invariant=1, pageCompression=0)
    pdf.setProducer("ReportLab PDF Library")
    pdf.drawString(72, 720, f"{issuer} - formulaire ({kind})")
    pdf.acroForm.textfield(name="nom", tooltip="nom", x=72, y=670, width=240, height=20, borderStyle="inset")
    pdf.acroForm.textfield(name="montant", tooltip="montant", x=72, y=630, width=140, height=20, borderStyle="inset")
    pdf.showPage()
    pdf.save()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buffer.getvalue())))
    writer.update_page_form_field_values(writer.pages[0], {"nom": person, "montant": _money(rng)}, auto_regenerate=False)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _qpdf_resaved(pdf_bytes):
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        out = io.BytesIO()
        pdf.save(out, linearize=True, object_stream_mode=pikepdf.ObjectStreamMode.generate, deterministic_id=True)
    return out.getvalue()


def _scanned(picture, rng):
    tilted = picture.rotate(rng.uniform(-1.2, 1.2), fillcolor=(245, 245, 242), resample=Image.BICUBIC).filter(ImageFilter.GaussianBlur(0.8))
    out = io.BytesIO()
    tilted.convert("L").save(out, format="PDF", resolution=150.0, creationDate=FIXED_DATE.timetuple(), modDate=FIXED_DATE.timetuple())
    return out.getvalue()


def _photographed(picture, rng, with_exif):
    shot = picture.rotate(rng.uniform(-3, 3), fillcolor=(120, 118, 110), resample=Image.BICUBIC).filter(ImageFilter.GaussianBlur(1.1))
    return _jpeg(shot, _exif() if with_exif else None, quality=72)


def _ghostscript(pdf_bytes, setting):
    with tempfile.TemporaryDirectory() as folder:
        source, target = f"{folder}/in.pdf", f"{folder}/out.pdf"
        with open(source, "wb") as handle:
            handle.write(pdf_bytes)
        subprocess.run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", f"-dPDFSETTINGS={setting}", f"-sOutputFile={target}", source],
                       check=True, capture_output=True, env={"PATH": os.environ["PATH"], "SOURCE_DATE_EPOCH": str(int(FIXED_DATE.replace(tzinfo=timezone.utc).timestamp()))})
        with open(target, "rb") as handle:
            return handle.read()


def _negative(workflow, index, who, rng, pdf_bytes, picture):
    """One ordinary document through one ordinary workflow: ``(bytes, media)``. ``who`` is ``(kind, person, issuer)``."""
    kind, person, issuer = who
    if workflow == "merged":
        return _merged(pdf_bytes, clean_pdf("invoice", person, issuer, rng)[0]), "pdf"
    if workflow == "annotated":
        return _annotated(pdf_bytes), "pdf"
    if workflow == "form-filled":
        return _form_filled(kind, person, issuer, rng), "pdf"
    if workflow == "qpdf-resaved":
        return _qpdf_resaved(pdf_bytes), "pdf"
    if workflow == "scanned-from-print":
        return _scanned(picture, rng), "pdf"
    if workflow == "photographed":
        return _photographed(picture, rng, with_exif=index % 2 == 0), "image"
    return _ghostscript(pdf_bytes, "/printer" if workflow == "printed-to-pdf" else "/ebook"), "pdf"


def negatives_set(per_workflow=35, seed=SEED + 1):
    rng = _seeded(seed)
    available = tools()
    items = []
    for workflow, needs in NEGATIVE_WORKFLOWS.items():
        if needs == "gs" and not available["ghostscript"]:
            continue
        for index in range(per_workflow):
            kind, person = KINDS[index % 4], rng.choice(PEOPLE)
            issuer = rng.choice(BANKS if kind == "bank-statement" else EMPLOYERS)
            pdf_bytes, _, _ = clean_pdf(kind, person, issuer, rng, pages=3 if kind == "bank-statement" else 1)
            picture, _, _ = page_image(kind, person, issuer, rng)
            blob, media = _negative(workflow, index, (kind, person, issuer), rng, pdf_bytes, picture)
            items.append(_item(f"{workflow}-{index:02d}-{kind}", "negative", workflow, media, blob, kind, None, issuer))
    return items


def _item(identifier, role, variant, media, data, kind, truth, issuer):
    return {"id": identifier, "role": role, "variant": variant, "media": media, "documentKind": kind, "issuer": issuer, "truth": truth, "bytes": data}


def build(per_type=10, per_workflow=35):
    """The whole corpus: ``{"tampered": [...], "negatives": [...], "tools": {...}}``."""
    return {"tampered": tampered_set(per_type), "negatives": negatives_set(per_workflow), "tools": tools()}
