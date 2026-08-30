/// Every repository, and the providers that expose them.
///
/// Repositories are thin: a path, a body, a parse. They hold no state, do no
/// caching and make no product decisions. Everything a screen needs to know
/// about *what a failure means* comes from [ApiException]; everything it needs
/// to know about *what is allowed* comes from the server fields the models
/// already carry.
///
/// One rule runs through the whole file and is worth stating once: **no method
/// here computes money, eligibility, ordering or timing.** Where a screen
/// seems to need such a value, the corresponding server field exists; if it
/// does not, that is a backend finding, not a place to improvise.
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_client.dart';
import '../core/env/app_config.dart';
import '../core/session/session.dart';
import '../domain/boost.dart';
import '../domain/cancellation.dart';
import '../domain/chat.dart';
import '../domain/communication_language.dart';
import '../domain/deal.dart';
import '../domain/delivery_request.dart';
import '../domain/discovery.dart';
import '../domain/dispute.dart';
import '../domain/handover.dart';
import '../domain/journey.dart';
import '../domain/kyc.dart';
import '../domain/location.dart';
import '../domain/notification.dart';
import '../domain/offer.dart';
import '../domain/payment.dart';
import '../domain/rating.dart';

// ---------------------------------------------------------------------------
// Locations
// ---------------------------------------------------------------------------

class LocationRepository {
  const LocationRepository(this._api);

  final ApiClient _api;

  /// The caller's own saved places, plus the shared trusted airports.
  ///
  /// The response is a **mixed** array: the caller's own rows arrive in the
  /// private shape with exact coordinates, the shared airports in the coarse
  /// public one. [AppLocation.isExact] distinguishes them.
  Future<List<AppLocation>> mine({CancelToken? cancelToken}) async {
    final rows = await _api.getList('/api/locations', cancelToken: cancelToken);
    return rows
        .map(AppLocation.maybe)
        .whereType<AppLocation>()
        .toList(growable: false);
  }

  Future<AppLocation> byId(int id, {CancelToken? cancelToken}) async =>
      AppLocation.fromJson(
        await _api.getObject('/api/locations/$id', cancelToken: cancelToken),
      );

  /// Creates a place owned by the caller.
  ///
  /// `public_label`, `coarse_latitude` and `coarse_longitude` are derived
  /// server-side and are rejected if sent, so they are absent here by design.
  Future<AppLocation> create({
    required LocationKind kind,
    required String normalizedLabel,
    required String privateLabel,
    required String city,
    required String countryCode,
    required double latitude,
    required double longitude,
    String region = '',
    LocationPrecision precision = LocationPrecision.unknown,
    String? provider,
    String? providerPlaceId,
    String? airportIata,
  }) async => AppLocation.fromJson(
    await _api.postObject(
      '/api/locations',
      body: {
        'kind': _kindWire(kind),
        'normalized_label': normalizedLabel,
        'private_label': privateLabel,
        'city': city,
        'region': region,
        'country_code': countryCode.toUpperCase(),
        'latitude': latitude.toStringAsFixed(6),
        'longitude': longitude.toStringAsFixed(6),
        'precision': _precisionWire(precision),
        if (provider != null && provider.isNotEmpty) 'provider': provider,
        if (providerPlaceId != null && providerPlaceId.isNotEmpty)
          'provider_place_id': providerPlaceId,
        'airport': ?airportIata,
      },
    ),
  );

  Future<List<Airport>> airports({
    String? country,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/airports',
      query: {if (country != null) 'country': country.toUpperCase()},
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => Airport.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }

  static String _kindWire(LocationKind kind) => switch (kind) {
    LocationKind.city => 'city',
    LocationKind.exactAddress => 'exact_address',
    LocationKind.mapPoint => 'map_point',
    LocationKind.airport => 'airport',
    LocationKind.publicMeetingPoint => 'public_meeting_point',
    LocationKind.unknown => 'city',
  };

  static String _precisionWire(LocationPrecision precision) =>
      switch (precision) {
        LocationPrecision.unknown => 'unknown',
        LocationPrecision.neighborhood => 'neighborhood',
        _ => precision.name,
      };
}

// ---------------------------------------------------------------------------
// Journeys
// ---------------------------------------------------------------------------

/// One leg as the create endpoint wants it.
class JourneyLegDraft {
  const JourneyLegDraft({
    required this.position,
    required this.mode,
    required this.originId,
    required this.destinationId,
    required this.departAt,
    required this.capacityKg,
    this.arriveAt,
    this.flightNumber = '',
  });

  final int position;
  final TransportModeDraft mode;
  final int originId;
  final int destinationId;
  final DateTime departAt;
  final DateTime? arriveAt;
  final double capacityKg;

  /// Required and non-empty for a flight leg; must be empty for a drive leg.
  final String flightNumber;

  Map<String, dynamic> toJson() => {
    'position': position,
    'mode': mode.wire,
    'origin': originId,
    'destination': destinationId,
    'depart_at': departAt.toUtc().toIso8601String(),
    if (arriveAt != null) 'arrive_at': arriveAt!.toUtc().toIso8601String(),
    'capacity_kg': capacityKg.toStringAsFixed(2),
    'flight_number': flightNumber,
  };
}

/// The two modes a draft leg may declare. Deliberately not the parsed
/// [TransportMode], which has an `unknown` member that must never be sent.
enum TransportModeDraft {
  flight,
  drive;

