"""Deployment money intent. Pure validation; no provider calls or secret output."""

from urllib.parse import urlsplit

from .connect import credential_mode


class PaymentConfigurationError(RuntimeError):
    pass


def payment_mode(config):
    mode = getattr(config, "PAYMENTS_ENVIRONMENT", "test")
    if mode not in ("test", "live"):
        raise PaymentConfigurationError("PAYMENTS_ENVIRONMENT must be test or live.")
    return mode


def validate_payment_configuration(config):
    mode = payment_mode(config)
    stripe = getattr(config, "STRIPE_SECRET_KEY", "")
    chargily = getattr(config, "CHARGILY_SECRET_KEY", "")
    if stripe:
        if credential_mode(stripe) != mode:
            raise PaymentConfigurationError(
                "STRIPE_SECRET_KEY contradicts PAYMENTS_ENVIRONMENT."
            )
        if (
            getattr(config, "STRIPE_API_BASE", "").rstrip("/")
            != "https://api.stripe.com"
        ):
            raise PaymentConfigurationError(
                "STRIPE_API_BASE must use the Stripe API origin."
            )
    if chargily:
        if not chargily.startswith(mode + "_sk_"):
            raise PaymentConfigurationError(
                "CHARGILY_SECRET_KEY contradicts PAYMENTS_ENVIRONMENT."
            )
        path = "/test/api/v2" if mode == "test" else "/api/v2"
        if (
            getattr(config, "CHARGILY_API_BASE", "").rstrip("/")
            != "https://pay.chargily.net" + path
        ):
            raise PaymentConfigurationError(
                "CHARGILY_API_BASE contradicts PAYMENTS_ENVIRONMENT."
            )
        secret = getattr(config, "CHARGILY_WEBHOOK_SECRET", "")
        if secret and secret != chargily:
            raise PaymentConfigurationError(
                "CHARGILY_WEBHOOK_SECRET must match the API signing key or be empty."
            )
    if getattr(config, "STRIPE_CONNECT_ENABLED", False):
        if getattr(config, "STRIPE_CONNECT_EXPECTED_MODE", "test") != mode:
            raise PaymentConfigurationError(
                "STRIPE_CONNECT_EXPECTED_MODE contradicts PAYMENTS_ENVIRONMENT."
            )
        if getattr(config, "STRIPE_WEBHOOK_SECRET", "") == getattr(
            config, "STRIPE_CONNECT_WEBHOOK_SECRET", ""
        ):
            raise PaymentConfigurationError(
                "Stripe platform and Connect require separate signing secrets."
            )
    if mode == "live":
        if not getattr(config, "PAYOUT_PROFILES_ENABLED", False):
            raise PaymentConfigurationError(
                "LIVE requires PAYOUT_PROFILES_ENABLED for frozen payout routing."
            )
        if not stripe and not chargily:
            raise PaymentConfigurationError(
                "LIVE requires a configured payment provider."
            )
        if not getattr(config, "TRANSACTIONAL_EMAIL_ENABLED", False):
            raise PaymentConfigurationError(
                "LIVE requires EMAIL_ENABLED for verification and recipient delivery codes."
            )
        origin = urlsplit(getattr(config, "PAYMENTS_PUBLIC_BASE_URL", ""))
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
            or origin.hostname in ("localhost", "127.0.0.1", "::1")
            or origin.hostname.endswith((".invalid", ".localhost", ".test"))
        ):
            raise PaymentConfigurationError(
                "LIVE requires a public HTTPS PAYMENTS_PUBLIC_BASE_URL origin."
            )
        if getattr(config, "FRONTEND_BASE_URL", "").rstrip("/") != getattr(
            config, "PAYMENTS_PUBLIC_BASE_URL", ""
        ).rstrip("/"):
            raise PaymentConfigurationError(
                "FRONTEND_BASE_URL must match PAYMENTS_PUBLIC_BASE_URL for this hosted deployment."
            )
