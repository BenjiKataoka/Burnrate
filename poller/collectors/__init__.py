"""Every service the poller knows. A service is enabled by giving it a section in config.toml."""
from collectors import neon

REGISTRY = {"neon": neon}
