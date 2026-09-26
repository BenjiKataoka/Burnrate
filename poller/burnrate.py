"""Burnrate poller.

  python3 burnrate.py            poll forever and store the results
  python3 burnrate.py --once     poll every service once and print the values (setup check)
"""
import argparse
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from pathlib import Path

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


def run(cfg: Config, registry: dict, stop: threading.Event | None = None) -> int:
    stop = stop or threading.Event()
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        store = Store(cfg.db_path)
    except sqlite3.Error as e:
        print(f"burnrate: cannot open the database at {cfg.db_path}: {e}", file=sys.stderr)
        return 1
    log.info("polling %s every %d min", ", ".join(cfg.services), cfg.interval_s // 60)
    while not stop.is_set():
        started = time.time()
        try:
            poll_once(cfg, store, registry, int(started))
        except Exception as e:  # a bad cycle (disk full, locked database) must not end the loop
            # printed directly (not just logged): logging's handler is bound once by
            # basicConfig, so a later reconfiguration or redirected stderr would miss it
            print(f"burnrate: poll cycle failed; trying again next interval: {e}",
                 file=sys.stderr)
            log.exception("poll cycle failed; trying again next interval")
        stop.wait(max(1.0, cfg.interval_s - (time.time() - started)))
    log.info("stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Burnrate poller")
    ap.add_argument("--config", default=str(HERE / "config.toml"))
    ap.add_argument("--once", action="store_true", help="poll once, print, save nothing")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = {**read_env_file(HERE.parent / ".env"), **os.environ}
    try:
        cfg = load_config(Path(args.config), REGISTRY, env, serving=False)
    except ConfigError as e:
        print(f"burnrate: {e}", file=sys.stderr)
        return 2
    return once(cfg, REGISTRY) if args.once else run(cfg, REGISTRY)


if __name__ == "__main__":
    sys.exit(main())
