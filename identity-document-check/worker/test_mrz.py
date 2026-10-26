#!/usr/bin/env python3
"""The machine-readable zone: ICAO Doc 9303 checksums and layouts, tested on the public specimens and on tampered variants.

Run: python3 test_mrz.py  (or python3 -m pytest test_mrz.py -q). The specimens are the ones ICAO prints in Doc 9303 itself
(the fictional Anna Maria Eriksson of Utopia, « UTO »): public, no real person.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "worker-common"))
import testkit  # noqa: E402
import mrz  # noqa: E402

TD3 = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]
TD2 = ["I<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<", "D231458907UTO7408122F1204159<<<<<<<6"]
TD1 = ["I<UTOD231458907<<<<<<<<<<<<<<<", "7408122F1204159UTO<<<<<<<<<<<6", "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"]


def _failed(parsed):
    return sorted(c["field"] for c in parsed["checks"] if not c["valid"])


def _swap(lines, line, index, char):
    out = list(lines)
    out[line] = out[line][:index] + char + out[line][index + 1:]
    return out


def test_the_check_digit_follows_the_weights_7_3_1():
    assert mrz.check_digit("L898902C3") == 6
    assert mrz.check_digit("740812") == 2
    assert mrz.check_digit("120415") == 9
    assert mrz.check_digit("ZE184226B<<<<<") == 1
    assert mrz.check_digit("<<<<<<") == 0


def test_a_character_outside_the_alphabet_is_refused_not_guessed():
    try:
        mrz.check_digit("AB-12")
    except ValueError:
        return
    raise AssertionError("an MRZ character outside 0-9, A-Z and < must be refused")


def test_the_icao_td3_specimen_parses_and_every_checksum_holds():
    parsed = mrz.parse(TD3)
    assert parsed["format"] == "TD3" and parsed["documentCode"] == "P" and parsed["issuer"] == "UTO"
    assert parsed["surname"] == "ERIKSSON" and parsed["givenNames"] == "ANNA MARIA"
    assert parsed["documentNumber"] == "L898902C3" and parsed["nationality"] == "UTO" and parsed["sex"] == "F"
    assert parsed["dateOfBirth"] == "740812" and parsed["dateOfExpiry"] == "120415"
    assert parsed["optionalData"] == "ZE184226B"
    assert _failed(parsed) == []
    assert {c["field"] for c in parsed["checks"]} == {"documentNumber", "dateOfBirth", "dateOfExpiry", "optionalData", "composite"}


def test_the_icao_td2_and_td1_specimens_parse_and_every_checksum_holds():
    for lines, fmt in ((TD2, "TD2"), (TD1, "TD1")):
        parsed = mrz.parse(lines)
        assert parsed["format"] == fmt
        assert parsed["surname"] == "ERIKSSON" and parsed["givenNames"] == "ANNA MARIA"
        assert parsed["documentNumber"] == "D23145890" and parsed["dateOfBirth"] == "740812"
        assert _failed(parsed) == [], (fmt, _failed(parsed))


def test_a_changed_digit_in_each_field_is_caught_by_its_own_checksum():
    cases = {
        "documentNumber": _swap(TD3, 1, 3, "9"),
        "dateOfBirth": _swap(TD3, 1, 15, "9"),
        "dateOfExpiry": _swap(TD3, 1, 24, "9"),
        "optionalData": _swap(TD3, 1, 30, "Q"),
    }
    for field, lines in cases.items():
        assert field in _failed(mrz.parse(lines)), field


def test_a_tampered_field_whose_own_checksum_was_recomputed_still_fails_the_composite():
    # Someone moves the expiry to 2032 and fixes the expiry digit; the composite digit still binds the whole line.
    digit = mrz.check_digit("320415")
    lines = list(TD3)
    lines[1] = lines[1][:21] + "320415" + str(digit) + lines[1][28:]
    parsed = mrz.parse(lines)
    assert "dateOfExpiry" not in _failed(parsed)
    assert _failed(parsed) == ["composite"]


def test_the_name_line_is_not_covered_by_a_checksum_so_the_pack_says_it():
    parsed = mrz.parse(_swap(TD3, 0, 8, "A"))
    assert _failed(parsed) == []
    assert "nameLine" in parsed["uncovered"]


def test_lines_are_read_loosely_but_the_shape_is_strict():
    assert mrz.parse([line.lower() + " " for line in TD3])["format"] == "TD3"
    for bad in ([], [TD3[0]], [TD3[0], TD3[1][:-1]], TD3 + TD3, ["!" * 44, "?" * 44]):
        try:
            mrz.parse(bad)
        except mrz.MrzError:
            continue
        raise AssertionError(f"{bad!r} was not refused")


def test_dates_are_real_calendar_days_and_the_century_follows_the_reference_day():
    assert mrz.expand_date("740812", "birth", "2026-10-26") == "1974-08-12"
    assert mrz.expand_date("120415", "expiry", "2026-10-26") == "2012-04-15"
    assert mrz.expand_date("260101", "birth", "2026-10-26") == "2026-01-01"
    assert mrz.expand_date("270101", "birth", "2026-10-26") == "1927-01-01"
    assert mrz.expand_date("740230", "birth", "2026-10-26") is None  # 30 February
    assert mrz.expand_date("74081", "birth", "2026-10-26") is None
    assert mrz.expand_date("7408<2", "birth", "2026-10-26") is None


if __name__ == "__main__":
    testkit.main(globals())
