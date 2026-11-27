/// Session: who is signed in, what they may do, and which side of the
/// marketplace they are currently looking at.
///
/// One controller owns all three because they change together. A sign-out has
/// to clear the account, the tokens, the role context and every cached screen;
/// splitting that across providers is how a stale traveller dashboard survives
/// a sign-in as a different user.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/auth_repository.dart';
import '../../domain/account.dart';
import '../../domain/communication_language.dart';
import '../../domain/person_photo.dart';
import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/bearer_account.dart';
import '../api/error_codes.dart';
import 'member_scope.dart';
import 'token_store.dart';

export 'member_scope.dart';

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

/// Nobody is signed in: the app is browsed as a guest.
class SessionSignedOut extends SessionState {
  const SessionSignedOut({
    this.becauseExpired = false,
    this.becauseDeleted = false,
  });

  /// True when a live session ended rather than the app simply starting
  /// signed out, until the guest signs in again or dismisses the notice that
  /// says so. The sign-in screen and the guest screens explain the difference.
  final bool becauseExpired;

  /// True right after the member deleted their account, until they dismiss
  /// the notice that confirms it or sign in again.
  final bool becauseDeleted;
}

class SessionSignedIn extends SessionState {
  const SessionSignedIn(this.account, {this.generation = 0, this.identity = 0});
  final Account account;

  /// Changes at each authentication, including a return to the same account.
  final int generation;

