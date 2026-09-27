"""Read-only JSON API for the Mac app. Every request needs the bearer token; nothing here
can change state, so a stolen token exposes usage numbers and nothing else."""
import hmac
import json
import logging
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from config import Config
from levels import DAY, days_to_limit, display_level, pressure, resets_at, slope_per_day
from store import Store

log = logging.getLogger("burnrate")
MAX_DAYS = 90


def build_status(cfg: Config, store: Store, registry: dict, now: int) -> dict:
    latest, runs = store.latest(), store.runs()
    rows = []
    for name in cfg.services:
        mod = registry[name]
        for metric, m in mod.METRICS.items():
            limit = cfg.limits[metric]
            ts, value = latest.get(metric, (None, None))
            reset = resets_at(m.resets, now)
            row = {"metric": metric, "service": mod.SERVICE, "label": m.label, "unit": m.unit,
                   "dir": m.dir, "value": value, "limit": limit, "pressure": None, "level": None,
                   "at_limit": m.at_limit, "resets_at": reset, "updated": ts,
                   "stale": ts is None or now - ts > 2 * cfg.interval_s, "support": m.support,
                   "slope_per_day": None, "days_to_limit": None}
            if value is not None:
                p = pressure(m.dir, value, limit)
                slope = slope_per_day(store.history(metric, now - 7 * DAY))
                row.update(pressure=round(p, 4), level=display_level(p, cfg.thresholds),
                           slope_per_day=slope,
                           days_to_limit=days_to_limit(m.dir, value, limit, slope, now, reset))
            rows.append(row)
    polled = max((r["updated"] for r in rows if r["updated"] is not None), default=None)
    collectors = {registry[n].SERVICE: {"last_ok": r["last_ok"], "failing": r["fails"] > 0,
                                        "error": r["last_err"]}
                  for n, r in runs.items() if n in cfg.services}
    return {"polled_at": polled, "next_poll_at": polled + cfg.interval_s if polled else None,
            "interval_s": cfg.interval_s, "collectors": collectors, "metrics": rows}


def make_server(cfg: Config, store: Store, registry: dict, token: str,
                clock: Callable[[], float] = time.time) -> ThreadingHTTPServer:
    if len(token) < 32:
        raise ValueError("BURNRATE_TOKEN must be at least 32 characters")
    expected = f"Bearer {token}".encode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "burnrate"
        sys_version = ""
        timeout = 10  # a stalled client cannot hold a thread forever

        def do_GET(self) -> None:
            given = self.headers.get("Authorization", "").encode("utf-8", "replace")
            if not hmac.compare_digest(given, expected):  # constant time: no timing hints
                return self._send(401, {"error": "unauthorized"})
            url = urlsplit(self.path)
            now = int(clock())
            if url.path == "/api/status":
                return self._send(200, build_status(cfg, store, registry, now))
            if url.path == "/api/history":
                q = parse_qs(url.query)
                metric, days = q.get("metric", [""])[0], q.get("days", ["7"])[0]
                if metric not in cfg.limits:
                    return self._send(400, {"error": "unknown metric"})
                if (not (days.isascii() and days.isdigit() and len(days) <= 2)
                        or not 1 <= int(days) <= MAX_DAYS):
                    return self._send(400, {"error": f"days must be 1 to {MAX_DAYS}"})
                points = store.history(metric, now - int(days) * DAY)
                return self._send(200, {"metric": metric, "points": [list(p) for p in points]})
            self._send(404, {"error": "not found"})

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: object) -> None:
            log.debug("api %s", fmt % args)  # method, path and status only; never headers

    server = ThreadingHTTPServer((cfg.host, cfg.port), Handler)
    server.daemon_threads = True
    return server
