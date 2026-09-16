/// The frozen J4 Find Travelers contract.
///
/// `GET /api/matches/find-travelers` supersedes `compatible-journeys` for the
/// Sender's discovery screen. Everything on a row is a **server verdict**: the
/// client does not rank, does not classify fit, does not decide which actions
/// exist and does not price. It renders what arrived.
///
/// Three rules this decoder holds to, because each of them was a real defect
/// somewhere else in the app first:
///
/// * **Fit is a closed vocabulary, not a number.** [RouteFit] and [TimingFit]
///   parse to `unknown` rather than throwing, so a fourth classification added
///   server-side degrades one badge instead of the whole screen.
/// * **Nothing here implies distance.** There is no detour band, no matched
///   distance and no radius in the contract, because canonical V1 matching is
///   locality identity and has no such measurement to report. A card that says
///   "2 km away" would be inventing one.
/// * **A rating is never fabricated.** An unrated Traveler is
///   [TravelerRatingState.unrated], whose [TravelerRating.average] is null. `5.0` for
///   somebody who has never carried anything is a lie the UI must not tell.
library;

import 'json.dart';
import 'transport_mode.dart';

/// What the whole page is, before any row is read.
///
/// All three are HTTP 200 and none of them is a failure. A transport or auth
/// failure arrives as an `ApiException` and never as one of these.
enum DiscoveryState {
  /// At least one compatible Traveler.
  results,

  /// The request is live and matchable; nobody is going that way yet.
  noCandidates,

  /// The request itself cannot be matched. See [FindTravelersPage.reason].
  requestIneligible,

  unknown;

  static DiscoveryState parse(Object? raw) =>
      readEnum(raw, DiscoveryState.values, fallback: DiscoveryState.unknown);
}

/// Why a request cannot be matched at all.
///
/// Distinct from "nobody matches" because the sender's next action differs:
/// pay the deposit, wait, or nothing at all.
enum IneligibleReason {
  /// The posting deposit has not been captured, so the request is unpublished.
  awaitingDeposit,

  /// An offer was accepted; this request already has its Traveler.
  alreadyMatched,

  /// Cancelled or expired.
  closed,

  /// The parcel is already being carried.
  inProgress,

  unknown;

  static IneligibleReason? maybe(Object? raw) {
    if (readString(raw) == null) return null;
    return readEnum(
      raw,
      IneligibleReason.values,
      fallback: IneligibleReason.unknown,
    );
  }
}

/// How much of the Traveler's own trip is the Sender's route.
///
/// Emphatically **not** physical closeness. `excellent` means the parcel rides
/// the whole published Journey; `good` means it shares one end of it;
/// `compatible` means the Traveler passes through. All three passed every hard
/// gate — ShipTrip returns nothing that did not.
enum RouteFit {
  excellent,
  good,
  compatible,
  unknown;

  static RouteFit parse(Object? raw) =>
      readEnum(raw, RouteFit.values, fallback: RouteFit.unknown);
}

/// Margin between the carrying route's published arrival and the deadline.
enum TimingFit {
  /// At least a full day of margin.
  comfortable,

  /// Arrives before the deadline.
  fits,

  unknown;

  static TimingFit? maybe(Object? raw) {
    if (readString(raw) == null) return null;
    return readEnum(raw, TimingFit.values, fallback: TimingFit.unknown);
  }
}

enum TravelerRatingState {
  /// Has revealed ratings.
  rated,

  /// No revealed rating yet. Never render a number for this state.
  unrated,

  unknown;

  static TravelerRatingState parse(Object? raw) => readEnum(
    raw,
    TravelerRatingState.values,
    fallback: TravelerRatingState.unknown,
    // The wire says `new`, which is a Dart keyword and cannot be an enum
    // member name.
    aliases: const {'new': TravelerRatingState.unrated},
  );
}

/// An action the **server** says is available. Never inferred from local state.
enum CandidateAction {
  viewJourney,
  proposeOffer,
  unknown;

  static CandidateAction parse(Object? raw) =>
      readEnum(raw, CandidateAction.values, fallback: CandidateAction.unknown);
}

class AuthorizedAction {
  const AuthorizedAction({
    required this.code,
    required this.available,
    this.reason,
  });

  factory AuthorizedAction.fromJson(Map<String, dynamic> json) =>
      AuthorizedAction(
        code: CandidateAction.parse(json['code']),
        available: readBool(json['available']),
        reason: readString(json['reason']),
      );

  final CandidateAction code;
  final bool available;

  /// A machine code when [available] is false. Rendered through the client's
  /// own copy, never printed raw.
  final String? reason;
}

