import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/route_transition_tracker.dart';
import '../../app/router.dart';
import '../api/api_exception.dart';
import '../../data/repositories.dart';
import '../../domain/progress.dart';
import '../live/live_updates.dart';
import '../session/session.dart';
import 'notification_socket.dart';
import 'push_messaging.dart';

@immutable
class PushRuntimeState {
  const PushRuntimeState({
    required this.availability,
    this.permission = PushPermission.unavailable,
    this.registration = PushRegistrationState.idle,
  });

  final PushAvailability availability;
  final PushPermission permission;
  final PushRegistrationState registration;

  bool get available => availability == PushAvailability.available;

  PushRuntimeState copyWith({
    PushAvailability? availability,
    PushPermission? permission,
    PushRegistrationState? registration,
  }) => PushRuntimeState(
    availability: availability ?? this.availability,
    permission: permission ?? this.permission,
    registration: registration ?? this.registration,
  );
}

enum PushRegistrationState { idle, pending, registered, failed }

/// The server's answer to a registration that a later one already overtook.
const _registrationSuperseded = 'push_registration_superseded';

/// How many times in one run the automatic prompt may fail to reach the system
/// before it stops trying on its own. Profile still asks on request.
const _automaticPromptFailuresAllowed = 2;

final pushCoordinatorProvider =
    NotifierProvider<PushCoordinator, PushRuntimeState>(PushCoordinator.new);

final notificationSocketProvider = Provider<NotificationSocket>(
  (ref) => NotificationSocket(),
);