  String get wire => this == flight ? 'FLIGHT' : 'DRIVE';
}

class JourneyRepository {
  const JourneyRepository(this._api);

  final ApiClient _api;

  Future<List<Journey>> mine({
    JourneyStatus? status,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/journeys',
      query: {if (status != null) 'status': _statusWire(status)},
      cancelToken: cancelToken,
    );
    return _parseJourneys(rows);
  }

  Future<Journey> byId(int id, {CancelToken? cancelToken}) async =>
      Journey.fromJson(
        await _api.getObject('/api/journeys/$id', cancelToken: cancelToken),
      );

  Future<Journey> create({
    required int startLocationId,
    required int destinationLocationId,
    required List<JourneyLegDraft> legs,
    String notes = '',
  }) async => Journey.fromJson(
    await _api.postObject(
      '/api/journeys',
      body: {
        'start_location': startLocationId,
        'destination_location': destinationLocationId,
        'notes': notes,
        'legs': legs.map((l) => l.toJson()).toList(growable: false),
      },
    ),
  );

  /// Idempotent: publishing an already-active journey returns it unchanged.
  Future<Journey> publish(int id) async =>
      Journey.fromJson(await _api.postObject('/api/journeys/$id/publish'));

  /// Returns the journey plus how many pending reservations were released.
  Future<({Journey journey, int releasedAllocations, bool changed})> cancel(
    int id,
  ) async {
    final body = await _api.postObject('/api/journeys/$id/cancel');
    return (
      journey: Journey.fromJson(
        Map<String, dynamic>.from(body['journey'] as Map? ?? const {}),
      ),
      releasedAllocations: (body['released_allocations'] as num?)?.toInt() ?? 0,
      changed: body['changed'] == true,
    );
  }

  /// Uploads flight proof for one leg. Only accepted before publication, and
  /// only on a flight leg.
  Future<JourneyLegProof> uploadProof({
    required int journeyId,
    required int legId,
    required String filePath,
    required String fileName,
    String kind = 'ticket',
    void Function(int sent, int total)? onProgress,
    CancelToken? cancelToken,
  }) async => JourneyLegProof.fromJson(
    await _api.upload(
      '/api/journeys/$journeyId/legs/$legId/proof',
      form: FormData.fromMap({
        'kind': kind,
        'photo': await MultipartFile.fromFile(filePath, filename: fileName),
      }),
      onProgress: onProgress,
      cancelToken: cancelToken,
    ),
  );

  /// Active journeys other than the caller's own, already filtered server-side
  /// to those whose traveller is verified and whose flight legs are proven.
  Future<List<Journey>> search({
    int? startLocationId,
    int? destinationLocationId,
    TransportModeDraft? mode,
    DateTime? departureAfter,
    double? minCapacityKg,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/journeys/search',
      query: {
        'start_location_id': ?startLocationId,
        'destination_location_id': ?destinationLocationId,
        if (mode != null) 'mode': mode.wire,
        if (departureAfter != null)
          'departure_after': departureAfter.toUtc().toIso8601String(),
        if (minCapacityKg != null)
          'min_capacity_kg': minCapacityKg.toStringAsFixed(2),
      },
      cancelToken: cancelToken,
    );
    return _parseJourneys(rows);
  }

  static List<Journey> _parseJourneys(List<dynamic> rows) => rows
      .whereType<Map>()
      .map((r) => Journey.fromJson(Map<String, dynamic>.from(r)))
      .toList(growable: false);

  static String _statusWire(JourneyStatus status) => switch (status) {
    JourneyStatus.pendingVerification => 'pending_verification',
    JourneyStatus.inProgress => 'in_progress',
    _ => status.name,
  };
}

// ---------------------------------------------------------------------------
// Delivery requests
// ---------------------------------------------------------------------------

/// The V1 create body. Strict: the server rejects any field it does not know,
/// so this carries exactly the accepted set and nothing else.
class DeliveryRequestDraft {
  const DeliveryRequestDraft({
    required this.pickupLocationId,
    required this.deliveryLocationId,
    required this.readyWindowStart,
    required this.readyWindowEnd,
    required this.deadlineAt,
    required this.actualWeightKg,
    required this.declaredValueEurCents,
    required this.senderProposedRewardEurCents,
    required this.title,
    required this.description,
    required this.category,
    required this.acknowledgements,
    this.lengthCm,
    this.widthCm,
    this.heightCm,
    this.handlingNotes = '',
    this.fragile = false,
    this.targetTravelerId,
  });

  final int pickupLocationId;
  final int deliveryLocationId;
  final DateTime readyWindowStart;
  final DateTime readyWindowEnd;
  final DateTime deadlineAt;
  final double actualWeightKg;

  /// All three together or none: the server refuses a partial set.
  final double? lengthCm;
  final double? widthCm;
  final double? heightCm;

  final int declaredValueEurCents;

  /// The sender's posted intent, in cents. Not a price.
  final int senderProposedRewardEurCents;

