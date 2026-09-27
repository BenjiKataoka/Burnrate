"""Vercel: deployments in the last 24 hours against Hobby's 100 a day. Hobby has no usage
API (billing/charges answers costs_not_found), so this is the one Vercel limit in v1."""
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from fetch import get_json
from metric import Metric

SERVICE = "Vercel"
ENV = ("VERCEL_TOKEN",)
REQUIRED = ()
METRICS = {"vercel.deploys_24h": Metric("Deploys in 24 hours", "", "max",
                                        "deploys are blocked", "rolling")}


def collect(env: dict[str, str], section: dict,
            get: Callable[[str, dict[str, str]], Any] = get_json,
            now: float | None = None) -> dict[str, float]:
    since_ms = int(((now or time.time()) - 86_400) * 1000)
    query = {"since": since_ms, "limit": 100}
    if env.get("VERCEL_TEAM_ID"):
        query["teamId"] = env["VERCEL_TEAM_ID"]
    body = get(f"https://api.vercel.com/v6/deployments?{urlencode(query)}",
               {"Authorization": f"Bearer {env['VERCEL_TOKEN']}"})
    # ponytail: one page of 100; a full page already means "at the limit", so no paging.
    return {"vercel.deploys_24h": float(len(body["deployments"]))}
