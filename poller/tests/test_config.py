import _run
import tempfile
from pathlib import Path
from types import SimpleNamespace

from config import ConfigError, load_config, read_env_file
from metric import Metric

FAKE = SimpleNamespace(SERVICE="Fake", ENV=("FAKE_KEY",), REQUIRED=("project_id",),
                       METRICS={"fake.used": Metric("Used", "GB", "max", "it stops")},
                       collect=lambda env, section: {})
REGISTRY = {"fake": FAKE}
ENV = {"FAKE_KEY": "k"}
TOKEN = "t" * 40
HOOK = "https://discord.com/api/webhooks/1/abc"  # gitleaks:allow scan:allow

GOOD = """
[poller]
listen = "127.0.0.1:8787"

[fake]
project_id = "p1"
[fake.limits]
used = 10
"""


def write(text: str) -> Path:
    p = Path(tempfile.mkdtemp()) / "config.toml"
    p.write_text(text)
    return p


def error_of(text: str, env: dict = ENV, serving: bool = False) -> str:
    try:
        load_config(write(text), REGISTRY, env, serving)
    except ConfigError as e:
        return str(e)
    raise AssertionError("expected ConfigError")


def test_valid_config():
    cfg = load_config(write(GOOD), REGISTRY, ENV, serving=False)
    assert cfg.limits == {"fake.used": 10.0}
    assert (cfg.host, cfg.port, cfg.interval_s) == ("127.0.0.1", 8787, 900)
    assert cfg.services == {"fake": {"project_id": "p1", "limits": {"used": 10}}}


def test_missing_file():
    try:
        load_config(Path("/nonexistent/config.toml"), REGISTRY, ENV, False)
    except ConfigError as e:
        assert "not found" in str(e)
    else:
        raise AssertionError


def test_unknown_service():
    assert "unknown service in config: nope" in error_of(GOOD + "\n[nope]\n")


def test_no_services():
    assert "no services enabled" in error_of('[poller]\nlisten = "127.0.0.1:1"\n')


def test_missing_limit():
    assert "[fake.limits] used must be a positive number" in error_of(GOOD.replace("used = 10", ""))


def test_limit_must_be_a_positive_number():
    for bad in ('"10"', "0", "-1", "true"):
        assert "must be a positive number" in error_of(GOOD.replace("used = 10", f"used = {bad}"))


def test_missing_env_var():
    assert "FAKE_KEY is not set (needed by fake)" in error_of(GOOD, env={})


def test_missing_required_key():
    assert "[fake] project_id is not set" in error_of(GOOD.replace('project_id = "p1"', ""))


def test_serving_needs_a_long_token_and_a_discord_webhook():
    assert "BURNRATE_TOKEN" in error_of(GOOD, env={**ENV, "DISCORD_WEBHOOK_URL": HOOK}, serving=True)
    assert "BURNRATE_TOKEN" in error_of(GOOD, env={**ENV, "BURNRATE_TOKEN": "short",
                                                    "DISCORD_WEBHOOK_URL": HOOK}, serving=True)
    assert "DISCORD_WEBHOOK_URL" in error_of(GOOD, env={**ENV, "BURNRATE_TOKEN": TOKEN,
                                                         "DISCORD_WEBHOOK_URL": "http://x"}, serving=True)
    cfg = load_config(write(GOOD), REGISTRY, {**ENV, "BURNRATE_TOKEN": TOKEN,
                                              "DISCORD_WEBHOOK_URL": HOOK}, serving=True)
    assert cfg.port == 8787


def test_every_interface_is_refused():
    for host in ("0.0.0.0", "[::]", "::", ""):
        assert "refused" in error_of(GOOD.replace("127.0.0.1", host))


def test_bad_listen():
    assert "listen must look like" in error_of(GOOD.replace("127.0.0.1:8787", "localhost"))


def test_interval_bounds():
    assert "interval_minutes" in error_of(GOOD.replace("[poller]", "[poller]\ninterval_minutes = 1"))


def test_threshold_order():
    assert "thresholds" in error_of(GOOD.replace("[poller]", "[poller]\nwarn_at = 0.7"))


def test_read_env_file():
    p = Path(tempfile.mkdtemp()) / ".env"
    p.write_text('# comment\n\nA=1\nB="two"\nC=x=y\nnot a pair\n')
    assert read_env_file(p) == {"A": "1", "B": "two", "C": "x=y"}
    assert read_env_file(p.parent / "missing") == {}


def test_limits_must_be_a_table():
    assert "[fake.limits] must be a table of numbers" in error_of(GOOD.replace("[fake.limits]\nused = 10", "limits = 5"))


def test_service_must_be_a_table():
    text = """fake = 5

[poller]
listen = "127.0.0.1:8787"
"""
    assert "[fake] must be a table" in error_of(text)


def test_non_numeric_settings_are_refused_cleanly():
    for line in ('interval_minutes = "soon"', 'warn_at = "high"', "crit_clear = true", "fail_alert_after = 0"):
        key = line.split(" ")[0]
        assert f"[poller] {key} must be a number" in error_of(GOOD.replace("[poller]", f"[poller]\n{line}")), line


def test_port_range():
    assert "port must be 1 to 65535" in error_of(GOOD.replace("8787", "99999"))


if __name__ == "__main__":
    _run.run(globals())