/// A Traveler's rating, or the honest absence of one.
class TravelerRating {
  const TravelerRating({
    required this.state,
    required this.count,
    this.average,
  });

  factory TravelerRating.fromJson(Map<String, dynamic>? json) {
    if (json == null) {
      return const TravelerRating(state: TravelerRatingState.unrated, count: 0);
    }
    return TravelerRating(
      state: TravelerRatingState.parse(json['state']),
      count: readInt(json['count']) ?? 0,
      average: readDouble(json['average']),
    );
  }

  final TravelerRatingState state;
  final int count;

  /// One decimal, and **null** for an unrated Traveler. The UI shows "New".
  final double? average;

  bool get hasScore => state == TravelerRatingState.rated && average != null;
}

/// Only enough of a person to decide whether to trust them with a parcel.
class CandidateTraveler {
  const CandidateTraveler({
    required this.id,
    required this.displayName,
    required this.identityVerified,
    required this.rating,
    required this.completedDeliveries,
    this.avatarUrl,
  });

  factory CandidateTraveler.fromJson(Map<String, dynamic>? json) {
    final data = json ?? const <String, dynamic>{};
    return CandidateTraveler(
      id: readInt(data['id']) ?? 0,
      displayName: readText(data['display_name']),
      // KYC is a hard compatibility gate, so this is true of every row in the
      // list. It belongs in the match explanation, not on a per-card badge
      // where a universal truth reads as a distinction.
      identityVerified: readBool(data['identity_verified']),
      rating: TravelerRating.fromJson(readObject(data['rating'])),
      completedDeliveries: readInt(data['completed_deliveries']) ?? 0,
      avatarUrl: readString(data['avatar_url']),
    );
  }

  final int id;

  /// First name only. Empty when the Traveler has no name on file — in which
  /// case the UI shows an anonymous Traveler, never an email local part.
  final String displayName;

  final bool identityVerified;
  final TravelerRating rating;
  final int completedDeliveries;

  /// Always null in V1: no profile photo exists anywhere in the data model.
  /// The field is here so landing photos later is not a contract change.
  final String? avatarUrl;
}

/// One node on the carrying route.
///
/// An airport is a **facet** of a stop, not a stop of its own: the label is the
/// city and [airportIata] rides beside it, so a route reads `Algiers · ALG`.
class RouteStopNode {
  const RouteStopNode({
    required this.placeId,
    required this.label,
    this.countryCode,
    this.airportIata,
    this.arriveAt,
    this.departAt,
  });

  factory RouteStopNode.fromJson(Map<String, dynamic> json) => RouteStopNode(
    placeId: readInt(json['place_id']),
    label: readText(json['label']),
    countryCode: readString(json['country_code']),
    airportIata: readString(json['airport_iata']),
    arriveAt: readDate(json['arrive_at']),
    departAt: readDate(json['depart_at']),
  );

  final int? placeId;
  final String label;
  final String? countryCode;
  final String? airportIata;

  /// Null on the first stop — nothing has arrived there yet.
  final DateTime? arriveAt;

  /// Null on the last stop — the parcel gets off.
  final DateTime? departAt;
}

class RouteSegmentLeg {
  const RouteSegmentLeg({
    required this.journeyLegId,
    required this.mode,
    this.departAt,
    this.arriveAt,
  });

  factory RouteSegmentLeg.fromJson(Map<String, dynamic> json) =>
      RouteSegmentLeg(
        journeyLegId: readInt(json['journey_leg_id']) ?? 0,
        mode: TransportMode.parse(json['mode']),
        departAt: readDate(json['depart_at']),
        arriveAt: readDate(json['arrive_at']),
      );

  final int journeyLegId;
  final TransportMode mode;
  final DateTime? departAt;
  final DateTime? arriveAt;
}

/// The carrying sub-route only — not the Traveler's whole itinerary.
class CandidateRoute {
  const CandidateRoute({
    required this.stops,
    required this.segments,
    required this.continuesBefore,
    required this.continuesAfter,
  });

  factory CandidateRoute.fromJson(Map<String, dynamic>? json) {
    final data = json ?? const <String, dynamic>{};
    return CandidateRoute(
      stops: readObjectList(
        data['stops'],
      ).map(RouteStopNode.fromJson).toList(growable: false),
      segments: readObjectList(
        data['segments'],
      ).map(RouteSegmentLeg.fromJson).toList(growable: false),
      continuesBefore: readBool(data['continues_before']),
      continuesAfter: readBool(data['continues_after']),
    );
  }

  /// N segments make N+1 stops, which is what a route line draws.
  final List<RouteStopNode> stops;
  final List<RouteSegmentLeg> segments;

