/// Disputes and their evidence.
///
/// A dispute is openable from pickup confirmation until the protection window
/// closes, and while one is active the traveller's payout is frozen. Both
/// facts are server state; the client shows them and never infers them.
///
/// Evidence files are uploaded to the platform and read back through a
/// short-lived signed URL — five minutes by default. The client therefore
/// fetches a URL at the moment of viewing and never caches one.
library;

import '../core/money/money.dart';
import 'json.dart';

enum DisputeStatus {
  open,
  awaitingEvidence,
  underReview,
  resolved,
  closed,
  unknown;

  bool get isActive =>
      this == open || this == awaitingEvidence || this == underReview;
}

enum DisputeCategory {
  notDelivered,
  damaged,
  wrongItem,
  late,
  noShow,
  payment,
  other,
  unknown;

  /// The value the API expects back.
  String get wire => switch (this) {
    DisputeCategory.notDelivered => 'not_delivered',
    DisputeCategory.damaged => 'damaged',
    DisputeCategory.wrongItem => 'wrong_item',
    DisputeCategory.late => 'late',
    DisputeCategory.noShow => 'no_show',
    DisputeCategory.payment => 'payment',
    DisputeCategory.other => 'other',
    DisputeCategory.unknown => '',
  };

  /// The categories a party may choose. `unknown` is a parse fallback, not an
  /// option, and `noShow`/`payment` remain selectable because both are real
  /// party-reported failures.
  static const selectable = [
    notDelivered,
    damaged,
    wrongItem,
    late,
    noShow,
    payment,
    other,
  ];
}

enum DisputeResolution {
  fullSenderRefund,
  fullTravelerPayout,
  partialSplit,
  unknown,
}

enum EvidenceKind { text, photo, video, unknown }

/// The dispute block nested on a Deal — enough to decide what to show and
/// where to link, without the full record.
class DisputeSummary {
  const DisputeSummary({
    required this.id,
    required this.status,
    required this.category,
    required this.isActive,
    this.publicReference,
    this.openedAt,
    this.openedByRole,
    this.resolution = DisputeResolution.unknown,
    this.resolvedAt,
  });

  static DisputeSummary? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return DisputeSummary(
      id: readInt(json['id']) ?? 0,
      publicReference: readString(json['public_reference']),
      status: readEnum(
        json['status'],
        DisputeStatus.values,
        fallback: DisputeStatus.unknown,
      ),
      category: readEnum(
        json['category'],
        DisputeCategory.values,
        fallback: DisputeCategory.unknown,
      ),
      openedAt: readDate(json['opened_at']),
      openedByRole: readString(json['opened_by_role']),
      isActive: readBool(json['is_active']),
      resolution: readEnum(
        json['resolution'],
        DisputeResolution.values,
        fallback: DisputeResolution.unknown,
      ),
      resolvedAt: readDate(json['resolved_at']),
    );
  }

  final int id;
  final String? publicReference;
  final DisputeStatus status;
  final DisputeCategory category;
  final DateTime? openedAt;
  final String? openedByRole;

  /// Server-computed. While true, the payout is frozen.
  final bool isActive;

  final DisputeResolution resolution;
  final DateTime? resolvedAt;
}

class DisputeEvidence {
  const DisputeEvidence({
    required this.id,
    required this.disputeId,
    required this.kind,
    required this.hasFile,
    this.submittedById,
    this.text,
    this.contentType,
    this.sizeBytes,
    this.createdAt,
  });

  factory DisputeEvidence.fromJson(Map<String, dynamic> json) =>
      DisputeEvidence(
        id: readInt(json['id']) ?? 0,
        disputeId: readInt(json['dispute_id']) ?? 0,
        submittedById: readInt(json['submitted_by_id']),
        kind: readEnum(
          json['kind'],
          EvidenceKind.values,
          fallback: EvidenceKind.unknown,
        ),
        text: readString(json['text']),
        contentType: readString(json['content_type']),
        sizeBytes: readInt(json['size_bytes']),
        hasFile: readBool(json['has_file']),
        createdAt: readDate(json['created_at']),
      );

  final int id;
  final int disputeId;
  final int? submittedById;
  final EvidenceKind kind;
  final String? text;
  final String? contentType;
  final int? sizeBytes;

  /// The storage key is never serialised. This flag is how a screen knows to
  /// offer "view" rather than rendering a broken image.
  final bool hasFile;

  final DateTime? createdAt;

  bool get isVideo => kind == EvidenceKind.video;
  bool get isImage => kind == EvidenceKind.photo;
}

/// A short-lived signed URL for one piece of evidence.
///
/// Expires in minutes. Fetched at view time and never stored.
class EvidenceLink {
  const EvidenceLink({required this.url, required this.kind, this.contentType});

  factory EvidenceLink.fromJson(Map<String, dynamic> json) => EvidenceLink(
    url: readText(json['url']),
    kind: readEnum(
      json['kind'],
      EvidenceKind.values,
      fallback: EvidenceKind.unknown,
    ),
    contentType: readString(json['content_type']),
  );

