"""SQLite storage. One short connection per call, so the poll loop and the API threads
never share a connection; WAL lets readers run while the loop writes."""
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  ts INTEGER NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (metric, ts));
CREATE TABLE IF NOT EXISTS collector_runs (
  service TEXT PRIMARY KEY, last_ok INTEGER, last_err TEXT, fails INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS alert_state (
  name TEXT PRIMARY KEY, level TEXT NOT NULL, since INTEGER NOT NULL);
"""


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        c = sqlite3.connect(path)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
        finally:
            c.close()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=10)
        try:
            with c:
                yield c
        finally:
            c.close()

    def add_snapshots(self, ts: int, values: dict[str, float]) -> None:
        with self._db() as c:
            c.executemany("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?)",
                          [(ts, metric, value) for metric, value in values.items()])

    def latest(self, metrics: Iterable[str]) -> dict[str, tuple[int, float]]:
        """One indexed lookup per metric (metric, ts) is the primary key, so this hits the
        index; the old correlated subquery scanned the whole table once per row."""
        out: dict[str, tuple[int, float]] = {}
        with self._db() as c:
            for metric in metrics:
                row = c.execute("SELECT ts, value FROM snapshots WHERE metric = ? "
                                "ORDER BY ts DESC LIMIT 1", (metric,)).fetchone()
                if row is not None:
                    out[metric] = tuple(row)
        return out

    def history(self, metric: str, since: int) -> list[tuple[int, float]]:
        with self._db() as c:
            return c.execute("SELECT ts, value FROM snapshots WHERE metric = ? AND ts >= ? "
                             "ORDER BY ts", (metric, since)).fetchall()

    def run_ok(self, service: str, ts: int) -> None:
        with self._db() as c:
            c.execute("INSERT INTO collector_runs (service, last_ok, last_err, fails) "
                      "VALUES (?, ?, NULL, 0) ON CONFLICT(service) DO UPDATE SET "
                      "last_ok = excluded.last_ok, last_err = NULL, fails = 0", (service, ts))

    def run_failed(self, service: str, ts: int, err: str) -> int:
        with self._db() as c:
            c.execute("INSERT INTO collector_runs (service, last_ok, last_err, fails) "
                      "VALUES (?, NULL, ?, 1) ON CONFLICT(service) DO UPDATE SET "
                      "last_err = excluded.last_err, fails = fails + 1", (service, err))
            return c.execute("SELECT fails FROM collector_runs WHERE service = ?",
                             (service,)).fetchone()[0]

    def runs(self) -> dict[str, dict]:
        with self._db() as c:
            rows = c.execute("SELECT service, last_ok, last_err, fails FROM collector_runs").fetchall()
        return {s: {"last_ok": ok, "last_err": err, "fails": fails} for s, ok, err, fails in rows}

    def level(self, name: str) -> str:
        with self._db() as c:
            row = c.execute("SELECT level FROM alert_state WHERE name = ?", (name,)).fetchone()
        return row[0] if row else "ok"

    def set_level(self, name: str, level: str, ts: int) -> None:
        with self._db() as c:
            c.execute("INSERT INTO alert_state VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                      "level = excluded.level, since = excluded.since", (name, level, ts))
