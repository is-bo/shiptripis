"""Least-privilege Phase 6A administrative API.

The surface is deliberately inspection-first. Sensitive changes call an
existing domain service (money, disputes, no-show, settings) or a narrow
admin-panel review service (KYC and flight proof). There is no generic model
editor and no endpoint accepts an arbitrary Django permission list.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status as http
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.boosts.models import BoostPurchase
from apps.core.business_settings import activate_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.cancellation import CancellationError, record_no_show
from apps.deals.models import Deal
from apps.disputes.models import Dispute
from apps.disputes.serializers import DisputeResolveSerializer, DisputeStatusSerializer, NoShowSerializer
from apps.disputes.services import DisputeError, resolve_dispute, set_dispute_status
from apps.finance.models import PaymentAttempt, PaymentOrder, PaymentProviderEvent, PaymentRefund, Payout, ScheduledJob
from apps.finance.policy import InvalidPaymentPolicy, phase3_policy
from apps.finance.providers import available_providers
from apps.finance.serializers import ManualPayoutCompleteSerializer, ManualRefundSettleSerializer, RefundRequestSerializer
from apps.finance.services import FinanceError, complete_manual_payout, request_refund, settle_refund_manually
from apps.kyc.models import KycSubmission
from apps.matching.models import Match, Offer
from apps.notifications.models import OutboundMessage
from apps.parcels.models import DeliveryRequest
from apps.ratings.models import Rating
from apps.routing.providers import route_provider_status
from apps.trips.models import Journey, JourneyLegProof

from .models import AdminAuditLog, AdminInvitation
from .ops_serializers import (
    AdminBoostSerializer,
    AdminDealDetailSerializer,
    AdminDealSerializer,
    AdminDisputeSerializer,
    AdminFlightProofSerializer,
    AdminJourneySerializer,
    AdminKycSerializer,
    AdminMatchSerializer,
    AdminOfferSerializer,
    AdminPaymentAttemptSerializer,
    AdminPaymentOrderSerializer,
    AdminPayoutSerializer,
    AdminProviderEventSerializer,
    AdminRatingSerializer,
    AdminRefundSerializer,
    AdminRequestSerializer,
    AdminReviewSerializer,
    AdminScheduledJobSerializer,
    AdminSettingsCreateSerializer,
    AdminSettingsSerializer,
    AdminUserDetailSerializer,
    AdminUserSerializer,
)
from .permissions import (
    PERMISSION_LABELS,
    ROLE_GROUP_NAMES,
    ROLE_PERMISSIONS,
    CanIssueRefunds,
    CanManageAdmins,
    CanManageDisputes,
    CanManagePermissions,
    CanManageSettings,
    CanRecordNoShow,
    CanResolveDisputes,
    CanReviewFlightProof,
    CanReviewKyc,
    CanSettleManualRefunds,
    CanSettlePayouts,
    CanViewAuditLog,
    CanViewBoosts,
    CanViewDashboard,
    CanViewDeals,
    CanViewDisputes,
    CanViewFlightProofs,
    CanViewJourneys,
    CanViewKyc,
    CanViewMatches,
    CanViewPaymentAttempts,
    CanViewPaymentOrders,
    CanViewPayouts,
    CanViewProviderEvents,
    CanViewProviderHealth,
    CanViewRatings,
    CanViewRefunds,
    CanViewRequests,
    CanViewScheduledJobs,
    CanViewSettings,
    CanViewUsers,
    has_admin_permission,
    user_admin_roles,
)
from .serializers import (
    AdminAuditLogSerializer,
    AdminInvitationAcceptSerializer,
    AdminInvitationCreateSerializer,
    AdminInvitationSerializer,
    AdminRoleChangeSerializer,
)
from .services import (
    AdminReviewError,
    accept_admin_invitation,
    change_admin_role,
    create_admin_invitation,
    record_admin_action,
    review_flight_proof,
    review_kyc_submission,
    revoke_admin_invitation,
)


class AdminPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


def _paginate(request, queryset, serializer_class):
    paginator = AdminPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True, context={"request": request})
    return paginator.get_paginated_response(serializer.data)


def _status_filter(queryset, request, *, field: str = "status"):
    value = request.query_params.get(field)
    if not value:
        return queryset
    model_field = queryset.model._meta.get_field(field)
    allowed = {choice for choice, _label in model_field.choices}
    if allowed and value not in allowed:
        raise serializers.ValidationError({field: {"code": "invalid_choice", "detail": "Unsupported status value."}})
    return queryset.filter(**{field: value})


def _search(queryset, request, fields):
    term = request.query_params.get("q", "").strip()
    if not term:
        return queryset
    if len(term) > 200:
        raise serializers.ValidationError({"q": "Search text is limited to 200 characters."})
    query = Q()
    for field in fields:
        query |= Q(**{f"{field}__icontains": term})
    return queryset.filter(query)


def _domain_error(exc: Exception, *, fallback_code: str) -> Response:
    # Domain/provider exceptions can contain gateway responses, SQL details or
    # user-supplied text.  Keep the admin API contract useful without turning
    # an operational error into an information disclosure channel.
    payload = {
        "code": getattr(exc, "code", fallback_code),
        "detail": "The administrative operation could not be completed.",
    }
    details = getattr(exc, "details", None)
    if callable(details):
        payload.update(details())
    return Response(payload, status=http.HTTP_409_CONFLICT)


def _database_health() -> dict:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - readiness must return a safe status
        return {"available": False, "code": "database_unavailable"}
    return {"available": True}


def _provider_health() -> dict:
    result = {"database": _database_health()}
    try:
        policy = phase3_policy()
        result["payments"] = [row.as_dict() for row in available_providers(policy)]
    except InvalidPaymentPolicy:
        result["payments"] = {"available": False, "code": "payment_policy_unavailable"}
    try:
        result["routing"] = route_provider_status()
    except Exception:  # noqa: BLE001 - readiness must not expose internals
        result["routing"] = {"available": False, "code": "route_provider_status_unavailable"}

    smtp_host = str(getattr(settings, "EMAIL_HOST", "") or "")
    smtp_user = str(getattr(settings, "EMAIL_HOST_USER", "") or "")
    from_address = str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or "")
    email_enabled = bool(getattr(settings, "TRANSACTIONAL_EMAIL_ENABLED", False))
    result["email"] = {
        "provider": str(getattr(settings, "TRANSACTIONAL_EMAIL_PROVIDER", "smtp")),
        "enabled": email_enabled,
        "configured": bool(email_enabled and smtp_host and smtp_user and from_address),
        "tls": bool(getattr(settings, "EMAIL_USE_TLS", False)),
        "sending_domain_verified": bool(getattr(settings, "EMAIL_SENDING_DOMAIN_VERIFIED", False)),
    }
    return result


class DashboardView(APIView):
    permission_classes = (CanViewDashboard,)

    def get(self, request):
        active_deals = Deal.objects.filter(
            status__in=(Deal.Status.FUNDED, Deal.Status.PICKUP_READY, Deal.Status.PICKED_UP, Deal.Status.IN_TRANSIT, Deal.Status.DELIVERY_READY, Deal.Status.DELIVERY_CONFIRMED, Deal.Status.PROTECTION_WINDOW)
        )
        payload = {
            "generated_at": timezone.now(),
            "users": {
                "total": User.objects.count(),
                "active": User.objects.filter(is_active=True, is_banned=False).count(),
                "senders": User.objects.filter(role__in=(User.Role.SENDER, User.Role.BOTH)).count(),
                "travelers": User.objects.filter(role__in=(User.Role.TRAVELER, User.Role.BOTH)).count(),
                "kyc": {row["status"]: row["count"] for row in KycSubmission.objects.values("status").annotate(count=Count("id"))},
            },
            "marketplace": {
                "active_requests": DeliveryRequest.objects.filter(status=DeliveryRequest.Status.OPEN).count(),
                "active_journeys": Journey.objects.filter(status=Journey.Status.ACTIVE).count(),
                "matches": Match.objects.filter(status=Match.Status.PENDING).count(),
                "offers": Offer.objects.filter(status=Offer.Status.PENDING).count(),
                "funded_deals": Deal.objects.filter(status=Deal.Status.FUNDED).count(),
                "in_transit_deals": active_deals.filter(status__in=(Deal.Status.PICKED_UP, Deal.Status.IN_TRANSIT, Deal.Status.DELIVERY_READY)).count(),
                "protection_window_deals": Deal.objects.filter(status=Deal.Status.PROTECTION_WINDOW).count(),
                "completed_deals": Deal.objects.filter(status=Deal.Status.COMPLETED).count(),
                "cancelled_deals": Deal.objects.filter(status=Deal.Status.CANCELLED).count(),
            },
            "trust": {
                "pending_kyc": KycSubmission.objects.filter(status=KycSubmission.Status.PENDING).count(),
                "pending_flight_proof": JourneyLegProof.objects.filter(status=JourneyLegProof.Status.PENDING).count(),
                "active_disputes": Dispute.objects.filter(status__in=Dispute.ACTIVE_STATUSES).count(),
                "no_show_reviews": Deal.objects.filter(no_show_party="", status__in=(Deal.Status.FUNDED, Deal.Status.PICKUP_READY)).count(),
            },
        }
        if has_admin_permission(request.user, "view_payment_orders"):
            payload["finance"] = {
                "pending_payment_orders": PaymentOrder.objects.filter(status__in=(PaymentOrder.Status.PENDING, PaymentOrder.Status.PARTIALLY_PAID)).count(),
                "processing_attempts": PaymentAttempt.objects.filter(status=PaymentAttempt.Status.PROCESSING).count(),
                "refunds_pending": PaymentRefund.objects.filter(status__in=(PaymentRefund.Status.PENDING, PaymentRefund.Status.PROCESSING)).count(),
                "refunds_manual": PaymentRefund.objects.filter(requires_manual_action=True, status__in=(PaymentRefund.Status.PENDING, PaymentRefund.Status.PROCESSING)).count(),
                "payouts_pending": Payout.objects.filter(status__in=(Payout.Status.ELIGIBLE, Payout.Status.SCHEDULED, Payout.Status.PROCESSING)).count(),
                "unapplied_funds": PaymentAttempt.objects.filter(is_unapplied=True).count(),
            }
        if has_admin_permission(request.user, "view_provider_health"):
            payload["system_health"] = _provider_health()
            payload["email"] = {
                "pending": OutboundMessage.objects.filter(status=OutboundMessage.Status.PENDING).count(),
                "failed": OutboundMessage.objects.filter(status=OutboundMessage.Status.FAILED).count(),
                "dispatched": OutboundMessage.objects.filter(status=OutboundMessage.Status.DISPATCHED).count(),
            }
        if has_admin_permission(request.user, "view_scheduled_jobs"):
            payload["jobs"] = {
                "pending": ScheduledJob.objects.filter(status=ScheduledJob.Status.PENDING).count(),
                "running": ScheduledJob.objects.filter(status=ScheduledJob.Status.RUNNING).count(),
                "failed": ScheduledJob.objects.filter(status=ScheduledJob.Status.FAILED).count(),
                "retrying": ScheduledJob.objects.filter(status=ScheduledJob.Status.PENDING, attempts__gt=0).count(),
            }
        return Response(payload)


class AdminUserListView(APIView):
    permission_classes = (CanViewUsers,)

    def get(self, request):
        queryset = _search(User.objects.prefetch_related("groups").order_by("-date_joined"), request, ("email", "full_name", "phone"))
        if role := request.query_params.get("role"):
            if role not in User.Role.values:
                raise serializers.ValidationError({"role": "Unsupported account role."})
            queryset = queryset.filter(role=role)
        if request.query_params.get("banned") in ("true", "false"):
            queryset = queryset.filter(is_banned=request.query_params["banned"] == "true")
        return _paginate(request, queryset, AdminUserSerializer)


class AdminUserDetailView(APIView):
    permission_classes = (CanViewUsers,)

    def get(self, request, pk):
        queryset = User.objects.prefetch_related("groups").annotate(
            kyc_count=Count("kyc_submissions", distinct=True),
            request_count=Count("parcel_requests", distinct=True),
            journey_count=Count("journeys", distinct=True),
            deal_count=Count("deals_as_sender", distinct=True) + Count("deals_as_traveler", distinct=True),
            dispute_count=Count("disputes_opened", distinct=True),
            completed_deal_count=Count(
                "deals_as_sender",
                filter=Q(deals_as_sender__status=Deal.Status.COMPLETED),
                distinct=True,
            )
            + Count(
                "deals_as_traveler",
                filter=Q(deals_as_traveler__status=Deal.Status.COMPLETED),
                distinct=True,
            ),
            no_show_count=Count(
                "deals_as_sender",
                filter=Q(deals_as_sender__no_show_party="sender"),
                distinct=True,
            )
            + Count(
                "deals_as_traveler",
                filter=Q(deals_as_traveler__no_show_party="traveler"),
                distinct=True,
            ),
            ratings_received_count=Count("ratings_received", distinct=True),
            average_rating=Avg("ratings_received__score"),
        )
        user = get_object_or_404(queryset, pk=pk)
        return Response(AdminUserDetailSerializer(user, context={"request": request}).data)


class AdminKycListView(APIView):
    permission_classes = (CanViewKyc,)

    def get(self, request):
        queryset = _status_filter(KycSubmission.objects.select_related("user").order_by("-created_at"), request)
        queryset = _search(queryset, request, ("user__email", "user__full_name", "idempotency_key"))
        return _paginate(request, queryset, AdminKycSerializer)


class AdminKycReviewView(APIView):
    permission_classes = (CanReviewKyc,)

    def post(self, request, pk):
        serializer = AdminReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            submission = review_kyc_submission(actor=request.user, submission_id=pk, **serializer.validated_data)
        except KycSubmission.DoesNotExist:
            return Response(status=http.HTTP_404_NOT_FOUND)
        except AdminReviewError as exc:
            return _domain_error(exc, fallback_code="kyc_not_reviewable")
        return Response(AdminKycSerializer(submission, context={"request": request}).data)


class AdminFlightProofListView(APIView):
    permission_classes = (CanViewFlightProofs,)

    def get(self, request):
        queryset = _status_filter(JourneyLegProof.objects.select_related("leg__journey__traveler").order_by("-created_at"), request)
        if journey_id := request.query_params.get("journey_id"):
            queryset = queryset.filter(leg__journey_id=journey_id)
        return _paginate(request, queryset, AdminFlightProofSerializer)


class AdminFlightProofReviewView(APIView):
    permission_classes = (CanReviewFlightProof,)

    def post(self, request, pk):
        serializer = AdminReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            proof = review_flight_proof(actor=request.user, proof_id=pk, **serializer.validated_data)
        except JourneyLegProof.DoesNotExist:
            return Response(status=http.HTTP_404_NOT_FOUND)
        except AdminReviewError as exc:
            return _domain_error(exc, fallback_code="proof_not_reviewable")
        return Response(AdminFlightProofSerializer(proof, context={"request": request}).data)


class AdminRequestListView(APIView):
    permission_classes = (CanViewRequests,)

    def get(self, request):
        queryset = _status_filter(DeliveryRequest.objects.select_related("sender", "pickup_location", "delivery_location").order_by("-created_at"), request)
        queryset = _search(queryset, request, ("title", "description", "sender__email", "sender__full_name", "pickup_city", "delivery_city"))
        return _paginate(request, queryset, AdminRequestSerializer)


class AdminJourneyListView(APIView):
    permission_classes = (CanViewJourneys,)

    def get(self, request):
        queryset = _status_filter(Journey.objects.select_related("traveler", "start_location", "destination_location").prefetch_related("legs__origin", "legs__destination", "legs__proofs").order_by("-created_at"), request)
        queryset = _search(queryset, request, ("traveler__email", "traveler__full_name"))
        return _paginate(request, queryset, AdminJourneySerializer)


class AdminMatchListView(APIView):
    permission_classes = (CanViewMatches,)

    def get(self, request):
        queryset = _status_filter(Match.objects.select_related("sender", "traveler").annotate(offer_count=Count("offers", distinct=True)).order_by("-created_at"), request)
        queryset = _search(queryset, request, ("sender__email", "traveler__email"))
        return _paginate(request, queryset, AdminMatchSerializer)


class AdminOfferListView(APIView):
    permission_classes = (CanViewMatches,)

    def get(self, request):
        queryset = _status_filter(Offer.objects.select_related("proposer").order_by("-created_at"), request)
        if match_id := request.query_params.get("match_id"):
            queryset = queryset.filter(match_id=match_id)
        return _paginate(request, queryset, AdminOfferSerializer)


class AdminDealListView(APIView):
    permission_classes = (CanViewDeals,)

    def get(self, request):
        queryset = _status_filter(Deal.objects.select_related("sender", "traveler", "payout").annotate(event_count=Count("events", distinct=True), dispute_count=Count("disputes", distinct=True)).order_by("-created_at"), request)
        queryset = _search(queryset, request, ("sender__email", "traveler__email"))
        return _paginate(request, queryset, AdminDealSerializer)


class AdminDealDetailView(APIView):
    permission_classes = (CanViewDeals,)

    def get(self, request, pk):
        deal = get_object_or_404(
            Deal.objects.select_related("sender", "traveler", "terms", "payout", "recipient").prefetch_related("events", "disputes").annotate(event_count=Count("events", distinct=True), dispute_count=Count("disputes", distinct=True)),
            pk=pk,
        )
        return Response(AdminDealDetailSerializer(deal, context={"request": request}).data)


class AdminDisputeListView(APIView):
    permission_classes = (CanViewDisputes,)

    def get(self, request):
        queryset = _status_filter(Dispute.objects.select_related("deal", "opened_by", "resolved_by").prefetch_related("evidence").order_by("-opened_at"), request)
        if deal_id := request.query_params.get("deal_id"):
            queryset = queryset.filter(deal_id=deal_id)
        return _paginate(request, queryset, AdminDisputeSerializer)


class AdminDisputeStatusView(APIView):
    permission_classes = (CanManageDisputes,)

    def post(self, request, pk):
        serializer = DisputeStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = get_object_or_404(Dispute.objects.only("status"), pk=pk).status
        try:
            with transaction.atomic():
                dispute = set_dispute_status(dispute_id=pk, status=serializer.validated_data["status"], admin_actor_id=request.user.pk, note=serializer.validated_data.get("note", ""))
                record_admin_action(actor=request.user, action="dispute.status_changed", target=dispute, before={"status": before}, after={"status": dispute.status}, reason=serializer.validated_data.get("note", ""))
        except DisputeError as exc:
            return _domain_error(exc, fallback_code="dispute_status_invalid")
        return Response(AdminDisputeSerializer(dispute, context={"request": request}).data)


class AdminDisputeResolveView(APIView):
    permission_classes = (CanResolveDisputes,)

    def post(self, request, pk):
        serializer = DisputeResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = get_object_or_404(Dispute.objects.only("status", "resolution"), pk=pk)
        try:
            with transaction.atomic():
                dispute = resolve_dispute(dispute_id=pk, admin_actor_id=request.user.pk, **serializer.validated_data)
                record_admin_action(
                    actor=request.user,
                    action="dispute.resolved",
                    target=dispute,
                    before={"status": before.status, "resolution": before.resolution},
                    after={"status": dispute.status, "resolution": dispute.resolution, "sender_refund_eur_cents": dispute.sender_refund_eur_cents, "traveler_payout_eur_cents": dispute.traveler_payout_eur_cents, "platform_fee_eur_cents": dispute.platform_fee_eur_cents},
                    reason=serializer.validated_data.get("note", ""),
                )
        except (DisputeError, FinanceError) as exc:
            return _domain_error(exc, fallback_code="dispute_resolution_invalid")
        return Response(AdminDisputeSerializer(dispute, context={"request": request}).data)


class AdminDealNoShowView(APIView):
    permission_classes = (CanRecordNoShow,)

    def post(self, request, pk):
        serializer = NoShowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        get_object_or_404(Deal, pk=pk)
        try:
            with transaction.atomic():
                result = record_no_show(deal_id=pk, admin_actor_id=request.user.pk, **serializer.validated_data)
                record_admin_action(actor=request.user, action="deal.no_show_recorded", target_type="deals.deal", target_id=str(pk), after={"party": result["party"], "sender_refunded": result.get("sender_refunded", False)}, reason=serializer.validated_data.get("note", ""))
        except CancellationError as exc:
            return _domain_error(exc, fallback_code="no_show_not_permitted")
        return Response(result)


class AdminPaymentOrderListView(APIView):
    permission_classes = (CanViewPaymentOrders,)

    def get(self, request):
        queryset = _status_filter(PaymentOrder.objects.select_related("owner").order_by("-created_at"), request)
        if purpose := request.query_params.get("purpose"):
            if purpose not in PaymentOrder.Purpose.values:
                raise serializers.ValidationError({"purpose": "Unsupported payment purpose."})
            queryset = queryset.filter(purpose=purpose)
        return _paginate(request, queryset, AdminPaymentOrderSerializer)


class AdminPaymentAttemptListView(APIView):
    permission_classes = (CanViewPaymentAttempts,)

    def get(self, request):
        queryset = _status_filter(PaymentAttempt.objects.select_related("order", "payer").order_by("-created_at"), request)
        if provider := request.query_params.get("provider"):
            if provider not in PaymentAttempt.Provider.values:
                raise serializers.ValidationError({"provider": "Unsupported payment provider."})
            queryset = queryset.filter(provider=provider)
        return _paginate(request, queryset, AdminPaymentAttemptSerializer)


class AdminProviderEventListView(APIView):
    permission_classes = (CanViewProviderEvents,)

    def get(self, request):
        queryset = _status_filter(PaymentProviderEvent.objects.order_by("-received_at"), request, field="processing_result")
        return _paginate(request, queryset, AdminProviderEventSerializer)


class AdminRefundListView(APIView):
    permission_classes = (CanViewRefunds,)

    def get(self, request):
        queryset = _status_filter(PaymentRefund.objects.select_related("order").order_by("-created_at"), request)
        if request.query_params.get("manual") == "true":
            queryset = queryset.filter(requires_manual_action=True)
        return _paginate(request, queryset, AdminRefundSerializer)


class AdminRefundRequestView(APIView):
    permission_classes = (CanIssueRefunds,)

    def post(self, request):
        serializer = RefundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        attempt = get_object_or_404(PaymentAttempt, pk=data["attempt_id"])
        try:
            with transaction.atomic():
                refund = request_refund(order_id=attempt.order_id, attempt_id=attempt.pk, amount_eur_cents=data["amount_eur_cents"], reason=data["reason"], requested_by_id=request.user.pk)
                record_admin_action(actor=request.user, action="refund.requested", target=refund, after={"status": refund.status, "amount_eur_cents": refund.amount_eur_cents}, reason=data["reason"])
        except FinanceError as exc:
            return _domain_error(exc, fallback_code="refund_not_permitted")
        return Response(AdminRefundSerializer(refund).data, status=http.HTTP_201_CREATED)


class AdminRefundSettleView(APIView):
    permission_classes = (CanSettleManualRefunds,)

    def post(self, request, pk):
        serializer = ManualRefundSettleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                refund = settle_refund_manually(refund_id=pk, admin_actor_id=request.user.pk, **serializer.validated_data)
                record_admin_action(actor=request.user, action="refund.manually_settled", target=refund, after={"status": refund.status}, reference=refund.settlement_reference)
        except FinanceError as exc:
            return _domain_error(exc, fallback_code="refund_not_permitted")
        return Response(AdminRefundSerializer(refund).data)


class AdminPayoutListView(APIView):
    permission_classes = (CanViewPayouts,)

    def get(self, request):
        queryset = _status_filter(Payout.objects.select_related("traveler").order_by("-created_at"), request)
        return _paginate(request, queryset, AdminPayoutSerializer)


class AdminPayoutCompleteView(APIView):
    permission_classes = (CanSettlePayouts,)

    def post(self, request, pk):
        serializer = ManualPayoutCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                payout = complete_manual_payout(payout_id=pk, admin_actor_id=request.user.pk, **serializer.validated_data)
                record_admin_action(actor=request.user, action="payout.manually_completed", target=payout, after={"status": payout.status, "payout_currency": payout.payout_currency, "payout_amount_minor": payout.payout_amount_minor, "fx_rate_micros": payout.fx_rate_micros, "method": payout.method}, reference=payout.reference)
        except FinanceError as exc:
            return _domain_error(exc, fallback_code="payout_not_releasable")
        return Response(AdminPayoutSerializer(payout).data)


class AdminScheduledJobListView(APIView):
    permission_classes = (CanViewScheduledJobs,)

    def get(self, request):
        queryset = _status_filter(ScheduledJob.objects.order_by("run_at"), request)
        if kind := request.query_params.get("kind"):
            if kind not in ScheduledJob.Kind.values:
                raise serializers.ValidationError({"kind": "Unsupported job kind."})
            queryset = queryset.filter(kind=kind)
        return _paginate(request, queryset, AdminScheduledJobSerializer)


class AdminRatingListView(APIView):
    permission_classes = (CanViewRatings,)

    def get(self, request):
        queryset = Rating.objects.select_related("rater", "ratee").order_by("-created_at")
        if user_id := request.query_params.get("user_id"):
            if not user_id.isdigit():
                raise serializers.ValidationError({"user_id": "A numeric user id is required."})
            queryset = queryset.filter(Q(rater_id=user_id) | Q(ratee_id=user_id))
        return _paginate(request, queryset, AdminRatingSerializer)


class AdminBoostListView(APIView):
    permission_classes = (CanViewBoosts,)

    def get(self, request):
        return _paginate(request, _status_filter(BoostPurchase.objects.order_by("-created_at"), request), AdminBoostSerializer)


class AdminProviderHealthView(APIView):
    permission_classes = (CanViewProviderHealth,)

    def get(self, request):
        del request
        return Response(_provider_health())


class AdminSettingsView(APIView):
    def get_permissions(self):
        return [CanManageSettings()] if self.request.method == "POST" else [CanViewSettings()]

    def get(self, request):
        del request
        return Response(AdminSettingsSerializer(BusinessSettingsVersion.objects.order_by("-version")[:50], many=True).data)

    def post(self, request):
        serializer = AdminSettingsCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                latest = BusinessSettingsVersion.objects.select_for_update().order_by("-version").first()
                setting = BusinessSettingsVersion.objects.create(version=(latest.version if latest else 0) + 1, commission_rate_bps=data["commission_rate_bps"], pricing_version=data["pricing_version"], policy=data["policy"], created_by=request.user)
                if data.get("activate"):
                    setting = activate_business_settings(setting)
                record_admin_action(actor=request.user, action="settings.version_created", target=setting, after={"version": setting.version, "status": setting.status, "commission_rate_bps": setting.commission_rate_bps, "pricing_version": setting.pricing_version, "policy": setting.policy}, reason=data["reason"])
        except (ValueError, DjangoValidationError) as exc:
            raise serializers.ValidationError({"policy": str(exc)}) from exc
        return Response(AdminSettingsSerializer(setting).data, status=http.HTTP_201_CREATED)


class AdminRoleMatrixView(APIView):
    permission_classes = (CanManagePermissions,)

    def get(self, request):
        del request
        return Response({"roles": [{"slug": slug, "name": ROLE_GROUP_NAMES[slug], "permissions": [{"codename": code, "label": PERMISSION_LABELS[code]} for code in sorted(ROLE_PERMISSIONS[slug])]} for slug in ROLE_GROUP_NAMES]})


class AdminAccountListView(APIView):
    permission_classes = (CanManageAdmins,)

    def get(self, request):
        queryset = _search(User.objects.filter(is_staff=True).prefetch_related("groups").order_by("email"), request, ("email", "full_name"))
        return _paginate(request, queryset, AdminUserSerializer)


class AdminAccountRoleView(APIView):
    permission_classes = (CanManagePermissions,)

    def post(self, request, pk):
        serializer = AdminRoleChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = change_admin_role(actor=request.user, user_id=pk, role=serializer.validated_data["role"])
        except User.DoesNotExist:
            return Response(status=http.HTTP_404_NOT_FOUND)
        except (PermissionDenied, DjangoValidationError) as exc:
            return Response({"detail": str(exc)}, status=http.HTTP_403_FORBIDDEN)
        return Response(AdminUserSerializer(user, context={"request": request}).data)


class AdminInvitationListCreateView(APIView):
    permission_classes = (CanManageAdmins,)

    def get(self, request):
        return _paginate(request, AdminInvitation.objects.select_related("invited_by", "accepted_by").order_by("-created_at"), AdminInvitationSerializer)

    def post(self, request):
        serializer = AdminInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            invitation, _token = create_admin_invitation(actor=request.user, email=data["email"], role=data["role"], ttl=timedelta(hours=data["expires_in_hours"]))
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=http.HTTP_403_FORBIDDEN)
        payload = AdminInvitationSerializer(invitation).data
        # The one-time capability is delivered by the durable email outbox.
        # Never return it to a browser or retain it in an API response.
        return Response(payload, status=http.HTTP_201_CREATED)


class AdminInvitationAcceptView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = AdminInvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        authenticated_user = request.user if getattr(request.user, "is_authenticated", False) else None
        try:
            user = accept_admin_invitation(plaintext_token=serializer.validated_data["token"], password=serializer.validated_data.get("password", ""), full_name=serializer.validated_data.get("full_name", ""), authenticated_user=authenticated_user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=http.HTTP_403_FORBIDDEN)
        except DjangoValidationError as exc:
            return Response({"detail": "; ".join(exc.messages)}, status=http.HTTP_400_BAD_REQUEST)
        return Response({"id": user.pk, "email": user.email, "roles": user_admin_roles(user)}, status=http.HTTP_201_CREATED)


class AdminInvitationRevokeView(APIView):
    permission_classes = (CanManageAdmins,)

    def post(self, request, pk):
        try:
            invitation = revoke_admin_invitation(actor=request.user, invitation_id=pk)
        except AdminInvitation.DoesNotExist:
            return Response(status=http.HTTP_404_NOT_FOUND)
        return Response(AdminInvitationSerializer(invitation).data)


class AdminAuditLogListView(APIView):
    permission_classes = (CanViewAuditLog,)

    def get(self, request):
        queryset = AdminAuditLog.objects.select_related("actor").order_by("-created_at", "-id")
        if action := request.query_params.get("action"):
            queryset = queryset.filter(action=action)
        if target_type := request.query_params.get("target_type"):
            queryset = queryset.filter(target_type=target_type)
        queryset = _search(queryset, request, ("action", "target_type", "target_id", "reason", "reference", "actor__email"))
        return _paginate(request, queryset, AdminAuditLogSerializer)
