"""Two operator-safety properties of the account and job admins.

**Banning is not here.** The account admin had bulk "ban" and "unban"
actions that changed `is_banned` and `is_active` with no reason and no audit
row. Plan L16 removed them (advisor, 2026-11-14): an account is banned or
restored on its console person page, with a required reason, audited
(`staff_actions.set_account_ban`). These tests were rewritten to that rule;
they used to prove the bulk action asked for a second click.

**A scheduled job moves only through its action.** The finance module's own
docstring says the one mutation offered on a job is `requeue`. The change form
quietly offered more: `status`, `run_at` and `max_attempts` were editable, so a
`payout_release_check` could be marked succeeded by hand — cancelling a
scheduled money action, with nothing recorded anywhere. These hold the form
shut and the action open.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.finance.models import ScheduledJob
from apps.admin_panel.tests.two_step_helpers import staff_login

User = get_user_model()

UNHASHED_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


@UNHASHED_STATIC
class NoUnauditedBanTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(
            username="ban-ops@example.com",
            email="ban-ops@example.com",
            password="Sup3rStrong!",
        )
        staff_login(self.client, self.operator)
        self.target = User.objects.create_user(
            username="traveler@example.com",
            email="traveler@example.com",
            full_name="A Traveler",
        )

    def _post(self, action, **extra):
        return self.client.post(
            "/admin/accounts/user/",
            {"action": action, "_selected_action": [str(self.target.pk)], **extra},
            follow=True,
        )

    def test_the_account_admin_offers_no_ban_action(self):
        response = self._post("ban_users")
        body = response.content.decode()
        self.target.refresh_from_db()
        assert self.target.is_banned is False
        assert self.target.is_active is True
        assert "Ban selected users" not in body
        assert "Unban selected users" not in body

    def test_the_ban_flag_is_read_only_and_points_to_the_person_page(self):
        model_admin = admin.site._registry[User]
        request = self.client.get(f"/admin/accounts/user/{self.target.pk}/change/").wsgi_request
        form = model_admin.get_form(request, self.target)
        assert "is_banned" not in form.base_fields
        body = self.client.get(f"/admin/accounts/user/{self.target.pk}/change/").content.decode()
        assert "Ban or restore an account on its person page" in body

    def test_the_queue_reads_words_rather_than_a_red_cross_that_means_good(self):
        """`is_banned=False` and `is_kyc_verified=False` are opposite news.

        Django draws both as the same red cross. The chips carry the word, and
        the tone means the same thing in every column of the admin.
        """

        body = self.client.get("/admin/accounts/user/").content.decode()
        assert "st-chip" in body
        assert "icon-no.svg" not in body
        assert "icon-yes.svg" not in body


@UNHASHED_STATIC
class ScheduledJobSafetyTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(
            username="job-ops@example.com",
            email="job-ops@example.com",
            password="Sup3rStrong!",
        )
        staff_login(self.client, self.operator)
        self.job = ScheduledJob.objects.create(
            key="safety-payout-release",
            kind=ScheduledJob.Kind.PAYOUT_RELEASE_CHECK,
            run_at=timezone.now() + timedelta(hours=4),
            status=ScheduledJob.Status.PENDING,
        )

    def test_the_job_page_offers_nothing_to_edit(self):
        model_admin = admin.site._registry[ScheduledJob]
        request = self.client.get("/admin/finance/scheduledjob/").wsgi_request
        # The list remains inspectable; mutations live only in the audited,
        # capability-checked operations console.
        assert model_admin.has_change_permission(request) is True
        assert model_admin.has_change_permission(request, self.job) is False
        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_delete_permission(request, self.job) is False

    def test_a_post_to_the_job_page_cannot_mark_it_succeeded(self):
        response = self.client.post(
            f"/admin/finance/scheduledjob/{self.job.pk}/change/",
            {"status": ScheduledJob.Status.SUCCEEDED, "run_at_0": "2026-01-01"},
        )
        self.job.refresh_from_db()
        assert response.status_code in (302, 403)
        assert self.job.status == ScheduledJob.Status.PENDING

    def test_raw_admin_has_no_unaudited_requeue_action(self):
        dead = ScheduledJob.objects.create(
            key="safety-dead-job",
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            run_at=timezone.now() - timedelta(hours=1),
            status=ScheduledJob.Status.FAILED,
            attempts=8,
        )
        response = self.client.post(
            "/admin/finance/scheduledjob/",
            {
                "action": "requeue_jobs",
                "_selected_action": [str(dead.pk), str(self.job.pk)],
            },
            follow=True,
        )
        dead.refresh_from_db()
        self.job.refresh_from_db()
        assert dead.status == ScheduledJob.Status.FAILED
        assert self.job.status == ScheduledJob.Status.PENDING
        assert "Requeue selected jobs" not in response.content.decode()

    def test_the_attempt_budget_reads_as_a_position_not_a_bare_number(self):
        body = self.client.get("/admin/finance/scheduledjob/").content.decode()
        assert f"{self.job.attempts} / {self.job.max_attempts}" in body
