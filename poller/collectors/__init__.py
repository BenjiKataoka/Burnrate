"""Every service the poller knows. A service is enabled by giving it a section in config.toml."""
from collectors import clerk, neon

REGISTRY = {"neon": neon, "clerk": clerk}
