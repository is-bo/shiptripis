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

  /// `wilaya` is a two-character Algerian region code and the server requires
  /// it. That is a genuine problem for the sender side of this marketplace —
  /// a sender in Paris has no wilaya — and is reported as a backend finding.
  /// Until it is relaxed, the sign-up screen has to collect one.
  Future<Account> signUp({
    required String fullName,
    required String email,
    required String password,
    required String phone,
    required String wilaya,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/sign-up',
      body: {
        'full_name': fullName.trim(),
        'email': email.trim(),
        'password': password,
        'phone': phone.trim(),
        'wilaya': wilaya,
      },
    ),
  );

  Future<Account> signInWithGoogle({
    required String idToken,
    String? phone,
    String? wilaya,
  }) async => _authenticate(
    await _api.postObject(
      '/api/auth/oauth/google',
      body: {
        'id_token': idToken,
        if (phone != null && phone.isNotEmpty) 'phone': phone,
        if (wilaya != null && wilaya.isNotEmpty) 'wilaya': wilaya,
      },
    ),
  );

  Future<Account> me() async => Account.fromJson(await _api.getObject('/api/me'));

  /// Blacklists the refresh token server-side, then clears local storage.
  ///
  /// Local clearing happens regardless of the network result: a user who taps
  /// sign out on a train must actually be signed out on the device.
  Future<void> signOut() async {
    final refresh = await _tokens.readRefresh();
    if (refresh != null) {
      try {
        await _api.postVoid('/api/auth/sign-out', body: {'refresh': refresh});
      } on ApiException {
        // Already expired, already blacklisted, or unreachable. None of these
        // should prevent the local session from ending.
      }
    }
    await _tokens.clear();
  }

  /// The server answers 202 for every address, known or not, so the UI must
  /// show the same message either way. Revealing which emails have accounts
  /// is an enumeration vector.
  Future<void> requestPasswordReset(String email) =>
      _api.postVoid('/api/auth/password/reset/request', body: {'email': email.trim()});

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
