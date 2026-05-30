import 'package:dio/dio.dart';

/// Repository for the matching API: Match list/detail + Offer counter chain.
///
/// Matches the Django endpoints under /api/matches and /api/offers.
/// All money fields are integer DZD (frozen on the Offer row at creation
/// — counters are NEW offers, they never mutate prior ones).
class MatchingFailure implements Exception {
  MatchingFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

enum MatchStatus {
  pending,
  accepted,
  inTransit,
  delivered,
  completed,
  cancelled,
  expired;

  static MatchStatus fromString(String s) {
    switch (s) {
      case 'pending':
        return MatchStatus.pending;
      case 'accepted':
        return MatchStatus.accepted;
      case 'in_transit':
        return MatchStatus.inTransit;
      case 'delivered':
        return MatchStatus.delivered;
      case 'completed':
        return MatchStatus.completed;
      case 'cancelled':
        return MatchStatus.cancelled;
      case 'expired':
        return MatchStatus.expired;
    }
    return MatchStatus.pending;
  }
}

enum OfferStatus {
  pending,
  accepted,
  declined,
  countered,
  withdrawn,
  expired;

  static OfferStatus fromString(String s) {
    switch (s) {
      case 'pending':
        return OfferStatus.pending;
      case 'accepted':
        return OfferStatus.accepted;
      case 'declined':
        return OfferStatus.declined;
      case 'countered':
        return OfferStatus.countered;
      case 'withdrawn':
        return OfferStatus.withdrawn;
      case 'expired':
        return OfferStatus.expired;
    }
    return OfferStatus.pending;
  }
}

class Offer {
  const Offer({
    required this.id,
    required this.matchId,
    required this.parentOfferId,
    required this.proposedBy, // 'sender' | 'traveler'
    required this.proposerId,
    required this.baseAmountDzd,
    required this.baseFeeDzd,
    required this.commissionDzd,
    required this.totalDzd,
    required this.status,
    required this.note,
    required this.createdAt,
  });

  factory Offer.fromJson(Map<String, dynamic> j) => Offer(
        id: j['id'] as int,
        matchId: j['match'] as int,
        parentOfferId: j['parent_offer'] as int?,
        proposedBy: j['proposed_by'] as String,
        proposerId: j['proposer_id'] as int,
        baseAmountDzd: j['base_amount_dzd'] as int,
        baseFeeDzd: j['base_fee_dzd'] as int,
        commissionDzd: j['commission_dzd'] as int,
        totalDzd: j['total_dzd'] as int,
        status: OfferStatus.fromString(j['status'] as String),
        note: (j['note'] as String?) ?? '',
        createdAt: DateTime.parse(j['created_at'] as String),
      );

  final int id;
  final int matchId;
  final int? parentOfferId;
  final String proposedBy;
  final int proposerId;
  final int baseAmountDzd;
  final int baseFeeDzd;
  final int commissionDzd;
  final int totalDzd;
  final OfferStatus status;
  final String note;
  final DateTime createdAt;
}

class MatchParcelMini {
  const MatchParcelMini({
    required this.id,
    required this.kind,
    required this.weightKg,
    required this.targetTravelerId,
    required this.originIata,
    required this.originCity,
    required this.originCountry,
    required this.destinationIata,
    required this.destinationCity,
    required this.destinationCountry,
  });

  factory MatchParcelMini.fromJson(Map<String, dynamic> j) {
    final o = Map<String, dynamic>.from(j['origin'] as Map);
    final d = Map<String, dynamic>.from(j['destination'] as Map);
    return MatchParcelMini(
      id: j['id'] as int,
      kind: j['kind'] as String,
      weightKg: j['weight_kg'] as int,
      targetTravelerId: (j['target_traveler_id'] as num?)?.toInt(),
      originIata: o['iata'] as String,
      originCity: o['city'] as String,
      originCountry: o['country'] as String,
      destinationIata: d['iata'] as String,
      destinationCity: d['city'] as String,
      destinationCountry: d['country'] as String,
    );
  }

  final int id;
  final String kind;
  final int weightKg;
  /// When non-null, the sender directed this parcel at a specific traveler
  /// (e.g. via a trip tile). Counter-offers are only allowed in this case;
  /// broadcast requests (null) accept-or-decline only.
  final int? targetTravelerId;
  final String originIata;
  final String originCity;
  final String originCountry;
  final String destinationIata;
  final String destinationCity;
  final String destinationCountry;
}

class MatchSummary {
  const MatchSummary({
    required this.id,
    required this.parcelId,
    required this.tripId,
    required this.senderId,
    required this.travelerId,
    required this.status,
    required this.parcel,
    required this.latestOffer,
    required this.acceptedOffer,
    required this.createdAt,
  });

  factory MatchSummary.fromJson(Map<String, dynamic> j) => MatchSummary(
        id: j['id'] as int,
        parcelId: j['parcel_id'] as int,
        tripId: j['trip_id'] as int,
        senderId: j['sender_id'] as int,
        travelerId: j['traveler_id'] as int,
        status: MatchStatus.fromString(j['status'] as String),
        parcel: j['parcel'] == null
            ? null
            : MatchParcelMini.fromJson(
                Map<String, dynamic>.from(j['parcel'] as Map)),
        latestOffer: j['latest_offer'] == null
            ? null
            : Offer.fromJson(Map<String, dynamic>.from(j['latest_offer'] as Map)),
        acceptedOffer: j['accepted_offer'] == null
            ? null
            : Offer.fromJson(
                Map<String, dynamic>.from(j['accepted_offer'] as Map)),
        createdAt: DateTime.parse(j['created_at'] as String),
      );

