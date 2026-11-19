/// A [SocialSignIn] that never reaches Google or Apple.
library;

import 'dart:convert';

import 'package:shiptrip/core/auth/social_sign_in.dart';

/// A JWT-shaped string whose payload says it expires at [expires]. The app
/// reads `exp` only to decide whether a retry may reuse the token; nothing
/// in it is verified on the phone.
String fakeJwt({required DateTime expires, String subject = 'apple-user'}) {
  String part(Map<String, Object> json) =>
      base64Url.encode(utf8.encode(jsonEncode(json))).replaceAll('=', '');
  return '${part({'alg': 'RS256'})}.'
      '${part({'sub': subject, 'exp': expires.millisecondsSinceEpoch ~/ 1000})}'
      '.signature';
}

AppleCredential appleCredential({
  String fullName = 'Yacine Belkacem',
  String? identityToken,
  String rawNonce = 'raw-nonce-0123456789abcdef',
  String userIdentifier = 'apple-user',
}) => AppleCredential(
  identityToken:
      identityToken ??
      fakeJwt(expires: DateTime.now().add(const Duration(minutes: 10))),
  rawNonce: rawNonce,
  fullName: fullName,
  userIdentifier: userIdentifier,
);

class FakeSocialSignIn implements SocialSignIn {
  FakeSocialSignIn({this.offersGoogle = true, this.offersApple = true});

  @override
  final bool offersGoogle;

  @override
  final bool offersApple;

  /// What the next tap answers: a credential, `null` (cancelled), or a
  /// throw. Each call takes the first; the last one repeats.
  final googleAnswers = <GoogleCredential? Function()>[
    () => const GoogleCredential(idToken: 'google-id-token'),
  ];
  final appleAnswers = <AppleCredential? Function()>[appleCredential];

  int googleCalls = 0;
  int appleCalls = 0;

  static T _next<T>(List<T Function()> answers) =>
      (answers.length > 1 ? answers.removeAt(0) : answers.single)();

  @override
  Future<GoogleCredential?> google() async {
    googleCalls++;
    return _next(googleAnswers);
  }

  @override
  Future<AppleCredential?> apple() async {
    appleCalls++;
    return _next(appleAnswers);
  }
}
