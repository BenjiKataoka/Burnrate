import _run
import io
import logging

import fakes
from fetch import FetchError
from metric import Metric
from poll import poll_once
from store import Store

USED = Metric("Used", "GB", "max", "it stops")
FLOOR = Metric("Guard", "%", "min", "it is reclaimed", "rolling")
SUPPORT = Metric("Part", "%", "min", "", "rolling", support=True)

# Captures "burnrate" logger output instead of letting it fall through to logging's
# last-resort handler, which would otherwise print the collector-failing warnings to
# stderr during this test.
LOG = io.StringIO()
logging.getLogger("burnrate").addHandler(logging.StreamHandler(LOG))


class Box:
    """A collector whose value the test changes between polls."""
    def __init__(self, value: float) -> None:
        self.value = value

    def collect(self, env: dict, s: dict) -> dict:
        return {"svc.used": self.value}


def setup(value: float):
    box = Box(value)
    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, box.collect)}
    cfg = fakes.config(reg, {"svc.used": 100})
    return box, reg, cfg, Store(cfg.db_path)


def titles(sent: list) -> list[str]:
    return [m["embeds"][0]["title"] for m in sent]


def test_warning_once_then_silence():
    box, reg, cfg, st = setup(86)
    sent: list = []
    for t in (1, 2, 3):
        poll_once(cfg, st, reg, t * 900, lambda m: sent.append(m) or True)
    assert titles(sent) == ["Warning: Svc used"]
    assert st.level("svc.used") == "warn"


def test_jump_past_the_limit_then_back_under():
    box, reg, cfg, st = setup(50)
    sent: list = []
    send = lambda m: sent.append(m) or True  # noqa: E731
    poll_once(cfg, st, reg, 900, send)
    box.value = 102
    poll_once(cfg, st, reg, 1800, send)
    box.value = 97
    poll_once(cfg, st, reg, 2700, send)
    box.value = 90
    poll_once(cfg, st, reg, 3600, send)
    assert titles(sent) == ["Limit reached: Svc used", "Back under the limit: Svc used"]
    assert st.level("svc.used") == "warn"


def test_failed_send_retries_next_poll():
    box, reg, cfg, st = setup(86)
    sent: list = []
    poll_once(cfg, st, reg, 900, lambda m: False)          # Discord down
    assert st.level("svc.used") == "ok"
    poll_once(cfg, st, reg, 1800, lambda m: sent.append(m) or True)
    poll_once(cfg, st, reg, 2700, lambda m: sent.append(m) or True)
    assert titles(sent) == ["Warning: Svc used"]


def test_restart_does_not_repeat_alerts():
    box, reg, cfg, st = setup(86)
    sent: list = []
    poll_once(cfg, st, reg, 900, lambda m: sent.append(m) or True)
    restarted = Store(cfg.db_path)
    poll_once(cfg, restarted, reg, 1800, lambda m: sent.append(m) or True)
    assert len(sent) == 1


def test_collector_failing_after_four_then_recovered():
    state = {"fail": True}

    def flaky(env: dict, s: dict) -> dict:
        if state["fail"]:
            raise FetchError("HTTP 401", 401)
        return {"svc.used": 10.0}

    reg = {"svc": fakes.service("Svc", {"svc.used": USED}, flaky)}
    cfg = fakes.config(reg, {"svc.used": 100})
    st = Store(cfg.db_path)
    sent: list = []
    send = lambda m: sent.append(m) or True  # noqa: E731
    for t in range(1, 7):
        poll_once(cfg, st, reg, t * 900, send)
    assert titles(sent) == ["Collector failing: Svc"]
    assert "HTTP 401" in sent[0]["embeds"][0]["description"]
    state["fail"] = False
    poll_once(cfg, st, reg, 7 * 900, send)
    assert titles(sent)[-1] == "Collector recovered: Svc"


def test_support_metrics_never_alert_and_floors_do():
    values = {"svc.guard": 22.0, "svc.part": 1.0}
    reg = {"svc": fakes.service("Svc", {"svc.guard": FLOOR, "svc.part": SUPPORT},
                                lambda env, s: dict(values))}
    cfg = fakes.config(reg, {"svc.guard": 20, "svc.part": 20})
    st = Store(cfg.db_path)
    sent: list = []
    poll_once(cfg, st, reg, 900, lambda m: sent.append(m) or True)
    assert titles(sent) == ["Warning: Svc guard"]
    assert "down to 22%" in sent[0]["embeds"][0]["description"]


def test_metrics_from_a_failed_cycle_are_not_judged():
    box, reg, cfg, st = setup(10)
    poll_once(cfg, st, reg, 900, lambda m: True)
    st.add_snapshots(1000, {"svc.used": 99.0})   # an old high value, not from this cycle

    def boom(env: dict, s: dict) -> dict:
        raise FetchError("HTTP 500", 500)
    reg["svc"].collect = boom
    sent: list = []
    poll_once(cfg, st, reg, 1800, lambda m: sent.append(m) or True)
    assert sent == []


if __name__ == "__main__":
    _run.run(globals())
