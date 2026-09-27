"""Discord messages. Severity is the embed colour and the first word of the title, never an
emoji. Mentions are disabled so provider error text can never ping a channel."""
import logging
from collections.abc import Callable

from fetch import FetchError, post_json
from metric import Metric

log = logging.getLogger("burnrate")
AMBER, RED, GREEN = 0xFF8A2B, 0xFF4D3D, 0x3DDC84
Message = dict


def num(v: float) -> str:
    """0.43, 86, 50,000: at most two decimals, no trailing zeros."""
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _embed(title: str, text: str, colour: int) -> Message:
    return {"username": "Burnrate", "allowed_mentions": {"parse": []},
            "embeds": [{"title": title, "description": text, "color": colour}]}


def _amount(m: Metric, value: float, limit: float) -> str:
    unit = f" {m.unit}" if m.unit else ""
    return f"{num(value)} of {num(limit)}{unit}"


def metric_message(kind: str, service: str, m: Metric, value: float, limit: float, pct: int,
                   days: float | None) -> Message:
    who = f"{service} {m.label.lower()}"
    edge = "floor" if m.dir == "min" else "limit"
    if kind == "warn":
        if m.dir == "min":
            head = f"{who} down to {num(value)}% (floor {num(limit)}%)."
        else:
            head = f"{who} at {pct}% ({_amount(m, value, limit)})."
        eta = f" {edge.capitalize()} in about {round(days)} days." if days is not None and days >= 1 else ""
        return _embed(f"Warning: {who}", f"{head}{eta} At the {edge}, {m.at_limit}.", AMBER)
    if kind == "crit":
        if m.dir == "min":
            text = f"{who} is below its floor ({num(value)}%, floor {num(limit)}%): {m.at_limit}."
        else:
            text = f"{who} is over its limit ({_amount(m, value, limit)}): {m.at_limit}."
        return _embed(f"Limit reached: {who}", text, RED)
    if m.dir == "min":
        text = f"{who} is back above its floor ({num(value)}%, floor {num(limit)}%)."
    else:
        text = f"{who} is back under its limit ({_amount(m, value, limit)})."
    return _embed(f"Back under the limit: {who}", text, GREEN)


def collector_failing(service: str, err: str) -> Message:
    return _embed(f"Collector failing: {service}",
                  f"The {service} collector is failing ({err}). Its numbers are stale until it recovers.",
                  AMBER)


def collector_recovered(service: str) -> Message:
    return _embed(f"Collector recovered: {service}", f"The {service} collector is working again.", GREEN)


def connected() -> Message:
    return _embed("Burnrate is connected", "Alerts will arrive in this channel.", GREEN)


def discord_sender(url: str, post: Callable[[str, dict], object] = post_json) -> Callable[[Message], bool]:
    def send(msg: Message) -> bool:
        try:
            post(url, msg)
            return True
        except FetchError as e:
            log.warning("Discord send failed: %s", e)  # FetchError text never holds the URL
            return False
    return send
