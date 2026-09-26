"""Runs every test_* function in a standalone test script and exits non-zero on failure.

Importing this module also puts poller/ on sys.path, so tests import modules directly.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(scope: dict) -> None:
    failed = 0
    for name, fn in list(scope.items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception:
                failed += 1
                print(f"FAIL  {name}")
                traceback.print_exc()
    print("all passed" if not failed else f"{failed} failed")
    sys.exit(1 if failed else 0)
