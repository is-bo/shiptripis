import 'package:flutter/foundation.dart' show immutable;

/// Who an action belongs to, captured **once** when it starts and checked once
/// when it commits (`SessionNotifier.isCurrent`).
///
/// It is the whole identity of the signed-in member in one value: the account,
/// the authentication it was published by (`SessionSignedIn.generation`) and
/// the credentials those were published under (`SessionSignedIn.identity`, the
/// token store's generation, which also names the bearer). Nothing an action
/// does afterwards re-reads any of these from the live state: a press, a
/// confirmation dialog, a prepared file or a profile read carries the scope it
/// began with, and what it was given is either still current when it commits or
/// it commits nothing. Two scopes are equal only if every part is.
@immutable
class MemberScope {
  const MemberScope({
    required this.accountId,
    required this.session,
    required this.credentials,
  });

  final int accountId;
  final int session;
  final int credentials;

  @override
  bool operator ==(Object other) =>
      other is MemberScope &&
      other.accountId == accountId &&
      other.session == session &&
      other.credentials == credentials;

  @override
  int get hashCode => Object.hash(accountId, session, credentials);

  @override
  String toString() =>
      'MemberScope(account: $accountId, session: $session, '
      'credentials: $credentials)';
}
