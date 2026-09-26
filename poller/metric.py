"""What a collector reports about each metric; the poller and the API read it, never write it."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Metric:
    label: str                         # shown after the service name, e.g. "Storage"
    unit: str                          # "GB", "%", "" for counts
    dir: Literal["max", "min"]         # max: trouble when high; min: trouble when low
    at_limit: str                      # what happens at the limit, e.g. "writes fail"
    resets: Literal["never", "monthly", "rolling"] = "never"
    support: bool = False              # shown, never alerted on (inputs to Oracle's idle guard)
