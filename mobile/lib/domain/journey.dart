/// A traveller's journey: an ordered chain of flight and drive legs.
///
/// The V1 model is deliberately not "a flight". Paris → Algiers by air then
/// Algiers → Jijel by road is one journey with two legs, and a sender's parcel
/// may ride a sub-range of it. Every leg carries its own capacity, so the
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

enum ProofStatus { pending, approved, rejected, unknown }

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
      flightNumber: readText(json['flight_number']),
      hasApprovedProof: readBool(json['has_approved_proof']),
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

  /// A flight leg with no approved proof blocks the whole journey from
  /// publishing. Drive legs never need one.
  bool get needsProof => mode.requiresProof && !hasApprovedProof;

  JourneyLegProof? get latestProof => proofs.isEmpty ? null : proofs.first;

  ProofStatus get proofStatus {
    if (!mode.requiresProof) return ProofStatus.approved;
    if (hasApprovedProof) return ProofStatus.approved;
    if (proofs.isEmpty) return ProofStatus.unknown;
    // A rejection is the more urgent fact when both exist.
    if (proofs.any((p) => p.status == ProofStatus.rejected)) {
      return ProofStatus.rejected;
    }
    return ProofStatus.pending;
  }
}

class Journey {
  const Journey({
    required this.id,
    required this.travelerId,
    required this.travelerName,
    required this.status,
    required this.notes,
    required this.legs,
    this.startLocation,
    this.destinationLocation,
    this.startPlace,
    this.destinationPlace,
    this.publishedAt,
    this.createdAt,
    this.updatedAt,
  });

  factory Journey.fromJson(Map<String, dynamic> json) => Journey(
    id: readInt(json['id']) ?? 0,
    travelerId: readInt(json['traveler_id']) ?? 0,
    travelerName: readText(json['traveler_name']),
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
  );

  final int id;
  final int travelerId;
  final String travelerName;
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

  DateTime? get firstDeparture => legs.isEmpty ? null : legs.first.departAt;
  DateTime? get lastArrival => legs.isEmpty ? null : legs.last.arriveAt;

  bool get isMultiLeg => legs.length > 1;

  bool get isMixedMode => legs.map((l) => l.mode).toSet().length > 1;

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

CanonicalPlace? _place(Object? raw) {
  final value = readObject(raw);
  return value == null ? null : CanonicalPlace.fromJson(value);
}
