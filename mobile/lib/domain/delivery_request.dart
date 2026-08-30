/// A sender's delivery request.
///
/// Only `schema_version == 2` exists in V1. Version 1 rows are the retired
/// airport/DZD contract and are structurally empty of V1 fields; the client
/// neither creates nor renders them as live requests.
///
/// `senderProposedReward` is the sender's **posted intent**, not a price. The
/// agreed price only exists once an Offer carries it. The two are kept
/// separate here so no screen can accidentally present an intent as a deal.
library;

import '../core/money/money.dart';
import 'json.dart';
import 'location.dart';

enum RequestStatus {
  awaitingDeposit,
  open,
  matched,
  inTransit,
  delivered,
  completed,
  cancelled,
  expired,
  unknown;

  /// Visible to travellers and open to proposals.
  bool get isDiscoverable => this == open;

  bool get isFinished =>
      this == completed || this == cancelled || this == expired;

  /// Only these two can be cancelled through the parcel endpoint; anything
  /// later belongs to the Deal cancellation workflow.
  bool get isCancellableAsRequest => this == open || this == awaitingDeposit;
}

enum ItemCategory { documents, smallBox, electronics, clothing, other, unknown }

class ParcelMedia {
  const ParcelMedia({
    required this.id,
    required this.contentType,
    required this.bytes,
  });

  factory ParcelMedia.fromJson(Map<String, dynamic> json) => ParcelMedia(
    id: readInt(json['id']) ?? 0,
    contentType: readText(json['content_type']),
    bytes: readInt(json['bytes']) ?? 0,
  );

  final int id;
  final String contentType;
  final int bytes;
}

class DeliveryRequest {
  const DeliveryRequest({
    required this.id,
    required this.senderId,
    required this.status,
    required this.schemaVersion,
    required this.title,
    required this.description,
    required this.handlingNotes,
    required this.category,
    required this.fragile,
    required this.media,
    required this.acknowledgements,
    this.targetTravelerId,
    this.pickupLocation,
    this.deliveryLocation,
    this.readyWindowStart,
    this.readyWindowEnd,
    this.deadlineAt,
    this.actualWeightKg,
    this.lengthCm,
    this.widthCm,
    this.heightCm,
    this.declaredValue,
    this.senderProposedReward,
    this.createdAt,
    this.updatedAt,
  });

  factory DeliveryRequest.fromJson(Map<String, dynamic> json) =>
      DeliveryRequest(
        id: readInt(json['id']) ?? 0,
        senderId: readInt(json['sender_id']) ?? 0,
        targetTravelerId: readInt(json['target_traveler_id']),
        status: readEnum(
          json['status'],
          RequestStatus.values,
          fallback: RequestStatus.unknown,
        ),
        schemaVersion: readInt(json['schema_version']) ?? 0,
        pickupLocation: AppLocation.maybe(json['pickup_location']),
        deliveryLocation: AppLocation.maybe(json['delivery_location']),
        readyWindowStart: readDate(json['ready_window_start']),
        readyWindowEnd: readDate(json['ready_window_end']),
        deadlineAt: readDate(json['deadline_at']),
        actualWeightKg: readDouble(json['actual_weight_kg']),
        lengthCm: readDouble(json['length_cm']),
        widthCm: readDouble(json['width_cm']),
        heightCm: readDouble(json['height_cm']),
        declaredValue: Money.eurCentsOrNull(json['declared_value_eur_cents']),
        senderProposedReward: Money.eurCentsOrNull(
          json['sender_proposed_reward_eur_cents'],
        ),
        title: readText(json['title']),
        description: readText(json['description']),
        handlingNotes: readText(json['handling_notes']),
        category: readEnum(
          json['category'],
          ItemCategory.values,
          fallback: ItemCategory.unknown,
        ),
        fragile: readBool(json['fragile']),
        media: readObjectList(
          json['media'],
        ).map(ParcelMedia.fromJson).toList(growable: false),
        acknowledgements: SafetyAcknowledgements.fromJson(json),
        createdAt: readDate(json['created_at']),
        updatedAt: readDate(json['updated_at']),
      );

  final int id;
  final int senderId;

  /// Set when the sender addressed this request to one traveller. A private
  /// request is invisible to everyone else.
  final int? targetTravelerId;

  final RequestStatus status;
  final int schemaVersion;

  /// Exact only for the sender, or for a traveller whose Deal is funded.
  /// Coarse for everyone else. Ask [AppLocation.isExact] rather than assuming.
  final AppLocation? pickupLocation;
  final AppLocation? deliveryLocation;

  final DateTime? readyWindowStart;
  final DateTime? readyWindowEnd;
  final DateTime? deadlineAt;

  final double? actualWeightKg;
  final double? lengthCm;
  final double? widthCm;
  final double? heightCm;

  final Money? declaredValue;

  /// The sender's posted intent. Never an agreed price.
  final Money? senderProposedReward;

  final String title;
  final String description;
  final String handlingNotes;
  final ItemCategory category;
  final bool fragile;
  final List<ParcelMedia> media;
  final SafetyAcknowledgements acknowledgements;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get isV1 => schemaVersion >= 2;
  bool get isTargeted => targetTravelerId != null;
  bool get hasDimensions =>
      lengthCm != null && widthCm != null && heightCm != null;

  bool get isExpired {
    final deadline = deadlineAt;
    return deadline != null && deadline.isBefore(DateTime.now());
  }
}

/// The five declarations a sender must make before a request can be published.
///
/// Recorded separately rather than as one blanket agreement because they are
/// five distinct claims about a physical object crossing a border, and a
/// dispute may turn on exactly one of them.
class SafetyAcknowledgements {
  const SafetyAcknowledgements({
    required this.descriptionIsAccurate,
    required this.itemIsLegal,
    required this.noProhibitedGoods,
    required this.declaredValueIsAccurate,
    required this.customsResponsibilitiesUnderstood,
  });

  factory SafetyAcknowledgements.fromJson(Map<String, dynamic> json) =>
      SafetyAcknowledgements(
        descriptionIsAccurate: readBool(json['description_is_accurate']),
        itemIsLegal: readBool(json['item_is_legal']),
        noProhibitedGoods: readBool(json['no_prohibited_goods']),
        declaredValueIsAccurate: readBool(json['declared_value_is_accurate']),
        customsResponsibilitiesUnderstood: readBool(
          json['customs_responsibilities_understood'],
        ),
      );

  const SafetyAcknowledgements.none()
    : descriptionIsAccurate = false,
      itemIsLegal = false,
      noProhibitedGoods = false,
      declaredValueIsAccurate = false,
      customsResponsibilitiesUnderstood = false;

  final bool descriptionIsAccurate;
  final bool itemIsLegal;
  final bool noProhibitedGoods;
  final bool declaredValueIsAccurate;
  final bool customsResponsibilitiesUnderstood;

  bool get allConfirmed =>
      descriptionIsAccurate &&
      itemIsLegal &&
      noProhibitedGoods &&
      declaredValueIsAccurate &&
      customsResponsibilitiesUnderstood;

  Map<String, dynamic> toJson() => {
    'description_is_accurate': descriptionIsAccurate,
    'item_is_legal': itemIsLegal,
    'no_prohibited_goods': noProhibitedGoods,
    'declared_value_is_accurate': declaredValueIsAccurate,
    'customs_responsibilities_understood': customsResponsibilitiesUnderstood,
  };
}
