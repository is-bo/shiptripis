/// P3B, round eight: what is drawn for a member is theirs, and the store says
/// whose credentials these are.
///
/// Round seven gave every action one `MemberScope`. The review then found the
/// places the scope itself was read from the wrong moment, or where a failure
/// left the session believing something the credential store did not:
///
/// * **A press** on a control drawn for A, delivered after B was published and
///   before the next frame, took B's scope. The section remembers who it was
///   drawn for and refuses a press that is not theirs.
/// * **A sign-in that fails** settled the session against whoever was shown, not
///   against whose credentials were saved. An earlier sign-in that saved and was
///   then overtaken owns them; and a storage failure may or may not have
///   changed them.
/// * **A profile update** that found the member gone returned as if it had
///   been applied.
/// * **A source sheet** can outlive its section (a session that ends under it).
/// * **A removal or dismissal** names the photo the member was looking at, so a
///   replacement put up on another device is not removed in its place.
///
/// Everything that waits on a held write runs on real time inside `runAsync`,
/// with completers made there.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/bearer_account.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/domain/person_photo.dart';
import 'package:shiptrip/features/profile/profile_photo_section.dart';

import 'support/fake_api.dart';
import 'support/fake_image_picker.dart';
import 'support/harness.dart';
import 'support/photo_cache.dart';
import 'support/photo_rig.dart';

const _put = photoPut;

