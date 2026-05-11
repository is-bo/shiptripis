"""HandoverCode — the trigger that drives escrow release.

Two codes per Match:
  PICKUP    — sender → traveler at parcel handoff
              moves Match: accepted → in_transit
  DELIVERY  — recipient → traveler at delivery
              moves Match: in_transit → delivered → completed
              fires `release_hold_to_payee` on the wallet ledger

Codes are 6-digit numeric, generated server-side, shown ONCE in plaintext
to the issuer (sender), and stored as an argon2 hash. Verification compares
the supplied code against the hash. After verification the row is marked
`used_at` and cannot be replayed.

Attempt rate-limit: 5 wrong tries lock the code; sender can rotate.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.matching.models import Match


class HandoverCode(models.Model):
    class Kind(models.TextChoices):
        PICKUP = "pickup", "Pickup (sender → traveler)"
        DELIVERY = "delivery", "Delivery (recipient → traveler)"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        USED = "used", "Used"
        LOCKED = "locked", "Locked (too many wrong attempts)"
        ROTATED = "rotated", "Rotated (replaced by a newer code)"

    match = models.ForeignKey(
        Match, on_delete=models.PROTECT, related_name="handover_codes"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    code_hash = models.CharField(max_length=255)  # argon2 hash; bigger than bcrypt
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=0)

    issued_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="handover_codes_issued",
    )
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="handover_codes_redeemed",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "verification_handover_code"
        ordering = ["-created_at"]
        constraints = [
            # At most one ACTIVE code per (match, kind). A rotated code becomes
            # ROTATED and a new ACTIVE row is inserted.
            models.UniqueConstraint(
                fields=["match", "kind"],
                condition=models.Q(status="active"),
                name="handover_one_active_per_match_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"HandoverCode #{self.id} {self.kind} match={self.match_id}"
