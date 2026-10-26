"""The identity-document rules: what a vision model *read* off a document, turned into findings and a status.

Pure functions of ``(ruleset, reading, reference day, the caller's options)`` — no broker, no model, no clock. A vision
model transcribes (the zone's lines, the printed fields) and reports what it *sees* (signs of tampering, a bad capture).
Everything that can be decided by arithmetic is decided here, in code: the check digits (:mod:`mrz`), the calendar, the
agreement between the printed fields, the zone and the barcode.

Each finding carries its **evidence** (the source, the field, the value read and where on the document) and a
**confidence** (the model's confidence in the reading the finding rests on). Two principles keep the verdict honest:

* a vision signal asks a person to look; it never fails a document by itself (``REVIEW``, not ``INCONSISTENT``);
* a failed check digit on a *doubtful transcription* asks for a new capture instead of accusing the document.

The report is **codes**: the product that asked words them. It identifies no one and looks nothing up (``limits``).
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import unicodedata
from typing import Optional

import mrz

HERE = os.path.dirname(os.path.abspath(__file__))
RULESETS = os.path.join(HERE, "..", "rules", "identity-document")

FAIL, WARN, INFO = "FAIL", "WARN", "INFO"
DETERMINISTIC, MODEL = "DETERMINISTIC", "MODEL"
_DEFAULT_CONFIDENCE = 0.5


class InvalidReading(ValueError):
    """The reading handed to the rules is not the shape the vision step is asked for — the caller's input is wrong."""


def load_ruleset(as_of: Optional[str] = None) -> dict:
    """The ruleset in force on ``as_of`` (``YYYY-MM-DD``) — the newest file only when no day is given."""
    files = sorted(glob.glob(os.path.join(RULESETS, "*.json")))
    chosen = None
    for path in files:
        effective = os.path.basename(path)[: -len(".json")]
        if as_of is None or effective <= as_of:
            chosen = path
    if chosen is None:
        raise FileNotFoundError("no identity-document ruleset in force on " + str(as_of))
    with open(chosen, encoding="utf-8") as handle:
        return json.load(handle)


def parse_reading(raw) -> dict:
    """A reading from the vision step: an object, or the text of one (possibly in a markdown fence, as models answer)."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise InvalidReading("the reading must be a JSON object")
    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as bad:
        raise InvalidReading("the reading is not JSON") from bad
    if not isinstance(value, dict):
        raise InvalidReading("the reading must be a JSON object")
    return value


# --- helpers -----------------------------------------------------------------------------------------------------

def _clamp(value, default=_DEFAULT_CONFIDENCE) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _ascii_name(text) -> str:
    """The zone's alphabet: upper case, accents removed, anything that is not a letter dropped (a hyphen is a filler)."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return re.sub(r"[^A-Z]", "", decomposed.encode("ascii", "ignore").decode().upper())


def _compact(text) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _iso(text) -> Optional[str]:
    """``YYYY-MM-DD`` or ``YYYYMMDD`` as a real day, else ``None``."""
    match = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})", str(text or "").strip())
    if not match:
        return None
    try:
        return dt.date(int(match[1]), int(match[2]), int(match[3])).isoformat()
    except ValueError:
        return None


def _finding(code, severity, field, basis, evidence, confidence, **extra) -> dict:
    return dict({"code": code, "severity": severity, "field": field, "basis": basis, "evidence": evidence, "confidence": confidence}, **extra)


def _years_between(born: str, as_of: str) -> int:
    b, a = dt.date.fromisoformat(born), dt.date.fromisoformat(as_of)
    return a.year - b.year - ((a.month, a.day) < (b.month, b.day))


# --- the barcode (AAMVA data elements, as a driver's licence prints them) ------------------------------------------

