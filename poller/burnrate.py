"""Burnrate poller.

  python3 burnrate.py               poll forever, store results, send alerts
  python3 burnrate.py --once        poll every service once and print the values (setup check)
  python3 burnrate.py --test-alert  send one message to the Discord webhook (setup check)
  python3 burnrate.py --check-config  validate config.toml, .env and the database path (deploy check)
"""
import argparse
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import alerts
import api
from collectors import REGISTRY
from config import Config, ConfigError, load_config, read_env_file
from poll import collect_all, poll_once
from store import Store

HERE = Path(__file__).resolve().parent
log = logging.getLogger("burnrate")


def once(cfg: Config, registry: dict) -> int:
    failed = False
    for name, result in collect_all(cfg, registry).items():
        service = registry[name].SERVICE
        if isinstance(result, str):
            failed = True
            print(f"{service:<10} FAILED  {result}")
            continue
        for metric, value in result.items():
            print(f"{service:<10} {metric:<24} {value:>12,.4g}   limit {cfg.limits[metric]:,g}")
    return 1 if failed else 0


def run(cfg: Config, registry: dict, stop: threading.Event | None = None,
        send: Callable[[dict], bool] | None = None,
        on_ready: Callable[[int], None] | None = None) -> int:
    stop = stop or threading.Event()
    send = send or alerts.discord_sender(cfg.env["DISCORD_WEBHOOK_URL"])
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        store = Store(cfg.db_path)
    except sqlite3.Error as e:
        print(f"burnrate: cannot open the database at {cfg.db_path}: {e}", file=sys.stderr)
        return 1

    server = None
    warned = False  # log "API not listening" once per failure streak, not every retry

    def bind() -> None:
        nonlocal server, warned
        try:
            server = api.make_server(cfg, store, registry, cfg.env.get("BURNRATE_TOKEN", ""))
        except OSError as e:
            # Usually Tailscale is not up yet at boot, or tailscaled is restarting; polling
            # does not depend on this, so keep going and retry the bind every cycle.
            if not warned:
                log.warning("API not listening on %s:%d yet (%s); polling and alerts continue",
                           cfg.host, cfg.port, e)
                warned = True
            return
        warned = False
        threading.Thread(target=server.serve_forever, name="api", daemon=True).start()
        if on_ready:
            on_ready(server.server_address[1])
        log.info("API on %s:%d", cfg.host, server.server_address[1])

    try:
        bind()
    except ValueError as e:  # a short token is a config error, not a transient one: fatal
        print(f"burnrate: {e}", file=sys.stderr)
        return 1

    log.info("polling %s every %d min", ", ".join(cfg.services), cfg.interval_s // 60)
    while not stop.is_set():
        started = time.monotonic()
        if server is None:
            bind()
        try:
            poll_once(cfg, store, registry, int(time.time()), send)
        except Exception:  # a bad cycle (disk full, locked database) must not end the loop
            log.exception("poll cycle failed; trying again next interval")
        stop.wait(max(1.0, cfg.interval_s - (time.monotonic() - started)))
    if server is not None:
        server.shutdown()
        server.server_close()
    log.info("stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Burnrate poller")
    ap.add_argument("--config", default=str(HERE / "config.toml"))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="poll once, print, save nothing")
    mode.add_argument("--test-alert", action="store_true", help="send one Discord message")
    mode.add_argument("--check-config", action="store_true",
                       help="validate config and the database path, then exit")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = {**read_env_file(HERE.parent / ".env"), **os.environ}
    try:
        cfg = load_config(Path(args.config), REGISTRY, env, serving=not args.once)
    except ConfigError as e:
        print(f"burnrate: {e}", file=sys.stderr)
        return 2
    if args.check_config:
        try:
            Store(cfg.db_path)
        except sqlite3.Error as e:
            print(f"burnrate: cannot open the database at {cfg.db_path}: {e}", file=sys.stderr)
            return 1
        print("Config OK.")
        return 0
    if args.once:
        return once(cfg, REGISTRY)
    if args.test_alert:
        ok = alerts.discord_sender(cfg.env["DISCORD_WEBHOOK_URL"])(alerts.connected())
        print("Sent. Check the Discord channel." if ok else
              "Discord refused the message; see the log line above.")
        return 0 if ok else 1
    return run(cfg, REGISTRY)


if __name__ == "__main__":
    sys.exit(main())
