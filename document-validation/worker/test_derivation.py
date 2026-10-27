#!/usr/bin/env python3
"""Stage 3 of ADR-089 (krizaka/orazaka-ai-engine#82): the derivation's data, read by this worker's own code.

The engine derives proposed rules and vets them (orazaka-ai-engine ``RuleProposalVet``) before they reach
``rule_proposal``; a proposal becomes a ruleset of this pack only through promotion (cut 9), where these tests and
``test_rules.py`` run on it. This suite pins that the engine's verdicts are this worker's:

- the recorded rules of the visit notice discriminate their fixtures under ``rules.evaluate``, quote art. 1931 to 1933
  as ``citations.check`` reads them, and cite no rent article;
- each planted proposal of ``derivation/planted`` fails here for the reason the engine gives it.

Pure data and pure functions: no model, no network, no clock. Run: python3 test_derivation.py
"""
import json
import os
import re
import sys

import citations
import rules
from test_regex_safety import NESTED

HERE = os.path.dirname(os.path.abspath(__file__))
DERIVATION = os.path.join(HERE, "..", "derivation")
HELD = citations.load_articles(os.path.join(DERIVATION, "law"))

#: The rent articles a visit notice must never bring in (ADR-089, « What went wrong »).
RENT_ARTICLES = {"1855", "1896", "1903", "1904"}

#: Numbers as the engine reads them (RuleFigures): digits, and the words it maps; « un » / « one » are left out.
_WORDS = {"vingt-quatre": "24", "quarante-huit": "48", "twenty-four": "24", "deux": "2", "trois": "3", "sept": "7",
          "neuf": "9", "dix": "10", "douze": "12"}


def _load(*parts):
    with open(os.path.join(DERIVATION, *parts), encoding="utf-8") as handle:
        return json.load(handle)


def _answers():
    return _load("qc-visit-notice.fr.answers.json")["answers"]


def _planted():
    folder = os.path.join(DERIVATION, "planted")
    return [dict(_load("planted", name), name=name) for name in sorted(os.listdir(folder)) if name.endswith(".json")]


def _excerpts():
    """The passages of each held article that the recorded answers quote, by article hash.

    ``derivation/law/`` holds the reference of an article (its hash, its official address), never its text: a Québec
    article is not reproduced in a public repository (the engine reads it from the official source). The quote check is
    exercised against the short passages the recorded answers themselves quote, so a quote that is not one of them
    is ``QUOTE_NOT_IN_ARTICLE`` here as it is in the engine.
    """
    found = {}
    for answer in _answers().values():
        for rule in answer["rules"]:
            for block in rule["law"]:
                found.setdefault(block["contentHash"], []).append(block["quote"])
    return {h: " ".join(quotes) for h, quotes in found.items()}


EXCERPTS = None


def _text_of(article):
    global EXCERPTS
    if EXCERPTS is None:
        EXCERPTS = _excerpts()
    return EXCERPTS.get(article["contentHash"])


def _as_list(value):
    return value if isinstance(value, list) else [value]


def _ruleset(rule):
    return {"rulesetId": "derivation", "rules": [rule]}


def _discriminates(rule):
    """The verdicts test_rules.py asks of a shipped rule: PASS on each pass fragment, FAIL on each fail one."""
    wrong = []
    for want, fragments in (("PASS", rule["fixtures"]["pass"]), ("FAIL", rule["fixtures"]["fail"])):
        for text in _as_list(fragments):
            got = rules.evaluate(_ruleset(rule), rule, text)["verdict"]
            if got != want:
                wrong.append(f"{want} expected, {got} on {text!r}")
    return wrong


def _figures(text):
    s = (text or "").lower()
    found = set(re.findall(r"\d+", s))
    found |= {v for w, v in _WORDS.items() if re.search(rf"(?<![\w-]){w}(?![\w-])", s)}
    return found


def _unsupported(rule):
    supported = set().union(*(_figures(b["quote"]) for b in rule["law"]))
    refs = set().union(*(_figures(b["ref"]) for b in rule["law"]))
    stated = set().union(*(_figures(rule.get(k)) for k in ("title", "question", "onPass", "onFail")))
    return stated - supported - refs


def _patterns(rule):
    found = [rule["check"]["pattern"]] if rule.get("method") == "DETERMINISTIC" else []
    return found + ([rule["subject"]] if rule.get("subject") else [])


def _compiles(pattern):
    try:
        re.compile(pattern)
        return not NESTED.search(pattern)
    except re.error:
        return False


# ── the golden case ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_held_articles_are_the_visit_notice_articles_by_reference_only():
    assert sorted(a["ref"] for a in HELD.values()) == ["1931", "1932", "1933"]
    assert all("text" not in a and a["officialUrl"].startswith("https://www.legisquebec.gouv.qc.ca/") for a in HELD.values())
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in HELD)


def test_an_article_held_by_reference_with_no_text_is_not_verified():
    block = _answers()["1931"]["rules"][0]["law"][0]
    assert citations.check(block, HELD) == citations.TEXT_NOT_HELD


def test_the_visit_notice_rules_discriminate_their_fixtures_in_this_worker():
    checked = 0
    for ref, answer in _answers().items():
        for rule in answer["rules"]:
            if rule["method"] == "JUDGMENT":
                assert rule["severity"] == "ADVISORY" and rule.get("subject"), rule["ruleId"]
                continue
            assert not _discriminates(rule), (rule["ruleId"], _discriminates(rule))
            checked += 1
    assert checked == 3


