import _run
import io
import logging
import tempfile
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import fakes
from burnrate import main, once, run
from fetch import FetchError
from metric import Metric
from store import Store

USED = Metric("Used", "GB", "max", "it stops")


def test_once_prints_values_and_saves_nothing():
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, lambda env, s: {"svc.used": 3.5})}
    cfg = fakes.config(reg, {"svc.used": 10})
    out = io.StringIO()
    with redirect_stdout(out):
        assert once(cfg, reg) == 0
    assert "svc.used" in out.getvalue() and "3.5" in out.getvalue()
    assert not Path(cfg.db_path).exists()


def test_once_exits_1_when_a_collector_fails():
    def boom(env: dict, s: dict) -> dict:
        raise FetchError("HTTP 401", 401)
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, boom)}
    out = io.StringIO()
    with redirect_stdout(out):
        assert once(fakes.config(reg, {"svc.used": 10}), reg) == 1
    assert "FAILED" in out.getvalue() and "HTTP 401" in out.getvalue()


def test_main_exits_2_on_a_config_error():
    saved_handlers, saved_level = logging.root.handlers[:], logging.root.level
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            assert main(["--once", "--config", "/nonexistent/config.toml"]) == 2
    finally:
        logging.root.handlers[:] = saved_handlers
        logging.root.setLevel(saved_level)
    assert "not found" in err.getvalue()


def test_run_polls_then_stops_cleanly():
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, lambda env, s: {"svc.used": 1.0})}
    cfg = fakes.config(reg, {"svc.used": 10})
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    assert run(cfg, reg, stop, send=lambda m: True) == 0
    assert "svc.used" in Store(cfg.db_path).latest()


def test_a_crashing_cycle_does_not_kill_the_loop():
    import burnrate

    calls = []

    def crash(*args: object) -> None:
        calls.append(args)
        raise RuntimeError("disk full")
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, lambda env, s: {"svc.used": 1.0})}
    cfg = fakes.config(reg, {"svc.used": 10})
    cfg.interval_s = 0
    original, burnrate.poll_once = burnrate.poll_once, crash
    stop = threading.Event()
    threading.Timer(2.5, stop.set).start()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger("burnrate").addHandler(handler)
    try:
        assert run(cfg, reg, stop, send=lambda m: True) == 0
    finally:
        burnrate.poll_once = original
        logging.getLogger("burnrate").removeHandler(handler)
    assert "poll cycle failed" in buf.getvalue() and "disk full" in buf.getvalue()
    assert len(calls) >= 2


def test_unopenable_database_exits_1():
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, lambda env, s: {"svc.used": 1.0})}
    cfg = fakes.config(reg, {"svc.used": 10})
    cfg.db_path = str(Path(tempfile.mkdtemp()) / "missing-dir" / "t.db")
    err = io.StringIO()
    with redirect_stderr(err):
        assert run(cfg, reg, threading.Event(), send=lambda m: True) == 1
    assert "cannot open the database" in err.getvalue()


if __name__ == "__main__":
    _run.run(globals())
