/// Authentication endpoints.
///
/// Thin on purpose: it maps requests to responses. Storing a sign-in is
/// `SessionCore`'s job, deciding what a failure *means* is [ApiException]'s,
/// and deciding what the user sees is the screen's.
library;

import '../core/api/api_client.dart';
import '../core/api/api_exception.dart';
import '../core/api/error_codes.dart';
import '../core/session/session_core.dart';
import '../domain/account.dart';
import '../domain/communication_language.dart';

class AuthRepository {
  AuthRepository(this._api);

  final ApiClient _api;

  Future<SignIn> signIn({
    required String email,
    required String password,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/sign-in',
      body: {'email': email.trim(), 'password': password},
    ),
  );

  /// [wilaya] is retained only for older clients that still send an Algerian
  /// profile hint. New V1 signup does not collect it: delivery and Journey
  /// locations carry the country and region where they are actually needed.
  ///
  /// [preferredLanguage] is the one moment the app language and the
  /// communication language are legitimately the same decision: the account
  /// does not exist yet, so there is no stored preference to overwrite and the
  /// alternative is a first email in a language the person never chose. After
  /// this call the two settings are independent — changing the interface
  /// language never rewrites the account preference.
  Future<SignIn> signUp({
    required String fullName,
    required String email,
    required String password,
    required String phone,
    String? wilaya,
    required CommunicationLanguage preferredLanguage,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/sign-up',
      body: {
        'full_name': fullName.trim(),
        'email': email.trim(),
        'password': password,
        'phone': phone.trim(),
        if (wilaya != null && wilaya.trim().isNotEmpty) 'wilaya': wilaya.trim(),
        'preferred_language': preferredLanguage.wire,
      },
    ),
  );

  /// [preferredLanguage] is used only when the sign-in creates a fresh
  /// account; the server ignores it for an account that already exists, so a
  /// returning user keeps whatever they chose.
  Future<SignIn> signInWithGoogle({
    required String idToken,
    required CommunicationLanguage preferredLanguage,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/oauth/google',
      body: {'id_token': idToken, 'preferred_language': preferredLanguage.wire},
    ),
  );

  /// [nonce] is the raw nonce whose SHA-256 Apple put in [identityToken].
  /// [fullName] is the name Apple gave with its first authorization, or
  /// `''`; the server uses it for a new account, or one whose name is empty.
  Future<SignIn> signInWithApple({
    required String identityToken,
    required String nonce,
    required String fullName,
    required CommunicationLanguage preferredLanguage,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/oauth/apple',
      body: {
        'identity_token': identityToken,
        'nonce': nonce,
        if (fullName.isNotEmpty) 'full_name': fullName,
        'preferred_language': preferredLanguage.wire,
      },
    ),
  );

  /// The signed-in profile.
  ///
  /// Launch confirmation, a profile refresh and the sockets' token probes can
  /// all ask at once; an identical read already in flight is shared (K5).
  /// [fresh] starts a new one instead, for a caller that may be answering a
  /// live event the read in flight could predate.
  Future<Account> me({bool fresh = false}) async => Account.fromJson(
    await _api.getObject('/api/me', share: true, fresh: fresh),
  );

  /// The profile's writable fields.
  ///
  /// `PATCH /api/me` accepts `preferred_language` at any time, and
  /// `full_name` only while the account has no name (a social sign-in that
  /// gave none); otherwise it answers `name_already_set`. Its answer is not
  /// shown: the account's one owner reads `/api/me` again after it (rule S-6).
  Future<void> updateProfile({
    CommunicationLanguage? preferredLanguage,
    String? fullName,
  }) => _api.patchObject(
    '/api/me',
    body: {
      if (preferredLanguage != null)
        'preferred_language': preferredLanguage.wire,
      if (fullName != null) 'full_name': fullName.trim(),
    },
  );

  /// What stands before deleting the account.
  Future<AccountDeletionCheck> deletionCheck() async =>
      AccountDeletionCheck.fromJson(await _api.getObject('/api/me/deletion'));

  /// Deletes the account. The server ends every session; the caller then
  /// ends this phone's sign-in (`EndReason.deleted`).
  Future<void> deleteAccount({
    String? password,
    String? appleAuthorizationCode,
  }) => _api.postVoid(
    '/api/me/deletion',
    body: {
      'password': ?password,
      'apple_authorization_code': ?appleAuthorizationCode,
    },
  );

  /// The server answers 202 for every address, known or not, so the UI must
  /// show the same message either way. Revealing which emails have accounts
  /// is an enumeration vector.
  Future<void> requestPasswordReset(String email) => _api.postVoid(
    '/api/auth/password/reset/request',
    body: {'email': email.trim()},
  );

  Future<void> confirmPasswordReset({
    required String email,
    required String code,
    required String newPassword,
  }) => _api.postVoid(
    '/api/auth/password/reset/confirm',
    body: {
      'email': email.trim(),
      'code': code.trim(),
      'new_password': newPassword,
    },
  );

  /// Idempotent: the server also answers 204 when the address is already
  /// verified, so a user who taps a link twice sees success, not an error.
  Future<void> verifyEmail({required String email, required String code}) =>
      _api.postVoid(
        '/api/auth/verify-email',
        body: {'email': email.trim(), 'code': code.trim()},
      );

  /// Signed in. The server always answers 204 and sends nothing to an
  /// already-verified account. Only the newest email's code works.
  Future<void> resendVerifyEmail() =>
      _api.postVoid('/api/auth/verify-email/resend');

  /// The sign-in the server issued. Keyed by the `sid` claim its tokens
  /// carry, so two sign-ins of one account are two sign-ins.
  SignIn _authenticate(Json body) {
    final access = body['access'];
    final refresh = body['refresh'];
    final user = body['user'];
    final sid = refresh is String ? SessionCore.sidOf(refresh) : null;
    if (access is! String ||
        refresh is! String ||
        user is! Map ||
        sid == null) {
      throw ApiException(
        kind: ApiFailureKind.malformed,
        code: ApiErrorCode.unknown,
        serverDetail: 'Authentication response was missing tokens or user.',
      );
    }
    return SignIn(
      sid: sid,
      account: Account.fromJson(Map<String, dynamic>.from(user)),
      access: access,
      refresh: refresh,
    );
  }
}