  final String title;
  final String description;
  final ItemCategory category;
  final String handlingNotes;
  final bool fragile;
  final int? targetTravelerId;
  final SafetyAcknowledgements acknowledgements;

  Map<String, dynamic> toJson() => {
    'pickup_location_id': pickupLocationId,
    'delivery_location_id': deliveryLocationId,
    'ready_window_start': readyWindowStart.toUtc().toIso8601String(),
    'ready_window_end': readyWindowEnd.toUtc().toIso8601String(),
    'deadline_at': deadlineAt.toUtc().toIso8601String(),
    'actual_weight_kg': actualWeightKg.toStringAsFixed(2),
    if (lengthCm != null) 'length_cm': lengthCm!.toStringAsFixed(2),
    if (widthCm != null) 'width_cm': widthCm!.toStringAsFixed(2),
    if (heightCm != null) 'height_cm': heightCm!.toStringAsFixed(2),
    'declared_value_eur_cents': declaredValueEurCents,
    'sender_proposed_reward_eur_cents': senderProposedRewardEurCents,
    'title': title,
    'description': description,
    'category': _categoryWire(category),
    'handling_notes': handlingNotes,
    'fragile': fragile,
    if (targetTravelerId != null) 'target_traveler_id': targetTravelerId,
    ...acknowledgements.toJson(),
  };

  static String _categoryWire(ItemCategory category) => switch (category) {
    ItemCategory.smallBox => 'small_box',
    ItemCategory.unknown => 'other',
    _ => category.name,
  };
}

/// A created request, plus the deposit obligation that came with it.
class CreatedRequest {
  const CreatedRequest({required this.request, this.postingDeposit});

  final DeliveryRequest request;

  /// Null when the platform's timing policy does not charge a deposit at
  /// posting time. This key exists **only** on the create response.
  final PaymentOrder? postingDeposit;
}

class RequestRepository {
  const RequestRepository(this._api);

  final ApiClient _api;

  Future<List<DeliveryRequest>> mine({
    RequestStatus? status,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/parcels',
      query: {if (status != null) 'status': _statusWire(status)},
      cancelToken: cancelToken,
    );
    return _parse(rows);
  }

  Future<DeliveryRequest> byId(int id, {CancelToken? cancelToken}) async =>
      DeliveryRequest.fromJson(
        await _api.getObject('/api/parcels/$id', cancelToken: cancelToken),
      );

  Future<CreatedRequest> create(DeliveryRequestDraft draft) async {
    final body = await _api.postObject(
      '/api/parcels/delivery/v1',
      body: draft.toJson(),
    );
    final deposit = body['posting_deposit'];
    return CreatedRequest(
      request: DeliveryRequest.fromJson(body),
      postingDeposit: deposit is Map
          ? PaymentOrder.fromJson(Map<String, dynamic>.from(deposit))
          : null,
    );
  }

  Future<DeliveryRequest> cancel(int id) async => DeliveryRequest.fromJson(
    await _api.postObject('/api/parcels/$id/cancel'),
  );

  Future<ParcelMedia> uploadPhoto({
    required int requestId,
    required String filePath,
    required String fileName,
    void Function(int sent, int total)? onProgress,
    CancelToken? cancelToken,
  }) async => ParcelMedia.fromJson(
    await _api.upload(
      '/api/parcels/$requestId/media',
      form: FormData.fromMap({
        'photo': await MultipartFile.fromFile(filePath, filename: fileName),
      }),
      onProgress: onProgress,
      cancelToken: cancelToken,
    ),
  );

  /// Open requests from other senders, for a browsing traveller.
  ///
  /// Note this is the untargeted, deadline-in-future feed. Real matching is
  /// `compatible-requests`, which is journey-aware; this is the shallower
  /// "what is out there" list.
  Future<List<DeliveryRequest>> openFeed({
    double? maxWeightKg,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/parcels/open',
      query: {
        if (maxWeightKg != null)
          'max_weight_kg': maxWeightKg.toStringAsFixed(2),
      },
      cancelToken: cancelToken,
    );
    return _parse(rows);
  }

  static List<DeliveryRequest> _parse(List<dynamic> rows) => rows
      .whereType<Map>()
      .map((r) => DeliveryRequest.fromJson(Map<String, dynamic>.from(r)))
      .toList(growable: false);

  static String _statusWire(RequestStatus status) => switch (status) {
    RequestStatus.awaitingDeposit => 'awaiting_deposit',
    RequestStatus.inTransit => 'in_transit',
    _ => status.name,
  };
}

// ---------------------------------------------------------------------------
// Matching: discovery, quoting, negotiation
// ---------------------------------------------------------------------------

class MatchingRepository {
  const MatchingRepository(this._api);

  final ApiClient _api;

  /// Travellers compatible with one of my requests. Sender-only, and the only
  /// discovery call that carries a recommended reward.
  Future<DiscoveryResults> compatibleJourneys({
    required int parcelId,
    CancelToken? cancelToken,
  }) async => DiscoveryResults.fromJson(
    await _api.getObject(
      '/api/matches/compatible-journeys',
      query: {'parcel_id': parcelId},
      cancelToken: cancelToken,
    ),
  );

