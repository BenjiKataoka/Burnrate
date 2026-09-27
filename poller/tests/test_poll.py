import _run
import io
import logging

import fakes
from fetch import FetchError
from metric import Metric
from poll import collect_all, describe_error, poll_once

USED = {"svc.used": Metric("Used", "GB", "max", "it stops")}

# Captures "burnrate" logger output instead of letting it fall through to logging's
# last-resort handler, which would otherwise print warnings straight to stderr during tests.
LOG = io.StringIO()
logging.getLogger("burnrate").addHandler(logging.StreamHandler(LOG))


def boom(env: dict, section: dict) -> dict:
    raise FetchError("HTTP 401", 401)


def test_one_failing_collector_does_not_stop_the_others():
    reg = {"good": fakes.service("Good", {"good.used": USED["svc.used"]},
                                 lambda env, s: {"good.used": 3.0}),
           "bad": fakes.service("Bad", {"bad.used": USED["svc.used"]}, boom)}
    cfg = fakes.config(reg, {"good.used": 10, "bad.used": 10})
    st = fakes.store()
    poll_once(cfg, st, reg, 1000, lambda m: True)
    assert st.latest() == {"good.used": (1000, 3.0)}
    runs = st.runs()
    assert runs["good"]["fails"] == 0 and runs["good"]["last_ok"] == 1000
    assert runs["bad"] == {"last_ok": None, "last_err": "HTTP 401", "fails": 1}
    assert "Bad collector failed (1 in a row): HTTP 401" in LOG.getvalue()


def test_bad_shape_is_a_failure_not_a_crash():
    cases = {
        "missing": lambda env, s: {}["project"],                  # KeyError from a renamed field
        "negative": lambda env, s: {"svc.used": -1.0},
        "nan": lambda env, s: {"svc.used": float("nan")},
        "text": lambda env, s: {"svc.used": "12"},
        "extra": lambda env, s: {"svc.used": 1.0, "svc.other": 2.0},
        "empty": lambda env, s: {},
    }
    for name, fn in cases.items():
        reg = {"svc": fakes.service("Svc", USED, fn)}
        cfg = fakes.config(reg, {"svc.used": 10})
        result = collect_all(cfg, reg)["svc"]
        assert isinstance(result, str), name
        st = fakes.store()
        poll_once(cfg, st, reg, 5, lambda m: True)
        assert st.latest() == {} and st.runs()["svc"]["fails"] == 1, name


def test_describe_error_redacts_secrets_and_truncates():
    e = ValueError("bad key not-a-real-key-SECRETVALUE in " + "x" * 400)
    text = describe_error(e, ["not-a-real-key-SECRETVALUE", ""])
    assert "SECRETVALUE" not in text and "[redacted]" in text
    assert text.startswith("ValueError: ") and len(text) <= 160
    assert describe_error(FetchError("HTTP 503", 503), []) == "HTTP 503"


def test_secrets_from_the_environment_are_redacted():
    secret = "not-a-real-key-123"  # scan:allow

    def leaky(env: dict, s: dict) -> dict:
        raise RuntimeError(f"auth failed with {secret}")

    reg = {"svc": fakes.service("Svc", USED, leaky)}
    cfg = fakes.config(reg, {"svc.used": 10}, env={"NEON_API_KEY": secret})
    st = fakes.store()
    poll_once(cfg, st, reg, 1, lambda m: True)
    err = st.runs()["svc"]["last_err"]
    assert secret not in err and "[redacted]" in err


if __name__ == "__main__":
    _run.run(globals())
