/// Authentication endpoints.
///
/// Thin on purpose: it maps requests to responses and stores tokens. Deciding
/// what a failure *means* is [ApiException]'s job, and deciding what the user
/// sees is the screen's.
library;

import '../core/api/api_client.dart';
import '../core/api/api_exception.dart';
import '../core/api/error_codes.dart';
import '../core/session/token_store.dart';
import '../domain/account.dart';
import '../domain/communication_language.dart';

class AuthRepository {
  AuthRepository(this._api, this._tokens);

  final ApiClient _api;
  final TokenStore _tokens;

  Future<Account> signIn({
    required String email,
    required String password,
    int? expectedIdentityGeneration,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/sign-in',
      body: {'email': email.trim(), 'password': password},
    ),
    expectedIdentityGeneration: expectedIdentityGeneration,
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
  Future<Account> signUp({
    required String fullName,
    required String email,
    required String password,
    required String phone,
    String? wilaya,
    required CommunicationLanguage preferredLanguage,
    int? expectedIdentityGeneration,
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
    expectedIdentityGeneration: expectedIdentityGeneration,
  );

  /// [preferredLanguage] is used only when the sign-in creates a fresh
  /// account; the server ignores it for an account that already exists, so a
  /// returning user keeps whatever they chose.
  Future<Account> signInWithGoogle({
    required String idToken,
    required CommunicationLanguage preferredLanguage,
    int? expectedIdentityGeneration,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/oauth/google',
      body: {'id_token': idToken, 'preferred_language': preferredLanguage.wire},
    ),
    expectedIdentityGeneration: expectedIdentityGeneration,
  );

  /// [nonce] is the raw nonce whose SHA-256 Apple put in [identityToken].
  /// [fullName] is the name Apple gave with its first authorization, or
  /// `''`; the server uses it for a new account, or one whose name is empty.
  Future<Account> signInWithApple({
    required String identityToken,
    required String nonce,
    required String fullName,
    required CommunicationLanguage preferredLanguage,
    int? expectedIdentityGeneration,
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
    expectedIdentityGeneration: expectedIdentityGeneration,
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
  /// gave none); otherwise it answers `name_already_set`. It answers with the
  /// whole profile, so the caller replaces its `Account` from the response
  /// rather than patching a local copy and hoping the two agree.
  Future<Account> updateProfile({
    CommunicationLanguage? preferredLanguage,
    String? fullName,
  }) async => Account.fromJson(
    await _api.patchObject(
      '/api/me',
      body: {
        if (preferredLanguage != null)
          'preferred_language': preferredLanguage.wire,
        if (fullName != null) 'full_name': fullName.trim(),
      },
    ),
  );

  /// Blacklists the refresh token server-side, then clears local storage.
  ///
  /// Local clearing happens regardless of the network result: a user who taps
  /// sign out on a train must actually be signed out on the device.
  Future<void> signOut() async {
    final signOutIdentity = _tokens.invalidateIdentity();
    final refresh = await _tokens.readRefresh();
    if (_tokens.identityGeneration != signOutIdentity) return;
    if (refresh != null) {
      try {
        final installationId = await _tokens.readOrCreateInstallationId();
        if (_tokens.identityGeneration != signOutIdentity) return;
        await _api.postVoid(
          '/api/auth/sign-out',
          body: {'refresh': refresh, 'installation_id': installationId},
        );
      } on Object {
        // Push cleanup is best-effort. An expired session, unreachable API,
        // or unavailable keystore must not prevent local sign-out.
      }
    }
    await _tokens.clearIfIdentityCurrent(signOutIdentity);
  }

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

  Future<Account> _authenticate(
    Json body, {
    int? expectedIdentityGeneration,
  }) async {
    final access = body['access'];
    final refresh = body['refresh'];
    final user = body['user'];

    if (access is! String || refresh is! String || user is! Map) {
      throw ApiException(
        kind: ApiFailureKind.malformed,
        code: ApiErrorCode.unknown,
        serverDetail: 'Authentication response was missing tokens or user.',
      );
    }

    final identity = expectedIdentityGeneration ?? _tokens.invalidateIdentity();
    final saved = await _tokens.saveAuthenticationIfCurrent(
      expectedIdentityGeneration: identity,
      access: access,
      refresh: refresh,
    );
    if (!saved) {
      throw StateError('The authenticated session changed.');
    }
    return Account.fromJson(Map<String, dynamic>.from(user));
  }
}
