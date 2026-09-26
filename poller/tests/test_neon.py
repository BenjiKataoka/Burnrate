import _run
import json
from pathlib import Path

from collectors import REGISTRY, neon

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "neon_project.json").read_text())


def test_collect_converts_units():
    seen = {}

    def get(url: str, headers: dict) -> dict:
        seen.update(url=url, headers=headers)
        return FIXTURE

    values = neon.collect({"NEON_API_KEY": "key"}, {"project_id": "p1"}, get=get)
    assert values == {"neon.compute_cu_hours": 61.0, "neon.transfer_gb": 1.1,
                      "neon.storage_gb": 0.36}
    assert seen["url"] == "https://console.neon.tech/api/v2/projects/p1"
    assert seen["headers"] == {"Authorization": "Bearer key"}


def test_missing_field_raises():
    broken = {"project": {k: v for k, v in FIXTURE["project"].items() if k != "data_transfer_bytes"}}
    try:
        neon.collect({"NEON_API_KEY": "k"}, {"project_id": "p1"}, get=lambda u, h: broken)
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_metrics_match_what_collect_returns():
    values = neon.collect({"NEON_API_KEY": "k"}, {"project_id": "p1"}, get=lambda u, h: FIXTURE)
    assert set(values) == set(neon.METRICS)
    assert REGISTRY["neon"] is neon


if __name__ == "__main__":
    _run.run(globals())
