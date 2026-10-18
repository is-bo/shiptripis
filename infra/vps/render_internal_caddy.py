"""Retain all Railway routes while trusting the VPS edge's sanitized client IP.

This runs at image build time. The gateway listener is never host-published.
"""
from pathlib import Path

def render(config):
    anchor = "\tauto_https off\n"
    if config.count(anchor) != 1:
        raise RuntimeError("review the shared Caddy global block before building VPS image")
    config = config.replace(anchor, anchor + "\tservers {\n\t\ttrusted_proxies static private_ranges\n\t}\n", 1)
    policy = '\t\tReferrer-Policy "strict-origin-when-cross-origin"'
    if config.count(policy) != 1:
        raise RuntimeError("review the shared Caddy referrer policy before building VPS image")
    # Capability/account pages supply no-referrer. Apply the generic policy
    # only when the application did not supply its own, at both proxy layers.
    return config.replace(policy, policy.replace("Referrer-Policy", "?Referrer-Policy"), 1)


if __name__ == "__main__":
    path = Path("/etc/caddy/Caddyfile")
    path.write_text(render(path.read_text()))
