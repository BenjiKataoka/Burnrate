#!/usr/bin/env bash
# Ship the committed poller to the server, install the locked dependencies, check the
# config against the real services, and restart. Run from your laptop.
#
#   deploy/push.sh ubuntu@<server>
#
# push.sh rolls back automatically if the new release fails to start. To roll back by hand
# (also re-syncing the previous release's own lock, since the venv is shared):
#   sudo mv /opt/burnrate/poller /opt/burnrate/poller.bad && sudo mv /opt/burnrate/poller.prev /opt/burnrate/poller \
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
env UV_CACHE_DIR="$APP/.cache/uv" uv pip sync --require-hashes \
  --python "$APP/venv/bin/python" poller.new/requirements.lock </dev/null

echo "==> Checking config (deploy check, no network calls)"
# burnrate.py reads /opt/burnrate/.env itself, so no secret ever appears on a command line.
(cd poller.new && sudo -u burnrate "$APP/venv/bin/python" burnrate.py --check-config --config "$APP/config.toml" </dev/null) \
  || { echo "Config check failed; the old release keeps running."; exit 1; }

echo "==> Checking every service before the swap"
set +e
(cd poller.new && sudo -u burnrate "$APP/venv/bin/python" burnrate.py --once --config "$APP/config.toml" </dev/null)
code=$?
set -e
case "$code" in
  0) ;;
  1) echo "A collector failed (see above). Deploying anyway; it is retried every poll." ;;
  *) echo "Check failed ($code); the old release keeps running."; exit 1 ;;
esac

echo "==> Swap and restart"
rm -rf poller.prev
[ -d poller ] && mv poller poller.prev
mv poller.new poller
systemctl daemon-reload
START=$(date +%s)
systemctl restart burnrate

started=0
for i in $(seq 1 20); do
  sleep 1
  if systemctl is-active --quiet burnrate \
      && journalctl -u burnrate --since "@$START" --no-pager -q | grep -q "API on"; then
    started=1
    break
  fi
done

if [ "$started" = 1 ]; then
  echo "Burnrate $REV is running."
else
  echo "Burnrate $REV did not start; rolling back."
  mv poller poller.bad
  if [ -d poller.prev ]; then
    mv poller.prev poller
    env UV_CACHE_DIR="$APP/.cache/uv" uv pip sync --require-hashes \
      --python "$APP/venv/bin/python" poller/requirements.lock </dev/null
    systemctl restart burnrate
    echo "Rolled back. Logs: sudo journalctl -u burnrate -n 60"
  else
    echo "No previous release to roll back to. Logs: sudo journalctl -u burnrate -n 60"
  fi
  exit 1
fi
REMOTE

echo "Done. Check it from your Mac with: deploy/smoke.sh http://<tailscale-ip>:8787 <public-ip>"
