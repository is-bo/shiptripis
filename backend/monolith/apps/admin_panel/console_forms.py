"""Human-scale forms for the ShipTrip operations console.

The domain stores basis points, integer euro cents and FX micros. Operators do
not: forms accept percentages, euro amounts and a readable DZD-per-EUR rate,
then convert once at the server boundary. Domain services remain authoritative
for every financial or lifecycle decision.
"""

from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.disputes.models import Dispute
from apps.finance.models import PaymentAttempt, PaymentRefund, ScheduledJob
from apps.finance.money import CURRENCY_EXPONENTS

from .permissions import ROLE_CHOICES


def decimal_to_scaled_integer(value: Decimal, scale: int, *, label: str) -> int:
    scaled = value * scale
    if scaled != scaled.to_integral_value():
        raise forms.ValidationError(
            f"{label} has more precision than ShipTrip can store safely."
        )
    return int(scaled)


class ConsoleForm(forms.Form):
    """Every console form, with the label colon dropped.

    Django appends a colon to each label. On a settings page that is read as
    prose rather than filled in like a database row, "Work email:" reads like a
    field name and "Work email" reads like a question, so the suffix goes.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)


class SearchForm(ConsoleForm):
    q = forms.CharField(
        required=False,
        max_length=200,
        label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Name, email or reference"}),
    )


class JobRetryForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Why retry this job now?",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="Queue one retry through the existing idempotent handler."
    )


class JobResolutionForm(ConsoleForm):
    resolution = forms.ChoiceField(
        choices=ScheduledJob.Resolution.choices, label="Resolution"
    )
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label=(
            "Archive this failure without deleting it. Dismissing an email job "
            "also cancels its still-pending message obligation."
        )
    )


class JobBulkActionForm(ConsoleForm):
    action = forms.ChoiceField(
        choices=(("retry", "Retry now"), ("dismiss", "Dismiss")), label="Action"
    )
    reason = forms.CharField(
        max_length=500,
        label="Reason for every selected job",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label=(
            "I reviewed the selected terminal jobs and understand this is audited; "
            "dismissing email jobs cancels their pending message obligations."
        )
    )


class PaymentReconcileForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Reason for reconciliation",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label=(
            "Queue provider/refund reconciliation. This does not mark the payment paid."
        )
    )


class PaymentAttentionResolutionForm(ConsoleForm):
    resolution = forms.ChoiceField(
        choices=PaymentAttempt.OperationalResolution.choices,
        label="Resolution",
    )
    reason = forms.CharField(
        max_length=500,
        label="Investigation outcome",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="Archive only the attention item; retain all financial records."
    )


class ReviewDecisionForm(ConsoleForm):
    decision = forms.ChoiceField(
        choices=(("approved", "Approve"), ("rejected", "Reject")),
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(
        required=False,
        max_length=2_000,
        label="Rejection reason",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="The applicant receives this reason when the submission is rejected.",
    )
    confirm = forms.BooleanField(
        label="I reviewed the evidence and understand this decision is audited.",
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("decision") == "rejected"
            and not (cleaned.get("reason") or "").strip()
        ):
            self.add_error("reason", "Explain what the applicant must correct.")
        return cleaned


class InvitationForm(ConsoleForm):
    email = forms.EmailField(label="Work email")
    role = forms.ChoiceField(choices=ROLE_CHOICES, label="Role")
    expires_in_hours = forms.IntegerField(
        min_value=1,
        max_value=168,
        initial=24,
        label="Invitation valid for",
        help_text="Hours. The default is 24; the maximum is 7 days.",
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class RoleChangeForm(ConsoleForm):
    role = forms.ChoiceField(choices=ROLE_CHOICES, label="Role")
    confirm = forms.BooleanField(
        label="I understand this replaces the staff member's current ShipTrip role."
    )


class StaffAccessForm(ConsoleForm):
    enabled = forms.TypedChoiceField(
        choices=((True, "Enable access"), (False, "Disable access")),
        coerce=lambda value: value == "True",
        widget=forms.HiddenInput,
    )
    confirm = forms.BooleanField(
        label="I understand this changes whether the staff member can sign in."
    )


class BoostEconomicsSettingsForm(ConsoleForm):
    """ShipTrip's commission on the Boost portion of a delivery.

    Separate from the ordinary delivery commission on purpose: a Boost is the
    sender's own extra reward, and the platform may price its cut of that
    differently from its cut of the base reward. The two are never assumed
    equal, and neither one is derived from the other.

    Like every commercial input, a change here creates a new audited settings
    revision and binds **future commitments only**. A Deal that already exists
    carries the rate it was frozen with.
    """

    boost_commission_percent = forms.DecimalField(
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        max_digits=5,
        decimal_places=2,
        label="ShipTrip commission on boosts (%)",
        help_text=(
            "Charged on top of the boost, exactly as the delivery commission is "
            "charged on top of the reward. The Traveler receives the whole "
            "boost. Applies to future commitments only."
        ),
    )
    reason = forms.CharField(
        max_length=500,
        label="Reason for change",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="Create and activate a new settings version for future boosts."
    )

    def boost_commission_rate_bps(self) -> int:
        return decimal_to_scaled_integer(
            self.cleaned_data["boost_commission_percent"],
            100,
            label="Boost commission",
        )


class PricingSettingsForm(ConsoleForm):
    commission_percent = forms.DecimalField(
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        max_digits=5,
        decimal_places=2,
        label="ShipTrip commission (%)",
        help_text="Added on top of the Traveler reward for future offers.",
    )
    deposit_percent = forms.DecimalField(
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        max_digits=5,
        decimal_places=2,
        label="Posting deposit (%)",
        help_text="Percentage of the recommended Sender total, clamped to the minimum and maximum below.",
    )
    deposit_min_eur = forms.DecimalField(
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
        label="Minimum posting deposit (€)",
    )
    deposit_max_eur = forms.DecimalField(
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
        label="Maximum posting deposit (€)",
    )
    global_floor_eur = forms.DecimalField(
        min_value=Decimal("0.01"),
        max_digits=8,
        decimal_places=2,
        label="Minimum Traveler reward (€)",
    )
    weight_rate_eur = forms.DecimalField(
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
        label="Weight rate per kg (€)",
    )
    recommendation_multiplier_percent = forms.DecimalField(
        min_value=Decimal("100"),
        max_value=Decimal("500"),
        max_digits=6,
        decimal_places=2,
        label="Recommendation multiplier (%)",
    )
    reason = forms.CharField(
        max_length=500,
        label="Reason for change",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="Create and activate a new settings version for future pricing."
    )

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("deposit_min_eur")
        maximum = cleaned.get("deposit_max_eur")
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error(
                "deposit_max_eur", "The maximum must be at least the minimum."
            )
        return cleaned

    def scaled_values(self) -> dict[str, int]:
        return {
            "commission_rate_bps": decimal_to_scaled_integer(
                self.cleaned_data["commission_percent"], 100, label="Commission"
            ),
            "deposit_percent_bps": decimal_to_scaled_integer(
                self.cleaned_data["deposit_percent"], 100, label="Deposit percentage"
            ),
            "deposit_min_eur_cents": decimal_to_scaled_integer(
                self.cleaned_data["deposit_min_eur"], 100, label="Minimum deposit"
            ),
            "deposit_max_eur_cents": decimal_to_scaled_integer(
                self.cleaned_data["deposit_max_eur"], 100, label="Maximum deposit"
            ),
            "global_floor_cents": decimal_to_scaled_integer(
                self.cleaned_data["global_floor_eur"], 100, label="Global floor"
            ),
            "weight_rate_cents_per_kg": decimal_to_scaled_integer(
                self.cleaned_data["weight_rate_eur"], 100, label="Weight rate"
            ),
            "recommendation_multiplier_bps": decimal_to_scaled_integer(
                self.cleaned_data["recommendation_multiplier_percent"],
                100,
                label="Recommendation multiplier",
            ),
        }


class FxSettingsForm(ConsoleForm):
    eur_dzd_rate = forms.DecimalField(
        min_value=Decimal("0.000001"),
        max_digits=12,
        decimal_places=6,
        label="DZD for €1",
        help_text="Used only for new Chargily attempts; old attempts keep their snapshot.",
    )
    reason = forms.CharField(
        max_length=500,
        label="Rate source or reason",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(label="Create and activate a new FX settings version.")

    def rate_micros(self) -> int:
        return decimal_to_scaled_integer(
            self.cleaned_data["eur_dzd_rate"], 1_000_000, label="FX rate"
        )


class ProviderSettingsForm(ConsoleForm):
    stripe_enabled = forms.BooleanField(
        required=False, label="Accept new Stripe payments"
    )
    chargily_enabled = forms.BooleanField(required=False, label="Allow Chargily")
    chargily_new_checkouts = forms.BooleanField(
        required=False, label="Accept new Chargily checkouts"
    )
    reason = forms.CharField(
        max_length=500,
        label="Reason for change",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label=(
            "I checked provider readiness. This changes business availability, "
            "not credentials or webhook configuration."
        )
    )


class DisputeStatusForm(ConsoleForm):
    status = forms.ChoiceField(
        choices=(
            (Dispute.Status.OPEN, "Open"),
            (Dispute.Status.AWAITING_EVIDENCE, "Awaiting evidence"),
            (Dispute.Status.UNDER_REVIEW, "Under review"),
        ),
        label="Review state",
    )
    note = forms.CharField(
        required=False,
        max_length=4_000,
        label="Operator note",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class DisputeResolutionForm(ConsoleForm):
    resolution = forms.ChoiceField(
        choices=Dispute.Resolution.choices,
        label="Resolution",
    )
    sender_refund_eur = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=10,
        decimal_places=2,
        label="Sender refund (€)",
        help_text="Required only for a partial split.",
    )
    traveler_payout_eur = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=10,
        decimal_places=2,
        label="Traveler payout (€)",
        help_text="Optional for a partial split; the settlement engine can apportion it.",
    )
    note = forms.CharField(
        required=False,
        max_length=4_000,
        label="Decision note",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("resolution") == Dispute.Resolution.PARTIAL_SPLIT
            and cleaned.get("sender_refund_eur") is None
        ):
            self.add_error(
                "sender_refund_eur", "A partial split needs a refund amount."
            )
        return cleaned

    def service_values(self) -> dict:
        refund = self.cleaned_data.get("sender_refund_eur")
        payout = self.cleaned_data.get("traveler_payout_eur")
        return {
            "resolution": self.cleaned_data["resolution"],
            "sender_refund_eur_cents": (
                decimal_to_scaled_integer(refund, 100, label="Sender refund")
                if refund is not None
                else None
            ),
            "traveler_payout_eur_cents": (
                decimal_to_scaled_integer(payout, 100, label="Traveler payout")
                if payout is not None
                else None
            ),
            "note": self.cleaned_data.get("note", ""),
        }


class RefundRequestForm(ConsoleForm):
    amount_eur = forms.DecimalField(
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
        label="Refund amount (€)",
    )
    reason = forms.ChoiceField(choices=PaymentRefund.Reason.choices, label="Reason")
    confirm = forms.BooleanField(
        label="I understand the provider may receive this refund request immediately."
    )

    def amount_eur_cents(self) -> int:
        return decimal_to_scaled_integer(
            self.cleaned_data["amount_eur"], 100, label="Refund amount"
        )


class ManualRefundForm(ConsoleForm):
    settlement_reference = forms.CharField(max_length=128, label="Settlement reference")
    settlement_note = forms.CharField(
        required=False,
        max_length=255,
        label="Note",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="I confirm the refund was sent outside ShipTrip and the reference is correct."
    )


class ManualPayoutForm(ConsoleForm):
    payout_currency = forms.ChoiceField(
        choices=(("EUR", "EUR — euro"), ("DZD", "DZD — whole dinars")),
        label="Currency",
    )
    payout_amount = forms.DecimalField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        label="Amount actually sent",
    )
    reference = forms.CharField(max_length=128, label="Bank/provider reference")
    fx_rate = forms.DecimalField(
        required=False,
        min_value=Decimal("0.000001"),
        max_digits=12,
        decimal_places=6,
        label="FX rate used",
        help_text="Required by the service when the payout currency is not EUR.",
    )
    receipt_url = forms.URLField(required=False, label="Receipt URL")
    notes = forms.CharField(
        required=False,
        max_length=2_000,
        label="Notes",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="I confirm this payout has been sent and the evidence is accurate."
    )

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("payout_amount")
        currency = cleaned.get("payout_currency")
        if amount is not None and currency in CURRENCY_EXPONENTS:
            try:
                decimal_to_scaled_integer(
                    amount, 10 ** CURRENCY_EXPONENTS[currency], label="Payout amount"
                )
            except forms.ValidationError as exc:
                self.add_error("payout_amount", exc)
        if currency and currency != "EUR" and cleaned.get("fx_rate") is None:
            self.add_error(
                "fx_rate", "Record the exchange rate used for this settlement."
            )
        return cleaned

    def service_values(self) -> dict:
        currency = self.cleaned_data["payout_currency"]
        amount = decimal_to_scaled_integer(
            self.cleaned_data["payout_amount"],
            10 ** CURRENCY_EXPONENTS[currency],
            label="Payout amount",
        )
        rate = self.cleaned_data.get("fx_rate")
        return {
            "payout_currency": currency,
            "payout_amount_minor": amount,
            "reference": self.cleaned_data["reference"].strip(),
            "fx_rate_micros": (
                decimal_to_scaled_integer(rate, 1_000_000, label="FX rate")
                if rate is not None
                else None
            ),
            "receipt_url": self.cleaned_data.get("receipt_url", ""),
            "notes": self.cleaned_data.get("notes", ""),
        }
