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
  Future<Account> signUp({
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

  /// [preferredLanguage] is used only when Google creates a fresh account; the
  /// server ignores it for an account that already exists, so a returning user
  /// keeps whatever they chose.
  Future<Account> signInWithGoogle({
    required String idToken,
    String? phone,
    String? wilaya,
    CommunicationLanguage? preferredLanguage,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/oauth/google',
      body: {
        'id_token': idToken,
        if (phone != null && phone.isNotEmpty) 'phone': phone,
        if (wilaya != null && wilaya.isNotEmpty) 'wilaya': wilaya,
        if (preferredLanguage != null)
          'preferred_language': preferredLanguage.wire,
      },
    ),
  );

  Future<Account> me() async =>
      Account.fromJson(await _api.getObject('/api/me'));

  /// The one writable field on the profile contract.
  ///
  /// `PATCH /api/me` accepts `preferred_language` and nothing else, and answers
  /// with the whole profile — so the caller replaces its `Account` from the
  /// response rather than patching a local copy and hoping the two agree.
  Future<Account> updatePreferredLanguage(
    CommunicationLanguage language,
  ) async => Account.fromJson(
    await _api.patchObject(
      '/api/me',
      body: {'preferred_language': language.wire},
    ),
  );

  /// Blacklists the refresh token server-side, then clears local storage.
  ///
  /// Local clearing happens regardless of the network result: a user who taps
  /// sign out on a train must actually be signed out on the device.
  Future<void> signOut() async {
    final refresh = await _tokens.readRefresh();
    if (refresh != null) {
      try {
        final installationId = await _tokens.readOrCreateInstallationId();
        await _api.postVoid(
          '/api/auth/sign-out',
          body: {'refresh': refresh, 'installation_id': installationId},
        );
      } on Object {
        // Push cleanup is best-effort. An expired session, unreachable API,
        // or unavailable keystore must not prevent local sign-out.
      }
    }
    await _tokens.clear();
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

  Future<Account> _authenticate(Json body) async {
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

    await _tokens.save(access: access, refresh: refresh);
    return Account.fromJson(Map<String, dynamic>.from(user));
  }
}
