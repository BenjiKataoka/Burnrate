import _run
import json
from pathlib import Path

from collectors import REGISTRY, clerk

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "clerk_count.json").read_text())


def test_collect_reads_the_total():
    seen = {}

    def get(url: str, headers: dict) -> dict:
        seen.update(url=url, headers=headers)
        return FIXTURE

    assert clerk.collect({"CLERK_SECRET_KEY": "sk"}, {}, get=get) == {"clerk.users": 142.0}
    assert seen["url"] == "https://api.clerk.com/v1/users/count"
    assert seen["headers"] == {"Authorization": "Bearer sk"}
    assert REGISTRY["clerk"] is clerk


def test_missing_total_raises():
    try:
        clerk.collect({"CLERK_SECRET_KEY": "sk"}, {}, get=lambda u, h: {"object": "error"})
    except KeyError:
        return
    raise AssertionError("expected KeyError")


if __name__ == "__main__":
    _run.run(globals())
