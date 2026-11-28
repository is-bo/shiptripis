"""F1 rule F-C as a table: every state of the EUR setup against every writer.

While the method's account creation can still produce an account (committed,
in flight, unclear), a write that would change the euro declaration's country
or switch euros off answers `payout_setup_in_progress` and changes nothing;
every other write goes through, and onboarding is the one call that settles
the creation. In every other state nothing is frozen. Staff changes are never
refused: they end eligibility, which the setup writes read on the locked User
row (`test_f1_setup_eligibility`).

"In flight" runs the writer inside the first onboarding call's Stripe request
and then lets that call finish; its answer is part of the row. The real-thread
versions are in `test_f1_setup_freeze`.

The property test checks the read against the writes: whatever a GET offers
is accepted by its write, or refused only with `payout_preference_changed`.
"""

from contextlib import nullcontext
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.finance.models import PayoutProviderOperation, StripePayoutAccount, TravelerPayoutMethod
from apps.finance.payout_accounts import ensure_account
from apps.finance.payout_profiles import member_refusal
from apps.finance.providers.base import ProviderCheckoutRejected, ProviderUnavailable

from .factories import make_user
from .test_f1_setup_eligibility import staff_change
from .test_phase8fh2_accounts import PLATFORM, FakeGateway, snapshot
from .test_phase8fh4_manual import configured_h4  # noqa: F401
from .test_phase8fh6a_mobile import (  # noqa: F401
    BOTH_COUNTRIES,
    ONBOARDING,
    HookedGateway,
    SecondPlatform,
    client_for,
    connect_gateway,
    preference,
    setup,
    summary,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("configured_h4")]

STATES = ("no_intent", "committed_unsent", "in_flight", "unclear_inside", "unclear_past",
          "refused", "bound", "bound_changed", "other_platform")
WRITERS = ("patch_country", "patch_euros_off", "patch_unchanged", "dzd_change", "post_country",
           "onboarding", "second_device", "ban", "role", "email")

OK, MADE, DONE = (200, None), (201, None), ("done", None)
FROZEN = (409, "payout_setup_in_progress")
MISMATCH = (409, "stripe_account_country_mismatch")
BOUND = {"bound": PLATFORM, "ops": ["accepted"], "accounts": 1}
RESTARTED = {"bound": PLATFORM, "ops": ["failed", "accepted"], "accounts": 1}
SECOND = "acct_platform_two"


def staff(changes=None):
    """The three staff changes: done, and the member gate says so afterwards."""
    changes = changes or {}
    return {"ban": (DONE, {**changes, "member": "payout_traveler_required"}),
            "role": (DONE, {**changes, "member": "payout_traveler_required"}),
            "email": (DONE, {**changes, "member": "email_verification_required"})}


def frozen(onboarded):
    """A creation in progress: the declaration waits, onboarding settles it."""
    return {"patch_country": (FROZEN, {}), "patch_euros_off": (FROZEN, {}),
            "patch_unchanged": (OK, {}), "dzd_change": (OK, {"dzd": True}),
            "post_country": (FROZEN, {}),
            "onboarding": (MADE, onboarded), "second_device": (MADE, onboarded), **staff()}


def free(*, country_change, euros_off, onboarded):
    """Nothing in progress: every preference write goes through."""
    return {"patch_country": (OK, country_change), "patch_euros_off": (OK, euros_off),
            "patch_unchanged": (OK, {}), "dzd_change": (OK, {"dzd": True}),
            "post_country": (OK, country_change),
            "onboarding": onboarded, "second_device": onboarded, **staff()}


