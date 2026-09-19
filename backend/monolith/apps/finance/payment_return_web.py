"""The page a payment provider sends the payer's browser back to (J7D).

Stripe and Chargily both finish a hosted checkout by sending the browser to
`/pay/<reference>/return?result=success|failure`. Until J7D that page said the
same thing whatever happened, because the redirect is not evidence. It still is
not: **the query string never decides what this page says.** What changed is
that the page now reads the one thing that is evidence -- the order's own state,
moved only by a signature-verified webhook -- and says what that state is:

* paid, by the payment that just returned        -> *Payment complete*
* paid, by another payment                       -> *already completed*
* the returning payment is still being confirmed -> *We're confirming...*,
  re-checked a few times on a backing-off schedule, then an honest
  "taking longer than usual" with a manual *Check again*
* the provider reported a failure                -> *Payment wasn't completed*
* cancelled / expired / abandoned at the provider -> *Payment cancelled*
* order closed, or no such reference             -> *This link is no longer active*

`result` is used for one thing only: telling "the payer came back through the
failure door with nothing settled" (cancelled, not completed) from "the payer
came back through the success door and the webhook has not landed yet"
(pending). Neither branch ever claims money moved. A forged `result=success` on
an unpaid order renders the pending state, then the slow state -- never success.

**What the page discloses.** The amount, the purpose in generic words and the
outcome -- the same class of facts the guest page shows to its token holder.
Never a party, an email, an address, a route, a parcel, a deal or an order id.
The reference is a random UUID the payer's own browser was sent to; the page is
throttled like the guest page and asks search engines and referrers to keep
away.

**Who is reading.** The newest attempt says whether the payer came from a
guest link. A guest has no ShipTrip app and is never told to open one; the
Sender, who left the app for the provider, is told the app updates by itself.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .guest_web import COPY as GUEST_COPY
from .guest_web import LANGUAGE_NAMES, LANGUAGES, _amount, _language, _throttled
from .models import PaymentAttempt, PaymentOrder, PaymentProvider, PaymentRefund
from .services import guest_receipt_email_required

#: Backing-off re-check delays, in seconds, for a return still being confirmed.
#: Six re-reads over ~46 s: long enough for a webhook that is merely slow, short
#: enough that a page left open does not poll forever. After the last one the
#: page stops and offers a manual check.
RECHECK_DELAYS = (3, 3, 5, 5, 10, 20)

RETURN_COPY: dict[str, dict[str, str]] = {
    "en": {
        "title": "ShipTrip — payment",
        "languages": "Language",
        "amount_paid": "Amount paid",
        "amount_pending": "Amount being confirmed",
        "amount_due": "Amount still due",
        "success_title": "Payment complete",
        "close_guest": "You can close this page.",
        "close_app": (
            "You can close this page and go back to the ShipTrip app. It "
            "updates by itself."
        ),
        "receipt_sent": "A receipt has been sent to your email.",
        "receipt_queued": "A receipt is on its way to your email.",
        "charged_dzd": "Charged in dinars: {amount}",
        "paid_title": "This payment has already been completed",
        "paid_body_guest": "Nothing more is needed. You can close this page.",
        "paid_body_app": (
            "Nothing more is needed. Go back to the ShipTrip app to continue."
        ),
        "unapplied_refund": (
            "Your payment wasn't needed, so it is being refunded to you in full."
        ),
        "pending_title": "We're confirming your payment",
        "pending_body": (
            "This usually takes a moment. This page checks again by itself."
        ),
        "slow_title": "Still confirming your payment",
        "slow_body": (
            "This is taking longer than usual. You don't need to pay again — "
            "if the payment went through, it will show here."
        ),
        "check_again": "Check again",
        "failed_title": "Payment wasn't completed",
        "failed_body": "The payment didn't go through, so nothing was charged.",
        "not_completed_body": "No completed payment was recorded.",
        "cancelled_title": "Payment cancelled",
        "cancelled_body": "No completed payment was recorded.",
        "retry_guest": "To try again, open the payment link you were sent.",
        "retry_app": "To try again, go back to the ShipTrip app.",
        "inactive_title": "This link is no longer active",
        "inactive_body": (
            "No payment can be made from this page. If a payment is still "
            "needed, start again from where you were asked to pay."
        ),
    },
    "fr": {
        "title": "ShipTrip — paiement",
        "languages": "Langue",
        "amount_paid": "Montant payé",
        "amount_pending": "Montant en cours de vérification",
        "amount_due": "Montant restant dû",
        "success_title": "Paiement effectué",
        "close_guest": "Vous pouvez fermer cette page.",
        "close_app": (
            "Vous pouvez fermer cette page et revenir dans l’application "
            "ShipTrip : elle se met à jour toute seule."
        ),
        "receipt_sent": "Un reçu vous a été envoyé par e-mail.",
        "receipt_queued": "Votre reçu va vous être envoyé par e-mail.",
        "charged_dzd": "Débité en dinars : {amount}",
        "paid_title": "Ce paiement a déjà été effectué",
        "paid_body_guest": (
            "Vous n’avez plus rien à faire. Vous pouvez fermer cette page."
        ),
        "paid_body_app": (
            "Vous n’avez plus rien à faire. Revenez dans l’application "
            "ShipTrip pour continuer."
        ),
        "unapplied_refund": (
            "Votre paiement n’était plus nécessaire : il vous est remboursé "
            "intégralement."
        ),
        "pending_title": "Nous vérifions votre paiement",
        "pending_body": (
            "Cela ne prend généralement qu’un instant. Cette page se met à "
            "jour toute seule."
        ),
        "slow_title": "Vérification toujours en cours",
        "slow_body": (
            "C’est plus long que d’habitude. Inutile de payer une seconde "
            "fois : si le paiement est passé, il s’affichera ici."
        ),
        "check_again": "Vérifier à nouveau",
        "failed_title": "Le paiement n’a pas abouti",
        "failed_body": "Le paiement a échoué : rien n’a été débité.",
        "not_completed_body": "Aucun paiement n’a été enregistré.",
        "cancelled_title": "Paiement annulé",
        "cancelled_body": "Aucun paiement n’a été enregistré.",
        "retry_guest": (
            "Pour réessayer, ouvrez le lien de paiement qui vous a été envoyé."
        ),
        "retry_app": "Pour réessayer, revenez dans l’application ShipTrip.",
        "inactive_title": "Ce lien n’est plus actif",
        "inactive_body": (
            "Aucun paiement ne peut être effectué depuis cette page. Si un "
            "paiement est encore nécessaire, recommencez depuis l’endroit où "
            "il vous a été demandé."
        ),
    },
    "ar": {
        "title": "ShipTrip — الدفع",
        "languages": "اللغة",
        "amount_paid": "المبلغ المدفوع",
        "amount_pending": "المبلغ قيد التأكيد",
        "amount_due": "المبلغ المتبقّي",
        "success_title": "تمّ الدفع",
        "close_guest": "يمكنك إغلاق هذه الصفحة.",
        "close_app": (
            "يمكنك إغلاق هذه الصفحة والعودة إلى تطبيق ShipTrip، فهو يتحدّث "
            "تلقائيًا."
        ),
        "receipt_sent": "أُرسل إيصال الدفع إلى بريدك الإلكتروني.",
        "receipt_queued": "سيصلك إيصال الدفع على بريدك الإلكتروني.",
        "charged_dzd": "المبلغ المقتطع بالدينار: {amount}",
        "paid_title": "تمّ هذا الدفع من قبل",
        "paid_body_guest": "لا حاجة إلى أي إجراء آخر. يمكنك إغلاق هذه الصفحة.",
        "paid_body_app": (
            "لا حاجة إلى أي إجراء آخر. عُد إلى تطبيق ShipTrip للمتابعة."
        ),
        "unapplied_refund": (
            "لم يعد دفعك ضروريًا، لذلك سيُعاد إليك المبلغ كاملًا."
        ),
        "pending_title": "نتحقّق من دفعك",
        "pending_body": "يستغرق ذلك عادةً لحظات. تتحدّث هذه الصفحة تلقائيًا.",
        "slow_title": "ما زلنا نتحقّق من دفعك",
        "slow_body": (
            "يستغرق الأمر وقتًا أطول من المعتاد. لا داعي للدفع مرة أخرى؛ إن "
            "تمّ الدفع فسيظهر هنا."
        ),
        "check_again": "تحقّق مجددًا",
        "failed_title": "لم يكتمل الدفع",
        "failed_body": "لم ينجح الدفع، ولم يُقتطع أي مبلغ.",
        "not_completed_body": "لم يُسجَّل أي دفع مكتمل.",
        "cancelled_title": "أُلغي الدفع",
        "cancelled_body": "لم يُسجَّل أي دفع مكتمل.",
        "retry_guest": "لإعادة المحاولة، افتح رابط الدفع الذي أُرسل إليك.",
        "retry_app": "لإعادة المحاولة، عُد إلى تطبيق ShipTrip.",
        "inactive_title": "لم يعد هذا الرابط صالحًا",
        "inactive_body": (
            "لا يمكن الدفع من هذه الصفحة. إن كان الدفع لا يزال مطلوبًا، "
            "فابدأ من جديد من حيث طُلب منك الدفع."
        ),
    },
}

_SETTLED = (PaymentOrder.Status.PAID,)
_DEAD_ATTEMPT = (
    PaymentAttempt.Status.CANCELLED,
    PaymentAttempt.Status.EXPIRED,
)
_IN_FLIGHT = (
    PaymentAttempt.Status.CREATED,
    PaymentAttempt.Status.CHECKOUT_PENDING,
    PaymentAttempt.Status.PROCESSING,
)


def _dinars(amount_minor: int, exponent: int, lang: str) -> str:
    """`6,375 DA` / `6 375 DA` -- the app's own dinar rendering."""

    units = int(amount_minor) // (10**exponent) if exponent else int(amount_minor)
    grouped = f"{units:,}"
    if lang != "en":
        grouped = grouped.replace(",", " ")
    return f"{grouped} DA"