  /// The Traveler's trip starts before this parcel joins it. Says *that* it
  /// continues, deliberately not *where*.
  final bool continuesBefore;

  /// The Traveler's trip carries on after the parcel gets off.
  final bool continuesAfter;
}

/// One claim in "Why this trip fits".
///
/// A code and its parameters, never an English sentence: the server does not
/// know the reader's language and the client does not parse prose.
class MatchReason {
  const MatchReason({required this.code, required this.params});

  factory MatchReason.fromJson(Map<String, dynamic> json) => MatchReason(
    code: readText(json['code']),
    params: readObject(json['params']) ?? const <String, dynamic>{},
  );

  final String code;
  final Map<String, dynamic> params;

  String? get place => readString(params['place']);
  int? get count => readInt(params['count']);
  String? get weightKg => readString(params['weight_kg']);
  DateTime? get arrivesAt => readDate(params['arrives_at']);
  DateTime? get deadlineAt => readDate(params['deadline_at']);
}

/// The four numbers the propose sheet renders. Nothing diagnostic.
class CandidateEconomics {
  const CandidateEconomics({
    required this.currency,
    this.minimumReward,
    this.minimumEconomics,
    this.recommendedReward,
    this.recommendedEconomics,
  });

  static CandidateEconomics? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return CandidateEconomics(
      currency: readText(json['currency']).isEmpty
          ? 'EUR'
          : readText(json['currency']),
      minimumReward: readInt(json['minimum_reward_eur_cents']),
      minimumEconomics: readObject(json['minimum_economics']),
      recommendedReward: readInt(json['recommended_reward_eur_cents']),
      recommendedEconomics: readObject(json['recommended_economics']),
    );
  }

  final String currency;

  /// The floor. An offer below it is refused with `reward_below_minimum`.
  final int? minimumReward;
  final Map<String, dynamic>? minimumEconomics;

  /// What the sender should offer. Present because the sender owns this
  /// request; a Traveler browsing requests never receives it.
  final int? recommendedReward;
  final Map<String, dynamic>? recommendedEconomics;
}

/// Everything `POST /api/matches/propose` needs, echoed back unchanged.
///
/// The server recomputes the sub-route and refuses a mismatch with
/// `invalid_leg_range`, which is not an error to apologise for but a signal
/// that the list is stale.
class ProposalTarget {
  const ProposalTarget({
    required this.journeyId,
    required this.startLegId,
    required this.endLegId,
  });

  static ProposalTarget? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final journeyId = readInt(json['journey_id']);
    final start = readInt(json['start_leg_id']);
    final end = readInt(json['end_leg_id']);
    if (journeyId == null || start == null || end == null) return null;
    return ProposalTarget(
      journeyId: journeyId,
      startLegId: start,
      endLegId: end,
    );
  }

  final int journeyId;
  final int startLegId;
  final int endLegId;
}

/// One row on Find Travelers. Route and fit first, person second, money last.
class TravelerCandidate {
  const TravelerCandidate({
    required this.journeyId,
    required this.traveler,
    required this.route,
    required this.routeFit,
    required this.transfers,
    required this.matchReasons,
    required this.caveats,
    required this.actions,
    this.timingFit,
    this.departsAt,
    this.arrivesAt,
    this.primaryMode = TransportMode.unknown,
    this.economics,
    this.proposal,
  });

  factory TravelerCandidate.fromJson(Map<String, dynamic> json) =>
      TravelerCandidate(
        journeyId: readInt(json['journey_id']) ?? 0,
        traveler: CandidateTraveler.fromJson(readObject(json['traveler'])),
        route: CandidateRoute.fromJson(readObject(json['route'])),
        routeFit: RouteFit.parse(json['route_fit']),
        timingFit: TimingFit.maybe(json['timing_fit']),
        departsAt: readDate(json['departs_at']),
        arrivesAt: readDate(json['arrives_at']),
        transfers: readInt(json['transfers']) ?? 0,
        primaryMode: TransportMode.parse(json['primary_mode']),
        matchReasons: readObjectList(
          json['match_reasons'],
        ).map(MatchReason.fromJson).toList(growable: false),
        caveats: readStringList(json['caveats']),
        economics: CandidateEconomics.maybe(json['economics']),
        proposal: ProposalTarget.maybe(json['proposal']),
        actions: readObjectList(
          json['actions'],
        ).map(AuthorizedAction.fromJson).toList(growable: false),
      );

  final int journeyId;
  final CandidateTraveler traveler;
  final CandidateRoute route;
  final RouteFit routeFit;
  final TimingFit? timingFit;
  final DateTime? departsAt;
  final DateTime? arrivesAt;

