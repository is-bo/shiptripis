/// A traveller's journey: an ordered chain of flight, sea and road legs.
///
/// The V1 model is deliberately not "a flight". Paris → Algiers by air then
/// Algiers → Jijel by road is one journey with two legs, and a sender's parcel
/// may ride a sub-range of it. A ferry between two port cities is a leg like
/// any other. Every leg carries its own capacity, so the
/// question "can you take 3 kg" is answered per leg, not per journey.
///
/// Owner and counterparty see materially different leg objects: the owner gets
/// `distance_meters`, the route polyline, the airport metadata and the proof
/// list; a counterparty gets a `distance_band` instead and none of the rest.
/// [JourneyLeg.isOwnerView] records which one arrived so a screen can ask
/// rather than guess.
library;

import 'json.dart';
import 'canonical_place.dart';
import 'location.dart';
import 'person_photo.dart';
import 'transport_mode.dart';

enum JourneyStatus {
  draft,
  pendingVerification,
  active,
  inProgress,
  completed,
  cancelled,
  expired,
  unknown;

  /// Discoverable by senders and open to proposals.
  bool get isLive => this == active || this == inProgress;

  bool get isEditable => this == draft || this == pendingVerification;

  bool get isFinished =>
      this == completed || this == cancelled || this == expired;
}

/// What a traveller charges for a journey, in euro cents: a price per kg and
/// a minimum per parcel. Both or neither, which is why this is one value.
///
/// The app does no arithmetic with it. What a parcel would cost on this
/// journey is the server's `listed` block on Find Travelers.
class JourneyPrice {
  const JourneyPrice({
    required this.perKgEurCents,
    required this.minimumEurCents,
  });

  /// Null when the journey has no price, or when it carries a half-price the
  /// contract forbids: a half-price is not shown as if it were a whole one.
  static JourneyPrice? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final perKg = readInt(json['price_per_kg_eur_cents']);
    final minimum = readInt(json['min_price_eur_cents']);
    if (perKg == null || minimum == null) return null;
    return JourneyPrice(perKgEurCents: perKg, minimumEurCents: minimum);
  }

  final int perKgEurCents;
  final int minimumEurCents;

  @override
  bool operator ==(Object other) =>
      other is JourneyPrice &&
      other.perKgEurCents == perKgEurCents &&
      other.minimumEurCents == minimumEurCents;

  @override
  int get hashCode => Object.hash(perKgEurCents, minimumEurCents);
}

/// `GET /api/journeys/pricing-policy`: whether travellers may set a price at
/// all, and the largest value each part may take. The ceilings are null while
/// the switch is off.
class TravelerPricingPolicy {
  const TravelerPricingPolicy({
    required this.enabled,
    this.maxPerKgEurCents,
    this.maxMinimumEurCents,
  });

  factory TravelerPricingPolicy.fromJson(Map<String, dynamic> json) =>
      TravelerPricingPolicy(
        enabled: json['enabled'] == true,
        maxPerKgEurCents: readInt(json['max_price_per_kg_eur_cents']),
        maxMinimumEurCents: readInt(json['max_min_price_eur_cents']),
      );

  final bool enabled;
  final int? maxPerKgEurCents;
  final int? maxMinimumEurCents;
}

enum ProofStatus { pending, approved, rejected, unknown }

/// What the server says a leg's ticket needs, from `proof_state`.
///
/// The client never decides whether a leg needs a ticket or whether one is
/// good enough: flight and sea legs need one, a road leg does not, and the
/// server tells us which state each leg is in. A value this build has never
/// heard of reads as [unknown] and blocks nothing it cannot explain.
enum LegProofState {
  notRequired,
  missing,
  pending,
  approved,
  rejected,
  unknown;

  static LegProofState parse(Object? raw) => switch (raw) {
    'not_required' => notRequired,
    'missing' => missing,
    'pending' => pending,
    'approved' => approved,
    'rejected' => rejected,
    _ => unknown,
  };
}

