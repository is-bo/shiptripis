"""Django-owned push registration, publication, and delivery feedback.

Business code publishes one authoritative notification event. This module
projects eligible per-user deliveries onto the existing ``notif:fcm`` Redis
stream; Firebase HTTP remains the Go notification service's responsibility.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any
from uuid import UUID

import redis
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.languages import normalize_communication_language

from .models import Notification, NotificationPreference, PushDevice

logger = logging.getLogger(__name__)

_FCM_MAX_TOKENS = 500
_STREAM_MAXLEN = 10_000
_SAFE_DATA_FIELDS = frozenset(
    {
        "deal_id",
        "dispute_id",
        "journey_id",
        "match_id",
        "message_id",
        "notification_id",
        "offer_id",
        "parcel_id",
        "payment_order_id",
        "proof_id",
        "request_id",
        "submission_id",
        "thread_id",
        "trip_id",
    }
)

# category, Android channel, offline collapse key, localized (title, body).
# Delivery-code issuance is deliberately absent: its event payload can contain
# the plaintext handover code and lock-screen previews are not trusted.
_PUSH_SPECS: dict[str, tuple[str, str, str, dict[str, tuple[str, str]]]] = {
    "parcel.created": (
        "marketplace",
        "deliveries",
        "shiptrip_activity",
        {
            "en": (
                "Request published",
                "Your delivery request is now visible to travelers.",
            ),
            "fr": (
                "Demande publiée",
                "Votre demande est désormais visible par les voyageurs.",
            ),
            "ar": ("تم نشر الطلب", "أصبح طلب التوصيل مرئيًا للمسافرين الآن."),
        },
    ),
    "parcel.cancelled": (
        "essential",
        "deliveries",
        "",
        {
            "en": ("Request cancelled", "Your delivery request was cancelled."),
            "fr": ("Demande annulée", "Votre demande de livraison a été annulée."),
            "ar": ("تم إلغاء الطلب", "تم إلغاء طلب التوصيل الخاص بك."),
        },
    ),
    "offer.created": (
        "marketplace",
        "deliveries",
        "shiptrip_activity",
        {
            "en": ("New offer", "An offer needs your attention."),
            "fr": ("Nouvelle offre", "Une offre nécessite votre attention."),
            "ar": ("عرض جديد", "هناك عرض يتطلب انتباهك."),
        },
    ),
    "offer.updated": (
        "marketplace",
        "deliveries",
        "shiptrip_activity",
        {
            "en": ("Offer updated", "Open ShipTrip to review the changes."),
            "fr": (
                "Offre mise à jour",
                "Ouvrez ShipTrip pour consulter les modifications.",
            ),
            "ar": ("تم تحديث العرض", "افتح ShipTrip لمراجعة التغييرات."),
        },
    ),
    "offer.accepted": (
        "essential",
        "deliveries",
        "",
        {
            "en": ("Offer accepted", "Open ShipTrip to review the delivery."),
            "fr": ("Offre acceptée", "Ouvrez ShipTrip pour consulter la livraison."),
            "ar": ("تم قبول العرض", "افتح ShipTrip لمراجعة عملية التسليم."),
        },
    ),
    "payment.captured": (
        "essential",
        "payments",
        "",
        {
            "en": ("Payment received", "Your delivery payment was confirmed."),
            "fr": ("Paiement reçu", "Le paiement de votre livraison a été confirmé."),
            "ar": ("تم استلام الدفعة", "تم تأكيد دفع عملية التسليم."),
        },
    ),
    "payment.refunded": (
        "essential",
        "payments",
        "",
        {
            "en": ("Refund update", "Your refund status was updated."),
            "fr": (
                "Mise à jour du remboursement",
                "Le statut de votre remboursement a été mis à jour.",
            ),
            "ar": ("تحديث الاسترداد", "تم تحديث حالة المبلغ المسترد."),
        },
    ),
    "payment.failed": (
        "essential",
        "payments",
        "",
        {
            "en": (
                "Payment failed",
                "Open ShipTrip to retry or choose another method.",
            ),
            "fr": (
                "Paiement échoué",
                "Ouvrez ShipTrip pour réessayer ou choisir un autre moyen.",
            ),
            "ar": ("تعذر الدفع", "افتح ShipTrip لإعادة المحاولة أو اختيار طريقة أخرى."),
        },
    ),
    "match.in_transit": (
        "essential",
        "deliveries",
        "",
        {
            "en": ("Pickup confirmed", "The parcel is now with the traveler."),
            "fr": ("Collecte confirmée", "Le colis est maintenant avec le voyageur."),
            "ar": ("تم تأكيد الاستلام", "الطرد الآن مع المسافر."),
        },
    ),
    "match.completed": (
        "essential",
        "deliveries",
        "",
        {
            "en": ("Delivery confirmed", "The 48-hour protection window has started."),
            "fr": (
                "Livraison confirmée",
                "La période de protection de 48 heures a commencé.",
            ),
            "ar": ("تم تأكيد التسليم", "بدأت فترة الحماية لمدة 48 ساعة."),
        },
    ),
    "handover.confirmed": (
        "essential",
        "deliveries",
        "",
        {
            "en": (
                "Handover confirmed",
                "Open ShipTrip to review the delivery status.",
            ),
            "fr": (
                "Remise confirmée",
                "Ouvrez ShipTrip pour consulter l'état de la livraison.",
            ),
            "ar": ("تم تأكيد التسليم", "افتح ShipTrip لمراجعة حالة التوصيل."),
        },
    ),
    "handover.delivery_code_available": (
        "essential",
        "deliveries",
        "",
        {
            "en": (
                "Delivery code available",
                "Open ShipTrip when the recipient is ready.",
            ),
            "fr": (
                "Code de livraison disponible",
                "Ouvrez ShipTrip lorsque le destinataire est prêt.",
            ),
            "ar": ("رمز التسليم متاح", "افتح ShipTrip عندما يكون المستلم جاهزًا."),
        },
    ),
    "handover.delivery_confirmed": (
        "essential",
        "deliveries",
        "",
        {
            "en": ("Delivery confirmed", "The 48-hour protection window has started."),
            "fr": (
                "Livraison confirmée",
                "La période de protection de 48 heures a commencé.",
            ),
            "ar": ("تم تأكيد التسليم", "بدأت فترة الحماية لمدة 48 ساعة."),
        },
    ),
    "kyc.status_changed": (
        "essential",
        "account",
        "",
        {
            "en": (
                "Identity verification updated",
                "Open ShipTrip to review the decision.",
            ),
            "fr": (
                "Vérification d'identité mise à jour",
                "Ouvrez ShipTrip pour consulter la décision.",
            ),
            "ar": ("تم تحديث التحقق من الهوية", "افتح ShipTrip لمراجعة القرار."),
        },
    ),
    "flight_proof.status_changed": (
        "essential",
        "account",
        "",
        {
            "en": ("Flight proof updated", "Open ShipTrip to review the decision."),
            "fr": (
                "Justificatif de vol mis à jour",
                "Ouvrez ShipTrip pour consulter la décision.",
            ),
            "ar": ("تم تحديث إثبات الرحلة", "افتح ShipTrip لمراجعة القرار."),
        },
    ),
    "deal.cancelled": (
        "essential",
        "deliveries",
        "",
        {
            "en": ("Delivery cancelled", "Open ShipTrip to review the cancellation."),
            "fr": ("Livraison annulée", "Ouvrez ShipTrip pour consulter l'annulation."),
            "ar": ("تم إلغاء التوصيل", "افتح ShipTrip لمراجعة الإلغاء."),
        },
    ),
    "dispute.opened": (
        "essential",
        "deliveries",
        "",
        {
            "en": ("Dispute opened", "Payout is paused while the dispute is reviewed."),
            "fr": (
                "Litige ouvert",
                "Le versement est suspendu pendant l'examen du litige.",
            ),
            "ar": ("تم فتح نزاع", "تم إيقاف التحويل مؤقتًا أثناء مراجعة النزاع."),
        },
    ),
    "dispute.resolved": (
        "essential",
        "deliveries",
        "",
        {
            "en": ("Dispute resolved", "Open ShipTrip to review the outcome."),
            "fr": ("Litige résolu", "Ouvrez ShipTrip pour consulter la décision."),
            "ar": ("تم حل النزاع", "افتح ShipTrip لمراجعة النتيجة."),
        },
    ),
    "payout.status_changed": (
        "essential",
        "payments",
        "",
        {
            "en": ("Payout update", "Your payout status was updated."),
            "fr": (
                "Mise à jour du versement",
                "Le statut de votre versement a été mis à jour.",
            ),
            "ar": ("تحديث التحويل", "تم تحديث حالة التحويل الخاص بك."),
        },
    ),
    "chat.message.new": (
        "messages",
        "messages",
        "shiptrip_messages",
        {
            "en": ("New message", "You have a new message on ShipTrip."),
            "fr": ("Nouveau message", "Vous avez un nouveau message sur ShipTrip."),
            "ar": ("رسالة جديدة", "لديك رسالة جديدة على ShipTrip."),
        },
    ),
}

_STATUS_PUSH_COPY: dict[
    tuple[str, str], dict[str, tuple[str, str]]
] = {
    ("kyc.status_changed", "approved"): {
        "en": ("Your KYC was approved", "You can now publish journeys."),
        "fr": ("Votre KYC a été approuvé", "Vous pouvez maintenant publier des trajets."),
        "ar": ("تمت الموافقة على التحقق", "يمكنك الآن نشر الرحلات."),
    },
    ("kyc.status_changed", "rejected"): {
        "en": ("KYC needs attention", "Open ShipTrip to review the decision and next step."),
        "fr": ("Votre KYC nécessite votre attention", "Ouvrez ShipTrip pour consulter la décision et la prochaine étape."),
        "ar": ("يتطلب التحقق انتباهك", "افتح ShipTrip لمراجعة القرار والخطوة التالية."),
    },
    ("flight_proof.status_changed", "approved"): {
        "en": ("Flight proof approved", "Your journey verification was updated."),
        "fr": ("Justificatif de vol approuvé", "La vérification de votre trajet a été mise à jour."),
        "ar": ("تمت الموافقة على إثبات الرحلة", "تم تحديث التحقق من رحلتك."),
    },
    ("flight_proof.status_changed", "rejected"): {
        "en": ("Flight proof needs attention", "Open ShipTrip to review the decision."),
        "fr": ("Votre justificatif de vol nécessite votre attention", "Ouvrez ShipTrip pour consulter la décision."),
        "ar": ("يتطلب إثبات الرحلة انتباهك", "افتح ShipTrip لمراجعة القرار."),
    },
}


def register_push_device(
    *,
    user,
    token: str,
    installation_id: UUID,
    platform: str,
    app_version: str = "",
) -> PushDevice:
    """Idempotently bind one installation and one current token to ``user``."""

    fingerprint = PushDevice.fingerprint(token)
    for attempt in range(2):
        try:
            with transaction.atomic():
                rows = list(
                    PushDevice.objects.select_for_update()
                    .filter(
                        Q(installation_id=installation_id)
                        | Q(token_fingerprint=fingerprint)
                    )
                    .order_by("id")
                )
                by_installation = next(
                    (row for row in rows if row.installation_id == installation_id),
                    None,
                )
                by_token = next(
                    (row for row in rows if row.token_fingerprint == fingerprint),
                    None,
                )
                device = by_installation or by_token
                if device is None:
                    device = PushDevice(installation_id=installation_id)
                if by_installation is not None and by_token not in (
                    None,
                    by_installation,
                ):
                    by_token.delete()

                rotated_or_rebound = device.pk is not None and (
                    device.token_fingerprint != fingerprint or device.user_id != user.pk
                )
                device.user = user
                device.provider = PushDevice.Provider.FCM
                device.platform = platform
                device.installation_id = installation_id
                device.token = token
                device.token_fingerprint = fingerprint
                device.app_version = app_version
                device.active = True
                device.last_seen_at = timezone.now()
                if rotated_or_rebound:
                    device.last_success_at = None
                    device.last_failure_at = None
                device.save()
                return device
        except IntegrityError:
            if attempt:
                raise
    raise RuntimeError("Push device registration retry was exhausted.")


def unregister_push_device(*, user, installation_id: UUID) -> bool:
    """Disable only the authenticated user's installation; idempotent."""

    return bool(
        PushDevice.objects.filter(
            user=user,
            installation_id=installation_id,
            active=True,
        ).update(active=False, last_seen_at=timezone.now(), updated_at=timezone.now())
    )


