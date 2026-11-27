/// N1: what a person can do about notifications without an account, and how
/// the phone's registration keeps its place when the server has seen more.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/push/push_messaging.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/token_store.dart';
import 'package:shiptrip/data/auth_repository.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/features/profile/notification_settings_screen.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';

import 'support/fake_api.dart';
import 'support/push_router.dart';

class _Store extends FakeTokenStore {
  _Store({super.refresh});

  /// Every change of the pending token, in order.
  final List<String?> pendingWrites = [];

  /// While set, numbering a registration or a sign-out fails.
  bool countFails = false;

  /// While set, counting a permission request waits for it.
  Completer<void>? recordGate;

  @override
  Future<int> recordPushPermissionRequest({bool afterDenial = false}) async {
    final count = await super.recordPushPermissionRequest(
      afterDenial: afterDenial,
    );
    await recordGate?.future;
    return count;
  }

  /// While set, catching the counter up to the server's number fails.
  bool raiseFails = false;

  /// While set, catching the counter up waits for it.
  Completer<void>? raiseGate;

  @override
  Future<String> readOrCreateInstallationId() async =>
      'ca7eedc0-1665-4bbd-bfae-45f841beb8d7';

  @override
  Future<int> nextPushBindingSequence() async {
    if (countFails) throw StateError('keystore refused the write');
    return super.nextPushBindingSequence();
  }

  @override
  Future<void> raisePushBindingSequence(int sequence) async {
    await raiseGate?.future;
    if (raiseFails) throw StateError('keystore refused the write');
    return super.raisePushBindingSequence(sequence);
  }

  @override
  Future<String?> readPendingPushToken() async => null;

  @override
  Future<void> writePendingPushToken(String? token) async =>
      pendingWrites.add(token);
}

class _Messaging implements PushMessaging {
  _Messaging({this.currentPermission = PushPermission.notDetermined});

  /// Where a test makes Firebase hand over a refreshed token.
  final refreshes = StreamController<String>.broadcast();

  PushPermission currentPermission;
  PushPermission requestResult = PushPermission.authorized;
  int requests = 0;

  @override
  bool get available => true;
  @override
  PushAvailability get availability => PushAvailability.available;
  @override
  Stream<PushMessage> get foregroundMessages => const Stream.empty();
  @override
  Stream<PushMessage> get openedMessages => const Stream.empty();
  @override
  Stream<String> get tokenRefresh => refreshes.stream;
  @override
  Future<PushMessage?> initialMessage() async => null;
  @override
  Future<PushPermission> permission() async => currentPermission;
  @override
  Future<PushPermission> requestPermission() async {
    requests++;
    return currentPermission = requestResult;
  }

  /// Answers for the next token lookups, in order; then [currentToken].
  final List<Future<String?>> tokenAnswers = [];
  String currentToken = 'fcm-token';

  @override
  Future<String?> token() async =>
      tokenAnswers.isEmpty ? currentToken : tokenAnswers.removeAt(0);
}

class _NoopSocket extends NotificationSocket {
  @override
  Future<void> start({
    required NotificationSocketToken accessToken,
    required NotificationSocketEvent onEvent,
    required NotificationSocketConnected onConnected,
  }) async {}

  @override
  Future<void> stop() async {}
}

class _Member extends SessionController {
  @override
  SessionState build() => SessionSignedIn(Account.fromJson(meFixture()));

  /// Another account takes the phone.
  void become(int id) =>
      state = SessionSignedIn(Account.fromJson(meFixture(id: id)));
}

