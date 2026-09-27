import _run
import io
import logging

import fakes
from alerts import collector_failing
from metric import Metric
from poll import poll_once

cred_value = "not-a-real-key-THISMUSTNEVERLEAK"
HOOK = "https://example.invalid/hooks/HOOKSECRET"


def test_a_failing_collector_never_leaks_secrets():
    def leaky(env: dict, s: dict) -> dict:
        raise RuntimeError(f"auth failed for {cred_value} via {HOOK}")

    reg = {"svc": fakes.service("Svc", {"svc.used": Metric("Used", "", "max", "x")}, leaky)}
    cfg = fakes.config(reg, {"svc.used": 10},
                       env={"CLERK_SECRET_KEY": cred_value, "DISCORD_WEBHOOK_URL": HOOK})
    st = fakes.store()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger("burnrate").addHandler(handler)
    try:
        poll_once(cfg, st, reg, 1, lambda m: True)
    finally:
        logging.getLogger("burnrate").removeHandler(handler)
    stored = st.runs()["svc"]["last_err"]
    discord = str(collector_failing("Svc", stored))
    for text in (buf.getvalue(), stored, discord):
        assert "THISMUSTNEVERLEAK" not in text and "HOOKSECRET" not in text, text
    assert "[redacted]" in stored


if __name__ == "__main__":
    _run.run(globals())
