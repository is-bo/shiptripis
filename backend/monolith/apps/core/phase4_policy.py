"""Versioned Phase 4 policy: handover, protection, cancellation, ratings, boost.

Phase 3 put every commercially tunable payment input behind a strict parser
(`apps.finance.policy.Phase3Policy`). Phase 4 follows the same discipline in a
separate parser on purpose: a settings revision that predates Phase 4 must be
able to keep taking payments. Rolling back to such a revision degrades handover,
disputes, cancellation, ratings and boosts to a fail-closed 503; it does not
break checkout, reconciliation or refunds.

The one value both phases read is the protection window. It lives where Phase 3
put it -- ``payments.payout.protection_window_seconds`` -- and Phase 4 reads the
same key rather than introducing a second source of truth for 48 hours.

The seeded shape is::

    "handover": {
      "delivery_code_buffer_seconds": 1800,
      "code_length": 8,
      "max_failed_attempts": 5,
      "attempt_lockout_seconds": 900,
      "max_lockouts": 3,
      "attempt_window_seconds": 3600,
      "max_attempts_per_window": 12
    },
    "cancellation": {
      "sender_free_cutoff_seconds": 86400,
      "sender_late_compensation_bps": 1000,
      "sender_late_compensation_cap_eur_cents": 1500,
      "sender_late_platform_fee_bps": 0
    },
    "disputes": {
      "max_evidence_items": 20,
      "max_evidence_bytes": 26214400,
      "allowed_evidence_content_types": [...],
      "partial_split_fee_mode": "proportional"
    },
    "ratings": {
      "review_window_seconds": 1209600,
      "max_comment_length": 1000,
      "allowed_tags": [...]
    },
    "boost": {
      "enabled": true,
      "max_active_per_request": 3,
      "minimum_amount_eur_cents": 500,
      "traveler_share_bps": 7500,
      "packages": [{"code", "label", "duration_seconds",
                    "ranking_weight"}, ...]
    }

Every duration and money value parsed here is snapshotted onto the Deal (or the
BoostPurchase) at the moment it first applies, so a later revision can never
move a deadline or a price that a party has already been quoted.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import BusinessSettingsVersion


class InvalidPhase4Policy(RuntimeError):
    """The active settings revision cannot drive Phase 4 behaviour."""

    code = "phase4_policy_unavailable"


def _object(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise InvalidPhase4Policy(f"Business setting {name!r} must be an object.")
    return value


def _int(
    value: object, name: str, *, minimum: int = 0, maximum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidPhase4Policy(f"Business setting {name!r} must be an integer.")
    if value < minimum:
        raise InvalidPhase4Policy(
            f"Business setting {name!r} must be at least {minimum}."
        )
    if maximum is not None and value > maximum:
        raise InvalidPhase4Policy(
            f"Business setting {name!r} must not exceed {maximum}."
        )
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidPhase4Policy(f"Business setting {name!r} must be boolean.")
    return value


def _string_list(value: object, name: str, *, maximum: int = 64) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise InvalidPhase4Policy(
            f"Business setting {name!r} must be a list of at most {maximum} strings."
        )
    items = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise InvalidPhase4Policy(
                f"Business setting {name!r} must contain non-empty strings."
            )
        items.append(entry.strip())
    return tuple(items)


@dataclass(frozen=True, slots=True)
class HandoverPolicy:
    """Code strength, the delivery-code safety buffer and attempt limits."""

    delivery_code_buffer_seconds: int
    code_length: int
    max_failed_attempts: int
    attempt_lockout_seconds: int
    max_lockouts: int
    attempt_window_seconds: int
    max_attempts_per_window: int


@dataclass(frozen=True, slots=True)
class CancellationPolicy:
    """Post-funding cancellation compensation, in EUR cents and basis points."""

    sender_free_cutoff_seconds: int
    sender_late_compensation_bps: int
    sender_late_compensation_cap_eur_cents: int
    sender_late_platform_fee_bps: int


@dataclass(frozen=True, slots=True)
class DisputePolicy:
    max_evidence_items: int
    max_evidence_bytes: int
    allowed_evidence_content_types: tuple[str, ...]
    partial_split_fee_mode: str

    FEE_MODES = ("proportional", "platform_waives")


@dataclass(frozen=True, slots=True)
class RatingPolicy:
    review_window_seconds: int
    max_comment_length: int
    allowed_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoostPackage:
    code: str
    label: str
    duration_seconds: int
    ranking_weight: int

    def snapshot(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "duration_seconds": self.duration_seconds,
            "ranking_weight": self.ranking_weight,
        }


@dataclass(frozen=True, slots=True)
class BoostPolicy:
    enabled: bool
    max_active_per_request: int
    minimum_amount_eur_cents: int
    traveler_share_bps: int
    packages: tuple[BoostPackage, ...]

    def package(self, code: str) -> BoostPackage:
        for entry in self.packages:
            if entry.code == code:
                return entry
        raise InvalidPhase4Policy(f"Unknown boost package {code!r}.")


@dataclass(frozen=True, slots=True)
class Phase4Policy:
    settings_version: BusinessSettingsVersion
    protection_window_seconds: int
    handover: HandoverPolicy
    cancellation: CancellationPolicy
    disputes: DisputePolicy
    ratings: RatingPolicy
    boost: BoostPolicy

    @classmethod
    def from_settings(cls, settings_version: BusinessSettingsVersion) -> "Phase4Policy":
        policy = _object(settings_version.policy, "policy")

        # One source of truth for 48 hours: the key Phase 3 already seeds.
        payments = _object(policy.get("payments"), "payments")
        payout = _object(payments.get("payout"), "payments.payout")
        protection_window_seconds = _int(
            payout.get("protection_window_seconds"),
            "payments.payout.protection_window_seconds",
            minimum=0,
            maximum=30 * 24 * 3_600,
        )

        handover = _object(policy.get("handover"), "handover")
        handover_policy = HandoverPolicy(
            delivery_code_buffer_seconds=_int(
                handover.get("delivery_code_buffer_seconds"),
                "handover.delivery_code_buffer_seconds",
                minimum=0,
                maximum=7 * 24 * 3_600,
            ),
            code_length=_int(
                handover.get("code_length"),
                "handover.code_length",
                # Six Crockford base32 characters is 30 bits. Below that the
                # attempt cap becomes the only thing between a guesser and a
                # parcel, which is not a margin worth configuring away.
                minimum=6,
                maximum=16,
            ),
            max_failed_attempts=_int(
                handover.get("max_failed_attempts"),
                "handover.max_failed_attempts",
                minimum=1,
                maximum=20,
            ),
            attempt_lockout_seconds=_int(
                handover.get("attempt_lockout_seconds"),
                "handover.attempt_lockout_seconds",
                minimum=0,
                maximum=24 * 3_600,
            ),
            max_lockouts=_int(
                handover.get("max_lockouts"),
                "handover.max_lockouts",
                minimum=1,
                maximum=20,
            ),
            attempt_window_seconds=_int(
                handover.get("attempt_window_seconds"),
                "handover.attempt_window_seconds",
                minimum=60,
                maximum=24 * 3_600,
            ),
            max_attempts_per_window=_int(
                handover.get("max_attempts_per_window"),
                "handover.max_attempts_per_window",
                minimum=1,
                maximum=200,
            ),
        )

        cancellation = _object(policy.get("cancellation"), "cancellation")
        cancellation_policy = CancellationPolicy(
            sender_free_cutoff_seconds=_int(
                cancellation.get("sender_free_cutoff_seconds"),
                "cancellation.sender_free_cutoff_seconds",
                minimum=0,
                maximum=30 * 24 * 3_600,
            ),
            sender_late_compensation_bps=_int(
                cancellation.get("sender_late_compensation_bps"),
                "cancellation.sender_late_compensation_bps",
                minimum=0,
                maximum=10_000,
            ),
            sender_late_compensation_cap_eur_cents=_int(
                cancellation.get("sender_late_compensation_cap_eur_cents"),
                "cancellation.sender_late_compensation_cap_eur_cents",
                minimum=0,
                maximum=1_000_000,
            ),
            sender_late_platform_fee_bps=_int(
                cancellation.get("sender_late_platform_fee_bps", 0),
                "cancellation.sender_late_platform_fee_bps",
                minimum=0,
                maximum=10_000,
            ),
        )

        disputes = _object(policy.get("disputes"), "disputes")
        fee_mode = disputes.get("partial_split_fee_mode")
        if fee_mode not in DisputePolicy.FEE_MODES:
            raise InvalidPhase4Policy(
                "Business setting 'disputes.partial_split_fee_mode' must be one of "
                f"{DisputePolicy.FEE_MODES}."
            )
        dispute_policy = DisputePolicy(
            max_evidence_items=_int(
                disputes.get("max_evidence_items"),
                "disputes.max_evidence_items",
                minimum=1,
                maximum=200,
            ),
            max_evidence_bytes=_int(
                disputes.get("max_evidence_bytes"),
                "disputes.max_evidence_bytes",
                minimum=1_024,
                maximum=512 * 1_024 * 1_024,
            ),
            allowed_evidence_content_types=_string_list(
                disputes.get("allowed_evidence_content_types"),
                "disputes.allowed_evidence_content_types",
            ),
            partial_split_fee_mode=fee_mode,
        )

        ratings = _object(policy.get("ratings"), "ratings")
        rating_policy = RatingPolicy(
            review_window_seconds=_int(
                ratings.get("review_window_seconds"),
                "ratings.review_window_seconds",
                minimum=3_600,
                maximum=365 * 24 * 3_600,
            ),
            max_comment_length=_int(
                ratings.get("max_comment_length"),
                "ratings.max_comment_length",
                minimum=1,
                maximum=4_000,
            ),
            allowed_tags=_string_list(
                ratings.get("allowed_tags"), "ratings.allowed_tags"
            ),
        )

        boost = _object(policy.get("boost"), "boost")
        raw_packages = boost.get("packages")
        if not isinstance(raw_packages, list) or not raw_packages:
            raise InvalidPhase4Policy(
                "Business setting 'boost.packages' must be a non-empty list."
            )
        packages: list[BoostPackage] = []
        seen_codes: set[str] = set()
        for index, raw in enumerate(raw_packages):
            entry = _object(raw, f"boost.packages[{index}]")
            code = entry.get("code")
            if not isinstance(code, str) or not code.strip():
                raise InvalidPhase4Policy(
                    f"Business setting 'boost.packages[{index}].code' must be a string."
                )
            code = code.strip()
            if code in seen_codes:
                raise InvalidPhase4Policy(f"Duplicate boost package code {code!r}.")
            seen_codes.add(code)
            label = entry.get("label")
            if not isinstance(label, str) or not label.strip():
                raise InvalidPhase4Policy(
                    f"Business setting 'boost.packages[{index}].label' must be a "
                    "non-empty string."
                )
            packages.append(
                BoostPackage(
                    code=code,
                    label=label.strip(),
                    duration_seconds=_int(
                        entry.get("duration_seconds"),
                        f"boost.packages[{index}].duration_seconds",
                        minimum=3_600,
                        maximum=90 * 24 * 3_600,
                    ),
                    ranking_weight=_int(
                        entry.get("ranking_weight"),
                        f"boost.packages[{index}].ranking_weight",
                        minimum=1,
                        maximum=100,
                    ),
                )
            )
        boost_policy = BoostPolicy(
            enabled=_bool(boost.get("enabled"), "boost.enabled"),
            max_active_per_request=_int(
                boost.get("max_active_per_request"),
                "boost.max_active_per_request",
                minimum=1,
                maximum=20,
            ),
            minimum_amount_eur_cents=_int(
                boost.get("minimum_amount_eur_cents"),
                "boost.minimum_amount_eur_cents",
                minimum=500,
            ),
            # Economic boosts must always give the Traveler the majority and
            # must leave a configured remainder for ShipTrip. The split is in
            # basis points so canonical money never passes through a float.
            traveler_share_bps=_int(
                boost.get("traveler_share_bps"),
                "boost.traveler_share_bps",
                minimum=5_001,
                maximum=9_999,
            ),
            packages=tuple(packages),
        )

        return cls(
            settings_version=settings_version,
            protection_window_seconds=protection_window_seconds,
            handover=handover_policy,
            cancellation=cancellation_policy,
            disputes=dispute_policy,
            ratings=rating_policy,
            boost=boost_policy,
        )

    def lifecycle_snapshot(self) -> dict:
        """The durations and money rules copied onto a Deal when it is funded.

        Everything the Deal's remaining timeline depends on is frozen here, so
        a later settings revision cannot move a deadline, change a compensation
        cap or shorten a safety buffer for a Deal that is already running.
        """

        return {
            "business_settings_version": self.settings_version.version,
            "delivery_code_buffer_seconds": self.handover.delivery_code_buffer_seconds,
            "protection_window_seconds": self.protection_window_seconds,
            "rating_review_window_seconds": self.ratings.review_window_seconds,
            "handover": {
                "code_length": self.handover.code_length,
                "max_failed_attempts": self.handover.max_failed_attempts,
                "attempt_lockout_seconds": self.handover.attempt_lockout_seconds,
                "max_lockouts": self.handover.max_lockouts,
                "attempt_window_seconds": self.handover.attempt_window_seconds,
                "max_attempts_per_window": self.handover.max_attempts_per_window,
            },
            "cancellation": {
                "sender_free_cutoff_seconds": (
                    self.cancellation.sender_free_cutoff_seconds
                ),
                "sender_late_compensation_bps": (
                    self.cancellation.sender_late_compensation_bps
                ),
                "sender_late_compensation_cap_eur_cents": (
                    self.cancellation.sender_late_compensation_cap_eur_cents
                ),
                "sender_late_platform_fee_bps": (
                    self.cancellation.sender_late_platform_fee_bps
                ),
            },
            "disputes": {
                "partial_split_fee_mode": self.disputes.partial_split_fee_mode,
            },
        }


def phase4_policy() -> Phase4Policy:
    """Load the Phase 4 policy from the single active settings revision."""

    from .business_settings import get_active_business_settings

    return Phase4Policy.from_settings(get_active_business_settings())
