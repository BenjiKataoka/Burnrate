"""One poll cycle: run every collector, store what came back, record what failed."""
import logging
import math

from config import Config
from fetch import FetchError
from store import Store

log = logging.getLogger("burnrate")
SECRET_VARS = ("NEON_API_KEY", "CLERK_SECRET_KEY", "VERCEL_TOKEN", "DISCORD_WEBHOOK_URL",
               "BURNRATE_TOKEN")


def describe_error(e: Exception, secrets: list[str]) -> str:
    """Short, loggable, Discord-safe: secrets replaced, length capped."""
    text = str(e) if isinstance(e, FetchError) else f"{type(e).__name__}: {e}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:160]


def _valid(values: object, allowed: set[str]) -> bool:
    return (isinstance(values, dict) and set(values) == allowed and
            all(isinstance(v, (int, float)) and not isinstance(v, bool) and
                math.isfinite(v) and v >= 0 for v in values.values()))


def collect_all(cfg: Config, registry: dict) -> dict[str, dict[str, float] | str]:
    """service -> values on success, or service -> error text."""
    secrets = [cfg.env.get(var, "") for var in SECRET_VARS]
    out: dict[str, dict[str, float] | str] = {}
    for name, section in cfg.services.items():
        mod = registry[name]
        try:
            values = mod.collect(cfg.env, section)
            if not _valid(values, set(mod.METRICS)):
                raise ValueError("missing or unexpected metric names, or a value that is "
                                 "not a non-negative number")
            out[name] = {k: float(v) for k, v in values.items()}
        except Exception as e:  # one broken collector must never stop the others
            out[name] = describe_error(e, secrets)
    return out


def poll_once(cfg: Config, store: Store, registry: dict, now: int) -> None:
    for name, result in collect_all(cfg, registry).items():
        if isinstance(result, str):
            fails = store.run_failed(name, now, result)
            log.warning("%s collector failed (%d in a row): %s", registry[name].SERVICE, fails, result)
        else:
            store.add_snapshots(now, result)
            store.run_ok(name, now)
