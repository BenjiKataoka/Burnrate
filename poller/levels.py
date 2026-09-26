"""Pure maths shared by alerts and the API: pressure, levels with hysteresis, projections."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Level = Literal["ok", "warn", "crit"]
Alert = Literal["warn", "crit", "back_under"]
DAY = 86_400


@dataclass(frozen=True)
class Thresholds:
    warn_at: float = 0.80
    warn_clear: float = 0.75
    crit_clear: float = 0.95


def pressure(direction: str, value: float, limit: float) -> float:
    """1.0 means at the limit. Floors invert (lower is worse), capped so a zero stays finite."""
    if direction == "min":
        return min(1.5, limit / max(value, 0.01))
    return value / limit


def display_level(p: float, t: Thresholds) -> Level:
    return "crit" if p >= 1 else "warn" if p >= t.warn_at else "ok"


def next_level(prev: str, p: float, t: Thresholds) -> tuple[Level, Alert | None]:
    """Edge-triggered with hysteresis, so a value hovering at a threshold alerts once."""
    if p >= 1:
        return "crit", None if prev == "crit" else "crit"
    if prev == "crit":
        if p >= t.crit_clear:
            return "crit", None
        return ("warn" if p >= t.warn_clear else "ok"), "back_under"
    if prev == "warn":
        return ("warn" if p >= t.warn_clear else "ok"), None
    return ("warn", "warn") if p >= t.warn_at else ("ok", None)


def slope_per_day(points: list[tuple[int, float]]) -> float | None:
    """Least-squares slope in units per day."""
    if len(points) < 2:
        return None
    n = len(points)
    mx = sum(t for t, _ in points) / n
    my = sum(v for _, v in points) / n
    den = sum((t - mx) ** 2 for t, _ in points)
    if den == 0:
        return None
    return sum((t - mx) * (v - my) for t, v in points) / den * DAY


def days_to_limit(direction: str, value: float, limit: float, slope: float | None,
                  now: int, resets_at: int | None) -> float | None:
    """Days until the limit at the current slope; None when never, already there, or after a reset."""
    if slope is None:
        return None
    if direction == "min":
        if slope >= 0 or value <= limit:
            return None
        days = (value - limit) / -slope
    else:
        if slope <= 0 or value >= limit:
            return None
        days = (limit - value) / slope
    if resets_at is not None and now + days * DAY > resets_at:
        return None
    return days


def next_month_start(now: int) -> int:
    # ponytail: calendar month in UTC; Neon's billing period may start on another day
    # (checked against consumption_period_end in Task 6), change here if it does.
    d = datetime.fromtimestamp(now, timezone.utc)
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())


def resets_at(resets: str, now: int) -> int | None:
    return next_month_start(now) if resets == "monthly" else None
