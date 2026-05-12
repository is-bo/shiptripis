"""Pricing rules per CLAUDE.md §6 — load-bearing, do not vary."""

import pytest

from apps.core.pricing import (
    DELIVERY_SUGGESTED_MIN_DZD,
    DELIVERY_SUGGESTED_PER_KG_DZD,
    PRODUCT_BASE_FEE_DZD,
    quote_delivery,
    quote_product,
    suggest_delivery_quote,
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


# ---------- delivery suggestion: weight + route anchor ----------

class TestDeliverySuggestion:
    def test_light_parcel_no_route(self):
        s = suggest_delivery_quote(weight_kg=1)
        # 1500 + 600*1 = 2100, no route multiplier
        assert s.weight_kg == 1
        assert s.suggested_base_dzd == 2_100
        assert s.route_multiplier_x100 == 100
        # sender total = base + 25% commission = 2625
        assert s.suggested_total_dzd == 2_625

    def test_heavier_parcel_scales_linearly(self):
        s = suggest_delivery_quote(weight_kg=10)
        # 1500 + 600*10 = 7500
        assert s.suggested_base_dzd == 7_500
        assert s.suggested_total_dzd == 9_375  # +25%

    def test_dz_fr_route_multiplier_applied(self):
        # 5kg: (1500 + 600*5) = 4500; * 1.6 = 7200
        s = suggest_delivery_quote(
            weight_kg=5, origin_country="DZ", destination_country="FR"
        )
        assert s.route_multiplier_x100 == 160
        assert s.suggested_base_dzd == 7_200
        assert s.suggested_total_dzd == 9_000  # +25%

    def test_route_is_symmetric(self):
        a = suggest_delivery_quote(
            weight_kg=3, origin_country="DZ", destination_country="FR"
        )
        b = suggest_delivery_quote(
            weight_kg=3, origin_country="FR", destination_country="DZ"
        )
        assert a.suggested_base_dzd == b.suggested_base_dzd

    def test_unknown_country_pair_uses_1x(self):
        s = suggest_delivery_quote(
            weight_kg=2, origin_country="US", destination_country="JP"
        )
        assert s.route_multiplier_x100 == 100
        assert s.suggested_base_dzd == DELIVERY_SUGGESTED_MIN_DZD + 2 * DELIVERY_SUGGESTED_PER_KG_DZD

    def test_band_is_plus_minus_40(self):
        s = suggest_delivery_quote(weight_kg=5)
        # base = 4500; floor = 60% = 2700; ceiling = 140% = 6300
        assert s.min_floor_dzd == 2_700
        assert s.max_ceiling_dzd == 6_300

    def test_zero_weight_rejected(self):
        with pytest.raises(ValueError):
            suggest_delivery_quote(weight_kg=0)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError):
            suggest_delivery_quote(weight_kg=-1)

    def test_float_weight_rejected(self):
        with pytest.raises(TypeError):
            suggest_delivery_quote(weight_kg=1.5)

    def test_all_outputs_are_int(self):
        s = suggest_delivery_quote(
            weight_kg=7, origin_country="DZ", destination_country="FR"
        )
        for v in (
            s.weight_kg,
            s.suggested_base_dzd,
            s.suggested_total_dzd,
            s.min_floor_dzd,
            s.max_ceiling_dzd,
            s.route_multiplier_x100,
        ):
            assert isinstance(v, int) and not isinstance(v, bool)

    def test_case_insensitive_country_codes(self):
        s = suggest_delivery_quote(
            weight_kg=2, origin_country="dz", destination_country="fr"
        )
        assert s.route_multiplier_x100 == 160