class PushCoordinator extends Notifier<PushRuntimeState>
    with WidgetsBindingObserver {
  late final PushMessaging _messaging;
  late final NotificationSocket _socket;
  late final LiveUpdates _live;
  final List<StreamSubscription<dynamic>> _subscriptions = [];
  String? _pendingLocation;
  int? _pendingNotificationId;
  int? _accountId;
  int _sessionGeneration = 0;
  int _registrationAttempt = 0;
  bool _resumed = true;

  /// Whether the app is the focused foreground app. Stricter than [_resumed],
  /// which keeps the sockets open through an `inactive` pull of the shade: the
  /// system is asked only while the app really is resumed.
  bool _foreground = true;

  /// The permission request in flight, shared by every caller: the first-open
  /// prompt, a resume and the Profile button all ask through it, so the system
  /// is never asked twice at once.
  Future<PushPermission>? _request;

  /// Set once the first permission read has settled, so the first-open prompt
  /// never acts on a permission that has not been read yet.
  bool _messagingRestored = false;
  bool _askingOnFirstOpen = false;
  bool _askedOnFirstOpen = false;
  bool _firstOpenCheckScheduled = false;
  bool _firstOpenRetrigger = false;
  int _automaticFailures = 0;
  int? _systemRequests;

  @override
  PushRuntimeState build() {
    _messaging = ref.read(pushMessagingProvider);
    _socket = ref.read(notificationSocketProvider);
    _live = ref.read(liveUpdatesProvider);
    // Whether the app is on screen: `inactive` still is, so only `hidden`,
    // `paused` and `detached` stop the sockets.
    _resumed =
        WidgetsBinding.instance.lifecycleState == null ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
    _foreground =
        WidgetsBinding.instance.lifecycleState == null ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
    WidgetsBinding.instance.addObserver(this);
    // The first-open prompt waits for a usable screen to be on the display,
    // so it listens to where the router is rather than guessing from the
    // session alone.
    final routerDelegate = ref.read(routerProvider).routerDelegate;
    routerDelegate.addListener(_askAfterNextFrame);
    ref.onDispose(() {
      routerDelegate.removeListener(_askAfterNextFrame);
      WidgetsBinding.instance.removeObserver(this);
      for (final subscription in _subscriptions) {
        unawaited(subscription.cancel());
      }
      unawaited(_socket.stop());
    });

    _subscriptions
      ..add(_messaging.tokenRefresh.listen(_tokenRefreshed))
      ..add(_messaging.foregroundMessages.listen(_foregroundMessage))
      ..add(_messaging.openedMessages.listen(_openMessage));
    ref.listen<SessionState>(sessionProvider, (_, next) {
      _sessionChanged(next);
    }, fireImmediately: true);
    final removeAccountRefresh = _live.register(
      const LiveResource.account(),
      () => unawaited(ref.read(sessionProvider.notifier).refreshAccount()),
    );
    ref.onDispose(removeAccountRefresh);
    unawaited(_restoreMessagingState());
    return PushRuntimeState(availability: _messaging.availability);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    switch (state) {
      case AppLifecycleState.resumed:
        unawaited(_checkOnResume());
        // Back from `inactive` alone — the notification shade, the app
        // switcher, a system dialog — the app never left the screen and its
        // sockets never closed, so nothing was missed. Tearing both down and
        // redialling for that cost two handshakes and a full catch-up each
        // time the shade was pulled. An endpoint waiting out a backoff is the
        // exception: the user may have just fixed the network from the shade,
        // so it redials now rather than in up to 32 s.
        if (_resumed) {
          _socket.reconnectIdle();
          return;
        }
        _resumed = true;
        _reconcileCurrentScope();
        _startSocketsIfSignedIn();
      case AppLifecycleState.inactive:
        break;
      case AppLifecycleState.hidden:
      case AppLifecycleState.paused:
      case AppLifecycleState.detached:
        if (!_resumed) return;
        _resumed = false;
        unawaited(_socket.stop());
    }
  }

  /// Asks the operating system for notification permission. A call made while
  /// another request is in flight joins it rather than asking again.
  ///
  /// [onScreen] says whether the screen that asked is still the one on top;
  /// the dialog is requested only while it is.
  Future<PushPermission> requestPermission({bool Function()? onScreen}) =>
      _request ??= _askExplicitly(
        onScreen ?? () => true,
      ).whenComplete(() => _request = null);

  /// What the person chose to ask for, from Profile: no screen condition of
  /// the first-open prompt, because they pressed the button.
  Future<PushPermission> _askExplicitly(bool Function() onScreen) async {
    if (!await _messagingReady()) return PushPermission.unavailable;
    // On Android a request from a requestable denial follows a denial the
    // system already holds, which an app from before N1 may never have
    // counted: the count then says two, so the next denial reads as the
    // permanent one it is.
    final afterDenial =
        defaultTargetPlatform == TargetPlatform.android &&
        state.permission == PushPermission.deniedRequestable;
    // A count that cannot be written must not stop a person who asked.
    final recorded = await _recordSystemRequest(afterDenial: afterDenial);
    // The write can outlast the tap: if the app left the foreground meanwhile
    // (the shade, the switcher, another app), or the person went Back, the
    // dialog would open over something else, so it is not requested and the
    // count is taken back.
    if (!ref.mounted || !_foreground || !onScreen()) {
      if (recorded) await _releaseSystemRequest();
      return ref.mounted ? state.permission : PushPermission.unavailable;
    }
    return _askSystem(recorded: recorded);
  }

  /// Puts the question to the system. The request count has been written
  /// already; it is taken back if the system could not be reached.
  Future<PushPermission> _askSystem({required bool recorded}) async {
    final PushPermission reported;
    try {
      reported = await _messaging.requestPermission();
    } on Object {
      if (recorded) await _releaseSystemRequest();
      rethrow;
    }
    _askedOnFirstOpen = true;
    final permission = await _withHistory(reported);
    await _applyPermission(permission);
    return permission;
  }

  Future<void> refreshPermission() async =>
      _applyPermission(await _withHistory(await _messaging.permission()));

  /// Android reads a first dialog that was swiped away as a permanent denial:
  /// nothing was denied, so no rationale is offered, and the plugin reports
  /// "asked before, no rationale" as permanent. One request on record with that
  /// reading is therefore still a question the person can be asked again from
  /// Profile; a real denial reads as requestable after one request and
  /// permanent only after two. (A second swipe-away reads as permanent: Android
  /// gives no way to tell it from two denials.) A request made from a
  /// requestable denial is counted as the second (see [_askExplicitly]), so
  /// its denial is never mistaken for a first dismissal.
  Future<PushPermission> _withHistory(PushPermission reported) async {
    if (defaultTargetPlatform != TargetPlatform.android ||
        reported != PushPermission.settingsRequired) {
      return reported;
    }
    return await _systemRequestCount() == 1
        ? PushPermission.deniedRequestable
        : reported;
  }

  Future<void> _applyPermission(PushPermission permission) async {
    final granted =
        permission == PushPermission.authorized ||
        permission == PushPermission.provisional;
    // Losing permission overtakes a registration still on its way: a token
    // found after permission went away must not reach the server, nor
    // publish the phone as registered.
    if (!granted) _registrationAttempt++;
    state = state.copyWith(
      permission: permission,
      registration: granted ? state.registration : PushRegistrationState.idle,
    );
    if (granted) await _syncRegistration();
  }

  Future<void> retryRegistration() => _syncRegistration();

  /// Waits for Firebase's deferred start (K5) and says whether push can run.
  /// Until it settles every step that follows would only wait on it, and the
  /// registration gate reads `available`.
  Future<bool> _messagingReady() async {
    final messaging = _messaging;
    if (messaging is DeferredPushMessaging &&
        messaging.availability == PushAvailability.initializing) {
      await messaging.ready;
      if (!ref.mounted) return false;
      state = state.copyWith(availability: messaging.availability);
    }
    return _messaging.available;
  }

  Future<void> _restoreMessagingState() async {
    if (!await _messagingReady()) return;
    // Nothing awaits this, so an escaping exception used to be invisible: the
    // permission stayed `unavailable` for the whole app run, which closes the
    // registration gate below permanently, and the cold-start tap was lost
    // with it. Each step now fails on its own terms.
    try {
      final permission = await _withHistory(await _messaging.permission());
      state = state.copyWith(permission: permission);
    } on Object {
      state = state.copyWith(registration: PushRegistrationState.failed);
    }

    // The launch notification is read before registration is awaited. It used
    // to sit behind a full registerDevice round trip, so opening the app from
    // a notification stalled on the network before navigating.
    try {
      final initial = await _messaging.initialMessage();
      if (initial != null) _openMessage(initial);
    } on Object {
      // A lost launch message is not worth failing registration for; the
      // inbox remains the authoritative list.
    }

    // The prompt waits for neither registration nor the network: it asks as
    // soon as the permission is known and the first screen is usable.
    _messagingRestored = true;
    _askAfterNextFrame();

    final permission = state.permission;
    if (permission == PushPermission.authorized ||
        permission == PushPermission.provisional) {
      await _syncRegistration();
    }
  }

  Future<void> _checkOnResume() async {
    await refreshPermission();
    _askAfterNextFrame();
  }

  /// Looks again at whether the first-open prompt can go ahead, once the next
  /// frame has been drawn. Every trigger comes through here (the end of the
  /// startup restore, a session change, a resume, a route change): the answer
  /// depends on the screen that is *painted*, which only a finished frame
  /// settles. Calls before that frame share it.
  void _askAfterNextFrame() {
    if (_firstOpenCheckScheduled) return;
    _firstOpenCheckScheduled = true;
    final binding = WidgetsBinding.instance;
    binding.addPostFrameCallback((_) {
      _firstOpenCheckScheduled = false;
      if (ref.mounted) unawaited(_askOnFirstOpen());
    });
    binding.ensureVisualUpdate();
  }

  /// Asks for notification permission on its own, once, the first time the app
  /// is open on a usable screen: after the first frame and Firebase's start,
  /// with the session resolved to a guest or a member, with the app focused in
  /// the foreground, and with a screen painted that is neither the splash, a
  /// sign-in or payment flow, nor a notification still being opened. Signing in
  /// is not required; registering the phone to an account waits for it.
  ///
  /// The system is asked only when it can show a dialog, and never again on
  /// its own after it has been asked: not after a dismissal or a denial, which
  /// Profile recovers from. Anything that stops the dialog before it is
  /// requested (the person leaves the app, a sign-in opens, the call fails)
  /// takes the count back and leaves the prompt pending for the next trigger.
  /// A start that never became available asks nothing and spends nothing.
  Future<void> _askOnFirstOpen() async {
    if (_askingOnFirstOpen) {
      // A trigger that lands while one is being decided is looked at again
      // once that one has finished, so a screen change is never lost.
      _firstOpenRetrigger = true;
      return;
    }
    if (!_canAskOnFirstOpen()) return;
    _askingOnFirstOpen = true;
    try {
      if (await _androidAskedBefore()) return;
      // Let the screen that made this possible reach the display: a screen
      // still sliding out (sign-in after its pop) is not yet gone.
      // The animation ending is not the screen leaving: the navigator drops the
      // route in the frame after, so each wait is followed by a frame.
      final transitions = ref.read(routeTransitionTrackerProvider);
      do {
        await transitions.settled;
        await SchedulerBinding.instance.endOfFrame;
      } while (!transitions.idle);
      if (!_canAskOnFirstOpen(settled: true)) return;
      // The prompt needs a count that is on disk before the system is asked:
      // without one a dialog shown and swiped away would be asked again at the
      // next launch.
      if (!await _recordSystemRequest()) {
        _automaticFailures++;
        return;
      }
      // The write above can outlast the person's stay on this screen. The
      // check and the request below follow each other with nothing between.
      if (!_canAskOnFirstOpen(settled: true)) {
        await _releaseSystemRequest();
        return;
      }
      await (_request = _askSystem(
        recorded: true,
      ).whenComplete(() => _request = null));
    } on Object {
      // A failed first prompt is not worth failing anything for: the count was
      // taken back, the next trigger tries again (twice at most), and Profile
      // offers the same request.
      _automaticFailures++;
    } finally {
      _askingOnFirstOpen = false;
      if (_firstOpenRetrigger) {
        _firstOpenRetrigger = false;
        _askAfterNextFrame();
      }
    }
  }

  /// Whether the prompt may go ahead. With [settled] it also requires that no
  /// screen is still sliding in or out: the first look at a trigger does not,
  /// because it is the one that goes on to wait for the transition.
  bool _canAskOnFirstOpen({bool settled = false}) =>
      ref.mounted &&
      !_askedOnFirstOpen &&
      _automaticFailures < _automaticPromptFailuresAllowed &&
      _messagingRestored &&
      _messaging.available &&
      _foreground &&
      _request == null &&
      _pendingLocation == null &&
      ref.read(sessionProvider) is! SessionRestoring &&
      (!settled || ref.read(routeTransitionTrackerProvider).idle) &&
      _onUsableScreen &&
      // Only a question never put. A requestable denial is a person's answer,
      // and on Android it is also what an app that asked before N1 reports
      // after an upgrade, with no count on this installation to say so.
      state.permission == PushPermission.notDetermined;

  /// Whether a screen the person can use is the one on display. The router
  /// reports the top of its stack, pushed routes included.
  bool get _onUsableScreen {
    final router = ref.read(routerProvider);
    if (router.routerDelegate.currentConfiguration.isEmpty) return false;
    final location = _currentLocation(router);
    final path = Uri.tryParse(location)?.path ?? location;
    return path != '/splash' &&
        !path.startsWith('/auth/') &&
        !path.startsWith('/guest/pay/');
  }

  /// Android reports a permission it was never asked for as a requestable
  /// denial or as undetermined, and reports the same again after the app was
  /// killed with its dialog open or after a dismissal; only this installation's
  /// own history says whether it has asked. iOS keeps its keychain across a
  /// reinstall but resets the permission, and its status is exact, so history
  /// never blocks it.
  Future<bool> _androidAskedBefore() async =>
      defaultTargetPlatform == TargetPlatform.android &&
      await _systemRequestCount() != 0;

  Future<int?> _systemRequestCount() async {
    if (_systemRequests != null) return _systemRequests;
    try {
      return _systemRequests = await ref
          .read(tokenStoreProvider)
          .readPushPermissionRequests();
    } on Object {
      return null;
    }
  }

  /// Writes the request count ahead of the system call, and says whether it
  /// reached the disk. The write is the last step before the native request, so
  /// the window in which a dialog is counted but not yet shown is as short as it
  /// can be; an app killed inside it counts a prompt that never appeared, which
  /// is the safe side (Profile still asks on request).
  Future<bool> _recordSystemRequest({bool afterDenial = false}) async {
    try {
      _systemRequests = await ref
          .read(tokenStoreProvider)
          .recordPushPermissionRequest(afterDenial: afterDenial);
      return true;
    } on Object {
      return false;
    }
  }

  Future<void> _releaseSystemRequest() async {
    try {
      _systemRequests = await ref
          .read(tokenStoreProvider)
          .releasePushPermissionRequest();
    } on Object {
      // Left counted: a prompt that is skipped is safer than one shown twice.
    }
  }

  void _sessionChanged(SessionState session) {
    if (session is! SessionRestoring) _askAfterNextFrame();
    final previousAccountId = _accountId;
    final nextAccountId = switch (session) {
      SessionSignedIn(:final account) => account.id,
      _ => null,
    };
    if (nextAccountId == _accountId) {
      if (session is! SessionRestoring) _openPendingIfReady();
      return;
    }

    _accountId = nextAccountId;
    _sessionGeneration++;
    _live.bindAccount(nextAccountId);
    unawaited(_socket.stop());
    if (session is SessionSignedIn) {
      _startSocketsIfSignedIn();
      final generation = _sessionGeneration;
      scheduleMicrotask(() {
        if (generation != _sessionGeneration) return;
        if (previousAccountId != null) {
          state = state.copyWith(registration: PushRegistrationState.idle);
        }
        unawaited(_syncRegistration(expectedGeneration: generation));
      });
      _openPendingIfReady();
    } else if (session is SessionSignedOut) {
      scheduleMicrotask(() {
        if (nextAccountId == _accountId) {
          state = state.copyWith(registration: PushRegistrationState.idle);
        }
      });
      _openPendingIfReady();
    }
  }

  void _startSocketsIfSignedIn() {
    if (!_resumed || ref.read(sessionProvider) is! SessionSignedIn) return;
    final generation = _sessionGeneration;
    unawaited(
      _socket.start(
        accessToken: _socketAccessToken,
        onEvent: (event, _) {
          if (generation != _sessionGeneration) return;
          _live.ingest(event, source: LiveEventSource.websocket);
        },
        onConnected: (_) {
          if (generation != _sessionGeneration) return;
          _reconcileCurrentScope();
        },
      ),
    );
  }

  Future<String?> _socketAccessToken({required bool refresh}) async {
    final session = ref.read(sessionProvider);
    if (session is! SessionSignedIn) return null;
    // A normal authenticated read of the account enters the same 401 and
    // single-flight refresh as every screen. It refreshes an expired access
    // token and ends a sign-in the server refused instead of looping a
    // rejected WS bearer forever.
    if (refresh &&
        !await ref.read(sessionProvider.notifier).refreshAccount()) {
      return null;
    }
    return ref.read(sessionCoreProvider).accessFor(session.sid);
  }

  void _reconcileCurrentScope() {
    final router = ref.read(routerProvider);
    _live.reconcileScope(liveResourcesForLocation(_currentLocation(router)));
  }

  /// The location actually on screen, including imperatively pushed routes.
  ///
  /// Every in-app detail route is reached with `pushNamed`, and go_router keeps
  /// the *base* uri across a push: `RouteMatchList.copyWith` carries the old
  /// uri forward, so `currentConfiguration.uri` still reads `/chat` while
  /// `/chat/thread/7` is on screen. Reconciling that base location resolved to
  /// no resources at all, which is why an open conversation — and every other
  /// pushed detail screen — got no catch-up on resume or on socket reconnect,
  /// and had to be left and reopened before a missed message appeared.
  static String _currentLocation(GoRouter router) {
    final configuration = router.routerDelegate.currentConfiguration;
    if (configuration.matches.isEmpty) return configuration.uri.toString();
    final matched = configuration.last.matchedLocation;
    return matched.isEmpty ? configuration.uri.toString() : matched;
  }

  Future<void> _syncRegistration({
    int? expectedGeneration,
    bool force = false,
    bool retried = false,
    String? refreshedToken,
  }) async {
    final generation = expectedGeneration ?? _sessionGeneration;
    if (generation != _sessionGeneration ||
        !_messaging.available ||
        (state.permission != PushPermission.authorized &&
            state.permission != PushPermission.provisional) ||
        ref.read(sessionProvider) is! SessionSignedIn) {
      return;
    }
    if (!force &&
        (state.registration == PushRegistrationState.pending ||
            state.registration == PushRegistrationState.registered)) {
      return;
    }
    state = state.copyWith(registration: PushRegistrationState.pending);
    final attempt = ++_registrationAttempt;
    // Whether this attempt was overtaken, checked after every wait: by another
    // account (or none), or by a newer attempt of the same one, such as a token
    // refresh. Only the newest attempt may number itself, reach the server, or
    // settle the state, so an older token found late is never sent above a
    // newer one, and an older outcome never hides a newer one.
    bool overtaken() =>
        !ref.mounted ||
        generation != _sessionGeneration ||
        attempt != _registrationAttempt ||
        ref.read(sessionProvider) is! SessionSignedIn;
    final store = ref.read(tokenStoreProvider);
    try {
      final current = refreshedToken ?? await _messaging.token();
      if (overtaken()) return;
      final token = current ?? await store.readPendingPushToken();
      if (overtaken()) return;
      if (token == null || token.isEmpty) {
        state = state.copyWith(registration: PushRegistrationState.failed);
        return;
      }
      final installationId = await store.readOrCreateInstallationId();
      if (overtaken()) return;
      // Numbered as late as possible: a sign-out or a later registration takes
      // a higher number, and the server then refuses this one if it arrives
      // after them.
      final bindingSequence = await store.nextPushBindingSequence();
      if (overtaken()) return;
      final active = await ref
          .read(pushRepositoryProvider)
          .registerDevice(
            token: token,
            installationId: installationId,
            bindingSequence: bindingSequence,
            platform: defaultTargetPlatform == TargetPlatform.iOS
                ? 'ios'
                : 'android',
            appVersion: '',
          );
      if (overtaken()) return;
      if (!active) {
        // The server kept the phone switched off: the token stays pending,
        // and Retry or the next resume registers it again.
        state = state.copyWith(registration: PushRegistrationState.failed);
        return;
      }
      try {
        await store.writePendingPushToken(null);
      } on Object {
        // The server has the token; a copy left on disk only stands in for a
        // token Firebase cannot hand over, and the next success clears it.
      }
      if (overtaken()) return;
      state = state.copyWith(registration: PushRegistrationState.registered);
    } on ApiException catch (error) {
      if (overtaken()) return;
      final newest = error.code.raw == _registrationSuperseded
          ? (error.extras['current_sequence'] as num?)?.toInt()
          : null;
      if (newest != null && !retried) {
        // A later registration or sign-out was applied first. This is the
        // latest attempt of the phone, so its own counter was behind the
        // server's: it catches up and the registration goes again, with a
        // higher number. A counter that cannot be written leaves a failure
        // the Retry button and the next resume recover from.
        try {
          await store.raisePushBindingSequence(newest);
        } on Object {
          if (!overtaken()) {
            state = state.copyWith(registration: PushRegistrationState.failed);
          }
          return;
        }
        if (overtaken()) return;
        return _syncRegistration(
          expectedGeneration: generation,
          force: true,
          retried: true,
        );
      }
      state = state.copyWith(registration: PushRegistrationState.failed);
    } on Object {
      if (overtaken()) return;
      state = state.copyWith(registration: PushRegistrationState.failed);
    }
  }

  /// Firebase replaced the token. The registration still on its way with the
  /// old one is overtaken at once, and the new token is sent as it came: it is
  /// also kept on disk for a registration that fails, but a keystore that
  /// refuses the write must not leave the server holding the old token.
  Future<void> _tokenRefreshed(String token) async {
    _registrationAttempt++;
    final generation = _sessionGeneration;
    try {
      await ref.read(tokenStoreProvider).writePendingPushToken(token);
    } on Object {
      // Sent below all the same; only a later retry would need the copy.
    }
    if (!ref.mounted) return;
    if (generation == _sessionGeneration &&
        ref.read(sessionProvider) is SessionSignedIn) {
      await _syncRegistration(
        expectedGeneration: generation,
        force: true,
        refreshedToken: token,
      );
    }
  }

  void _foregroundMessage(PushMessage message) {
    _live.ingest(message.data, source: LiveEventSource.firebase);
  }

  void _openMessage(PushMessage message) {
    _live.ingest(message.data, source: LiveEventSource.firebase);
    final location = pushLocation(message.data);
    if (location == null) return;
    _pendingLocation = location;
    final notificationId = int.tryParse(message.data['notification_id'] ?? '');
    if (notificationId != null && notificationId > 0) {
      _pendingNotificationId = notificationId;
    }
    _openPendingIfReady();
  }

  void _openPendingIfReady() {
    final location = _pendingLocation;
    if (location == null) return;
    final session = ref.read(sessionProvider);
    if (session is SessionRestoring) return;
    final router = ref.read(routerProvider);
    if (session is SessionSignedOut) {
      router.go(
        Uri(
          path: '/auth/sign-in',
          queryParameters: {'next': location},
        ).toString(),
      );
      return;
    }
    if (session is SessionSignedIn) {
      _pendingLocation = null;
      final notificationId = _pendingNotificationId;
      _pendingNotificationId = null;
      router.go(location);
      if (notificationId != null) {
        unawaited(
          ref
              .read(notificationRepositoryProvider)
              .markRead(notificationId)
              // Opening from a push marked the row read and then refreshed
              // nothing, so the bell and the inbox kept counting it. Reconcile
              // the scope we just navigated to, which re-reads the badge, the
              // inbox and the destination itself.
              .then((_) => _reconcileCurrentScope())
              .catchError((Object _) {}),
        );
      }
    }
  }
}