def parse_barcode(text: str) -> dict:
    """The data elements the checks need, read from the decoded text of a PDF417 (AAMVA ``DAQ`` ``DCS`` ``DAC`` ``DBB`` ``DBA``)."""
    fields = {}
    for line in re.split(r"[\r\n]+", text or ""):
        line = line.strip("\x1e\x1d@ ")
        for tag, name in (("DAQ", "documentNumber"), ("DCS", "surname"), ("DAC", "givenNames"), ("DBB", "dateOfBirth"), ("DBA", "dateOfExpiry")):
            if line.startswith(tag) and name not in fields:
                value = line[len(tag):].strip()
                fields[name] = _iso(value) if name.startswith("dateOf") else value
    return {k: v for k, v in fields.items() if v}


# --- the assessment ------------------------------------------------------------------------------------------------

def assess(ruleset: dict, reading, as_of: str, minimum_age: Optional[int] = None, barcode_text: Optional[str] = None) -> dict:
    if not isinstance(reading, dict):
        raise InvalidReading("the reading must be a JSON object")
    lines = reading.get("mrzLines")
    if lines is None:
        lines = []
    if not isinstance(lines, list):
        raise InvalidReading("'mrzLines' must be a list of strings")
    printed = reading.get("printed")
    if printed is None:
        printed = {}
    if not isinstance(printed, dict):
        raise InvalidReading("'printed' must be an object")
    confidence = reading.get("confidence") if isinstance(reading.get("confidence"), dict) else {}
    mrz_conf, printed_conf = _clamp(confidence.get("mrz")), _clamp(confidence.get("printed"))
    thresholds = ruleset["thresholds"]
    findings: list = []
    fields: dict = {}
    mrz_info: dict = {"present": False}

    # 1. the machine-readable zone
    parsed = None
    if [line for line in lines if str(line).strip()]:
        try:
            parsed = mrz.parse(lines)
        except mrz.MrzError as bad:
            findings.append(_finding("MRZ_UNREADABLE", WARN, "mrz", DETERMINISTIC, {"source": "mrz", "field": "mrz", "value": str(bad), "region": "mrz"}, mrz_conf))
    else:
        findings.append(_finding("MRZ_ABSENT", INFO, "mrz", DETERMINISTIC, {"source": "mrz", "field": "mrz", "value": None, "region": "mrz"}, mrz_conf))
    doubtful = mrz_conf < thresholds["lowReadConfidence"]
    if parsed:
        mrz_info = {"present": True, "format": parsed["format"], "checksumsValid": all(c["valid"] for c in parsed["checks"]), "uncovered": parsed["uncovered"]}
        findings.extend(_checksum_findings(parsed, mrz_conf, doubtful))
        fields.update(_mrz_fields(parsed, as_of))

    # 2. the printed fields, and their agreement with the zone
    printed_fields = _printed_fields(printed)
    for name, value in printed_fields.items():
        fields.setdefault(name, value)
    if parsed:
        findings.extend(_compare("printed", printed, printed_fields, fields, printed_conf, "PRINTED_MRZ_MISMATCH", doubtful))
    # 3. the barcode
    barcode = {"present": False}
    if barcode_text and barcode_text.strip():
        extracted = parse_barcode(barcode_text)
        barcode = {"present": True, "fields": sorted(extracted)}
        findings.extend(_compare("barcode", extracted, extracted, printed_fields or fields, printed_conf, "BARCODE_MISMATCH", False))
    # 4. the calendar
    findings.extend(_date_findings(fields, as_of, printed_conf if not parsed else mrz_conf))
    age = None
    if fields.get("dateOfBirth") and dt.date.fromisoformat(fields["dateOfBirth"]) <= dt.date.fromisoformat(as_of):
        years = _years_between(fields["dateOfBirth"], as_of)
        age = {"years": years, "minimum": minimum_age, "meets": minimum_age is None or years >= minimum_age}
        if not age["meets"]:
            findings.append(_finding("AGE_BELOW_MINIMUM", WARN, "dateOfBirth", DETERMINISTIC, {"source": "mrz" if parsed else "printed", "field": "dateOfBirth", "value": fields["dateOfBirth"], "region": "dateOfBirth"}, mrz_conf if parsed else printed_conf))
    # 5. what the model saw
    ignored = 0
    findings_signals, ignored = _signal_findings(reading.get("signals"), thresholds, ruleset)
    findings.extend(findings_signals)
    findings.extend(_quality_findings(reading.get("quality"), ruleset))

    return {
        "rulesetId": ruleset["rulesetId"],
        "rulesetVersion": ruleset["version"],
        "rulesetRevision": ruleset["revision"],
        "asOf": as_of,
        "documentType": reading.get("documentType") if reading.get("documentType") in ruleset["documentTypes"] else "OTHER",
        "issuer": str(reading.get("issuer") or fields.get("issuer") or "")[:3] or None,
        "status": _status(findings, fields, parsed),
        "fields": fields,
        "mrz": mrz_info,
        "barcode": barcode,
        "age": age,
        "findings": findings,
        "ignoredSignals": ignored,
        "limits": list(ruleset["limits"]),
    }


