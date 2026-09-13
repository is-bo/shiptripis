"""Boot-time validation for the H2 Stripe Connect configuration.

Kept out of `prod.py` and out of the finance app on purpose. `prod.py` runs
before Django's app registry exists, so this module imports nothing from
`apps.*`; and a pure function is something tests can attack directly with
dozens of bad configurations instead of booting a subprocess for each one.

Nothing here reads a secret's *value* beyond the documented `sk_test_` /
`sk_live_` prefix that says which rail it points at. Error messages name
variables, never contents.
"""

from __future__ import annotations

from urllib.parse import urlparse

#: H0's country safety ceiling. `STRIPE_CONNECT_ALLOWED_COUNTRIES` is the
#: deployment's own list; the ceiling is what this architecture has decided may
#: ever appear in it. Widening it is an architecture change, not a config edit.
CONNECT_COUNTRY_CEILING = ("FR", "DE", "ES")

#: The pinned contract for the Connect adapter and both Connect event
#: destinations. A different value is allowed but must be deliberate.
PINNED_CONNECT_API_VERSION = "2026-03-25.dahlia"

VALID_MODES = ("test", "live")


class ConnectConfigurationError(RuntimeError):
    """A Connect configuration that must not be allowed to serve traffic."""


def credential_mode(secret_key: str) -> str:
    """Which rail a Stripe key points at, from its documented prefix alone."""

    if not secret_key:
        return "not_configured"
    if secret_key.startswith(("sk_test_", "rk_test_")):
        return "test"
    if secret_key.startswith(("sk_live_", "rk_live_")):
        return "live"
    return "unknown"


def normalise_countries(values) -> tuple:
    """Uppercase, de-duplicated, ceiling-checked ISO country codes."""

    seen = []
    for value in values or ():
        code = str(value).strip().upper()
        if not code:
            continue
        if code not in seen:
            seen.append(code)
    return tuple(seen)