String? pushLocation(Map<String, String> data) {
  int? positive(String key) {
    final value = int.tryParse(data[key] ?? '');
    return value != null && value > 0 ? value : null;
  }

  final channel = data['channel'] ?? '';
  final matchId = positive('match_id');
  if (channel == 'chat.message.new' && matchId != null) {
    return '/chat/thread/$matchId';
  }
  if (channel == 'discovery.route_alert') return _routeAlertLocation(data);
  if (channel == 'discovery.traveler_interested') {
    // The sender's own request, with the traveler's trip in focus.
    final requestId = positive('request_id');
    final journeyId = positive('journey_id');
    if (requestId == null) return '/notifications';
    return journeyId == null
        ? '/requests/$requestId'
        : '/requests/$requestId/discovery?journey=$journeyId';
  }
  if (channel == 'discovery.request_fits_trip') {
    // A parcel for the traveler's own trip: its preview, trip in focus.
    final requestId = positive('request_id');
    final journeyId = positive('journey_id');
    if (requestId == null || journeyId == null) return '/notifications';
    return Uri(
      path: '/discover/requests',
      queryParameters: {'focus': '$requestId', 'journey': '$journeyId'},
    ).toString();
  }
  if (channel == 'journey.schedule_change_proposed') {
    // A sender is asked: straight to the answer. The traveler's copy of the
    // channel carries no delivery and opens their journey.
    final dealId = positive('deal_id');
    if (dealId != null) return '/deals/$dealId/schedule-change';
  }
  if (channel == 'journey.leg_reminder') {
    // The traveler's own journey, with the question for that leg. A payload
    // missing the leg or the step still opens the journey.
    final journeyId = positive('journey_id');
    if (journeyId == null) return '/notifications';
    final leg = positive('leg_id');
    final ask = ProgressKind.parse(data['progress_kind']);
    return leg == null || ask == null
        ? '/journeys/$journeyId'
        : '/journeys/$journeyId?leg=$leg&ask=${ask.wire}';
  }
  final disputeId = positive('dispute_id');
  if (disputeId != null) return '/disputes/$disputeId';
  if (channel == 'payout.status_changed') {
    final payoutRef = data['payout_reference']?.trim();
    if (payoutRef != null && payoutRef.isNotEmpty) {
      return '/payouts/$payoutRef';
    }
    final event = data['event']?.trim();
    if (event == 'profile_ready' || event == 'profile_needs_attention') {
      return '/profile/payout-methods';
    }
    final dealId = positive('deal_id');
    if (dealId != null) return '/deals/$dealId';
    return '/profile/payouts';
  }
  final dealId = positive('deal_id');
  if (dealId != null) return '/deals/$dealId';
  // An open negotiation belongs on the negotiation screen. These payloads are
  // built from `match_resources`, so they also carry the traveler's
  // `journey_id` for live invalidation — which the generic ladder below would
  // otherwise treat as the destination and send the sender to a journey they
  // may not even be allowed to read. `offer.accepted` is deliberately not
  // here: it has a `deal_id` and was already answered above.
  if (channel.startsWith('offer.') && matchId != null) {
    return '/matches/$matchId';
  }
  final journeyId = positive('journey_id') ?? positive('trip_id');
  if (journeyId != null) return '/journeys/$journeyId';
  final requestId = positive('request_id') ?? positive('parcel_id');
  if (requestId != null) return '/requests/$requestId';
  if (matchId != null) return '/matches/$matchId';
  if (channel == 'kyc.status_changed') return '/kyc';
  if (channel.startsWith('payment.') || channel.startsWith('payout.')) {
    return '/profile/payouts';
  }
  return channel.isEmpty ? null : '/notifications';
}

/// A route alert opens Browse on the alert's own route and focuses the trip or
/// request that triggered it. Without either id the member's alert list opens:
/// there is nothing to focus, and `journey_id` here is somebody else's trip,
/// which the generic ladder would wrongly open as the member's own journey.
String _routeAlertLocation(Map<String, String> data) {
  int? positive(String key) {
    final value = int.tryParse(data[key] ?? '');
    return value != null && value > 0 ? value : null;
  }

  final alertId = positive('alert_id');
  final journeyId = positive('journey_id');
  final requestId = positive('request_id');
  final (path, focus) = journeyId != null
      ? ('/discover/trips', journeyId)
      : requestId != null
      ? ('/discover/requests', requestId)
      : ('/profile/alerts', null);
  if (focus == null) return path;
  return Uri(
    path: path,
    queryParameters: {
      if (alertId != null) 'alert': '$alertId',
      'focus': '$focus',
    },
  ).toString();
}