#: (state, writer) -> (the writer's answer, the rows that changed). For
#: "in_flight", also the first call's answer.
TABLE = {
    "no_intent": free(country_change={"eur": (True, "DE")},
                      euros_off={"eur": (False, "FR"), "dzd": True}, onboarded=(MADE, BOUND)),
    "committed_unsent": frozen(BOUND),
    "unclear_inside": frozen(BOUND),
    # Past the window a complete listing holds no account: a fresh attempt.
    "unclear_past": frozen(RESTARTED),
    "refused": free(country_change={"eur": (True, "DE")},
                    euros_off={"eur": (False, "FR"), "dzd": True}, onboarded=(MADE, RESTARTED)),
    "bound": free(country_change={"eur": (True, "DE"), "bound": None},
                  euros_off={"eur": (False, "FR"), "dzd": True}, onboarded=(MADE, {})),
    # DE declared over the FR account: the account never serves DE.
    "bound_changed": free(country_change={"eur": (True, "FR")},
                          euros_off={"eur": (False, "DE"), "dzd": True},
                          onboarded=(MISMATCH, {})),
    # The account of the first platform is history in the second.
    "other_platform": free(country_change={"eur": (True, "DE"), "bound": None},
                           euros_off={"eur": (False, "FR"), "dzd": True},
                           onboarded=(MADE, {"bound": SECOND, "ops": ["accepted", "accepted"],
                                             "accounts": 2})),
}
KEPT = {"ops": ["accepted"], "accounts": 1}
TABLE["in_flight"] = {
    **{writer: (answer, MADE, {**BOUND, **changes})
       for writer, (answer, changes) in frozen(BOUND).items() if writer not in ("ban", "role", "email")},
    "ban": (DONE, (403, "payout_traveler_required"), {**KEPT, "member": "payout_traveler_required"}),
    "role": (DONE, (403, "payout_traveler_required"), {**KEPT, "member": "payout_traveler_required"}),
    "email": (DONE, (403, "email_verification_required"),
              {**KEPT, "member": "email_verification_required"}),
}


class Crash(FakeGateway):
    def create_account(self, **kwargs):
        raise RuntimeError("the worker died before the request left")


def rows(user):
    user.refresh_from_db()
    eur = TravelerPayoutMethod.objects.get(traveler=user, currency="EUR")
    dzd = TravelerPayoutMethod.objects.filter(traveler=user, currency="DZD").first()
    version = eur.current_version
    return {
        "eur": (eur.enabled, version.country),
        "dzd": bool(dzd and dzd.enabled),
        # The platform of the bound account: each traveler's account id is their own.
        "bound": version.stripe_account.platform_id if version.stripe_account else None,
        "ops": list(PayoutProviderOperation.objects.filter(method=eur, kind="account_create")
                    .order_by("pk").values_list("status", flat=True)),
        "accounts": StripePayoutAccount.objects.filter(traveler=user).count(),
        "member": getattr(member_refusal(user), "code", None),
    }


def opened(user, platform="first"):
    """What Stripe answers for `user`: an FR account of their own."""
    return snapshot(account_id=f"acct_1TEST{platform}{user.pk}")


def arrange(state, user, client, monkeypatch):
    """Bring `user`'s EUR setup to `state`; answer the scope and gateway the writers use."""
    assert preference(client, "eur_only", country="FR").status_code == 200
    if state == "committed_unsent":
        with pytest.raises(RuntimeError):
            ensure_account(actor=user, gateway=Crash())
    elif state in ("unclear_inside", "unclear_past"):
        connect_gateway(monkeypatch, FakeGateway(create=ProviderUnavailable("timeout")))
        assert client.post(ONBOARDING, {}, format="json").status_code == 502
        if state == "unclear_past":
            PayoutProviderOperation.objects.update(first_request_at=timezone.now() - timedelta(days=2))
    elif state == "refused":
        with pytest.raises(ProviderCheckoutRejected):
            ensure_account(actor=user, gateway=FakeGateway(
                create=ProviderCheckoutRejected("Connect signup required")))
    elif state in ("bound", "bound_changed", "other_platform"):
        connect_gateway(monkeypatch, FakeGateway(create=opened(user)))
        assert client.post(ONBOARDING, {}, format="json").status_code == 201
        if state == "bound_changed":
            revisions = summary(client)["revisions"]
            assert preference(client, "eur_only", eur=revisions["EUR"], dzd=revisions["DZD"],
                              country="DE").status_code == 200
    if state == "other_platform":
        return (override_settings(STRIPE_CONNECT_PLATFORM_ACCOUNT_ID="acct_platform_two"),
                SecondPlatform(create=opened(user, "second")))
    return nullcontext(), FakeGateway(create=opened(user))


