#!/usr/bin/env bash
# Ship the COMMITTED poller to the server, install the locked dependencies, check the
# config against the real services, and restart. Run from your laptop.
#
#   deploy/push.sh ubuntu@<server>
#
# Rollback, on the server:
#   sudo mv /opt/burnrate/poller /opt/burnrate/poller.bad && sudo mv /opt/burnrate/poller.prev /opt/burnrate/poller && sudo systemctl restart burnrate
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
chown -R burnrate:burnrate poller.new

echo "==> Dependencies (exact, hashed lock)"
sudo -u burnrate env UV_CACHE_DIR="$APP/.cache/uv" uv pip sync --require-hashes \
  --python "$APP/venv/bin/python" poller.new/requirements.lock

echo "==> Checking config and every service before the swap"
set +e
# burnrate.py reads /opt/burnrate/.env itself, so no secret ever appears on a command line.
(cd poller.new && sudo -u burnrate "$APP/venv/bin/python" burnrate.py --once --config "$APP/config.toml")
code=$?
set -e
if [ "$code" = 2 ]; then echo "Config error; the old release keeps running."; exit 1; fi
[ "$code" = 1 ] && echo "A collector failed (see above). Deploying anyway; it is retried every poll."

echo "==> Swap and restart"
rm -rf poller.prev
[ -d poller ] && mv poller poller.prev
mv poller.new poller
systemctl daemon-reload
systemctl restart burnrate
sleep 3
systemctl is-active --quiet burnrate && echo "Burnrate $REV is running." \
  || { echo "Burnrate did not start. Logs: sudo journalctl -u burnrate -n 60"; exit 1; }
REMOTE

echo "Done. Check it from your Mac with: deploy/smoke.sh http://<tailscale-ip>:8787 <public-ip>"
