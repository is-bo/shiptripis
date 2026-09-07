"""Phase 8F-G2: a queue row opens the record it stands for, everywhere.

The behaviour under test is a discoverability fix, not a new capability. Before
this, a KYC submission was opened by clicking the applicant's name and nothing
else, and the other nine tenths of the row looked exactly the same as the live
tenth. The fix keeps the anchor exactly where it was — so keyboard, screen
reader, middle-click and "open in new tab" are untouched — and marks the row
around it as a click surface.

So these tests assert the two halves that make that safe:

  * every openable row carries exactly one real ``<a href>`` marked
    ``data-row-primary``, which is what a keyboard actually follows; and
  * a row still containing a checkbox, a secondary link or an action does not
    lose them to the surface.

They also pin the parts that must NOT have changed: which queues are openable
(only those with a detail page), the G1 recovery controls, and role scoping.
"""

from __future__ import annotations

from datetime import timedelta
from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.console_views import _table
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.finance.models import ScheduledJob
from apps.kyc.models import KycSubmission
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

User = get_user_model()

UNHASHED_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


class _RowParser(HTMLParser):
    """Collect table rows with the attributes this contract depends on.

    Deliberately a parser rather than substring assertions: "the response
    contains data-row-primary somewhere" would pass for a page that put the
    marker on the wrong row, or on two anchors in one row, which is precisely
    the failure mode worth catching.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._row: dict | None = None
        self._anchor: dict | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "tr":
            self._row = {
                "openable": "data-row-link" in attributes,
                "links": [],
                "primaries": [],
                "controls": [],
            }
            return
        if self._row is None:
            return
        if tag == "a":
            self._anchor = {
                "href": attributes.get("href", ""),
                "primary": "data-row-primary" in attributes,
                "aria_label": attributes.get("aria-label", ""),
                "text": "",
            }
            return
        if tag in {"input", "button", "select", "textarea"}:
            self._row["controls"].append(
                {"tag": tag, "type": attributes.get("type", ""), **attributes}
            )

    def handle_data(self, data):
        if self._anchor is not None:
            self._anchor["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None and self._row is not None:
            self._anchor["text"] = self._anchor["text"].strip()
            self._row["links"].append(self._anchor)
            if self._anchor["primary"]:
                self._row["primaries"].append(self._anchor)
            self._anchor = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def rows_of(html: str) -> list[dict]:
    parser = _RowParser()
    parser.feed(html)
    return parser.rows


def body_rows(html: str) -> list[dict]:
    """Rows that carry data, i.e. everything but the header row."""

    return [row for row in rows_of(html) if row["links"] or row["controls"]]


class ConsoleRowsMixin:
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username="g2-owner@example.com",
            email="g2-owner@example.com",
            password="Sup3rStrong!",
        )
        self.client.force_login(self.owner)

    def html(self, path, user=None):
        self.client.force_login(user or self.owner)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


@UNHASHED_STATIC
class OpenableRowContractTests(ConsoleRowsMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.applicant = User.objects.create_user(
            username="g2-applicant@example.com",
            email="g2-applicant@example.com",
            full_name="Amina Applicant",
        )
        self.submission = KycSubmission.objects.create(
            user=self.applicant,
            document_type=KycSubmission.DocumentType.PASSPORT,
            idempotency_key="phase8fg2-kyc-000000000001",
            front_image_key="kyc/private/front.jpg",
            selfie_image_key="kyc/private/selfie.jpg",
            status=KycSubmission.Status.PENDING,
        )

    def test_a_kyc_row_opens_the_review_from_anywhere_in_the_row(self):
        """The owner's reported problem, stated as a contract.

        The row is a surface (`data-row-link`) and the applicant's name is
        still the anchor (`data-row-primary`) — the click target grew, the
        navigation target did not move.
        """

        html = self.html(reverse("admin_console:kyc-queue"))
        rows = body_rows(html)
        self.assertEqual(len(rows), 1)
        row = rows[0]

        self.assertTrue(row["openable"])
        self.assertEqual(len(row["primaries"]), 1)
        self.assertEqual(
            row["primaries"][0]["href"],
            reverse("admin_console:kyc-detail", args=(self.submission.pk,)),
        )
        self.assertEqual(row["primaries"][0]["text"], "Amina Applicant")

    def test_the_open_affordance_is_announced_but_not_read_twice(self):
        """The chevron column is a mark for the eye and silent to a reader.

        Its header carries the word; the per-row cell is `aria-hidden`, because
        a screen reader that heard "Open" on every row would be hearing the
        same link twice.
        """

        html = self.html(reverse("admin_console:kyc-queue"))

        self.assertIn('<th scope="col" class="st-row-go">', html)
        self.assertIn('<span class="st-visually-hidden">Open</span>', html)
        self.assertIn('<td class="st-row-go" aria-hidden="true">', html)

    def test_the_primary_target_is_a_real_anchor_a_keyboard_can_reach(self):
        """No `role="button"`, no div, no JavaScript-only target.

        This is the whole accessibility argument for the feature: the row
        surface is an addition, and removing every script from the page would
        still leave a focusable link that Enter follows.
        """

        html = self.html(reverse("admin_console:kyc-queue"))
        primary = body_rows(html)[0]["primaries"][0]

        self.assertTrue(primary["href"].startswith("/admin/"))
        detail = self.html(primary["href"])
        self.assertIn("Amina Applicant", detail)

    def test_every_queue_with_a_detail_page_is_openable_and_no_other_is(self):
        """Only a row that stands for one record gets a click surface.

        An audit entry, a ledger transaction and an outbound message have no
        detail page, so a row surface there would promise a page that does not
        exist. They must stay inert.
        """

        openable = (
            reverse("admin_console:users"),
            reverse("admin_console:kyc-queue"),
        )
        for path in openable:
            with self.subTest(path=path):
                rows = body_rows(self.html(path))
                self.assertTrue(rows)
                for row in rows:
                    self.assertTrue(row["openable"])
                    self.assertEqual(len(row["primaries"]), 1)

        for path in (
            reverse("admin_console:audit"),
            reverse("admin_console:ledger"),
            reverse("admin_console:email"),
            reverse("admin_console:requests"),
        ):
            with self.subTest(path=path):
                html = self.html(path)
                self.assertNotIn("data-row-link", html)
                self.assertNotIn("data-row-primary", html)
                self.assertNotIn('class="st-row-go"', html)

    def test_a_row_may_declare_only_one_primary_cell(self):
        """Two click targets on one surface is a bug, not a preference.

        A row whose surface could open either of two records is worse than one
        that opens nothing, so the table helper refuses to render it rather
        than picking a winner.
        """

        from apps.admin_panel.console_presenters import text_cell

        request = self.client.get(reverse("admin_console:kyc-queue")).wsgi_request
        rows = [
            {
                "cells": (
                    text_cell("One", href="/admin/users/1/", opens_row=True),
                    text_cell("Two", href="/admin/users/2/", opens_row=True),
                )
            }
        ]
        with self.assertRaises(ValueError) as raised:
            _table(
                request,
                title="Ambiguous",
                description="",
                columns=("One", "Two"),
                rows=rows,
                page_obj=None,
                empty_title="",
                empty_text="",
            )
        self.assertIn("exactly one cell may open the row", str(raised.exception))

    def test_the_shared_activation_script_is_loaded_once_for_every_screen(self):
        """One delegated listener, declared in the base template.

        The alternative the brief ruled out is a snippet per page; this asserts
        there is not one.
        """

        html = self.html(reverse("admin_console:kyc-queue"))

        self.assertIn("shiptrip/console.js", html)
        self.assertEqual(html.count("shiptrip/console.js"), 1)
        self.assertNotIn("onclick=", html)


@UNHASHED_STATIC
class NestedControlTests(ConsoleRowsMixin, TestCase):
    """A row surface must not swallow the controls inside it."""

    def setUp(self):
        super().setUp()
        self.job = ScheduledJob.objects.create(
            kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
            key="phase8fg2-job-1",
            payload={"message_id": 4242},
            run_at=timezone.now() - timedelta(hours=2),
            status=ScheduledJob.Status.FAILED,
            attempts=8,
            max_attempts=8,
            last_error_code="permanent_failure",
        )

    def test_a_job_row_keeps_its_checkbox_and_its_secondary_link(self):
        """Three targets in one row, each still its own.

        The bulk-select checkbox belongs to the bulk form, the related-object
        link belongs to that object, and only the row's own `Review` anchor is
        the surface's target.
        """

        html = self.html(f'{reverse("admin_console:jobs")}?attention=1')
        rows = body_rows(html)
        self.assertEqual(len(rows), 1)
        row = rows[0]

        self.assertTrue(row["openable"])
        checkboxes = [
            control
            for control in row["controls"]
            if control["type"] == "checkbox" and control.get("name") == "job_ids"
        ]
        self.assertEqual(len(checkboxes), 1)
        self.assertEqual(checkboxes[0]["value"], str(self.job.pk))

        self.assertEqual(len(row["primaries"]), 1)
        self.assertEqual(
            row["primaries"][0]["href"],
            reverse("admin_console:job-detail", args=(self.job.pk,)),
        )

        # The related-object link is present, is a different destination, and
        # is deliberately not the row's target.
        secondary = [link for link in row["links"] if not link["primary"]]
        self.assertTrue(secondary)
        for link in secondary:
            self.assertNotEqual(link["href"], row["primaries"][0]["href"])

    def test_a_generic_review_link_still_names_its_record_to_a_reader(self):
        """"Review" out of context names nothing; the accessible name does.

        The visible word is kept as the first word of the accessible name, so
        someone using voice control can still say "Review".
        """

        html = self.html(f'{reverse("admin_console:jobs")}?attention=1')
        primary = body_rows(html)[0]["primaries"][0]

        self.assertEqual(primary["text"], "Review")
        self.assertEqual(
            primary["aria_label"], f"Review background job {self.job.pk}"
        )

    def test_g1_recovery_controls_and_history_filters_are_unchanged(self):
        """Phase 8F-G1 semantics survive a visual pass.

        The counters, the two queue slices, the bulk form and its required
        reason and confirmation are all still here; only their weight changed.
        """

        html = self.html(f'{reverse("admin_console:jobs")}?attention=1')

        self.assertIn("Actionable failures", html)
        self.assertIn("Resolved history", html)
        self.assertIn("Act on selected terminal jobs", html)
        self.assertIn('name="reason"', html)
        self.assertIn('name="confirm"', html)
        self.assertIn("Apply audited action", html)

        detail = self.html(
            reverse("admin_console:job-detail", args=(self.job.pk,))
        )
        self.assertIn("Retry now", detail)
        self.assertIn("Resolve or dismiss", detail)
        # Retry leads and closing without re-running follows; both are present.
        self.assertIn("st-button-quiet", detail)

    def test_the_history_slice_marks_which_one_is_being_shown(self):
        """Two view switches, not two primary actions.

        Both are quiet; the one already showing carries the selected mark. The
        page previously rendered them as two equally weighted dark buttons,
        which read as a decision the page is not asking for.
        """

        history = self.html(f'{reverse("admin_console:jobs")}?history=resolved')
        self.assertIn(
            '<a class="button st-button-quiet is-current" '
            'href="/admin/system/jobs/?history=resolved" aria-current="page">'
            "Resolved history</a>",
            history,
        )
        self.assertIn(
            '<a class="button st-button-quiet" '
            'href="/admin/system/jobs/?attention=1">Actionable failures</a>',
            history,
        )

        attention = self.html(f'{reverse("admin_console:jobs")}?attention=1')
        self.assertIn(
            '<a class="button st-button-quiet is-current" '
            'href="/admin/system/jobs/?attention=1" aria-current="page">'
            "Actionable failures</a>",
            attention,
        )


@UNHASHED_STATIC
class RowScopeTests(ConsoleRowsMixin, TestCase):
    """A click surface never widens what a role can reach."""

    def setUp(self):
        super().setUp()
        self.support = User.objects.create_user(
            username="g2-support@example.com",
            email="g2-support@example.com",
        )
        assign_admin_roles(self.support, (AdminRole.SUPPORT,))

    def test_support_still_cannot_open_the_kyc_queue_at_all(self):
        self.client.force_login(self.support)
        response = self.client.get(reverse("admin_console:kyc-queue"))
        self.assertEqual(response.status_code, 403)

    def test_a_flight_proof_row_behaves_the_same_as_a_kyc_row(self):
        """Consistency is the point: the two review queues cannot differ."""

        traveler = User.objects.create_user(
            username="g2-traveler@example.com",
            email="g2-traveler@example.com",
            full_name="Tarek Traveler",
        )
        journey = Journey.objects.create(traveler=traveler)
        leg = JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode="FLIGHT",
            depart_at=timezone.now() + timedelta(days=3),
            capacity_kg="10.00",
            flight_number="AH1009",
        )
        proof = JourneyLegProof.objects.create(
            leg=leg,
            bucket="private-proof",
            object_key=f"journeys/{leg.pk}/proof.jpg",
        )

        rows = body_rows(self.html(reverse("admin_console:proof-queue")))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["openable"])
        self.assertEqual(
            rows[0]["primaries"][0]["href"],
            reverse("admin_console:proof-detail", args=(proof.pk,)),
        )
        self.assertEqual(rows[0]["primaries"][0]["text"], "Tarek Traveler")