  /// Requests compatible with one of my journeys. Traveller-only. Carries the
  /// minimum reward but deliberately **no** recommendation.
  Future<DiscoveryResults> compatibleRequests({
    required int journeyId,
    CancelToken? cancelToken,
  }) async => DiscoveryResults.fromJson(
    await _api.getObject(
      '/api/matches/compatible-requests',
      query: {'journey_id': journeyId},
      cancelToken: cancelToken,
    ),
  );

  /// A price for one request/journey pair. Sender-only.
  ///
  /// An incompatible pair is a `409` carrying `rejection_codes`, surfaced as an
  /// [ApiException] rather than as a null return, so the caller can explain
  /// *why* rather than showing an empty screen.
  Future<DiscoveryCandidate> quote({
    required int parcelId,
    required int journeyId,
  }) async => DiscoveryCandidate.fromJson(
    await _api.postObject(
      '/api/matches/quote',
      body: {'parcel_id': parcelId, 'journey_id': journeyId},
    ),
  );

  /// The sender proposes. Always the first move in V1.
  ///
  /// The leg range must be exactly what discovery returned — the server
  /// recomputes it and refuses a mismatch with `invalid_leg_range` rather than
  /// silently accepting a different sub-route.
  Future<Offer> propose({
    required int parcelId,
    required int journeyId,
    required int startLegId,
    required int endLegId,
    required int travelerRewardEurCents,
    String note = '',
  }) async => Offer.fromJson(
    await _api.postObject(
      '/api/matches/propose',
      body: {
        'parcel_id': parcelId,
        'journey_id': journeyId,
        'start_leg_id': startLegId,
        'end_leg_id': endLegId,
        'traveler_reward_eur_cents': travelerRewardEurCents,
        'note': note,
      },
    ),
  );

  /// Counter with a different reward. Creates a **new** offer; the parent
  /// becomes `countered`.
  Future<Offer> counter({
    required int offerId,
    required int travelerRewardEurCents,
    String note = '',
  }) async => Offer.fromJson(
    await _api.postObject(
      '/api/offers/$offerId/counter',
      body: {'traveler_reward_eur_cents': travelerRewardEurCents, 'note': note},
    ),
  );

  /// Accepting creates the Deal, which arrives in `payment_required`.
  ///
  /// Idempotent server-side: accepting an already-accepted offer returns the
  /// existing Deal rather than failing.
  Future<Deal> accept(int offerId) async =>
      Deal.fromJson(await _api.postObject('/api/offers/$offerId/accept'));

  Future<Offer> decline(int offerId) async =>
      Offer.fromJson(await _api.postObject('/api/offers/$offerId/decline'));

  Future<Offer> withdraw(int offerId) async =>
      Offer.fromJson(await _api.postObject('/api/offers/$offerId/withdraw'));