def _preference_allows(
    user_id: int, category: str, preferences: dict[int, NotificationPreference]
) -> bool:
    preference = preferences.get(user_id)
    if category == "messages":
        return preference is None or preference.messages_enabled
    if category == "marketplace":
        return preference is None or preference.marketplace_enabled
    return True


def _safe_data(
    *, channel: str, event_id: str, notification_id: int | None, payload: dict[str, Any]
) -> dict[str, str]:
    data = {"channel": channel, "event_id": event_id}
    if notification_id is not None:
        data["notification_id"] = str(notification_id)
    for key in _SAFE_DATA_FIELDS:
        value = payload.get(key)
        if value is not None and key != "notification_id":
            rendered = str(value)
            if len(rendered) <= 128:
                data[key] = rendered
    return data


def enqueue_fcm_for_event(
    *,
    channel: str,
    event_id: str,
    payload: dict[str, Any],
    targets: list[int],
) -> int:
    """XADD localized per-user multicast payloads; return entry count."""

    if not bool(getattr(settings, "FCM_ENABLED", False)):
        return 0
    spec = _PUSH_SPECS.get(channel)
    if spec is None or not targets:
        return 0

    devices = list(
        PushDevice.objects.filter(user_id__in=targets, active=True)
        .select_related("user")
        .order_by("user_id", "id")
    )
    if not devices:
        return 0
    preferences = {
        row.user_id: row
        for row in NotificationPreference.objects.filter(user_id__in=targets)
    }
    notification_ids = dict(
        Notification.objects.filter(
            event_id=event_id, recipient_id__in=targets
        ).values_list("recipient_id", "id")
    )
    by_user: dict[int, list[PushDevice]] = defaultdict(list)
    for device in devices:
        by_user[device.user_id].append(device)

    category, android_channel, collapse_key, localized = spec
    status = str(payload.get("status", "")).strip().lower()
    localized = _STATUS_PUSH_COPY.get((channel, status), localized)
    client = None
    entries = 0
    for user_id, user_devices in by_user.items():
        if not _preference_allows(user_id, category, preferences):
            continue
        language = normalize_communication_language(
            user_devices[0].user.preferred_language
        )
        title, body = localized.get(language, localized["en"])
        data = _safe_data(
            channel=channel,
            event_id=event_id,
            notification_id=notification_ids.get(user_id),
            payload=payload,
        )
        for offset in range(0, len(user_devices), _FCM_MAX_TOKENS):
            batch = user_devices[offset : offset + _FCM_MAX_TOKENS]
            fcm_payload = {
                "event_id": event_id,
                "user_id": user_id,
                "tokens": [device.token for device in batch],
                "device_ids": [device.pk for device in batch],
                "token_fingerprints": [
                    device.token_fingerprint for device in batch
                ],
                "title": title,
                "body": body,
                "android_channel_id": android_channel,
                "collapse_key": collapse_key,
                "data": data,
            }
            if client is None:
                from apps.core.redis_bus import get_client

                client = get_client()
            client.xadd(
                settings.FCM_STREAM,
                {
                    "event_id": event_id,
                    "user_id": str(user_id),
                    "payload": json.dumps(fcm_payload, separators=(",", ":")),
                },
                maxlen=_STREAM_MAXLEN,
                approximate=True,
            )
            entries += 1
    return entries


