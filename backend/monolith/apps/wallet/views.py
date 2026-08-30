"""Wallet API — read-only views on the ledger + withdrawal request.

Endpoints:
  GET  /api/wallets                            — my wallets (one per currency)
  GET  /api/wallets/<currency>                 — single wallet with live balance
  GET  /api/wallets/<currency>/entries         — recent ledger entries (?limit=)
  GET  /api/wallets/<currency>/holds           — escrow holds
  GET  /api/withdrawals                        — my withdrawal requests
  POST /api/withdrawals                        — request a payout
"""

from __future__ import annotations

from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Wallet, Withdrawal
from .serializers import (
    HoldSerializer,
    WalletEntrySerializer,
    WalletSerializer,
    WithdrawalCreateSerializer,
    WithdrawalSerializer,
)
from .services import get_balance, get_or_create_wallet


def _annotate(wallet: Wallet) -> Wallet:
    """Attach computed balance fields onto the wallet for serialization."""
    b = get_balance(wallet)
    wallet.total_minor = b.total_minor
    wallet.available_minor = b.available_minor
    wallet.on_hold_minor = b.on_hold_minor
    return wallet


class WalletListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        wallets = list(Wallet.objects.filter(user=request.user))
        for w in wallets:
            _annotate(w)
        return Response(WalletSerializer(wallets, many=True).data)


class WalletDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, currency: str) -> Response:
        wallet = get_or_create_wallet(request.user, currency.upper())
        _annotate(wallet)
        return Response(WalletSerializer(wallet).data)


class WalletEntriesView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, currency: str) -> Response:
        wallet = get_or_create_wallet(request.user, currency.upper())
        try:
            limit = min(int(request.query_params.get("limit", 50)), 200)
        except ValueError:
            limit = 50
        entries = wallet.entries.all()[:limit]
        return Response(WalletEntrySerializer(entries, many=True).data)


class WalletHoldsView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, currency: str) -> Response:
        wallet = get_or_create_wallet(request.user, currency.upper())
        holds = wallet.holds.all()
        if (s := request.query_params.get("status")):
            holds = holds.filter(status=s)
        return Response(HoldSerializer(holds[:200], many=True).data)


class WithdrawalListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        wds = Withdrawal.objects.filter(user=request.user)[:200]
        return Response(WithdrawalSerializer(wds, many=True).data)


class WithdrawalCreateView(APIView):
    """Request a payout from a wallet.

    Refuses if `available_minor < amount_minor`. The request is queued for
    ops to disburse. V1 does NOT write a debit entry yet — ops marks `sent`
    in admin (V2: signed entry on transition).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        s = WithdrawalCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        wallet = get_or_create_wallet(request.user, d["currency"])
        balance = get_balance(wallet)
        if balance.available_minor < d["amount_minor"]:
            return Response(
                {
                    "detail": "Insufficient available balance.",
                    "available_minor": balance.available_minor,
                },
                status=http.HTTP_409_CONFLICT,
            )

        wd = Withdrawal.objects.create(
            wallet=wallet,
            user=request.user,
            amount_minor=d["amount_minor"],
            currency=d["currency"],
            destination=d["destination"],
            destination_ref=d.get("destination_ref", ""),
        )
        return Response(WithdrawalSerializer(wd).data, status=http.HTTP_201_CREATED)
