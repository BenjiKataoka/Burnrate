import _run
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from collectors import REGISTRY, vercel

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "vercel_deployments.json").read_text())
NOW = 1790460000


def call(env: dict) -> tuple[dict, dict]:
    seen = {}

    def get(url: str, headers: dict) -> dict:
        seen.update(url=url, headers=headers)
        return FIXTURE

    return vercel.collect(env, {}, get=get, now=NOW), seen


def test_counts_deployments_in_the_last_24_hours():
    values, seen = call({"VERCEL_TOKEN": "tok"})
    assert values == {"vercel.deploys_24h": 3.0}
    url = urlsplit(seen["url"])
    assert url.netloc == "api.vercel.com" and url.path == "/v6/deployments"
    q = parse_qs(url.query)
    assert q["since"] == [str((NOW - 86_400) * 1000)] and q["limit"] == ["100"]
    assert "teamId" not in q
    assert seen["headers"] == {"Authorization": "Bearer tok"}
    assert REGISTRY["vercel"] is vercel


def test_team_id_is_passed_when_set():
    _, seen = call({"VERCEL_TOKEN": "tok", "VERCEL_TEAM_ID": "team_1"})
    assert parse_qs(urlsplit(seen["url"]).query)["teamId"] == ["team_1"]


if __name__ == "__main__":
    _run.run(globals())
