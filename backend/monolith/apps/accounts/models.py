import secrets
import uuid
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
    #: When the member deleted their account (`apps.accounts.deletion`). The
    #: row stays, emptied, because deliveries and payments point at it.
    deleted_at = models.DateTimeField(null=True, blank=True)
    #: How many times every sign-in of the account was ended at once
    #: (`apps.accounts.sessions.end_all_sessions`). A sign-in is issued only
    #: while the count is still the one its credentials were checked under.
    session_epoch = models.PositiveIntegerField(default=0)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self) -> str:
        return self.email

    def fill_blank_name(self, name: str) -> bool:
        """Set ``name`` only while the stored name is blank; True if it was set.

        A name is set once (plan EGS review): by the member through
        `PATCH /api/me`, or by Google or Apple at a later sign-in, whichever
        comes first. One conditional UPDATE decides, so of two concurrent
        writers only one can win, whatever this instance says.
        """

        if not name:
            return False
        filled = User.objects.filter(pk=self.pk, full_name__regex=r"^\s*$").update(
            full_name=name
        )
        if filled:
            self.full_name = name
        return bool(filled)


class SignInSession(models.Model):
    """One sign-in, from the moment its tokens are issued until it ends.

    Its id is the ``sid`` claim of every token the sign-in produces: the first
    refresh and access tokens, and every pair a refresh rotates into. It ends
    with its own sign-out, or with every other sign-in of the account when the
    account changes hands (`apps.accounts.sessions.end_all_sessions`), and an
    ended sign-in never comes back. A refresh and a push registration both
    require the sign-in to be live, so no token can outlive the sign-in it
    came from, however it was rotated (`apps.notifications.push`).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sign_in_sessions",
    )
    created_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_sign_in_session"

    def __str__(self) -> str:
        return f"SignInSession({self.user_id}, {self.pk})"

    @classmethod
    def live(cls, *, user_id, session_id) -> "SignInSession | None":
        """The live sign-in ``session_id`` (a token's ``sid``) of ``user_id``.

        None when the claim is missing or malformed, names another account's
        sign-in, or names one that has ended.
        """

        try:
            pk = uuid.UUID(str(session_id))
        except (TypeError, ValueError, AttributeError):
            return None
        return cls.objects.filter(
            pk=pk, user_id=user_id, ended_at__isnull=True
        ).first()


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


class ProfilePhoto(models.Model):
    """A member's one optional profile photo (spec 21; `apps.accounts.photos`).

    The stored object is the server's own re-encoding (a 512 px square JPEG
    with no metadata) under a random key that never contains the user id.
    `version` is random and changes with every upload: the app caches the
    image by it, and a staff removal names the version it was looking at, so a
    replacement that arrives meanwhile is never removed unseen.

    A photo is visible from the moment it is stored. Staff removal keeps the
    row (`removed`, with the reason the member is shown) and deletes the
    object; the member may upload a new photo, which replaces the row's
    contents.
    """

    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        REMOVED = "removed", "Removed by Wassla"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile_photo",
    )
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    #: The bucket the object was written to, so it resolves to the credential
    #: that can read it (`apps.core.storage.store_for_bucket`). Blank once the
    #: object is gone.
    bucket = models.CharField(max_length=128, blank=True)
    object_key = models.CharField(max_length=256, blank=True)
    bytes = models.PositiveIntegerField(default=0)
    version = models.CharField(max_length=32)
    uploaded_at = models.DateTimeField()
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    #: Written by staff; the member is shown it.
    removed_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "accounts_profile_photo"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(state="active", removed_at__isnull=True)
                    & ~models.Q(object_key="")
                )
                | (
                    models.Q(state="removed", removed_at__isnull=False, object_key="")
                    & ~models.Q(removed_reason="")
                ),
                name="accounts_profile_photo_state_shape",
            ),
        ]

    def __str__(self) -> str:
        return f"ProfilePhoto({self.user_id}, {self.state})"


class UserBlock(models.Model):
    """One member has blocked another (App Store 1.2; `apps.accounts.blocks`).

    While either of two members blocks the other, neither can message the
    other, propose to the other, accept the other's proposal or tell the other
    "I can carry this". A delivery already funded goes on: its codes,
    progress, problem reports and disputes do not need the chat.
    """

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocks_made",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocks_received",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_user_block"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("blocker", "blocked"), name="accounts_user_block_once"
            ),
            models.CheckConstraint(
                condition=~models.Q(blocker=models.F("blocked")),
                name="accounts_user_block_not_self",
            ),
        ]
        indexes = [models.Index(fields=("blocked", "blocker"), name="accounts_block_rev_idx")]

    def __str__(self) -> str:
        return f"UserBlock({self.blocker_id} blocks {self.blocked_id})"
