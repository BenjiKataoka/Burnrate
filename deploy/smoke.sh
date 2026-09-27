#!/usr/bin/env bash
# Checks the deployed API from your Mac over Tailscale, and that it is NOT public.
#   read -s BURNRATE_TOKEN && export BURNRATE_TOKEN
#   deploy/smoke.sh http://<tailscale-ip>:8787 [public-ip]
set -uo pipefail

BASE="${1:?usage: deploy/smoke.sh http://<tailscale-ip>:8787 [public-ip]}"
BASE="${BASE%/}"
PUBLIC="${2:-}"
: "${BURNRATE_TOKEN:?export BURNRATE_TOKEN first (read -s keeps it out of your history)}"
fail=0
check() { if [ "$2" = "$3" ]; then echo "  ok    $1"; else echo "  FAIL  $1 (expected $3, got $2)"; fail=1; fi; }
code() { curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }

echo "Checking $BASE"
check "no token is refused"          "$(code "$BASE/api/status")" 401
check "a wrong token is refused"     "$(code -H 'Authorization: Bearer wrong' "$BASE/api/status")" 401
check "the real token works"         "$(code -H "Authorization: Bearer $BURNRATE_TOKEN" "$BASE/api/status")" 200
check "unknown metric is refused"    "$(code -H "Authorization: Bearer $BURNRATE_TOKEN" "$BASE/api/history?metric=nope&days=7")" 400

age="$(curl -sS --max-time 10 -H "Authorization: Bearer $BURNRATE_TOKEN" "$BASE/api/status" \
  | python3 -c 'import json,sys,time; s=json.load(sys.stdin); print(int(time.time()-(s["polled_at"] or 0)))')"
if [ "${age:-99999}" -lt 1200 ]; then echo "  ok    last poll ${age}s ago"; else echo "  FAIL  last poll ${age}s ago (over 20 min)"; fail=1; fi

if [ -n "$PUBLIC" ]; then
  port="${BASE##*:}"
  if curl -sS -o /dev/null --max-time 5 "http://$PUBLIC:$port/api/status" 2>/dev/null; then
    echo "  FAIL  the API answers on the public IP"; fail=1
  else
    echo "  ok    not reachable on the public IP"
  fi
fi

[ "$fail" = 0 ] && echo "All checks passed." || echo "Some checks failed."
exit "$fail"
