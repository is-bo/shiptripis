/// Identity verification.
///
/// KYC does not live in the main API. It is a separate Go service reached
/// through the gateway at `/kyc/submit`, with its own error envelope
/// (`{"error": "..."}` rather than `{"code", "detail"}`) and its own size and
/// content-type limits. `core/api/api_exception.dart` already normalises that
/// shape, so screens see the same failure model as everywhere else.
///
/// Two consequences the UI has to be honest about:
///
/// * **There is no status endpoint on the KYC service.** Status is read from
///   the account (`GET /api/me` → `is_kyc_verified` / `kyc_status`). After a
///   submission the app refreshes the account rather than polling KYC.
///
/// * **`unverified` is ambiguous.** The account collapses "never submitted"
///   and "expired, resubmit" into the same value. The copy therefore says what
///   to do next rather than asserting which of the two happened.
library;

import 'json.dart';

enum KycDocumentType {
  idCard,
  passport,
  drivingLicense;

  String get wire => switch (this) {
    KycDocumentType.idCard => 'id_card',
    KycDocumentType.passport => 'passport',
    KycDocumentType.drivingLicense => 'driving_license',
  };

  /// A passport is a single page; the other two have a reverse side.
  bool get requiresBackImage => this != KycDocumentType.passport;
}

/// The submission's own status, as returned by the KYC service.
enum KycSubmissionStatus { pending, approved, rejected, expired, unknown }

class KycSubmissionResult {
  const KycSubmissionResult({
    required this.submissionId,
    required this.status,
    required this.created,
  });

  factory KycSubmissionResult.fromJson(Map<String, dynamic> json) =>
      KycSubmissionResult(
        submissionId: readInt(json['submission_id']) ?? 0,
        status: readEnum(
          json['status'],
          KycSubmissionStatus.values,
          fallback: KycSubmissionStatus.unknown,
        ),
        created: readBool(json['created']),
      );

  final int submissionId;
  final KycSubmissionStatus status;

  /// False when the idempotency key matched an existing submission — a retry,
  /// not a second attempt. The UI treats both as success.
  final bool created;
}

/// The limits the KYC service enforces.
///
/// Duplicated here only so the picker can reject an oversized file before
/// spending the user's data on an upload that will be refused. The server
/// remains the authority; a local pass never implies a server pass.
abstract final class KycLimits {
  static const maxImageBytes = 8 * 1024 * 1024;
  static const maxRequestBytes = 25 * 1024 * 1024;

  /// WebP is accepted for dispute evidence but **not** for KYC.
  static const allowedContentTypes = ['image/jpeg', 'image/png'];
}
