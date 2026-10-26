"""The machine-readable zone of a travel or identity document (ICAO Doc 9303), read by arithmetic and never by a model.

A vision model may *transcribe* the zone; what the transcription means is decided here, in plain code: the layout of
the three formats (TD1, TD2, TD3), the check digits (weights 7-3-1 modulo 10) and the calendar. A pure module: no broker,
no clock (the reference day is a parameter), no model — so the part that says « this zone does not add up » is the part
that is tested hardest, on the public specimens of the standard and on tampered variants of them.

The name line is covered by no check digit. A caller must therefore not read « all checksums hold » as « the names are
right »: the parse says so in ``uncovered``.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional

WEIGHTS = (7, 3, 1)
FILLER = "<"
#: Lines per format and their length: the three shapes the standard allows.
SHAPES = {"TD1": (3, 30), "TD2": (2, 36), "TD3": (2, 44)}


class MrzError(ValueError):
    """The lines are not the shape of any machine-readable zone."""


def _value(char: str) -> int:
    if char.isdigit():
        return int(char)
    if "A" <= char <= "Z":
        return ord(char) - 55
    if char == FILLER:
        return 0
    raise ValueError(f"{char!r} is not an MRZ character (0-9, A-Z, <)")


def check_digit(field: str) -> int:
    """The ICAO check digit of ``field``: the sum of each character's value times 7, 3, 1 repeating, modulo 10."""
    return sum(_value(char) * WEIGHTS[index % 3] for index, char in enumerate(field)) % 10


def normalise(lines) -> list:
    """Upper case, no blanks: what a transcription looks like once the obvious noise of OCR is taken out."""
    return [re.sub(r"\s+", "", str(line)).upper() for line in lines if str(line).strip()]


def _format_of(lines: list) -> str:
    for name, (count, width) in SHAPES.items():
        if len(lines) == count and all(len(line) == width for line in lines):
            return name
    raise MrzError("the lines are not a TD1 (3 x 30), TD2 (2 x 36) or TD3 (2 x 44) zone")


def _names(field: str) -> tuple:
    surname, _, given = field.partition("<<")
    clean = lambda text: re.sub(r"\s+", " ", text.replace(FILLER, " ")).strip()  # noqa: E731
    return clean(surname), clean(given)


def _check(name: str, field: str, digit_char: str) -> dict:
    # An unreadable digit (a filler where a digit is due) is a failed check, not an exception.
    expected = check_digit(field)
    found = int(digit_char) if digit_char.isdigit() else None
    return {"field": name, "value": field, "expected": expected, "found": found, "valid": found == expected}


def parse(raw_lines) -> dict:
    """Parse and verify a zone. Raises :class:`MrzError` for a shape that is not a zone; a *wrong* zone is a parse whose
    ``checks`` say which digit failed."""
    lines = normalise(raw_lines)
    if not lines:
        raise MrzError("no lines")
    try:
        fmt = _format_of(lines)
        for line in lines:
            for char in line:
                _value(char)
    except ValueError as bad:
        if isinstance(bad, MrzError):
            raise
        raise MrzError(str(bad)) from bad
    if fmt == "TD1":
        return _td1(lines)
    return _td3_or_td2(lines, fmt)


def _td3_or_td2(lines: list, fmt: str) -> dict:
    first, second = lines
    surname, given = _names(first[5:])
    number = second[0:9]
    optional_end = 42 if fmt == "TD3" else 35
    optional = second[28:optional_end]
    checks = [
        _check("documentNumber", number, second[9]),
        _check("dateOfBirth", second[13:19], second[19]),
        _check("dateOfExpiry", second[21:27], second[27]),
    ]
    if fmt == "TD3":
        checks.append(_check("optionalData", optional, second[42]) if optional.strip(FILLER) else
                      {"field": "optionalData", "value": optional, "expected": None, "found": None, "valid": second[42] in (FILLER, "0")})
        composite = second[0:10] + second[13:20] + second[21:43]
        checks.append(_check("composite", composite, second[43]))
    else:
        composite = second[0:10] + second[13:20] + second[21:35]
        checks.append(_check("composite", composite, second[35]))
    return {
        "format": fmt,
        "documentCode": first[0:2].strip(FILLER),
        "issuer": first[2:5].strip(FILLER),
        "surname": surname,
        "givenNames": given,
        "documentNumber": number.rstrip(FILLER),
        "nationality": second[10:13].strip(FILLER),
        "dateOfBirth": second[13:19],
        "sex": second[20],
        "dateOfExpiry": second[21:27],
        "optionalData": optional.rstrip(FILLER),
        "checks": checks,
        "uncovered": ["nameLine", "sex", "issuer", "nationality", "documentCode"],
    }


def _td1(lines: list) -> dict:
    first, second, third = lines
    surname, given = _names(third)
    number = first[5:14]
    composite = first[5:30] + second[0:7] + second[8:15] + second[18:29]
    checks = [
        _check("documentNumber", number, first[14]),
        _check("dateOfBirth", second[0:6], second[6]),
        _check("dateOfExpiry", second[8:14], second[14]),
        _check("composite", composite, second[29]),
    ]
    return {
        "format": "TD1",
        "documentCode": first[0:2].strip(FILLER),
        "issuer": first[2:5].strip(FILLER),
        "surname": surname,
        "givenNames": given,
        "documentNumber": number.rstrip(FILLER),
        "nationality": second[15:18].strip(FILLER),
        "dateOfBirth": second[0:6],
        "sex": second[7],
        "dateOfExpiry": second[8:14],
        "optionalData": (first[15:30] + second[18:29]).replace(FILLER, "").strip(),
        "checks": checks,
        "uncovered": ["nameLine", "sex", "issuer", "nationality", "documentCode"],
    }


def expand_date(yymmdd: str, kind: str, as_of: str) -> Optional[str]:
    """``YYMMDD`` as ``YYYY-MM-DD``, or ``None`` when it is not a real calendar day.

    The zone has two digits for the year. A birth date is the latest century that is not after the reference day (a
    ``27`` read on 2026-10-26 is 1927, never 2027); an expiry date is read in the 2000s.
    """
    if not isinstance(yymmdd, str) or not re.fullmatch(r"\d{6}", yymmdd):
        return None
    yy, month, day = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    reference = dt.date.fromisoformat(as_of)
    year = 2000 + yy
    if kind == "birth":
        try:
            if dt.date(year, month, day) > reference:
                year -= 100
        except ValueError:
            return None
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None
