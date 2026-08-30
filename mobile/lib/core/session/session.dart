/// Session: who is signed in, what they may do, and which side of the
/// marketplace they are currently looking at.
///
/// One controller owns all three because they change together. A sign-out has
/// to clear the account, the tokens, the role context and every cached screen;
/// splitting that across providers is how a stale traveller dashboard survives
/// a sign-in as a different user.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/auth_repository.dart';
import '../../domain/account.dart';
import '../../domain/communication_language.dart';
import '../api/api_client.dart';
import '../api/api_exception.dart';
import 'token_store.dart';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

@immutable
sealed class SessionState {
  const SessionState();
}

/// Before the stored token has been read. The router holds on the splash
/// rather than flashing the sign-in screen at a user who is already signed in.
class SessionRestoring extends SessionState {
  const SessionRestoring();
}

class SessionSignedOut extends SessionState {
  const SessionSignedOut({this.becauseExpired = false});

  /// True when a live session ended rather than the app simply starting
  /// signed out. The sign-in screen explains the difference.
  final bool becauseExpired;
}

class SessionSignedIn extends SessionState {
  const SessionSignedIn(this.account);
  final Account account;
}

/// Which side of the marketplace the UI is presenting.
///
/// For a `sender` or `traveler` account this is fixed by the server. For a
/// `both` account it is the user's own choice, remembered across launches.
enum RoleContext {
  sender,
  traveler;

  String get wire => name;

  static RoleContext? tryParse(String? raw) => switch (raw) {
    'sender' => RoleContext.sender,
    'traveler' => RoleContext.traveler,
    _ => null,
  };
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());

final apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient(
    tokens: ref.watch(tokenStoreProvider),
    onSessionExpired: () {
      // Fired from inside the interceptor after refresh has definitively
      // failed. Routed through the controller so the whole app tears down
      // consistently instead of individual screens each discovering a 401.
      ref.read(sessionProvider.notifier).handleSessionExpired();
    },
  );
  ref.onDispose(() => client.raw.close(force: true));
  return client;
});

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(
    ref.watch(apiClientProvider),
    ref.watch(tokenStoreProvider),
  ),
);

final sessionProvider = NotifierProvider<SessionController, SessionState>(
  SessionController.new,
);

/// The signed-in account, or null. Convenience for the many widgets that only
/// need the account and should not re-render on unrelated session churn.
final accountProvider = Provider<Account?>((ref) {
  final state = ref.watch(sessionProvider);
  return state is SessionSignedIn ? state.account : null;
});

/// The role the UI is currently presenting.
///
/// Server role wins: a pure sender is always in sender context regardless of
/// what is stored locally, so a role downgrade on the server takes effect
/// immediately rather than after the next reinstall.
final roleContextProvider =
    NotifierProvider<RoleContextController, RoleContext>(
      RoleContextController.new,
    );

/// True when the account may switch sides at all. Drives whether the switch
/// affordance exists — not merely whether it is enabled.
final canSwitchRoleProvider = Provider<bool>(
  (ref) => ref.watch(accountProvider)?.role.canSwitch ?? false,
);

// ---------------------------------------------------------------------------
// Controllers
// ---------------------------------------------------------------------------

class SessionController extends Notifier<SessionState> {
  /// How long to wait on secure storage before giving up on it.
  ///
  /// Generous — a cold keystore unlock is genuinely slow on an older Android
  /// device — but bounded, because a platform channel that never answers must
  /// not be able to hold the app on its splash screen indefinitely.
  static const _storageBudget = Duration(seconds: 5);

  @override
  SessionState build() {
    // Kicked off here rather than from a screen: the router's guard reads this
    // state before any screen is built, so a restore that only started when
    // the splash mounted would leave the very first redirect deciding on a
    // value nothing had yet produced. The splash's retry re-enters the same
    // method.
    unawaited(restore());
    return const SessionRestoring();
  }

  AuthRepository get _auth => ref.read(authRepositoryProvider);
  TokenStore get _tokens => ref.read(tokenStoreProvider);

  /// Reads stored credentials and, if present, confirms them against the
  /// server before declaring the user signed in.
  ///
  /// A token that parses is not the same as a token the server still honours;
  /// entering the app on a blacklisted refresh token means every screen fails
  /// at once. One `/api/me` up front is worth that.
  Future<void> restore() async {
    final String? refresh;
    try {
      // Deletes handover-code plaintext left by the retired build, before
      // anything else touches storage.
      await _tokens.purgeLegacyArtifacts().timeout(_storageBudget);
      refresh = await _tokens.readRefresh().timeout(_storageBudget);
    } on Object {
      // The keystore failed or never answered — an Android keystore that
      // cannot unwrap after a backup restore, a wedged platform channel, a
      // platform with no secure storage at all. A store we cannot read is
      // indistinguishable from an empty one, and asking for a fresh sign-in
      // is a recoverable outcome; hanging on the splash forever is not.
      state = const SessionSignedOut();
      return;
    }

    if (refresh == null) {
      state = const SessionSignedOut();
      return;
    }

    try {
      state = SessionSignedIn(await _auth.me());
    } on ApiException catch (error) {
      // Offline at launch is not a signed-out user. Keeping the credentials
      // and surfacing the network state lets the app recover when
      // connectivity returns instead of demanding a password in a tunnel.
      if (error.isRetryable) {
        state = const SessionRestoring();
        return;
      }
      await _tokens.clear();
      state = const SessionSignedOut();
    }
  }