/// What this stop accepts, and the handover detail the owner set for it.
///
/// [handoverNote] and the window are served only to the owner (and, after
/// funding, to the two parties of a deal that uses the stop, through the
/// deal's own route). Everyone else gets the flags alone.
class JourneyStop {
  const JourneyStop({
    required this.position,
    this.placeId,
    this.acceptsPickup = true,
    this.acceptsDropoff = true,
    this.handoverNote = '',
    this.windowStart,
    this.windowEnd,
  });

  factory JourneyStop.fromJson(Map<String, dynamic> json) => JourneyStop(
    position: readInt(json['position']) ?? 0,
    placeId: readInt(json['place_id']),
    acceptsPickup: json['accepts_pickup'] != false,
    acceptsDropoff: json['accepts_dropoff'] != false,
    handoverNote: readText(json['handover_note']),
    windowStart: readDate(json['window_start']),
    windowEnd: readDate(json['window_end']),
  );

  final int position;
  final int? placeId;

  /// What the stop *effectively* accepts: never a drop-off at the first stop
  /// or a pickup at the last, whatever was set.
  final bool acceptsPickup;
  final bool acceptsDropoff;

  final String handoverNote;
  final DateTime? windowStart;
  final DateTime? windowEnd;

  bool get hasHandoverDetail =>
      handoverNote.isNotEmpty || (windowStart != null && windowEnd != null);
}

/// The owner's view of a pause. Staff reasons are never served.
class JourneyPause {
  const JourneyPause({
    required this.paused,
    this.pausedAt,
    this.pausedByStaff = false,
  });

  factory JourneyPause.fromJson(Map<String, dynamic> json) => JourneyPause(
    paused: json['paused'] == true,
    pausedAt: readDate(json['paused_at']),
    pausedByStaff: json['paused_by_staff'] == true,
  );

  final bool paused;
  final DateTime? pausedAt;

  /// Staff paused it, so only staff can lift it and the traveller is told to
  /// contact support.
  final bool pausedByStaff;
}

class JourneyLegProof {
  const JourneyLegProof({
    required this.id,
    required this.kind,
    required this.contentType,
    required this.bytes,
    required this.status,
    this.reviewedAt,
    this.rejectionReason,
  });

  factory JourneyLegProof.fromJson(Map<String, dynamic> json) =>
      JourneyLegProof(
        id: readInt(json['id']) ?? 0,
        kind: readText(json['kind']),
        contentType: readText(json['content_type']),
        bytes: readInt(json['bytes']) ?? 0,
        status: readEnum(
          json['status'],
          ProofStatus.values,
          fallback: ProofStatus.unknown,
        ),
        reviewedAt: readDate(json['reviewed_at']),
        rejectionReason: readString(json['rejection_reason']),
      );

  final int id;

  /// `ticket`, `boarding_pass` or `booking_confirmation`.
  final String kind;

  final String contentType;
  final int bytes;
  final ProofStatus status;
  final DateTime? reviewedAt;

  /// Only populated on a rejection, and only for the owner.
  final String? rejectionReason;
}

class JourneyLeg {
  const JourneyLeg({
    required this.id,
    required this.position,
    required this.mode,
    required this.origin,
    required this.destination,
    this.originPlace,
    this.destinationPlace,
    required this.departAt,
    required this.capacityKg,
    required this.flightNumber,
    required this.hasApprovedProof,
    required this.proofs,
    required this.isOwnerView,
    this.proofRequired = false,
    this.proofState = LegProofState.notRequired,
    this.capacityVolumeLitres,
    this.capacityParcels,
    this.arriveAt,
    this.distanceMeters,
    this.distanceBand,
    this.routeDurationSeconds,
  });

