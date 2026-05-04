import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

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
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.SENDER)

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
        if not self.is_active():
            return False
        ok = check_password(plaintext, self.code_hash)
        self.attempts += 1
        if ok:
            self.used_at = timezone.now()
        self.save(update_fields=("attempts", "used_at"))
        return ok
