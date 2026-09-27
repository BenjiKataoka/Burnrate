#!/usr/bin/env bash
# Ship the committed poller to the server, install the locked dependencies, check the
# config against the real services, and restart. Run from your laptop.
#
#   deploy/push.sh ubuntu@<server>
#
# push.sh rolls back automatically if the new release fails to start. To roll back by hand
# (also re-syncing the previous release's own lock, since the venv is shared):
#   sudo rm -rf /opt/burnrate/poller.bad \
#     && sudo mv /opt/burnrate/poller /opt/burnrate/poller.bad && sudo mv /opt/burnrate/poller.prev /opt/burnrate/poller \
#     && sudo env UV_CACHE_DIR=/opt/burnrate/.cache/uv uv pip sync --require-hashes \
#          --python /opt/burnrate/venv/bin/python /opt/burnrate/poller/requirements.lock \
#     && sudo systemctl restart burnrate
set -euo pipefail

HOST="${1:?usage: deploy/push.sh ubuntu@<server>}"
cd "$(git rev-parse --show-toplevel)"
if [ -n "$(git status --porcelain -- poller)" ]; then
  echo "poller/ has uncommitted changes. Commit them first, so the server runs what you tested."
  exit 1
fi
REV="$(git rev-parse --short HEAD)"
echo "==> Shipping poller at $REV to $HOST"

ssh "$HOST" "sudo rm -rf /opt/burnrate/poller.new && sudo mkdir -p /opt/burnrate/poller.new"
git archive --format=tar HEAD poller | ssh "$HOST" "sudo tar -x -C /opt/burnrate/poller.new --strip-components=1"

ssh "$HOST" "sudo REV=$REV bash -s" <<'REMOTE'
set -euo pipefail
APP=/opt/burnrate
cd "$APP"
echo "$REV" > poller.new/REVISION
rm -rf poller.new/tests
# The release tree is owned by root and world-readable; only $APP/data is writable by the
# service user (defense in depth: a compromised poller cannot touch its own code).
chown -R root:root poller.new
chmod -R a+rX poller.new

echo "==> Dependencies (exact, hashed lock)"
if cmp -s poller.new/requirements.lock poller/requirements.lock; then
  echo "Dependencies unchanged."
else
  env UV_CACHE_DIR="$APP/.cache/uv" uv pip sync --require-hashes \
    --python "$APP/venv/bin/python" poller.new/requirements.lock </dev/null
fi

echo "==> Checking config (deploy check, no network calls)"
# burnrate.py reads /opt/burnrate/.env itself, so no secret ever appears on a command line.
(cd poller.new && sudo -u burnrate "$APP/venv/bin/python" burnrate.py --check-config --config "$APP/config.toml" </dev/null) \
  || { echo "Config check failed; the old release is still in place, but the venv now has the new lock. Run the rollback sync from the header comment before restarting it."; exit 1; }

echo "==> Checking every service before the swap"
set +e
(cd poller.new && sudo -u burnrate "$APP/venv/bin/python" burnrate.py --once --config "$APP/config.toml" </dev/null)
code=$?
set -e
case "$code" in
  0) ;;
  1) echo "A collector failed (see above). Deploying anyway; it is retried every poll." ;;
  *) echo "Check failed ($code); the old release is still in place, but the venv now has the new lock. Run the rollback sync from the header comment before restarting it."; exit 1 ;;
esac

# Since item 1, polling starts even when the API cannot bind (Tailscale down), so "API on"
# can legitimately be missing; either line proves the process is up and polling.
wait_for_start() {
  since="$1"
  for _ in $(seq 1 20); do
    sleep 1
    if systemctl is-active --quiet burnrate \
        && journalctl -u burnrate --since "@$since" --no-pager -q | grep -qE "API on|API not listening"; then
      return 0
    fi
  done
  return 1
}

echo "==> Swap and restart"
rm -rf poller.prev
[ -d poller ] && mv poller poller.prev
mv poller.new poller
systemctl daemon-reload
START=$(date +%s)
systemctl restart burnrate

if wait_for_start "$START"; then
  echo "Burnrate $REV is running."
else
  echo "Burnrate $REV did not start; rolling back."
  rm -rf poller.bad
  mv poller poller.bad
  if [ -d poller.prev ]; then
    mv poller.prev poller
    env UV_CACHE_DIR="$APP/.cache/uv" uv pip sync --require-hashes \
      --python "$APP/venv/bin/python" poller/requirements.lock </dev/null \
      || echo "Warning: could not re-sync the previous lock; restarting anyway."
    ROLLBACK_START=$(date +%s)
    systemctl restart burnrate
    if wait_for_start "$ROLLBACK_START"; then
      echo "Rolled back to the previous release."
    else
      echo "Rollback did not start either; see sudo journalctl -u burnrate -n 60."
    fi
  else
    echo "No previous release to roll back to. Logs: sudo journalctl -u burnrate -n 60"
  fi
  exit 1
fi
REMOTE

echo "Done. Check it from your Mac with: deploy/smoke.sh http://<tailscale-ip>:8787 <public-ip>"
