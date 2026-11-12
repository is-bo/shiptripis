"""The one answer to "does this leg need a ticket, and is that need met?".

Spec section 6 makes this a single backend function: no other code may decide
a leg's proof requirement by comparing its mode. Publication, compatibility,
the acceptance lock, listings, Find Travelers, journey payloads and the admin
console all ask here (plan 2.2, code map 6.1).

Today a ticket is required on every flight and sea leg, and a road leg needs
none. L6A adds the verified-professional exemption; it changes
`leg_proof_satisfied` and the SQL twin `proof_gap_exists` together, so every
caller follows without being touched.

Three representations of the same rule live here, and they must agree:

* `leg_proof_satisfied` / `journey_proof_gaps` for Python decisions,
* `proof_gap_exists` for querysets that must not list a journey the engine
  would refuse,
* `leg_proof_state` for the server-authored `proof_state` a client renders,
  so the app never decides it either.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db.models import Case, CharField, Exists, OuterRef, Q, Value, When

from .models import JourneyLeg, JourneyLegProof

PROOF_REQUIRED_MODES = frozenset({JourneyLeg.Mode.FLIGHT, JourneyLeg.Mode.SEA})

#: `proof_state` values, as journey payloads publish them.
STATE_NOT_REQUIRED = "not_required"
STATE_MISSING = "missing"
STATE_PENDING = "pending"
STATE_APPROVED = "approved"
STATE_REJECTED = "rejected"

#: The publication refusal for a leg whose ticket is not approved. The flight
#: code predates sea legs and is kept; sea has its own (plan L3A).
PROOF_GAP_CODES = {
    JourneyLeg.Mode.FLIGHT: "flight_proof_not_approved",
    JourneyLeg.Mode.SEA: "sea_proof_not_approved",
}
PROOF_GAP_MESSAGES = {
    JourneyLeg.Mode.FLIGHT: "Every flight leg requires a currently approved ticket proof.",
    JourneyLeg.Mode.SEA: "Every sea leg requires a currently approved ticket proof.",
}

_PROOF_STATUS = JourneyLegProof.Status


def leg_requires_proof(leg: JourneyLeg) -> bool:
    """Whether this leg's mode carries a per-trip ticket requirement."""

    return leg.mode in PROOF_REQUIRED_MODES


def _has_approved_proof(leg: JourneyLeg) -> bool:
    annotated = getattr(leg, "has_approved_proof_value", None)
    if annotated is not None:
        return bool(annotated)
    prefetched = getattr(leg, "_prefetched_objects_cache", {}).get("proofs")
    if prefetched is not None:
        return any(proof.status == _PROOF_STATUS.APPROVED for proof in prefetched)
    return JourneyLegProof.objects.filter(
        leg=leg, status=_PROOF_STATUS.APPROVED
    ).exists()


def leg_proof_satisfied(leg: JourneyLeg) -> bool:
    """Whether this leg may be published, listed and matched as far as proof goes.

    Reads, in order, the ``has_approved_proof_value`` annotation a matching or
    acceptance queryset attached (the acceptance lock sets it from locked
    witness rows), prefetched proofs, and finally one query.
    """

    return not leg_requires_proof(leg) or _has_approved_proof(leg)


def journey_proof_gaps(legs: Iterable[JourneyLeg]) -> list[JourneyLeg]:
    """The legs, in the order given, whose proof requirement is not met."""

    return [leg for leg in legs if not leg_proof_satisfied(leg)]


def proof_gap_code(leg: JourneyLeg) -> str:
    return PROOF_GAP_CODES[leg.mode]


def proof_gap_message(leg: JourneyLeg) -> str:
    return PROOF_GAP_MESSAGES[leg.mode]


def proof_gap_exists(*, journey_ref: str = "pk") -> Exists:
    """SQL twin of `journey_proof_gaps`: the journey has a leg still missing proof."""

    approved = JourneyLegProof.objects.filter(
        leg_id=OuterRef("pk"), status=_PROOF_STATUS.APPROVED
    )
    return Exists(
        JourneyLeg.objects.filter(
            journey_id=OuterRef(journey_ref), mode__in=PROOF_REQUIRED_MODES
        )
        .alias(approved=Exists(approved))
        .filter(approved=False)
    )


def proof_state_annotation() -> Case:
    """Per-leg review state in SQL, for collection payloads.

    Any approved proof wins; otherwise a proof still waiting for a reviewer;
    otherwise a refusal; otherwise nothing was submitted. The mode is applied
    in Python by `leg_proof_state`, so the annotation stays one expression.
    """

    def proofs(status: str) -> Exists:
        return Exists(
            JourneyLegProof.objects.filter(leg_id=OuterRef("pk"), status=status)
        )

    return Case(
        When(Q(proofs(_PROOF_STATUS.APPROVED)), then=Value(STATE_APPROVED)),
        When(Q(proofs(_PROOF_STATUS.PENDING)), then=Value(STATE_PENDING)),
        When(Q(proofs(_PROOF_STATUS.REJECTED)), then=Value(STATE_REJECTED)),
        default=Value(STATE_MISSING),
        output_field=CharField(),
    )


def leg_proof_state(leg: JourneyLeg) -> str:
    """The server-authored `proof_state` for one leg.

    Same precedence as `proof_state_annotation`: approved, then pending, then
    rejected, then missing. A newer rejection never hides an older proof that
    still waits for review, because that proof can still be approved.
    """

    if not leg_requires_proof(leg):
        return STATE_NOT_REQUIRED
    annotated = getattr(leg, "proof_state_value", None)
    if annotated is not None:
        return annotated
    if getattr(leg, "has_approved_proof_value", None) is True:
        # Matching legs carry only this annotation; approval outranks every
        # other state, so it answers without a query.
        return STATE_APPROVED
    prefetched = getattr(leg, "_prefetched_objects_cache", {}).get("proofs")
    if prefetched is not None:
        statuses = {proof.status for proof in prefetched}
    else:
        statuses = set(
            JourneyLegProof.objects.filter(leg=leg).values_list("status", flat=True)
        )
    for status, state in (
        (_PROOF_STATUS.APPROVED, STATE_APPROVED),
        (_PROOF_STATUS.PENDING, STATE_PENDING),
        (_PROOF_STATUS.REJECTED, STATE_REJECTED),
    ):
        if status in statuses:
            return state
    return STATE_MISSING
