/// The signed-in account, as `GET /api/me` describes it.
library;

import 'package:characters/characters.dart';

import 'communication_language.dart';
import 'json.dart';

/// What the account is permitted to do, per the server.
///
/// This is authority, not preference. A user who is `sender` cannot be shown
/// traveller actions no matter what they last tapped. `both` is the signup
/// default, and is the only value for which the in-app role switch does
/// anything.
enum AccountRole {
  sender,
  traveler,
  both,
  admin,
  unknown;

  static AccountRole parse(Object? raw) => switch (raw) {
    'sender' => AccountRole.sender,
    'traveler' => AccountRole.traveler,
    'both' => AccountRole.both,
    'admin' => AccountRole.admin,
    // A role this build has never heard of must not lock the user out of the
    // app. Treat it as the least-privileged useful value and let the server
    // refuse anything it should not allow.
    _ => AccountRole.unknown,
  };

  bool get canSend => this == sender || this == both || this == admin;
  bool get canTravel => this == traveler || this == both || this == admin;
  bool get canSwitch => canSend && canTravel;
}

/// Display-only KYC state. [Account.isKycVerified] remains the sole authority
/// for whether the account may actually transact — the server's own
/// serializer says so, and a client that trusted the display string would let
/// a user start a journey they cannot publish.
enum KycStatus {
  verified,
  pending,
  rejected,
  unverified,
  unknown;

  static KycStatus parse(Object? raw) => switch (raw) {
    'verified' => KycStatus.verified,
    'pending' => KycStatus.pending,
    'rejected' => KycStatus.rejected,
    'unverified' => KycStatus.unverified,
    _ => KycStatus.unknown,
  };
}

class Account {
  const Account({
    required this.id,
    required this.email,
    required this.fullName,
    required this.phone,
    required this.wilaya,
    required this.role,
    required this.preferredLanguage,
    required this.isEmailVerified,
    required this.isPhoneVerified,
    required this.isKycVerified,
    required this.kycStatus,
    this.kycRejectionReason,
    this.dateJoined,
  });

  factory Account.fromJson(Map<String, dynamic> json) => Account(
    id: readInt(json['id']) ?? 0,
    email: readString(json['email']) ?? '',
    fullName: readString(json['full_name']) ?? '',
    phone: readString(json['phone']) ?? '',
    wilaya: readString(json['wilaya']) ?? '',
    role: AccountRole.parse(json['role']),
    // The server already normalises this, including for accounts created
    // before the preference existed. Parsing defensively anyway costs
    // nothing and keeps the selector out of an impossible state if an older
    // deployment omits the key entirely.
    preferredLanguage: CommunicationLanguage.parse(json['preferred_language']),
    isEmailVerified: readBool(json['is_email_verified']),
    isPhoneVerified: readBool(json['is_phone_verified']),
    isKycVerified: readBool(json['is_kyc_verified']),
    kycStatus: KycStatus.parse(json['kyc_status']),
    kycRejectionReason: readString(json['kyc_rejection_reason']),
    dateJoined: readDate(json['date_joined']),
  );

  /// The profile as [Account.fromJson] reads it, for the local launch
  /// snapshot (K5). Exactly the keys parsed above and nothing else: no tokens,
  /// no payout data, no KYC evidence. It is display state for the first
  /// frames of a launch; `/api/me` replaces it as soon as the server answers.
  Map<String, Object?> toSnapshotJson() => {
    'id': id,
    'email': email,
    'full_name': fullName,
    'phone': phone,
    'wilaya': wilaya,
    'role': role.name,
    'preferred_language': preferredLanguage.wire,
    'is_email_verified': isEmailVerified,
    'is_phone_verified': isPhoneVerified,
    'is_kyc_verified': isKycVerified,
    'kyc_status': kycStatus.name,
    'kyc_rejection_reason': kycRejectionReason,
    'date_joined': dateJoined?.toUtc().toIso8601String(),
  };

  final int id;
  final String email;
  final String fullName;
  final String phone;
  final String wilaya;
  final AccountRole role;

  /// The language ShipTrip writes to this account in. Distinct from the app's
  /// interface language, which is a device setting and never leaves the phone.
  final CommunicationLanguage preferredLanguage;

  final bool isEmailVerified;
  final bool isPhoneVerified;

  /// The authority for "may publish a journey / may carry".
  final bool isKycVerified;

  /// For display. See [KycStatus].
  final KycStatus kycStatus;

  /// Present only when the latest submission was rejected. May be an empty
  /// string, which means "rejected, reason not given" — render the generic
  /// copy in that case rather than an empty line.
  final String? kycRejectionReason;

  final DateTime? dateJoined;

  /// Initials for the avatar. Falls back to the email so a user who signed up
  /// through Google without a name still gets something recognisable rather
  /// than a question mark.
  String get initials {
    final parts = fullName
        .trim()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty)
        .toList();
    if (parts.isEmpty) {
      return email.isEmpty ? '?' : email.characters.first.toUpperCase();
    }
    if (parts.length == 1) return parts.first.characters.first.toUpperCase();
    return (parts.first.characters.first + parts.last.characters.first)
        .toUpperCase();
  }
}

/// What stands before deleting an account, as the server reads it.
enum AccountDeletionBlocker {
  openDeliveries,
  openDisputes,
  pendingPayouts,
  pendingRefunds,
  openRequests,
  activeJourneys,
  unknown;

  static AccountDeletionBlocker parse(Object? raw) => readEnum(
    raw,
    AccountDeletionBlocker.values,
    fallback: AccountDeletionBlocker.unknown,
  );
}

/// `GET /api/me/deletion`: whether the account can be deleted now, and what
/// the confirmation needs.
class AccountDeletionCheck {
  const AccountDeletionCheck({
    required this.blockers,
    required this.passwordRequired,
    required this.appleAuthorizationRequired,
  });

  factory AccountDeletionCheck.fromJson(Map<String, dynamic> json) =>
      AccountDeletionCheck(
        blockers: [
          for (final raw in (json['blockers'] as List? ?? const []))
            AccountDeletionBlocker.parse(raw),
        ],
        passwordRequired: readBool(json['password_required']),
        appleAuthorizationRequired: readBool(
          json['apple_authorization_required'],
        ),
      );

  /// In the order to show them. Empty when nothing stands in the way.
  final List<AccountDeletionBlocker> blockers;
  final bool passwordRequired;

  /// The account signs in with Apple, so deleting it asks Apple first.
  final bool appleAuthorizationRequired;

  bool get canDelete => blockers.isEmpty;
}