def _region(parsed: dict, name: str) -> str:
    layouts = {
        "TD3": {"documentNumber": "mrz.line2[0:9]", "dateOfBirth": "mrz.line2[13:19]", "dateOfExpiry": "mrz.line2[21:27]", "optionalData": "mrz.line2[28:42]", "composite": "mrz.line2[0:10]+[13:20]+[21:43]"},
        "TD2": {"documentNumber": "mrz.line2[0:9]", "dateOfBirth": "mrz.line2[13:19]", "dateOfExpiry": "mrz.line2[21:27]", "optionalData": "mrz.line2[28:35]", "composite": "mrz.line2[0:10]+[13:20]+[21:35]"},
        "TD1": {"documentNumber": "mrz.line1[5:14]", "dateOfBirth": "mrz.line2[0:6]", "dateOfExpiry": "mrz.line2[8:14]", "optionalData": "mrz.line1[15:30]+line2[18:29]", "composite": "mrz.line1[5:30]+line2[0:7]+[8:15]+[18:29]"},
    }
    return layouts[parsed["format"]].get(name, "mrz")


def _checksum_findings(parsed: dict, mrz_conf: float, doubtful: bool) -> list:
    out = []
    for check in parsed["checks"]:
        if check["valid"]:
            continue
        evidence = {"source": "mrz", "field": check["field"], "value": check["value"], "region": _region(parsed, check["field"]), "expectedCheckDigit": check["expected"], "foundCheckDigit": check["found"]}
        out.append(_finding("MRZ_CHECKSUM_FAILED", WARN if doubtful else FAIL, check["field"], DETERMINISTIC, evidence, mrz_conf, maybeTranscription=doubtful))
    return out


def _mrz_fields(parsed: dict, as_of: str) -> dict:
    out = {
        "surname": parsed["surname"],
        "givenNames": parsed["givenNames"],
        "documentNumber": parsed["documentNumber"],
        "sex": parsed["sex"] if parsed["sex"] in ("M", "F") else ("X" if parsed["sex"] in ("X", "<") else None),
        "issuer": parsed["issuer"],
        "nationality": parsed["nationality"],
    }
    birth = mrz.expand_date(parsed["dateOfBirth"], "birth", as_of)
    expiry = mrz.expand_date(parsed["dateOfExpiry"], "expiry", as_of)
    out["dateOfBirth"], out["dateOfExpiry"] = birth, expiry
    out["_invalidDates"] = [n for n, v in (("dateOfBirth", birth), ("dateOfExpiry", expiry)) if v is None]
    return {k: v for k, v in out.items() if v not in (None, "") or k == "_invalidDates"}


def _printed_fields(printed: dict) -> dict:
    out = {}
    for name in ("surname", "givenNames", "documentNumber", "sex"):
        if printed.get(name):
            out[name] = str(printed[name]).strip()
    for name in ("dateOfBirth", "dateOfExpiry"):
        if printed.get(name):
            iso = _iso(printed[name])
            out[name] = iso if iso else "INVALID:" + str(printed[name])[:20]
    return out


def _same(name: str, a, b) -> bool:
    if name in ("surname", "givenNames"):
        left, right = _ascii_name(a), _ascii_name(b)
        return left == right or (min(len(left), len(right)) >= 20 and (left.startswith(right) or right.startswith(left)))  # the zone truncates long names
    if name == "documentNumber":
        return _compact(a) == _compact(b)
    return str(a).upper() == str(b).upper()


