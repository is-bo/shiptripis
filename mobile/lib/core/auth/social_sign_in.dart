/// Sign in with Google and Sign in with Apple.
///
/// Two layers. [SocialSignIn] talks to the provider on the phone and answers
/// a credential, `null` when the person cancelled, or a
/// [SocialSignInFailure]; tests replace it through [socialSignInProvider],
/// so no test ever reaches a provider. [SocialAuth] takes that credential to
/// the server, which verifies it and decides everything: the app only carries
/// it.
///
/// Neither provider is offered until it is configured for the platform
/// (decision 15 of the plan): Google needs its server client id, and on iOS
/// its iOS client id too; Apple needs `APPLE_SIGN_IN_ENABLED` on an iOS
/// build, and is never offered elsewhere. On iOS Google is offered only
/// together with Apple (App Store 4.8): a build with Google configured and
/// Apple off offers neither.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:characters/characters.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart';

import '../../domain/communication_language.dart';
import '../api/api_exception.dart';
import '../env/app_config.dart';
import '../session/session.dart';
import '../time/clock.dart';

enum SocialProvider { google, apple }

/// What Google gives the app: an ID token for the server to verify.
@immutable
class GoogleCredential {
  const GoogleCredential({required this.idToken});

  final String idToken;
}

/// What Apple gives the app.
@immutable
class AppleCredential {
  const AppleCredential({
    required this.identityToken,
    required this.rawNonce,
    required this.fullName,
    required this.userIdentifier,
  });

  final String identityToken;

  /// The nonce before hashing. Apple was given its SHA-256 ([appleNonceHash])
  /// and wrote that into the token; the server hashes this one to compare.
  final String rawNonce;

  /// The person's name, or `''`. Apple gives it on the first authorization
  /// only, and never inside the token.
  final String fullName;

  /// Apple's stable id for the person, used only to tell whether a name kept
  /// from an earlier authorization is theirs.
  final String? userIdentifier;

  AppleCredential withFullName(String name) => AppleCredential(
    identityToken: identityToken,
    rawNonce: rawNonce,
    fullName: name,
    userIdentifier: userIdentifier,
  );
}

/// The provider could not give a credential (misconfigured, no UI, a
/// platform error). Cancelling is not a failure: it answers `null`.
class SocialSignInFailure implements Exception {
  const SocialSignInFailure(this.provider, this.cause);

  final SocialProvider provider;
  final Object cause;

  @override
  String toString() => 'SocialSignInFailure(${provider.name}, $cause)';
}

abstract interface class SocialSignIn {
  /// Whether this build offers Continue with Google.
  bool get offersGoogle;

  /// Whether this build offers Continue with Apple.
  bool get offersApple;

  Future<GoogleCredential?> google();

  Future<AppleCredential?> apple();

  /// A fresh Apple authorization code, asked for when the person deletes an
  /// account that uses Sign in with Apple, so the server can revoke it.
  /// `null` when the person cancelled.
  Future<String?> appleAuthorizationCode();

  /// Forgets the provider's own signed-in account, so the next person on a
  /// shared phone is offered the account picker. Best effort: never throws.
  Future<void> signOut();
}

/// Which providers a build offers on [platform], given its configuration.
({bool google, bool apple}) socialSignInOffers({
  required TargetPlatform platform,
  required bool isWeb,
  required String googleServerClientId,
  required String googleIosClientId,
  required bool appleSignInEnabled,
}) {
  if (isWeb) return (google: false, apple: false);
  return switch (platform) {
    TargetPlatform.android => (
      google: googleServerClientId.isNotEmpty,
      apple: false,
    ),
    TargetPlatform.iOS => (
      google:
          appleSignInEnabled &&
          googleServerClientId.isNotEmpty &&
          googleIosClientId.isNotEmpty,
      apple: appleSignInEnabled,
    ),
    _ => (google: false, apple: false),
  };
}

/// A fresh nonce for one Apple authorization: 32 random bytes, base64url.
String newAppleNonce([Random? random]) {
  final source = random ?? Random.secure();
  final bytes = List<int>.generate(32, (_) => source.nextInt(256));
  return base64Url.encode(bytes).replaceAll('=', '');
}

/// What Apple is given for [rawNonce]: its SHA-256, in hex.
String appleNonceHash(String rawNonce) =>
    sha256.convert(utf8.encode(rawNonce)).toString();

/// The longest name the server takes.
const maxFullNameLength = 120;