def _receipt_line(attempt: PaymentAttempt, t: dict) -> str:
    """Only when ShipTrip really is sending this payer a receipt.

    Email must be switched on, the payer must have given an address, and the
    outbox must hold a live (pending or dispatched) receipt for this very
    payment. A cancelled or failed message gets no sentence at all.
    """

    if not guest_receipt_email_required() or not attempt.guest_email:
        return ""
    from apps.notifications.models import OutboundMessage

    status = (
        OutboundMessage.objects.filter(
            key=f"guest_payment:attempt:{attempt.pk}:succeeded"
        )
        .values_list("status", flat=True)
        .first()
    )
    if status == OutboundMessage.Status.DISPATCHED:
        return t["receipt_sent"]
    if status == OutboundMessage.Status.PENDING:
        return t["receipt_queued"]
    return ""


def _state(order: PaymentOrder | None, latest, result: str) -> str:
    """The page's one answer, from the server's state alone."""

    if order is None:
        return "inactive"
    if order.status in _SETTLED:
        if (
            latest is not None
            and latest.status == PaymentAttempt.Status.SUCCEEDED
            and not latest.is_unapplied
            and result != "failure"
        ):
            return "success"
        return "already_paid"
    if not order.is_collectable:
        return "inactive"
    if latest is None:
        return "not_completed" if result == "failure" else "inactive"
    if latest.status == PaymentAttempt.Status.SUCCEEDED and not latest.is_unapplied:
        # Applied to an order that is still collectable: this payment went
        # through and something else is still owed on the obligation.
        return "success"
    if latest.status == PaymentAttempt.Status.FAILED:
        return "failed"
    if latest.status in _DEAD_ATTEMPT:
        return "cancelled"
    if latest.status in _IN_FLIGHT:
        if result == "failure":
            # Stripe only uses the failure door for "I left the checkout";
            # Chargily uses it for a declined or abandoned payment and has not
            # said which yet. Neither is a failure we can vouch for.
            return (
                "cancelled"
                if latest.provider == PaymentProvider.STRIPE
                else "not_completed"
            )
        return "pending"
    return "not_completed"