def test_the_visit_notice_rules_quote_their_articles_and_cite_no_rent_article():
    for ref, answer in _answers().items():
        for rule in answer["rules"]:
            for block in rule["law"]:
                assert block["ref"] == ref and block["ref"] not in RENT_ARTICLES, rule["ruleId"]
                assert citations.check(block, HELD, _text_of) == citations.VERIFIED, rule["ruleId"]
            assert all(_compiles(p) for p in _patterns(rule)), rule["ruleId"]
            assert not _unsupported(rule), (rule["ruleId"], _unsupported(rule))


def test_a_forbidden_rule_passes_only_a_fragment_that_addresses_its_subject():
    rule = _answers()["1932"]["rules"][0]
    assert rule["check"]["type"] == "FORBIDDEN_PATTERN"
    assert rules.evaluate(_ruleset(rule), rule, "Le locateur passera.")["verdict"] == rules.NOT_APPLICABLE


def test_an_answer_citing_an_article_the_corpus_does_not_hold_is_not_verified():
    outside = _load("qc-visit-notice.fr.outside-corpus.answer.json")["rules"][1]
    assert citations.check(outside["law"][0], HELD, _text_of) == citations.ARTICLE_NOT_HELD


# ── the planted cases: each fails here for the engine's reason ────────────────────────────────────────────────────

def _fails_for(reason, rule, planted):
    if reason == "SCHEMA_INVALID":
        return rule["method"] == "JUDGMENT" and rule["severity"] != "ADVISORY"
    if reason == "REGEX_INVALID":
        return not all(_compiles(p) for p in _patterns(rule))
    if reason == "REGEX_MATCHES_EMPTY":
        return any(_compiles(p) and re.search(p, "") is not None for p in _patterns(rule))
    if reason == "QUOTE_NOT_IN_ARTICLE":
        return any(citations.check(b, HELD, _text_of) == citations.QUOTE_NOT_IN_ARTICLE for b in rule["law"])
    if reason == "UNSUPPORTED_NUMBER":
        return bool(_unsupported(rule))
    if reason == "FIXTURES_INDISTINCT":
        return bool(_discriminates(rule))
    if reason == "SUBJECT_MISSING":
        # Without a subject the worker can never say PASS: every document without the wording is INSUFFICIENT_EVIDENCE.
        return not rule.get("subject") and all(
            rules.evaluate(_ruleset(rule), rule, t)["verdict"] == rules.INSUFFICIENT_EVIDENCE
            for t in _as_list(rule["fixtures"]["pass"]))
    if reason == "LAW_VERSION_UNKNOWN":
        return any(citations.check(b, HELD, _text_of) == citations.ARTICLE_NOT_HELD for b in rule["law"])
    if reason == "OVER_RULE_LIMIT":
        return [r["ruleId"] for r in planted["rules"]].index(rule["ruleId"]) >= planted["maxRulesPerKind"]
    raise AssertionError(f"unknown reason {reason}")


def test_each_planted_proposal_fails_in_this_worker_for_its_reason():
    seen = set()
    for planted in _planted():
        rule = next(r for r in planted["rules"] if r["ruleId"] == planted["plantedRuleId"])
        assert _fails_for(planted["reason"], rule, planted), planted["name"]
        seen.add(planted["reason"])
    assert seen == {"SCHEMA_INVALID", "REGEX_INVALID", "REGEX_MATCHES_EMPTY", "QUOTE_NOT_IN_ARTICLE",
                    "UNSUPPORTED_NUMBER", "FIXTURES_INDISTINCT", "SUBJECT_MISSING", "LAW_VERSION_UNKNOWN",
                    "OVER_RULE_LIMIT"}


def test_a_planted_proposal_fails_for_its_reason_only():
    # The engine rejects each plant for exactly one reason; here, every other check this suite can run passes on it.
    for planted in _planted():
        rule = next(r for r in planted["rules"] if r["ruleId"] == planted["plantedRuleId"])
        reason = planted["reason"]
        if reason in ("SCHEMA_INVALID", "OVER_RULE_LIMIT"):
            continue  # the engine reads nothing else of such a rule
        others = [r for r in ("REGEX_INVALID", "REGEX_MATCHES_EMPTY", "QUOTE_NOT_IN_ARTICLE", "UNSUPPORTED_NUMBER",
                              "LAW_VERSION_UNKNOWN") if r != reason]
        if reason not in ("REGEX_INVALID", "REGEX_MATCHES_EMPTY", "FIXTURES_INDISTINCT") and rule["method"] == "DETERMINISTIC":
            others.append("FIXTURES_INDISTINCT")
        for other in others:
            if other == "FIXTURES_INDISTINCT" and reason == "SUBJECT_MISSING":
                continue  # without a subject the worker cannot PASS; the engine checks the pattern pair only
            assert not _fails_for(other, rule, planted), (planted["name"], other)


def test_the_sound_rules_beside_a_plant_pass_every_check():
    for planted in _planted():
        for rule in planted["rules"]:
            if rule["ruleId"] == planted["plantedRuleId"]:
                continue
            assert not _discriminates(rule) and not _unsupported(rule), (planted["name"], rule["ruleId"])
            assert all(citations.check(b, HELD, _text_of) == citations.VERIFIED for b in rule["law"]), rule["ruleId"]


def _run_all() -> int:
    """Runs every test of this file, prints one line each, and returns how many failed."""
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — a failing check is reported, never raised past the summary
            failed.append(name)
            print(f"  FAIL {name}: {exc!r}")
        else:
            print(f"  ok   {name}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} green" + (f", failed: {', '.join(failed)}" if failed else ""))
    return len(failed)


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