def _hosted_return_url(name: str, value: str, base: str) -> None:
    """A server-owned HTTPS URL on this deployment's own public origin.

    Stripe sends the Traveler's browser here after onboarding. Accepting an
    arbitrary origin would make the platform's own configuration the open
    redirect, so the check is origin equality against
    `PAYMENTS_PUBLIC_BASE_URL`, not a pattern match.
    """

    parsed = urlparse(value)
    try:
        parsed.port
    except ValueError as exc:
        raise ConnectConfigurationError(f"{name} has an invalid port.") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConnectConfigurationError(f"{name} must be an https:// URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ConnectConfigurationError(f"{name} must not carry credentials.")
    if parsed.query or parsed.fragment:
        raise ConnectConfigurationError(f"{name} must not carry a query or fragment.")
    origin = urlparse(base)
    if (origin.scheme, origin.hostname, origin.port) != (
        parsed.scheme,
        parsed.hostname,
        parsed.port,
    ):
        raise ConnectConfigurationError(
            f"{name} must be on the PAYMENTS_PUBLIC_BASE_URL origin."
        )


def validate_connect_configuration(
    *,
    enabled: bool,
    expected_mode: str,
    platform_account_id: str,
    api_version: str,
    webhook_secret: str,
    allowed_countries,
    return_url: str,
    refresh_url: str,
    public_base_url: str,
    stripe_secret_key: str,
    payouts_enabled: bool = False,
    non_stripe_funding_enabled: bool = False,
    payment_environment: str = "test",
) -> None:
    """Refuse a Connect configuration that could act on the wrong rail.

    Called with the flag off too, because two of these rules apply regardless:
    the country list may never exceed the architecture ceiling, and the
    non-Stripe funding facility — which is neither approved nor implemented —
    may never be on.
    """

    countries = normalise_countries(allowed_countries)
    outside = [code for code in countries if code not in CONNECT_COUNTRY_CEILING]
    if outside:
        raise ConnectConfigurationError(
            "STRIPE_CONNECT_ALLOWED_COUNTRIES may only contain "
            + ", ".join(CONNECT_COUNTRY_CEILING)
            + f"; refused {', '.join(outside)}."
        )
    if payouts_enabled:
        # H3 implements automatic EUR execution, so this flag is no longer
        # refused outright. What it still refuses is the two configurations
        # that would make it dangerous: execution without the onboarding and
        # readiness layer it depends on, and execution without H8A's explicit
        # deployment payment intent. Setting that intent belongs to H8B.
        if not enabled:
            raise ConnectConfigurationError(
                "STRIPE_CONNECT_PAYOUTS_ENABLED requires STRIPE_CONNECT_ENABLED; "
                "payout execution cannot run without Connect onboarding."
            )
        if expected_mode not in VALID_MODES or expected_mode != payment_environment:
            raise ConnectConfigurationError(
                "STRIPE_CONNECT_PAYOUTS_ENABLED requires matching explicit "
                "PAYMENTS_ENVIRONMENT; TEST is the default."
            )
    if non_stripe_funding_enabled:
        raise ConnectConfigurationError(
            "STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED must be false; the "
            "funding facility it describes is not approved or implemented."
        )
    if not enabled:
        # Everything below is only meaningful once the deployment intends to
        # create Connect objects. With the flag off no secret is required and
        # existing production behaviour is untouched.
        return

    if expected_mode not in VALID_MODES:
        raise ConnectConfigurationError(
            "STRIPE_CONNECT_EXPECTED_MODE must be 'test' or 'live'."
        )
    if not platform_account_id.startswith("acct_"):
        raise ConnectConfigurationError(
            "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID must be the platform's acct_ id."
        )
    if not api_version:
        raise ConnectConfigurationError(
            "STRIPE_CONNECT_API_VERSION must pin an explicit Stripe API version."
        )
    if not webhook_secret.startswith("whsec_"):
        raise ConnectConfigurationError(
            "STRIPE_CONNECT_WEBHOOK_SECRET must be the connected-accounts "
            "endpoint's own signing secret."
        )
    if not stripe_secret_key:
        raise ConnectConfigurationError(
            "STRIPE_SECRET_KEY is required when STRIPE_CONNECT_ENABLED is true."
        )
    mode = credential_mode(stripe_secret_key)
    if mode != expected_mode:
        # The whole point of an expected mode is that a key swap cannot quietly
        # move onboarding onto real money, or leave a live deployment creating
        # test accounts nobody can be paid through.
        raise ConnectConfigurationError(
            "STRIPE_CONNECT_EXPECTED_MODE does not match the mode of the "
            f"configured Stripe credential (expected {expected_mode!r})."
        )
    if not public_base_url:
        raise ConnectConfigurationError(
            "PAYMENTS_PUBLIC_BASE_URL is required for Connect onboarding returns."
        )
    _hosted_return_url(
        "STRIPE_CONNECT_ONBOARDING_RETURN_URL", return_url, public_base_url
    )
    _hosted_return_url(
        "STRIPE_CONNECT_ONBOARDING_REFRESH_URL", refresh_url, public_base_url
    )
    if return_url == refresh_url:
        raise ConnectConfigurationError(
            "STRIPE_CONNECT_ONBOARDING_RETURN_URL and "
            "STRIPE_CONNECT_ONBOARDING_REFRESH_URL must be different routes."
        )


def validate_from_settings(settings_module) -> None:
    """Adapter for a Django settings namespace (module or object)."""

    def value(name, default=None):
        return getattr(settings_module, name, default)

    validate_connect_configuration(
        enabled=bool(value("STRIPE_CONNECT_ENABLED", False)),
        expected_mode=str(value("STRIPE_CONNECT_EXPECTED_MODE", "test") or ""),
        platform_account_id=str(value("STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or ""),
        api_version=str(value("STRIPE_CONNECT_API_VERSION", "") or ""),
        webhook_secret=str(value("STRIPE_CONNECT_WEBHOOK_SECRET", "") or ""),
        allowed_countries=value("STRIPE_CONNECT_ALLOWED_COUNTRIES", ()),
        return_url=str(value("STRIPE_CONNECT_ONBOARDING_RETURN_URL", "") or ""),
        refresh_url=str(value("STRIPE_CONNECT_ONBOARDING_REFRESH_URL", "") or ""),
        public_base_url=str(value("PAYMENTS_PUBLIC_BASE_URL", "") or ""),
        stripe_secret_key=str(value("STRIPE_SECRET_KEY", "") or ""),
        payouts_enabled=bool(value("STRIPE_CONNECT_PAYOUTS_ENABLED", False)),
        payment_environment=value("PAYMENTS_ENVIRONMENT", "test"),
        non_stripe_funding_enabled=bool(
            value("STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED", False)
        ),
    )