def _compare(source: str, raw: dict, values: dict, reference: dict, conf: float, code: str, doubtful) -> list:
    out = []
    for name, value in values.items():
        if name not in reference or name.startswith("_") or str(value).startswith("INVALID:"):
            continue
        if source == "barcode" and name not in ("surname", "documentNumber", "dateOfBirth", "dateOfExpiry"):
            continue
        if not _same(name, value, reference[name]):
            evidence = {"source": source, "field": name, "value": value, "against": reference[name], "region": name}
            if doubtful:  # the zone itself is a doubtful transcription: the difference may be the reading's, not the document's
                out.append(_finding(code, WARN, name, DETERMINISTIC, evidence, conf, maybeTranscription=True))
            else:
                out.append(_finding(code, FAIL, name, DETERMINISTIC, evidence, conf))
    return out


def _date_findings(fields: dict, as_of: str, conf: float) -> list:
    out = []
    today = dt.date.fromisoformat(as_of)
    invalid = set(fields.get("_invalidDates", []))
    for name in ("dateOfBirth", "dateOfExpiry"):
        value = fields.get(name)
        if isinstance(value, str) and value.startswith("INVALID:"):
            invalid.add(name)
    for name in sorted(invalid):
        out.append(_finding("DATE_INVALID", FAIL, name, DETERMINISTIC, {"source": "document", "field": name, "value": None, "region": name}, conf))
    fields.pop("_invalidDates", None)
    for name in invalid:
        fields.pop(name, None)
    birth, expiry = fields.get("dateOfBirth"), fields.get("dateOfExpiry")
    if birth and dt.date.fromisoformat(birth) > today:
        out.append(_finding("BIRTH_IN_FUTURE", FAIL, "dateOfBirth", DETERMINISTIC, {"source": "document", "field": "dateOfBirth", "value": birth, "region": "dateOfBirth"}, conf))
    if birth and expiry and dt.date.fromisoformat(expiry) <= dt.date.fromisoformat(birth):
        out.append(_finding("EXPIRY_BEFORE_BIRTH", FAIL, "dateOfExpiry", DETERMINISTIC, {"source": "document", "field": "dateOfExpiry", "value": expiry, "against": birth, "region": "dateOfExpiry"}, conf))
    elif expiry and dt.date.fromisoformat(expiry) < today:
        out.append(_finding("DOCUMENT_EXPIRED", WARN, "dateOfExpiry", DETERMINISTIC, {"source": "document", "field": "dateOfExpiry", "value": expiry, "region": "dateOfExpiry"}, conf))
    return out


def _signal_findings(signals, thresholds: dict, ruleset: dict):
    out, ignored = [], 0
    for signal in signals if isinstance(signals, list) else []:
        if not isinstance(signal, dict) or signal.get("kind") not in ruleset["signalKinds"]:
            ignored += 1
            continue
        conf = _clamp(signal.get("confidence"), 0.0)
        severity = WARN if conf >= thresholds["tamperReview"] else INFO
        region = str(signal.get("region") or "document")[:60]
        out.append(_finding("TAMPERING_SIGNAL", severity, signal["kind"], MODEL, {"source": "vision", "field": signal["kind"], "value": signal["kind"], "region": region}, conf))
    return out, ignored


def _quality_findings(quality, ruleset: dict) -> list:
    out = []
    if isinstance(quality, dict):
        for kind in ruleset["qualityKinds"]:
            if quality.get(kind) is True:
                out.append(_finding("QUALITY_POOR", WARN, kind, MODEL, {"source": "vision", "field": kind, "value": True, "region": "document"}, 1.0))
    return out


def _status(findings: list, fields: dict, parsed) -> str:
    if not parsed and not any(fields.get(k) for k in ("documentNumber", "dateOfBirth", "surname")):
        return "UNREADABLE"
    severities = {f["severity"] for f in findings}
    if FAIL in severities:
        return "INCONSISTENT"
    if WARN in severities:
        return "REVIEW"
    return "CONSISTENT"