  factory JourneyLeg.fromJson(Map<String, dynamic> json) {
    // The owner's payload carries `distance_meters`; a counterparty's carries
    // `distance_band` in its place. Presence of the owner-only key is the
    // honest test for which projection arrived.
    final isOwnerView =
        json.containsKey('distance_meters') ||
        json.containsKey('proofs') ||
        json.containsKey('route_metadata');

    return JourneyLeg(
      id: readInt(json['id']) ?? 0,
      position: readInt(json['position']) ?? 0,
      mode: TransportMode.parse(json['mode']),
      origin: AppLocation.maybe(json['origin']),
      destination: AppLocation.maybe(json['destination']),
      originPlace: _place(json['origin_place']),
      destinationPlace: _place(json['destination_place']),
      departAt: readDate(json['depart_at']),
      arriveAt: readDate(json['arrive_at']),
      capacityKg: readDouble(json['capacity_kg']),
      distanceMeters: readInt(json['distance_meters']),
      distanceBand: DistanceBand.maybe(json['distance_band']),
      routeDurationSeconds: readInt(json['route_duration_seconds']),
      capacityVolumeLitres: readInt(json['capacity_volume_l']),
      capacityParcels: readInt(json['capacity_parcels']),
      flightNumber: readText(json['flight_number']),
      hasApprovedProof: readBool(json['has_approved_proof']),
      proofRequired: json['proof_required'] == true,
      proofState: LegProofState.parse(json['proof_state']),
      proofs: readObjectList(
        json['proofs'],
      ).map(JourneyLegProof.fromJson).toList(growable: false),
      isOwnerView: isOwnerView,
    );
  }

  final int id;
  final int position;
  final TransportMode mode;
  final AppLocation? origin;
  final AppLocation? destination;
  final CanonicalPlace? originPlace;
  final CanonicalPlace? destinationPlace;
  final DateTime? departAt;
  final DateTime? arriveAt;

  /// Declared capacity for this leg. Remaining capacity is not published; the
  /// server answers "does this fit" during discovery and again at acceptance.
  final double? capacityKg;

  /// Owner view only.
  final int? distanceMeters;

  /// Counterparty view only.
  final DistanceBand? distanceBand;

  final int? routeDurationSeconds;
  final String flightNumber;
  final bool hasApprovedProof;
  final List<JourneyLegProof> proofs;
  final bool isOwnerView;

  /// Optional extra limits the traveller declared. Remaining room is never
  /// published; the server answers "does this fit" during discovery and again
  /// at acceptance.
  final int? capacityVolumeLitres;
  final int? capacityParcels;

  /// The server's answer to "does this leg need a ticket". Flight and sea legs
  /// do; a road leg does not. Never derived from [mode] on the client.
  final bool proofRequired;
  final LegProofState proofState;

  /// A leg that needs a ticket and has no approved one blocks the whole
  /// journey from publishing.
  bool get needsProof => proofRequired && proofState != LegProofState.approved;
}

class Journey {
  const Journey({
    required this.id,
    required this.travelerId,
    required this.travelerName,
    required this.status,
    this.travelerPhoto,
    required this.notes,
    required this.legs,
    this.startLocation,
    this.destinationLocation,
    this.startPlace,
    this.destinationPlace,
    this.publishedAt,
    this.createdAt,
    this.updatedAt,
    this.editable,
    this.editBlockedCode,
    this.stops = const [],
    this.refusedCategories = const [],
    this.acceptsFragile = true,
    this.pause,
    this.price,
  });

  factory Journey.fromJson(Map<String, dynamic> json) => Journey(
    id: readInt(json['id']) ?? 0,
    travelerId: readInt(json['traveler_id']) ?? 0,
    travelerName: readText(json['traveler_name']),
    travelerPhoto: PersonPhoto.maybe(json['traveler_photo']),
    startLocation: AppLocation.maybe(json['start_location']),
    destinationLocation: AppLocation.maybe(json['destination_location']),
    startPlace: _place(json['start_place']),
    destinationPlace: _place(json['destination_place']),
    status: readEnum(
      json['status'],
      JourneyStatus.values,
      fallback: JourneyStatus.unknown,
    ),
    publishedAt: readDate(json['published_at']),
    notes: readText(json['notes']),
    legs: (readObjectList(json['legs']).map(JourneyLeg.fromJson).toList()
      ..sort((a, b) => a.position.compareTo(b.position))),
    createdAt: readDate(json['created_at']),
    updatedAt: readDate(json['updated_at']),
    // Served only to the owner, and only on the detail endpoint. Absent means
    // "not this viewer's business", which is not the same as "no".
    editable: json['editable'] is bool ? json['editable'] as bool : null,
    editBlockedCode: readString(json['edit_blocked_code']),
    stops: (readObjectList(json['stops']).map(JourneyStop.fromJson).toList()
      ..sort((a, b) => a.position.compareTo(b.position))),
    refusedCategories: [
      for (final value in json['refused_categories'] as List? ?? const [])
        if (value is String) value,
    ],
    acceptsFragile: json['accepts_fragile'] != false,
    pause: readObject(json['pause']) == null
        ? null
        : JourneyPause.fromJson(readObject(json['pause'])!),
    price: JourneyPrice.maybe(json['price']),
  );

