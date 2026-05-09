"""Pricing rules per CLAUDE.md §6 — load-bearing, do not vary."""

import pytest

from apps.core.pricing import (
    PRODUCT_BASE_FEE_DZD,
    quote_delivery,
    quote_product,
)


# ---------- delivery: 25% commission ----------

class TestDelivery:
    def test_zero_base_yields_zero_total(self):
        q = quote_delivery(0)
        assert q.commission_dzd == 0
        assert q.total_dzd == 0
        assert q.traveler_payout_dzd == 0

    def test_round_thousand(self):
        q = quote_delivery(10_000)
        assert q.commission_dzd == 2_500
        assert q.total_dzd == 12_500
        assert q.traveler_payout_dzd == 10_000

    def test_floor_division_on_odd_amount(self):
        # 1_001 * 25 // 100 = 250 (NOT 250.25 — integer floor)
        q = quote_delivery(1_001)
        assert q.commission_dzd == 250
        assert q.total_dzd == 1_251

    def test_offer_fields_shape(self):
        q = quote_delivery(8_000)
        assert q.as_offer_fields() == {
            "base_fee_dzd": 0,
            "commission_dzd": 2_000,
            "total_dzd": 10_000,
        }

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            quote_delivery(-1)

    def test_float_rejected(self):
        with pytest.raises(TypeError):
            quote_delivery(100.0)

    def test_bool_rejected(self):
        # bool is a subclass of int — guard against it explicitly.
        with pytest.raises(TypeError):
            quote_delivery(True)


# ---------- product: tiered + 2_500 base fee ----------

class TestProduct:
    def test_below_30k_zero_pct(self):
        q = quote_product(20_000)
        assert q.commission_dzd == 0
        assert q.base_fee_dzd == PRODUCT_BASE_FEE_DZD
        assert q.total_dzd == 20_000 + 2_500
        assert q.traveler_payout_dzd == 20_000 + 2_500

    def test_at_30k_seven_pct(self):
        # Tier boundary: 30_000 falls in [30_000, 55_000) at 7%.
        q = quote_product(30_000)
        assert q.commission_dzd == 30_000 * 7 // 100  # 2_100
        assert q.total_dzd == 30_000 + 2_500 + 2_100  # 34_600

    def test_at_55k_five_pct(self):
        q = quote_product(55_000)
        assert q.commission_dzd == 55_000 * 5 // 100  # 2_750
        assert q.total_dzd == 55_000 + 2_500 + 2_750  # 60_250

    def test_at_100k_three_pct(self):
        q = quote_product(100_000)
        assert q.commission_dzd == 100_000 * 3 // 100  # 3_000
        assert q.total_dzd == 100_000 + 2_500 + 3_000  # 105_500

    def test_high_value_three_pct(self):
        q = quote_product(500_000)
        assert q.commission_dzd == 500_000 * 3 // 100  # 15_000

    def test_traveler_excludes_commission(self):
        q = quote_product(40_000)
        # commission goes to platform, traveler keeps product + base_fee
        assert q.traveler_payout_dzd == 40_000 + 2_500
        assert q.commission_dzd > 0

    def test_offer_fields_shape(self):
        q = quote_product(40_000)
        assert q.as_offer_fields() == {
            "base_fee_dzd": 2_500,
            "commission_dzd": 40_000 * 7 // 100,
            "total_dzd": 40_000 + 2_500 + (40_000 * 7 // 100),
        }

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            quote_product(-1)

    def test_float_rejected(self):
        with pytest.raises(TypeError):
            quote_product(40_000.0)
