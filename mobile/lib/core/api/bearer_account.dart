import 'dart:convert';

/// The account an access token was issued to (its `user_id` claim), or null
/// when the token carries none that can be read.
///
/// Read only to refuse sending a member's write under someone else's token; the
/// server still decides everything, and never trusts what the app read here.
int? bearerAccountId(String accessToken) {
  final parts = accessToken.split('.');
  if (parts.length != 3) return null;
  try {
    final payload = jsonDecode(
      utf8.decode(base64Url.decode(base64Url.normalize(parts[1]))),
    );
    if (payload is! Map) return null;
    final claim = payload['user_id'];
    if (claim is int) return claim;
    if (claim is String) return int.tryParse(claim);
    return null;
  } on Object {
    return null;
  }
}
