"""One refusal type for discovery: a stable machine code, a sentence, a status."""

from __future__ import annotations


class DiscoveryError(ValueError):
    def __init__(self, code: str, detail: str, *, status: int = 400):
        super().__init__(detail)
        self.code = code
        self.status = status
