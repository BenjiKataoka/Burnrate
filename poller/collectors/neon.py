"""Neon: current-period compute, transfer and storage from GET /projects/{id}."""
from collections.abc import Callable
from typing import Any

from fetch import get_json
from metric import Metric

SERVICE = "Neon"
ENV = ("NEON_API_KEY",)
REQUIRED = ("project_id",)
GB = 1e9  # decimal GB; confirmed against the Neon console in Task 6

METRICS = {
    "neon.compute_cu_hours": Metric("Compute", "CU-h", "max",
                                    "the database is suspended until next month", "monthly"),
    "neon.transfer_gb": Metric("Transfer", "GB", "max",
                               "the database is suspended until next month", "monthly"),
    "neon.storage_gb": Metric("Storage", "GB", "max", "writes fail"),
}


def collect(env: dict[str, str], section: dict,
            get: Callable[[str, dict[str, str]], Any] = get_json) -> dict[str, float]:
    body = get(f"https://console.neon.tech/api/v2/projects/{section['project_id']}",
               {"Authorization": f"Bearer {env['NEON_API_KEY']}"})
    p = body["project"]
    return {
        "neon.compute_cu_hours": round(float(p["compute_time_seconds"]) / 3600, 4),
        "neon.transfer_gb": round(float(p["data_transfer_bytes"]) / GB, 4),
        "neon.storage_gb": round(float(p["synthetic_storage_size"]) / GB, 4),
    }