  Future<List<Match>> matches({
    String? role,
    MatchStatus? status,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/matches',
      query: {
        'role': ?role,
        if (status != null) 'status': _matchStatusWire(status),
      },
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => Match.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }

  Future<Match> match(int id, {CancelToken? cancelToken}) async =>
      Match.fromJson(
        await _api.getObject('/api/matches/$id', cancelToken: cancelToken),
      );

  /// The full offer chain on a match, newest first, including declined and
  /// withdrawn history.
  Future<List<Offer>> offers(int matchId, {CancelToken? cancelToken}) async {
    final rows = await _api.getList(
      '/api/matches/$matchId/offers',
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => Offer.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }

  Future<Match> cancelMatch(int matchId) async =>
      Match.fromJson(await _api.postObject('/api/matches/$matchId/cancel'));

  static String _matchStatusWire(MatchStatus status) => switch (status) {
    MatchStatus.inTransit => 'in_transit',
    _ => status.name,
  };
}

// ---------------------------------------------------------------------------
// Deals
// ---------------------------------------------------------------------------

class DealRepository {
  const DealRepository(this._api);

  final ApiClient _api;

  /// Paginated, 20 per page.
  Future<List<Deal>> list({
    DealStatus? status,
    int page = 1,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/deals',
      query: {
        if (status != null) 'status': dealStatusWire(status),
        if (page > 1) 'page': page,
      },
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => Deal.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }

  /// The aggregate: terms, allocations, recipient, handover, protection,
  /// dispute, cancellation availability and ratings in one call.
  Future<Deal> byId(int id, {CancelToken? cancelToken}) async => Deal.fromJson(
    await _api.getObject('/api/deals/$id', cancelToken: cancelToken),
  );

  /// Sender-only, and only while funded and before pickup.
  ///
  /// [communicationLanguage] is the language of the recipient's delivery-code
  /// email. Omitting it is meaningful on the server, not merely tolerated: a
  /// new recipient inherits the sender's stored preference and an existing one
  /// keeps whatever is already stored. The screen therefore sends a value only
  /// when it has an authoritative one to send.
  Future<Deal> setRecipient({
    required int dealId,
    required String fullName,
    required String email,
    String phone = '',
    String deliveryNote = '',
    CommunicationLanguage? communicationLanguage,
  }) async {
    final body = await _api.putObject(
      '/api/deals/$dealId/recipient',
      body: {
        'full_name': fullName.trim(),
        'email': email.trim(),
        'phone': phone.trim(),
        'delivery_note': deliveryNote,
        if (communicationLanguage != null)
          'communication_language': communicationLanguage.wire,
      },
    );
    return Deal.fromJson(
      Map<String, dynamic>.from(body['deal'] as Map? ?? const {}),
    );
  }

  /// What cancelling would cost, before the user commits to it.
  ///
  /// Returns `200` even when cancellation is refused — the refusal is the
  /// thing the user needs to read.
  Future<CancellationQuote> cancellationQuote(
    int dealId, {
    CancelToken? cancelToken,
  }) async => CancellationQuote.fromJson(
    await _api.getObject(
      '/api/deals/$dealId/cancellation',
      cancelToken: cancelToken,
    ),
  );

  /// One endpoint, two policies. The server decides which applies from the
  /// Deal's own status; the client does not choose.
  Future<({Deal deal, CancellationOutcome outcome})> cancel({
    required int dealId,
    String? reason,
  }) async {
    final body = await _api.postObject(
      '/api/deals/$dealId/cancel',
      body: {if (reason != null && reason.isNotEmpty) 'reason': reason},
    );
    return (
      deal: Deal.fromJson(
        Map<String, dynamic>.from(body['deal'] as Map? ?? const {}),
      ),
      outcome: CancellationOutcome.fromJson(body),
    );
  }
}

String dealStatusWire(DealStatus status) => switch (status) {
  DealStatus.offerAccepted => 'offer_accepted',
  DealStatus.paymentRequired => 'payment_required',
  DealStatus.pickupReady => 'pickup_ready',
  DealStatus.pickedUp => 'picked_up',
  DealStatus.inTransit => 'in_transit',
  DealStatus.deliveryReady => 'delivery_ready',
  DealStatus.deliveryConfirmed => 'delivery_confirmed',
  DealStatus.protectionWindow => 'protection_window',
  DealStatus.paymentFailed => 'payment_failed',
  DealStatus.partiallyRefunded => 'partially_refunded',
  _ => status.name,
};

// ---------------------------------------------------------------------------
// Handover
// ---------------------------------------------------------------------------

class HandoverRepository {
  const HandoverRepository(this._api);

  final ApiClient _api;

  /// The same shape reaches both parties; only the permission booleans differ.
  Future<HandoverState> state(int dealId, {CancelToken? cancelToken}) async {
    final json = await _api.getObject(
      '/api/deals/$dealId/handover',
      cancelToken: cancelToken,
    );
    return HandoverState.maybe(json)!;
  }

  /// **Sender only.** A traveller calling this receives `403 not_authorized`.
  ///
  /// The returned plaintext is transient: it belongs in screen state for as
  /// long as the sender is looking at it and nowhere else. Never persist it,
  /// never log it, never put it in an analytics event.
  Future<RevealedCode> revealPickupCode(int dealId) async =>
      RevealedCode.fromJson(
        await _api.getObject('/api/deals/$dealId/handover/pickup-code'),
      );

  /// **Sender only**, and refused with `delivery_code_buffer_open` until the
  /// server's own 30-minute window has elapsed.
  ///
  /// There is no traveller equivalent of this method anywhere in the app, and
  /// there must never be one.
  Future<RevealedCode> revealDeliveryCode(int dealId) async =>
      RevealedCode.fromJson(
        await _api.getObject('/api/deals/$dealId/handover/delivery-code'),
      );

  Future<RevealedCode> rotatePickupCode(int dealId) async =>
      RevealedCode.fromJson(
        await _api.postObject('/api/deals/$dealId/handover/pickup-code/rotate'),
      );

  Future<RevealedCode> rotateDeliveryCode(int dealId) async =>
      RevealedCode.fromJson(
        await _api.postObject(
          '/api/deals/$dealId/handover/delivery-code/rotate',
        ),
      );

  /// **Traveller only.** The code came from the sender, in person.
  Future<HandoverSubmission> submitPickupCode({
    required int dealId,
    required String code,
  }) async => HandoverSubmission.fromJson(
    await _api.postObject(
      '/api/deals/$dealId/handover/pickup',
      body: {'code': code},
    ),
  );

  /// **Traveller only.** The code came from the recipient, at the door.
  Future<HandoverSubmission> submitDeliveryCode({
    required int dealId,
    required String code,
  }) async => HandoverSubmission.fromJson(
    await _api.postObject(
      '/api/deals/$dealId/handover/delivery',
      body: {'code': code},
    ),
  );
}

// ---------------------------------------------------------------------------
// Payments
// ---------------------------------------------------------------------------

class PaymentRepository {
  const PaymentRepository(this._api);

  final ApiClient _api;

  Future<ProvidersView> providers({CancelToken? cancelToken}) async =>
      ProvidersView.fromJson(
        await _api.getObject(
          '/api/payments/providers',
          cancelToken: cancelToken,
        ),
      );

  Future<List<PaymentOrder>> orders({
    PaymentPurpose? purpose,
    PaymentOrderStatus? status,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/payments/orders',
      query: {
        if (purpose != null) 'purpose': _purposeWire(purpose),
        if (status != null) 'status': _orderStatusWire(status),
      },
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => PaymentOrder.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }

  /// The authoritative post-redirect poll.
  ///
  /// A provider's return URL proves nothing. This is what a "confirming your
  /// payment" screen reads until `status` flips or the attempt dies.
  Future<PaymentOrder> order(
    String reference, {
    CancelToken? cancelToken,
  }) async => PaymentOrder.fromJson(
    await _api.getObject(
      '/api/payments/orders/$reference',
      cancelToken: cancelToken,
    ),
  );

  /// Opens a hosted checkout. The response carries a `checkout_url` and
  /// nothing else usable — there is no client secret and no embedded form.
  ///
  /// Amounts, currencies and rates are **not** sent: the server rejects the
  /// whole request if any of them appear.
  Future<PaymentAttempt> checkout({
    required String reference,
    required PaymentProviderId provider,
  }) async => PaymentAttempt.fromJson(
    await _api.postObject(
      '/api/payments/orders/$reference/checkout',
      body: {'provider': provider.wire},
    ),
  );

  /// Creates a shareable link so somebody else can pay this obligation.
  ///
  /// The raw token comes back exactly once and is not recoverable afterwards;
  /// issuing a new link revokes the previous one.
  ///
  /// [communicationLanguage] is the language of the guest payer's receipt. The
  /// server snapshots it onto the link at issue time, so a later change to the
  /// owner's own preference cannot rewrite a message already owed. Omitting it
  /// tells the server to snapshot the owner's resolved preference, which is
  /// the correct behaviour when the caller has no more specific instruction.
  Future<GuestPaymentLink> createGuestLink({
    required String reference,
    String label = '',
    CommunicationLanguage? communicationLanguage,
  }) async => GuestPaymentLink.fromJson(
    await _api.postObject(
      '/api/payments/orders/$reference/guest-link',
      body: {
        if (label.isNotEmpty) 'label': label,
        if (communicationLanguage != null)
          'communication_language': communicationLanguage.wire,
      },
    ),
  );

  Future<int> revokeGuestLink(String reference) async {
    final body = await _api.postObject(
      '/api/payments/orders/$reference/guest-link/revoke',
    );
    return (body['revoked'] as num?)?.toInt() ?? 0;
  }

  /// Anonymous. Every invalid reason collapses to one `guest_link_invalid`
  /// response so a prober learns nothing.
  Future<GuestPaymentView> guestView(String token) async =>
      GuestPaymentView.fromJson(
        await _api.getObject('/api/payments/guest/$token'),
      );

  /// Starts the anonymous hosted checkout. The email is a receipt destination
  /// only; it never becomes a ShipTrip identity and does not expand guest
  /// permissions. The server requires it when transactional email is enabled.
  Future<GuestCheckout> guestCheckout({
    required String token,
    required PaymentProviderId provider,
    String? email,
  }) async => GuestCheckout.fromJson(
    await _api.postObject(
      '/api/payments/guest/$token/checkout',
      body: {
        'provider': provider.wire,
        if (email != null && email.trim().isNotEmpty) 'email': email.trim(),
      },
    ),
  );

  Future<PostingDepositState> postingDeposit(
    int requestId, {
    CancelToken? cancelToken,
  }) async => PostingDepositState.fromJson(
    await _api.getObject(
      '/api/parcels/$requestId/posting-deposit',
      cancelToken: cancelToken,
    ),
  );

  /// Idempotent create-or-return.
  Future<PaymentOrder> createPostingDeposit(int requestId) async =>
      PaymentOrder.fromJson(
        await _api.postObject('/api/parcels/$requestId/posting-deposit'),
      );

  /// The Deal's balance obligation.
  ///
  /// There is no POST here: paying goes through [checkout] against the
  /// returned order's reference. The traveller's copy is deliberately reduced
  /// to a status and an outstanding amount, which [viewerIsTraveler] records
  /// so no screen misreads the absence of attempts as "never attempted".
  Future<DealPaymentState> dealPayment(
    int dealId, {
    required bool viewerIsTraveler,
    CancelToken? cancelToken,
  }) async => DealPaymentState.fromJson(
    await _api.getObject(
      '/api/deals/$dealId/payment',
      cancelToken: cancelToken,
    ),
    viewerIsTraveler: viewerIsTraveler,
  );

  Future<List<Payout>> payouts({
    PayoutStatus? status,
    CancelToken? cancelToken,
  }) async {
    final rows = await _api.getList(
      '/api/payouts',
      query: {if (status != null) 'status': _payoutStatusWire(status)},
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => Payout.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }

  static String _purposeWire(PaymentPurpose purpose) => switch (purpose) {
    PaymentPurpose.postingDeposit => 'posting_deposit',
    PaymentPurpose.dealBalance => 'deal_balance',
    PaymentPurpose.boost => 'boost',
    PaymentPurpose.unknown => '',
  };

  static String _orderStatusWire(PaymentOrderStatus status) => switch (status) {
    PaymentOrderStatus.partiallyPaid => 'partially_paid',
    PaymentOrderStatus.refundPending => 'refund_pending',
    PaymentOrderStatus.partiallyRefunded => 'partially_refunded',
    _ => status.name,
  };

  static String _payoutStatusWire(PayoutStatus status) => switch (status) {
    PayoutStatus.notEligible => 'not_eligible',
    _ => status.name,
  };
}

// ---------------------------------------------------------------------------
// Disputes
// ---------------------------------------------------------------------------

class DisputeRepository {
  const DisputeRepository(this._api);

  final ApiClient _api;

  /// Idempotent: a party who already has an active dispute gets that one back.
  Future<Dispute> open({
    required int dealId,
    required DisputeCategory category,
    required String reasonText,
  }) async => Dispute.fromJson(
    await _api.postObject(
      '/api/deals/$dealId/disputes',
      body: {'category': category.wire, 'reason_text': reasonText},
    ),
  );

  /// Both parties see every dispute on the deal — a frozen payout is a fact
  /// about both of them.
  Future<List<Dispute>> forDeal(int dealId, {CancelToken? cancelToken}) async {
    final rows = await _api.getList(
      '/api/deals/$dealId/disputes',
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => Dispute.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }

  Future<Dispute> byId(int id, {CancelToken? cancelToken}) async =>
      Dispute.fromJson(
        await _api.getObject('/api/disputes/$id', cancelToken: cancelToken),
      );

  Future<DisputeEvidence> addText({
    required int disputeId,
    required String text,
  }) async => DisputeEvidence.fromJson(
    await _api.upload(
      '/api/disputes/$disputeId/evidence',
      form: FormData.fromMap({'kind': 'text', 'text': text}),
    ),
  );

  /// The multipart field is literally `file`.
  Future<DisputeEvidence> addFile({
    required int disputeId,
    required EvidenceKind kind,
    required String filePath,
    required String fileName,
    void Function(int sent, int total)? onProgress,
    CancelToken? cancelToken,
  }) async => DisputeEvidence.fromJson(
    await _api.upload(
      '/api/disputes/$disputeId/evidence',
      form: FormData.fromMap({
        'kind': kind.name,
        'file': await MultipartFile.fromFile(filePath, filename: fileName),
      }),
      onProgress: onProgress,
      cancelToken: cancelToken,
    ),
  );

  /// A signed URL that expires in minutes. Fetched at view time and never
  /// cached.
  Future<EvidenceLink> evidenceUrl({
    required int disputeId,
    required int evidenceId,
  }) async => EvidenceLink.fromJson(
    await _api.getObject('/api/disputes/$disputeId/evidence/$evidenceId/url'),
  );
}

// ---------------------------------------------------------------------------
// Ratings
// ---------------------------------------------------------------------------

class RatingRepository {
  const RatingRepository(this._api);

  final ApiClient _api;

  /// Role, rater and ratee are all derived server-side from the Deal — the
  /// client sends only the review itself.
  Future<Rating> submit({
    required int dealId,
    required int score,
    List<String> tags = const [],
    String comment = '',
  }) async => Rating.fromJson(
    await _api.postObject(
      '/api/deals/$dealId/ratings',
      body: {
        'score': score,
        'tags': tags,
        if (comment.isNotEmpty) 'comment': comment,
      },
    ),
  );

  Future<RatingState> forDeal(int dealId, {CancelToken? cancelToken}) async {
    final json = await _api.getObject(
      '/api/deals/$dealId/ratings',
      cancelToken: cancelToken,
    );
    return RatingState.maybe(json)!;
  }

  /// Ratings I have received, revealed ones only.
  Future<List<Rating>> received({CancelToken? cancelToken}) async {
    final rows = await _api.getList(
      '/api/users/me/ratings',
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => Rating.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

class NotificationRepository {
  const NotificationRepository(this._api);

  final ApiClient _api;

  Future<NotificationPage> page({
    int page = 1,
    bool unreadOnly = false,
    String? channel,
    CancelToken? cancelToken,
  }) async => NotificationPage.fromJson(
    await _api.getObject(
      '/api/notifications',
      query: {
        if (page > 1) 'page': page,
        if (unreadOnly) 'unread': '1',
        'channel': ?channel,
      },
      cancelToken: cancelToken,
    ),
  );

  Future<int> unreadCount({CancelToken? cancelToken}) async {
    final body = await _api.getObject(
      '/api/notifications/unread-count',
      cancelToken: cancelToken,
    );
    return (body['unread'] as num?)?.toInt() ?? 0;
  }

  Future<void> markAllRead() => _api.postVoid('/api/notifications/read-all');

  Future<void> markRead(int id) => _api.postVoid('/api/notifications/$id/read');
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

class ChatRepository {
  const ChatRepository(this._api);

  final ApiClient _api;

  /// Every thread the caller may read, including ones they can no longer write
  /// to. `can_send` on each row is the composer's gate.
  Future<List<ChatThread>> threads({CancelToken? cancelToken}) async {
    final rows = await _api.getList(
      '/api/chat/threads',
      cancelToken: cancelToken,
    );
    return rows
        .whereType<Map>()
        .map((r) => ChatThread.fromJson(Map<String, dynamic>.from(r)))
        .toList(growable: false);
  }

  /// Oldest first within a page. Reading also marks the other party's messages
  /// as read, server-side.
  Future<ChatMessagePage> messages({
    required int matchId,
    int page = 1,
    int pageSize = 50,
    CancelToken? cancelToken,
  }) async => ChatMessagePage.fromJson(
    await _api.getObject(
      '/api/matches/$matchId/chat/messages',
      query: {if (page > 1) 'page': page, 'page_size': pageSize},
      cancelToken: cancelToken,
    ),
  );

  /// A `402` here is not a generic failure: it means the deal is unfunded and
  /// the sender can act on it. The reason travels in a `reason` field, which
  /// `ApiException` lifts into `extras`.
  Future<ChatMessage> send({
    required int matchId,
    required String body,
  }) async => ChatMessage.fromJson(
    await _api.postObject(
      '/api/matches/$matchId/chat/messages',
      body: {'body': body},
    ),
  );
}

// ---------------------------------------------------------------------------
// Boosts
// ---------------------------------------------------------------------------

class BoostRepository {
  const BoostRepository(this._api);

  final ApiClient _api;

  Future<BoostCatalogue> catalogue({CancelToken? cancelToken}) async =>
      BoostCatalogue.fromJson(
        await _api.getObject('/api/boosts/packages', cancelToken: cancelToken),
      );

  Future<BoostState> forRequest(
    int requestId, {
    CancelToken? cancelToken,
  }) async => BoostState.fromJson(
    await _api.getObject(
      '/api/parcels/$requestId/boosts',
      cancelToken: cancelToken,
    ),
  );

  /// Creates the purchase and its payment order. It activates only once that
  /// order is confirmed paid — returning from a checkout page activates
  /// nothing.
  Future<BoostPurchase> purchase({
    required int requestId,
    required String packageCode,
  }) async => BoostPurchase.fromJson(
    await _api.postObject(
      '/api/parcels/$requestId/boosts',
      body: {'package_code': packageCode},
    ),
  );
}

// ---------------------------------------------------------------------------
// KYC
// ---------------------------------------------------------------------------

class KycRepository {
  const KycRepository(this._api);

  final ApiClient _api;

  /// Submits identity documents to the KYC service.
  ///
  /// A different host and a different error envelope from the rest of the API;
  /// `ApiException` already normalises the latter. [idempotencyKey] must be 32
  /// lowercase hex characters and must stay the same across retries of the
  /// same logical submission, so a retry is a no-op rather than a second
  /// review.
  ///
  /// There is no status endpoint here. After a successful submission the
  /// caller refreshes the account, whose `is_kyc_verified` is the authoritative
  /// gate.
  Future<KycSubmissionResult> submit({
    required KycDocumentType documentType,
    required String idempotencyKey,
    required ({String path, String name}) front,
    required ({String path, String name}) selfie,
    ({String path, String name})? back,
    void Function(int sent, int total)? onProgress,
    CancelToken? cancelToken,
  }) async {
    final form = FormData.fromMap({
      'document_type': documentType.wire,
      'idempotency_key': idempotencyKey,
      'front': await MultipartFile.fromFile(front.path, filename: front.name),
      'selfie': await MultipartFile.fromFile(
        selfie.path,
        filename: selfie.name,
      ),
      if (back != null)
        'back': await MultipartFile.fromFile(back.path, filename: back.name),
    });

    return KycSubmissionResult.fromJson(
      await _api.upload(
        '${AppConfig.kycBaseUrl}/kyc/submit',
        form: form,
        onProgress: onProgress,
        cancelToken: cancelToken,
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

final locationRepositoryProvider = Provider<LocationRepository>(
  (ref) => LocationRepository(ref.watch(apiClientProvider)),
);

final journeyRepositoryProvider = Provider<JourneyRepository>(
  (ref) => JourneyRepository(ref.watch(apiClientProvider)),
);

final requestRepositoryProvider = Provider<RequestRepository>(
  (ref) => RequestRepository(ref.watch(apiClientProvider)),
);

final matchingRepositoryProvider = Provider<MatchingRepository>(
  (ref) => MatchingRepository(ref.watch(apiClientProvider)),
);

final dealRepositoryProvider = Provider<DealRepository>(
  (ref) => DealRepository(ref.watch(apiClientProvider)),
);

final handoverRepositoryProvider = Provider<HandoverRepository>(
  (ref) => HandoverRepository(ref.watch(apiClientProvider)),
);

final paymentRepositoryProvider = Provider<PaymentRepository>(
  (ref) => PaymentRepository(ref.watch(apiClientProvider)),
);

final disputeRepositoryProvider = Provider<DisputeRepository>(
  (ref) => DisputeRepository(ref.watch(apiClientProvider)),
);

final ratingRepositoryProvider = Provider<RatingRepository>(
  (ref) => RatingRepository(ref.watch(apiClientProvider)),
);

final notificationRepositoryProvider = Provider<NotificationRepository>(
  (ref) => NotificationRepository(ref.watch(apiClientProvider)),
);

final chatRepositoryProvider = Provider<ChatRepository>(
  (ref) => ChatRepository(ref.watch(apiClientProvider)),
);

final boostRepositoryProvider = Provider<BoostRepository>(
  (ref) => BoostRepository(ref.watch(apiClientProvider)),
);

final kycRepositoryProvider = Provider<KycRepository>(
  (ref) => KycRepository(ref.watch(apiClientProvider)),
);
