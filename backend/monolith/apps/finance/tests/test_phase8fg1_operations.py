"""Phase 8F-G1 failed-job recovery and finance-attention contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from importlib import import_module
from io import StringIO
from unittest.mock import patch

from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance import jobs
from apps.finance.models import PaymentAttempt, ScheduledJob
from apps.finance.operations import (
    FinanceOperationsError,
    payment_attention_queryset,
    resolve_failed_job,
    resolve_payment_attention,
    retry_failed_job,
)
from apps.notifications.models import OutboundMessage

from .factories import build_scenario, open_mock_checkout


LOCAL_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


class JobFailureClassificationTests(TestCase):
    def test_data_migration_classifies_only_email_kill_switch_exhaustion(self):
        real_message = OutboundMessage.objects.create(
            key="legacy-real-message",
            kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
            to_email="recipient@example.com",
        )
        synthetic_message = OutboundMessage.objects.create(
            key="legacy-synthetic-message",
            kind=OutboundMessage.Kind.EMAIL_VERIFICATION,
            to_email="phase8@shiptrip-test.invalid",
        )
        disabled = ScheduledJob.objects.create(
            key="legacy-email-disabled",
            kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
            payload={"message_id": real_message.pk},
            run_at=timezone.now() - timedelta(days=1),
            status=ScheduledJob.Status.FAILED,
            attempts=10,
            max_attempts=10,
            last_error="JobFailed: transactional email is disabled",
            completed_at=timezone.now() - timedelta(days=1),
        )
        synthetic = ScheduledJob.objects.create(
            key="legacy-email-disabled-synthetic",
            kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
            payload={"message_id": synthetic_message.pk},
            run_at=timezone.now() - timedelta(days=1),
            status=ScheduledJob.Status.FAILED,
            attempts=10,
            max_attempts=10,
            last_error="JobFailed: transactional email is disabled",
            completed_at=timezone.now() - timedelta(days=1),
        )
        other = ScheduledJob.objects.create(
            key="legacy-real-failure",
            kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
            run_at=timezone.now() - timedelta(days=1),
            status=ScheduledJob.Status.FAILED,
            attempts=10,
            max_attempts=10,
            last_error="JobFailed: SMTP unavailable",
            completed_at=timezone.now() - timedelta(days=1),
        )

        migration = import_module(
            "apps.finance.migrations.0008_paymentattempt_operational_resolution_and_more"
        )
        migration.classify_existing_jobs(django_apps, None)

        disabled.refresh_from_db()
        synthetic.refresh_from_db()
        synthetic_message.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(disabled.status, ScheduledJob.Status.PENDING)
        self.assertEqual(disabled.attempts, 10)
        self.assertEqual(disabled.last_result, "deferred:email_disabled")
        self.assertEqual(synthetic.status, ScheduledJob.Status.FAILED)
        self.assertEqual(synthetic.resolution, ScheduledJob.Resolution.DISMISSED)
        self.assertEqual(synthetic.attempts, 10)
        self.assertEqual(synthetic_message.status, OutboundMessage.Status.CANCELLED)
        self.assertEqual(other.status, ScheduledJob.Status.FAILED)
        self.assertEqual(
            AdminAuditLog.objects.filter(
                reference="phase8fg1",
                target_id__in=(str(disabled.pk), str(synthetic.pk)),
            ).count(),
            2,
        )

    def test_disabled_email_is_deferred_without_consuming_attempts(self):
        job = ScheduledJob.objects.create(
            key="email-disabled",
            kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
            payload={"message_id": 1},
            run_at=timezone.now(),
            status=ScheduledJob.Status.RUNNING,
            attempts=9,
            max_attempts=10,
        )
        with patch(
            "apps.notifications.outbox.dispatch_message", return_value="disabled"
        ):
            result = jobs.run_job(job)

        job.refresh_from_db()
        self.assertEqual(result, "deferred")
        self.assertEqual(job.status, ScheduledJob.Status.PENDING)
        self.assertEqual(job.attempts, 9)
        self.assertEqual(job.last_result, "deferred:email_disabled")
        self.assertEqual(job.last_error, "")
        self.assertGreater(job.run_at, timezone.now())

    def test_invalid_payload_is_terminal_on_the_first_attempt(self):
        job = ScheduledJob.objects.create(
            key="bad-payload",
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            payload={"attempt_id": "not-an-integer"},
            run_at=timezone.now(),
            status=ScheduledJob.Status.RUNNING,
            max_attempts=8,
        )

        self.assertEqual(jobs.run_job(job), "failed")

        job.refresh_from_db()
        self.assertEqual(job.status, ScheduledJob.Status.FAILED)
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.last_error_code, "invalid_payload")
        self.assertIsNotNone(job.completed_at)

    def test_retryable_failure_uses_bounded_backoff_and_safe_category(self):
        job = ScheduledJob.objects.create(
            key="transient",
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            payload={},
            run_at=timezone.now(),
            status=ScheduledJob.Status.RUNNING,
            max_attempts=2,
        )

        def fail(_payload):
            raise jobs.RetryableJobError(
                "Temporary provider outage.", code="provider_unavailable"
            )

        with patch.dict(jobs.HANDLERS, {ScheduledJob.Kind.ATTEMPT_EXPIRY: fail}):
            self.assertEqual(jobs.run_job(job), "failed")
            job.refresh_from_db()
            self.assertEqual(job.status, ScheduledJob.Status.PENDING)
            self.assertEqual(job.last_error_code, "provider_unavailable")
            job.status = ScheduledJob.Status.RUNNING
            job.save(update_fields=("status", "updated_at"))
            self.assertEqual(jobs.run_job(job), "failed")

        job.refresh_from_db()
        self.assertEqual(job.status, ScheduledJob.Status.FAILED)
        self.assertEqual(job.attempts, 2)


class FinanceOperationsTests(TestCase):
    def setUp(self):
        active = get_active_business_settings()
        policy = deepcopy(active.policy)
        policy["payments"]["providers"]["mock_enabled"] = True
        BusinessSettingsVersion.objects.filter(pk=active.pk).update(policy=policy)
        self.scenario = build_scenario(prefix="g1-ops")
        self.scenario.accept(reward_eur_cents=3_200)
        self.attempt = open_mock_checkout(self.scenario.balance_order())

    def test_normal_decline_is_history_but_amount_anomaly_needs_attention(self):
        PaymentAttempt.objects.filter(pk=self.attempt.pk).update(
            status=PaymentAttempt.Status.FAILED,
            failure_code="provider_error",
        )
        self.assertFalse(
            payment_attention_queryset().filter(pk=self.attempt.pk).exists()
        )

        PaymentAttempt.objects.filter(pk=self.attempt.pk).update(
            failure_code="amount_mismatch"
        )
        self.assertTrue(
            payment_attention_queryset().filter(pk=self.attempt.pk).exists()
        )

    def test_unapplied_money_cannot_be_dismissed_without_a_full_refund(self):
        PaymentAttempt.objects.filter(pk=self.attempt.pk).update(
            status=PaymentAttempt.Status.SUCCEEDED,
            is_unapplied=True,
        )
        with self.assertRaises(FinanceOperationsError) as caught:
            resolve_payment_attention(
                attempt_id=self.attempt.pk,
                actor_id=self.scenario.admin.pk,
                resolution=PaymentAttempt.OperationalResolution.DISMISSED,
                reason="Reviewed",
            )
        self.assertEqual(caught.exception.code, "unapplied_money_unsettled")

    @LOCAL_STATIC
    def test_unapplied_payment_detail_uses_attention_state_not_success_tone(self):
        PaymentAttempt.objects.filter(pk=self.attempt.pk).update(
            status=PaymentAttempt.Status.SUCCEEDED,
            is_unapplied=True,
        )
        assign_admin_roles(self.scenario.admin, (AdminRole.FINANCE,))
        self.client.force_login(self.scenario.admin)

        body = self.client.get(
            f"/admin/finance/payments/{self.attempt.pk}/"
        ).content.decode()

        self.assertIn("Needs finance review", body)
        self.assertIn("st-attn", body)

    def test_retry_and_resolution_are_row_locked_state_changes_only(self):
        job = ScheduledJob.objects.create(
            key="operator-job",
            kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
            payload={"message_id": 999},
            run_at=timezone.now(),
            status=ScheduledJob.Status.FAILED,
            attempts=10,
            max_attempts=10,
            completed_at=timezone.now(),
        )
        requeued = retry_failed_job(job_id=job.pk)
        self.assertEqual(requeued.status, ScheduledJob.Status.PENDING)
        self.assertEqual(requeued.attempts, 0)

        ScheduledJob.objects.filter(pk=job.pk).update(
            status=ScheduledJob.Status.FAILED, completed_at=timezone.now()
        )
        resolved = resolve_failed_job(
            job_id=job.pk,
            actor_id=self.scenario.admin.pk,
            resolution=ScheduledJob.Resolution.DISMISSED,
            reason="Synthetic QA obligation",
        )
        self.assertEqual(resolved.status, ScheduledJob.Status.FAILED)
        self.assertEqual(resolved.resolution, ScheduledJob.Resolution.DISMISSED)
        self.assertTrue(ScheduledJob.objects.filter(pk=job.pk).exists())


class ScheduledJobPruneCommandTests(TestCase):
    def setUp(self):
        old = timezone.now() - timedelta(days=100)
        self.succeeded = ScheduledJob.objects.create(
            key="old-succeeded",
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            run_at=old,
            status=ScheduledJob.Status.SUCCEEDED,
            completed_at=old,
        )
        self.resolved = ScheduledJob.objects.create(
            key="old-resolved",
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            run_at=old,
            status=ScheduledJob.Status.FAILED,
            completed_at=old,
            resolution=ScheduledJob.Resolution.DISMISSED,
            resolved_at=old,
            resolution_reason="Reviewed",
        )
        self.unresolved = ScheduledJob.objects.create(
            key="old-unresolved",
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            run_at=old,
            status=ScheduledJob.Status.FAILED,
            completed_at=old,
        )

    def test_command_is_dry_run_by_default_and_never_prunes_unresolved(self):
        output = StringIO()
        call_command("prune_scheduled_jobs", stdout=output)
        self.assertIn("dry-run: 2", output.getvalue())
        self.assertEqual(ScheduledJob.objects.count(), 3)

        call_command("prune_scheduled_jobs", execute=True, stdout=StringIO())
        self.assertFalse(ScheduledJob.objects.filter(pk=self.succeeded.pk).exists())
        self.assertFalse(ScheduledJob.objects.filter(pk=self.resolved.pk).exists())
        self.assertTrue(ScheduledJob.objects.filter(pk=self.unresolved.pk).exists())


@LOCAL_STATIC
class OperationsConsoleRecoveryTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.owner = User.objects.create_superuser(
            username="g1-owner@example.com",
            email="g1-owner@example.com",
            password="Sup3rStrong!",
        )
        self.finance = User.objects.create_user(
            username="g1-finance@example.com", email="g1-finance@example.com"
        )
        assign_admin_roles(self.finance, (AdminRole.FINANCE,))
        self.ops = User.objects.create_user(
            username="g1-ops@example.com", email="g1-ops@example.com"
        )
        assign_admin_roles(self.ops, (AdminRole.OPS,))
        self.support = User.objects.create_user(
            username="g1-support@example.com", email="g1-support@example.com"
        )
        assign_admin_roles(self.support, (AdminRole.SUPPORT,))

    def job(
        self,
        *,
        kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
        suffix="one",
        message_id=999,
    ):
        return ScheduledJob.objects.create(
            key=f"console-{suffix}",
            kind=kind,
            payload={"message_id": message_id},
            run_at=timezone.now(),
            status=ScheduledJob.Status.FAILED,
            attempts=10,
            max_attempts=10,
            completed_at=timezone.now(),
            last_error_code="email_disabled",
        )

    def post_as(self, user, path, data):
        self.client.force_login(user)
        return self.client.post(path, data)

    def test_retry_requires_confirmation_and_is_audited(self):
        job = self.job()
        path = f"/admin/system/jobs/{job.pk}/retry/"
        self.assertEqual(
            self.post_as(self.ops, path, {"reason": "Email enabled"}).status_code,
            200,
        )
        job.refresh_from_db()
        self.assertEqual(job.status, ScheduledJob.Status.FAILED)

        response = self.post_as(
            self.ops, path, {"reason": "Email enabled", "confirm": "on"}
        )
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, ScheduledJob.Status.PENDING)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action="scheduled_job.retry_queued", target_id=str(job.pk)
            ).exists()
        )

    def test_role_is_checked_against_the_specific_job_kind(self):
        finance_job = self.job(
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE, suffix="finance"
        )
        path = f"/admin/system/jobs/{finance_job.pk}/retry/"
        data = {"reason": "Provider recovered", "confirm": "on"}
        self.assertEqual(self.post_as(self.ops, path, data).status_code, 403)
        self.assertEqual(self.post_as(self.support, path, data).status_code, 403)
        self.assertEqual(self.post_as(self.finance, path, data).status_code, 302)

    def test_bulk_dismiss_requires_reason_and_retains_rows(self):
        message = OutboundMessage.objects.create(
            key="bulk-dismiss-message",
            kind=OutboundMessage.Kind.EMAIL_VERIFICATION,
            to_email="qa@shiptrip-test.invalid",
        )
        first = self.job(suffix="bulk-a", message_id=message.pk)
        second = self.job(suffix="bulk-b")
        response = self.post_as(
            self.ops,
            "/admin/system/jobs/bulk/",
            {
                "job_ids": [str(first.pk), str(second.pk)],
                "action": "dismiss",
                "reason": "Synthetic QA messages",
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            ScheduledJob.objects.filter(
                pk__in=(first.pk, second.pk),
                resolution=ScheduledJob.Resolution.DISMISSED,
            ).count(),
            2,
        )
        self.assertEqual(
            ScheduledJob.objects.filter(pk__in=(first.pk, second.pk)).count(), 2
        )
        message.refresh_from_db()
        self.assertEqual(message.status, OutboundMessage.Status.CANCELLED)

    def test_overview_and_default_failed_queue_ignore_resolved_history(self):
        active = self.job(suffix="active")
        resolved = self.job(suffix="resolved")
        ScheduledJob.objects.filter(pk=resolved.pk).update(
            resolution=ScheduledJob.Resolution.DISMISSED,
            resolved_at=timezone.now(),
            resolution_reason="Reviewed",
        )
        self.client.force_login(self.owner)
        overview = self.client.get("/admin/").content.decode()
        self.assertIn("Background jobs needing attention", overview)
        response = self.client.get("/admin/system/jobs/?status=failed")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        detail = self.client.get(f"/admin/system/jobs/{active.pk}/").content.decode()
        self.assertIn("email_disabled", detail)
        history = self.client.get("/admin/system/jobs/?history=resolved")
        self.assertEqual(history.context["page_obj"].paginator.count, 1)
