/// Discovery, compatibility and pricing.
///
/// Everything here is a *server verdict*, rendered. The client does not rank,
/// does not score, does not decide compatibility and does not price. It shows
/// what came back and, when a candidate is refused, shows why using the
/// machine `rejection_codes` — never a parsed English string.
///
/// One asymmetry the API enforces and this file records honestly:
/// `recommendedReward` is present for a **sender** browsing travellers or
/// quoting, and absent for a **traveller** browsing requests. That is an
/// anti-harvest rule, not an oversight, so [PricingQuote.recommendedReward] is
/// nullable and the traveller UI must not imply a recommendation exists.
library;

import '../core/money/money.dart';
import 'json.dart';
import 'location.dart';
import 'transport_mode.dart';

/// The four numbers that describe one price, all server-computed.
class Economics {
  const Economics({
    required this.travelerReward,
    required this.commissionRateBps,
    required this.platformFee,
    required this.senderTotal,
  });

  static Economics? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return Economics(
      travelerReward: Money.eurCentsOrNull(json['traveler_reward_minor']),
      commissionRateBps: readInt(json['commission_rate_bps']),
      platformFee: Money.eurCentsOrNull(json['platform_fee_minor']),
      senderTotal: Money.eurCentsOrNull(json['sender_total_minor']),
    );
  }

  /// What the traveller is paid.
  final Money? travelerReward;

  /// Commission in basis points. Displayed, never applied.
  final int? commissionRateBps;

  /// Added **on top of** the reward, never deducted from it.
  final Money? platformFee;

  /// Reward plus fee. Comes from the server as its own field; this class never
  /// computes it.
  final Money? senderTotal;
}

class TimeWindow {
  const TimeWindow({this.start, this.end});

  static TimeWindow? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final window = TimeWindow(
      start: readDate(json['start']),
      end: readDate(json['end']),
    );
    return window.start == null && window.end == null ? null : window;
  }

  final DateTime? start;
  final DateTime? end;
}

class CoveredLeg {
  const CoveredLeg({
    required this.journeyLegId,
    required this.position,
    required this.mode,
    this.origin,
    this.destination,
    this.departAt,
    this.arriveAt,
  });

  /// A covered leg carries its endpoints under **two** key pairs and only one
  /// of them is ever populated. `origin`/`destination` hold the legacy
  /// user-owned `Location` rows; `origin_place`/`destination_place` hold the
  /// canonical catalogue `Place`. Every V1 journey is canonical, so on the live
  /// contract the first pair is null on every leg — reading only that pair is
  /// what made Find Travelers draw a route line of blank stops.
  factory CoveredLeg.fromJson(Map<String, dynamic> json) => CoveredLeg(
    journeyLegId: readInt(json['journey_leg_id']) ?? 0,
    position: readInt(json['position']) ?? 0,
    mode: TransportMode.parse(json['mode']),
    origin:
        AppLocation.maybe(json['origin']) ??
        AppLocation.maybe(json['origin_place']),
    destination:
        AppLocation.maybe(json['destination']) ??
        AppLocation.maybe(json['destination_place']),
    departAt: readDate(json['depart_at']),
    arriveAt: readDate(json['arrive_at']),
  );

  final int journeyLegId;
  final int position;

  /// Note: the compatibility payload sends this **lowercase** (`"drive"`),
  /// unlike a journey leg's own `"DRIVE"`. [TransportMode.parse] upper-cases
  /// before matching, so both arrive at the same value.
  final TransportMode mode;

  final AppLocation? origin;
  final AppLocation? destination;
  final DateTime? departAt;
  final DateTime? arriveAt;
}

/// The server's compatibility verdict for one request/journey pair.
class Compatibility {
  const Compatibility({
    required this.compatible,
    required this.rejectionCodes,
    required this.coveredLegIds,
    required this.coveredLegs,
    required this.limitations,
    required this.capacityAvailableOnEveryCoveredLeg,
    this.matchingVersion,
    this.startLegId,
    this.endLegId,
    this.estimatedPickupWindow,
    this.estimatedDeliveryWindow,
    this.matchedDistanceBand,
    this.matchedDistancePrecision = DistancePrecision.unknown,
    this.pickupDetour = DetourBand.unknown,
    this.deliveryDetour = DetourBand.unknown,
    this.totalAddedDistance = DetourBand.unknown,
  });

