import _run
import io
import logging

from alerts import (AMBER, GREEN, RED, collector_failing, collector_recovered, connected,
                    discord_sender, metric_message, num)
from fetch import FetchError
from metric import Metric

STORAGE = Metric("Storage", "GB", "max", "writes fail")
COMPUTE = Metric("Compute", "CU-h", "max", "the database is suspended until next month", "monthly")
GUARD = Metric("Idle guard", "%", "min", "Oracle can reclaim the VM", "rolling")
USERS = Metric("Users", "", "max", "an upgrade is required")

# Captures "burnrate" logger output instead of letting the two expected "Discord send failed"
# warnings below fall through to logging's last-resort handler and print to stderr.
LOG = io.StringIO()
logging.getLogger("burnrate").addHandler(logging.StreamHandler(LOG))


def embed(msg: dict) -> dict:
    assert msg["allowed_mentions"] == {"parse": []}
    assert msg["username"] == "Burnrate"
    return msg["embeds"][0]


def test_num():
    assert [num(v) for v in (0.43, 86.0, 50000, 0.5, 1.10, 0.0)] == \
        ["0.43", "86", "50,000", "0.5", "1.1", "0"]


def test_warning_max():
    e = embed(metric_message("warn", "Neon", STORAGE, 0.43, 0.5, 86, 4.2))
    assert e["title"] == "Warning: Neon storage" and e["color"] == AMBER
    assert e["description"] == ("Neon storage at 86% (0.43 of 0.5 GB). Limit in about 4 days. "
                                "At the limit, writes fail.")


def test_warning_without_projection_and_unitless():
    e = embed(metric_message("warn", "Clerk", USERS, 41000, 50000, 82, None))
    assert e["description"] == "Clerk users at 82% (41,000 of 50,000). At the limit, an upgrade is required."


def test_warning_min():
    e = embed(metric_message("warn", "Oracle", GUARD, 25, 20, 80, 6))
    assert e["description"] == ("Oracle idle guard down to 25% (floor 20%). Floor in about 6 days. "
                                "At the floor, Oracle can reclaim the VM.")


def test_limit_reached():
    e = embed(metric_message("crit", "Neon", STORAGE, 0.51, 0.5, 102, None))
    assert e["title"] == "Limit reached: Neon storage" and e["color"] == RED
    assert e["description"] == "Neon storage is over its limit (0.51 of 0.5 GB): writes fail."
    e = embed(metric_message("crit", "Oracle", GUARD, 18, 20, 111, None))
    assert e["description"] == "Oracle idle guard is below its floor (18%, floor 20%): Oracle can reclaim the VM."


def test_back_under():
    e = embed(metric_message("back_under", "Neon", COMPUTE, 80, 100, 80, None))
    assert e["title"] == "Back under the limit: Neon compute" and e["color"] == GREEN
    assert e["description"] == "Neon compute is back under its limit (80 of 100 CU-h)."


def test_collector_messages():
    e = embed(collector_failing("Neon", "HTTP 401"))
    assert e["title"] == "Collector failing: Neon" and e["color"] == AMBER
    assert e["description"] == "The Neon collector is failing (HTTP 401). Its numbers are stale until it recovers."
    assert embed(collector_recovered("Neon"))["color"] == GREEN
    assert embed(connected())["title"] == "Burnrate is connected"


def test_house_style_no_dashes_ellipses_or_emoji():
    msgs = [metric_message(k, "Neon", STORAGE, 0.43, 0.5, 86, 4) for k in ("warn", "crit", "back_under")]
    msgs += [collector_failing("Neon", "HTTP 500"), collector_recovered("Neon"), connected()]
    for msg in msgs:
        text = embed(msg)["title"] + embed(msg)["description"]
        assert all(ord(c) < 0x2000 for c in text), text


def test_sender_reports_success_and_failure():
    sent = []
    ok = discord_sender("https://example.invalid/hook", post=lambda u, b: sent.append(b))
    assert ok(connected()) is True and len(sent) == 1

    def down(url: str, body: dict) -> None:
        raise FetchError("HTTP 429", 429)
    assert discord_sender("https://example.invalid/hook", post=down)(connected()) is False


def test_warning_says_one_day():
    e = embed(metric_message("warn", "Neon", STORAGE, 0.43, 0.5, 86, 1.2))
    assert "Limit in about 1 day." in e["description"]
    assert "1 days" not in e["description"]


def test_sender_never_raises():
    def bad_post(url: str, body: dict) -> None:
        raise TypeError("not serializable")
    assert discord_sender("https://example.invalid/hook", post=bad_post)(connected()) is False


def test_back_under_min_and_recovered_text():
    e = embed(metric_message("back_under", "Oracle", GUARD, 25, 20, 80, None))
    assert e["title"] == "Back above the floor: Oracle idle guard"
    assert e["description"] == "Oracle idle guard is back above its floor (25%, floor 20%)."
    e = embed(collector_recovered("Neon"))
    assert e["title"] == "Collector recovered: Neon"
    assert e["description"] == "The Neon collector is working again."


if __name__ == "__main__":
    _run.run(globals())
