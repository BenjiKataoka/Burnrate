"""Loads config.toml and the environment, and refuses to start on anything missing or unsafe."""
import ipaddress
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from levels import Thresholds


class ConfigError(Exception):
    pass


@dataclass
class Config:
    interval_s: int
    db_path: str
    host: str
    port: int
    thresholds: Thresholds
    fail_alert_after: int
    services: dict[str, dict]      # enabled services: their config.toml sections
    limits: dict[str, float]       # full metric name -> limit
    env: dict[str, str]


WEBHOOK_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")
LOOPBACK_NET = ipaddress.ip_network("127.0.0.0/8")
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")  # CGNAT range, not a real address; scan:allow


def _setting(poller: dict, key: str, default: float, low: float, high: float) -> float:
    """Validate a numeric setting, raising ConfigError on bad types or out-of-range values."""
    value = poller.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ConfigError(f"[poller] {key} must be a number from {low:g} to {high:g}")
    return float(value)


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=value lines. The poller reads this file itself; the systemd unit has no
    EnvironmentFile, so this is the only parser and the only place secrets are read from."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_config(path: Path, registry: dict[str, ModuleType], env: dict[str, str],
                serving: bool) -> Config:
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"{path} not found; copy config.example.toml to config.toml") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None

    poller = raw.pop("poller", {})
    if not isinstance(poller, dict):
        raise ConfigError("[poller] must be a table")
    unknown = [name for name in raw if name not in registry]
    if unknown:
        raise ConfigError(f"unknown service in config: {', '.join(unknown)} "
                          f"(known: {', '.join(registry)})")
    if not raw:
        raise ConfigError("no services enabled; add at least one [service] section")

    limits: dict[str, float] = {}
    for name, section in raw.items():
        if not isinstance(section, dict):
            raise ConfigError(f"[{name}] must be a table")
        mod = registry[name]
        for key in mod.REQUIRED:
            if not section.get(key):
                raise ConfigError(f"[{name}] {key} is not set")
        for var in mod.ENV:
            if not env.get(var):
                raise ConfigError(f"{var} is not set (needed by {name})")
        given = section.get("limits", {})
        if not isinstance(given, dict):
            raise ConfigError(f"[{name}.limits] must be a table of numbers")
        for metric in mod.METRICS:
            short = metric.split(".", 1)[1]
            value = given.get(short)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ConfigError(f"[{name}.limits] {short} must be a positive number")
            limits[metric] = float(value)

    host, sep, port = str(poller.get("listen", "127.0.0.1:8787")).rpartition(":")
    if not sep or not port.isdigit():
        raise ConfigError("[poller] listen must look like 127.0.0.1:8787")
    port_int = int(port)
    if not 1 <= port_int <= 65535:
        raise ConfigError("[poller] listen port must be 1 to 65535")
    if host != "localhost":
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        allowed = isinstance(ip, ipaddress.IPv4Address) and (
            ip in LOOPBACK_NET or ip in TAILSCALE_NET)
        if not allowed:
            raise ConfigError("listen host must be 127.0.0.1 or a Tailscale address "
                              "(100.64.0.0/10)")  # scan:allow

    if serving:
        if len(env.get("BURNRATE_TOKEN", "")) < 32:
            raise ConfigError("BURNRATE_TOKEN must be at least 32 characters; make one with: "
                              "python3 -c 'import secrets; print(secrets.token_urlsafe(32))'")
        if not env.get("DISCORD_WEBHOOK_URL", "").startswith(WEBHOOK_PREFIXES):
            raise ConfigError("DISCORD_WEBHOOK_URL must be a https://discord.com/api/webhooks/ URL")

    interval = int(_setting(poller, "interval_minutes", 15, 5, 60))
    warn_at = _setting(poller, "warn_at", 0.80, 0, 1)
    warn_clear = _setting(poller, "warn_clear", 0.75, 0, 1)
    crit_clear = _setting(poller, "crit_clear", 0.95, 0, 1)
    fail_alert_after = int(_setting(poller, "fail_alert_after", 4, 1, 100))
    t = Thresholds(warn_at, warn_clear, crit_clear)
    if not 0 < t.warn_clear < t.warn_at < t.crit_clear < 1:
        raise ConfigError("thresholds must satisfy 0 < warn_clear < warn_at < crit_clear < 1")

    return Config(interval_s=interval * 60, db_path=str(poller.get("db_path", "burnrate.db")),
                  host=host, port=port_int, thresholds=t,
                  fail_alert_after=fail_alert_after,
                  services=raw, limits=limits, env=env)