  static Compatibility? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return Compatibility(
      matchingVersion: readString(json['matching_version']),
      compatible: readBool(json['compatible']),
      rejectionCodes: readStringList(json['rejection_codes']),
      startLegId: readInt(json['start_leg_id']),
      endLegId: readInt(json['end_leg_id']),
      coveredLegIds: readIntList(json['covered_leg_ids']),
      coveredLegs: readObjectList(
        json['covered_legs'],
      ).map(CoveredLeg.fromJson).toList(growable: false),
      estimatedPickupWindow: TimeWindow.maybe(json['estimated_pickup_window']),
      estimatedDeliveryWindow: TimeWindow.maybe(
        json['estimated_delivery_window'],
      ),
      matchedDistanceBand: DistanceBand.maybe(json['matched_distance_band']),
      matchedDistancePrecision: readEnum(
        json['matched_distance_precision'],
        DistancePrecision.values,
        fallback: DistancePrecision.unknown,
      ),
      pickupDetour: DetourBand.parse(json['pickup_detour_band']),
      deliveryDetour: DetourBand.parse(json['delivery_detour_band']),
      totalAddedDistance: DetourBand.parse(json['total_added_distance_band']),
      capacityAvailableOnEveryCoveredLeg: readBool(
        json['capacity_available_on_every_covered_leg'],
        fallback: true,
      ),
      limitations: readStringList(json['limitations']),
    );
  }

  final String? matchingVersion;
  final bool compatible;

  /// Machine codes such as `capacity_available_on_every_leg` or
  /// `delivery_before_deadline`. More than one can be present; the UI must
  /// handle the list, not assume a single reason.
  final List<String> rejectionCodes;

  final int? startLegId;
  final int? endLegId;
  final List<int> coveredLegIds;
  final List<CoveredLeg> coveredLegs;
  final TimeWindow? estimatedPickupWindow;
  final TimeWindow? estimatedDeliveryWindow;
  final DistanceBand? matchedDistanceBand;
  final DistancePrecision matchedDistancePrecision;
  final DetourBand pickupDetour;
  final DetourBand deliveryDetour;
  final DetourBand totalAddedDistance;
  final bool capacityAvailableOnEveryCoveredLeg;
  final List<String> limitations;

  bool get spansMultipleLegs => coveredLegIds.length > 1;
}

/// The server's price for one candidate.
class PricingQuote {
  const PricingQuote({
    required this.currency,
    required this.commissionRateBps,
    required this.globalFloorApplied,
    required this.detourAdjustmentApplied,
    required this.urgencyAdjustmentApplied,
    this.matchedDistanceBand,
    this.actualWeightKg,
    this.volumetricWeightKg,
    this.chargeableWeightKg,
    this.minimumReward,
    this.minimumEconomics,
    this.recommendedReward,
    this.recommendedEconomics,
    this.pricingVersion,
    this.businessSettingsVersion,
  });

  static PricingQuote? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return PricingQuote(
      currency: readText(json['currency']).isEmpty
          ? 'EUR'
          : readText(json['currency']),
      matchedDistanceBand: DistanceBand.maybe(json['matched_distance_band']),
      actualWeightKg: readDouble(json['actual_weight_kg']),
      volumetricWeightKg: readDouble(json['volumetric_weight_kg']),
      chargeableWeightKg: readDouble(json['chargeable_weight_kg']),
      minimumReward: Money.eurCentsOrNull(json['minimum_reward_eur_cents']),
      minimumEconomics: Economics.maybe(json['minimum_economics']),
      recommendedReward: Money.eurCentsOrNull(
        json['recommended_reward_eur_cents'],
      ),
      recommendedEconomics: Economics.maybe(json['recommended_economics']),
      commissionRateBps: readInt(json['commission_rate_bps']),
      globalFloorApplied: readBool(json['global_floor_applied']),
      detourAdjustmentApplied: readBool(json['detour_adjustment_applied']),
      urgencyAdjustmentApplied: readBool(json['urgency_adjustment_applied']),
      pricingVersion: readString(json['pricing_version']),
      businessSettingsVersion: readInt(json['business_settings_version']),
    );
  }

  final String currency;
  final DistanceBand? matchedDistanceBand;

  final double? actualWeightKg;
  final double? volumetricWeightKg;

  /// The greater of actual and volumetric. The server picked it; the client
  /// shows which one won, it does not compare them itself.
  final double? chargeableWeightKg;

  /// The floor. An offer below this is refused server-side with
  /// `reward_below_minimum`.
  final Money? minimumReward;
  final Economics? minimumEconomics;

  /// Present for a sender browsing or quoting; **absent** for a traveller
  /// browsing requests.
  final Money? recommendedReward;
  final Economics? recommendedEconomics;

  final int? commissionRateBps;
  final bool globalFloorApplied;
  final bool detourAdjustmentApplied;
  final bool urgencyAdjustmentApplied;
  final String? pricingVersion;
  final int? businessSettingsVersion;

  bool get hasRecommendation => recommendedReward != null;

  /// True when volumetric weight is what is being charged — the fact that
  /// makes a light, bulky parcel cost more than the scales suggest.
  bool get isVolumetric {
    final chargeable = chargeableWeightKg;
    final actual = actualWeightKg;
    final volumetric = volumetricWeightKg;
    if (chargeable == null || actual == null || volumetric == null) {
      return false;
    }
    return volumetric > actual && chargeable == volumetric;
  }
}

