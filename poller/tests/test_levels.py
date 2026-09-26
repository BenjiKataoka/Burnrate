import _run
from levels import (DAY, Thresholds, days_to_limit, display_level, next_level,
                    next_month_start, pressure, resets_at, slope_per_day)

T = Thresholds()


def test_pressure_max_is_value_over_limit():
    assert pressure("max", 0.36, 0.5) == 0.72


def test_pressure_min_inverts_and_caps():
    assert abs(pressure("min", 25, 20) - 0.8) < 1e-9
    assert pressure("min", 0, 20) == 1.5


def test_display_level():
    assert display_level(0.5, T) == "ok"
    assert display_level(0.8, T) == "warn"
    assert display_level(1.0, T) == "crit"


def test_warning_fires_once_while_hovering():
    level, alerts = "ok", []
    for p in [0.79, 0.81, 0.79, 0.81, 0.77]:
        level, alert = next_level(level, p, T)
        alerts.append(alert)
    assert alerts == [None, "warn", None, None, None]
    assert level == "warn"


def test_warning_clears_quietly_under_75():
    assert next_level("warn", 0.74, T) == ("ok", None)


def test_jump_past_limit_sends_only_crit():
    assert next_level("ok", 1.02, T) == ("crit", "crit")


def test_crit_holds_until_under_95():
    assert next_level("crit", 0.97, T) == ("crit", None)
    assert next_level("crit", 0.90, T) == ("warn", "back_under")
    assert next_level("crit", 0.50, T) == ("ok", "back_under")


def test_crit_again_after_back_under():
    assert next_level("warn", 1.01, T) == ("crit", "crit")


def test_slope_per_day():
    assert slope_per_day([(0, 1.0), (DAY, 2.0), (2 * DAY, 3.0)]) == 1.0
    assert slope_per_day([(0, 1.0)]) is None
    assert slope_per_day([(5, 1.0), (5, 2.0)]) is None


def test_days_to_limit_max():
    assert abs(days_to_limit("max", 0.36, 0.5, 0.01, 0, None) - 14) < 1e-9
    assert days_to_limit("max", 0.36, 0.5, -0.01, 0, None) is None
    assert days_to_limit("max", 0.6, 0.5, 0.01, 0, None) is None


def test_days_to_limit_respects_monthly_reset():
    assert days_to_limit("max", 61, 100, 1.0, 0, 5 * DAY) is None
    assert abs(days_to_limit("max", 61, 100, 10.0, 0, 5 * DAY) - 3.9) < 1e-9


def test_days_to_limit_min_counts_down_to_the_floor():
    assert abs(days_to_limit("min", 31, 20, -1.0, 0, None) - 11) < 1e-9
    assert days_to_limit("min", 31, 20, 0.5, 0, None) is None


def test_next_month_start_rolls_the_year():
    dec_15 = 1797292800  # 2026-12-15 00:00 UTC
    assert next_month_start(dec_15) == 1798761600  # 2027-01-01 00:00 UTC
    assert resets_at("monthly", dec_15) == 1798761600
    assert resets_at("rolling", dec_15) is None


if __name__ == "__main__":
    _run.run(globals())
