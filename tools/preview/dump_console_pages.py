"""Render every Phase 8D console page from the throwaway preview database.

Local review tooling only; nothing imports it and CI does not run it. It signs
in with `force_login` — no credential is typed anywhere — issues GETs only, and
writes `build/adminshots/console-*.html` with `/static/` rewritten to the
running preview server so the dumps carry the real stylesheet.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.test import Client

from apps.accounts.models import User
from apps.deals.models import Deal
from apps.disputes.models import Dispute
from apps.finance.models import PaymentAttempt, PaymentRefund, Payout, ScheduledJob
from apps.kyc.models import KycSubmission
from apps.trips.models import Journey, JourneyLegProof

if "admin_preview" not in str(settings.DATABASES["default"]["NAME"]):
    raise RuntimeError("Run this against the throwaway admin preview database only.")

owner = User.objects.get(email="review-owner@example.invalid")
client = Client()
client.force_login(owner)


def first(queryset, **filters):
    row = queryset.filter(**filters).first() if filters else queryset.first()
    return row.pk if row is not None else None


kyc_pending = first(KycSubmission.objects.order_by("created_at"), status="pending")
kyc_rejected = first(KycSubmission.objects.all(), status="rejected")
proof_pending = first(JourneyLegProof.objects.all(), status="pending")
proof_rejected = first(JourneyLegProof.objects.all(), status="rejected")
multileg = Journey.objects.filter(schema_version=2).order_by("-id").first()
deal = first(Deal.objects.order_by("id"))
dispute_open = first(Dispute.objects.all(), status="under_review")
dispute_done = first(Dispute.objects.all(), status="resolved")
refund = first(PaymentRefund.objects.all())
payout = first(Payout.objects.all(), status="eligible")
payment = first(PaymentAttempt.objects.order_by("-is_unapplied", "id"))
failed_job = first(ScheduledJob.objects.all(), status="failed")
person = first(User.objects.all(), email="ok-traveler@example.com")

pages = {
    "overview": "/admin/",
    "users": "/admin/users/",
    "user-detail": f"/admin/users/{person}/",
    "kyc-queue": "/admin/verification/kyc/",
    "kyc-queue-pending": "/admin/verification/kyc/?status=pending",
    "kyc-queue-empty": "/admin/verification/kyc/?q=nobody-matches-this",
    "kyc-detail": f"/admin/verification/kyc/{kyc_pending}/",
    "kyc-detail-decided": f"/admin/verification/kyc/{kyc_rejected}/",
    "proof-queue": "/admin/verification/flight-proofs/",
    "proof-detail": f"/admin/verification/flight-proofs/{proof_pending}/",
    "proof-detail-rejected": f"/admin/verification/flight-proofs/{proof_rejected}/",
    "requests": "/admin/marketplace/requests/",
    "journeys": "/admin/marketplace/journeys/",
    "journey-detail": f"/admin/marketplace/journeys/{multileg.pk if multileg else 1}/",
    "deals": "/admin/marketplace/deals/",
    "deal-detail": f"/admin/marketplace/deals/{deal}/",
    "disputes": "/admin/disputes/",
    "dispute-detail": f"/admin/disputes/{dispute_open}/",
    "dispute-resolved": f"/admin/disputes/{dispute_done}/",
    "payments": "/admin/finance/payments/",
    "payments-attention": "/admin/finance/payments/?attention=1",
    "payment-detail": f"/admin/finance/payments/{payment}/",
    "payment-reconcile": f"/admin/finance/payments/{payment}/reconcile/",
    "payment-resolve": f"/admin/finance/payments/{payment}/resolve/",
    "refunds": "/admin/finance/refunds/",
    "refund-detail": f"/admin/finance/refunds/{refund}/",
    "payouts": "/admin/finance/payouts/",
    "payout-detail": f"/admin/finance/payouts/{payout}/",
    "ledger": "/admin/finance/ledger/",
    "staff": "/admin/staff/",
    "settings": "/admin/settings/",
    "system": "/admin/system/",
    "jobs": "/admin/system/jobs/",
    "jobs-attention": "/admin/system/jobs/?attention=1",
    "job-detail": f"/admin/system/jobs/{failed_job}/",
    "job-retry": f"/admin/system/jobs/{failed_job}/retry/",
    "job-resolve": f"/admin/system/jobs/{failed_job}/resolve/",
    "email": "/admin/system/email/",
    "geography": "/admin/system/geography/",
    "audit": "/admin/audit/",
    "technical": "/admin/technical/",
}

sample = "data:image/svg+xml," + quote(
    '<svg xmlns="http://www.w3.org/2000/svg" width="620" height="400">'
    '<rect width="620" height="400" fill="#ece6da"/>'
    '<rect x="24" y="24" width="572" height="352" fill="none" stroke="#b6ab97" stroke-dasharray="8 6"/>'
    '<text x="310" y="185" text-anchor="middle" font-family="sans-serif" font-size="26" fill="#2b3a44">Synthetic review document</text>'
    '<text x="310" y="222" text-anchor="middle" font-family="sans-serif" font-size="15" fill="#5d6b75">Layout fixture — not identity evidence</text>'
    "</svg>"
)

_STYLESHEET_VERSION = int(
    Path("apps/core/static/shiptrip/admin.css").stat().st_mtime
)
output = Path("build/adminshots")
output.mkdir(parents=True, exist_ok=True)
for name, path in pages.items():
    if "None" in path:
        print(f"skip {name}: no representative row")
        continue
    response = client.get(path)
    if response.status_code != 200:
        print(f"FAIL {name}: {response.status_code} {path}")
        continue
    html = response.content.decode().replace("<head>", '<head><meta charset="utf-8">')
    html = html.replace('"/static/', '"http://127.0.0.1:8199/static/')
    html = html.replace("'/static/", "'http://127.0.0.1:8199/static/")
    # The console stylesheet is the thing under review and it changes between
    # runs, so it gets a fresh URL each dump. Without this a browser keeps
    # showing the previous pass and the review is of a stale page.
    html = html.replace(
        "shiptrip/admin.css", f"shiptrip/admin.css?v={_STYLESHEET_VERSION}"
    )
    # Private evidence is never exported. Any in-page image that would have
    # fetched an authorized object-store URL is replaced with a visibly
    # synthetic placeholder of the same shape.
    html = re.sub(r'src="/admin/[^"]*/evidence/[^"]*"', f'src="{sample}"', html)
    (output / f"console-{name}.html").write_text(html, encoding="utf-8")
    print(f"ok  {name}")
