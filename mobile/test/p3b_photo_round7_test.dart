/// P3B, round seven: one identity per action.
///
/// Every round of the review found another way for an action of member A to
/// land on member B while one replaces the other. The cause was always the same:
/// an action read "who am I" more than once, from places that move at different
/// moments (the published account, the token store's generation, the bearer in
/// storage). Now `SessionNotifier.beginAction` captures one `MemberScope`
/// (account, authentication, credentials) when an action starts, the action
/// carries it, and `isCurrent` is asked once when it commits.
///
/// * **The interval between B's credentials being saved and B being published**
///   (role-context storage held) is exercised for every action that can begin
///   there: a pick, a removal, a profile refresh (and its snapshot write), a
///   profile update.
/// * **A confirmation dialog belongs to the member it was opened over.**
/// * **A second window of the app** (another task, its own token store) cannot
///   send a member's photo write under another member's bearer.
/// * **Failed or overtaken transitions leave the app usable.**
///
/// Everything that waits on a held write or file runs on real time inside
/// `runAsync`, with completers made there.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart' show AlertDialog;
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/profile_photo_state.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/bearer_account.dart';
import 'package:shiptrip/core/media/pick_guard.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/communication_language.dart';

import 'support/fake_api.dart';
import 'support/fake_image_picker.dart';
import 'support/photo_cache.dart';
import 'support/photo_rig.dart';

const _put = photoPut;
const _launchChannel = MethodChannel('wassla/pick_launch');