Future<void> _until(bool Function() condition) async {
  for (var i = 0; i < 300; i++) {
    if (condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  throw StateError('never reached the state the test waited for');
}

Future<Completer<T>> _gate<T>(WidgetTester tester) async =>
    (await tester.runAsync(() async => Completer<T>()))!;

String _jwtFor(int account) {
  String part(Object value) =>
      base64Url.encode(utf8.encode(jsonEncode(value))).replaceAll('=', '');
  return '${part({'alg': 'none'})}.${part({'user_id': account})}.sig';
}

FakeResponse _signInAs(int id, String name, {Map<String, dynamic>? photo}) =>
    FakeResponse(200, {
      'access': _jwtFor(id),
      'refresh': 'refresh-$id',
      'user': {...meFixture(photo: photo), 'id': id, 'full_name': name},
    });

const _wrongPassword = FakeResponse(400, {
  'detail': 'Wrong password.',
  'code': 'invalid_credentials',
});

/// `GET /api/me` for whoever the bearer of the request belongs to, as the
/// server does.
FakeResponse _meOfBearer(RecordedRequest request) {
  final token = '${request.headers['Authorization']}'.replaceFirst(
    'Bearer ',
    '',
  );
  return bearerAccountId(token) == 99
      ? FakeResponse(200, {...meFixture(), 'id': 99, 'full_name': 'Karim Hadj'})
      : FakeResponse(200, meFixture());
}

/// A keystore whose role-context write (the step between a member's
/// credentials being saved and the member being published) can be held, or can
/// fail.
class _HeldStore extends FakeTokenStore {
  _HeldStore(this.reached, {super.refresh});

  final Completer<void> reached;
  Completer<void>? hold;

  /// What a sign-in saved; a restore finds it, as it does on a device.
  @override
  Future<String?> readRefresh() async =>
      savedAccess == null ? await super.readRefresh() : 'refresh-saved';

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

enum _Failure { beforeCredentials, afterCredentials, roleContext }

/// A keystore that fails at a chosen step, as secure storage can.
class _FlakyStore extends FakeTokenStore {
  _FlakyStore(this.failure) {
    savedAccess = _jwtFor(42);
  }

  final _Failure failure;

  @override
  Future<bool> saveAuthenticationIfCurrent({
    required int expectedIdentityGeneration,
    required String access,
    required String refresh,
  }) async {
    if (failure == _Failure.beforeCredentials) {
      throw PlatformException(code: 'storage');
    }
    final saved = await super.saveAuthenticationIfCurrent(
      expectedIdentityGeneration: expectedIdentityGeneration,
      access: access,
      refresh: refresh,
    );
    if (failure == _Failure.afterCredentials) {
      throw PlatformException(code: 'storage');
    }
    return saved;
  }

  @override
  Future<void> writeRoleContext(String value) async {
    if (failure == _Failure.roleContext) {
      throw PlatformException(code: 'storage');
    }
    await super.writeRoleContext(value);
  }
}

/// The photo section on a page that can lose its member, as Profile can.
Future<void> _pumpSection(WidgetTester tester, PhotoRig rig) async {
  await rig.start(tester);
  await tester.pumpWidget(const SizedBox.shrink());
  await pumpApp(
    tester,
    Scaffold(
      body: Consumer(
        builder: (context, ref, _) {
          final account = ref.watch(accountProvider);
          return ListView(
            children: [
              if (account != null) ProfilePhotoSection(account: account),
            ],
          );
        },
      ),
    ),
    container: rig.container,
  );
}

void main() {
  // ---------------------------------------------------------------------------
  group('1. a press is for the member the control was drawn for', () {
    testWidgets(
      'a tap on A\'s Dismiss, after B is published and before the next frame, '
      'removes nothing of B\'s',
      (tester) async {
        installPhotoCache(PhotoCacheBehavior.serve);
        final backend = FakeBackend()
          ..on('DELETE', _put, const FakeResponse(204))
          ..on(
            'POST',
            '/api/auth/sign-in',
            _signInAs(99, 'Karim Hadj', photo: photoActive('v-b')),
          );
        final rig = PhotoRig(backend, photo: photoRemoved());
        await rig.pump(tester);
        final l = rig.l(tester);

        await tester.runAsync(
          () => rig.container
              .read(sessionProvider.notifier)
              .signIn(email: 'b@example.test', password: 'password-b'),
        );
        expect(rig.account.id, 99, reason: 'B is published');

        // No frame has been drawn since: A's notice is still on screen.
        await tester.tap(find.text(l.profilePhotoDismiss));
        await tester.pump();

        expect(backend.to('DELETE', _put), isEmpty);
        expect(rig.account.photo?.version, 'v-b', reason: 'B kept their photo');
        expect(find.text(l.profilePhotoWassla), findsNothing);
      },
    );

    testWidgets('a tap on A\'s Remove, likewise, opens no dialog and removes '
        'nothing', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204))
        ..on(
          'POST',
          '/api/auth/sign-in',
          _signInAs(99, 'Karim Hadj', photo: photoActive('v-b')),
        );
      final rig = PhotoRig(backend, photo: photoActive('v-a'));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.runAsync(
        () => rig.container
            .read(sessionProvider.notifier)
            .signIn(email: 'b@example.test', password: 'password-b'),
      );
      await tester.tap(photoButton(l.profilePhotoRemove));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
      expect(backend.to('DELETE', _put), isEmpty);
      expect(rig.account.photo?.version, 'v-b');
    });

    testWidgets('a press on the member who is still shown goes through', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204));
      final rig = PhotoRig(backend, photo: photoRemoved());
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(find.text(l.profilePhotoDismiss));
      await tester.pumpAndSettle();

      expect(backend.to('DELETE', _put), hasLength(1));
    });

    testWidgets('a source chosen after the session ended under the sheet '
        'opens no picker and throws nothing', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final picker = FakeImagePicker();
      final rig = PhotoRig(
        FakeBackend()..on('PUT', _put, FakeResponse(200, photoActive('v2'))),
        photo: photoActive('v1'),
        imagePicker: picker,
      );
      await _pumpSection(tester, rig);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChange));
      await tester.pumpAndSettle();
      expect(find.text(l.profilePhotoChoose), findsOneWidget, reason: 'sheet');

      rig.container.read(sessionProvider.notifier).handleSessionExpired();
      await tester.pump();
      expect(
        find.byType(ProfilePhotoSection),
        findsNothing,
        reason: 'the section went away with the session',
      );

      await tester.tap(find.text(l.profilePhotoChoose));
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(picker.picks, isEmpty);
    });
  });

  // ---------------------------------------------------------------------------
  group('2. a removal or dismissal names the photo that was shown', () {
    testWidgets('the DELETE carries the version of the notice', (tester) async {
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204));
      final rig = PhotoRig(backend, photo: photoRemoved());
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(find.text(l.profilePhotoDismiss));
      await tester.pumpAndSettle();

      expect(backend.lastTo('DELETE', _put)!.query, {'version': 'v0'});
    });

    testWidgets('the DELETE of a removal carries the version of the photo', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204));
      final rig = PhotoRig(backend, photo: photoActive('v7'));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoRemove));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(l.profilePhotoRemove),
        ),
      );
      await tester.pumpAndSettle();

      expect(backend.lastTo('DELETE', _put)!.query, {'version': 'v7'});
    });

    testWidgets('a notice already replaced elsewhere is not dismissed: the '
        'profile is read again and nothing is said', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final backend = FakeBackend()
        ..on(
          'DELETE',
          _put,
          const FakeResponse(409, {
            'detail': 'The photo changed since it was shown.',
            'code': 'profile_photo_changed',
          }),
        );
      final rig = PhotoRig(backend, photo: photoRemoved());
      await rig.pump(tester);
      final l = rig.l(tester);
      // Another device put a photo up.
      backend.on(
        'GET',
        '/api/me',
        FakeResponse(200, meFixture(photo: photoActive('v2'))),
      );

      await tester.tap(find.text(l.profilePhotoDismiss));
      await untilReached(tester, () => rig.account.photo?.version == 'v2');
      await tester.pumpAndSettle();

      expect(backend.to('DELETE', _put), hasLength(1));
      expect(find.byType(SnackBar), findsNothing);
      expect(find.text(l.profilePhotoWassla), findsNothing);
      expect(rig.account.photo?.isActive, isTrue, reason: 'the new photo');
      expect(photoButton(l.profilePhotoRemove), findsOneWidget);
    });

    test('a removed photo without a version is no photo at all', () {
      // The server always names it; a body that does not is not trusted.
      expect(
        OwnPhoto.maybe(const {
          'state': 'removed',
          'url': null,
          'removed_at': '2026-11-24T10:00:00Z',
          'reason': 'Not a photo of you.',
        }),
        isNull,
        reason: 'nothing to name in a dismissal',
      );
    });
  });

  // ---------------------------------------------------------------------------
  group('3. a sign-in that fails is settled against the credentials in '
      'storage', () {
    Future<
      ({
        PhotoRig rig,
        _HeldStore store,
        FakeBackend backend,
        Completer<void> release,
        Future<void> signInB,
      })
    >
    overtaken(WidgetTester tester, {String? refresh = 'refresh-token'}) async {
      final release = await _gate<void>(tester);
      final store = _HeldStore(await _gate<void>(tester), refresh: refresh)
        ..hold = release;
      var attempts = 0;
      final backend = FakeBackend()
        ..on('PATCH', '/api/me', FakeResponse(200, meFixture()))
        ..handle('POST', '/api/auth/sign-in', (_) {
          attempts++;
          return attempts == 1 ? _signInAs(99, 'Karim Hadj') : _wrongPassword;
        });
      final rig = PhotoRig(backend, tokens: store);
      await rig.start(tester);
      backend.handle('GET', '/api/me', _meOfBearer);
      late Future<void> pending;
      await tester.runAsync(() async {
        pending = rig.container
            .read(sessionProvider.notifier)
            .signIn(email: 'b@example.test', password: 'password-b');
        await store.reached.future;
      });
      return (
        rig: rig,
        store: store,
        backend: backend,
        release: release,
        signInB: pending,
      );
    }

    testWidgets('B saved and was overtaken, C is refused: B is shown, not A', (
      tester,
    ) async {
      final s = await overtaken(tester);
      final session = s.rig.container.read(sessionProvider.notifier);
      expect(s.rig.account.id, 42, reason: 'A is still shown');

      await tester.runAsync(() async {
        await expectLater(
          session.signIn(email: 'c@example.test', password: 'wrong'),
          throwsA(isA<ApiException>()),
        );
        await _until(() => s.rig.container.read(accountProvider)?.id == 99);
        s.release.complete();
        await s.signInB;
      });

      expect(
        bearerAccountId(s.store.savedAccess!),
        99,
        reason: 'storage holds B\'s credentials',
      );
      expect(s.rig.account.id, 99, reason: 'and B is who is shown');
      expect(session.beginAction()?.accountId, 99);
      expect(s.backend.to('PATCH', '/api/me'), isEmpty);
    });

    testWidgets('the same, from the sign-in screen: the guest is signed in as '
        'the member whose credentials were saved', (tester) async {
      final s = await overtaken(tester, refresh: null);
      final session = s.rig.container.read(sessionProvider.notifier);
      expect(s.rig.container.read(accountProvider), isNull, reason: 'a guest');

      await tester.runAsync(() async {
        await expectLater(
          session.signIn(email: 'c@example.test', password: 'wrong'),
          throwsA(isA<ApiException>()),
        );
        await _until(() => s.rig.container.read(accountProvider)?.id == 99);
        s.release.complete();
        await s.signInB;
      });

      expect(s.rig.account.id, 99);
      expect(session.beginAction()?.accountId, 99);
    });

    testWidgets('a refusal with nothing overtaken leaves the member shown, '
        'able to act', (tester) async {
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-in', _wrongPassword);
      final rig = PhotoRig(backend);
      await rig.start(tester);
      final session = rig.container.read(sessionProvider.notifier);

      await tester.runAsync(() async {
        await expectLater(
          session.signIn(email: 'a@example.test', password: 'wrong'),
          throwsA(isA<ApiException>()),
        );
      });

      expect(rig.account.id, 42);
      expect(session.beginAction()?.accountId, 42);
    });

    testWidgets('storage that fails before anything changed leaves the member '
        'shown, able to act', (tester) async {
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(
        backend,
        tokens: _FlakyStore(_Failure.beforeCredentials),
      );
      await rig.start(tester);
      final session = rig.container.read(sessionProvider.notifier);

      await tester.runAsync(() async {
        await expectLater(
          session.signIn(email: 'b@example.test', password: 'password-b'),
          throwsA(isA<PlatformException>()),
        );
      });

      expect(rig.account.id, 42);
      expect(session.beginAction()?.accountId, 42, reason: 'not stranded');
    });

    testWidgets('storage that fails after the credentials changed ends the '
        'local session, and clears what it holds', (tester) async {
      final store = _FlakyStore(_Failure.afterCredentials);
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(backend, tokens: store);
      await rig.start(tester);
      final session = rig.container.read(sessionProvider.notifier);

      await tester.runAsync(() async {
        await expectLater(
          session.signIn(email: 'b@example.test', password: 'password-b'),
          throwsA(isA<PlatformException>()),
        );
        await _until(() => store.savedAccess == null);
      });

      expect(rig.container.read(accountProvider), isNull, reason: 'signed out');
      expect(session.beginAction(), isNull);
    });

    testWidgets(
      'a role context that cannot be kept does not undo the sign-in',
      (tester) async {
        final backend = FakeBackend()
          ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
        final rig = PhotoRig(
          backend,
          tokens: _FlakyStore(_Failure.roleContext),
        );
        await rig.start(tester);

        await tester.runAsync(
          () => rig.container
              .read(sessionProvider.notifier)
              .signIn(email: 'b@example.test', password: 'password-b'),
        );

        expect(rig.account.id, 99);
        expect(
          rig.container.read(sessionProvider.notifier).beginAction()?.accountId,
          99,
        );
      },
    );
  });

  // ---------------------------------------------------------------------------
  group('4. a profile update says whether it was applied', () {
    testWidgets('for a member who is gone it is not applied, and sends '
        'nothing', (tester) async {
      final release = await _gate<void>(tester);
      final store = _HeldStore(await _gate<void>(tester))..hold = release;
      final backend = FakeBackend()
        ..on('PATCH', '/api/me', FakeResponse(200, meFixture()))
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(backend, tokens: store);
      await rig.start(tester);
      final session = rig.container.read(sessionProvider.notifier);

      await tester.runAsync(() async {
        final pending = session.signIn(
          email: 'b@example.test',
          password: 'password-b',
        );
        await store.reached.future;
        // A is still shown; B's credentials are the stored ones.
        expect(
          await session.updatePreferredLanguage(CommunicationLanguage.french),
          isFalse,
        );
        expect(await session.setFullName('Amina'), isFalse);
        release.complete();
        await pending;
      });

      expect(backend.to('PATCH', '/api/me'), isEmpty);
    });

    testWidgets('an answer that comes back after the member left is not '
        'applied', (tester) async {
      final held = await _gate<FakeResponse>(tester);
      final backend = FakeBackend()
        ..handle('PATCH', '/api/me', (_) => held.future)
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(backend);
      await rig.start(tester);
      final session = rig.container.read(sessionProvider.notifier);

      final applied = await tester.runAsync(() async {
        final update = session.updatePreferredLanguage(
          CommunicationLanguage.french,
        );
        await _until(() => backend.to('PATCH', '/api/me').isNotEmpty);
        await session.signIn(email: 'b@example.test', password: 'password-b');
        held.complete(
          FakeResponse(200, {...meFixture(), 'preferred_language': 'fr'}),
        );
        return update;
      });

      expect(applied, isFalse);
      expect(rig.account.id, 99);
      expect(
        rig.account.preferredLanguage,
        isNot(CommunicationLanguage.french),
      );
    });

    testWidgets('for the member who asked it is applied', (tester) async {
      final backend = FakeBackend()
        ..on(
          'PATCH',
          '/api/me',
          FakeResponse(200, {...meFixture(), 'preferred_language': 'fr'}),
        );
      final rig = PhotoRig(backend);
      await rig.start(tester);

      final applied = await tester.runAsync(
        () => rig.container
            .read(sessionProvider.notifier)
            .updatePreferredLanguage(CommunicationLanguage.french),
      );

      expect(applied, isTrue);
      expect(rig.account.preferredLanguage, CommunicationLanguage.french);
    });
  });
}