/// Apple's name parts as one name the server accepts: joined, trimmed, and
/// cut to [maxFullNameLength] code points without splitting a character.
String joinAppleName(String? givenName, String? familyName) {
  final joined = [givenName, familyName]
      .map((part) => part?.trim() ?? '')
      .where((part) => part.isNotEmpty)
      .join(' ');
  if (joined.runes.length <= maxFullNameLength) return joined;
  final kept = StringBuffer();
  for (final character in joined.characters) {
    if ((kept.toString() + character).runes.length > maxFullNameLength) break;
    kept.write(character);
  }
  return kept.toString().trim();
}

/// Asks Apple for a credential carrying [hashedNonce].
typedef AppleAuthorize =
    Future<AuthorizationCredentialAppleID> Function(String hashedNonce);

Future<AuthorizationCredentialAppleID> _authorizeWithApple(
  String hashedNonce,
) => SignInWithApple.getAppleIDCredential(
  scopes: const [
    AppleIDAuthorizationScopes.email,
    AppleIDAuthorizationScopes.fullName,
  ],
  nonce: hashedNonce,
);

/// Asks Apple for an authorization with no name or email: only its code.
typedef AppleReauthorize = Future<AuthorizationCredentialAppleID> Function();

Future<AuthorizationCredentialAppleID> _reauthorizeWithApple() =>
    SignInWithApple.getAppleIDCredential(scopes: const []);

/// The real providers.
class PlatformSocialSignIn implements SocialSignIn {
  PlatformSocialSignIn({
    AppleAuthorize authorizeApple = _authorizeWithApple,
    AppleReauthorize reauthorizeApple = _reauthorizeWithApple,
  }) : _authorizeApple = authorizeApple,
       _reauthorizeApple = reauthorizeApple;

  final AppleAuthorize _authorizeApple;
  final AppleReauthorize _reauthorizeApple;
  Future<void>? _googleReady;

  static final _offers = socialSignInOffers(
    platform: defaultTargetPlatform,
    isWeb: kIsWeb,
    googleServerClientId: AppConfig.googleServerClientId,
    googleIosClientId: AppConfig.googleIosClientId,
    appleSignInEnabled: AppConfig.appleSignInEnabled,
  );

  @override
  bool get offersGoogle => _offers.google;

  @override
  bool get offersApple => _offers.apple;

  @override
  Future<GoogleCredential?> google() async {
    await _initializeGoogle();
    try {
      final account = await GoogleSignIn.instance.authenticate();
      final idToken = account.authentication.idToken;
      if (idToken == null || idToken.isEmpty) {
        throw const SocialSignInFailure(SocialProvider.google, 'no id token');
      }
      return GoogleCredential(idToken: idToken);
    } on GoogleSignInException catch (error) {
      if (error.code == GoogleSignInExceptionCode.canceled ||
          error.code == GoogleSignInExceptionCode.interrupted) {
        return null;
      }
      throw SocialSignInFailure(SocialProvider.google, error.code);
    } on SocialSignInFailure {
      rethrow;
    } on Object catch (error) {
      throw SocialSignInFailure(SocialProvider.google, error);
    }
  }

  /// `initialize` is called once per process. Only a failed one is tried
  /// again, at the next tap.
  Future<void> _initializeGoogle() async {
    final ready = _googleReady ??= GoogleSignIn.instance.initialize(
      clientId: defaultTargetPlatform == TargetPlatform.iOS
          ? AppConfig.googleIosClientId
          : null,
      serverClientId: AppConfig.googleServerClientId,
    );
    try {
      await ready;
    } on Object catch (error) {
      if (identical(_googleReady, ready)) _googleReady = null;
      throw SocialSignInFailure(SocialProvider.google, error);
    }
  }

  @override
  Future<void> signOut() async {
    final ready = _googleReady;
    if (ready == null) return;
    try {
      await ready;
      await GoogleSignIn.instance.signOut();
    } on Object {
      // The app's own sign-out has already happened; this is a courtesy.
    }
  }

  @override
  Future<AppleCredential?> apple() async {
    final rawNonce = newAppleNonce();
    final AuthorizationCredentialAppleID credential;
    try {
      credential = await _authorizeApple(appleNonceHash(rawNonce));
    } on SignInWithAppleAuthorizationException catch (error) {
      if (error.code == AuthorizationErrorCode.canceled) return null;
      throw SocialSignInFailure(SocialProvider.apple, error.code);
    } on Object catch (error) {
      throw SocialSignInFailure(SocialProvider.apple, error);
    }
    final identityToken = credential.identityToken;
    if (identityToken == null || identityToken.isEmpty) {
      throw const SocialSignInFailure(SocialProvider.apple, 'no token');
    }
    return AppleCredential(
      identityToken: identityToken,
      rawNonce: rawNonce,
      fullName: joinAppleName(credential.givenName, credential.familyName),
      userIdentifier: credential.userIdentifier,
    );
  }

