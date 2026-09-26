import _run
import fakes
from fetch import FetchError
from metric import Metric
from poll import collect_all, describe_error, poll_once

USED = {"svc.used": Metric("Used", "GB", "max", "it stops")}


def boom(env: dict, section: dict) -> dict:
    raise FetchError("HTTP 401", 401)


def test_one_failing_collector_does_not_stop_the_others():
    reg = {"good": fakes.service("Good", {"good.used": USED["svc.used"]},
                                 lambda env, s: {"good.used": 3.0}),
           "bad": fakes.service("Bad", {"bad.used": USED["svc.used"]}, boom)}
    cfg = fakes.config(reg, {"good.used": 10, "bad.used": 10})
    st = fakes.store()
    poll_once(cfg, st, reg, 1000)
    assert st.latest() == {"good.used": (1000, 3.0)}
    runs = st.runs()
    assert runs["good"]["fails"] == 0 and runs["good"]["last_ok"] == 1000
    assert runs["bad"] == {"last_ok": None, "last_err": "HTTP 401", "fails": 1}


def test_bad_shape_is_a_failure_not_a_crash():
    cases = {
        "missing": lambda env, s: {}["project"],                  # KeyError from a renamed field
        "negative": lambda env, s: {"svc.used": -1.0},
        "nan": lambda env, s: {"svc.used": float("nan")},
        "text": lambda env, s: {"svc.used": "12"},
        "extra": lambda env, s: {"svc.used": 1.0, "svc.other": 2.0},
    }
    for name, fn in cases.items():
        reg = {"svc": fakes.service("Svc", USED, fn)}
        cfg = fakes.config(reg, {"svc.used": 10})
        result = collect_all(cfg, reg)["svc"]
        assert isinstance(result, str), name
        st = fakes.store()
        poll_once(cfg, st, reg, 5)
        assert st.latest() == {} and st.runs()["svc"]["fails"] == 1, name


def test_describe_error_redacts_secrets_and_truncates():
    e = ValueError("bad key sk_test_SECRETVALUE123 in " + "x" * 400)  # gitleaks:allow
    text = describe_error(e, ["sk_test_SECRETVALUE123", ""])  # gitleaks:allow
    assert "SECRETVALUE" not in text and "[redacted]" in text
    assert text.startswith("ValueError: ") and len(text) <= 160
    assert describe_error(FetchError("HTTP 503", 503), []) == "HTTP 503"


if __name__ == "__main__":
    _run.run(globals())