Future<void> _until(bool Function() condition) async {
  for (var i = 0; i < 300; i++) {
    if (condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  throw StateError('never reached the state the test waited for');
}

Future<Completer<T>> _gate<T>(WidgetTester tester) async =>
    (await tester.runAsync(() async => Completer<T>()))!;

FakeResponse _signInAs(int id, String name, {Map<String, dynamic>? photo}) =>
    FakeResponse(200, {
      'access': 'access-$id',
      'refresh': 'refresh-$id',
      'user': {...meFixture(photo: photo), 'id': id, 'full_name': name},
    });

/// A keystore whose role-context write (the step between B's credentials being
/// saved and B being published) can be held.
class _RoleHeldStore extends FakeTokenStore {
  _RoleHeldStore(this.reached);

  /// Made by the test inside `runAsync`, so that it completes on real time.
  final Completer<void> reached;
  Completer<void>? hold;

  @override
  Future<void> writeRoleContext(String value) async {
    final gate = hold;
    if (gate != null) {
      if (!reached.isCompleted) reached.complete();
      await gate.future;
    }
    await super.writeRoleContext(value);
  }
}

/// A keystore whose bearer another window can replace.
class _SharedBearerStore extends FakeTokenStore {
  String? access;

  @override
  Future<String?> readAccess() async => access ?? await super.readAccess();
}

String _jwtFor(int account) {
  String part(Object value) =>
      base64Url.encode(utf8.encode(jsonEncode(value))).replaceAll('=', '');
  return '${part({'alg': 'none'})}.${part({'user_id': account})}.sig';
}

class _Switching {
  _Switching({
    required this.rig,
    required this.store,
    required this.backend,
    required this.picker,
    required this.release,
    required this.signIn,
  });

  final PhotoRig rig;
  final _RoleHeldStore store;
  final FakeBackend backend;
  final FakeImagePicker picker;
  final Completer<void> release;
  final Future<void> signIn;
}

/// A signed in as 42, and B (99) signing in with B's credentials saved and the
/// role-context write held: A is still the published member, the store's
/// generation is B's.
Future<_Switching> _switching(WidgetTester tester) async {
  final release = await _gate<void>(tester);
  final store = _RoleHeldStore(await _gate<void>(tester))..hold = release;
  final backend = FakeBackend()
    ..on('PUT', _put, FakeResponse(200, photoActive('v-new')))
    ..on('DELETE', _put, const FakeResponse(204))
    ..on('PATCH', '/api/me', FakeResponse(200, meFixture()))
    ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
  final file = sourceFile();
  final picker = FakeImagePicker(onPick: (_) async => XFile(file));
  final rig = PhotoRig(backend, tokens: store, imagePicker: picker);
  await rig.start(tester);
  late Future<void> pending;
  await tester.runAsync(() async {
    pending = rig.container
        .read(sessionProvider.notifier)
        .signIn(email: 'b@example.test', password: 'password-b');
    await store.reached.future;
  });
  return _Switching(
    rig: rig,
    store: store,
    backend: backend,
    picker: picker,
    release: release,
    signIn: pending,
  );
}

void main() {
  // ---------------------------------------------------------------------------
  group('1. the interval between B\'s credentials and B being published', () {
    testWidgets('a pick and a removal begun there do nothing', (tester) async {
      final s = await _switching(tester);

      await tester.runAsync(() async {
        expect(s.rig.account.id, 42, reason: 'A is still published');
        expect(
          s.rig.container.read(sessionProvider.notifier).beginAction(),
          isNull,
          reason: 'nothing can begin on A\'s account with B\'s credentials',
        );
        final picked = await pickPhoto(s.rig.container, ImageSource.gallery);
        final removed = await removeOwnPhoto(s.rig.container);
        expect(picked, isFalse);
        expect(removed, isNull);
        s.release.complete();
        await s.signIn;
      });

      expect(s.picker.picks, isEmpty);
      expect(s.backend.to('PUT', _put), isEmpty);
      expect(s.backend.to('DELETE', _put), isEmpty);
      expect(s.rig.account.id, 99);
    });

    testWidgets('a profile read begun there is not made, and writes no '
        'snapshot', (tester) async {
      final s = await _switching(tester);
      final before = s.backend.to('GET', '/api/me').length;

      await tester.runAsync(() async {
        await s.rig.container.read(sessionProvider.notifier).refreshAccount();
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(
          s.backend.to('GET', '/api/me'),
          hasLength(before),
          reason: 'no request for A under B\'s credentials',
        );
        expect(
          s.store.accountSnapshot,
          isNull,
          reason: 'A\'s profile is never filed under B\'s generation',
        );
        s.release.complete();
        await s.signIn;
        await _until(() => s.store.accountSnapshot != null);
      });

      final saved =
          jsonDecode(s.store.accountSnapshot!) as Map<String, dynamic>;
      expect(saved['id'], 99, reason: 'only B\'s own profile is remembered');
    });

    testWidgets('a profile read begun before it, answering inside it, is '
        'dropped', (tester) async {
      final held = await _gate<FakeResponse>(tester);
      final release = await _gate<void>(tester);
      final store = _RoleHeldStore(await _gate<void>(tester));
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(backend, tokens: store);
      await rig.start(tester);
      backend.handle('GET', '/api/me', (_) => held.future);

      await tester.runAsync(() async {
        final session = rig.container.read(sessionProvider.notifier);
        final refresh = session.refreshAccount();
        await _until(() => backend.to('GET', '/api/me').length == 2);
        store.hold = release;
        final signIn = session.signIn(
          email: 'b@example.test',
          password: 'password-b',
        );
        await store.reached.future;
        held.complete(FakeResponse(200, meFixture()));
        await refresh;
        expect(store.accountSnapshot, isNull, reason: 'A is not remembered');
        expect(rig.account.id, 42);
        release.complete();
        await signIn;
      });

      expect(rig.account.id, 99);
    });

    testWidgets('a profile update begun there is not sent', (tester) async {
      final s = await _switching(tester);

      await tester.runAsync(() async {
        await s.rig.container
            .read(sessionProvider.notifier)
            .updatePreferredLanguage(CommunicationLanguage.french);
        s.release.complete();
        await s.signIn;
      });

      expect(s.backend.to('PATCH', '/api/me'), isEmpty);
    });
  });

  // ---------------------------------------------------------------------------
  group('2. a confirmation belongs to the member it was opened over', () {
    testWidgets('the removal dialog opened over A removes nothing of B\'s', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204))
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      installPhotoCache(PhotoCacheBehavior.serve);
      final rig = PhotoRig(backend, photo: photoActive('a-photo'));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoRemove));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);

      // B signs in while A's dialog is open.
      await tester.runAsync(
        () => rig.container
            .read(sessionProvider.notifier)
            .signIn(email: 'b@example.test', password: 'password-b'),
      );
      await tester.pump();
      expect(rig.account.id, 99);

      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(l.profilePhotoRemove),
        ),
      );
      await tester.pumpAndSettle();

      expect(backend.to('DELETE', _put), isEmpty, reason: 'nothing was sent');
      expect(
        find.text(l.profilePhotoRemoved),
        findsNothing,
        reason: 'and the screen does not claim a removal',
      );
    });

    testWidgets('a removal for a member who is gone is stale, not a success', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204))
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(backend);
      await rig.start(tester);
      final session = rig.container.read(sessionProvider.notifier);
      final scopeOfA = session.beginAction()!;

      final result = await tester.runAsync(() async {
        await session.signIn(email: 'b@example.test', password: 'password-b');
        return rig.container
            .read(profilePhotoProvider.notifier)
            .remove(scopeOfA);
      });

      expect(result!.isStale, isTrue);
      expect(result.isDone, isFalse);
      expect(backend.to('DELETE', _put), isEmpty);
    });
  });

  // ---------------------------------------------------------------------------
  group('3. a second window of the app', () {
    testWidgets('a removal under another member\'s bearer is refused', (
      tester,
    ) async {
      final store = _SharedBearerStore()..access = _jwtFor(42);
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204));
      final rig = PhotoRig(backend, tokens: store);
      await rig.start(tester);

      // The other window signs B in through the same secure storage.
      store.access = _jwtFor(99);
      final removal = await tester.runAsync(
        () => removeOwnPhoto(rig.container),
      );

      expect(removal!.error, isA<ApiException>());
      expect(backend.to('DELETE', _put), isEmpty, reason: 'never sent');
    });

    testWidgets('an upload under another member\'s bearer is refused', (
      tester,
    ) async {
      final store = _SharedBearerStore()..access = _jwtFor(42);
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('v2')));
      final rig = PhotoRig(
        backend,
        tokens: store,
        picker: pickerReturning(sourceFile()),
      );
      await rig.start(tester);
      store.access = _jwtFor(99);

      final saved = await tester.runAsync(
        () => pickPhoto(rig.container, ImageSource.gallery),
      );

      expect(saved, isFalse);
      expect(backend.to('PUT', _put), isEmpty);
    });

    testWidgets('the member\'s own bearer goes through', (tester) async {
      final store = _SharedBearerStore()..access = _jwtFor(42);
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204));
      final rig = PhotoRig(backend, tokens: store);
      await rig.start(tester);

      final removal = await tester.runAsync(
        () => removeOwnPhoto(rig.container),
      );

      expect(removal!.isDone, isTrue);
      expect(backend.to('DELETE', _put), hasLength(1));
    });

    test('the account is read from the token and from nothing else', () {
      expect(bearerAccountId(_jwtFor(42)), 42);
      expect(bearerAccountId('access-token'), isNull);
      expect(bearerAccountId('a.b.c'), isNull);
      expect(bearerAccountId(''), isNull);
    });

    test('the activity is a single instance for the whole device', () {
      final manifest = File(
        'android/app/src/main/AndroidManifest.xml',
      ).readAsStringSync();
      expect(manifest, contains('android:launchMode="singleTask"'));
      expect(manifest, isNot(contains('android:launchMode="singleTop"')));
    });
  });

  // ---------------------------------------------------------------------------
  group('4. transitions that fail or are overtaken leave the app usable', () {
    testWidgets('a second sign-in that fails leaves the member able to act', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('v-new')))
        ..on(
          'POST',
          '/api/auth/sign-in',
          const FakeResponse(400, {
            'detail': 'Wrong password.',
            'code': 'invalid_credentials',
          }),
        );
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.start(tester);
      final session = rig.container.read(sessionProvider.notifier);
      final generation = rig.tokenStore.identityGeneration;

      await tester.runAsync(() async {
        await expectLater(
          session.signIn(email: 'b@example.test', password: 'wrong'),
          throwsA(isA<ApiException>()),
        );
      });

      expect(rig.tokenStore.identityGeneration, isNot(generation));
      expect(rig.account.id, 42, reason: 'still signed in');
      expect(session.beginAction(), isNotNull, reason: 'and able to act');
      final saved = await tester.runAsync(
        () => pickPhoto(rig.container, ImageSource.gallery),
      );
      expect(saved, isTrue);
      expect(backend.to('PUT', _put), hasLength(1));
    });

    testWidgets('a removal in flight across a sign-in of the same member '
        'frees the controls', (tester) async {
      final held = await _gate<FakeResponse>(tester);
      final backend = FakeBackend()
        ..handle('DELETE', _put, (_) => held.future)
        ..on('POST', '/api/auth/sign-in', _signInAs(42, 'Amina Bouzid'));
      final rig = PhotoRig(backend);
      await rig.start(tester);

      final removal = await tester.runAsync(() async {
        final pending = removeOwnPhoto(rig.container);
        await _until(() => backend.to('DELETE', _put).isNotEmpty);
        await rig.container
            .read(sessionProvider.notifier)
            .signIn(email: 'a@example.test', password: 'password-a');
        held.complete(const FakeResponse(204));
        return pending;
      });

      expect(
        removal!.isDone,
        isFalse,
        reason: 'not a removal for the new login',
      );
      final state = rig.container.read(profilePhotoProvider);
      expect(state.busy, isFalse, reason: 'the controls are usable again');
      expect(state.removing, isFalse);
    });
  });

  // ---------------------------------------------------------------------------
  group('5. the picker never opens for a member who has gone', () {
    ({PickGuard guard, FakeImagePicker picker, FakeTokenStore tokens})
    announcing() {
      final tokens = FakeTokenStore();
      final picker = FakeImagePicker();
      final provider = Provider<PickGuard>(
        (ref) => PickGuard(ref, nativeLaunchGate: true),
      );
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          imagePickerProvider.overrideWithValue(picker),
        ],
      );
      addTearDown(container.dispose);
      return (guard: container.read(provider), picker: picker, tokens: tokens);
    }

    testWidgets('a sign-out while the opening is announced opens no picker', (
      tester,
    ) async {
      final log = <String>[];
      final hold = await _gate<void>(tester);
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        _launchChannel,
        (call) async {
          log.add(call.method);
          if (call.method == 'opened') await hold.future;
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          _launchChannel,
          null,
        ),
      );
      final (:guard, :picker, :tokens) = announcing();

      await tester.runAsync(() async {
        final pick = guard.pickImage(
          PickPurpose.profilePhoto,
          source: ImageSource.gallery,
        );
        await _until(() => log.contains('opened'));
        tokens.invalidateIdentity();
        hold.complete();
        expect(await pick, isNull);
      });

      expect(picker.picks, isEmpty, reason: 'the camera never opened');
      expect(log, ['opened', 'closed'], reason: 'the launch was ended');
      expect(guard.busy, isFalse);
      expect(tokens.pendingPick, isNull);
    });

    testWidgets('a caller that no longer wants the pick opens no picker', (
      tester,
    ) async {
      final log = <String>[];
      final hold = await _gate<void>(tester);
      var wanted = true;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        _launchChannel,
        (call) async {
          log.add(call.method);
          if (call.method == 'opened') await hold.future;
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          _launchChannel,
          null,
        ),
      );
      final (:guard, :picker, tokens: _) = announcing();

      await tester.runAsync(() async {
        final pick = guard.run(
          PickPurpose.profilePhoto,
          () async => throw StateError('must not open'),
          proceed: () => wanted,
        );
        await _until(() => log.contains('opened'));
        wanted = false;
        hold.complete();
        expect(await pick, isNull);
      });

      expect(picker.picks, isEmpty);
      expect(log, ['opened', 'closed']);
    });

    testWidgets('a build with no native gate opens no picker', (tester) async {
      final (:guard, :picker, tokens: _) = announcing();

      await tester.runAsync(() async {
        await expectLater(
          guard.pickImage(PickPurpose.itemPhoto, source: ImageSource.gallery),
          throwsA(isA<PickBlockedException>()),
        );
      });

      expect(picker.picks, isEmpty);
      expect(guard.busy, isFalse);
    });
  });
}
