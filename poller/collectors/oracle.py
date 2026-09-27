"""Oracle A1: the three inputs to Oracle's idle-reclamation rule, and outbound transfer.

Oracle may reclaim an Always Free VM only when CPU (95th percentile), memory and network
all stay under 20% for 7 days, so the VM is safe while the busiest of the three is above
the floor. That busiest value is the idle guard, the only Oracle metric that alerts.
"""
import math
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from metric import Metric

SERVICE = "Oracle"
ENV = ()
REQUIRED = ("compartment_id", "instance_id", "network_gbps")
STEP_S = 300  # 5-minute data: 1-minute data is not guaranteed across a 7-day window
INSTANCE_ID_RE = re.compile(r"ocid1\.instance\.[a-z0-9._-]+")
Series = Callable[[str, datetime, datetime], list[float]]
_clients: dict[str, object] = {}  # one MonitoringClient per auth mode, built on first use

METRICS = {
    "oracle.idle_guard": Metric("Idle guard", "%", "min", "Oracle can reclaim the VM", "rolling"),
    "oracle.cpu_p95": Metric("CPU p95", "%", "min", "", "rolling", support=True),
    "oracle.memory": Metric("Memory", "%", "min", "", "rolling", support=True),
    "oracle.network": Metric("Network", "%", "min", "", "rolling", support=True),
    "oracle.outbound_tb": Metric("Outbound", "TB", "max",
                                 "Oracle charges for or throttles transfer", "monthly"),
}


def _nonempty(name: str, values: list[float]) -> list[float]:
    if not values:
        raise ValueError(f"no {name} data for this instance")
    return values


def collect(env: dict[str, str], section: dict, series: Series | None = None,
            now: datetime | None = None) -> dict[str, float]:
    if not INSTANCE_ID_RE.fullmatch(section["instance_id"]):
        raise ValueError("[oracle] instance_id does not look like an instance OCID")
    try:
        network_gbps = float(section["network_gbps"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("[oracle] network_gbps must be a positive number") from None
    if network_gbps <= 0:
        raise ValueError("[oracle] network_gbps must be a positive number")

    series = series or _sdk_series(section)
    now = now or datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rid = f'{{resourceId = "{section["instance_id"]}"}}'

    cpu = sorted(_nonempty("CpuUtilization", series(f"CpuUtilization[5m]{rid}.mean()", week, now)))
    cpu_p95 = cpu[max(0, math.ceil(0.95 * len(cpu)) - 1)]  # nearest-rank percentile
    mem = _nonempty("MemoryUtilization", series(f"MemoryUtilization[5m]{rid}.mean()", week, now))
    # ponytail: network % = average rate over the link speed; Oracle does not publish its
    # exact formula, so this is checked against the console's graphs in Task 13.
    link_bits = network_gbps * 1e9
    net = 0.0
    for name in ("NetworksBytesIn", "NetworksBytesOut"):
        per_step = _nonempty(name, series(f"{name}[5m]{rid}.sum()", week, now))
        net = max(net, sum(per_step) / len(per_step) / STEP_S * 8 / link_bits * 100)
    outbound = series(f"NetworksBytesOut[1h]{rid}.sum()", month, now)

    memory = sum(mem) / len(mem)
    return {
        "oracle.cpu_p95": round(cpu_p95, 2),
        "oracle.memory": round(memory, 2),
        "oracle.network": round(net, 4),
        "oracle.idle_guard": round(max(cpu_p95, memory, net), 2),
        "oracle.outbound_tb": round(sum(outbound) / 1e12, 6),
    }


def _sdk_series(section: dict) -> Series:
    import oci  # only needed on a machine that polls Oracle; tests never import it

    auth = section.get("auth", "instance_principal")
    if auth not in ("instance_principal", "config_file"):
        raise ValueError('[oracle] auth must be "instance_principal" or "config_file"')

    client = _clients.get(auth)
    if client is None:
        # ponytail: only this first build pays the SDK's own IMDS-certificate and federation
        # retries; every later poll reuses the cached client and the signer refreshes its own
        # token, so a failed query fails fast instead of stalling the sequential poll loop.
        if auth == "instance_principal":
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            client = oci.monitoring.MonitoringClient(
                config={"region": signer.region}, signer=signer, timeout=(10, 20),
                retry_strategy=oci.retry.NoneRetryStrategy())
        else:
            client = oci.monitoring.MonitoringClient(
                oci.config.from_file(), timeout=(10, 20),
                retry_strategy=oci.retry.NoneRetryStrategy())
        _clients[auth] = client

    def series(query: str, start: datetime, end: datetime) -> list[float]:
        interval = query[query.index("[") + 1:query.index("]")]
        details = oci.monitoring.models.SummarizeMetricsDataDetails(
            namespace="oci_computeagent", query=query, start_time=start, end_time=end,
            resolution=interval)
        try:
            data = client.summarize_metrics_data(section["compartment_id"], details).data
        except oci.exceptions.ServiceError as e:
            raise RuntimeError(f"OCI {e.status} {e.code}: {e.message}") from None
        return [p.value for item in data for p in item.aggregated_datapoints]

    return series