def write(writer, user, client):
    """Run one writer as the phone or staff would; answer (status, code)."""
    if writer in ("ban", "role", "email"):
        staff_change(user, writer)
        return DONE
    if writer in ("onboarding", "second_device"):
        device = client if writer == "onboarding" else client_for(user)
        answered = device.post(ONBOARDING, {}, format="json")
    else:
        read = summary(client)
        revisions, saved = read["revisions"], read["eur"]["country"]
        other = {"FR": "DE", "DE": "FR"}[saved]
        if writer == "post_country":
            answered = client.post("/api/payouts/methods", {
                "currency": "EUR", "enabled": True, "country": other,
                "expected_revision": revisions["EUR"], "consent_policy": "payout_profile_v1",
            }, format="json")
        else:
            value, country = {"patch_country": ("eur_only", other),
                              "patch_euros_off": ("dzd_only", ""),
                              "patch_unchanged": ("eur_only", saved),
                              "dzd_change": ("both", saved)}[writer]
            answered = preference(client, value, eur=revisions["EUR"], dzd=revisions["DZD"],
                                  country=country)
    return answered.status_code, answered.data.get("code")


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("state", STATES)
def test_every_writer_in_every_setup_state(monkeypatch, state, writer):
    user = make_user(f"f1table-{state}-{writer}@f1.test", is_email_verified=True)
    client = client_for(user)
    scope, gateway = arrange(state, user, client, monkeypatch)
    with scope:
        before = rows(user)
        if state == "in_flight":
            answers = []
            connect_gateway(monkeypatch, HookedGateway(
                during="create_account", hook=lambda: answers.append(write(writer, user, client)),
                create=opened(user)))
            first = client.post(ONBOARDING, {}, format="json")
            expected, expected_first, changes = TABLE[state][writer]
            assert (first.status_code, first.data.get("code")) == expected_first, first.data
            answer = answers[0]
        else:
            connect_gateway(monkeypatch, gateway)
            answer = write(writer, user, client)
            expected, changes = TABLE[state][writer]
        assert answer == expected
        assert rows(user) == {**before, **changes}


#: How each action the read offers reaches its write.
ACTION_WRITES = {"configure_eur": "/api/payouts/methods/stripe/onboarding",
                 "resume_eur_setup": "/api/payouts/methods/stripe/onboarding",
                 "refresh": "/api/payouts/methods/stripe/refresh",
                 "manage_eur": "/api/payouts/methods/stripe/dashboard"}


def offered(read):
    """Everything the EUR read offers: its actions, then the preference options."""
    return ([("action", name) for name in read["eur"]["available_actions"]]
            + [("preference", value) for value in read["setup"]["preference_options"]])


def take(item, read, client):
    kind, name = item
    if kind == "action":
        return client.post(ACTION_WRITES[name], {}, format="json")
    country = "" if name == "dzd_only" else read["eur"]["country"]
    return preference(client, name, eur=read["revisions"]["EUR"], dzd=read["revisions"]["DZD"],
                      country=country)


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("state", STATES)
def test_whatever_the_read_offers_its_write_accepts(monkeypatch, state):
    """Each offer is taken on a fresh setup in `state`, read the way the phone reads it."""

    def offers_in(state, tag, then):
        user = make_user(f"f1offer-{state}-{tag}@f1.test", is_email_verified=True)
        client = client_for(user)
        scope, gateway = arrange(state, user, client, monkeypatch)
        with scope:
            if state != "in_flight":
                connect_gateway(monkeypatch, gateway)
                return then(client)
            answers = []
            connect_gateway(monkeypatch, HookedGateway(
                during="create_account", hook=lambda: answers.append(then(client)),
                create=opened(user)))
            assert client.post(ONBOARDING, {}, format="json").status_code == 201
            return answers[0]

    items = offers_in(state, "read", lambda client: offered(summary(client)))
    assert items, f"{state} offers nothing at all"
    for number, item in enumerate(items):
        def taken(client, item=item):
            read = summary(client)
            assert item in offered(read), (state, item)
            answered = take(item, read, client)
            return answered.status_code, answered.data.get("code")

        status, code = offers_in(state, number, taken)
        assert status < 300 or code == "payout_preference_changed", (state, item, status, code)
