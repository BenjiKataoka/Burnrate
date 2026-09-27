"""Every service the poller knows. A service is enabled by giving it a section in config.toml."""
from collectors import clerk, neon, oracle, vercel

REGISTRY = {"neon": neon, "oracle": oracle, "clerk": clerk, "vercel": vercel}
