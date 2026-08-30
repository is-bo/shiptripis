"""Render admin pages to static HTML for visual review.

Uses `force_login` rather than the login form: nobody types a credential into a
page here, and the point of the exercise is what an authenticated operator
sees. Static URLs are rewritten to the running dev server so the dumps carry
the real stylesheet.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import Client

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.disputes.models import Dispute
from apps.finance.models import PaymentOrder, PaymentRefund


# --- local toolchain shim, not shipped -------------------------------------
# Django 5.1.4 copies a template context with `copy(super())`. Under Python
# 3.14 `copy.copy` on a `super` proxy returns the proxy itself, so the next
# line raises. CI and the image both pin Python 3.12, where this path is fine;
# this shim exists only so the admin can be rendered on this machine.
from django.template.context import BaseContext  # noqa: E402


def _base_context_copy(self):
    duplicate = BaseContext.__new__(type(self))
    duplicate.__dict__.update(self.__dict__)
    duplicate.dicts = self.dicts[:]
    return duplicate


BaseContext.__copy__ = _base_context_copy
# ---------------------------------------------------------------------------

OUT = Path("build/adminshots")
OUT.mkdir(parents=True, exist_ok=True)
STATIC_ORIGIN = "http://127.0.0.1:8199"

operator, _ = User.objects.get_or_create(
    email="ops@example.com",
    defaults={"username": "ops@example.com", "full_name": "Operations"},
)
operator.is_staff = True
operator.is_superuser = True
operator.is_active = True
operator.save()

client = Client()
client.force_login(operator)

dispute = Dispute.objects.filter(status="under_review").first()
resolved = Dispute.objects.filter(status="resolved").first()
order = PaymentOrder.objects.order_by("-amount_eur_cents").first()
refund = PaymentRefund.objects.filter(requires_manual_action=True).first()
settings_version = BusinessSettingsVersion.objects.filter(status="active").first()

PAGES = {
    "index": "/admin/",
    "users": "/admin/accounts/user/",
    "kyc": "/admin/kyc/kycsubmission/",
    "proofs": "/admin/trips/journeylegproof/",
    "requests": "/admin/parcels/deliveryrequest/",
    "deals": "/admin/deals/deal/",
    "journeys": "/admin/trips/journey/",
    "offers": "/admin/matching/offer/",
    "disputes": "/admin/disputes/dispute/",
    "dispute-detail": f"/admin/disputes/dispute/{dispute.pk}/change/" if dispute else "",
    "dispute-resolved": f"/admin/disputes/dispute/{resolved.pk}/change/" if resolved else "",
    "orders": "/admin/finance/paymentorder/",
    "order-detail": f"/admin/finance/paymentorder/{order.pk}/change/" if order else "",
    "attempts": "/admin/finance/paymentattempt/",
    "provider-events": "/admin/finance/paymentproviderevent/",
    "refunds": "/admin/finance/paymentrefund/",
    "refund-detail": f"/admin/finance/paymentrefund/{refund.pk}/change/" if refund else "",
    "payouts": "/admin/finance/payout/",
    "jobs": "/admin/finance/scheduledjob/",
    "settings": "/admin/core/businesssettingsversion/",
    "settings-detail": (
        f"/admin/core/businesssettingsversion/{settings_version.pk}/change/"
        if settings_version
        else ""
    ),
    "outbox": "/admin/notifications/outboundmessage/",
    "audit": "/admin/admin_panel/adminauditlog/",
    "handover": "/admin/handover/dealhandovercode/",
}

for name, url in PAGES.items():
    if not url:
        print(f"SKIP {name}: no row")
        continue
    response = client.get(url, follow=True)
    if response.status_code != 200:
        print(f"FAIL {name} {url} -> {response.status_code}")
        continue
    html = response.content.decode("utf-8")
    html = re.sub(r'(href|src)="/static/', rf'\1="{STATIC_ORIGIN}/static/', html)
    # Django serves these with `charset=utf-8` on the response header; the
    # throwaway file server used to view the dumps does not, so the
    # declaration is written into the document rather than read as latin-1.
    html = html.replace("<head>", '<head>\n<meta charset="utf-8">', 1)
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")
    print(f"OK   {name:18} {url}")
