#!/bin/sh
# Runs every test script from poller/, stopping at the first file that fails.
cd "$(dirname "$0")/.." || exit 1
for f in tests/test_*.py; do
  echo "== $f"
  python3 "$f" || exit 1
done
