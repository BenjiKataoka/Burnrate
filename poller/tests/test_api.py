import _run
import json
import threading
import urllib.error
import urllib.request

import fakes
from api import build_status, make_server
from metric import Metric
from poll import poll_once

TOKEN = "a" * 43
USED = Metric("Used", "GB", "max", "it stops", "monthly")
PART = Metric("Part", "%", "min", "", "rolling", support=True)
NOW = 1_790_000_000


def world(value: float = 72.0):
    reg = {"svc": fakes.service("Svc", {"svc.used": USED, "svc.part": PART},
                                lambda env, s: {"svc.used": value, "svc.part": 30.0})}
    cfg = fakes.config(reg, {"svc.used": 100, "svc.part": 20})
    st = fakes.store()
    return reg, cfg, st


def serve(cfg, st, reg, clock=lambda: NOW):
    srv = make_server(cfg, st, reg, TOKEN, clock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def get(url: str, token: str | None = TOKEN, method: str = "GET") -> tuple[int, dict | None]:
    req = urllib.request.Request(url, method=method)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        return e.code, json.loads(body) if body.startswith(b"{") else None


def test_status_shape():
    reg, cfg, st = world()
    poll_once(cfg, st, reg, NOW - 60, lambda m: True)
    s = build_status(cfg, st, reg, NOW)
    assert s["polled_at"] == NOW - 60 and s["next_poll_at"] == NOW - 60 + 900
    assert s["collectors"] == {"Svc": {"last_ok": NOW - 60, "failing": False, "error": None}}
    used = next(r for r in s["metrics"] if r["metric"] == "svc.used")
    assert used["value"] == 72.0 and used["pressure"] == 0.72 and used["level"] == "ok"
    assert used["stale"] is False and used["support"] is False and used["at_limit"] == "it stops"
    assert used["resets_at"] is not None
    part = next(r for r in s["metrics"] if r["metric"] == "svc.part")
    assert part["support"] is True and part["dir"] == "min"


def test_projection_comes_from_history():
    reg, cfg, st = world()
    for day in range(7):
        st.add_snapshots(NOW - (7 - day) * 86_400, {"svc.used": 60.0 + day})
    st.add_snapshots(NOW, {"svc.used": 67.0})
    used = next(r for r in build_status(cfg, st, reg, NOW)["metrics"] if r["metric"] == "svc.used")
    assert abs(used["slope_per_day"] - 1.0) < 1e-6


def test_stale_after_two_intervals():
    reg, cfg, st = world()
    poll_once(cfg, st, reg, NOW - 3 * 900, lambda m: True)
    rows = build_status(cfg, st, reg, NOW)["metrics"]
    assert all(r["stale"] for r in rows)
    reg2, cfg2, _ = world()
    never = build_status(cfg2, fakes.store(), reg2, NOW)["metrics"]
    assert all(r["stale"] and r["value"] is None for r in never)


def test_rejects_bad_tokens():
    reg, cfg, st = world()
    srv, base = serve(cfg, st, reg)
    try:
        for token in (None, "", "wrong", TOKEN + "x", TOKEN[:-1], "é" * 43):
            code, body = get(f"{base}/api/status", token)
            assert code == 401 and body == {"error": "unauthorized"}, token
        assert get(f"{base}/api/status")[0] == 200
    finally:
        srv.shutdown()


def test_rejects_bad_queries():
    reg, cfg, st = world()
    poll_once(cfg, st, reg, NOW - 60, lambda m: True)
    srv, base = serve(cfg, st, reg)
    try:
        assert get(f"{base}/api/history?metric=svc.used&days=7") == \
            (200, {"metric": "svc.used", "points": [[NOW - 60, 72.0]]})
        for q in ("metric=nope&days=7", "metric=../etc&days=7", "metric=svc.used&days=0",
                  "metric=svc.used&days=91", "metric=svc.used&days=7abc", "days=7"):
            assert get(f"{base}/api/history?{q}")[0] == 400, q
        assert get(f"{base}/api/anything")[0] == 404
    finally:
        srv.shutdown()


def test_post_is_refused():
    reg, cfg, st = world()
    srv, base = serve(cfg, st, reg)
    try:
        assert get(f"{base}/api/status", method="POST")[0] == 501
    finally:
        srv.shutdown()


if __name__ == "__main__":
    _run.run(globals())
