"""Retain all Railway routes while trusting the VPS edge's sanitized client IP.

This runs at image build time. The gateway listener is never host-published.
"""
from pathlib import Path

path = Path("/etc/caddy/Caddyfile")
config = path.read_text()
anchor = "\tauto_https off\n"
if config.count(anchor) != 1:
    raise RuntimeError("review the shared Caddy global block before building VPS image")
config = config.replace(anchor, anchor + "\tservers {\n\t\ttrusted_proxies static private_ranges\n\t}\n", 1)
path.write_text(config)
