"""Sender.net transactional email through its REST API, as a Django email backend.

`EMAIL_PROVIDER=sender_net` selects this backend in production
(`config/settings/prod.py`). It is the final send boundary for the
secret-bearing messages Django sends itself (`outbox._send_email_via_provider`);
the Go email service speaks the same contract for the ordinary stream
(`backend/services/internal/email/sender_net.go`).

One message is one `POST https://api.sender.net/v2/message/send` with a bearer
API token. The answer is classified the way SMTP replies are:

* `400` and `422` say the message itself is invalid, so retrying cannot help:
  `SenderNetRejected` (permanent).
* Every other failure is `SenderNetUnavailable` (retryable within the outbox's
  bounded budget): `401`, `403` and `404` are configuration problems that must
  not burn messages, `408`, `429` and `5xx` are temporary, as are a timeout, a
  network error, a redirect, and a `2xx` whose JSON does not say
  `"success": true`.

Both exception types carry fixed text and the HTTP status only. Nothing here
logs, raises or stores the API token, a recipient, a subject or a body: the
body of a verification or delivery-code email is the code itself.

At-least-once, as with SMTP: the API offers no idempotency key, so a timeout
after Sender accepted a message can lead to one duplicate on retry.
"""

from __future__ import annotations

from email.header import decode_header, make_header
from email.utils import formataddr, parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

SENDER_NET_SEND_URL = "https://api.sender.net/v2/message/send"

#: Answers that name the message itself as invalid. Everything else retries.
_PERMANENT_STATUSES = frozenset({400, 422})


class SenderNetError(Exception):
    """A log-safe Sender.net failure: fixed text and the HTTP status, if any."""

    def __init__(self, reason: str, *, status: int = 0):
        self.reason = reason
        self.status = status
        text = f"Sender.net send failed: {reason}"
        if status:
            text = f"{text} (HTTP {status})"
        super().__init__(text)


class SenderNetRejected(SenderNetError):
    """Sender.net refused this message; sending it again cannot succeed."""


class SenderNetUnavailable(SenderNetError):
    """Sender.net did not accept the message this time; a retry may succeed."""


def _display_name(raw: str) -> str:
    """The readable form of an RFC 2047 encoded display name."""

    try:
        return str(make_header(decode_header(raw))).strip()
    except (UnicodeError, LookupError, ValueError):
        return raw.strip()


def _address(raw: str) -> tuple[str, str]:
    """`(name, email)` from one formatted address, refusing header tricks."""

    if not raw or "\r" in raw or "\n" in raw:
        raise SenderNetRejected("invalid address")
    name, email = parseaddr(raw)
    if "@" not in email:
        raise SenderNetRejected("invalid address")
    return _display_name(name), email


def build_payload(message) -> dict:
    """The JSON body for one `EmailMessage`, per Sender's documented contract.

    Only what the outbox sends is supported: one `to` recipient and no copies,
    a plain-text body with at most one HTML alternative, no attachments.
    Anything else is a programming error and is refused before the network.
    Other extra headers (the outbox's stable Message-ID) are not sent: the
    API's custom `headers` carry Reply-To only, and Sender assigns the
    Message-ID of what it delivers.
    """

    if len(message.to) != 1 or message.cc or message.bcc:
        raise SenderNetRejected("exactly one recipient is required")
    if message.attachments:
        raise SenderNetRejected("attachments are not supported")
    subject = str(message.subject or "")
    if not subject or "\r" in subject or "\n" in subject:
        raise SenderNetRejected("invalid subject")

    from_name, from_email = _address(str(message.from_email or ""))
    to_name, to_email = _address(str(message.to[0]))

    html = ""
    for content, mimetype in getattr(message, "alternatives", None) or ():
        if mimetype != "text/html" or html:
            raise SenderNetRejected("unsupported alternative")
        html = str(content)
    if message.content_subtype == "html":
        if html:
            raise SenderNetRejected("unsupported alternative")
        html, text = str(message.body), ""
    else:
        text = str(message.body or "")

    payload: dict = {
        "from": {
            "email": from_email,
            "name": from_name or str(getattr(settings, "EMAIL_FROM_NAME", "") or ""),
        },
        "to": {"email": to_email, **({"name": to_name} if to_name else {})},
        "subject": subject,
    }
    if text:
        payload["text"] = text
    if html:
        payload["html"] = html

    # Reply-To travels as a custom header, and only when it says something
    # From does not: the shipped configuration uses one address for both.
    reply_to = []
    for entry in message.reply_to or ():
        name, email = _address(str(entry))
        if email.casefold() != from_email.casefold():
            reply_to.append(formataddr((name, email)))
    if reply_to:
        payload["headers"] = {"Reply-To": ", ".join(reply_to)}
    return payload


def send_one(payload: dict, *, token: str, timeout: float) -> None:
    """POST one payload and classify the answer. Returns only on acceptance."""

    if not token:
        raise SenderNetUnavailable("API token is not configured")
    try:
        response = requests.post(
            SENDER_NET_SEND_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=(timeout, timeout),
            allow_redirects=False,
        )
    except requests.Timeout:
        raise SenderNetUnavailable("timeout") from None
    except requests.ConnectionError:
        raise SenderNetUnavailable("connection error") from None
    except (requests.RequestException, ValueError):
        raise SenderNetUnavailable("transport error") from None

    status = int(response.status_code)
    if 200 <= status < 300:
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if isinstance(answer, dict) and answer.get("success") is True:
            return
        raise SenderNetUnavailable("acceptance not confirmed", status=status)
    if status in _PERMANENT_STATUSES:
        raise SenderNetRejected("message refused", status=status)
    raise SenderNetUnavailable("provider unavailable", status=status)


class SenderNetEmailBackend(BaseEmailBackend):
    """Send each message with one Sender.net API call."""

    def send_messages(self, email_messages) -> int:
        token = str(getattr(settings, "SENDER_NET_API_TOKEN", "") or "")
        timeout = float(getattr(settings, "EMAIL_TIMEOUT", 10) or 10)
        sent = 0
        for message in email_messages or ():
            try:
                send_one(build_payload(message), token=token, timeout=timeout)
            except SenderNetError:
                if self.fail_silently:
                    continue
                raise
            sent += 1
        return sent
