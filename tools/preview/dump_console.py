"""Render Phase 8D task pages using an isolated in-memory review database.

Run via manage.py shell with config.settings.test_local. No existing preview
database is touched, no email is sent, and only the test payment rail is used.
Evidence previews use a visibly synthetic SVG in the exported HTML only.
"""

from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.management import call_command
from django.test import Client, override_settings

from apps.accounts.models import User
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.deals.tests.phase4_factories import delivered_scenario
from apps.disputes.models import Dispute
from apps.disputes.services import open_dispute
from apps.kyc.models import KycSubmission

if settings.DATABASES["default"]["NAME"] != ":memory:":
    raise RuntimeError("This review tool requires an isolated in-memory database.")

call_command("migrate", verbosity=0)
client = Client()
scenario = delivered_scenario(client, prefix="phase8d-review")
dispute = open_dispute(
    deal_id=scenario.deal.pk,
    actor_id=scenario.sender.pk,
    category=Dispute.Category.DAMAGED,
    reason_text="Review fixture: package arrived damaged.",
)
owner = User.objects.create_superuser(
    username="owner-review@example.invalid",
    email="owner-review@example.invalid",
    full_name="Review Owner",
)
staff = User.objects.create_user(
    username="support-review@example.invalid",
    email="support-review@example.invalid",
    full_name="Support Operator",
)
assign_admin_roles(staff, (AdminRole.SUPPORT,))
submission = KycSubmission.objects.create(
    user=scenario.outsider,
    document_type="passport",
    status="pending",
    idempotency_key="phase8d-review-pending-identity",
    front_image_key="synthetic/front.jpg",
    selfie_image_key="synthetic/selfie.jpg",
)
pages = {
    "overview": "/admin/",
    "staff": "/admin/staff/",
    "settings": "/admin/settings/",
    "system": "/admin/system/",
    "kyc-detail": f"/admin/verification/kyc/{submission.pk}/",
    "dispute": f"/admin/disputes/{dispute.pk}/",
    "payments": "/admin/finance/payments/",
}
output = Path("build/adminshots")
output.mkdir(parents=True, exist_ok=True)
sample = "data:image/svg+xml," + quote(
    '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="260"><rect width="500" height="260" fill="#ede8df"/><text x="250" y="115" text-anchor="middle" font-family="sans-serif" font-size="24" fill="#263b36">Synthetic review document</text><text x="250" y="155" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#536b64">Layout fixture — not identity evidence</text></svg>'
)
with override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
):
    client.force_login(owner)
    for name, path in pages.items():
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        html = response.content.decode().replace(
            "<head>", '<head><meta charset="utf-8">'
        )
        html = html.replace('"/static/', '"http://127.0.0.1:8199/static/')
        for slot in ("front", "selfie"):
            html = html.replace(
                f'src="/admin/verification/kyc/{submission.pk}/evidence/{slot}/"',
                f'src="{sample}"',
            )
        (output / f"phase8d-{name}.html").write_text(html, encoding="utf-8")
        print(f"Rendered {name}: {response.status_code}")
