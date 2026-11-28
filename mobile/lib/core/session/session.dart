/// Session: who is signed in, what they may do, and which side of the
/// marketplace they are currently looking at.
///
/// The sign-in itself lives in [SessionCore], created once in `main()`: one
/// stored record, one writer, one way in and one way out. [SessionController]
/// shows what the core holds, runs the sign-in requests through it, and is
/// the one owner of the account snapshot (rule S-6): only it reads `/api/me`.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/auth_repository.dart';
import '../../domain/account.dart';
import '../../domain/communication_language.dart';
import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/error_codes.dart';
import 'session_core.dart';
import 'token_store.dart';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

@immutable
sealed class SessionState {
  const SessionState();
}

/// Before the stored record has been read. The router holds on the splash
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
  const SessionSignedIn(this.account, {required this.sid});
  final Account account;

  /// The sign-in: a new one at each authentication, including a return to the
  /// same account.
  final String sid;
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

/// The one [SessionCore]. `main()` creates it and passes it in.
final sessionCoreProvider = Provider<SessionCore>(
  (ref) => throw UnimplementedError('SessionCore is created in main().'),
);

final apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient(session: ref.watch(sessionCoreProvider));
  ref.onDispose(() => client.raw.close(force: true));
  return client;
});

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(ref.watch(apiClientProvider)),
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
typedef AccountSession = ({int accountId, String sid});

