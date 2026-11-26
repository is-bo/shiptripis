/// P3B, round five: the findings of the independent review of the fourth round.
///
/// * **One pick at a time, for every purpose.** A second tap while the first is
///   still being given its marker opens nothing and leaves the first's marker
///   where it is.
/// * **Every caller gets only a result that is provably its own.** The guard
///   throws an uncertain result away before it is returned, so a parcel photo
///   pick can never stage a restored identity document.
/// * **The marker is only trusted when its write reached the disk**, and a
///   sign-out while the marker is written opens no picker.
/// * **A retry is bound to the session that prepared the photo**, not to
///   whoever is signed in when the button is pressed.
/// * **Only the operation that owns the state ever starts it over.**
///
/// Everything that waits on a held write or file runs on real time inside
/// `runAsync`, with completers made there.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/profile_photo_state.dart';
import 'package:shiptrip/core/media/pick_guard.dart';
import 'package:shiptrip/core/session/pending_pick_store.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/token_store.dart';

import 'support/fake_api.dart';
import 'support/fake_image_picker.dart';
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

ProfilePhotoController _photo(PhotoRig rig) =>
    rig.container.read(profilePhotoProvider.notifier);

/// A keystore whose marker exchange can be held *after* it has written: the
/// moment a real store spends waiting on the disk.
class _HeldExchangeStore extends FakeTokenStore {
  Completer<void>? hold;
  Completer<void>? reached;
  int exchanges = 0;

  @override
  Future<({bool applied, String? previous})> exchangePendingPick(
    String marker, {
    required int expectedIdentityGeneration,
  }) async {
    exchanges++;
    final answer = await super.exchangePendingPick(
      marker,
      expectedIdentityGeneration: expectedIdentityGeneration,
    );
    final gate = hold;
    if (gate != null) {
      hold = null;
      reached?.complete();
      await gate.future;
    }
    return answer;
  }
}