  @override
  Future<String?> appleAuthorizationCode() async {
    final AuthorizationCredentialAppleID credential;
    try {
      credential = await _reauthorizeApple();
    } on SignInWithAppleAuthorizationException catch (error) {
      if (error.code == AuthorizationErrorCode.canceled) return null;
      throw SocialSignInFailure(SocialProvider.apple, error.code);
    } on Object catch (error) {
      throw SocialSignInFailure(SocialProvider.apple, error);
    }
    final code = credential.authorizationCode;
    if (code.isEmpty) {
      throw const SocialSignInFailure(SocialProvider.apple, 'no code');
    }
    return code;
  }
}

final socialSignInProvider = Provider<SocialSignIn>(
  (ref) => PlatformSocialSignIn(),
);

/// Takes a provider's credential to the server.
///
/// Apple gives the person's name on the first authorization only, so it is
/// kept until a sign-in succeeds: a retry after a failure sends it again.
/// When the server could not be asked (offline, a timeout, a 5xx such as
/// `apple_sign_in_unavailable`, a rate limit) and the token is still valid,
/// the retry reuses the same credential without asking Apple again. When the
/// token itself was refused, or has expired, Apple is asked again and the
/// kept name goes with the new token.
class SocialAuth {
  SocialAuth(this._ref);

  final Ref _ref;

  /// A token can be reused only while it has this long left.
  static const _tokenMargin = Duration(seconds: 60);

  AppleCredential? _keptApple;
  bool _keptAppleUsable = false;

  SocialSignIn get _provider => _ref.read(socialSignInProvider);
  SessionController get _session => _ref.read(sessionProvider.notifier);

  /// Signs in with Google. False when the person cancelled.
  Future<bool> google(CommunicationLanguage language) async {
    final credential = await _provider.google();
    if (credential == null) return false;
    await _session.signInWithGoogle(
      idToken: credential.idToken,
      preferredLanguage: language,
    );
    return true;
  }

  /// Signs in with Apple. False when the person cancelled.
  Future<bool> apple(CommunicationLanguage language) async {
    final credential = await _appleCredential();
    if (credential == null) return false;
    _keptApple = credential;
    _keptAppleUsable = true;
    try {
      await _session.signInWithApple(
        identityToken: credential.identityToken,
        nonce: credential.rawNonce,
        fullName: credential.fullName,
        preferredLanguage: language,
      );
    } on ApiException catch (error) {
      _keptAppleUsable =
          error.isRetryable || error.kind == ApiFailureKind.rateLimited;
      rethrow;
    } on Object {
      _keptAppleUsable = false;
      rethrow;
    }
    _keptApple = null;
    _keptAppleUsable = false;
    return true;
  }

  Future<AppleCredential?> _appleCredential() async {
    final kept = _keptApple;
    if (kept != null && _keptAppleUsable && _stillValid(kept.identityToken)) {
      return kept;
    }
    final fresh = await _provider.apple();
    if (fresh == null) return null;
    final keptFor = kept?.userIdentifier;
    if (fresh.fullName.isEmpty &&
        kept != null &&
        kept.fullName.isNotEmpty &&
        keptFor != null &&
        keptFor == fresh.userIdentifier) {
      return fresh.withFullName(kept.fullName);
    }
    return fresh;
  }

  /// The session moved on (signed out, or someone signed in): a kept Apple
  /// credential and name belong to an attempt that is over.
  void _sessionChanged(SessionState? previous, SessionState next) {
    _keptApple = null;
    _keptAppleUsable = false;
    if (previous is SessionSignedIn && next is SessionSignedOut) {
      unawaited(_provider.signOut());
    }
  }

  /// Whether a JWT's `exp` leaves at least [_tokenMargin]. Read only to
  /// decide whether a retry may reuse it; the server verifies the token.
  bool _stillValid(String token) {
    final parts = token.split('.');
    if (parts.length != 3) return false;
    try {
      final payload = jsonDecode(
        utf8.decode(base64Url.decode(base64Url.normalize(parts[1]))),
      );
      final exp = payload is Map ? payload['exp'] : null;
      if (exp is! num) return false;
      final expiry = DateTime.fromMillisecondsSinceEpoch(
        exp.toInt() * 1000,
        isUtc: true,
      );
      final now = _ref.read(clockProvider)();
      return expiry.difference(now) > _tokenMargin;
    } on FormatException {
      return false;
    }
  }
}

final socialAuthProvider = Provider<SocialAuth>((ref) {
  final auth = SocialAuth(ref);
  ref.listen(sessionProvider, auth._sessionChanged);
  return auth;
});