final accountSessionProvider = Provider<AccountSession?>((ref) {
  final session = ref.watch(sessionProvider);
  return session is SessionSignedIn
      ? (accountId: session.account.id, sid: session.sid)
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
  /// When a launch could not reach the server, how long to wait before asking
  /// again. Bounded: after the last one, a resume or any screen's own read
  /// does the revalidating.
  static const _revalidateAfter = <Duration>[
    Duration(seconds: 10),
    Duration(seconds: 30),
    Duration(seconds: 90),
  ];
  Timer? _revalidation;

  /// The newest read of `/api/me`. An answer to an older read is dropped
  /// (rule R9): this notifier is not rebuilt between reads, so nothing else
  /// would drop it.
  int _reads = 0;

  /// What [state] last showed of the core, so a change it does not show (an
  /// attempt reserved, a token replaced) publishes nothing.
  Object? _shown;

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

  SessionCore get _core => ref.read(sessionCoreProvider);
  AuthRepository get _auth => ref.read(authRepositoryProvider);

  @override
  SessionState build() {
    final core = ref.watch(sessionCoreProvider);
    var loaded = core.loaded;
    var signedIn = core.current != null;
    void sync() {
      if (!loaded && core.loaded) {
        loaded = true;
        _confirmStored(core);
      }
      // A sign-in that ends takes its side of the marketplace with it, so the
      // next account starts from its own (or from the guest's choice).
      if (signedIn && core.current == null) {
        ref.read(tokenStoreProvider).writeRoleContext(null).ignore();
      }
      signedIn = core.current != null;
      final shown = _showing(core);
      if (shown == _shown) return;
      _shown = shown;
      state = _stateOf(core);
    }

    core.addListener(sync);
    ref.onDispose(() {
      core.removeListener(sync);
      _revalidation?.cancel();
    });
    // Deletes handover-code plaintext left by the retired build.
    unawaited(ref.read(tokenStoreProvider).purgeLegacyArtifacts());
    // Kicked off here rather than from a screen: the router's guard reads this
    // state before any screen is built.
    unawaited(core.load());
    if (loaded) _confirmStored(core);
    _shown = _showing(core);
    return _stateOf(core);
  }

  static Object _showing(SessionCore core) =>
      (core.loaded, core.current?.sid, core.current?.account, core.notice);

  static SessionState _stateOf(SessionCore core) {
    if (!core.loaded) return const SessionRestoring();
    final signIn = core.current;
    if (signIn == null) {
      return SessionSignedOut(
        becauseExpired: core.notice == EndReason.refused,
        becauseDeleted: core.notice == EndReason.deleted,
      );
    }
    return SessionSignedIn(signIn.account, sid: signIn.sid);
  }

  /// A stored sign-in is shown at once, from its snapshot, and confirmed with
  /// the server in the background (K5). The snapshot is display state only:
  /// every screen still reads the server and every action is decided there.
  void _confirmStored(SessionCore core) {
    final signIn = core.current;
    if (signIn != null) unawaited(_confirm(core, signIn.sid, 0));
  }

  /// No answer ends the sign-in here: only the refusal of its refresh token
  /// does, in the API client. A throttle waits for its `Retry-After`; no
  /// network or a server error asks again on a short schedule.
  Future<void> _confirm(SessionCore core, String sid, int attempt) async {
    final error = await _read();
    if (error == null ||
        core.current?.sid != sid ||
        attempt >= _revalidateAfter.length) {
      return;
    }
    final wait = error.kind == ApiFailureKind.rateLimited
        ? error.retryAfter ?? _revalidateAfter[attempt]
        : error.isRetryable
        ? _revalidateAfter[attempt]
        : null;
    if (wait == null) return;
    _revalidation?.cancel();
    _revalidation = Timer(wait, () {
      if (core.current?.sid == sid) unawaited(_confirm(core, sid, attempt + 1));
    });
  }

  /// The one read of `/api/me` (rule S-6). Its answer is stored only if no
  /// newer read started meanwhile and the sign-in it was read for is still
  /// current. Returns the request's failure, if any.
  Future<ApiException?> _read({bool fresh = false}) async {
    final core = _core;
    final auth = _auth;
    final signIn = core.current;
    if (signIn == null) return null;
    final read = ++_reads;
    _markAccountRead();
    try {
      final account = await auth.me(fresh: fresh);
      if (read == _reads) await core.updateAccount(signIn.sid, account);
      return null;
    } on ApiException catch (error) {
      return error;
    } on Object {
      // The phone could not store it: what is shown stays as it was.
      return null;
    }
  }

  /// Re-reads `/api/me`. Called after KYC submission, on resume, and whenever
  /// a screen has reason to believe verification state moved.
  ///
  /// A failure keeps the account shown: dropping the user to a sign-in screen
  /// because one background poll timed out would be worse than a slightly
  /// stale badge. True when the server answered.
  ///
  /// Always a new read: a live KYC event lands here, and a read already in
  /// flight may predate it.
  Future<bool> refreshAccount() async => await _read(fresh: true) == null;

  /// Runs one sign-in attempt (rule S-2). It is reserved before the first
  /// await, so a second tap in the same frame, on this control or another,
  /// starts nothing. [request] answers with the sign-in the server issued, or
  /// null when the person stopped first (a provider's sheet closed). An
  /// attempt ends with its answer: there is no cancel.
  ///
  /// True when the member is signed in; false when nothing started. Throws
  /// the request's failure, or [SessionNotSaved] when the phone could not
  /// keep the sign-in the server issued.
  Future<bool> signInWith(Future<SignIn?> Function() request) async {
    final core = _core;
    final attempt = core.reserve();
    if (attempt == null) return false;
    final SignIn? signIn;
    try {
      signIn = await request();
    } on Object {
      core.release(attempt);
      rethrow;
    }
    if (signIn == null) {
      core.release(attempt);
      return false;
    }
    await core.signedIn(attempt, signIn);
    _markAccountRead();
    _adoptRoleContext(signIn.account).ignore();
    return true;
  }

  /// Stores the side a sign-in starts on: the server's when the account has
  /// only one, else the guest's choice, else sending. A preference only, so a
  /// keystore that refuses it changes nothing else.
  Future<void> _adoptRoleContext(Account account) async {
    final tokens = ref.read(tokenStoreProvider);
    final stored = RoleContext.tryParse(await tokens.readRoleContext());
    final side = switch (account.role) {
      AccountRole.sender => RoleContext.sender,
      AccountRole.traveler => RoleContext.traveler,
      _ => stored ?? RoleContext.sender,
    };
    await tokens.writeRoleContext(side.wire);
  }

  Future<bool> signIn({required String email, required String password}) =>
      signInWith(() => _auth.signIn(email: email, password: password));

  Future<bool> signUp({
    required String fullName,
    required String email,
    required String password,
    required String phone,
    String? wilaya,
    required CommunicationLanguage preferredLanguage,
  }) => signInWith(
    () => _auth.signUp(
      fullName: fullName,
      email: email,
      password: password,
      phone: phone,
      wilaya: wilaya,
      preferredLanguage: preferredLanguage,
    ),
  );

  /// Changes the language ShipTrip writes to this account in.
  ///
  /// Deliberately not swallowed the way [refreshAccount] is: this one is a
  /// user action with a visible result, so the screen has to be able to say
  /// "that did not save" rather than silently keeping a value the server never
  /// accepted.
  Future<void> updatePreferredLanguage(CommunicationLanguage language) =>
      _write(() => _auth.updateProfile(preferredLanguage: language));

  /// Names an account that has no name: a social sign-in that gave none.
  ///
  /// The server takes a name only while the account has none. When it
  /// answers `name_already_set` (the name arrived another way, such as a
  /// later sign-in that carried it) the step is done, the same as a success.
  /// Any other failure is the screen's to show.
  Future<void> setFullName(String fullName) async {
    try {
      await _write(() => _auth.updateProfile(fullName: fullName));
    } on ApiException catch (error) {
      if (error.code != ApiErrorCode.nameAlreadySet) rethrow;
    }
  }

  /// A profile write. Whatever it answered, the account is read again, and
  /// only that read is shown: a write's own answer could be older than a
  /// read that overtook it.
  Future<void> _write(Future<void> Function() write) async {
    try {
      await write();
    } finally {
      await _read(fresh: true);
    }
  }

  /// Signs the member out (rule S-3). The server hears of it from the core's
  /// sender. If the phone cannot store the sign-out, the member stays signed
  /// in and [SessionNotSaved] is thrown for the screen to say so.
  Future<void> signOut() async {
    final signIn = _core.current;
    if (signIn != null) await _core.end(signIn.sid, EndReason.signedOut);
  }

  /// The server deleted the account and ended every session.
  Future<void> accountDeleted() async {
    final signIn = _core.current;
    if (signIn != null) await _core.end(signIn.sid, EndReason.deleted);
  }

  /// The guest closed the "you were signed out" notice.
  void dismissSignedOutNotice() => _core.dismissNotice();
}

class RoleContextController extends Notifier<RoleContext> {
  /// Survives `build()` re-running when the account changes, so a user who
  /// switched to travelling does not snap back to sending the moment their
  /// profile refreshes.
  RoleContext? _remembered;

  /// The sign-in [_remembered] belongs to. Sign-out, another account, or the
  /// same account signing in again all start over from the choice stored on
  /// the phone, never from the previous sign-in's own.
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
