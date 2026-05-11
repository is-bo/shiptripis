from __future__ import annotations

from django.urls import path

from .views import (
    WalletDetailView,
    WalletEntriesView,
    WalletHoldsView,
    WalletListView,
    WithdrawalCreateView,
    WithdrawalListView,
)

urlpatterns = [
    path("wallets", WalletListView.as_view(), name="wallets-list"),
    path("wallets/<str:currency>", WalletDetailView.as_view(), name="wallets-detail"),
    path(
        "wallets/<str:currency>/entries",
        WalletEntriesView.as_view(),
        name="wallets-entries",
    ),
    path(
        "wallets/<str:currency>/holds",
        WalletHoldsView.as_view(),
        name="wallets-holds",
    ),
    path("withdrawals", WithdrawalListView.as_view(), name="withdrawals-list"),
    path(
        "withdrawals/create",
        WithdrawalCreateView.as_view(),
        name="withdrawals-create",
    ),
]
