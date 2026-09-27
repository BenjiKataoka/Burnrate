#!/usr/bin/env bash
# One-time setup of Burnrate on the Oracle VM that already runs Fantas.ai.
# Safe to re-run: every step checks before it changes anything. Opens no ports.
#
# On the server:  sudo bash setup.sh
set -euo pipefail

APP=/opt/burnrate
HERE="$(cd "$(dirname "$0")" && pwd)"
TEMPLATES="$(cd "$HERE/.." && pwd)"   # .env.example and config.example.toml sit beside deploy/
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }

echo "==> uv (installs the exact Python the lock was built for)"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

echo "==> Tailscale (the API listens only on this private network)"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh

echo "==> Service user and directories"
id burnrate >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin burnrate
mkdir -p "$APP/data"
# Only data is writable by the service; everything else in $APP is owned by root.
chown root:burnrate "$APP"
chmod 750 "$APP"
chown burnrate:burnrate "$APP/data"
chmod 750 "$APP/data"
cd "$APP"

echo "==> Python 3.14 and the virtualenv (installed by root, readable by everyone)"
env UV_PYTHON_INSTALL_DIR="$APP/.python" UV_CACHE_DIR="$APP/.cache/uv" uv python install 3.14 </dev/null
[ -x "$APP/venv/bin/python" ] || env UV_PYTHON_INSTALL_DIR="$APP/.python" UV_CACHE_DIR="$APP/.cache/uv" \
  uv venv --python 3.14 "$APP/venv" </dev/null
chmod -R a+rX "$APP/.python" "$APP/venv"

echo "==> Environment and config (created once, never overwritten)"
for pair in ".env.example:.env" "config.example.toml:config.toml"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if [ ! -f "$APP/$dst" ]; then cp "$TEMPLATES/$src" "$APP/$dst"; CREATED=1; fi
  chown root:burnrate "$APP/$dst"
  chmod 640 "$APP/$dst"
done

echo "==> systemd unit"
cp "$HERE/burnrate.service" /etc/systemd/system/burnrate.service
systemctl daemon-reload
systemctl enable burnrate   # started by push.sh once code and .env are in place

echo
echo "Setup done."
[ "${CREATED:-0}" = 1 ] && echo "Still to do: sudo nano $APP/.env and $APP/config.toml (see deploy/README.md)."
tailscale status >/dev/null 2>&1 || echo "Still to do: sudo tailscale up, then put this machine's Tailscale IP in config.toml listen."
echo "Then from your laptop: deploy/push.sh ubuntu@<server>"