  Future<void> signIn({required String email, required String password}) async {
    final account = await _auth.signIn(email: email, password: password);
    await _adoptRoleContextFor(account);
    state = SessionSignedIn(account);
  }

  Future<void> signUp({
    required String fullName,
    required String email,
    required String password,
    required String phone,
    String? wilaya,
    required CommunicationLanguage preferredLanguage,
  }) async {
    final account = await _auth.signUp(
      fullName: fullName,
      email: email,
      password: password,
      phone: phone,
      wilaya: wilaya,
      preferredLanguage: preferredLanguage,
    );
    await _adoptRoleContextFor(account);
    state = SessionSignedIn(account);
  }

  Future<void> signInWithGoogle({
    required String idToken,
    String? phone,
    String? wilaya,
    CommunicationLanguage? preferredLanguage,
  }) async {
    final account = await _auth.signInWithGoogle(
      idToken: idToken,
      phone: phone,
      wilaya: wilaya,
      preferredLanguage: preferredLanguage,
    );
    await _adoptRoleContextFor(account);
    state = SessionSignedIn(account);
  }

  /// Changes the language ShipTrip writes to this account in.
  ///
  /// Deliberately not swallowed the way [refreshAccount] is: this one is a
  /// user action with a visible result, so the screen has to be able to say
  /// "that did not save" rather than silently keeping a value the server never
  /// accepted. The state moves only once the server has answered, and it moves
  /// to the profile the server returned — never to the value that was asked
  /// for.
  Future<void> updatePreferredLanguage(CommunicationLanguage language) async {
    if (state is! SessionSignedIn) return;
    state = SessionSignedIn(await _auth.updatePreferredLanguage(language));
  }

  /// Re-reads `/api/me`. Called after KYC submission, on resume, and whenever
  /// a screen has reason to believe verification state moved.
  ///
  /// Failure is deliberately swallowed: this is a refresh of something the UI
  /// already has, and dropping the user to a sign-in screen because one
  /// background poll timed out would be worse than a slightly stale badge.
  Future<void> refreshAccount() async {
    if (state is! SessionSignedIn) return;
    try {
      state = SessionSignedIn(await _auth.me());
    } on ApiException {
      // Keep the previous account.
    }
  }

  Future<void> signOut() async {
    // Clear locally first. If the network call hangs, the user is still out —
    // a sign-out that can fail is not a sign-out.
    state = const SessionSignedOut();
    await _auth.signOut();
    _invalidateEverything();
  }

  /// Called by the API client when refresh has failed terminally.
  void handleSessionExpired() {
    if (state is SessionSignedOut) return;
    state = const SessionSignedOut(becauseExpired: true);
    _invalidateEverything();
  }

  /// Drops every cached provider so nothing from the previous account can be
  /// rendered to the next one.
  void _invalidateEverything() {
    ref.invalidate(roleContextProvider);
  }

  /// Picks the starting context for a freshly authenticated account: the
  /// remembered choice when it is still permitted, otherwise whichever side
  /// the account can actually use.
  Future<void> _adoptRoleContextFor(Account account) async {
    final stored = RoleContext.tryParse(await _tokens.readRoleContext());
    final resolved = switch (account.role) {
      AccountRole.sender => RoleContext.sender,
      AccountRole.traveler => RoleContext.traveler,
      _ => stored ?? RoleContext.sender,
    };
    await _tokens.writeRoleContext(resolved.wire);
  }
}

class RoleContextController extends Notifier<RoleContext> {
  /// Survives `build()` re-running when the account changes, so a user who
  /// switched to travelling does not snap back to sending the moment their
  /// profile refreshes.
  RoleContext? _remembered;

  @override
  RoleContext build() {
    final role = ref.watch(accountProvider)?.role;

    // Server role is authority. Only `both` defers to the stored preference.
    if (role == AccountRole.sender) return RoleContext.sender;
    if (role == AccountRole.traveler) return RoleContext.traveler;

    final known = _remembered;
    if (known != null) return known;

    // First build for a dual-role account: show sending immediately and let
    // the keystore read land a frame or two later. Blocking the first frame
    // on disk would be a worse trade than a brief default.
    unawaited(_hydrate());
    return RoleContext.sender;
  }

  Future<void> _hydrate() async {
    final stored = RoleContext.tryParse(
      await ref.read(tokenStoreProvider).readRoleContext(),
    );
    if (stored == null) return;
    _remembered = stored;
    if (stored != state) state = stored;
  }

  /// Switches context. A no-op for accounts the server has restricted to one
  /// side, so a stale UI affordance can never put the user into a context
  /// they are not allowed to act in.
  void set(RoleContext next) {
    if (!(ref.read(accountProvider)?.role.canSwitch ?? false)) return;
    if (state == next) return;
    _remembered = next;
    state = next;
    unawaited(ref.read(tokenStoreProvider).writeRoleContext(next.wire));
  }

  void toggle() => set(
    state == RoleContext.sender ? RoleContext.traveler : RoleContext.sender,
  );
}
