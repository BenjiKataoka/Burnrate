"""Fake services, configs and stores shared by the poll, alert and API tests."""
import _run  # noqa: F401  (puts poller/ on sys.path)
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from config import Config
from levels import Thresholds
from metric import Metric
from store import Store


def service(name: str, metrics: dict[str, Metric], collect: Callable) -> SimpleNamespace:
    return SimpleNamespace(SERVICE=name, ENV=(), REQUIRED=(), METRICS=metrics, collect=collect)


def config(registry: dict, limits: dict[str, float], env: dict | None = None) -> Config:
    return Config(interval_s=900, db_path=str(Path(tempfile.mkdtemp()) / "t.db"),
                  host="127.0.0.1", port=0, thresholds=Thresholds(), fail_alert_after=4,
                  services={name: {} for name in registry}, limits=limits, env=env or {})


def store() -> Store:
    return Store(str(Path(tempfile.mkdtemp()) / "t.db"))