ProviderContainer _guardContainer(
  FakeTokenStore tokens,
  FakeImagePicker picker,
) {
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      imagePickerProvider.overrideWithValue(picker),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

/// Secure storage in memory.
class _Storage extends FlutterSecureStorage {
  _Storage();

  final values = <String, String>{};

  @override
  Future<String?> read({
    required String key,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => values[key];

  @override
  Future<void> write({
    required String key,
    required String? value,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }

  @override
  Future<void> delete({
    required String key,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    values.remove(key);
  }
}

void main() {
  // ---------------------------------------------------------------------------
  group('1. one pick at a time, whatever its purpose', () {
    testWidgets(
      'two identity-check taps while the first awaits storage open one picker',
      (tester) async {
        final hold = await _gate<void>(tester);
        final reached = await _gate<void>(tester);
        final tokens = _HeldExchangeStore()
          ..hold = hold
          ..reached = reached;
        final picker = FakeImagePicker();
        final guard = _guardContainer(tokens, picker).read(pickGuardProvider);
        final open = await _gate<XFile?>(tester);
        picker.onPick = (_) => open.future;

        await tester.runAsync(() async {
          final first = guard.pickImage(
            PickPurpose.identityDocument,
            source: ImageSource.gallery,
          );
          await reached.future;
          final firstMarker = tokens.pendingPick;
          expect(firstMarker, startsWith('identityDocument:'));

          // The second tap arrives while the first is still being given its
          // marker. It finds the guard taken: no storage, no picker.
          final second = await guard.pickImage(
            PickPurpose.identityDocument,
            source: ImageSource.camera,
          );
          expect(second, isNull);
          expect(tokens.exchanges, 1, reason: 'the marker was not replaced');
          expect(tokens.pendingPick, firstMarker, reason: 'owner untouched');

          hold.complete();
          await _until(() => picker.picks.isNotEmpty);
          expect(picker.picks, [ImageSource.gallery], reason: 'one picker');
          expect(
            tokens.pendingPick,
            firstMarker,
            reason: 'the first pick still owns the open picker',
          );

          open.complete(null);
          await first;
          expect(tokens.pendingPick, isNull, reason: 'the owner cleared it');
        });
      },
    );

    testWidgets(
      'a pick of another purpose waits for nobody and opens nothing',
      (tester) async {
        final tokens = FakeTokenStore();
        final picker = FakeImagePicker();
        final guard = _guardContainer(tokens, picker).read(pickGuardProvider);
        final open = await _gate<XFile?>(tester);
        picker.onPick = (_) => open.future;

        await tester.runAsync(() async {
          final first = guard.pickVideo(
            PickPurpose.disputeEvidence,
            source: ImageSource.gallery,
          );
          await _until(() => picker.picks.isNotEmpty);
          expect(guard.busy, isTrue);

          final profile = await guard.run(
            PickPurpose.profilePhoto,
            () async => throw StateError('must not open'),
          );

          expect(profile, isNull);
          expect(picker.picks, hasLength(1));
          open.complete(null);
          await first;
          expect(guard.busy, isFalse, reason: 'free again');
        });
      },
    );

    testWidgets('a pick that fails frees the guard', (tester) async {
      final tokens = FakeTokenStore()..pendingPickWritesFail = true;
      final guard = _guardContainer(
        tokens,
        FakeImagePicker(),
      ).read(pickGuardProvider);

      await tester.runAsync(() async {
        await expectLater(
          guard.pickImage(PickPurpose.itemPhoto, source: ImageSource.gallery),
          throwsA(isA<PickBlockedException>()),
        );
        expect(guard.busy, isFalse);
        tokens.pendingPickWritesFail = false;
        expect(
          await guard.pickImage(
            PickPurpose.itemPhoto,
            source: ImageSource.gallery,
          ),
          isNull,
          reason: 'the next pick runs (and the member closed the picker)',
        );
      });
    });
  });

  // ---------------------------------------------------------------------------
  group('2. a result that may belong to another pick is never returned', () {
    for (final purpose in [
      PickPurpose.itemPhoto,
      PickPurpose.ticketProof,
      PickPurpose.payoutCheque,
      PickPurpose.identityDocument,
    ]) {
      testWidgets('${purpose.name}: a stale marker means no file', (
        tester,
      ) async {
        final file = sourceFile(name: 'restored-id.jpg');
        final tokens = FakeTokenStore()..pendingPick = 'identityDocument:old';
        final picker = FakeImagePicker()..onPick = (_) async => XFile(file);
        final guard = _guardContainer(tokens, picker).read(pickGuardProvider);

        await tester.runAsync(() async {
          await expectLater(
            guard.pickImage(purpose, source: ImageSource.gallery),
            throwsA(
              isA<PickBlockedException>().having(
                (e) => e.uncertain,
                'uncertain',
                isTrue,
              ),
            ),
          );
        });

        expect(File(file).existsSync(), isFalse, reason: 'thrown away');
        expect(tokens.pendingPick, isNull, reason: 'the pick still ended');
      });
    }

    testWidgets('a video is held to the same rule', (tester) async {
      final file = sourceFile(name: 'restored.mp4');
      final tokens = FakeTokenStore()..pendingPick = 'ticketProof:old';
      final picker = FakeImagePicker()..onPick = (_) async => XFile(file);
      final guard = _guardContainer(tokens, picker).read(pickGuardProvider);

      await tester.runAsync(
        () => expectLater(
          guard.pickVideo(
            PickPurpose.disputeEvidence,
            source: ImageSource.gallery,
          ),
          throwsA(isA<PickBlockedException>()),
        ),
      );

      expect(File(file).existsSync(), isFalse);
    });

    testWidgets('a lost result found at the start taints the pick', (
      tester,
    ) async {
      final lost = sourceFile(name: 'lost.jpg');
      final answer = sourceFile(name: 'answer.jpg');
      final picker = FakeImagePicker(lost: XFile(lost))
        ..onPick = (_) async => XFile(answer);
      final guard = _guardContainer(
        FakeTokenStore(),
        picker,
      ).read(pickGuardProvider);

      await tester.runAsync(
        () => expectLater(
          guard.pickImage(PickPurpose.itemPhoto, source: ImageSource.gallery),
          throwsA(isA<PickBlockedException>()),
        ),
      );

      expect(File(lost).existsSync(), isFalse, reason: 'consumed, deleted');
      expect(File(answer).existsSync(), isFalse);
    });

    testWidgets('a clean pick returns its file', (tester) async {
      final file = sourceFile();
      final picker = FakeImagePicker()..onPick = (_) async => XFile(file);
      final guard = _guardContainer(
        FakeTokenStore(),
        picker,
      ).read(pickGuardProvider);

      final picked = await tester.runAsync(
        () =>
            guard.pickImage(PickPurpose.itemPhoto, source: ImageSource.gallery),
      );

      expect(picked?.path, file);
      expect(File(file).existsSync(), isTrue);
    });
  });

  // ---------------------------------------------------------------------------
  group('3. a sign-out while the marker is written opens no picker', () {
    testWidgets(
      'at the guard: the picker never opens and the file is refused',
      (tester) async {
        final hold = await _gate<void>(tester);
        final reached = await _gate<void>(tester);
        final tokens = _HeldExchangeStore()
          ..hold = hold
          ..reached = reached;
        final picker = FakeImagePicker();
        final guard = _guardContainer(tokens, picker).read(pickGuardProvider);

        await tester.runAsync(() async {
          final pick = guard.pickImage(
            PickPurpose.identityDocument,
            source: ImageSource.camera,
          );
          await reached.future;
          tokens.invalidateIdentity(); // the member signed out
          hold.complete();

          expect(await pick, isNull);
        });

        expect(
          picker.picks,
          isEmpty,
          reason: 'no camera for a member who left',
        );
        expect(
          tokens.pendingPick,
          isNull,
          reason: 'the pick released its marker',
        );
      },
    );

    testWidgets(
      'on the profile photo: the flow starts over and opens nothing',
      (tester) async {
        final hold = await _gate<void>(tester);
        final reached = await _gate<void>(tester);
        final tokens = _HeldExchangeStore()
          ..hold = hold
          ..reached = reached;
        final picker = FakeImagePicker();
        final backend = FakeBackend();
        final rig = PhotoRig(backend, tokens: tokens, imagePicker: picker);
        await rig.start(tester);

        await tester.runAsync(() async {
          final pick = _photo(rig).pick(ImageSource.camera);
          await reached.future;
          tokens.invalidateIdentity();
          hold.complete();
          expect(await pick, isFalse);
        });

        expect(picker.picks, isEmpty);
        expect(backend.to('PUT', _put), isEmpty);
        expect(
          rig.container.read(profilePhotoProvider),
          const ProfilePhotoState(),
          reason: 'not stuck busy',
        );
      },
    );

    testWidgets('a photo that arrives after the sign-out is deleted unseen', (
      tester,
    ) async {
      final open = await _gate<XFile?>(tester);
      final file = sourceFile();
      final tokens = FakeTokenStore();
      final picker = FakeImagePicker()..onPick = (_) => open.future;
      final guard = _guardContainer(tokens, picker).read(pickGuardProvider);

      await tester.runAsync(() async {
        final pick = guard.pickImage(
          PickPurpose.ticketProof,
          source: ImageSource.gallery,
        );
        await _until(() => picker.picks.isNotEmpty);
        tokens.invalidateIdentity();
        open.complete(XFile(file));
        expect(await pick, isNull);
      });

      expect(File(file).existsSync(), isFalse);
    });
  });

  // ---------------------------------------------------------------------------
  group('4. a retry belongs to the session that prepared the photo', () {
    const storageDown = FakeResponse(503, {
      'code': 'profile_photo_storage_unavailable',
    });

    testWidgets(
      'B\'s tokens saved but B not yet published: A\'s file is not sent',
      (tester) async {
        final backend = FakeBackend()..on('PUT', _put, storageDown);
        final outputs = <String>[];
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile()),
          preparer: preparerWriting(jpegBytes, outputs: outputs),
        );
        await rig.start(tester);

        await tester.runAsync(() async {
          expect(await _photo(rig).pick(ImageSource.gallery), isFalse);
        });
        expect(
          rig.container.read(profilePhotoProvider).failure,
          ProfilePhotoFailure.storageUnavailable,
        );
        expect(backend.to('PUT', _put), hasLength(1));

        // B signs in: B's tokens are saved (the credential generation moves)
        // while B's role-context write is still held, so the session still
        // says member 42 (A). Pressing "try again" now must not send A's file
        // with B's bearer.
        rig.tokenStore.invalidateIdentity();
        expect(rig.account.id, 42, reason: 'B is not published yet');
        final again = await tester.runAsync(() => _photo(rig).upload());

        expect(again, isFalse);
        expect(backend.to('PUT', _put), hasLength(1), reason: 'never re-sent');
        expect(
          rig.container.read(profilePhotoProvider),
          const ProfilePhotoState(),
          reason: 'the photo was A\'s and is gone',
        );
        expect(
          File(outputs.single).existsSync(),
          isFalse,
          reason: 'A\'s prepared file is deleted',
        );
      },
    );

    testWidgets('the same session may retry as often as it likes', (
      tester,
    ) async {
      var attempts = 0;
      final backend = FakeBackend()
        ..handle('PUT', _put, (_) {
          attempts++;
          return attempts == 1
              ? storageDown
              : FakeResponse(200, photoActive('v8'));
        });
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.start(tester);

      await tester.runAsync(() async {
        expect(await _photo(rig).pick(ImageSource.gallery), isFalse);
        expect(await _photo(rig).upload(), isTrue);
      });

      expect(attempts, 2);
      expect(rig.account.photo?.version, 'v8');
    });

    testWidgets('a retry after the credentials were replaced is refused', (
      tester,
    ) async {
      // Same member, new credentials (a sign-in again): the file was prepared
      // under the old ones, so it is not sent under the new.
      final backend = FakeBackend()..on('PUT', _put, storageDown);
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.start(tester);
      await tester.runAsync(() => _photo(rig).pick(ImageSource.gallery));

      rig.tokenStore.invalidateIdentity();
      final again = await tester.runAsync(() => _photo(rig).upload());

      expect(again, isFalse);
      expect(backend.to('PUT', _put), hasLength(1));
    });
  });

  // ---------------------------------------------------------------------------
  group('5. only the operation that owns the state starts it over', () {
    testWidgets(
      'a step of an older press cannot reset the press that followed it',
      (tester) async {
        // Press one is preparing its photo when the account changes and then
        // comes back as the same member (here: the flow is discarded). Press
        // two begins. Press one's preparation then finishes and finds itself
        // not live: it must delete its own file and leave press two alone.
        final firstGate = await _gate<void>(tester);
        final secondGate = await _gate<void>(tester);
        final outputs = <String>[];
        final inner = preparerWriting(jpegBytes, outputs: outputs);
        var calls = 0;
        final backend = FakeBackend()
          ..on('PUT', _put, FakeResponse(200, photoActive('v5')));
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile()),
          preparer: (source) async {
            final call = ++calls;
            final out = await inner(source);
            await (call == 1 ? firstGate : secondGate).future;
            return out;
          },
        );
        await rig.start(tester);

        await tester.runAsync(() async {
          final one = _photo(rig).pick(ImageSource.gallery);
          await _until(() => outputs.isNotEmpty);
          await _photo(rig).discard();

          final two = _photo(rig).pick(ImageSource.gallery);
          await _until(() => outputs.length == 2);

          firstGate.complete();
          expect(await one, isFalse);
          expect(
            rig.container.read(profilePhotoProvider).uploading,
            isTrue,
            reason: 'press two is still preparing, untouched',
          );
          expect(File(outputs.first).existsSync(), isFalse, reason: 'its own');

          secondGate.complete();
          expect(await two, isTrue);
        });

        expect(backend.to('PUT', _put), hasLength(1));
        expect(rig.account.photo?.version, 'v5');
      },
    );

    testWidgets('a discard detaches the photo at once', (tester) async {
      final backend = FakeBackend()
        ..on(
          'PUT',
          _put,
          const FakeResponse(503, {
            'code': 'profile_photo_storage_unavailable',
          }),
        );
      final outputs = <String>[];
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(sourceFile()),
        preparer: preparerWriting(jpegBytes, outputs: outputs),
      );
      await rig.start(tester);
      await tester.runAsync(() => _photo(rig).pick(ImageSource.gallery));
      expect(rig.container.read(profilePhotoProvider).picked, isNotNull);

      Future<void>? deleting;
      await tester.runAsync(() async {
        deleting = _photo(rig).discard();
        expect(
          rig.container.read(profilePhotoProvider),
          const ProfilePhotoState(),
          reason:
              'clean before the file is gone, so a new press keeps its state',
        );
        await deleting;
      });

      expect(File(outputs.single).existsSync(), isFalse);
    });
  });

  // ---------------------------------------------------------------------------
  group('6. the marker is committed, or no picker opens', () {
    late Map<String, String?> disk;
    late List<String> calls;
    bool diskRefuses = false;

    setUp(() {
      disk = {};
      calls = [];
      diskRefuses = false;
    });

    void install(WidgetTester tester) {
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('wassla/pick_marker'),
        (call) async {
          calls.add(call.method);
          final marker = (call.arguments as Map?)?['marker'] as String?;
          switch (call.method) {
            case 'exchange':
              if (diskRefuses) {
                throw PlatformException(
                  code: 'storage',
                  message: 'commit failed',
                );
              }
              final previous = disk['pick'];
              disk['pick'] = marker;
              return previous;
            case 'release':
              if (disk['pick'] == marker) disk.remove('pick');
              return null;
            case 'closeBySignOut':
              if (disk['pick'] != null) disk['pick'] = 'signed-out';
              return null;
            case 'read':
              return disk['pick'];
          }
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          const MethodChannel('wassla/pick_marker'),
          null,
        ),
      );
    }

    testWidgets('the committed store exchanges, releases and closes', (
      tester,
    ) async {
      install(tester);
      const store = CommittedPendingPickStore();

      expect(await store.exchange('profilePhoto:a'), isNull);
      expect(await store.exchange('itemPhoto:b'), 'profilePhoto:a');
      await store.release('profilePhoto:a');
      expect(await store.read(), 'itemPhoto:b', reason: 'not that pick\'s');
      await store.closeBySignOut();
      expect(await store.read(), 'signed-out');
      await store.release('signed-out');
      expect(await store.read(), isNull);
      expect(calls, [
        'exchange',
        'exchange',
        'release',
        'read',
        'closeBySignOut',
        'read',
        'release',
        'read',
      ]);
    });

    testWidgets('a write the disk refused opens no picker', (tester) async {
      install(tester);
      diskRefuses = true;
      final tokens = TokenStore(_Storage(), const CommittedPendingPickStore());
      final picker = FakeImagePicker(lost: XFile('/never/read.jpg'));
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          imagePickerProvider.overrideWithValue(picker),
        ],
      );
      addTearDown(container.dispose);

      await tester.runAsync(
        () => expectLater(
          container
              .read(pickGuardProvider)
              .pickImage(PickPurpose.profilePhoto, source: ImageSource.camera),
          throwsA(
            isA<PickBlockedException>().having(
              (e) => e.uncertain,
              'uncertain',
              isFalse,
            ),
          ),
        ),
      );

      expect(picker.picks, isEmpty, reason: 'no marker on disk, no picker');
      expect(picker.lostReads, 0);
      expect(disk, isEmpty);
    });

    testWidgets('sign-out through the token store leaves the bare tombstone', (
      tester,
    ) async {
      install(tester);
      final tokens = TokenStore(_Storage(), const CommittedPendingPickStore());
      await tokens.exchangePendingPick(
        'identityDocument:abc',
        expectedIdentityGeneration: tokens.identityGeneration,
      );

      await tokens.clear();

      expect(disk['pick'], 'signed-out');
      expect(await tokens.readPendingPick(), 'signed-out');
    });

    testWidgets('a change of identity writes nothing to the disk', (
      tester,
    ) async {
      install(tester);
      final tokens = TokenStore(_Storage(), const CommittedPendingPickStore());
      final generation = tokens.identityGeneration;
      tokens.invalidateIdentity();

      final result = await tokens.exchangePendingPick(
        'profilePhoto:a',
        expectedIdentityGeneration: generation,
      );

      expect(result.applied, isFalse);
      expect(calls, isEmpty);
    });
  });
}