  final int id;
  final int travelerId;
  final String travelerName;
  final PersonPhoto? travelerPhoto;
  final AppLocation? startLocation;
  final AppLocation? destinationLocation;
  final CanonicalPlace? startPlace;
  final CanonicalPlace? destinationPlace;
  final JourneyStatus status;
  final DateTime? publishedAt;
  final String notes;
  final List<JourneyLeg> legs;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  /// Whether the server will accept an edit to this journey's route.
  ///
  /// The server decides, not the client: a draft can still be uneditable
  /// because a sender is already proposing against it. Null when the payload
  /// carried no answer — a counterparty's view, or a list row.
  final bool? editable;

  /// Why an edit is refused, when it is. One of `journey_not_editable`,
  /// `journey_has_dependent_state` or `journey_not_owned`.
  final String? editBlockedCode;

  /// Every stop with what it accepts. Empty when the payload carried none.
  final List<JourneyStop> stops;

  /// The item categories the traveller will not carry, and whether they take
  /// fragile items. Defaults match a journey that never set either.
  final List<String> refusedCategories;
  final bool acceptsFragile;

  /// Owner only; null for anyone else, who never sees a paused journey.
  final JourneyPause? pause;

  /// What the traveller charges, or null when no price is set.
  final JourneyPrice? price;

  bool get isPaused => pause?.paused ?? false;
  bool get isPausedByStaff => pause?.pausedByStaff ?? false;

  /// True only when the server has said so. A journey whose payload said
  /// nothing is not assumed editable just because its status looks right.
  bool get canEdit => editable == true;

  DateTime? get firstDeparture => legs.isEmpty ? null : legs.first.departAt;

  /// Legs that still block publication. Empty means proof is not the reason
  /// the journey cannot go live.
  List<JourneyLeg> get legsNeedingProof =>
      legs.where((l) => l.needsProof).toList(growable: false);

  /// The smallest declared capacity along the chain, which is the practical
  /// limit on what the journey can carry end to end.
  ///
  /// Presentation only — the server decides what actually fits, per leg, at
  /// proposal and again at acceptance.
  double? get narrowestCapacityKg {
    final values = legs
        .map((l) => l.capacityKg)
        .whereType<double>()
        .toList(growable: false);
    if (values.isEmpty) return null;
    return values.reduce((a, b) => a < b ? a : b);
  }
}

/// What one route edit did, as the server reports it.
///
/// Not decoration. An edit that sent a reviewed boarding pass back to the
/// queue has changed when the journey can go live, and the traveller has to
/// hear that from the screen that did it — not from a publish refusal days
/// later.
class JourneyRouteChange {
  const JourneyRouteChange({
    this.legsCreated = 0,
    this.legsUpdated = 0,
    this.legsRemoved = 0,
    this.proofsResetForReview = 0,
    this.proofsDiscarded = 0,
  });

  factory JourneyRouteChange.fromJson(Map<String, dynamic> json) =>
      JourneyRouteChange(
        legsCreated: readInt(json['legs_created']) ?? 0,
        legsUpdated: readInt(json['legs_updated']) ?? 0,
        legsRemoved: readInt(json['legs_removed']) ?? 0,
        proofsResetForReview: readInt(json['proofs_reset_for_review']) ?? 0,
        proofsDiscarded: readInt(json['proofs_discarded']) ?? 0,
      );

  final int legsCreated;
  final int legsUpdated;
  final int legsRemoved;

  /// Approved or pending ticket that has to be reviewed again, because the
  /// flight or crossing it evidenced materially changed.
  final int proofsResetForReview;

  /// Proof that went with a leg the edit removed entirely.
  final int proofsDiscarded;
}

CanonicalPlace? _place(Object? raw) {
  final value = readObject(raw);
  return value == null ? null : CanonicalPlace.fromJson(value);
}