@require_GET
def payment_return_page(request: HttpRequest, reference) -> HttpResponse:
    result = request.GET.get("result", "")
    result = result if result in ("success", "failure") else ""
    try:
        check = int(request.GET.get("check", "0"))
    except ValueError:
        check = 0
    check = max(0, min(check, len(RECHECK_DELAYS)))

    if _throttled(request):
        # Answer, but do not re-check: a throttled page is told it is slow,
        # never that the payment failed or that the link is dead.
        return _render(request, _language(request), "slow", status=429, result=result)

    order = (
        PaymentOrder.objects.select_related("owner")
        .filter(public_reference=reference)
        .first()
    )
    latest = None
    if order is not None:
        latest = (
            PaymentAttempt.objects.select_related("guest_link")
            .filter(order=order)
            .order_by("-created_at", "-pk")
            .first()
        )
    is_guest = latest is not None and latest.guest_link_id is not None

    class _LanguageHint:
        communication_language = (
            latest.guest_link.communication_language
            if is_guest
            else getattr(getattr(order, "owner", None), "preferred_language", "")
        )

    lang = _language(request, _LanguageHint)
    state = _state(order, latest, result)
    if state == "pending" and check >= len(RECHECK_DELAYS):
        state = "slow"

    t = RETURN_COPY[lang]
    context: dict = {"is_guest": is_guest}
    if order is not None and state != "inactive":
        context["purpose"] = GUEST_COPY[lang].get(
            f"purpose_{order.purpose}", GUEST_COPY[lang]["purpose_other"]
        )

    if state == "success":
        context["amount_display"] = _amount(latest.amount_eur_cents, lang)
        context["amount_label"] = t["amount_paid"]
        context["next_line"] = t["close_guest"] if is_guest else t["close_app"]
        if latest.payment_currency == "DZD" and latest.provider_amount_minor:
            context["charged_line"] = t["charged_dzd"].format(
                amount=_dinars(
                    latest.provider_amount_minor,
                    latest.provider_amount_exponent or 0,
                    lang,
                )
            )
        if is_guest:
            context["receipt_line"] = _receipt_line(latest, t)
    elif state == "already_paid":
        context["next_line"] = (
            t["paid_body_guest"] if is_guest else t["paid_body_app"]
        )
        if (
            latest is not None
            and latest.status == PaymentAttempt.Status.SUCCEEDED
            and latest.is_unapplied
            and PaymentRefund.objects.filter(
                attempt=latest, reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT
            ).exists()
        ):
            context["refund_line"] = t["unapplied_refund"]
    elif state in ("pending", "slow"):
        context["amount_display"] = _amount(latest.amount_eur_cents, lang)
        context["amount_label"] = t["amount_pending"]
        if state == "pending":
            context["recheck_after"] = RECHECK_DELAYS[check]
            context["recheck_href"] = _href(lang, "success", check + 1)
        # A manual check re-reads once and does not restart the automatic
        # schedule: the reader asked for one look, not another minute of it.
        context["check_href"] = _href(lang, "success", len(RECHECK_DELAYS))
    elif state in ("failed", "cancelled", "not_completed"):
        if order.outstanding_eur_cents > 0:
            context["amount_display"] = _amount(order.outstanding_eur_cents, lang)
            context["amount_label"] = t["amount_due"]
        context["next_line"] = t["retry_guest"] if is_guest else t["retry_app"]

    return _render(
        request,
        lang,
        state,
        status=404 if state == "inactive" else 200,
        result=result,
        extra=context,
    )


def _href(lang: str, result: str, check: int | None = None) -> str:
    query = f"?result={result}&lang={lang}" if result else f"?lang={lang}"
    if check:
        query += f"&check={check}"
    return query


def _render(
    request: HttpRequest,
    lang: str,
    state: str,
    *,
    status: int,
    result: str,
    extra: dict | None = None,
) -> HttpResponse:
    t = RETURN_COPY[lang]
    context = {
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "t": t,
        "state": state,
        "languages": [
            {
                "code": code,
                "name": LANGUAGE_NAMES[code],
                "current": code == lang,
                "href": _href(code, result),
            }
            for code in LANGUAGES
        ],
        **(extra or {}),
    }
    if state == "slow" and "check_href" not in context:
        context["check_href"] = _href(lang, "success", len(RECHECK_DELAYS))
    return render(request, "payments/return.html", context, status=status)
