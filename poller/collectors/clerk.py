"""Clerk: total users. Clerk's free limit counts monthly retained users, which is never more
than the total, so the total is a safe upper bound."""
from collections.abc import Callable
from typing import Any

from fetch import get_json
from metric import Metric

SERVICE = "Clerk"
ENV = ("CLERK_SECRET_KEY",)
REQUIRED = ()
METRICS = {"clerk.users": Metric("Users", "", "max", "an upgrade is required")}


def collect(env: dict[str, str], section: dict,
            get: Callable[[str, dict[str, str]], Any] = get_json) -> dict[str, float]:
    body = get("https://api.clerk.com/v1/users/count",
               {"Authorization": f"Bearer {env['CLERK_SECRET_KEY']}"})
    return {"clerk.users": float(body["total_count"])}
