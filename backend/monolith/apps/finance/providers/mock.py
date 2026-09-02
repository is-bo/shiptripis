"""Deterministic in-process gateway for tests and local development.

This rail exists so the reconciliation, refund and webhook code paths can be
exercised without network access or provider credentials. It is not a
production adapter and the registry refuses to return it unless the deployment
has explicitly opted in — see `apps.finance.providers.__init__` and the
production settings guard.

It deliberately does **not** self-succeed. `create_checkout` returns a pending
session exactly like a real rail; a test must post a signed mock webhook, or
call `MockGateway.mark`, to move it. A provider that succeeds on creation is
precisely the footgun this phase is removing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from django.conf import settings

from .base import (
    MODE_TEST,
    AttemptSnapshot,
    CheckoutRequest,
    CheckoutResult,
    ProviderError,
    ProviderEvent,
    ProviderSignatureError,
    RefundRequest,
    RefundResult,
)

MOCK_WEBHOOK_SECRET = "mock-webhook-secret"


def sign_mock_webhook(raw_body: bytes, *, secret: str = MOCK_WEBHOOK_SECRET) -> str:
    """Produce the header a mock webhook must carry. Test helper."""

    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


class MockGateway:
    """A hosted-checkout rail whose outcomes are driven by the test."""

    name = "mock"
    supports_guest_payment = True
    payment_currency = "EUR"

    #: session id -> provider-side outcome, set by tests through `mark`.
    _outcomes: dict[str, str] = {}
    #: These dictionaries are deliberately independent from Django's database.
    #: A rolled-back application transaction therefore cannot erase the test
    #: provider's knowledge that it created a checkout, captured money or
    #: issued a refund.
    _checkouts: dict[str, CheckoutResult] = {}
    _sessions: dict[str, dict[str, int | str]] = {}
    _refunds: dict[str, RefundResult] = {}
    _refund_calls: dict[str, int] = {}

    def __init__(self, *, webhook_secret: str = MOCK_WEBHOOK_SECRET):
        self.webhook_secret = webhook_secret

    def credential_mode(self) -> str:
        """Always test. Production refuses to boot with this rail enabled."""

        return MODE_TEST

    def is_configured(self) -> bool:
        return bool(getattr(settings, "PAYMENTS_ALLOW_MOCK_PROVIDER", False))

    @classmethod
    def mark(cls, session_id: str, outcome: str) -> None:
        cls._outcomes[session_id] = outcome

    @classmethod
    def reset(cls) -> None:
        cls._outcomes.clear()
        cls._checkouts.clear()
        cls._sessions.clear()
        cls._refunds.clear()
        cls._refund_calls.clear()

    @classmethod
    def successful_funds_minor(
        cls,
        *,
        currency: str = "EUR",
        session_ids: "tuple[str, ...] | list[str] | None" = None,
    ) -> int:
        """What this rail believes it charged, independent of the database.

        Tests assert local accounting against this number. Because the amount
        comes from `_sessions` — written when the checkout was created and
        never touched by Django — a rolled-back application transaction cannot
        shrink it. A payment that vanished locally therefore shows up as a
        mismatch instead of agreeing with itself.

        `session_ids` narrows the sum to specific checkouts, which a test that
        loops over many scenarios on one shared rail needs.
        """

        if session_ids is None:
            candidates = list(cls._sessions.items())
        else:
            candidates = [
                (session_id, cls._sessions[session_id])
                for session_id in session_ids
                if session_id in cls._sessions
            ]
        return sum(
            int(snapshot["amount_minor"])
            for session_id, snapshot in candidates
            if snapshot["currency"] == currency
            and cls._outcomes.get(session_id) == "succeeded"
        )

    @classmethod
    def refund_count(cls, idempotency_key: str) -> int:
        """Number of distinct external refunds for one local obligation."""

        return int(idempotency_key in cls._refunds)

    @classmethod
    def refund_call_count(cls, idempotency_key: str) -> int:
        return cls._refund_calls.get(idempotency_key, 0)

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        existing = self._checkouts.get(request.idempotency_key)
        if existing is not None:
            return existing
        session_id = f"mock_cs_{secrets.token_hex(8)}"
        result = CheckoutResult(
            provider_session_id=session_id,
            checkout_url=f"https://mock.invalid/checkout/{session_id}",
            provider_status="pending",
            raw={"id": session_id, "amount": request.amount_minor},
        )
        self._checkouts[request.idempotency_key] = result
        self._sessions[session_id] = {
            "amount_minor": request.amount_minor,
            "currency": request.currency,
        }
        return result

    def fetch_attempt(
        self, *, provider_session_id: str, provider_payment_id: str
    ) -> AttemptSnapshot:
        """Report the outcome and the amount, exactly as a real rail does.

        A real provider knows what it charged, and reconciliation refuses a
        success it cannot verify against that number. The test double therefore
        has to answer with the amount too — reading it back from the attempt is
        the honest stand-in for the provider's own record.
        """

        outcome = self._outcomes.get(provider_session_id, "ignored")
        snapshot = self._sessions.get(provider_session_id)
        return AttemptSnapshot(
            outcome=outcome,
            provider_payment_id=provider_payment_id or f"{provider_session_id}_pi",
            amount_minor=int(snapshot["amount_minor"]) if snapshot else None,
            currency=str(snapshot["currency"]) if snapshot else "",
        )

    def refund(self, request: RefundRequest) -> RefundResult:
        if not request.provider_payment_id and not request.provider_session_id:
            raise ProviderError("A mock refund needs a provider handle.")
        self._refund_calls[request.idempotency_key] = (
            self._refund_calls.get(request.idempotency_key, 0) + 1
        )
        existing = self._refunds.get(request.idempotency_key)
        if existing is not None:
            return existing
        result = RefundResult(
            provider_refund_id=f"mock_re_{secrets.token_hex(8)}",
            succeeded=True,
        )
        self._refunds[request.idempotency_key] = result
        return result

    def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> ProviderEvent:
        signature = headers.get("x-mock-signature", "").strip()
        # Same hex guard as the real adapters: `hmac.compare_digest` raises
        # TypeError on a non-ASCII string, and a signature check must fail as a
        # signature check, never as a 500.
        if not signature or not all(c in "0123456789abcdefABCDEF" for c in signature):
            raise ProviderSignatureError("Mock webhook signature is malformed.")
        expected = sign_mock_webhook(raw_body, secret=self.webhook_secret)
        if not hmac.compare_digest(expected, signature):
            raise ProviderSignatureError("Mock webhook signature did not match.")
        try:
            event = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProviderSignatureError("Mock webhook body is not valid JSON.") from exc
        if not isinstance(event, dict) or not event.get("id"):
            raise ProviderSignatureError("Mock webhook carries no event id.")
        data = event.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        return ProviderEvent(
            provider=self.name,
            event_id=str(event["id"]),
            event_type=str(event.get("type") or ""),
            outcome=str(event.get("outcome") or "ignored"),
            provider_session_id=str(data.get("session_id") or ""),
            provider_payment_id=str(data.get("payment_id") or ""),
            reference=str(data.get("reference") or ""),
            amount_minor=data.get("amount"),
            currency=str(data.get("currency") or "EUR").upper(),
            guest_email=str(data.get("guest_email") or ""),
            failure_code=str(data.get("failure_code") or ""),
            payload={"id": event["id"], "type": event.get("type")},
        )