  /// The credential generation (`TokenStore.identityGeneration`) this account
  /// was published under. A sign-in moves the store's generation the moment it
  /// starts, while the previous account stays published until the new one
  /// answers; a press that must belong to the published account reads this, not
  /// the store, so it can never pair one account with another's generation.
  final int identity;
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

/// Cache identity for private reads. Account ID alone would reuse A's cached
/// data after A signs out and signs back in while a listener remains mounted.
typedef AccountSession = ({int accountId, int generation});

final accountSessionProvider = Provider<AccountSession?>((ref) {
  final session = ref.watch(sessionProvider);
  return session is SessionSignedIn
      ? (accountId: session.account.id, generation: session.generation)
      : null;
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

/// True once the restore has settled on nobody being signed in.
final isGuestProvider = Provider<bool>(
  (ref) => ref.watch(sessionProvider) is SessionSignedOut,
);

/// True when the viewer may switch sides at all. Drives whether the switch
/// affordance exists — not merely whether it is enabled. A guest may: they
/// are only looking, and the choice carries into the account they make.
final canSwitchRoleProvider = Provider<bool>((ref) {
  if (ref.watch(isGuestProvider)) return true;
  return ref.watch(accountProvider)?.role.canSwitch ?? false;
});

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

  /// When a launch that started on the snapshot could not reach the server,
  /// how long to wait before asking again. Bounded: after the last one, a
  /// resume or any screen's own read does the revalidating.
  static const _revalidateAfter = <Duration>[
    Duration(seconds: 10),
    Duration(seconds: 30),
    Duration(seconds: 90),
  ];
  int _generation = 0;

  /// Counts the member's own photo writes the server accepted and this session
  /// applied (a failed write is not one: it changed nothing). A read of the
  /// profile that began under a different count may predate a write that has
  /// since finished, so it may not decide what the photo is.
  int _photoApplied = 0;
  Timer? _revalidation;

  /// The account the credentials in storage belong to, as far as this window
  /// has seen them committed: set when a sign-in's credentials were saved or a
  /// restore confirmed them, cleared when they are cleared. A failed sign-in
  /// is settled against it, not against whoever happens to be displayed: a
  /// sign-in that was overtaken after it saved still owns the credentials.
  int? _credentialOwner;

  /// Monotonic; [_accountReadAt] is measured on it.
  final Stopwatch _clock = Stopwatch()..start();
  Duration? _accountReadAt;

  /// Whether this session sent or received a server read of the account in
  /// the last [window]. A resume uses it to tell a launch — whose restore is
  /// reading `/api/me` already — from a first real open long after one.
  bool accountReadWithin(Duration window) {
    final at = _accountReadAt;
    return at != null && _clock.elapsed - at < window;
  }

  void _markAccountRead() => _accountReadAt = _clock.elapsed;

  @override
  SessionState build() {
    // Kicked off here rather than from a screen: the router's guard reads this
    // state before any screen is built, so a restore that only started when
    // the splash mounted would leave the very first redirect deciding on a
    // value nothing had yet produced. The splash's retry re-enters the same
    // method.
    ref.onDispose(() => _revalidation?.cancel());
    listenSelf((_, next) => _tokens.bearerWithheld = next is SessionSignedOut);
    unawaited(restore());
    return const SessionRestoring();
  }

  AuthRepository get _auth => ref.read(authRepositoryProvider);
  TokenStore get _tokens => ref.read(tokenStoreProvider);

  /// The scope of an action that starts now, or null when there is none to
  /// begin: nobody is signed in, or the credentials have already moved on from
  /// the account that is published (a sign-in is replacing it), so anything
  /// begun now would pair one member with the next one's credentials.
  MemberScope? beginAction() {
    final now = state;
    if (now is! SessionSignedIn || now.identity != _tokens.identityGeneration) {
      return null;
    }
    return MemberScope(
      accountId: now.account.id,
      session: now.generation,
      credentials: now.identity,
    );
  }

  /// Whether [scope] is still the member who is signed in, on the same
  /// authentication and the same credentials. The one check an action makes
  /// when it commits.
  bool isCurrent(MemberScope scope) {
    final now = state;
    return now is SessionSignedIn &&
        now.account.id == scope.accountId &&
        now.generation == scope.session &&
        now.identity == scope.credentials &&
        _tokens.identityGeneration == scope.credentials;
  }

  /// Reads stored credentials and confirms them against the server.
  ///
  /// With a snapshot of the last server-confirmed profile, the user enters the
  /// app on it at once and `/api/me` confirms it in the background (K5): a
  /// cold start no longer waits on a round trip before Home can start loading,
  /// and a launch without network reaches the app instead of the splash. The
  /// snapshot is display state only. Every screen still reads the server, every
  /// action is still decided there, and a credential the server no longer
  /// honours still ends the session — through the same 401 path as any read.
  ///
  /// Without a snapshot (first launch after sign-in on an older build, or a
  /// keystore that lost it) the previous contract holds: one `/api/me` up
  /// front, and an offline launch holds the splash with its retry.
  Future<void> restore() async {
    _revalidation?.cancel();
    final generation = ++_generation;
    final identity = _tokens.identityGeneration;
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
      if (generation == _generation) state = const SessionSignedOut();
      return;
    }

    if (generation != _generation) return;
    if (refresh == null) {
      _credentialOwner = null;
      state = const SessionSignedOut();
      return;
    }

    final cached = await _readSnapshot();
    if (generation != _generation) return;
    if (cached != null) {
      _credentialOwner = cached.id;
      state = SessionSignedIn(
        cached,
        generation: generation,
        identity: identity,
      );
    }
    await _confirm(
      generation: generation,
      identity: identity,
      cached: cached,
      attempt: 0,
    );
  }

  /// Asks the server who the stored credentials belong to.
  Future<void> _confirm({
    required int generation,
    required int identity,
    required Account? cached,
    required int attempt,
  }) async {
    final photoWrites = _photoApplied;
    _markAccountRead();
    try {
      final answered = await _auth.me();
      if (generation != _generation) return;
      final Account account;
      if (cached != null && answered.id != cached.id) {
        // Only a damaged snapshot can get here. Move every account-scoped
        // read to a fresh generation rather than let one survive the swap.
        account = answered;
        _generation++;
        _credentialOwner = account.id;
        state = SessionSignedIn(
          account,
          generation: _generation,
          identity: identity,
        );
      } else {
        // The member may have changed their photo while this answer was on
        // its way: the newer photo is kept.
        account = _withNewestPhoto(answered, photoWrites);
        _credentialOwner = account.id;
        state = SessionSignedIn(
          account,
          generation: generation,
          identity: identity,
        );
      }
      unawaited(_remember(account, identity));
    } on ApiException catch (error) {
      if (generation != _generation) return;
      // Offline at launch is not a signed-out user. Keeping the credentials
      // and surfacing the network state lets the app recover when
      // connectivity returns instead of demanding a password in a tunnel.
      if (error.isRetryable) {
        if (cached == null) {
          state = const SessionRestoring();
        } else if (attempt < _revalidateAfter.length) {
          _revalidation?.cancel();
          _revalidation = Timer(_revalidateAfter[attempt], () {
            if (generation != _generation) return;
            unawaited(
              _confirm(
                generation: generation,
                identity: identity,
                cached: cached,
                attempt: attempt + 1,
              ),
            );
          });
        }
        return;
      }
      // Another request's terminal refresh already ended this login: it
      // cleared the credentials and its expiry callback reports it, with the
      // "session expired" message. This answer lost that race and is not a
      // verdict on the credentials, so it must not pre-empt that message.
      if (error.kind == ApiFailureKind.cancelled ||
          identity != _tokens.identityGeneration) {
        return;
      }
      await _tokens.clear();
      if (generation == _generation) {
        _generation++;
        _credentialOwner = null;
        state = const SessionSignedOut();
      }
    }
  }

  Future<Account?> _readSnapshot() async {
    try {
      final raw = await _tokens.readAccountSnapshot().timeout(_storageBudget);
      if (raw == null || raw.isEmpty) return null;
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      final account = Account.fromJson(Map<String, dynamic>.from(decoded));
      return account.id > 0 ? account : null;
    } on Object {
      // Unreadable or malformed: launch as if there were none.
      return null;
    }
  }

  /// Keeps the snapshot current. Best effort: failing to write it only costs
  /// the next launch its head start.
  Future<void> _remember(Account account, int identity) async {
    try {
      await _tokens.writeAccountSnapshotIfCurrent(
        expectedIdentityGeneration: identity,
        json: jsonEncode(account.toSnapshotJson()),
      );
    } on Object {
      // Ignored on purpose.
    }
  }

  Future<void> signIn({required String email, required String password}) =>
      _authenticateWith(
        (identity) => _auth.signIn(
          email: email,
          password: password,
          expectedIdentityGeneration: identity,
        ),
      );

  Future<void> signUp({
    required String fullName,
    required String email,
    required String password,
    required String phone,
    String? wilaya,
    required CommunicationLanguage preferredLanguage,
  }) => _authenticateWith(
    (identity) => _auth.signUp(
      fullName: fullName,
      email: email,
      password: password,
      phone: phone,
      wilaya: wilaya,
      preferredLanguage: preferredLanguage,
      expectedIdentityGeneration: identity,
    ),
  );

  Future<void> signInWithGoogle({
    required String idToken,
    required CommunicationLanguage preferredLanguage,
  }) => _authenticateWith(
    (identity) => _auth.signInWithGoogle(
      idToken: idToken,
      preferredLanguage: preferredLanguage,
      expectedIdentityGeneration: identity,
    ),
  );

  Future<void> signInWithApple({
    required String identityToken,
    required String nonce,
    required String fullName,
    required CommunicationLanguage preferredLanguage,
  }) => _authenticateWith(
    (identity) => _auth.signInWithApple(
      identityToken: identityToken,
      nonce: nonce,
      fullName: fullName,
      preferredLanguage: preferredLanguage,
      expectedIdentityGeneration: identity,
    ),
  );

  /// Every sign-in's one path: a new generation and identity, so nothing
  /// started under the previous login lands; the role context; the state;
  /// the launch snapshot.
  Future<void> _authenticateWith(
    Future<Account> Function(int identity) authenticate,
  ) async {
    final generation = ++_generation;
    final identity = _tokens.invalidateIdentity();
    final Account account;
    try {
      account = await authenticate(identity);
    } on Object catch (error) {
      await _settleAfterFailedSignIn(
        generation,
        identity,
        credentialsUncertain: error is! ApiException,
      );
      rethrow;
    }
    // Saved: from here the stored credentials are this account's, whether or
    // not a newer sign-in overtakes this one before it is published.
    _credentialOwner = account.id;
    if (generation != _generation) return;
    await _adoptRoleContextFor(account);
    if (generation != _generation) return;
    state = SessionSignedIn(
      account,
      generation: generation,
      identity: identity,
    );
    _markAccountRead();
    unawaited(_remember(account, identity));
  }

  /// Brings what is published in line with the credentials in storage after a
  /// sign-in that did not end in a published member, when it is still the
  /// newest one (a newer sign-in settles itself).
  ///
  /// The attempt moved the store's generation already, so whoever is shown
  /// must be published again under the generation the credentials now carry,
  /// or every action of theirs would find them "changed" and refuse. But only
  /// if the credentials are theirs: an earlier sign-in that was overtaken
  /// after it saved owns them, and then that member is the one to show.
  ///
  /// A refusal before anything was written ([credentialsUncertain] false)
  /// left the credentials as they were. A storage failure may have come before
  /// or after the credentials changed, so storage is asked whose they are.
  /// Credentials that cannot be tied to the member shown end the local
  /// session: nobody is signed in, and nothing is left half written.
  Future<void> _settleAfterFailedSignIn(
    int generation,
    int identity, {
    required bool credentialsUncertain,
  }) async {
    if (generation != _generation) return;
    int? owner = _credentialOwner;
    if (credentialsUncertain) {
      try {
        final access = await _tokens.readAccess().timeout(_storageBudget);
        owner = access == null ? null : bearerAccountId(access);
      } on Object {
        owner = null;
      }
    }
    if (generation != _generation) return;
    final shown = state;
    if (owner != null &&
        shown is SessionSignedIn &&
        shown.account.id == owner) {
      _credentialOwner = owner;
      state = SessionSignedIn(
        shown.account,
        generation: generation,
        identity: identity,
      );
      return;
    }
    if (owner != null && !credentialsUncertain) {
      // Saved by a sign-in this window did not publish: show that member, as a
      // launch would. Restoring, not signed out: a guest's reads carry no
      // bearer, and this one asks the server whose the credentials are.
      state = const SessionRestoring();
      unawaited(restore());
      return;
    }
    if (shown is SessionSignedIn || credentialsUncertain) {
      _generation++;
      _credentialOwner = null;
      state = const SessionSignedOut();
      if (credentialsUncertain) unawaited(_clearQuietly(identity));
    }
  }

  Future<void> _clearQuietly(int identity) async {
    try {
      await _tokens.clearIfIdentityCurrent(identity);
    } on Object {
      // Nothing more can be done about a keystore that cannot be written.
    }
  }

  /// Changes the language ShipTrip writes to this account in.
  ///
  /// Deliberately not swallowed the way [refreshAccount] is: this one is a
  /// user action with a visible result, so the screen has to be able to say
  /// "that did not save" rather than silently keeping a value the server never
  /// accepted. The state moves only once the server has answered, and it moves
  /// to the profile the server returned — never to the value that was asked
  /// for.
  ///
  /// True when the member's profile now shows what the server stored. False
  /// when nothing was applied because the member signed out or another member
  /// signed in meanwhile: there is nothing for the screen to confirm.
  Future<bool> updatePreferredLanguage(CommunicationLanguage language) =>
      _updateProfile(() => _auth.updateProfile(preferredLanguage: language));

  /// Names an account that has no name: a social sign-in that gave none.
  ///
  /// The server takes a name only while the account has none. When it
  /// answers `name_already_set` (the name arrived another way, such as a
  /// later sign-in that carried it) the account is re-read and the step is
  /// done, the same as a success. Any other failure is the screen's to show.
  ///
  /// True when the step is done for the member who asked, false when that
  /// member is no longer the one signed in (see [updatePreferredLanguage]).
  Future<bool> setFullName(String fullName) async {
    final scope = beginAction();
    try {
      return await _updateProfile(
        () => _auth.updateProfile(fullName: fullName),
      );
    } on ApiException catch (error) {
      if (error.code != ApiErrorCode.nameAlreadySet || scope == null) rethrow;
      await refreshAccount();
      return isCurrent(scope);
    }
  }

  /// Sets the member's photo. The account moves only once the server has
  /// answered, to the photo it returned. Sent once and never repeated here:
  /// the screen's button is the only retry.
  ///
  /// [expectedIdentity] is the credential generation read when the member
  /// pressed the button (see `TokenStore.identityGeneration`): if a sign-in or
  /// sign-out has happened since, nothing is sent.
  Future<void> uploadPhoto({
    required MemberScope scope,
    required String filePath,
    required String fileName,
    required String contentType,
    void Function(int sent, int total)? onProgress,
  }) => _updatePhoto(
    scope,
    () => _auth.uploadPhoto(
      filePath: filePath,
      fileName: fileName,
      contentType: contentType,
      scope: scope,
      onProgress: onProgress,
    ),
  );

  /// Removes the photo, or dismisses the notice that Wassla removed it.
  ///
  /// [scope] is as for [uploadPhoto]: nothing is sent when it is no longer
  /// current.
  ///
  /// [shownVersion] is the photo the member was looking at, see
  /// `AuthRepository.removePhoto`.
  Future<void> removePhoto({
    required MemberScope scope,
    required String shownVersion,
  }) => _updatePhoto(scope, () async {
    await _auth.removePhoto(scope: scope, shownVersion: shownVersion);
    return null;
  });

  Future<void> _updatePhoto(
    MemberScope scope,
    Future<OwnPhoto?> Function() change,
  ) async {
    final photo = await change();
    final now = state;
    if (isCurrent(scope) && now is SessionSignedIn) {
      _photoApplied++;
      state = SessionSignedIn(
        now.account.withPhoto(photo),
        generation: now.generation,
        identity: now.identity,
      );
    }
  }

  /// How many photo writes the server accepted and the session applied. Another
  /// part of the app that holds the member's own photo compares it before and
  /// after a read or a write of its own, and re-reads when it moved. A write
  /// that failed is not counted: it left the photo as it was, so an overlapping
  /// read still decides what the photo is.
  int get photoWrites => _photoApplied;

  /// [fresh], a profile read that began when the applied-write count was
  /// [startedAt], with the photo the session holds now if a write was applied
  /// since. The rest of the profile is the fresh read's.
  Account _withNewestPhoto(Account fresh, int startedAt) {
    final now = state;
    if (startedAt == _photoApplied || now is! SessionSignedIn) return fresh;
    return fresh.withPhoto(now.account.photo);
  }

  /// Applies a profile change the server answered with the whole profile.
  /// The state moves only once the server has answered, and to the profile it
  /// returned, never to the value that was asked for. False when it did not
  /// move because the member who asked is no longer the one signed in.
  Future<bool> _updateProfile(Future<Account> Function() update) async {
    final scope = beginAction();
    if (scope == null) return false;
    final photoWrites = _photoApplied;
    final Account answered;
    try {
      answered = await update();
    } on ApiException {
      // A request that was out when the member left is refused or answers for
      // nobody here: that is not a failure of theirs to show.
      if (!isCurrent(scope)) return false;
      rethrow;
    }
    if (!isCurrent(scope) || answered.id != scope.accountId) return false;
    final account = _withNewestPhoto(answered, photoWrites);
    _publishProfile(account);
    unawaited(_remember(account, scope.credentials));
    return true;
  }

  /// Replaces the published profile of the member who is signed in, keeping the
  /// authentication and the credentials it was published under.
  void _publishProfile(Account account) {
    final now = state;
    if (now is! SessionSignedIn) return;
    state = SessionSignedIn(
      account,
      generation: now.generation,
      identity: now.identity,
    );
  }

  /// Re-reads `/api/me`. Called after KYC submission, on resume, and whenever
  /// a screen has reason to believe verification state moved.
  ///
  /// Failure is deliberately swallowed: this is a refresh of something the UI
  /// already has, and dropping the user to a sign-in screen because one
  /// background poll timed out would be worse than a slightly stale badge.
  ///
  /// Always a new read: a live KYC event lands here, and a read already in
  /// flight may predate it.
  Future<void> refreshAccount() async {
    // Begun only for the member who is published on the credentials they hold:
    // during a sign-in the store has moved on while the previous member is still
    // shown, and an answer to a read made then would be filed under the new
    // credentials (and written to the launch snapshot as theirs).
    final scope = beginAction();
    if (scope == null) return;
    final photoWrites = _photoApplied;
    _markAccountRead();
    try {
      final answered = await _auth.me(fresh: true);
      if (isCurrent(scope) && answered.id == scope.accountId) {
        final account = _withNewestPhoto(answered, photoWrites);
        _publishProfile(account);
        unawaited(_remember(account, scope.credentials));
      }
    } on ApiException {
      // Keep the previous account.
    }
  }

  Future<void> signOut() async {
    // Clear locally first. If the network call hangs, the user is still out —
    // a sign-out that can fail is not a sign-out.
    _generation++;
    _revalidation?.cancel();
    _credentialOwner = null;
    state = const SessionSignedOut();
    // In the same turn as the tap: from here on no response or snapshot
    // write started under this login is accepted.
    final identity = _tokens.invalidateIdentity();
    // Before the network call: the profile must not outlive the user's
    // decision to leave, even if the app is killed mid sign-out. Queued
    // behind any credential write already in flight, so a snapshot write
    // that was waiting cannot land after it.
    try {
      await _tokens.deleteAccountSnapshot();
    } on Object {
      // The credential clear below deletes it too.
    }
    await _auth.signOut(expectedIdentityGeneration: identity);
  }

  /// The server deleted the account and ended every session: clear the
  /// device as a sign-out does, without asking the server to sign out.
  Future<void> accountDeleted() async {
    _generation++;
    _revalidation?.cancel();
    _credentialOwner = null;
    state = const SessionSignedOut(becauseDeleted: true);
    final identity = _tokens.invalidateIdentity();
    try {
      await _tokens.deleteAccountSnapshot();
    } on Object {
      // The credential clear below deletes it too.
    }
    await _tokens.clearIfIdentityCurrent(identity);
  }

  /// Called by the API client when refresh has failed terminally.
  ///
  /// Nothing else needs resetting here. Private reads bind to
  /// [accountSessionProvider] and switch away from the old cache as soon as
  /// session state changes, and [RoleContextController] forgets a sign-in's
  /// choice the same way. (It used to be invalidated from here, which debug
  /// Riverpod rejects as a circular dependency — it depends on this session —
  /// and which never reset the remembered choice anyway, because invalidating
  /// a notifier keeps the same instance.)
  void handleSessionExpired() {
    if (state is SessionSignedOut) return;
    _generation++;
    _revalidation?.cancel();
    _credentialOwner = null;
    state = const SessionSignedOut(becauseExpired: true);
  }

  /// The guest closed the "you were signed out" notice.
  void dismissSignedOutNotice() {
    final current = state;
    if (current is SessionSignedOut &&
        (current.becauseExpired || current.becauseDeleted)) {
      state = const SessionSignedOut();
    }
  }

  /// Picks the starting context for a freshly authenticated account: the
  /// remembered choice when it is still permitted, otherwise whichever side
  /// the account can actually use.
  ///
  /// Best effort. It runs after the credentials are saved, so a keystore that
  /// cannot keep the choice must not undo the sign-in: the account's own role
  /// decides what is shown, and the choice is read again the next time.
  Future<void> _adoptRoleContextFor(Account account) async {
    try {
      final stored = RoleContext.tryParse(await _tokens.readRoleContext());
      final resolved = switch (account.role) {
        AccountRole.sender => RoleContext.sender,
        AccountRole.traveler => RoleContext.traveler,
        _ => stored ?? RoleContext.sender,
      };
      await _tokens.writeRoleContext(resolved.wire);
    } on Object {
      // See above.
    }
  }
}

class RoleContextController extends Notifier<RoleContext> {
  /// Survives `build()` re-running when the account changes, so a user who
  /// switched to travelling does not snap back to sending the moment their
  /// profile refreshes.
  RoleContext? _remembered;

