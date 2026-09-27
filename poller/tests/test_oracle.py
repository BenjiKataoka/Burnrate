import _run
import sys
import types
from datetime import datetime, timedelta, timezone

from collectors import REGISTRY, oracle

NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
SECTION = {"compartment_id": "ocid1.tenancy.oc1..example", "instance_id": "ocid1.instance.oc1.example",
           "network_gbps": 1}


def _key(query: str) -> tuple[str, str]:
    # name is before "[", statistic is the call after the last "." (e.g. "rate", "sum")
    name = query.split("[")[0]
    stat = query.rsplit(".", 1)[-1].split("(")[0]
    return name, stat


def standard() -> dict[tuple[str, str], list[float]]:
    return {("CpuUtilization", "mean"): [float(v) for v in range(1, 101)],  # p95 by rank = 95
            ("MemoryUtilization", "mean"): [30.0, 32.0],                     # mean 31
            ("NetworksBytesIn", "rate"): [1.25e6] * 4,                       # 10 Mbit/s = 1% of 1 Gbps
            ("NetworksBytesOut", "rate"): [0.625e6] * 4,                     # 0.5%
            ("NetworksBytesOut", "increment"): [2e12, 1e12],                 # 3 TB this month
            }


def fake_series(data):
    # keyed on (name, statistic) so a query for the wrong statistic (e.g. .sum() on a
    # counter) raises KeyError instead of silently reading someone else's fixture
    return lambda q, s, e: data[_key(q)]


def test_collect_computes_the_idle_rule_inputs():
    calls: list = []
    data = standard()

    def series(q, s, e):
        calls.append((q, s, e))
        return data[_key(q)]

    out = oracle.collect({}, SECTION, series=series, now=NOW)
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
    data[("CpuUtilization", "mean")] = [5.0] * 20
    out = oracle.collect({}, SECTION, series=fake_series(data), now=NOW)
    assert out["oracle.idle_guard"] == 31.0


def test_no_cpu_data_is_an_error():
    data = standard()
    data[("CpuUtilization", "mean")] = []
    try:
        oracle.collect({}, SECTION, series=fake_series(data), now=NOW)
    except ValueError as e:
        assert "no CpuUtilization data" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_empty_memory_is_an_error():
    data = standard()
    data[("MemoryUtilization", "mean")] = []
    try:
        oracle.collect({}, SECTION, series=fake_series(data), now=NOW)
    except ValueError as e:
        assert "no MemoryUtilization data" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_returns_exactly_its_metrics():
    data = standard()
    out = oracle.collect({}, SECTION, series=fake_series(data), now=NOW)
    assert set(out) == set(oracle.METRICS)


def test_month_start_on_day_one():
    now = datetime(2026, 10, 1, 0, 5, tzinfo=timezone.utc)
    data = standard()
    calls: list = []

    def series(q, s, e):
        calls.append((q, s, e))
        return data[_key(q)]

    oracle.collect({}, SECTION, series=series, now=now)
    month = [c for c in calls if "[1h]" in c[0]]
    assert month[0][1] == datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_network_uses_rate_of_the_counter():
    # rate() bytes/sec direct from Oracle, not a running total: 10 Mbit/s in, 5 Mbit/s out
    # over a 1 Gbps link is 1% (the larger of the two)
    data = standard()
    out = oracle.collect({}, SECTION, series=fake_series(data), now=NOW)
    assert abs(out["oracle.network"] - 1.0) < 1e-9


def test_outbound_uses_the_increment():
    # increment() per-interval change for the month, not a cumulative counter sum
    data = standard()
    out = oracle.collect({}, SECTION, series=fake_series(data), now=NOW)
    assert out["oracle.outbound_tb"] == 3.0


def test_counter_reset_points_are_ignored():
    # a counter reset (VM/agent restart) can make one rate()/increment() point negative;
    # those points are dropped rather than pulling the average or the total down
    data = standard()
    data[("NetworksBytesIn", "rate")] = [1.25e6, -5e9, 1.25e6]
    data[("NetworksBytesOut", "increment")] = [1e12, -2e12, 1e12]
    out = oracle.collect({}, SECTION, series=fake_series(data), now=NOW)
    assert abs(out["oracle.network"] - 1.0) < 1e-9
    assert out["oracle.outbound_tb"] == 2.0


