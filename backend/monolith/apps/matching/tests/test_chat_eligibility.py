"""The chat rule for every state a current Deal can be in.

Send: the Deal must be funded (`funded_at`) and not closed. Read: funded is
enough, closed or not. Built through the real propose and accept services, so
each row is one the app can produce.
"""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.deals.models import Deal
from apps.finance.tests.factories import build_scenario
from apps.matching.services import chat_eligibility, chat_history_visible

#: Deal states that close a funded conversation to new messages.
CLOSED = {"completed", "cancelled", "expired", "refunded", "partially_refunded"}


class ChatRuleForEveryDealStateTests(TestCase):
    def setUp(self):
        self.scenario = build_scenario(prefix="chat-rule")

    def answers(self, match):
        return {
            user.pk: (chat_eligibility(match, user.pk), chat_history_visible(match, user.pk))
            for user in (self.scenario.sender, self.scenario.traveler)
        }

    def test_a_proposal_without_a_deal_opens_nothing(self):
        match = self.scenario.propose().match
        for send, read in self.answers(match).values():
            assert send == (False, "no_accepted_offer")
            assert read == (False, "payment_pending")

    def test_an_outsider_is_never_a_party(self):
        match = self.scenario.accept().match
        outsider = self.scenario.outsider.pk
        assert chat_eligibility(match, outsider) == (False, "not_a_party")
        assert chat_history_visible(match, outsider) == (False, "not_a_party")

    def test_every_deal_state_funded_and_not(self):
        deal = self.scenario.accept()
        for status in Deal.Status.values:
            for funded_at in (None, timezone.now()):
                with self.subTest(status=status, funded=funded_at is not None):
                    Deal.objects.filter(pk=deal.pk).update(status=status, funded_at=funded_at)
                    match = Deal.objects.select_related("match").get(pk=deal.pk).match
                    if funded_at is None:
                        expected_send = (False, "payment_pending")
                        expected_read = (False, "payment_pending")
                    elif status in CLOSED:
                        expected_send = (False, "match_closed")
                        expected_read = (True, "ok")
                    else:
                        expected_send = (True, "ok")
                        expected_read = (True, "ok")
                    for send, read in self.answers(match).values():
                        assert send == expected_send
                        assert read == expected_read