  final String url;
  final EvidenceKind kind;
  final String? contentType;

  @override
  String toString() => 'EvidenceLink(${kind.name}, url redacted)';
}

class DisputeEvent {
  const DisputeEvent({
    required this.id,
    required this.kind,
    required this.payload,
    this.actorId,
    this.createdAt,
  });

  factory DisputeEvent.fromJson(Map<String, dynamic> json) => DisputeEvent(
    id: readInt(json['id']) ?? 0,
    kind: readText(json['kind']),
    actorId: readInt(json['actor_id']),
    payload: readObject(json['payload']) ?? const {},
    createdAt: readDate(json['created_at']),
  );

  final int id;

  /// `opened`, `status_changed`, `evidence_added`, `resolved`, `closed`,
  /// `payout_frozen`, `note`.
  final String kind;

  final int? actorId;

  /// Allowlist-filtered for a party. Staff notes never reach here.
  final Map<String, dynamic> payload;

  final DateTime? createdAt;
}

class Dispute {
  const Dispute({
    required this.id,
    required this.dealId,
    required this.status,
    required this.category,
    required this.reasonText,
    required this.payoutFrozen,
    required this.payoutAlreadySettled,
    required this.evidence,
    required this.events,
    this.publicReference,
    this.dealStatusRaw,
    this.openedById,
    this.openedByRole,
    this.openedAt,
    this.protectionEndsAt,
    this.resolution = DisputeResolution.unknown,
    this.senderRefund,
    this.travelerPayout,
    this.platformFee,
    this.collectedTotal,
    this.resolutionNote,
    this.resolvedAt,
    this.closedAt,
  });

  factory Dispute.fromJson(Map<String, dynamic> json) => Dispute(
    id: readInt(json['id']) ?? 0,
    publicReference: readString(json['public_reference']),
    dealId: readInt(json['deal_id']) ?? 0,
    dealStatusRaw: readString(json['deal_status']),
    status: readEnum(
      json['status'],
      DisputeStatus.values,
      fallback: DisputeStatus.unknown,
    ),
    category: readEnum(
      json['category'],
      DisputeCategory.values,
      fallback: DisputeCategory.unknown,
    ),
    reasonText: readText(json['reason_text']),
    openedById: readInt(json['opened_by_id']),
    openedByRole: readString(json['opened_by_role']),
    openedAt: readDate(json['opened_at']),
    protectionEndsAt: readDate(json['protection_ends_at']),
    resolution: readEnum(
      json['resolution'],
      DisputeResolution.values,
      fallback: DisputeResolution.unknown,
    ),
    senderRefund: Money.eurCentsOrNull(json['sender_refund_eur_cents']),
    travelerPayout: Money.eurCentsOrNull(json['traveler_payout_eur_cents']),
    platformFee: Money.eurCentsOrNull(json['platform_fee_eur_cents']),
    collectedTotal: Money.eurCentsOrNull(json['collected_total_eur_cents']),
    resolutionNote: readString(json['resolution_note']),
    resolvedAt: readDate(json['resolved_at']),
    closedAt: readDate(json['closed_at']),
    payoutFrozen: readBool(json['payout_frozen']),
    payoutAlreadySettled: readBool(json['payout_already_settled']),
    evidence: readObjectList(
      json['evidence'],
    ).map(DisputeEvidence.fromJson).toList(growable: false),
    events: readObjectList(
      json['events'],
    ).map(DisputeEvent.fromJson).toList(growable: false),
  );

  final int id;
  final String? publicReference;
  final int dealId;
  final String? dealStatusRaw;
  final DisputeStatus status;
  final DisputeCategory category;
  final String reasonText;
  final int? openedById;
  final String? openedByRole;
  final DateTime? openedAt;
  final DateTime? protectionEndsAt;

  final DisputeResolution resolution;

  /// The settlement amounts, once the platform has decided. Displayed
  /// verbatim; the split is never computed here.
  final Money? senderRefund;
  final Money? travelerPayout;
  final Money? platformFee;
  final Money? collectedTotal;

  final String? resolutionNote;
  final DateTime? resolvedAt;
  final DateTime? closedAt;

  /// The traveller's money is held while this is true.
  final bool payoutFrozen;

  final bool payoutAlreadySettled;
  final List<DisputeEvidence> evidence;
  final List<DisputeEvent> events;

  bool get isActive => status.isActive;
  bool get canAddEvidence => status.isActive;
  bool get hasResolution => resolution != DisputeResolution.unknown;

  bool openedByViewer(int viewerId) => openedById == viewerId;
}

/// The evidence limits the server currently enforces, surfaced in refusals.
///
/// Read from the error envelope rather than hard-coded, because they are
/// policy and can change between releases.
class EvidenceLimits {
  const EvidenceLimits({this.maxBytes, this.allowedContentTypes = const []});

  final int? maxBytes;
  final List<String> allowedContentTypes;
}
