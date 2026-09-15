"""Posting a request under J2: the price floor, the Boost, and the deposit.

Three things a sender does on one screen, and all three are the server's to
decide:

**The price floor is enforced at creation.** Whatever the posting screen showed,
a reward below the platform minimum for this route and weight is refused before
a row exists. Below the *recommendation* is the sender's business and is not
refused.

**A Boost posted with the request is a real Boost.** Bounded by the same policy
band as one set later, audited from its first cent, and actually ranking once
the deposit publishes the request.

**The deposit is a choice.** Omitting it takes the recommendation; supplying one
is bounded by the floor and by the obligation it pre-pays -- and a deposit that
cannot be charged rolls the whole creation back rather than leaving a request
with nothing to pay.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boosts.models import BoostIntentEvent
from apps.finance.models import PaymentOrder
from apps.locations.models import Country, Place
from apps.parcels.models import DeliveryRequest, ParcelMedia, ParcelRequest

CREATE_URL = reverse("parcels-delivery-v1-create")
QUOTE_URL = reverse("parcels-pricing-quote")


@patch("apps.core.redis_bus.publish_after_commit")
class J2PostingTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            username="j2post-sender@example.com",
            email="j2post-sender@example.com",
            password="Sup3rStrongPass!",
            full_name="J2 Sender",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.sender)

        france = Country.objects.create(
            code="FR",
            name="France",
            source="j2post",
            source_id="j2post-fr",
            source_version="j2post",
        )
        algeria = Country.objects.create(
            code="DZ",
            name="Algeria",
            source="j2post",
            source_id="j2post-dz",
            source_version="j2post",
        )
        self.pickup_place = Place.objects.create(
            country=france,
            place_type=Place.PlaceType.LOCALITY,
            source="j2post",
            source_id="locality-paris",
            source_version="j2post",
            name="Paris",
            latitude=Decimal("48.856614"),
            longitude=Decimal("2.352222"),
        )
        self.delivery_place = Place.objects.create(
            country=algeria,
            place_type=Place.PlaceType.LOCALITY,
            source="j2post",
            source_id="locality-algiers",
            source_version="j2post",
            name="Algiers",
            latitude=Decimal("36.737232"),
            longitude=Decimal("3.086472"),
        )

    # -- helpers ----------------------------------------------------------

    def _photo(self) -> ParcelMedia:
        return ParcelMedia.objects.create(
            parcel=None,
            uploaded_by=self.sender,
            purpose=ParcelMedia.Purpose.ITEM_PHOTO,
            bucket="shiptrip-parcel-test",
            object_key=f"parcels/staged/{self.sender.pk}/{uuid4().hex}.jpg",
            content_type="image/jpeg",
            bytes=2048,
        )

    def _payload(self, **overrides) -> dict:
        now = timezone.now()
        body = {
            "pickup_place_id": self.pickup_place.pk,
            "delivery_place_id": self.delivery_place.pk,
            "ready_window_start": (now + timedelta(days=1)).isoformat(),
            "ready_window_end": (now + timedelta(days=1, hours=2)).isoformat(),
            "deadline_at": (now + timedelta(days=3)).isoformat(),
            "actual_weight_kg": "2.50",
            "declared_value_eur_cents": 12_500,
            "sender_proposed_reward_eur_cents": 3_000,
            "title": "Documents for Algiers",
            "description": "A sealed folder of personal documents.",
            "category": "documents",
            "handling_notes": "",
            "fragile": False,
            "description_is_accurate": True,
            "item_is_legal": True,
            "no_prohibited_goods": True,
            "declared_value_is_accurate": True,
            "customs_responsibilities_understood": True,
            "item_photo_media_id": self._photo().pk,
        }
        body.update(overrides)
        return body

    def _create(self, **overrides):
        return self.client.post(CREATE_URL, self._payload(**overrides), format="json")

    def _draft_quote(self, **overrides):
        now = timezone.now()
        body = {
            "pickup_place_id": self.pickup_place.pk,
            "delivery_place_id": self.delivery_place.pk,
            "actual_weight_kg": "2.50",
            "ready_window_end": (now + timedelta(days=1, hours=2)).isoformat(),
            "deadline_at": (now + timedelta(days=3)).isoformat(),
        }
        body.update(overrides)
        return self.client.post(QUOTE_URL, body, format="json")

    # -- the three prices, before anything is written ----------------------

    def test_a_draft_is_priced_before_the_sender_chooses(self, _publish):
        res = self._draft_quote()

        assert res.status_code == 200, res.data
        minimum = res.data["minimum_reward_eur_cents"]
        recommended = res.data["recommended_reward_eur_cents"]
        assert minimum > 0
        assert recommended >= minimum
        # The recommendation is available with no chosen value supplied at all.
        assert res.data["chosen_reward_eur_cents"] is None
        assert res.data["recommended_economics"]["sender_total_minor"] > recommended
        assert res.data["deposit"]["recommended_eur_cents"] >= 300
        assert res.data["deposit"]["minimum_eur_cents"] == 300
        assert res.data["boost"]["policy"]["has_expiry"] is False
        # Nothing was written.
        assert DeliveryRequest.objects.count() == 0

    def test_a_draft_says_whether_a_chosen_price_clears_the_floor(self, _publish):
        band = self._draft_quote().data
        minimum = band["minimum_reward_eur_cents"]
        recommended = band["recommended_reward_eur_cents"]

        below = self._draft_quote(chosen_reward_eur_cents=minimum - 1).data
        assert below["chosen_is_below_minimum"] is True

        under_recommended = self._draft_quote(
            chosen_reward_eur_cents=minimum
        ).data
        assert under_recommended["chosen_is_below_minimum"] is False
        assert under_recommended["chosen_is_below_recommended"] is True
        assert under_recommended["chosen_economics"]["sender_total_minor"] > minimum

        above = self._draft_quote(chosen_reward_eur_cents=recommended * 3).data
        assert above["chosen_is_below_minimum"] is False
        assert above["chosen_is_below_recommended"] is False

    # -- the floor ---------------------------------------------------------

    def test_a_reward_below_the_minimum_is_refused_and_writes_nothing(
        self, _publish
    ):
        minimum = self._draft_quote().data["minimum_reward_eur_cents"]

        res = self._create(sender_proposed_reward_eur_cents=minimum - 1)

        assert res.status_code == 400, res.data
        assert res.data["code"] == "price_below_minimum"
        assert res.data["minimum_reward_eur_cents"] == minimum
        assert res.data["recommended_reward_eur_cents"] >= minimum
        assert DeliveryRequest.objects.count() == 0
        assert PaymentOrder.objects.count() == 0

    def test_a_reward_below_the_recommendation_but_above_the_floor_is_accepted(
        self, _publish
    ):
        band = self._draft_quote().data
        minimum = band["minimum_reward_eur_cents"]
        assert minimum < band["recommended_reward_eur_cents"]

        res = self._create(sender_proposed_reward_eur_cents=minimum)

        assert res.status_code == 201, res.data
        assert res.data["sender_proposed_reward_eur_cents"] == minimum
        assert res.data["pricing"]["minimum_reward_eur_cents"] == minimum
        assert res.data["pricing"]["chosen_reward_eur_cents"] == minimum

    # -- the boost ---------------------------------------------------------

    def test_a_boost_posted_with_the_request_ranks_and_is_audited(self, _publish):
        res = self._create(boost_eur_cents=800)

        assert res.status_code == 201, res.data
        assert res.data["boost_eur_cents"] == 800
        assert res.data["total_offered_reward_eur_cents"] == 3_800

        parcel = DeliveryRequest.objects.get(pk=res.data["id"])
        assert parcel.boost_eur_cents == 800
        # It actually ranks: weight derived and paired with the deadline.
        assert parcel.ranking_boost_weight > 0
        assert parcel.ranking_boost_expires_at == parcel.deadline_at
        # And it is on the record from its first cent.
        event = BoostIntentEvent.objects.get(delivery_request_id=parcel.pk)
        assert event.reason == BoostIntentEvent.Reason.SENDER_SET
        assert (event.previous_eur_cents, event.amount_eur_cents) == (0, 800)
        assert event.actor_id == self.sender.pk

    def test_a_boost_outside_the_policy_band_is_refused_at_posting(self, _publish):
        res = self._create(boost_eur_cents=50)

        assert res.status_code == 400, res.data
        assert res.data["code"] == "boost_amount_below_minimum"
        assert res.data["minimum_boost_eur_cents"] == 100
        assert DeliveryRequest.objects.count() == 0

    def test_no_boost_is_the_default_and_writes_no_event(self, _publish):
        res = self._create()

        assert res.status_code == 201, res.data
        assert res.data["boost_eur_cents"] == 0
        assert res.data["total_offered_reward_eur_cents"] == 3_000
        assert BoostIntentEvent.objects.count() == 0

    # -- the deposit -------------------------------------------------------

    def test_omitting_the_deposit_takes_the_recommendation(self, _publish):
        res = self._create()

        assert res.status_code == 201, res.data
        deposit = res.data["posting_deposit"]
        assert deposit is not None
        assert 300 <= deposit["amount_eur_cents"] <= 700
        assert res.data["status"] == ParcelRequest.Status.AWAITING_DEPOSIT

    def test_the_sender_may_post_with_a_deposit_of_their_own(self, _publish):
        res = self._create(posting_deposit_eur_cents=2_000)

        assert res.status_code == 201, res.data
        # Well above the EUR 7 recommendation clamp, which is not a limit.
        assert res.data["posting_deposit"]["amount_eur_cents"] == 2_000
        order = PaymentOrder.objects.get(
            delivery_request_id=res.data["id"],
            purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
        )
        snapshot = order.terms_snapshot["posting_deposit_inputs"]
        assert snapshot["chosen_by_sender"] is True
        assert snapshot["chosen_deposit_eur_cents"] == 2_000
        assert snapshot["chosen_reward_eur_cents"] == 3_000

    def test_a_deposit_above_the_obligation_rolls_the_whole_creation_back(
        self, _publish
    ):
        """A request that cannot be paid for must not survive the attempt."""

        # Chosen reward 3000 + 25% commission = 3750 owed in total.
        res = self._create(posting_deposit_eur_cents=3_751)

        assert res.status_code == 400, res.data
        assert res.data["code"] == "deposit_above_obligation"
        assert res.data["maximum_eur_cents"] == 3_750
        assert DeliveryRequest.objects.count() == 0
        assert PaymentOrder.objects.count() == 0
        # The staged photo is not consumed by a creation that did not happen.
        assert ParcelMedia.objects.filter(parcel__isnull=True).exists()

    def test_the_deposit_ceiling_includes_a_boost_posted_alongside_it(
        self, _publish
    ):
        # 3000 + 750 commission + 800 boost + 200 boost commission = 4750.
        res = self._create(boost_eur_cents=800, posting_deposit_eur_cents=4_750)

        assert res.status_code == 201, res.data
        assert res.data["posting_deposit"]["amount_eur_cents"] == 4_750
