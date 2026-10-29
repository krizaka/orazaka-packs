"""Every pattern a pack ships is safe to run on an uploaded document (Sonar pythonsecurity:S2631, ReDoS).

The patterns are data (kinds/*.json, rulesets/**/*.json) and they run on the text of a document someone uploaded. A
pattern with a repeated group that itself repeats — « (a+)+ », « (\\w*\\s?)* » — can take exponential time on a crafted
text. This test refuses them before they ship. Run: python3 test_regex_safety.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

# A group whose body holds an unbounded quantifier (+, *, {n,}) and that is itself repeated without bound.
NESTED = re.compile(r"\((?:\?:)?(?:[^()\\]|\\.)*(?:[+*]|\{\d+,\})(?:[^()\\]|\\.)*\)(?:[+*]|\{\d+,\})")


def _patterns(node, path):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("pattern", "subject", "label") and isinstance(value, str):
                yield f"{path}.{key}", value
            elif key == "excludes" and isinstance(value, list):
                for i, v in enumerate(value):
                    if isinstance(v, str):
                        yield f"{path}.excludes[{i}]", v
            else:
                yield from _patterns(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _patterns(value, f"{path}[{i}]")


def shipped_patterns():
    for folder in ("kinds", "rulesets"):
        for base, _, files in os.walk(os.path.join(ROOT, folder)):
            for name in sorted(files):
                if name.endswith(".json") and not name.endswith(".schema.json"):
                    file = os.path.join(base, name)
                    with open(file, encoding="utf-8") as handle:
                        yield from _patterns(json.load(handle), os.path.relpath(file, ROOT))


def test_the_linter_catches_the_classic_shapes():
    for bad in ["(a+)+", "(\\w*\\s?)*", "(?:x+y)+", "(ab*){2,}"]:
        assert NESTED.search(bad), bad
    for good in ["(?i)d[ée]p[ôo]ts?\\s+(?:de\\s+)?garantie", "(\\d{1,2})\\s+(janvier|f[ée]vrier)", "(?:ab)+", "a+b*"]:
        assert not NESTED.search(good), good


def test_no_shipped_pattern_nests_unbounded_quantifiers():
    found = [(where, p) for where, p in shipped_patterns() if NESTED.search(p)]
    assert not found, "patterns that can backtrack exponentially: " + "; ".join(f"{w}: {p}" for w, p in found)


def test_the_declared_facts_are_scanned():
    """`facts[].pattern` and `facts[].label` (rents read for Section G) run on the document like a rule's pattern."""
    where = [w for w, _ in shipped_patterns()]
    assert any(".facts[" in w and w.endswith(".label") for w in where), "facts labels are not scanned"
    assert any(".facts[" in w and w.endswith(".pattern") for w in where), "facts patterns are not scanned"


def test_every_shipped_pattern_compiles():
    for where, pattern in shipped_patterns():
        try:
            re.compile(pattern)
        except re.error as exc:
            raise AssertionError(f"{where}: {exc}") from exc


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