  final int id;
  final int parcelId;
  final int tripId;
  final int senderId;
  final int travelerId;
  final MatchStatus status;
  final MatchParcelMini? parcel;
  final Offer? latestOffer;
  final Offer? acceptedOffer;
  final DateTime createdAt;
}

class ChatEligibility {
  const ChatEligibility({required this.eligible, required this.reason});
  factory ChatEligibility.fromJson(Map<String, dynamic> j) => ChatEligibility(
        eligible: j['eligible'] as bool,
        reason: j['reason'] as String,
      );
  final bool eligible;
  final String reason;
}

class MatchingRepository {
  MatchingRepository(this._dio);
  final Dio _dio;

  Future<List<MatchSummary>> list({String? role, String? status}) async {
    final r = await _dio.get<dynamic>(
      '/api/matches',
      queryParameters: {
        if (role != null) 'role': role,
        if (status != null) 'status': status,
      },
    );
    if (r.statusCode == 200 && r.data is List) {
      return (r.data as List)
          .map((e) =>
              MatchSummary.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    }
    throw MatchingFailure(_msg(r) ?? 'Could not load matches.');
  }

  Future<MatchSummary> detail(int id) async {
    final r = await _dio.get<Map<String, dynamic>>('/api/matches/$id');
    if (r.statusCode == 200 && r.data != null) return MatchSummary.fromJson(r.data!);
    throw MatchingFailure(_msg(r) ?? 'Could not load match.');
  }

  Future<List<Offer>> offers(int matchId) async {
    final r = await _dio.get<dynamic>('/api/matches/$matchId/offers');
    if (r.statusCode == 200 && r.data is List) {
      return (r.data as List)
          .map((e) => Offer.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    }
    throw MatchingFailure(_msg(r) ?? 'Could not load offers.');
  }

  /// Traveler applies to carry a sender's parcel. Creates Match + first Offer.
  /// 409 if a pending Match already exists for (parcel, trip).
  Future<MatchSummary> apply({
    required int parcelId,
    required int tripId,
    int? baseAmountDzd,
    String note = '',
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/api/matches/apply',
      data: {
        'parcel_id': parcelId,
        'trip_id': tripId,
        if (baseAmountDzd != null) 'base_amount_dzd': baseAmountDzd,
        if (note.isNotEmpty) 'note': note,
      },
    );
    if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
      return MatchSummary.fromJson(r.data!);
    }
    throw MatchingFailure(_msg(r) ?? 'Could not apply to parcel.');
  }

  /// Counter the current pending offer with a new asking amount.
  /// The new offer's pricing is computed server-side; we just send the base.
  Future<Offer> counter({
    required int matchId,
    required int baseAmountDzd,
    String note = '',
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/api/matches/$matchId/offers/counter',
      data: {
        'base_amount_dzd': baseAmountDzd,
        if (note.isNotEmpty) 'note': note,
      },
    );
    if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
      return Offer.fromJson(r.data!);
    }
    throw MatchingFailure(_msg(r) ?? 'Could not counter offer.');
  }

  Future<Offer> accept(int offerId) async {
    final r = await _dio.post<Map<String, dynamic>>('/api/offers/$offerId/accept');
    if (r.statusCode == 200 && r.data != null) return Offer.fromJson(r.data!);
    throw MatchingFailure(_msg(r) ?? 'Could not accept offer.');
  }

  Future<Offer> decline(int offerId) async {
    final r = await _dio.post<Map<String, dynamic>>('/api/offers/$offerId/decline');
    if (r.statusCode == 200 && r.data != null) return Offer.fromJson(r.data!);
    throw MatchingFailure(_msg(r) ?? 'Could not decline offer.');
  }

  Future<Offer> withdraw(int offerId) async {
    final r =
        await _dio.post<Map<String, dynamic>>('/api/offers/$offerId/withdraw');
    if (r.statusCode == 200 && r.data != null) return Offer.fromJson(r.data!);
    throw MatchingFailure(_msg(r) ?? 'Could not withdraw offer.');
  }

  Future<MatchSummary> cancel(int matchId) async {
    final r =
        await _dio.post<Map<String, dynamic>>('/api/matches/$matchId/cancel');
    if (r.statusCode == 200 && r.data != null) return MatchSummary.fromJson(r.data!);
    throw MatchingFailure(_msg(r) ?? 'Could not cancel match.');
  }

  Future<ChatEligibility> chatEligibility(int matchId) async {
    final r = await _dio
        .get<Map<String, dynamic>>('/api/matches/$matchId/chat-eligibility');
    if (r.statusCode == 200 && r.data != null) {
      return ChatEligibility.fromJson(r.data!);
    }
    throw MatchingFailure(_msg(r) ?? 'Could not check chat eligibility.');
  }

  String? _msg(Response r) {
    final d = r.data;
    if (d is Map) {
      if (d['detail'] is String) return d['detail'] as String;
      for (final v in d.values) {
        if (v is List && v.isNotEmpty && v.first is String) {
          return v.first as String;
        }
        if (v is String) return v;
      }
    }
    return null;
  }
}
