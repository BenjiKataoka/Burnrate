"""One poll cycle: run every collector, store what came back, record what failed, then
decide which alerts to send."""
import logging
import math
from collections.abc import Callable

import alerts
from config import Config
from fetch import FetchError
from levels import DAY, days_to_limit, next_level, pressure, resets_at, slope_per_day
from store import Store

log = logging.getLogger("burnrate")
SECRET_VARS = ("NEON_API_KEY", "CLERK_SECRET_KEY", "VERCEL_TOKEN", "DISCORD_WEBHOOK_URL",
               "BURNRATE_TOKEN")
Send = Callable[[dict], bool]


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


def evaluate(cfg: Config, store: Store, registry: dict, send: Send, now: int) -> None:
    """Alert on level changes only. A level is saved after Discord accepts the message, so
    a failed send is retried next poll and a restart never repeats one."""
    latest, runs = store.latest(), store.runs()
    for name in cfg.services:
        mod = registry[name]
        run = runs.get(name, {"fails": 0, "last_ok": None, "last_err": None})
        key = f"collector:{name}"
        if run["fails"] >= cfg.fail_alert_after and store.level(key) != "failing":
            if send(alerts.collector_failing(mod.SERVICE, run["last_err"] or "unknown error")):
                store.set_level(key, "failing", now)
        elif run["fails"] == 0 and store.level(key) == "failing":
            if send(alerts.collector_recovered(mod.SERVICE)):
                store.set_level(key, "ok", now)
        if run["last_ok"] != now:
            continue  # only judge values collected in this cycle
        for metric, m in mod.METRICS.items():
            if m.support or metric not in latest:
                continue
            value, limit = latest[metric][1], cfg.limits[metric]
            p = pressure(m.dir, value, limit)
            prev = store.level(metric)
            level, alert = next_level(prev, p, cfg.thresholds)
            if alert is None:
                if level != prev:
                    store.set_level(metric, level, now)
                continue
            days = None
            if alert == "warn":
                slope = slope_per_day(store.history(metric, now - 7 * DAY))
                days = days_to_limit(m.dir, value, limit, slope, now, resets_at(m.resets, now))
            if send(alerts.metric_message(alert, mod.SERVICE, m, value, limit, round(p * 100), days)):
                store.set_level(metric, level, now)


def poll_once(cfg: Config, store: Store, registry: dict, now: int, send: Send) -> None:
    for name, result in collect_all(cfg, registry).items():
        if isinstance(result, str):
            fails = store.run_failed(name, now, result)
            log.warning("%s collector failed (%d in a row): %s", registry[name].SERVICE, fails, result)
        else:
            store.add_snapshots(now, result)
            store.run_ok(name, now)
    evaluate(cfg, store, registry, send, now)
