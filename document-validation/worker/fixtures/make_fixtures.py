#!/usr/bin/env python3
"""Builds the three PDFs the authenticity gate runs against, and says exactly how.

A fixture nobody can rebuild is a fixture nobody can check. Run:

    .venv/bin/python worker/fixtures/make_fixtures.py

- ``clean.pdf``          written once by reportlab, never reopened. One %%EOF, no /ModDate.
- ``modified.pdf``       ``clean.pdf`` reopened by pypdf, given a /ModDate two days after its
                         /CreationDate and a different /Producer, then APPENDED to the original
                         bytes as an incremental update — which is exactly what an editor does
                         when it saves a change into an existing file, and leaves two %%EOF.
- ``scanned.pdf``        a page bearing an image with an invisible text layer over it (render
                         mode 3) and an OCR tool named as producer: what a scan-then-OCR produces.
"""

import io
import os
import zlib

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
CREATED = "D:20260101090000"
MODIFIED = "D:20260103141500"


def _clean(path):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setAuthor("Agence Meridien")
    pdf.setTitle("Contrat de location")
    pdf.setProducer("Agence Meridien - chaine documentaire")
    for page, body in enumerate(
        [
            "CONTRAT DE LOCATION - LOGEMENT VIDE",
            "Article 2 - Duree et loyer",
            "Signatures",
        ],
        start=1,
    ):
        pdf.setFont("Helvetica", 12)
        pdf.drawString(72, 760, body)
        pdf.drawString(72, 730, f"Page {page} sur 3.")
        pdf.showPage()
    pdf.save()
    raw = buffer.getvalue()
    # reportlab writes /CreationDate; normalise it so the fixture is reproducible.
    raw = raw.replace(b"/ModDate", b"/XxxDate")
    with open(path, "wb") as handle:
        handle.write(raw)
    return raw


def _modified(clean_path, path):
    """An incremental update appended to the original bytes — how an editor saves a change."""
    with open(clean_path, "rb") as handle:
        original = handle.read()
    reader = PdfReader(io.BytesIO(original))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({
        "/Producer": "PDFescape Online",
        "/Creator": "PDFescape Online",
        "/CreationDate": CREATED,
        "/ModDate": MODIFIED,
    })
    revised = io.BytesIO()
    writer.write(revised)
    # Appended, not replaced: the first %%EOF stays, and the file records both writings.
    with open(path, "wb") as handle:
        handle.write(original + b"\n" + revised.getvalue())


def _scanned(path):
    """A page-sized image with invisible text drawn over it, and an OCR producer."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setProducer("Tesseract OCR 5.3")
    pdf.setCreator("Tesseract OCR 5.3")
    # A real (tiny) image object, scaled across the page — what a scan is.
    from reportlab.lib.utils import ImageReader
    from PIL import Image

    grey = Image.new("L", (64, 90), color=235)
    pdf.drawImage(ImageReader(grey), 0, 0, width=A4[0], height=A4[1])
    text = pdf.beginText(72, 760)
    text.setTextRenderMode(3)  # invisible: the OCR layer
    text.setFont("Helvetica", 12)
    text.textLine("CONTRAT DE LOCATION - LOGEMENT VIDE")
    text.textLine("Loyer mensuel : 850 EUR hors charges.")
    pdf.drawText(text)
    pdf.showPage()
    pdf.save()
    with open(path, "wb") as handle:
        handle.write(buffer.getvalue())


if __name__ == "__main__":
    clean = os.path.join(HERE, "clean.pdf")
    _clean(clean)
    _modified(clean, os.path.join(HERE, "modified.pdf"))
    _scanned(os.path.join(HERE, "scanned.pdf"))
    for name in ("clean.pdf", "modified.pdf", "scanned.pdf"):
        path = os.path.join(HERE, name)
        with open(path, "rb") as handle:
            raw = handle.read()
        print(f"{name}: {len(raw)} bytes, {raw.count(b'%%EOF')} %%EOF")
