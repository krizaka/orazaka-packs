"""The tiny runner the pack workers' test files share: `python3 test_x.py` runs every `test_*` function of the file and exits 1 on a failure."""
import sys


def main(namespace: dict) -> None:
    failures = 0
    for name, fn in sorted(namespace.items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print(f"\n{'FAILED' if failures else 'all green'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)