  /// Times the parcel changes leg. Zero is a direct carry.
  final int transfers;

  /// `FLIGHT` whenever any covered leg flies.
  final TransportMode primaryMode;

  final List<MatchReason> matchReasons;

  /// Machine codes for anything the matching verdict qualified. Empty on a
  /// canonical candidate.
  final List<String> caveats;

  final CandidateEconomics? economics;
  final ProposalTarget? proposal;
  final List<AuthorizedAction> actions;

  /// Whether the **server** says this action can be taken. A missing action is
  /// unavailable: the client never fills a gap in the contract with a guess.
  bool can(CandidateAction action) => actions.any(
    (candidate) => candidate.code == action && candidate.available,
  );
}

/// The sender's own request, sent once per page rather than on every row.
class DiscoveryRequestSummary {
  const DiscoveryRequestSummary({
    required this.id,
    required this.chosenRewardEurCents,
    required this.boostEurCents,
    required this.totalOfferedRewardEurCents,
    this.actualWeightKg,
    this.volumetricWeightKg,
    this.chargeableWeightKg,
    this.readyWindowStart,
    this.readyWindowEnd,
    this.deadlineAt,
  });

  static DiscoveryRequestSummary? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return DiscoveryRequestSummary(
      id: readInt(json['id']) ?? 0,
      actualWeightKg: readDouble(json['actual_weight_kg']),
      volumetricWeightKg: readDouble(json['volumetric_weight_kg']),
      chargeableWeightKg: readDouble(json['chargeable_weight_kg']),
      readyWindowStart: readDate(json['ready_window_start']),
      readyWindowEnd: readDate(json['ready_window_end']),
      deadlineAt: readDate(json['deadline_at']),
      chosenRewardEurCents: readInt(json['chosen_reward_eur_cents']) ?? 0,
      boostEurCents: readInt(json['boost_eur_cents']) ?? 0,
      totalOfferedRewardEurCents:
          readInt(json['total_offered_reward_eur_cents']) ?? 0,
    );
  }

  final int id;
  final double? actualWeightKg;
  final double? volumetricWeightKg;
  final double? chargeableWeightKg;
  final DateTime? readyWindowStart;
  final DateTime? readyWindowEnd;
  final DateTime? deadlineAt;

  /// The sender's own posted economics. Belongs in the propose sheet, not on a
  /// browse row: a sender already knows what they offered.
  final int chosenRewardEurCents;
  final int boostEurCents;
  final int totalOfferedRewardEurCents;

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

/// Real pagination: the server bounds the page and says whether there is more.
class DiscoveryPageInfo {
  const DiscoveryPageInfo({
    required this.limit,
    required this.offset,
    required this.total,
    required this.hasMore,
    this.nextOffset,
  });

  static DiscoveryPageInfo fromJson(Map<String, dynamic>? json) {
    final data = json ?? const <String, dynamic>{};
    return DiscoveryPageInfo(
      limit: readInt(data['limit']) ?? 0,
      offset: readInt(data['offset']) ?? 0,
      total: readInt(data['total']) ?? 0,
      hasMore: readBool(data['has_more']),
      nextOffset: readInt(data['next_offset']),
    );
  }

  final int limit;
  final int offset;
  final int total;
  final bool hasMore;

  /// Where the next read starts. Null on the last page — the client does not
  /// compute it, because a client that computes an offset can skip a row.
  final int? nextOffset;
}

/// One page of Find Travelers.
class FindTravelersPage {
  const FindTravelersPage({
    required this.state,
    required this.sort,
    required this.page,
    required this.candidates,
    this.reason,
    this.requestStatus,
    this.request,
  });

  factory FindTravelersPage.fromJson(Map<String, dynamic> json) =>
      FindTravelersPage(
        state: DiscoveryState.parse(json['state']),
        sort: readText(json['sort']),
        reason: IneligibleReason.maybe(json['reason']),
        requestStatus: readString(json['request_status']),
        request: DiscoveryRequestSummary.maybe(json['request']),
        page: DiscoveryPageInfo.fromJson(readObject(json['page'])),
        candidates: readObjectList(
          json['results'],
        ).map(TravelerCandidate.fromJson).toList(growable: false),
      );

  final DiscoveryState state;
  final String sort;
  final DiscoveryPageInfo page;
  final List<TravelerCandidate> candidates;

  /// Present only when [state] is [DiscoveryState.requestIneligible].
  final IneligibleReason? reason;
  final String? requestStatus;

  /// Absent when the request is ineligible — there is nothing to browse for.
  final DiscoveryRequestSummary? request;
}
