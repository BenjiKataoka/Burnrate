import _run
from datetime import datetime, timedelta, timezone

from collectors import REGISTRY, oracle

NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
SECTION = {"compartment_id": "ocid1.tenancy.oc1..example", "instance_id": "ocid1.instance.oc1.example",
           "network_gbps": 1}


def standard() -> dict[str, list[float]]:
    return {"CpuUtilization": [float(v) for v in range(1, 101)],     # p95 by nearest rank = 95
            "MemoryUtilization": [30.0, 32.0],                         # mean 31
            "NetworksBytesIn": [300 * 1.25e6] * 4,                     # 10 Mbit/s = 1% of 1 Gbps
            "NetworksBytesOut": [300 * 0.625e6] * 4,                   # 0.5%
            }


def test_collect_computes_the_idle_rule_inputs():
    calls: list = []
    data = standard()
    out = oracle.collect({}, SECTION, series=lambda q, s, e: (calls.append((q, s, e)) or
                         ([2e12, 1e12] if "[1h]" in q else data[q.split("[")[0]])), now=NOW)
    assert out["oracle.cpu_p95"] == 95.0
    assert out["oracle.memory"] == 31.0
    assert abs(out["oracle.network"] - 1.0) < 1e-9
    assert out["oracle.idle_guard"] == 95.0
    assert out["oracle.outbound_tb"] == 3.0
    week = [c for c in calls if "[5m]" in c[0]]
    assert all(c[1] == NOW - timedelta(days=7) and c[2] == NOW for c in week)
    assert all('resourceId = "ocid1.instance.oc1.example"' in c[0] for c in calls)
    month = [c for c in calls if "[1h]" in c[0]]
    assert month[0][1] == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert REGISTRY["oracle"] is oracle


def test_idle_guard_is_the_busiest_of_the_three():
    data = standard()
    data["CpuUtilization"] = [5.0] * 20
    out = oracle.collect({}, SECTION, series=lambda q, s, e: [0.0] if "[1h]" in q
                         else data[q.split("[")[0]], now=NOW)
    assert out["oracle.idle_guard"] == 31.0


def test_no_cpu_data_is_an_error():
    data = standard()
    data["CpuUtilization"] = []
    try:
        oracle.collect({}, SECTION, series=lambda q, s, e: [] if "[1h]" in q
                       else data[q.split("[")[0]], now=NOW)
    except ValueError as e:
        assert "no CpuUtilization data" in str(e)
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    _run.run(globals())
