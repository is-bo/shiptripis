"""The page behind a shared guest payment link.

`GuestPaymentView` is the JSON surface the app uses. This is the surface a
*person* uses: someone who was sent a link, has no ShipTrip account, and opened
it in a browser. Without it the link the owner shares is a URL that returns raw
JSON, which is not a payment experience and not something anyone should be asked
to forward to a relative.

Everything about the page is bounded by the same rule as the JSON surface:
holding the token buys exactly one capability, paying this one obligation. The
page renders an amount, what kind of payment it is, and how long the link
lasts. It never renders the sender, the traveler, the recipient, an address, a
parcel, a deal or an order reference, and the POST handler cannot be given an
amount -- it reads the outstanding balance from the locked order, exactly as the
app's own checkout does.

Every failure -- unknown token, expired, revoked, order closed -- renders the
same page in the same words. Distinguishing them would let someone holding a
guessed token learn which obligations exist. A real link whose payment is
complete says so instead (J7D; see `_completed_link`).

**Language.** A guest has no ShipTrip locale, so the page speaks the reader's
browser language when it is one of ours, falls back to the language the owner's
link was issued in, and always offers a one-tap switch. The switch is a query
parameter on the same path; the token never moves into a query string.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.business_settings import NoActiveBusinessSettings

from .models import GuestPaymentLink, PaymentOrder
from .policy import InvalidPaymentPolicy, phase3_policy
from .providers import ProviderError
from .services import (
    FinanceError,
    guest_payment_view,
    hash_guest_token,
    resolve_guest_link,
    start_checkout,
)

logger = logging.getLogger(__name__)

LANGUAGES = ("en", "fr", "ar")

#: Every word on the page, per language. Kept here rather than in gettext
#: catalogues because this is the only server-rendered page a member of the
#: public reads, and the three languages have to be reviewed side by side.
COPY: dict[str, dict[str, str]] = {
    "en": {
        "title": "ShipTrip — payment request",
        "eyebrow": "Payment request",
        "lead": (
            "The person who sent you this link is asking you to pay this for "
            "their ShipTrip delivery. You don't need an account."
        ),
        "pay_with": "Pay with",
        "email_label": "Email for your receipt",
        "email_hint": (
            "We'll send your receipt here, and tell you if a refund is ever "
            "due. It doesn't create an account."
        ),
        "email_error": "Enter a valid email address so we can send your receipt.",
        "pay": "Pay {amount}",
        "pay_generic": "Continue to payment",
        "handoff": (
            "You'll finish on our payment partner's secure page. ShipTrip "
            "never sees your card details."
        ),
        "scope": (
            "This link only lets you pay this amount. It gives no access to the "
            "delivery or to anyone's details."
        ),
        "valid_for": "Link valid for {duration}.",
        "languages": "Language",
        "invalid_title": "This link is no longer active",
        "invalid_body": (
            "It may have expired or been stopped by the person who sent it. If "
            "a payment is still needed, ask them for a new link."
        ),
        "paid_title": "This payment has already been completed",
        "paid_body": "Nothing more is needed. You can close this page.",
        "unavailable_title": "Payments are paused for a moment",
        "unavailable_body": (
            "Your link is fine — we just can't take a payment right now. Please "
            "try again shortly; there's no need to ask for a new link."
        ),
        "try_again": "Try again",
        "purpose_posting_deposit": "Deposit for a delivery request",
        "purpose_deal_balance": "Payment for a delivery",
        "purpose_boost": "Extra reward for a delivery",
        "purpose_other": "ShipTrip payment",
        "rail_stripe": "Card",
        "rail_stripe_note": "Visa, Mastercard and more",
        "rail_chargily": "Chargily (Algeria)",
        "rail_chargily_note": "CIB and Edahabia",
        "rail_mock": "Test rail",
        "rail_mock_note": "Development only",
    },
    "fr": {
        "title": "ShipTrip — demande de paiement",
        "eyebrow": "Demande de paiement",
        "lead": (
            "La personne qui vous a envoyé ce lien vous demande de régler ce "
            "montant pour sa livraison ShipTrip. Aucun compte n’est nécessaire."
        ),
        "pay_with": "Payer par",
        "email_label": "E-mail pour votre reçu",
        "email_hint": (
            "Nous y enverrons votre reçu et vous préviendrons si un "
            "remboursement vous est dû. Aucun compte n’est créé."
        ),
        "email_error": "Saisissez une adresse e-mail valide pour recevoir votre reçu.",
        "pay": "Payer {amount}",
        "pay_generic": "Continuer vers le paiement",
        "handoff": (
            "Vous finaliserez sur la page sécurisée de notre partenaire de "
            "paiement. ShipTrip ne voit jamais vos données de carte."
        ),
        "scope": (
            "Ce lien permet uniquement de régler ce montant. Il ne donne accès "
            "ni à la livraison ni aux informations de quiconque."
        ),
        "valid_for": "Lien encore valable {duration}.",
        "languages": "Langue",
        "invalid_title": "Ce lien n’est plus actif",
        "invalid_body": (
            "Il a peut-être expiré ou été désactivé par la personne qui l’a "
            "envoyé. Si un paiement est encore nécessaire, demandez-lui un "
            "nouveau lien."
        ),
        "paid_title": "Ce paiement a déjà été effectué",
        "paid_body": "Vous n’avez plus rien à faire. Vous pouvez fermer cette page.",
        "unavailable_title": "Les paiements sont momentanément indisponibles",
        "unavailable_body": (
            "Votre lien est valable : nous ne pouvons simplement pas encaisser "
            "pour l’instant. Réessayez dans un moment ; inutile de demander un "
            "nouveau lien."
        ),
        "try_again": "Réessayer",
        "purpose_posting_deposit": "Acompte pour une demande de livraison",
        "purpose_deal_balance": "Paiement d’une livraison",
        "purpose_boost": "Bonus pour une livraison",
        "purpose_other": "Paiement ShipTrip",
        "rail_stripe": "Carte bancaire",
        "rail_stripe_note": "Visa, Mastercard et autres",
        "rail_chargily": "Chargily (Algérie)",
        "rail_chargily_note": "CIB et Edahabia",
        "rail_mock": "Canal de test",
        "rail_mock_note": "Développement uniquement",
    },
    "ar": {
        "title": "ShipTrip — طلب دفع",
        "eyebrow": "طلب دفع",
        "lead": (
            "الشخص الذي أرسل إليك هذا الرابط يطلب منك دفع هذا المبلغ مقابل "
            "توصيله عبر ShipTrip. لا حاجة إلى حساب."
        ),
        "pay_with": "الدفع عبر",
        "email_label": "بريدك الإلكتروني لاستلام الإيصال",
        "email_hint": (
            "سنرسل إليه إيصال الدفع، ونبلغك إن استحق لك أي استرداد. لن يُنشأ "
            "لك أي حساب."
        ),
        "email_error": "أدخل بريدًا إلكترونيًا صالحًا لنرسل إليك الإيصال.",
        "pay": "ادفع {amount}",
        "pay_generic": "المتابعة إلى الدفع",
        "handoff": (
            "ستُكمل الدفع على الصفحة الآمنة لشريك الدفع لدينا. لا تطّلع "
            "ShipTrip على بيانات بطاقتك أبدًا."
        ),
        "scope": (
            "يتيح لك هذا الرابط دفع هذا المبلغ فقط، ولا يمنح أي اطلاع على "
            "التوصيل أو على بيانات أي شخص."
        ),
        "valid_for": "الرابط صالح لمدة {duration}.",
        "languages": "اللغة",
        "invalid_title": "لم يعد هذا الرابط صالحًا",
        "invalid_body": (
            "ربما انتهت صلاحيته أو أوقفه الشخص الذي أرسله. إن كان الدفع لا "
            "يزال مطلوبًا، اطلب منه رابطًا جديدًا."
        ),
        "paid_title": "تمّ هذا الدفع من قبل",
        "paid_body": "لا حاجة إلى أي إجراء آخر. يمكنك إغلاق هذه الصفحة.",
        "unavailable_title": "الدفع غير متاح مؤقتًا",
        "unavailable_body": (
            "رابطك صالح، لكن لا يمكننا استلام الدفع حاليًا. أعد المحاولة بعد "
            "قليل، ولا حاجة لطلب رابط جديد."
        ),
        "try_again": "أعد المحاولة",
        "purpose_posting_deposit": "عربون لطلب توصيل",
        "purpose_deal_balance": "دفع مقابل توصيل",
        "purpose_boost": "مكافأة إضافية لتوصيل",
        "purpose_other": "دفعة عبر ShipTrip",
        "rail_stripe": "بطاقة بنكية",
        "rail_stripe_note": "فيزا وماستركارد وغيرها",
        "rail_chargily": "شارجيلي (الجزائر)",
        "rail_chargily_note": "CIB والذهبية",
        "rail_mock": "قناة اختبار",
        "rail_mock_note": "للتطوير فقط",
    },
}

#: The switcher's own labels are each language's name for itself.
LANGUAGE_NAMES = {"en": "English", "fr": "Français", "ar": "العربية"}


def _language(request: HttpRequest, link=None) -> str:
    """The reader's language: explicit choice, their browser, then the link's."""

    chosen = request.POST.get("lang") or request.GET.get("lang")
    if chosen in LANGUAGES:
        return chosen
    header = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    for part in header.split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGUAGES:
            return code
    snapshot = getattr(link, "communication_language", "")
    if snapshot in LANGUAGES:
        return snapshot
    return "en"


def _amount(amount_eur_cents: int, lang: str) -> str:
    """The euro figure the way the app writes it in the same language.

    `€37.50` in English, `37,50 €` in French and in Arabic (Latin digits, as
    the app renders ar_DZ). Formatting only: the number is the server's.
    """

    euros, cents = divmod(int(amount_eur_cents), 100)
    if lang == "en":
        return f"€{euros:,}.{cents:02d}"
    # French grouping is a narrow no-break space, as intl renders fr_FR/ar_DZ.
    grouped = f"{euros:,}".replace(",", " ")
    return f"{grouped},{cents:02d} €"


def _plural_ar(count: int, one: str, two: str, few: str, many: str) -> str:
    if count == 1:
        return one
    if count == 2:
        return two
    if 3 <= count <= 10:
        return f"{count} {few}"
    return f"{count} {many}"


def _duration(expires_at: datetime, lang: str, *, now: datetime | None = None) -> str:
    """How much longer the link works, in words, with no timezone to guess.

    A clock time would need the reader's timezone, which the server does not
    have. "Two more days" is true wherever they are.
    """

    seconds = (expires_at - (now or timezone.now())).total_seconds()
    hours = math.ceil(seconds / 3600)
    if hours < 1:
        return {
            "en": "less than an hour",
            "fr": "moins d’une heure",
            "ar": "أقل من ساعة",
        }[lang]
    if hours < 24:
        return {
            "en": "1 more hour" if hours == 1 else f"{hours} more hours",
            "fr": "1 heure" if hours == 1 else f"{hours} heures",
            "ar": _plural_ar(hours, "ساعة واحدة", "ساعتين", "ساعات", "ساعة"),
        }[lang]
    days = max(1, round(hours / 24))
    return {
        "en": "1 more day" if days == 1 else f"{days} more days",
        "fr": "1 jour" if days == 1 else f"{days} jours",
        "ar": _plural_ar(days, "يوم واحد", "يومين", "أيام", "يومًا"),
    }[lang]


def _throttled(request: HttpRequest) -> bool:
    """Bound token guessing on the unauthenticated page as on the API."""

    from .views import GuestPaymentThrottle

    return not GuestPaymentThrottle().allow_request(request, None)


def _page(
    request: HttpRequest,
    lang: str,
    context: dict,
    *,
    status: int = 200,
) -> HttpResponse:
    return render(
        request,
        "payments/guest.html",
        {
            **context,
            "lang": lang,
            "dir": "rtl" if lang == "ar" else "ltr",
            "t": COPY[lang],
            "languages": [
                {
                    "code": code,
                    "name": LANGUAGE_NAMES[code],
                    "current": code == lang,
                    "href": f"?lang={code}",
                }
                for code in LANGUAGES
            ],
        },
        status=status,
    )


def _unavailable(request: HttpRequest, lang: str, status: int = 404) -> HttpResponse:
    """The link does not work. One page, one wording, every reason."""

    return _page(request, lang, {"payable": False}, status=status)


def _no_rail(request: HttpRequest, lang: str) -> HttpResponse:
    """The link is fine; the platform cannot take a payment right now.

    Told apart from an invalid link on purpose. "Try again shortly" and "ask
    for a new link" are different instructions, and giving a guest the wrong one
    sends them back to the sender for a link that was never the problem. It
    discloses nothing: a holder of a valid token already knows it is valid.
    """

    return _page(
        request,
        lang,
        {"payable": False, "temporarily_unavailable": True},
        status=503,
    )


def _completed_link(token: str):
    """The stored link behind `token` when its payment is complete (J7D).

    Every other dead link keeps the one uniform page. This branch exists for
    the person who has just paid and opens the link again: "no longer active,
    ask for a new link" would send them back to the Sender for a payment that
    is already done. It is reached only by a token whose hash matches a stored
    link, and tokens cannot be guessed, so it teaches a prober nothing.
    """

    if not token or len(token) > 512:
        return None
    link = (
        GuestPaymentLink.objects.select_related("order")
        .filter(token_hash=hash_guest_token(token))
        .first()
    )
    if link is None or link.order.status != PaymentOrder.Status.PAID:
        return None
    return link


@require_http_methods(["GET", "POST"])
def guest_payment_page(request: HttpRequest, token: str) -> HttpResponse:
    """Show what is owed, or start a hosted checkout for it.

    The POST branch redirects the browser to the provider rather than returning
    JSON, and returning from that provider proves nothing: only the
    signature-verified webhook moves money, exactly as for a signed-in payer.
    """

    if _throttled(request):
        return _unavailable(request, _language(request), status=429)
    try:
        link = resolve_guest_link(token)
        policy = phase3_policy()
    except (FinanceError, NoActiveBusinessSettings, InvalidPaymentPolicy):
        completed = _completed_link(token)
        if completed is not None:
            return _page(
                request,
                _language(request, completed),
                {"payable": False, "already_paid": True},
            )
        return _unavailable(request, _language(request))

    lang = _language(request, link)
    t = COPY[lang]
    payload = guest_payment_view(link, policy=policy)
    providers = [
        {
            "provider": row["provider"],
            "label": t.get(f"rail_{row['provider']}", row["provider"]),
            "note": t.get(f"rail_{row['provider']}_note", ""),
            "currency": row.get("settlement_currency") or row.get("payment_currency"),
        }
        for row in payload["providers"]
    ]
    if not providers:
        return _no_rail(request, lang)

    email_required = payload["receipt_email_required"]
    email = ""
    email_error = ""
    chosen = providers[0]["provider"]

    if request.method == "POST":
        chosen = request.POST.get("provider", "")
        if chosen not in {row["provider"] for row in providers}:
            return _unavailable(request, lang)
        email = (request.POST.get("email") or "").strip()[:254]
        if email_required:
            try:
                validate_email(email)
            except ValidationError:
                email_error = t["email_error"]
        else:
            # Never collected when nothing would be sent to it.
            email = ""
        if not email_error:
            try:
                session = start_checkout(
                    order_id=link.order_id,
                    provider=chosen,
                    actor_id=None,
                    guest_link=link,
                    guest_email=email,
                )
            except (ProviderError, NoActiveBusinessSettings, InvalidPaymentPolicy):
                # The link is fine; the rail is not. Same instruction as a rail
                # that is switched off: try again, not "ask for a new link".
                logger.warning(
                    "finance.guest_page_checkout_unavailable order=%s", link.order_id
                )
                return _no_rail(request, lang)
            except FinanceError:
                # The token is never echoed into a log line; the order is named
                # by its own id, which is not derivable from anything the payer
                # holds.
                logger.warning(
                    "finance.guest_page_checkout_failed order=%s", link.order_id
                )
                return _unavailable(request, lang, status=409)
            if not session.attempt.checkout_url:
                return _no_rail(request, lang)
            return HttpResponseRedirect(session.attempt.checkout_url)

    amount = _amount(payload["amount_eur_cents"], lang)
    # The button states an amount only when every rail on offer charges that
    # euro figure. A rail settling in another currency charges another number,
    # and a "Pay €42.50" button in front of it would be the wrong promise.
    euro_only = all(row["currency"] in ("", None, "EUR") for row in providers)
    purpose = t.get(f"purpose_{payload['purpose']}", t["purpose_other"])
    return _page(
        request,
        lang,
        {
            "payable": True,
            "amount_display": amount,
            "purpose": purpose,
            "providers": providers,
            "chosen": chosen,
            "email_required": email_required,
            "email": email,
            "email_error": email_error,
            # The figure is isolated left-to-right inside the sentence so an
            # Arabic button reads "42,50 €" exactly as the headline does.
            "pay_label": (
                t["pay"].format(amount=f"⁦{amount}⁩")
                if euro_only
                else t["pay_generic"]
            ),
            "valid_for": t["valid_for"].format(
                duration=_duration(link.expires_at, lang)
            ),
            "checkout_action": request.path,
        },
        status=400 if email_error else 200,
    )
