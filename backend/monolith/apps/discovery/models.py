"""Home discovery: public profiles, route alerts and "I can carry this".

Discovery is a window onto the marketplace, never a second marketplace. Nothing
here decides compatibility, creates a match, reserves capacity or moves money:
those stay with `apps.matching`, `apps.deals` and `apps.finance`. The rows below
hold only what a member chose to publish about themselves and what they asked
to be told about.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

#: At most three "usual routes" on a public profile (spec 4.2).
MAX_USUAL_ROUTES = 3
#: At most ten active route alerts per member (plan L2A).
MAX_ACTIVE_ALERTS = 10


class PublicProfile(models.Model):
    """A member's opt-in public profile. Off by default (spec 4.3).

    `public_id` is the only identifier that ever leaves the server for a
    profile. The member's own user id is never published by discovery.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="public_profile",
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_discoverable = models.BooleanField(default=False)
    #: The wording the member agreed to when they last turned the profile on.
    consent_version = models.CharField(max_length=32, blank=True, default="")
    consented_at = models.DateTimeField(null=True, blank=True)
    prompt_dismissed_at = models.DateTimeField(null=True, blank=True)
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    hidden_reason = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_public_profile"
        indexes = [
            models.Index(
                fields=("is_discoverable", "hidden_at"),
                name="disc_profile_visible_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(hidden_at__isnull=True) | ~Q(hidden_reason=""),
                name="disc_profile_hidden_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(is_discoverable=False) | Q(consented_at__isnull=False),
                name="disc_profile_visible_has_consent",
            ),
        ]

    def __str__(self) -> str:
        return f"PublicProfile(user={self.user_id})"


class PublicProfileRoute(models.Model):
    """One "usual route" on a profile: an ordered pair of catalogue localities."""

    profile = models.ForeignKey(
        PublicProfile, on_delete=models.CASCADE, related_name="usual_routes"
    )
    position = models.PositiveSmallIntegerField()
    origin_locality = models.ForeignKey(
        "locations.Place", on_delete=models.PROTECT, related_name="+"
    )
    destination_locality = models.ForeignKey(
        "locations.Place", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "discovery_public_profile_route"
        ordering = ("profile_id", "position")
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "position"), name="disc_route_profile_position_uniq"
            ),
            models.UniqueConstraint(
                fields=("profile", "origin_locality", "destination_locality"),
                name="disc_route_profile_pair_uniq",
            ),
            models.CheckConstraint(
                condition=Q(position__lt=MAX_USUAL_ROUTES),
                name="disc_route_position_bound",
            ),
            models.CheckConstraint(
                condition=~Q(origin_locality=F("destination_locality")),
                name="disc_route_distinct_ends",
            ),
        ]
        indexes = [
            models.Index(
                fields=("origin_locality", "destination_locality"),
                name="disc_route_pair_idx",
            ),
        ]


class RouteAlert(models.Model):
    """"Tell me when someone publishes on this route" (spec 4.4).

    `subject_user` narrows the alert to one person's trips or requests; empty
    means anyone. A deleted alert is deactivated, not removed, so staff can
    still read what a member asked for.
    """

    class Watches(models.TextChoices):
        TRIPS = "trips", "Trips"
        REQUESTS = "requests", "Requests"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="route_alerts",
    )
    watches = models.CharField(max_length=12, choices=Watches.choices)
    origin_locality = models.ForeignKey(
        "locations.Place", on_delete=models.PROTECT, related_name="+"
    )
    destination_locality = models.ForeignKey(
        "locations.Place", on_delete=models.PROTECT, related_name="+"
    )
    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
    is_active = models.BooleanField(default=True)
    #: The last time this alert notified its owner. At most one notification
    #: per alert per `ALERT_QUIET_PERIOD` (plan L2A), enforced by a guarded
    #: UPDATE so two concurrent publications cannot both notify.
    last_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "discovery_route_alert"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("watches", "origin_locality", "destination_locality", "is_active"),
                name="disc_alert_route_idx",
            ),
            models.Index(fields=("user", "is_active"), name="disc_alert_user_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "user",
                    "watches",
                    "origin_locality",
                    "destination_locality",
                    "subject_user",
                ),
                condition=Q(is_active=True),
                nulls_distinct=False,
                name="disc_alert_active_uniq",
            ),
            models.CheckConstraint(
                condition=~Q(origin_locality=F("destination_locality")),
                name="disc_alert_distinct_ends",
            ),
            models.CheckConstraint(
                condition=Q(subject_user__isnull=True) | ~Q(subject_user=F("user")),
                name="disc_alert_not_self",
            ),
            models.CheckConstraint(
                condition=Q(is_active=True, deactivated_at__isnull=True)
                | Q(is_active=False, deactivated_at__isnull=False),
                name="disc_alert_deactivation_consistent",
            ),
        ]


class TravelerInterest(models.Model):
    """"I can carry this": one signal per request and journey (spec 4.4).

    It is a notification to the sender and nothing more. It carries no price,
    is not an offer and reserves nothing; the sender still proposes first.
    """

    delivery_request = models.ForeignKey(
        "parcels.DeliveryRequest",
        on_delete=models.CASCADE,
        related_name="traveler_interests",
    )
    journey = models.ForeignKey(
        "trips.Journey", on_delete=models.CASCADE, related_name="traveler_interests"
    )
    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="discovery_interests",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "discovery_traveler_interest"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("delivery_request", "journey"),
                name="disc_interest_request_journey_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("traveler", "created_at"), name="disc_interest_cap_idx"
            ),
        ]


class TripFitAlert(models.Model):
    """One trip-fit alert sent: a new request really fits this journey (spec 17.2).

    The row is the record that the traveler was told, written in the same
    transaction as the notification. It makes the alert once-only per request
    and journey, counts toward the traveler's daily cap, and tells the
    route-alert step whom to leave out. Like "I can carry this", it is not an
    offer and reserves nothing.
    """

    delivery_request = models.ForeignKey(
        "parcels.DeliveryRequest",
        on_delete=models.CASCADE,
        related_name="trip_fit_alerts",
    )
    journey = models.ForeignKey(
        "trips.Journey", on_delete=models.CASCADE, related_name="trip_fit_alerts"
    )
    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trip_fit_alerts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "discovery_trip_fit_alert"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("delivery_request", "journey"),
                name="disc_trip_fit_request_journey_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("traveler", "created_at"), name="disc_trip_fit_cap_idx"
            ),
        ]

    def __str__(self) -> str:
        return (
            f"TripFitAlert request={self.delivery_request_id} "
            f"journey={self.journey_id}"
        )