def consume_fcm_results(*, limit: int = 100) -> int:
    """Apply Go sender feedback without ever moving raw tokens across logs."""

    if limit <= 0 or limit > 500:
        raise ValueError("FCM feedback limit must be between 1 and 500.")
    if not bool(getattr(settings, "FCM_ENABLED", False)):
        return 0
    client = None
    try:
        from apps.core.redis_bus import get_client

        client = get_client()
        try:
            client.xgroup_create(
                settings.FCM_RESULTS_STREAM,
                settings.FCM_RESULTS_CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        # Drain this stable consumer's pending entries before reading new ones.
        # If Django stopped after applying a result but before XACK, replay is
        # harmless because both timestamp updates are idempotent.
        messages = client.xreadgroup(
            settings.FCM_RESULTS_CONSUMER_GROUP,
            settings.FCM_RESULTS_CONSUMER_NAME,
            {settings.FCM_RESULTS_STREAM: "0"},
            count=limit,
            block=None,
        )
        if not any(entries for _stream, entries in messages):
            messages = client.xreadgroup(
                settings.FCM_RESULTS_CONSUMER_GROUP,
                settings.FCM_RESULTS_CONSUMER_NAME,
                {settings.FCM_RESULTS_STREAM: ">"},
                count=limit,
                block=None,
            )
    except redis.RedisError:
        logger.warning("push feedback stream unavailable")
        return 0

    processed = 0
    for _stream, entries in messages:
        for entry_id, fields in entries:
            try:
                raw = fields.get("payload", "")
                result = json.loads(raw)
                successful = _validated_device_results(result, "successful")
                invalid = _validated_device_results(result, "invalid")
                now = timezone.now()
                with transaction.atomic():
                    if successful:
                        PushDevice.objects.filter(
                            _device_result_query(successful), active=True
                        ).update(
                            last_success_at=now,
                            last_failure_at=None,
                            updated_at=now,
                        )
                    if invalid:
                        PushDevice.objects.filter(
                            _device_result_query(invalid)
                        ).update(
                            active=False,
                            last_failure_at=now,
                            updated_at=now,
                        )
                client.xack(
                    settings.FCM_RESULTS_STREAM,
                    settings.FCM_RESULTS_CONSUMER_GROUP,
                    entry_id,
                )
                processed += 1
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.warning("dropping malformed push feedback entry id=%s", entry_id)
                client.xack(
                    settings.FCM_RESULTS_STREAM,
                    settings.FCM_RESULTS_CONSUMER_GROUP,
                    entry_id,
                )
            except Exception:
                logger.exception("push feedback application failed id=%s", entry_id)
    return processed


def _validated_device_ids(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > _FCM_MAX_TOKENS:
        raise ValueError("invalid device id list")
    ids = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError("invalid device id")
        device_id = int(item)
        if device_id <= 0:
            raise ValueError("invalid device id")
        ids.append(device_id)
    return ids


def _validated_device_results(
    result: dict[str, Any], outcome: str
) -> list[tuple[int, str]]:
    ids = _validated_device_ids(result.get(f"{outcome}_device_ids"))
    fingerprints = result.get(f"{outcome}_token_fingerprints")
    if not ids and fingerprints is None:
        return []
    if not isinstance(fingerprints, list) or len(fingerprints) != len(ids):
        raise ValueError("device feedback fingerprints must align with ids")
    validated = []
    for fingerprint in fingerprints:
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("invalid token fingerprint")
        normalized = fingerprint.lower()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("invalid token fingerprint")
        validated.append(normalized)
    return list(zip(ids, validated, strict=True))


def _device_result_query(devices: list[tuple[int, str]]) -> Q:
    query = Q()
    for device_id, fingerprint in devices:
        query |= Q(id=device_id, token_fingerprint=fingerprint)
    return query


def deactivate_stale_push_devices(*, days: int = 180) -> int:
    """Disable installations not seen for a bounded operator-selected age."""

    if days < 30:
        raise ValueError("Stale-device threshold must be at least 30 days.")
    cutoff = timezone.now() - timedelta(days=days)
    return PushDevice.objects.filter(active=True, last_seen_at__lt=cutoff).update(
        active=False,
        updated_at=timezone.now(),
    )
