/// P3B, round two of the second pass: the findings the re-review kept open or
/// found new.
///
/// * **B.** An upload never goes out under another member's token, whether the
///   other member signs in while the photo is prepared, while its file is read,
///   or while the request is in flight.
/// * **C.** The member's own photo is guarded against older reads (a profile
///   write, the launch confirmation), a file that vanishes during a failed
///   upload is not offered for a retry, and one picker's lost result is never
///   offered to another purpose.
/// * **D.** A second tap cannot reserve the picker twice, and no prepared file
///   outlives the pick that made it.
///
/// Everything runs on real time inside `runAsync` where it waits on files or
/// on a held request, with completers made there too (one made in a test's
/// fake-async zone cannot be completed from outside it).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/discovery_state.dart';
import 'package:shiptrip/app/profile_photo_state.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/media/pick_guard.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart' show InfoNotice;
import 'package:shiptrip/domain/account.dart';

import 'support/fake_api.dart';
import 'support/fake_image_picker.dart';
import 'support/photo_rig.dart';

const _put = photoPut;

/// Waits (on real time) until [condition] holds.
Future<void> _until(bool Function() condition) async {
  for (var i = 0; i < 300; i++) {
    if (condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  throw StateError('never reached the state the test waited for');
}

Future<Completer<T>> _gate<T>(WidgetTester tester) async =>
    (await tester.runAsync(() async => Completer<T>()))!;

FakeResponse _signInAs(int id, String name) => FakeResponse(200, {
  'access': 'access-$id',
  'refresh': 'refresh-$id',
  'user': {...meFixture(), 'id': id, 'full_name': name},
});

ProfilePhotoController _photo(PhotoRig rig) =>
    rig.container.read(profilePhotoProvider.notifier);

void main() {
  // ---------------------------------------------------------------------------
  group('B. an upload never goes out under another account', () {
    testWidgets('a sign-in while the file is being read stops the request', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive()));
      final rig = PhotoRig(backend);
      await rig.start(tester);
      final file = sourceFile();
      final auth = rig.container.read(authRepositoryProvider);
      Object? error;

      await tester.runAsync(() async {
        final upload = auth.uploadPhoto(
          filePath: file,
          fileName: 'photo.jpg',
          contentType: 'image/jpeg',
          expectedIdentity: rig.tokenStore.identityGeneration,
        );
        // The file is being read; another member's sign-in lands now.
        rig.tokenStore.invalidateIdentity();
        try {
          await upload;
        } on Object catch (caught) {
          error = caught;
        }
      });

      expect(error, isA<ApiException>());
      expect(backend.to('PUT', _put), isEmpty, reason: 'nothing was sent');
    });

    testWidgets('the client refuses an upload begun under an older sign-in', (
      tester,
    ) async {
      final backend = FakeBackend();
      final rig = PhotoRig(backend);
      await rig.start(tester);
      final api = rig.container.read(apiClientProvider);
      final stale = api.identityGeneration;
      rig.tokenStore.invalidateIdentity();
      Object? error;

      await tester.runAsync(() async {
        try {
          await api.upload(
            _put,
            form: FormData(),
            method: 'PUT',
            expectedIdentity: stale,
          );
        } on Object catch (caught) {
          error = caught;
        }
      });

      expect(error, isA<ApiException>());
      expect(backend.requests.where((r) => r.path == _put), isEmpty);
    });

    testWidgets('an upload that does not name an identity is unaffected', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('POST', '/api/parcels/media', const FakeResponse(201, {'id': 1}));
      final rig = PhotoRig(backend);
      await rig.start(tester);
      final api = rig.container.read(apiClientProvider);

      final body = await tester.runAsync(
        () => api.upload('/api/parcels/media', form: FormData()),
      );

      expect(body?['id'], 1);
    });

    testWidgets(
      'account A to B while the photo is being prepared sends nothing',
      (tester) async {
        final held = await _gate<void>(tester);
        final outputs = <String>[];
        final backend = FakeBackend()
          ..on('PUT', _put, FakeResponse(200, photoActive('a-photo')))
          ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
        final write = preparerWriting(jpegBytes, outputs: outputs);
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile()),
          preparer: (path) async {
            await held.future;
            return write(path);
          },
        );
        await rig.start(tester);

        final picked = await tester.runAsync(() async {
          final pick = _photo(rig).pick(ImageSource.gallery);
          await Future<void>.delayed(const Duration(milliseconds: 60));
          // Account B signs in on this phone while A's photo is being prepared.
          await rig.container
              .read(sessionProvider.notifier)
              .signIn(email: 'b@example.test', password: 'password-b');
          held.complete();
          return pick;
        });

        expect(picked, isFalse);
        expect(
          backend.to('PUT', _put),
          isEmpty,
          reason: 'not under A\'s photo, not under B\'s token',
        );
        expect(rig.account.id, 99);
        expect(rig.account.photo, isNull);
        final state = rig.container.read(profilePhotoProvider);
        expect(state.picked, isNull);
        expect(state.busy, isFalse);
        expect(
          File(outputs.single).existsSync(),
          isFalse,
          reason: 'not leaked',
        );
      },
    );

    testWidgets('account A to B while the upload is in flight leaves B alone', (
      tester,
    ) async {
      final held = await _gate<FakeResponse>(tester);
      final backend = FakeBackend()
        ..handle('PUT', _put, (_) => held.future)
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.start(tester);

      final saved = await tester.runAsync(() async {
        final pick = _photo(rig).pick(ImageSource.gallery);
        await _until(() => backend.to('PUT', _put).isNotEmpty);
        // A's request is on the wire. B signs in.
        await rig.container
            .read(sessionProvider.notifier)
            .signIn(email: 'b@example.test', password: 'password-b');
        // A's answer arrives late, with A's new photo.
        held.complete(FakeResponse(200, photoActive('a-photo')));
        return pick;
      });

      expect(saved, isFalse);
      expect(backend.to('PUT', _put), hasLength(1));
      expect(rig.account.id, 99);
      expect(rig.account.photo, isNull, reason: 'A\'s photo is not B\'s');
      final state = rig.container.read(profilePhotoProvider);
      expect(state.picked, isNull);
      expect(state.failure, isNull);
      expect(state.busy, isFalse);
    });
  });

  // ---------------------------------------------------------------------------
  group('C6. a public-profile write that began earlier', () {
    Map<String, dynamic> ownProfile(Map<String, dynamic>? photo) => {
      ...ownProfileFixture(state: 'visible', discoverable: true),
      'card': profileCardFixture(id: 'me', name: 'Amina', photo: photo),
    };

    testWidgets('does not put the old photo back after a removal', (
      tester,
    ) async {
      final held = await _gate<FakeResponse>(tester);
      Map<String, dynamic>? shown = photoFixture('v1');
      final backend = FakeBackend()
        ..emptyDiscovery()
        ..handle(
          'GET',
          '/api/discovery/profile/me',
          (_) => FakeResponse(200, ownProfile(shown)),
        )
        // The write's answer is held back, and carries the photo as it was.
        ..handle('PUT', '/api/discovery/profile/me', (_) => held.future)
        ..handle('DELETE', _put, (_) {
          shown = null;
          return const FakeResponse(204);
        });
      final rig = PhotoRig(backend, photo: photoActive());
      await rig.start(tester);

      final after = await tester.runAsync(() async {
        final keep = rig.container.listen(ownProfileProvider, (_, _) {});
        addTearDown(keep.close);
        await rig.container.read(ownProfileProvider.future);
        final write = rig.container
            .read(ownProfileProvider.notifier)
            .setDiscoverable(true);
        await _until(
          () => backend.to('PUT', '/api/discovery/profile/me').isNotEmpty,
        );
        await _photo(rig).remove();
        held.complete(FakeResponse(200, ownProfile(photoFixture('v1'))));
        await write;
        return rig.container.read(ownProfileProvider.future);
      });

      expect(after!.card.person.photo, isNull);
    });

    testWidgets(
      'with no photo change meanwhile, its answer is used as it was',
      (tester) async {
        final backend = FakeBackend()
          ..emptyDiscovery()
          ..on(
            'PUT',
            '/api/discovery/profile/me',
            FakeResponse(200, ownProfile(photoFixture('v1'))),
          );
        final rig = PhotoRig(backend);
        await rig.start(tester);

        final reads = backend.to('GET', '/api/discovery/profile/me').length;
        await tester.runAsync(() async {
          final keep = rig.container.listen(ownProfileProvider, (_, _) {});
          addTearDown(keep.close);
          await rig.container.read(ownProfileProvider.future);
          await rig.container
              .read(ownProfileProvider.notifier)
              .setDiscoverable(true);
        });

        expect(
          backend.to('GET', '/api/discovery/profile/me').length,
          reads + 1,
          reason: 'one read to open it; the write\'s answer needs no second',
        );
      },
    );
  });

  // ---------------------------------------------------------------------------
  group('C7. the launch confirmation', () {
    testWidgets('does not overwrite a photo changed while it was in flight', (
      tester,
    ) async {
      final held = await _gate<FakeResponse>(tester);
      final snapshot = jsonEncode(
        Account.fromJson({
          ...meFixture(),
          'full_name': 'Amina (saved)',
        }).toSnapshotJson(),
      );
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('v2')));
      final rig = PhotoRig(
        backend,
        tokens: FakeTokenStore(accountSnapshot: snapshot),
      );
      // Not restored: the launch is the test, and its /api/me is held.
      await rig.start(tester, restore: false);
      backend.handle('GET', '/api/me', (_) => held.future);
      final file = sourceFile();

      await tester.runAsync(() async {
        final session = rig.container.read(sessionProvider.notifier);
        // The app enters on the snapshot while /api/me is still being asked.
        await _until(() => rig.container.read(accountProvider) != null);
        expect(rig.account.fullName, 'Amina (saved)');
        await session.uploadPhoto(
          filePath: file,
          fileName: 'photo.jpg',
          contentType: 'image/jpeg',
          expectedIdentity: rig.tokenStore.identityGeneration,
        );
        // The confirmation lands last, and says there is no photo.
        held.complete(
          FakeResponse(200, {
            ...meFixture(photo: null),
            'full_name': 'Amina Bouzid',
          }),
        );
        await _until(() => rig.account.fullName == 'Amina Bouzid');
      });

      expect(rig.account.photo?.version, 'v2', reason: 'the newer photo stays');
      expect(rig.account.fullName, 'Amina Bouzid', reason: 'the rest applies');
    });

    testWidgets('with no photo change meanwhile, the server\'s photo is used', (
      tester,
    ) async {
      final held = await _gate<FakeResponse>(tester);
      final snapshot = jsonEncode(
        Account.fromJson(meFixture()).toSnapshotJson(),
      );
      final backend = FakeBackend();
      final rig = PhotoRig(
        backend,
        tokens: FakeTokenStore(accountSnapshot: snapshot),
      );
      await rig.start(tester, restore: false);
      backend.handle('GET', '/api/me', (_) => held.future);

      await tester.runAsync(() async {
        rig.container.read(sessionProvider.notifier);
        await _until(() => rig.container.read(accountProvider) != null);
        held.complete(FakeResponse(200, meFixture(photo: photoActive('v7'))));
        await _until(() => rig.account.photo != null);
      });

      expect(rig.account.photo?.version, 'v7');
    });
  });

  // ---------------------------------------------------------------------------
  group('C9. a file that vanishes during a failed upload', () {
    testWidgets('is not offered for a retry', (tester) async {
      late PhotoRig rig;
      final backend = FakeBackend()
        ..handle('PUT', _put, (_) {
          // The phone clears the cache between Dio's length read and its
          // stream open: the request fails, and the file is gone.
          final path = rig.container.read(profilePhotoProvider).picked!.path;
          File(path).deleteSync();
          return const FakeResponse(503, {
            'code': 'profile_photo_storage_unavailable',
          });
        });
      rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.start(tester);

      final saved = await tester.runAsync(
        () => _photo(rig).pick(ImageSource.gallery),
      );

      expect(saved, isFalse);
      final state = rig.container.read(profilePhotoProvider);
      expect(state.failure, ProfilePhotoFailure.unreadable);
      expect(state.failure!.canRetry, isFalse, reason: 'pick again instead');
      expect(state.picked, isNull);
      expect(state.busy, isFalse);
    });

    testWidgets('a failure with the file still there keeps its retry', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'PUT',
          _put,
          const FakeResponse(503, {
            'code': 'profile_photo_storage_unavailable',
          }),
        );
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.start(tester);

      await tester.runAsync(() => _photo(rig).pick(ImageSource.gallery));

      final state = rig.container.read(profilePhotoProvider);
      expect(state.failure, ProfilePhotoFailure.storageUnavailable);
      expect(state.picked, isNotNull);
    });
  });

  // ---------------------------------------------------------------------------
  group(
    'C14. one picker\'s lost result is never offered to another purpose',
    () {
      /// A phone that ends the app while a picker is open: the picker keeps the
      /// photo, the marker stays in secure storage, and the next launch gets a
      /// new container over the same two.
      Future<PhotoRig> launch(
        WidgetTester tester,
        FakeTokenStore tokens,
        FakeImagePicker picker, {
        Map<String, dynamic>? photo,
      }) async {
        final rig = PhotoRig(
          FakeBackend()..on('PUT', _put, FakeResponse(200, photoActive())),
          tokens: tokens,
          imagePicker: picker,
          photo: photo,
        );
        await rig.start(tester);
        return rig;
      }

      testWidgets(
        'Profile, restart, KYC, restart: the ID photo never reaches Profile',
        (tester) async {
          final tokens = FakeTokenStore();
          final picker = FakeImagePicker();
          final profileFile = sourceFile(name: 'profile.jpg');
          final idFile = sourceFile(name: 'id-document.jpg');

          // Launch 1: the member is choosing a profile photo; the phone ends the
          // app with the picture saved by the picker.
          picker.onPick = (_) async {
            picker.lost = XFile(profileFile);
            return Completer<XFile?>().future;
          };
          final first = await launch(tester, tokens, picker);
          await tester.runAsync(() async {
            unawaited(_photo(first).pick(ImageSource.gallery));
            await _until(() => picker.lost != null);
          });
          expect(tokens.pendingPick, startsWith('profilePhoto:'));
          expect(picker.lost, isNotNull);

          // Launch 2: before Profile is opened, the identity check opens its
          // picker (a selfie); the phone ends the app again.
          picker.onPick = (_) async {
            picker.lost = XFile(idFile);
            return Completer<XFile?>().future;
          };
          final second = await launch(tester, tokens, picker);
          await tester.runAsync(() async {
            unawaited(
              second.container
                  .read(pickGuardProvider)
                  .pickImage(
                    PickPurpose.identityDocument,
                    source: ImageSource.camera,
                  ),
            );
            await _until(
              () =>
                  tokens.pendingPick?.startsWith('identityDocument:') ?? false,
            );
            // The picker is open once it has saved the ID photo.
            await _until(() => picker.lost?.path == idFile);
          });
          expect(
            File(profileFile).existsSync(),
            isFalse,
            reason: 'the profile photo was consumed and deleted first',
          );
          expect(picker.lost?.path, idFile);

          // Launch 3: Profile opens. Nothing is offered: the profile photo does
          // not recover a lost result at all.
          final backend = FakeBackend()
            ..on('PUT', _put, FakeResponse(200, photoActive()));
          final third = PhotoRig(
            backend,
            tokens: tokens,
            imagePicker: picker,
            picker: (_) async => XFile(idFile),
          );
          await third.pump(tester);
          await tester.runAsync(
            () => Future<void>.delayed(const Duration(milliseconds: 120)),
          );
          await tester.pump();
          expect(find.byType(InfoNotice), findsNothing);
          expect(third.container.read(profilePhotoProvider).picked, isNull);
          expect(backend.to('PUT', _put), isEmpty);

          // The member now picks a profile photo, and the ID file's late copy
          // is what answers: it is refused and deleted, never kept or sent.
          await tester.tap(photoButton(third.l(tester).profilePhotoChoose));
          await untilReached(
            tester,
            () => find
                .text(third.l(tester).profilePhotoUncertain)
                .evaluate()
                .isNotEmpty,
          );
          expect(backend.to('PUT', _put), isEmpty);
          expect(File(idFile).existsSync(), isFalse);
          expect(third.container.read(profilePhotoProvider).picked, isNull);
          expect(picker.lost, isNull, reason: 'consumed, deleted');
          expect(tokens.pendingPick, isNull);
        },
      );

      testWidgets('Profile, restart, Profile: the photo is not offered', (
        tester,
      ) async {
        final tokens = FakeTokenStore();
        final picker = FakeImagePicker();
        final profileFile = sourceFile(name: 'profile.jpg');
        picker.onPick = (_) async {
          picker.lost = XFile(profileFile);
          return Completer<XFile?>().future;
        };
        final first = await launch(tester, tokens, picker);
        await tester.runAsync(() async {
          unawaited(_photo(first).pick(ImageSource.gallery));
          await _until(() => picker.lost != null);
        });

        final backend = FakeBackend();
        final second = PhotoRig(backend, tokens: tokens, imagePicker: picker);
        await second.pump(tester);
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 120)),
        );
        await tester.pump();

        expect(find.byType(InfoNotice), findsNothing);
        expect(second.container.read(profilePhotoProvider).picked, isNull);
        expect(backend.to('PUT', _put), isEmpty);
      });

      testWidgets(
        'a pick of any purpose throws away an older lost result first',
        (tester) async {
          final tokens = FakeTokenStore()..pendingPick = 'ticketProof:42:abc';
          final picker = FakeImagePicker(lost: XFile(sourceFile()));
          picker.onPick = (_) async => null;
          final rig = await launch(tester, tokens, picker);

          await tester.runAsync(
            () => rig.container
                .read(pickGuardProvider)
                .pickImage(PickPurpose.itemPhoto, source: ImageSource.gallery),
          );

          expect(picker.lost, isNull);
          expect(picker.lostReads, greaterThanOrEqualTo(1));
          expect(
            tokens.pendingPick,
            isNull,
            reason: 'cleared by the pick that wrote it',
          );
        },
      );

      testWidgets('a second pick while one is open does nothing at all', (
        tester,
      ) async {
        // The first pick's picker is open. A second pick (of any purpose) finds
        // the guard taken: it opens nothing and, above all, leaves the first
        // pick's marker where it is.
        final tokens = FakeTokenStore();
        final picker = FakeImagePicker();
        final rig = await launch(tester, tokens, picker);
        final guard = rig.container.read(pickGuardProvider);

        await tester.runAsync(() async {
          final open = Completer<XFile?>();
          picker.onPick = (_) => open.future;
          final first = guard.pickImage(
            PickPurpose.identityDocument,
            source: ImageSource.gallery,
          );
          await _until(() => picker.picks.isNotEmpty);
          final firstMarker = tokens.pendingPick;
          expect(firstMarker, startsWith('identityDocument:'));

          final second = await guard.pickImage(
            PickPurpose.itemPhoto,
            source: ImageSource.camera,
          );

          expect(second, isNull);
          expect(picker.picks, hasLength(1), reason: 'no second picker');
          expect(tokens.pendingPick, firstMarker, reason: 'owner untouched');
          open.complete(null);
          await first;
          expect(tokens.pendingPick, isNull, reason: 'the owner cleared it');
        });
      });

      testWidgets('every purpose is a different marker', (tester) async {
        final tokens = FakeTokenStore();
        final rig = await launch(tester, tokens, FakeImagePicker());
        final guard = rig.container.read(pickGuardProvider);
        final seen = <String>{};

        await tester.runAsync(() async {
          for (final purpose in PickPurpose.values) {
            await guard.run(purpose, () async {
              seen.add(tokens.pendingPick!.split(':').first);
              return null;
            });
          }
        });

        expect(seen, PickPurpose.values.map((p) => p.name).toSet());
      });
    },
  );

  // ---------------------------------------------------------------------------
  group('D. a double tap, and the files a pick leaves behind', () {
    testWidgets(
      'a second tap cannot reserve the picker, and the first keeps its marker',
      (tester) async {
        final tokens = FakeTokenStore();
        final picker = FakeImagePicker();
        final backend = FakeBackend()
          ..on('PUT', _put, FakeResponse(200, photoActive()));
        final rig = PhotoRig(
          backend,
          tokens: tokens,
          imagePicker: picker,
          preparer: preparerWriting(jpegBytes),
        );
        await rig.start(tester);

        await tester.runAsync(() async {
          final open = Completer<XFile?>();
          picker.onPick = (_) => open.future;
          final controller = _photo(rig);

          final first = controller.pick(ImageSource.gallery);
          // The same press arriving twice, before anything has been awaited.
          final second = controller.pick(ImageSource.camera);
          expect(await second, isFalse);

          await _until(() => picker.picks.isNotEmpty);
          expect(picker.picks, [ImageSource.gallery], reason: 'opened once');
          expect(
            tokens.pendingPick,
            startsWith('profilePhoto:'),
            reason: 'the second tap did not clear the first one\'s marker',
          );
          expect(rig.container.read(profilePhotoProvider).picking, isTrue);

          open.complete(XFile(sourceFile()));
          expect(await first, isTrue);
        });

        expect(tokens.pendingPick, isNull);
        expect(picker.picks, [ImageSource.gallery]);
        expect(backend.to('PUT', _put), hasLength(1));
      },
    );

    testWidgets('while the picker is open the buttons are not pressable', (
      tester,
    ) async {
      final picker = FakeImagePicker();
      final rig = PhotoRig(FakeBackend(), imagePicker: picker);
      await rig.pump(tester);
      final l = rig.l(tester);
      final open = await _gate<XFile?>(tester);
      picker.onPick = (_) => open.future;

      await tester.tap(photoButton(l.profilePhotoChoose));
      await tester.pump();

      expect(photoButtonEnabled(tester, l.profilePhotoTake), isFalse);
      expect(photoButtonEnabled(tester, l.profilePhotoChoose), isFalse);
      expect(picker.picks, hasLength(1));
    });

    group('a prepared file lasts only as long as its pick', () {
      Future<PhotoRig> failing(
        WidgetTester tester, {
        required List<String> outputs,
      }) async {
        final backend = FakeBackend()
          ..on(
            'PUT',
            _put,
            const FakeResponse(503, {
              'code': 'profile_photo_storage_unavailable',
            }),
          );
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile()),
          preparer: preparerWriting(jpegBytes, outputs: outputs),
        );
        await rig.start(tester);
        return rig;
      }

      testWidgets('replaced by another pick', (tester) async {
        final outputs = <String>[];
        final rig = await failing(tester, outputs: outputs);

        await tester.runAsync(() async {
          await _photo(rig).pick(ImageSource.gallery);
          await _photo(rig).pick(ImageSource.gallery);
        });

        expect(outputs, hasLength(2));
        expect(File(outputs[0]).existsSync(), isFalse, reason: 'superseded');
        expect(File(outputs[1]).existsSync(), isTrue, reason: 'still pending');
      });

      testWidgets('discarded', (tester) async {
        final outputs = <String>[];
        final rig = await failing(tester, outputs: outputs);

        await tester.runAsync(() async {
          await _photo(rig).pick(ImageSource.gallery);
          await _photo(rig).discard();
        });

        expect(File(outputs.single).existsSync(), isFalse);
      });

      testWidgets('uploaded', (tester) async {
        final outputs = <String>[];
        final backend = FakeBackend()
          ..on('PUT', _put, FakeResponse(200, photoActive()));
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile()),
          preparer: preparerWriting(jpegBytes, outputs: outputs),
        );
        await rig.start(tester);

        await tester.runAsync(() => _photo(rig).pick(ImageSource.gallery));

        expect(File(outputs.single).existsSync(), isFalse);
      });

      testWidgets(
        'removed with the photo, so a stale failed pick is gone too',
        (tester) async {
          final outputs = <String>[];
          final rig = await failing(tester, outputs: outputs);
          rig.backend.on('DELETE', _put, const FakeResponse(204));

          await tester.runAsync(() async {
            await _photo(rig).pick(ImageSource.gallery);
            await _photo(rig).remove();
          });

          expect(File(outputs.single).existsSync(), isFalse);
        },
      );

      testWidgets('signing out', (tester) async {
        final outputs = <String>[];
        final rig = await failing(tester, outputs: outputs);
        rig.backend.on(
          'POST',
          '/api/auth/sign-out',
          const FakeResponse(200, {}),
        );

        await tester.runAsync(() async {
          await _photo(rig).pick(ImageSource.gallery);
          expect(File(outputs.single).existsSync(), isTrue);
          await rig.container.read(sessionProvider.notifier).signOut();
        });
        await tester.pump();

        expect(File(outputs.single).existsSync(), isFalse);
      });

      testWidgets('the end of the session', (tester) async {
        final outputs = <String>[];
        final rig = await failing(tester, outputs: outputs);

        await tester.runAsync(() => _photo(rig).pick(ImageSource.gallery));
        expect(File(outputs.single).existsSync(), isTrue);
        rig.container.dispose();

        expect(File(outputs.single).existsSync(), isFalse);
      });

      testWidgets('signing out mid-upload waits for the upload to let go', (
        tester,
      ) async {
        final held = await _gate<FakeResponse>(tester);
        final outputs = <String>[];
        final backend = FakeBackend()
          ..handle('PUT', _put, (_) => held.future)
          ..on('POST', '/api/auth/sign-out', const FakeResponse(200, {}));
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile()),
          preparer: preparerWriting(jpegBytes, outputs: outputs),
        );
        await rig.start(tester);

        await tester.runAsync(() async {
          final pick = _photo(rig).pick(ImageSource.gallery);
          await _until(() => backend.to('PUT', _put).isNotEmpty);
          await rig.container.read(sessionProvider.notifier).signOut();
          expect(
            File(outputs.single).existsSync(),
            isTrue,
            reason: 'the request may still be reading it',
          );
          held.complete(FakeResponse(200, photoActive()));
          await pick;
        });

        expect(
          File(outputs.single).existsSync(),
          isFalse,
          reason: 'deleted once the upload had finished with it',
        );
      });
    });
  });
}