  /// The sign-in [_remembered] belongs to. Sign-out, another account, or the
  /// same account signing in again all start over from what that sign-in
  /// stored, never from the previous one's choice.
  AccountSession? _rememberedFor;

  @override
  RoleContext build() {
    final role = ref.watch(accountProvider.select((account) => account?.role));
    final session = ref.watch(accountSessionProvider);
    if (session != _rememberedFor) {
      _rememberedFor = session;
      _remembered = null;
    }

    // Server role is authority. Only `both` defers to the stored preference.
    if (role == AccountRole.sender) return RoleContext.sender;
    if (role == AccountRole.traveler) return RoleContext.traveler;

    final known = _remembered;
    if (known != null) return known;

    // First build for a dual-role account: show sending immediately and let
    // the keystore read land a frame or two later. Blocking the first frame
    // on disk would be a worse trade than a brief default.
    unawaited(_hydrate(session));
    return RoleContext.sender;
  }

  Future<void> _hydrate(AccountSession? session) async {
    final stored = RoleContext.tryParse(
      await ref.read(tokenStoreProvider).readRoleContext(),
    );
    // A read begun for an earlier sign-in says nothing about this one.
    if (stored == null || session != _rememberedFor) return;
    _remembered = stored;
    if (stored != state) state = stored;
  }

  /// Switches context. A no-op for accounts the server has restricted to one
  /// side, so a stale UI affordance can never put the user into a context
  /// they are not allowed to act in. A guest's choice is stored like a
  /// member's, so the account they then make starts on the same side.
  void set(RoleContext next) {
    if (!ref.read(canSwitchRoleProvider)) return;
    if (state == next) return;
    _remembered = next;
    state = next;
    unawaited(ref.read(tokenStoreProvider).writeRoleContext(next.wire));
  }

  void toggle() => set(
    state == RoleContext.sender ? RoleContext.traveler : RoleContext.sender,
  );
}