/// The request as it appears inside a discovery candidate — coarse locations
/// only, no exact geometry.
class CandidateRequest {
  const CandidateRequest({
    required this.id,
    required this.senderId,
    this.pickup,
    this.delivery,
    this.actualWeightKg,
    this.readyWindowStart,
    this.readyWindowEnd,
    this.deadlineAt,
    this.senderProposedReward,
  });

  static CandidateRequest? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return CandidateRequest(
      id: readInt(json['id']) ?? 0,
      senderId: readInt(json['sender_id']) ?? 0,
      pickup:
          AppLocation.maybe(json['pickup']) ??
          AppLocation.maybe(json['pickup_place']),
      delivery:
          AppLocation.maybe(json['delivery']) ??
          AppLocation.maybe(json['delivery_place']),
      actualWeightKg: readDouble(json['actual_weight_kg']),
      readyWindowStart: readDate(json['ready_window_start']),
      readyWindowEnd: readDate(json['ready_window_end']),
      deadlineAt: readDate(json['deadline_at']),
      senderProposedReward: Money.eurCentsOrNull(
        json['sender_proposed_reward_eur_cents'],
      ),
    );
  }

  final int id;
  final int senderId;
  final AppLocation? pickup;
  final AppLocation? delivery;
  final double? actualWeightKg;
  final DateTime? readyWindowStart;
  final DateTime? readyWindowEnd;
  final DateTime? deadlineAt;

  /// The sender's posted intent, shown to a browsing traveller so they can
  /// judge whether waiting for a proposal is worth it. Not a price.
  final Money? senderProposedReward;
}

/// The journey as it appears inside a discovery candidate.
class CandidateJourney {
  const CandidateJourney({
    required this.id,
    required this.travelerId,
    required this.coveredLegs,
    this.startLocation,
    this.destinationLocation,
    this.firstDeparture,
    this.startLegId,
    this.endLegId,
  });

  static CandidateJourney? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return CandidateJourney(
      id: readInt(json['id']) ?? 0,
      travelerId: readInt(json['traveler_id']) ?? 0,
      // Same two-shape rule as a covered leg: the server fills
      // `start_location` with a canonical place summary when the journey has no
      // legacy Location, and sends the place under its own key as well.
      startLocation:
          AppLocation.maybe(json['start_location']) ??
          AppLocation.maybe(json['start_place']),
      destinationLocation:
          AppLocation.maybe(json['destination_location']) ??
          AppLocation.maybe(json['destination_place']),
      firstDeparture: readDate(json['first_departure']),
      startLegId: readInt(json['start_leg_id']),
      endLegId: readInt(json['end_leg_id']),
      coveredLegs: readObjectList(
        json['covered_legs'],
      ).map(CoveredLeg.fromJson).toList(growable: false),
    );
  }

  final int id;
  final int travelerId;
  final AppLocation? startLocation;
  final AppLocation? destinationLocation;
  final DateTime? firstDeparture;

  /// The sub-route the server calculated for this parcel. A proposal **must**
  /// echo these two ids back unchanged, or it is refused with
  /// `invalid_leg_range`.
  final int? startLegId;
  final int? endLegId;

  final List<CoveredLeg> coveredLegs;
}

/// One row in a discovery result.
class DiscoveryCandidate {
  const DiscoveryCandidate({
    this.request,
    this.journey,
    this.compatibility,
    this.pricing,
  });

  factory DiscoveryCandidate.fromJson(Map<String, dynamic> json) =>
      DiscoveryCandidate(
        request: CandidateRequest.maybe(json['delivery_request']),
        journey: CandidateJourney.maybe(json['journey']),
        compatibility: Compatibility.maybe(json['compatibility']),
        pricing: PricingQuote.maybe(json['pricing']),
      );

  final CandidateRequest? request;
  final CandidateJourney? journey;
  final Compatibility? compatibility;
  final PricingQuote? pricing;

  /// Everything a proposal needs, or null when the server did not resolve a
  /// leg range — in which case proposing is not possible and the UI must not
  /// offer it.
  ({int parcelId, int journeyId, int startLegId, int endLegId})?
  get proposalTarget {
    final requestId = request?.id;
    final journeyId = journey?.id;
    final start = journey?.startLegId ?? compatibility?.startLegId;
    final end = journey?.endLegId ?? compatibility?.endLegId;
    if (requestId == null || journeyId == null) return null;
    if (start == null || end == null) return null;
    return (
      parcelId: requestId,
      journeyId: journeyId,
      startLegId: start,
      endLegId: end,
    );
  }
}

/// The paged-but-not-really discovery envelope: `{count, results}` with no
/// page parameters — the server bounds the result set itself.
class DiscoveryResults {
  const DiscoveryResults({required this.count, required this.candidates});

  factory DiscoveryResults.fromJson(Map<String, dynamic> json) =>
      DiscoveryResults(
        count: readInt(json['count']) ?? 0,
        candidates: readObjectList(
          json['results'],
        ).map(DiscoveryCandidate.fromJson).toList(growable: false),
      );

  final int count;
  final List<DiscoveryCandidate> candidates;
}
