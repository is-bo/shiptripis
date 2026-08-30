import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.utils import timezone

from apps.core.languages import CommunicationLanguage

from .wilayas import WILAYA_CHOICES


class User(AbstractUser):
    class Role(models.TextChoices):
        SENDER = "sender", "Sender"
        TRAVELER = "traveler", "Traveler"
        BOTH = "both", "Both"
        ADMIN = "admin", "Admin"

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    wilaya = models.CharField(max_length=2, choices=WILAYA_CHOICES, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.BOTH)
    preferred_language = models.CharField(
        max_length=2,
        choices=CommunicationLanguage.choices,
        blank=True,
        default="",
        help_text=(
            "Durable communication preference. Blank is a legacy/unselected "
            "value and resolves to English when an outbound message is queued."
        ),
    )

    is_phone_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    is_kyc_verified = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False, db_index=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self) -> str:
        return self.email


class OAuthIdentity(models.Model):
    """Maps a third-party account (Google sub, Apple sub, ...) to a User."""

    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"
        APPLE = "apple", "Apple"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_identities",
    )
    provider = models.CharField(max_length=16, choices=Provider.choices)
    # Stable provider-side user id (Google `sub`, Apple `sub`).
    subject = models.CharField(max_length=128)
    email_at_link = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "subject"),
                name="oauthidentity_provider_subject_unique",
            ),
        ]
        indexes = [models.Index(fields=("user", "provider"))]


class PasswordResetCode(models.Model):
    """Argon2-hashed 6-digit code with attempt counter and TTL."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_codes",
    )
    code_hash = models.CharField(max_length=200)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("user", "used_at", "expires_at"))]

    @classmethod
    def issue(cls, user: "User") -> tuple["PasswordResetCode", str]:
        plaintext = f"{secrets.randbelow(1_000_000):06d}"
        ttl = timedelta(seconds=settings.PASSWORD_RESET_CODE_TTL_SECONDS)
        obj = cls.objects.create(
            user=user,
            code_hash=make_password(plaintext),
            expires_at=timezone.now() + ttl,
        )
        return obj, plaintext

    def is_active(self) -> bool:
        return (
            self.used_at is None
            and self.expires_at > timezone.now()
            and self.attempts < settings.PASSWORD_RESET_MAX_ATTEMPTS
        )

    def verify(self, plaintext: str) -> bool:
        # The attempt budget is a security boundary. Refetch under a row lock
        # so concurrent guesses cannot both observe the same remaining slot.
        with transaction.atomic():
            current = type(self).objects.select_for_update().get(pk=self.pk)
            if not current.is_active():
                return False
            ok = check_password(plaintext, current.code_hash)
            current.attempts += 1
            if ok:
                current.used_at = timezone.now()
            current.save(update_fields=("attempts", "used_at"))
            self.attempts = current.attempts
            self.used_at = current.used_at
            return ok


class EmailVerificationCode(models.Model):
    """Argon2-hashed 6-digit signup-verification code — a near-clone of
    PasswordResetCode. Django owns generation + verification; the Go
    email-service only transports the rendered message."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_verification_codes",
    )
    code_hash = models.CharField(max_length=200)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("user", "used_at", "expires_at"))]

    @classmethod
    def issue(cls, user: "User") -> tuple["EmailVerificationCode", str]:
        plaintext = f"{secrets.randbelow(1_000_000):06d}"
        ttl = timedelta(seconds=settings.EMAIL_VERIFY_CODE_TTL_SECONDS)
        obj = cls.objects.create(
            user=user,
            code_hash=make_password(plaintext),
            expires_at=timezone.now() + ttl,
        )
        return obj, plaintext

    def is_active(self) -> bool:
        return (
            self.used_at is None
            and self.expires_at > timezone.now()
            and self.attempts < settings.EMAIL_VERIFY_MAX_ATTEMPTS
        )

    def verify(self, plaintext: str) -> bool:
        with transaction.atomic():
            current = type(self).objects.select_for_update().get(pk=self.pk)
            if not current.is_active():
                return False
            ok = check_password(plaintext, current.code_hash)
            current.attempts += 1
            if ok:
                current.used_at = timezone.now()
            current.save(update_fields=("attempts", "used_at"))
            self.attempts = current.attempts
            self.used_at = current.used_at
            return ok
