import _run
import sqlite3
import tempfile
from pathlib import Path

from store import Store


def fresh() -> Store:
    return Store(str(Path(tempfile.mkdtemp()) / "t.db"))


def test_latest_is_the_newest_value_per_metric():
    s = fresh()
    s.add_snapshots(100, {"a": 1.0, "b": 5.0})
    s.add_snapshots(200, {"a": 2.0})
    assert s.latest(["a", "b"]) == {"a": (200, 2.0), "b": (100, 5.0)}
    assert s.latest(["a"]) == {"a": (200, 2.0)}
    assert s.latest(["missing"]) == {}


def test_history_is_filtered_and_ordered():
    s = fresh()
    for ts in (300, 100, 200):
        s.add_snapshots(ts, {"a": float(ts)})
    assert s.history("a", 150) == [(200, 200.0), (300, 300.0)]
    assert s.history("missing", 0) == []


def test_same_timestamp_replaces():
    s = fresh()
    s.add_snapshots(100, {"a": 1.0})
    s.add_snapshots(100, {"a": 9.0})
    assert s.history("a", 0) == [(100, 9.0)]


def test_run_counting():
    s = fresh()
    assert s.run_failed("neon", 1, "HTTP 500") == 1
    assert s.run_failed("neon", 2, "HTTP 500") == 2
    assert s.runs()["neon"] == {"last_ok": None, "last_err": "HTTP 500", "fails": 2}
    s.run_ok("neon", 3)
    assert s.runs()["neon"] == {"last_ok": 3, "last_err": None, "fails": 0}


def test_levels_default_to_ok_and_persist_across_reopen():
    path = str(Path(tempfile.mkdtemp()) / "t.db")
    s = Store(path)
    assert s.level("neon.storage_gb") == "ok"
    s.set_level("neon.storage_gb", "warn", 10)
    assert Store(path).level("neon.storage_gb") == "warn"


def test_wal_mode_so_reads_never_block_on_the_writer():
    path = str(Path(tempfile.mkdtemp()) / "t.db")
    Store(path)
    assert sqlite3.connect(path).execute("PRAGMA journal_mode").fetchone()[0] == "wal"


if __name__ == "__main__":
    _run.run(globals())
