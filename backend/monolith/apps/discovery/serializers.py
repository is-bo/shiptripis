"""Input validation for discovery. Output is built by the allowlist cards."""

from __future__ import annotations

from rest_framework import serializers

from .listings import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .models import MAX_USUAL_ROUTES, RouteAlert
from .profiles import ROLE_SENDER, ROLE_TRAVELER

ROLE_CHOICES = (ROLE_SENDER, ROLE_TRAVELER)
#: Paging deeper than this is a scrape, not a browse.
MAX_OFFSET = 1_000


class _PageSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        min_value=1, max_value=MAX_PAGE_SIZE, default=DEFAULT_PAGE_SIZE
    )
    offset = serializers.IntegerField(min_value=0, max_value=MAX_OFFSET, default=0)


class ListingQuerySerializer(_PageSerializer):
    origin_country = serializers.RegexField(r"^[A-Z]{2}$", required=False)
    destination_country = serializers.RegexField(r"^[A-Z]{2}$", required=False)
    origin_place_id = serializers.IntegerField(min_value=1, required=False)
    destination_place_id = serializers.IntegerField(min_value=1, required=False)
    departing_after = serializers.DateTimeField(required=False)


class ReviewsQuerySerializer(_PageSerializer):
    """A page of reviews (L13A). `request` is the Find Travelers context."""

    request = serializers.IntegerField(min_value=1, required=False)


class MatchesQuerySerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ROLE_CHOICES)


class PeopleQuerySerializer(_PageSerializer):
    role = serializers.ChoiceField(choices=ROLE_CHOICES)
    origin_place_id = serializers.IntegerField(min_value=1, required=False)
    destination_place_id = serializers.IntegerField(min_value=1, required=False)


class UsualRouteSerializer(serializers.Serializer):
    origin_place_id = serializers.IntegerField(min_value=1)
    destination_place_id = serializers.IntegerField(min_value=1)


class ProfileUpdateSerializer(serializers.Serializer):
    is_discoverable = serializers.BooleanField(required=False)
    usual_routes = UsualRouteSerializer(
        many=True, required=False, max_length=MAX_USUAL_ROUTES
    )
    prompt_dismissed = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("prompt_dismissed") and not (
            {"is_discoverable", "usual_routes"} & set(attrs)
        ):
            raise serializers.ValidationError("Nothing to change.")
        return attrs


class AlertCreateSerializer(serializers.Serializer):
    watches = serializers.ChoiceField(choices=RouteAlert.Watches.values)
    origin_place_id = serializers.IntegerField(min_value=1)
    destination_place_id = serializers.IntegerField(min_value=1)
    subject_profile_id = serializers.UUIDField(required=False)


class InterestCreateSerializer(serializers.Serializer):
    journey_id = serializers.IntegerField(min_value=1)
