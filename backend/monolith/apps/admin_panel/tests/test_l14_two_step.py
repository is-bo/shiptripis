"""L14, spec 19.1: staff two-step sign-in.

The codes (RFC vectors, tolerance, replay, lockout), recovery codes, the pages,
the gate on every console, technical admin and staff API route, the reset, the
fresh-code rule and the production refusal.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock
from xml.etree import ElementTree

import segno
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User

from .. import two_step
from ..models import AdminAuditLog, AdminInvitation, AdminRecoveryCode, AdminTwoStep
from ..permissions import AdminRole, assign_admin_roles
from ..staff_api import OPEN_STAFF_API_ROUTES
from .two_step_helpers import staff_login, verify_session

KEYRING = {
    "PAYOUT_DATA_KEYRING": json.dumps({"l14": base64.b64encode(b"k" * 32).decode()}),
    "PAYOUT_DATA_ACTIVE_KEY_ID": "l14",
    "PAYOUT_ACCOUNT_FINGERPRINT_KEY": base64.b64encode(b"f" * 32).decode(),
}
#: Pages render without a collected static manifest.
PAGES = {
    **KEYRING,
    "STORAGES": {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
}

#: RFC 6238 appendix B, SHA-1 rows: (unix time, 8-digit code).
RFC6238_SHA1 = (
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
)
RFC_KEY = b"12345678901234567890"


def make_staff(email: str, role: str = AdminRole.OPS) -> User:
    user = User.objects.create_user(
        email=email,
        username=email,
        password="Strong-pass-123!",
        full_name=email.split("@")[0].title(),
        is_staff=True,
        is_superuser=role == AdminRole.SUPER_ADMIN,
    )
    assign_admin_roles(user, (role,), elevate_super_admin=role == AdminRole.SUPER_ADMIN)
    return user


def at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=dt_timezone.utc)


def enrol(user: User, *, now: datetime | None = None) -> bytes:
    """Enrol ``user`` through the service and return their key."""

    row = two_step.pending_enrolment(user)
    key = two_step._key_bytes(two_step.secret_text(row))
    moment = now or timezone.now()
    outcome = two_step.confirm_enrolment(user, two_step.totp(key, moment), now=moment)
    assert outcome.ok, outcome
    return key


class TotpTests(TestCase):
    def test_rfc_6238_sha1_vectors(self):
        for seconds, expected in RFC6238_SHA1:
            assert two_step.totp(RFC_KEY, at(seconds), digits=8) == expected
            # The 6-digit code is the same number cut to six digits.
            assert two_step.totp(RFC_KEY, at(seconds)) == expected[-6:]

    def test_rfc_4226_vectors(self):
        expected = ("755224", "287082", "359152", "969429", "338314")
        assert tuple(two_step.hotp(RFC_KEY, n) for n in range(5)) == expected

    def test_one_step_of_tolerance_either_side_and_no_more(self):
        now = at(1_700_000_000)
        step = two_step.time_step(now)
        for offset, accepted in ((-2, False), (-1, True), (0, True), (1, True), (2, False)):
            code = two_step.hotp(RFC_KEY, step + offset)
            result = two_step._accepted_step(RFC_KEY, code, now=now, after_step=0)
            assert (result is not None) is accepted, offset

    def test_malformed_codes_are_refused(self):
        now = at(1_700_000_000)
        for code in ("", "12345", "1234567", "abcdef", "١٢٣٤٥٦"):
            assert two_step._accepted_step(RFC_KEY, code, now=now, after_step=0) is None


@override_settings(**KEYRING)
class VerificationTests(TestCase):
    def setUp(self):
        self.user = make_staff("ops@example.test")
        self.now = at(1_800_000_000)
        self.key = enrol(self.user, now=self.now - timedelta(minutes=5))

    def code(self, moment, offset=0):
        return two_step.hotp(self.key, two_step.time_step(moment) + offset)

    def test_secret_is_sealed_and_bound_to_its_row(self):
        row = AdminTwoStep.objects.get(user=self.user)
        assert base64.b32encode(self.key).decode().rstrip("=") not in row.secret
        assert json.loads(row.secret)["kid"] == "l14"

    def test_a_code_works_once(self):
        code = self.code(self.now)
        assert two_step.verify_code(self.user, code, now=self.now).ok
        replay = two_step.verify_code(self.user, code, now=self.now)
        assert not replay.ok and replay.reason == two_step.WRONG

    def test_an_older_code_after_a_newer_one_is_refused(self):
        assert two_step.verify_code(self.user, self.code(self.now, 1), now=self.now).ok
        assert not two_step.verify_code(self.user, self.code(self.now), now=self.now).ok
        row = AdminTwoStep.objects.get(user=self.user)
        assert row.last_accepted_step == two_step.time_step(self.now) + 1

    def test_five_wrong_codes_lock_for_fifteen_minutes(self):
        for attempt in range(4):
            outcome = two_step.verify_code(self.user, "000000", now=self.now)
            assert outcome.reason == two_step.WRONG, attempt
        locked = two_step.verify_code(self.user, "000000", now=self.now)
        assert locked.reason == two_step.LOCKED
        assert locked.locked_until == self.now + timedelta(minutes=15)
        # The right code is refused while locked, and does not count.
        later = self.now + timedelta(minutes=14)
        assert two_step.verify_code(self.user, self.code(later), now=later).reason == (
            two_step.LOCKED
        )
        audit = AdminAuditLog.objects.get(action="admin.two_step_locked")
        assert audit.target_id == str(self.user.pk)
        # Released after fifteen minutes; the counter starts again.
        released = self.now + timedelta(minutes=15, seconds=1)
        assert two_step.verify_code(self.user, self.code(released), now=released).ok
        row = AdminTwoStep.objects.get(user=self.user)
        assert (row.failed_attempts, row.locked_until) == (0, None)

    def test_a_right_code_resets_the_failure_count(self):
        for _ in range(4):
            two_step.verify_code(self.user, "000000", now=self.now)
        assert two_step.verify_code(self.user, self.code(self.now), now=self.now).ok
        assert two_step.verify_code(self.user, "000000", now=self.now).reason == two_step.WRONG

    def test_recovery_codes_work_once_each_and_are_stored_hashed(self):
        codes = enrol(make_staff("other@example.test"))  # noqa: F841 - separate user
        row_codes = two_step._issue_recovery_codes(self.user)
        assert len(row_codes) == 10 and len(set(row_codes)) == 10
        stored = set(AdminRecoveryCode.objects.filter(user=self.user).values_list("code_hash", flat=True))
        assert not any(code.replace("-", "") in stored for code in row_codes)
        first = row_codes[0]
        used = two_step.use_recovery_code(self.user, first.upper().replace("-", " "))
        assert used.ok and used.recovery_codes_left == 9
        again = two_step.use_recovery_code(self.user, first)
        assert not again.ok and again.reason == two_step.WRONG
        audit = AdminAuditLog.objects.get(action="admin.two_step_recovery_code_used")
        assert audit.after == {"recovery_remaining": 9}

    def test_wrong_recovery_codes_count_toward_the_lock(self):
        for _ in range(5):
            outcome = two_step.use_recovery_code(self.user, "aaaa-bbbb-cccc-dddd")
        assert outcome.reason == two_step.LOCKED
        good = two_step._issue_recovery_codes(self.user)[0]
        assert two_step.use_recovery_code(self.user, good).reason == two_step.LOCKED

    def test_enrolment_writes_an_audit_row(self):
        audit = AdminAuditLog.objects.get(action="admin.two_step_enrolled", target_id=str(self.user.pk))
        assert audit.after == {"enrolled": True, "recovery_set": 10}


def _concrete(route: str) -> str:
    """A URL pattern with every converter filled with a plausible value."""

    import re

    values = {"int": "1", "uuid": str(uuid.uuid4()), "slug": "x", "str": "x", "path": "x"}

    def fill(match):
        converter = match.group(1) or "str"
        return values.get(converter, "x")

    path = re.sub(r"<(?:(\w+):)?\w+>", fill, route)
    path = re.sub(r"\^|\$|\\Z", "", path)
    path = re.sub(r"\(\?P<\w+>[^)]+\)", "x", path)
    return "/" + path


def _routes(prefix: str):
    def walk(patterns, base=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, base + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                yield base + str(pattern.pattern), pattern

    seen = set()
    for route, pattern in walk(get_resolver().url_patterns):
        if route.startswith(prefix) and route not in seen:
            seen.add(route)
            yield route, pattern


#: Every staff JSON API route (spec 19.1, plan L14 route inventory). A new
#: route must be added here, which makes its author decide whether it is
#: behind the second step (the default) or on `OPEN_STAFF_API_ROUTES`.
STAFF_API_ROUTES = frozenset(
    {
        "api/admin/dashboard",
        "api/admin/users",
        "api/admin/users/<int:pk>",
        "api/admin/kyc",
        "api/admin/kyc/<int:pk>/review",
        "api/admin/flight-proofs",
        "api/admin/flight-proofs/<int:pk>/review",
        "api/admin/requests",
        "api/admin/journeys",
        "api/admin/matches",
        "api/admin/offers",
        "api/admin/deals",
        "api/admin/deals/<int:pk>",
        "api/admin/deals/<int:pk>/no-show",
        "api/admin/disputes",
        "api/admin/disputes/<int:pk>/status",
        "api/admin/disputes/<int:pk>/resolve",
        "api/admin/payment-orders",
        "api/admin/payment-attempts",
        "api/admin/provider-events",
        "api/admin/refunds",
        "api/admin/refunds/request",
        "api/admin/refunds/<int:pk>/settle",
        "api/admin/payouts",
        "api/admin/payouts/<int:pk>/complete",
        "api/admin/scheduled-jobs",
        "api/admin/ratings",
        "api/admin/provider-health",
        "api/admin/health/deep",
        "api/admin/settings",
        "api/admin/roles",
        "api/admin/accounts",
        "api/admin/accounts/<int:pk>/role",
        "api/admin/invitations",
        "api/admin/invitations/accept",
        "api/admin/invitations/<uuid:pk>/revoke",
        "api/admin/audit-log",
        "api/admin/payouts/receipts",
        "api/admin/payouts/evidence/<uuid:reference>",
        "api/admin/payouts/profiles/<uuid:reference>/reveal",
        "api/admin/payouts/profiles/<uuid:reference>/review",
        "api/admin/payouts/<int:pk>/manual",
        "api/admin/payouts/<int:pk>/manual/prepare",
        "api/admin/payouts/<int:pk>/manual/begin",
        "api/admin/payouts/<int:pk>/manual/release",
        "api/admin/payouts/<int:pk>/manual/confirm",
        "api/admin/payout-identity-reviews/<uuid:reference>",
        "api/admin/payments/orders/<uuid:reference>/refund",
        "api/admin/payments/refunds/<int:pk>/settle",
        # L15. The AI helper: a helper key only, on `OPEN_STAFF_API_ROUTES`.
        "api/admin/helper/v1/guide",
        "api/admin/helper/v1/briefing",
        "api/admin/helper/v1/queues/<slug:code>",
        "api/admin/helper/v1/records/<slug:record_type>/<int:pk>",
        "api/admin/helper/v1/search",
        "api/admin/helper/v1/tasks",
        # L16. The helper's one change endpoint: a change key only.
        "api/admin/helper/v1/actions",
    }
)


class StaffApiGateTests(TestCase):
    """No staff API route answers without the second step (plan 2.12)."""

    def setUp(self):
        self.owner = make_staff("owner@example.test", AdminRole.SUPER_ADMIN)

    def bearer(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}

    def test_the_inventory_is_complete(self):
        assert {route for route, _ in _routes("api/admin")} == STAFF_API_ROUTES

    def test_open_routes_are_only_the_named_list(self):
        names = {
            pattern.name for route, pattern in _routes("api/admin") if pattern.name
        }
        assert OPEN_STAFF_API_ROUTES <= names
        assert OPEN_STAFF_API_ROUTES == {
            "admin-invitation-accept",
            "admin-helper-guide",
            "admin-helper-briefing",
            "admin-helper-queue",
            "admin-helper-record",
            "admin-helper-search",
            "admin-helper-tasks",
            "admin-helper-actions",
        }

    def _assert_refused(self, client, path, **extra):
        for method in ("get", "post"):
            response = getattr(client, method)(path, **extra)
            assert response.status_code == 403, (method, path, response.status_code)
            assert response.json()["code"] == two_step.TWO_STEP_REQUIRED_CODE, (method, path)

    def test_a_bearer_token_alone_is_refused_on_every_route(self):
        client = Client()
        for route, pattern in _routes("api/admin"):
            if pattern.name in OPEN_STAFF_API_ROUTES:
                continue
            self._assert_refused(client, _concrete(route), **self.bearer(self.owner))

    def test_an_unverified_console_session_is_refused_on_every_route(self):
        client = Client()
        client.force_login(self.owner)
        for route, pattern in _routes("api/admin"):
            if pattern.name in OPEN_STAFF_API_ROUTES:
                continue
            self._assert_refused(client, _concrete(route))

    def test_a_verified_console_session_is_answered(self):
        client = Client()
        staff_login(client, self.owner)
        assert client.get("/api/admin/dashboard").status_code == 200
        assert client.get("/api/admin/health/deep").status_code in (200, 503)

    def test_a_bearer_token_beside_a_verified_session_is_ignored(self):
        support = make_staff("support@example.test", AdminRole.SUPPORT)
        client = Client()
        staff_login(client, support)
        # The owner's token would open the staff accounts list; the session's
        # Support role does not, and the session is what counts.
        response = client.get("/api/admin/accounts", **self.bearer(self.owner))
        assert response.status_code == 403
        assert response.json().get("code") != two_step.TWO_STEP_REQUIRED_CODE

    def test_writes_need_the_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        staff_login(client, self.owner)
        response = client.post("/api/admin/refunds/request", {}, content_type="application/json")
        assert response.status_code == 403
        assert "CSRF" in response.json()["detail"]

    def test_the_verification_is_bound_to_the_user(self):
        other = make_staff("other@example.test", AdminRole.SUPER_ADMIN)
        client = Client()
        client.force_login(self.owner)
        verify_session(client, other)
        assert client.get("/api/admin/dashboard").status_code == 403


@override_settings(**PAGES)
class InvitationAcceptanceTests(TestCase):
    def test_accepting_answers_without_a_second_step_and_opens_nothing(self):
        owner = make_staff("owner@example.test", AdminRole.SUPER_ADMIN)
        invitation, token = AdminInvitation.issue(
            email="new@example.test", role=AdminRole.OPS, invited_by=owner
        )
        client = Client()
        response = client.post(
            "/api/admin/invitations/accept",
            {"token": token, "password": "Another-strong-pass-1", "full_name": "New"},
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"id", "email", "roles"}
        assert token not in response.content.decode()
        new = User.objects.get(email="new@example.test")
        assert not AdminTwoStep.objects.filter(user=new).exists()
        # The new account must still enrol before the console or the API answer.
        assert client.login(username="new@example.test", password="Another-strong-pass-1")
        page = client.get("/admin/users/")
        assert page.status_code == 302
        assert page["Location"].startswith(reverse("admin_console:two-step"))
        assert client.get("/api/admin/dashboard").json()["code"] == (
            two_step.TWO_STEP_REQUIRED_CODE
        )


@override_settings(**PAGES)
class ConsoleGateTests(TestCase):
    """Every console and technical admin page waits for the second step."""

    def setUp(self):
        self.owner = make_staff("owner@example.test", AdminRole.SUPER_ADMIN)
        self.open = {
            reverse("admin:login"),
            reverse("admin:logout"),
            reverse("admin-invitation-accept-page"),
        }

    def test_every_admin_route_redirects_an_unverified_session(self):
        client = Client()
        client.force_login(self.owner)
        checked = 0
        for route, _pattern in _routes("admin/"):
            path = _concrete(route)
            if path in self.open or path.startswith(reverse("admin_console:two-step")):
                continue
            response = client.get(path)
            assert response.status_code == 302, (path, response.status_code)
            assert response["Location"].startswith("/admin/two-step/?next="), path
            checked += 1
        # The console's routes and Django's technical admin (one route per
        # registered model, plus its index and app pages) are all in the walk.
        assert checked > 150

    def test_the_technical_admin_is_behind_the_second_step(self):
        client = Client()
        client.force_login(self.owner)
        for path in ("/admin/auth/group/", "/admin/accounts/user/", "/admin/technical/"):
            response = client.get(path)
            assert response.status_code == 302
            assert response["Location"].startswith("/admin/two-step/"), path
        verify_session(client, self.owner)
        assert client.get("/admin/auth/group/").status_code == 200

    def test_a_signed_out_visitor_still_gets_the_password_page(self):
        response = Client().get("/admin/users/")
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("admin:login"))

    def test_signing_in_again_asks_again(self):
        client = Client()
        staff_login(client, self.owner)
        assert client.get("/admin/users/").status_code == 200
        client.force_login(self.owner)
        assert client.get("/admin/users/").status_code == 302
        staff_login(client, self.owner)
        client.post(reverse("admin:logout"))
        client.force_login(self.owner)
        assert two_step.SESSION_KEY not in client.session


@override_settings(**PAGES)
class TwoStepPagesTests(TestCase):
    def setUp(self):
        self.user = make_staff("ops@example.test")
        self.client = Client()
        self.client.force_login(self.user)

    def test_a_server_without_the_keyring_says_so_instead_of_failing(self):
        with override_settings(PAYOUT_DATA_KEYRING="{}"):
            response = self.client.get(reverse("admin_console:two-step-enrol"))
        assert response.status_code == 503
        assert "encryption keys" in response.content.decode()
        assert not AdminTwoStep.objects.filter(user=self.user).exists()

    def test_first_sign_in_enrols_and_shows_ten_codes_once(self):
        start = self.client.get("/admin/marketplace/deals/")
        assert start["Location"] == "/admin/two-step/?next=%2Fadmin%2Fmarketplace%2Fdeals%2F"
        enrol_page = self.client.get(start["Location"], follow=True)
        assert enrol_page.redirect_chain[-1][0].startswith(reverse("admin_console:two-step-enrol"))
        html = enrol_page.content.decode()
        assert "<svg" in html and "Set up two-step sign-in" in html
        row = AdminTwoStep.objects.get(user=self.user)
        secret = two_step.secret_text(row)
        assert two_step.grouped_secret(secret) in html
        # Reloading keeps the same key.
        self.client.get(reverse("admin_console:two-step-enrol"))
        assert two_step.secret_text(AdminTwoStep.objects.get(user=self.user)) == secret

        wrong = self.client.post(
            reverse("admin_console:two-step-enrol"),
            {"code": "000000", "next": "/admin/marketplace/deals/"},
        )
        assert wrong.status_code == 400 and "did not work" in wrong.content.decode()

        code = two_step.totp(two_step._key_bytes(secret), timezone.now())
        done = self.client.post(
            reverse("admin_console:two-step-enrol"),
            {"code": code, "next": "/admin/marketplace/deals/"},
        )
        assert done.status_code == 302
        assert done["Location"].startswith(reverse("admin_console:two-step-recovery-codes"))
        shown = self.client.get(done["Location"])
        assert shown.status_code == 200
        codes = shown.context["codes"]
        assert len(codes) == 10
        for value in codes:
            assert value in shown.content.decode()
        assert "no-store" in shown["Cache-Control"]
        # Shown once: a second visit goes straight on.
        again = self.client.get(done["Location"])
        assert again.status_code == 302 and again["Location"] == "/admin/marketplace/deals/"
        assert self.client.get("/admin/marketplace/deals/").status_code == 200

    def test_verify_page_and_open_redirects(self):
        key = enrol(self.user, now=timezone.now() - timedelta(minutes=2))
        page = self.client.get("/admin/two-step/?next=https://evil.example/")
        assert page["Location"] == (
            reverse("admin_console:two-step-verify") + "?next=%2Fadmin%2F"
        )
        response = self.client.post(
            reverse("admin_console:two-step-verify"),
            {"code": two_step.totp(key, timezone.now()), "next": "//evil.example/x"},
        )
        assert response["Location"] == reverse("admin_console:overview")

    def test_lockout_is_shown(self):
        enrol(self.user, now=timezone.now() - timedelta(minutes=2))
        for _ in range(5):
            response = self.client.post(reverse("admin_console:two-step-verify"), {"code": "000000"})
        assert response.status_code == 400
        assert "locked until" in response.content.decode()

    def test_recovery_code_page_signs_in_and_warns(self):
        enrol(self.user, now=timezone.now() - timedelta(minutes=2))
        code = two_step._issue_recovery_codes(self.user)[0]
        response = self.client.post(
            reverse("admin_console:two-step-recovery"),
            {"code": code, "next": "/admin/users/"},
            follow=True,
        )
        assert response.redirect_chain[0][0] == "/admin/users/"
        assert "9 of 10 left" in response.content.decode()


class EnrolmentQrCodeTests(SimpleTestCase):
    """The enrolment QR code reaches the page whole, so an app can scan it.

    The first version drew a 285px code with no ``viewBox`` into a 220px box:
    the browser cut off its right and bottom, two of the three corner squares
    with them, and no authenticator app could read it.
    """

    def test_the_svg_is_the_whole_symbol_of_the_address_with_a_quiet_zone(self):
        uri = two_step.provisioning_uri(
            User(email="first.last-operations@example.test"), two_step._new_secret()
        )
        svg = ElementTree.fromstring(two_step.qr_svg(uri))

        # Sized in whole pixels, with a viewBox that matches: a narrower page
        # shrinks the code, whole and square, instead of cropping it.
        assert svg.get("width") == svg.get("height")
        side = int(svg.get("width").removesuffix("px"))
        assert svg.get("viewBox") == f"0 0 {side} {side}"
        group = svg.find("g")
        scale = int(re.fullmatch(r"scale\((\d+)\)", group.get("transform")).group(1))
        assert side % scale == 0
        modules = side // scale

        # Dark modules on a light square that covers the quiet zone too.
        background = group.find("path[@fill]")
        assert background.get("fill") == "#fff"
        assert background.get("d") == f"M0 0h{modules}v{modules}h-{modules}z"
        line = group.find("path[@class='qrline']")
        assert line.get("stroke") == "#14232e"

        # segno draws each run of dark modules as a one-module-high line.
        dark = set()
        x = y = 0.0
        for move, dx, dy, run in re.findall(r"([Mm])(-?[\d.]+) (-?[\d.]+)h(\d+)", line.get("d")):
            x, y = (float(dx), float(dy)) if move == "M" else (x + float(dx), y + float(dy))
            dark.update((int(y), column) for column in range(int(x), int(x) + int(run)))
            x += int(run)
        top = min(row for row, _ in dark)
        left = min(column for _, column in dark)
        symbol = segno.make(uri, error="m", micro=False).matrix
        assert {(row - top, column - left) for row, column in dark} == {
            (row, column)
            for row, cells in enumerate(symbol)
            for column, cell in enumerate(cells)
            if cell
        }
        # The quiet zone the QR standard asks for: four modules on every side.
        bottom = modules - top - len(symbol)
        right = modules - left - len(symbol)
        assert min(top, left, bottom, right) >= 4, (top, left, bottom, right)


@override_settings(**PAGES)
class ResetAndFreshCodeTests(TestCase):
    def setUp(self):
        self.owner = make_staff("owner@example.test", AdminRole.SUPER_ADMIN)
        self.target = make_staff("ops@example.test")
        enrol(self.target)
        self.target_client = Client()
        staff_login(self.target_client, self.target)
        self.client = Client()
        staff_login(self.client, self.owner)

    def reset_url(self):
        return reverse("admin_console:staff-two-step-reset", args=[self.target.pk])

    def test_reset_deletes_rows_ends_sessions_and_audits(self):
        response = self.client.post(self.reset_url(), {"reason": "Lost phone", "confirm": "on"})
        assert response.status_code == 302
        assert not AdminTwoStep.objects.filter(user=self.target).exists()
        assert not AdminRecoveryCode.objects.filter(user=self.target).exists()
        # Their session is gone: the next page asks for the password.
        page = self.target_client.get("/admin/users/")
        assert page["Location"].startswith(reverse("admin:login"))
        audit = AdminAuditLog.objects.get(action="admin.two_step_reset")
        assert (audit.actor, audit.reason, audit.target_id) == (
            self.owner, "Lost phone", str(self.target.pk)
        )
        # L15: a reset also stops the target's AI helper keys (none here).
        assert audit.metadata == {"via": "console", "sessions_ended": 1, "helper_keys_stopped": 0}
        # The owner's own session survives, and the target enrols again.
        assert self.client.get("/admin/staff/").status_code == 200
        self.target_client.force_login(self.target)
        again = self.target_client.get("/admin/users/", follow=True)
        assert again.redirect_chain[-1][0].startswith(reverse("admin_console:two-step-enrol"))

    def test_reset_needs_a_reason_and_a_fresh_code(self):
        self.client.post(self.reset_url(), {"reason": " ", "confirm": "on"})
        assert AdminTwoStep.objects.filter(user=self.target).exists()
        stale = Client()
        stale.force_login(self.owner)
        verify_session(stale, self.owner, at=timezone.now() - timedelta(minutes=11))
        response = stale.post(self.reset_url(), {"reason": "Lost phone", "confirm": "on"})
        assert response["Location"].startswith(reverse("admin_console:two-step-verify"))
        assert AdminTwoStep.objects.filter(user=self.target).exists()

    def test_no_one_resets_their_own_second_step(self):
        url = reverse("admin_console:staff-two-step-reset", args=[self.owner.pk])
        self.client.post(url, {"reason": "test", "confirm": "on"})
        assert not AdminAuditLog.objects.filter(action="admin.two_step_reset").exists()

    def test_only_manage_admins_may_reset(self):
        support = make_staff("support@example.test", AdminRole.SUPPORT)
        client = Client()
        staff_login(client, support)
        assert client.post(self.reset_url(), {"reason": "x", "confirm": "on"}).status_code == 403
        assert AdminTwoStep.objects.filter(user=self.target).exists()

    def test_role_change_needs_a_fresh_code_in_the_console_and_the_api(self):
        url = reverse("admin_console:staff-role", args=[self.target.pk])
        stale = Client()
        stale.force_login(self.owner)
        verify_session(stale, self.owner, at=timezone.now() - timedelta(minutes=11))
        response = stale.post(url, {"role": AdminRole.SUPPORT, "confirm": "on"})
        assert response["Location"].startswith(reverse("admin_console:two-step-verify"))
        api = stale.post(
            f"/api/admin/accounts/{self.target.pk}/role",
            {"role": AdminRole.SUPPORT},
            content_type="application/json",
        )
        assert api.status_code == 403
        assert api.json()["code"] == two_step.FRESH_TWO_STEP_REQUIRED_CODE
        self.target.refresh_from_db()
        assert self.target.groups.get().name == "Ops"
        # Fresh: both go through.
        fresh = self.client.post(url, {"role": AdminRole.SUPPORT, "confirm": "on"})
        assert fresh.status_code == 302
        self.target.refresh_from_db()
        assert self.target.groups.get().name == "Support"

    def test_fresh_two_step_window(self):
        request = mock.Mock(user=self.owner, session={})
        request.session[two_step.SESSION_KEY] = {
            "user": self.owner.pk,
            "at": int((timezone.now() - timedelta(minutes=9)).timestamp()),
        }
        assert two_step.fresh_two_step(request)
        request.session[two_step.SESSION_KEY]["at"] -= 120
        assert not two_step.fresh_two_step(request)
        assert two_step.two_step_satisfied(request)

    def test_server_command_resets_the_last_super_admin(self):
        enrol(self.owner)
        call_command("reset_admin_two_step", "OWNER@example.test", reason="Lost phone")
        assert not AdminTwoStep.objects.filter(user=self.owner).exists()
        assert not Session.objects.filter(
            session_key=self.client.session.session_key
        ).exists()
        audit = AdminAuditLog.objects.get(action="admin.two_step_reset")
        assert audit.actor is None
        assert audit.metadata == {"via": "manage.py", "sessions_ended": 1, "helper_keys_stopped": 0}
        with self.assertRaises(CommandError):
            call_command("reset_admin_two_step", "nobody@example.test", reason="x")


class ProductionSettingsTests(TestCase):
    def test_production_refuses_the_relaxed_flag(self):
        from apps.finance.tests.test_deployment_safety import (
            PROD_ENTRYPOINT_BOOT,
            boot_production,
        )

        relaxed = boot_production(PROD_ENTRYPOINT_BOOT, ADMIN_TWO_STEP_REQUIRED="false")
        assert relaxed.returncode != 0
        assert "ADMIN_TWO_STEP_REQUIRED must be true in production" in relaxed.stderr
        no_keys = boot_production(PROD_ENTRYPOINT_BOOT, PAYOUT_DATA_KEYRING="{}")
        assert no_keys.returncode != 0
        assert "keyring" in no_keys.stderr
        assert boot_production(PROD_ENTRYPOINT_BOOT).returncode == 0

    def test_the_gate_is_on_by_default(self):
        from django.conf import settings

        assert settings.ADMIN_TWO_STEP_REQUIRED is True