def test_all_negative_network_is_an_error():
    data = standard()
    data[("NetworksBytesIn", "rate")] = [-1.0, -2.0]
    try:
        oracle.collect({}, SECTION, series=fake_series(data), now=NOW)
    except ValueError as e:
        assert "no NetworksBytesIn data" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_bad_instance_id_is_refused():
    section = dict(SECTION, instance_id="not-an-ocid")
    try:
        oracle.collect({}, section, series=lambda q, s, e: [1.0], now=NOW)
    except ValueError as e:
        assert "instance_id" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_network_gbps_is_required():
    missing = {k: v for k, v in SECTION.items() if k != "network_gbps"}
    zero = dict(SECTION, network_gbps=0)
    for bad in (missing, zero):
        try:
            oracle.collect({}, bad, series=lambda q, s, e: [1.0], now=NOW)
        except ValueError as e:
            assert "network_gbps" in str(e)
            continue
        raise AssertionError("expected ValueError")


def test_sdk_path_uses_matching_resolution_and_one_client():
    calls = {"clients": [], "details": []}

    class FakeSigner:
        region = "us-ashburn-1"

    class FakeServiceError(Exception):
        def __init__(self, status, code, headers, message):
            super().__init__(message)
            self.status = status
            self.code = code
            self.message = message

    class FakeDetails:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeNoneRetryStrategy:
        pass

    class FakeMonitoringClient:
        def __init__(self, config=None, signer=None, timeout=None, retry_strategy=None):
            calls["clients"].append({"config": config, "signer": signer, "timeout": timeout,
                                     "retry_strategy": retry_strategy})

        def summarize_metrics_data(self, compartment_id, details):
            calls["details"].append(details)
            point = types.SimpleNamespace(value=1.0)
            item = types.SimpleNamespace(aggregated_datapoints=[point])
            return types.SimpleNamespace(data=[item])

    fake_oci = types.SimpleNamespace(
        auth=types.SimpleNamespace(signers=types.SimpleNamespace(
            InstancePrincipalsSecurityTokenSigner=FakeSigner)),
        monitoring=types.SimpleNamespace(
            MonitoringClient=FakeMonitoringClient,
            models=types.SimpleNamespace(SummarizeMetricsDataDetails=FakeDetails)),
        retry=types.SimpleNamespace(NoneRetryStrategy=FakeNoneRetryStrategy),
        config=types.SimpleNamespace(from_file=lambda: {}),
        exceptions=types.SimpleNamespace(ServiceError=FakeServiceError),
    )

    original = sys.modules.get("oci")
    oracle._clients.clear()
    sys.modules["oci"] = fake_oci
    try:
        oracle.collect({}, SECTION, now=NOW)
        oracle.collect({}, SECTION, now=NOW)

        assert len(calls["clients"]) == 1
        built = calls["clients"][0]
        assert isinstance(built["retry_strategy"], FakeNoneRetryStrategy)
        assert built["timeout"] == (10, 20)
        assert len(calls["details"]) > 0
        for details in calls["details"]:
            interval = details.query[details.query.index("[") + 1:details.query.index("]")]
            assert details.resolution == interval
            assert interval in ("5m", "1h")

        client = oracle._clients["instance_principal"]

        def raise_service_error(compartment_id, details):
            raise fake_oci.exceptions.ServiceError(404, "NotAuthorizedOrNotFound", {},
                                                    "authorizationFailed")

        client.summarize_metrics_data = raise_service_error
        try:
            oracle.collect({}, SECTION, now=NOW)
        except RuntimeError as e:
            assert str(e).startswith("OCI 404 NotAuthorizedOrNotFound:")
        else:
            raise AssertionError("expected RuntimeError")

        try:
            oracle.collect({}, dict(SECTION, auth="instance_principle"), now=NOW)
        except ValueError as e:
            assert "auth" in str(e)
        else:
            raise AssertionError("expected ValueError")
    finally:
        if original is not None:
            sys.modules["oci"] = original
        else:
            sys.modules.pop("oci", None)
        oracle._clients.clear()


if __name__ == "__main__":
    _run.run(globals())