Future<void> _settle(WidgetTester tester, [int frames = 10]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  group('without an account', () {
    Future<(ProviderContainer, FakeBackend, _Messaging)> openGuestProfile(
      WidgetTester tester,
      _Messaging push, {
      _Store? tokens,
    }) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(360, 800);
      addTearDown(tester.view.reset);
      final backend = FakeBackend()..emptyDiscovery();
      tokens ??= _Store(refresh: null);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            tokenStoreProvider.overrideWithValue(tokens),
            apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
            notificationSocketProvider.overrideWithValue(_NoopSocket()),
            pushMessagingProvider.overrideWithValue(push),
          ],
          child: const ShipTripApp(),
        ),
      );
      final container = ProviderScope.containerOf(
        tester.element(find.byType(ShipTripApp)),
      );
      await _settle(tester);
      await tester.tap(find.text('Profile'));
      await _settle(tester);
      return (container, backend, push);
    }

    testWidgets('guest Profile offers the notification controls, and a refusal '
        'is recoverable from there', (tester) async {
      final push = _Messaging()
        ..requestResult = PushPermission.deniedRequestable;
      final (container, backend, _) = await openGuestProfile(tester, push);
      expect(push.requests, 1, reason: 'asked once on the guest front page');
      expect(find.byType(ProfileScreen), findsOneWidget);

      await tester.tap(find.text('Notifications'));
      await _settle(tester);

      expect(container.read(sessionProvider), isA<SessionSignedOut>());
      expect(find.byType(NotificationSettingsScreen), findsOneWidget);
      expect(find.textContaining('still off'), findsOneWidget);
      expect(
        find.text('Enable notifications'),
        findsOneWidget,
        reason: 'a guest can ask again',
      );
      expect(find.textContaining('Sign in to receive'), findsOneWidget);
      expect(
        backend.to('GET', '/api/notifications/preferences'),
        isEmpty,
        reason: 'account preferences load after sign-in',
      );

      push.requestResult = PushPermission.authorized;
      await tester.tap(find.text('Enable notifications'));
      await _settle(tester);

      expect(push.requests, 2);
      expect(
        find.textContaining('Sign in and Wassla will start'),
        findsOneWidget,
      );
      expect(
        backend.to('POST', '/api/notifications/devices'),
        isEmpty,
        reason: 'the phone registers to an account at sign-in',
      );
    });
    // Astra round 3, should-fix 3: the Profile button checked the foreground
    // after the count write, but not that Notifications was still on screen.
    testWidgets('Back pressed while the request is being counted opens no '
        'dialog over the previous screen', (tester) async {
      final push = _Messaging(
        currentPermission: PushPermission.deniedRequestable,
      );
      final tokens = _Store(refresh: null);
      final (container, _, _) = await openGuestProfile(
        tester,
        push,
        tokens: tokens,
      );
      expect(
        push.requests,
        0,
        reason: 'a requestable denial is not auto-asked',
      );
      await tester.tap(find.text('Notifications'));
      await _settle(tester);

      tokens.recordGate = Completer<void>();
      await tester.tap(find.text('Enable notifications'));
      await _settle(tester, 2);
      await tester.pageBack();
      await _settle(tester);
      expect(find.byType(NotificationSettingsScreen), findsNothing);
      tokens.recordGate!.complete();
      tokens.recordGate = null;
      await _settle(tester);

      expect(push.requests, 0, reason: 'the person left the screen');
      expect(
        await tokens.readPushPermissionRequests(),
        1,
        reason: 'this request is taken back; the earlier denial stays counted',
      );
      expect(
        container.read(pushCoordinatorProvider).permission,
        PushPermission.deniedRequestable,
      );

      // Back on the screen, the button asks.
      await tester.tap(find.text('Notifications'));
      await _settle(tester);
      await tester.tap(find.text('Enable notifications'));
      await _settle(tester);
      expect(push.requests, 1);
    });

    testWidgets('a guest who refused is not promised the inbox', (
      tester,
    ) async {
      final push = _Messaging()
        ..requestResult = PushPermission.deniedRequestable;
      await openGuestProfile(tester, push);
      await tester.tap(find.text('Notifications'));
      await _settle(tester);

      expect(find.textContaining('still off'), findsOneWidget);
      expect(find.textContaining('inbox'), findsNothing);
    });
  });

  group('the registration number', () {
    Future<ProviderContainer> member(
      WidgetTester tester,
      FakeBackend backend,
      FakeTokenStore tokens, {
      _Messaging? messaging,
    }) async {
      final router = pushTestRouter();
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
          sessionProvider.overrideWith(_Member.new),
          routerProvider.overrideWithValue(router),
          notificationSocketProvider.overrideWithValue(_NoopSocket()),
          pushMessagingProvider.overrideWithValue(
            messaging ??
                _Messaging(currentPermission: PushPermission.authorized),
          ),
        ],
      );
      addTearDown(() {
        container.dispose();
        router.dispose();
      });
      await mountRouter(tester, container, router);
      return container;
    }

    testWidgets(
      'signing out takes a number above the registration it follows',
      (tester) async {
        final backend = FakeBackend()
          ..on(
            'POST',
            '/api/notifications/devices',
            const FakeResponse(201, {'id': 3, 'active': true}),
          )
          ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
        final tokens = _Store();
        final container = await member(tester, backend, tokens);
        container.read(pushCoordinatorProvider);
        await _settle(tester);

        unawaited(
          AuthRepository(apiClientFor(backend, tokens), tokens).signOut(),
        );
        await _settle(tester);

        expect(
          backend
              .lastTo('POST', '/api/notifications/devices')
              ?.body['binding_sequence'],
          1,
        );
        expect(
          backend
              .lastTo('POST', '/api/auth/sign-out')
              ?.body['binding_sequence'],
          2,
        );
      },
    );

    testWidgets('a phone that fell behind the server catches up and registers '
        'once more', (tester) async {
      var attempts = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) {
          attempts++;
          return attempts == 1
              ? const FakeResponse(409, {
                  'code': 'push_registration_superseded',
                  'detail': 'newer',
                  'current_sequence': 40,
                })
              : const FakeResponse(200, {'id': 3, 'active': true});
        });
      final container = await member(tester, backend, _Store());
      container.read(pushCoordinatorProvider);
      await _settle(tester);

      final sent = backend.to('POST', '/api/notifications/devices');
      expect([for (final r in sent) r.body['binding_sequence']], [1, 41]);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );
    });

    testWidgets('a registration the server keeps refusing as old stops after '
        'one more try', (tester) async {
      final backend = FakeBackend()
        ..on(
          'POST',
          '/api/notifications/devices',
          const FakeResponse(409, {
            'code': 'push_registration_superseded',
            'detail': 'newer',
            'current_sequence': 40,
          }),
        );
      final container = await member(tester, backend, _Store());
      container.read(pushCoordinatorProvider);
      await _settle(tester);

      expect(backend.to('POST', '/api/notifications/devices'), hasLength(2));
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.failed,
        reason: 'the Retry button is the way back',
      );
    });

    testWidgets('an older request failing after a newer one registered does '
        'not undo it', (tester) async {
      final olderAnswer = Completer<void>();
      var calls = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) async {
          if (++calls == 1) {
            await olderAnswer.future;
            return const FakeResponse(500, {'detail': 'server error'});
          }
          return const FakeResponse(200, {'id': 3, 'active': true});
        });
      final tokens = _Store();
      final messaging = _Messaging(
        currentPermission: PushPermission.authorized,
      );
      final container = await member(
        tester,
        backend,
        tokens,
        messaging: messaging,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester);
      expect(calls, 1, reason: 'the first registration is still in flight');

      messaging.refreshes.add('fcm-token-2');
      await _settle(tester);
      expect(calls, 2);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );

      olderAnswer.complete();
      await _settle(tester);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
        reason: 'the older failure arrives after the newer success',
      );
    });

    testWidgets('an older success arriving after a newer failure neither '
        'hides it nor consumes the pending token', (tester) async {
      final olderAnswer = Completer<void>();
      var calls = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) async {
          if (++calls == 1) {
            await olderAnswer.future;
            return const FakeResponse(200, {'id': 3, 'active': true});
          }
          return const FakeResponse(500, {'detail': 'server error'});
        });
      final tokens = _Store();
      final messaging = _Messaging(
        currentPermission: PushPermission.authorized,
      );
      final container = await member(
        tester,
        backend,
        tokens,
        messaging: messaging,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester);

      messaging.refreshes.add('fcm-token-2');
      await _settle(tester);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.failed,
      );
      final writesBefore = tokens.pendingWrites.length;

      olderAnswer.complete();
      await _settle(tester);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.failed,
        reason: 'the current token is not registered: Retry must stay',
      );
      expect(
        tokens.pendingWrites.skip(writesBefore),
        isEmpty,
        reason: 'the pending token is still needed',
      );
    });

    // Astra round 3, should-fix 1: the newest-attempt check covered the
    // server's answers only, so an older token lookup finishing late could
    // still number itself above the refresh and send the obsolete token.
    testWidgets('an older token lookup finishing after a refresh registration '
        'is never sent', (tester) async {
      final backend = FakeBackend()
        ..on(
          'POST',
          '/api/notifications/devices',
          const FakeResponse(200, {'id': 3, 'active': true}),
        );
      final oldLookup = Completer<String?>();
      final messaging = _Messaging(currentPermission: PushPermission.authorized)
        ..tokenAnswers.add(oldLookup.future);
      final container = await member(
        tester,
        backend,
        _Store(),
        messaging: messaging,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester);
      expect(backend.to('POST', '/api/notifications/devices'), isEmpty);

      messaging.currentToken = 'fcm-token-new';
      messaging.refreshes.add('fcm-token-new');
      await _settle(tester);
      oldLookup.complete('fcm-token-old');
      await _settle(tester);

      final sent = backend.to('POST', '/api/notifications/devices');
      expect([for (final r in sent) r.body['token']], ['fcm-token-new']);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );
    });

    testWidgets('an older lookup that finds no token does not report a '
        'failure over a newer registration', (tester) async {
      final backend = FakeBackend()
        ..on(
          'POST',
          '/api/notifications/devices',
          const FakeResponse(200, {'id': 3, 'active': true}),
        );
      final oldLookup = Completer<String?>();
      final messaging = _Messaging(currentPermission: PushPermission.authorized)
        ..tokenAnswers.add(oldLookup.future);
      final container = await member(
        tester,
        backend,
        _Store(),
        messaging: messaging,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester);

      messaging.refreshes.add('fcm-token');
      await _settle(tester);
      oldLookup.complete(null);
      await _settle(tester);

      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );
    });

    // Astra round 3, should-fix 2: a counter write failing during the catch-up
    // escaped with the registration still pending, which Resume and Retry
    // both skip.
    testWidgets('a counter that cannot catch up leaves a failure Retry '
        'recovers from', (tester) async {
      var attempts = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) {
          attempts++;
          return attempts == 1
              ? const FakeResponse(409, {
                  'code': 'push_registration_superseded',
                  'detail': 'newer',
                  'current_sequence': 40,
                })
              : const FakeResponse(200, {'id': 3, 'active': true});
        });
      final tokens = _Store()..raiseFails = true;
      final container = await member(tester, backend, tokens);
      container.read(pushCoordinatorProvider);
      await _settle(tester);

      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.failed,
      );
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(1));

      tokens.raiseFails = false;
      unawaited(
        container.read(pushCoordinatorProvider.notifier).retryRegistration(),
      );
      await _settle(tester);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );
    });

    testWidgets('a catch-up overtaken by another account leaves that '
        "account's registration alone", (tester) async {
      var attempts = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) {
          attempts++;
          return attempts == 1
              ? const FakeResponse(409, {
                  'code': 'push_registration_superseded',
                  'detail': 'newer',
                  'current_sequence': 40,
                })
              : const FakeResponse(200, {'id': 3, 'active': true});
        });
      final tokens = _Store()..raiseGate = Completer<void>();
      final container = await member(tester, backend, tokens);
      container.read(pushCoordinatorProvider);
      await _settle(tester);
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(1));

      // While the counter catches up, the other account signs in, and its own
      // registration waits on the same keystore queue.
      (container.read(sessionProvider.notifier) as _Member).become(77);
      await _settle(tester);
      tokens.raiseGate!.complete();
      tokens.raiseGate = null;
      await _settle(tester);

      final sent = backend.to('POST', '/api/notifications/devices');
      expect(
        sent,
        hasLength(2),
        reason: "only the new account's registration follows",
      );
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );
    });
  });

  group('signing out and the phone identity', () {
    testWidgets('a counter that cannot be written still ends the sign-in on '
        'the server', (tester) async {
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      final tokens = _Store()..countFails = true;

      unawaited(
        AuthRepository(apiClientFor(backend, tokens), tokens).signOut(),
      );
      await _settle(tester);

      final sent = backend.lastTo('POST', '/api/auth/sign-out');
      expect(sent, isNotNull, reason: 'the refresh token is revoked');
      expect(sent!.body['refresh'], 'refresh-token');
      expect(sent.body['installation_id'], isNotEmpty);
      expect(sent.body.containsKey('binding_sequence'), isFalse);
    });

    test(
      'two registrations starting together share one installation ID',
      () async {
        FlutterSecureStorage.setMockInitialValues({});
        final store = TokenStore(const FlutterSecureStorage());

        // A startup registration and a token-refresh registration, both on a
        // phone that has never registered.
        final both = await Future.wait([
          for (var i = 0; i < 2; i++)
            () async {
              final id = await store.readOrCreateInstallationId();
              final sequence = await store.nextPushBindingSequence();
              return (id, sequence);
            }(),
        ]);

        expect(both[0].$1, both[1].$1, reason: 'one phone, one identity');
        expect({both[0].$2, both[1].$2}, {1, 2});
        expect(await store.readOrCreateInstallationId(), both[0].$1);
      },
    );
  });
}
