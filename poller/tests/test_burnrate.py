import _run
import io
import logging
import os
import socket
import tempfile
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import fakes
from burnrate import main, once, run
from fetch import FetchError
from metric import Metric
from store import Store

USED = Metric("Used", "GB", "max", "it stops")

# Built from parts so this literal does not look like a real Discord webhook to a secret scanner.
_FAKE_WEBHOOK = "https://discord.com/api/webhooks/" + "1/abc"


def _write_config(tmp_path: Path, db_path: Path | str) -> str:
    path = tmp_path / "config.toml"
    path.write_text(
        '[poller]\n'
        'listen = "127.0.0.1:8787"\n'
        f'db_path = "{db_path}"\n\n'
        '[clerk]\n'
        '[clerk.limits]\n'
        'users = 50000\n'
    )
    return str(path)


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
    cfg = fakes.config(reg, {"svc.used": 10}, env={"BURNRATE_TOKEN": "t" * 40})
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    assert run(cfg, reg, stop, send=lambda m: True) == 0
    assert "svc.used" in Store(cfg.db_path).latest(cfg.limits)


def test_polling_continues_when_the_api_cannot_bind():
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, lambda env, s: {"svc.used": 1.0})}
    cfg = fakes.config(reg, {"svc.used": 10}, env={"BURNRATE_TOKEN": "t" * 40})
    cfg.interval_s = 0
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    cfg.port = blocker.getsockname()[1]
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger("burnrate").addHandler(handler)
    stop = threading.Event()
    threading.Timer(2.5, stop.set).start()
    try:
        assert run(cfg, reg, stop, send=lambda m: True) == 0
    finally:
        logging.getLogger("burnrate").removeHandler(handler)
        blocker.close()
    assert "svc.used" in Store(cfg.db_path).latest(cfg.limits)
    assert buf.getvalue().count("API not listening") == 1


def test_api_starts_later_when_the_port_frees():
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, lambda env, s: {"svc.used": 1.0})}
    cfg = fakes.config(reg, {"svc.used": 10}, env={"BURNRATE_TOKEN": "t" * 40})
    cfg.interval_s = 0
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    cfg.port = blocker.getsockname()[1]
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    burnrate_log = logging.getLogger("burnrate")
    saved_level = burnrate_log.level
    burnrate_log.addHandler(handler)
    burnrate_log.setLevel(logging.INFO)  # "API on" logs at INFO; root defaults to WARNING here
    ready: dict = {}
    stop = threading.Event()
    threading.Timer(1.2, blocker.close).start()
    threading.Timer(2.8, stop.set).start()
    try:
        assert run(cfg, reg, stop, send=lambda m: True,
                  on_ready=lambda port: ready.update(port=port)) == 0
    finally:
        burnrate_log.removeHandler(handler)
        burnrate_log.setLevel(saved_level)
    assert "port" in ready
    assert "API on" in buf.getvalue()


def test_a_crashing_cycle_does_not_kill_the_loop():
    import burnrate

    calls = []

    def crash(*args: object) -> None:
        calls.append(args)
        raise RuntimeError("disk full")
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, lambda env, s: {"svc.used": 1.0})}
    cfg = fakes.config(reg, {"svc.used": 10}, env={"BURNRATE_TOKEN": "t" * 40})
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


def test_run_serves_the_api_while_polling():
    import json
    import urllib.request
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, lambda env, s: {"svc.used": 1.0})}
    cfg = fakes.config(reg, {"svc.used": 10}, env={"BURNRATE_TOKEN": "t" * 40})
    stop, ready = threading.Event(), {}
    t = threading.Thread(target=lambda: run(cfg, reg, stop, send=lambda m: True,
                                            on_ready=lambda port: ready.update(port=port)))
    t.start()
    try:
        for _ in range(50):
            if "port" in ready and "svc.used" in Store(cfg.db_path).latest(cfg.limits):
                break
            threading.Event().wait(0.1)
        req = urllib.request.Request(f"http://127.0.0.1:{ready['port']}/api/status",
                                     headers={"Authorization": "Bearer " + "t" * 40})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert json.loads(r.read())["metrics"][0]["value"] == 1.0
    finally:
        stop.set()
        t.join(5)
    assert not t.is_alive()


def test_check_config_ok():
    tmp = Path(tempfile.mkdtemp())
    path = _write_config(tmp, tmp / "burnrate.db")
    saved_handlers, saved_level = logging.root.handlers[:], logging.root.level
    out = io.StringIO()
    try:
        with patch.dict(os.environ, {
            "CLERK_SECRET_KEY": "x",
            "BURNRATE_TOKEN": "t" * 40,
            "DISCORD_WEBHOOK_URL": _FAKE_WEBHOOK,
        }, clear=False):
            with redirect_stdout(out):
                assert main(["--check-config", "--config", path]) == 0
    finally:
        logging.root.handlers[:] = saved_handlers
        logging.root.setLevel(saved_level)
    assert "Config OK." in out.getvalue()


def test_check_config_refuses_a_short_token():
    tmp = Path(tempfile.mkdtemp())
    path = _write_config(tmp, tmp / "burnrate.db")
    saved_handlers, saved_level = logging.root.handlers[:], logging.root.level
    err = io.StringIO()
    try:
        with patch.dict(os.environ, {
            "CLERK_SECRET_KEY": "x",
            "BURNRATE_TOKEN": "short",
            "DISCORD_WEBHOOK_URL": _FAKE_WEBHOOK,
        }, clear=False):
            with redirect_stderr(err):
                assert main(["--check-config", "--config", path]) == 2
    finally:
        logging.root.handlers[:] = saved_handlers
        logging.root.setLevel(saved_level)


def test_check_config_refuses_an_unwritable_db():
    tmp = Path(tempfile.mkdtemp())
    path = _write_config(tmp, tmp / "missing-dir" / "burnrate.db")
    saved_handlers, saved_level = logging.root.handlers[:], logging.root.level
    err = io.StringIO()
    try:
        with patch.dict(os.environ, {
            "CLERK_SECRET_KEY": "x",
            "BURNRATE_TOKEN": "t" * 40,
            "DISCORD_WEBHOOK_URL": _FAKE_WEBHOOK,
        }, clear=False):
            with redirect_stderr(err):
                assert main(["--check-config", "--config", path]) == 1
    finally:
        logging.root.handlers[:] = saved_handlers
        logging.root.setLevel(saved_level)
    assert "cannot open the database" in err.getvalue()


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
