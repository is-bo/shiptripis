/// P3B, round four: the findings of the independent second pass of the third
/// round.
///
/// * **Markers.** A pick has a durable owner before its picker opens, the
///   marker changes only through one serialized queue shared with sign-out, and
///   a pick that cannot be given an owner opens nothing.
/// * **Account switch.** The credential generation read at the press goes with
///   the flow to the moment of dispatch; a sign-in whose tokens are saved while
///   the picker, the preparation or a file check is waiting ends the flow.
/// * **File waits.** After every wait on the file system the flow checks again
///   that it is still the press's own.
/// * **Launch confirmation.** A photo write that failed changed nothing, so the
///   launch confirmation still carries the server's photo.
/// * **Failures.** A decoder's refusal and a failed preparation are different
///   messages.
///
/// Everything that waits on a file or a held request runs on real time inside
/// `runAsync`, with completers made there.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/profile_photo_state.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/media/photo_prepare.dart';
import 'package:shiptrip/core/media/pick_guard.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/token_store.dart';
import 'package:shiptrip/domain/account.dart';

import 'support/fake_api.dart';
import 'support/fake_image_picker.dart';
import 'support/photo_rig.dart';

const _put = photoPut;
const _kPendingPick = 'media.pending_pick';

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

/// Secure storage in memory, with a write to one key that can be held.
class _Storage extends FlutterSecureStorage {
  _Storage();

  final values = <String, String>{};
  bool failWrites = false;
  Completer<void>? holdPickWrite;
  Completer<void>? pickWriteReached;

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
    if (failWrites) throw const _KeystoreRefused();
    final hold = holdPickWrite;
    if (key == _kPendingPick && hold != null) {
      // Only the first write is held.
      holdPickWrite = null;
      pickWriteReached?.complete();
      await hold.future;
    }
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

class _KeystoreRefused implements Exception {
  const _KeystoreRefused();
}

/// A file whose `exists()` waits for the test; everything else is the real file.
class _GatedFile implements File {
  _GatedFile(this._inner, this._gate);

  final File _inner;
  final Completer<void> _gate;

  @override
  String get path => _inner.path;

  @override
  Future<bool> exists() async {
    await _gate.future;
    return _inner.exists();
  }

  @override
  bool existsSync() => _inner.existsSync();

  @override
  Future<FileSystemEntity> delete({bool recursive = false}) =>
      _inner.delete(recursive: recursive);

  @override
  void deleteSync({bool recursive = false}) =>
      _inner.deleteSync(recursive: recursive);

  @override
  Future<int> length() => _inner.length();

  @override
  int lengthSync() => _inner.lengthSync();

  @override
  Future<RandomAccessFile> open({FileMode mode = FileMode.read}) =>
      _inner.open(mode: mode);

  @override
  Stream<List<int>> openRead([int? start, int? end]) =>
      _inner.openRead(start, end);

  @override
  Future<Uint8List> readAsBytes() => _inner.readAsBytes();

  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw UnimplementedError('${invocation.memberName} on a gated file');
}

base class _PlainIo extends IOOverrides {}

File _realFile(String path) =>
    IOOverrides.runWithIOOverrides(() => File(path), _PlainIo());

void main() {
  // ---------------------------------------------------------------------------
  group('2. the marker has a durable owner before a picker opens', () {
    test(
      'exchange answers the marker it replaced; release is conditional',
      () async {
        final tokens = TokenStore(_Storage());
        final generation = tokens.identityGeneration;

        final first = await tokens.exchangePendingPick(
          'ticketProof:a',
          expectedIdentityGeneration: generation,
        );
        final second = await tokens.exchangePendingPick(
          'profilePhoto:b',
          expectedIdentityGeneration: generation,
        );
        await tokens.releasePendingPick('ticketProof:a');
        final afterWrongRelease = await tokens.readPendingPick();
        await tokens.releasePendingPick('profilePhoto:b');

        expect(first, (applied: true, previous: null));
        expect(second, (applied: true, previous: 'ticketProof:a'));
        expect(afterWrongRelease, 'profilePhoto:b', reason: 'not that pick\'s');
        expect(await tokens.readPendingPick(), isNull);
      },
    );

    test(
      'a sign-in or sign-out since the guard looked writes nothing',
      () async {
        final storage = _Storage();
        final tokens = TokenStore(storage);
        final generation = tokens.identityGeneration;
        tokens.invalidateIdentity();

        final result = await tokens.exchangePendingPick(
          'profilePhoto:a',
          expectedIdentityGeneration: generation,
        );

        expect(result.applied, isFalse);
        expect(storage.values, isNot(contains(_kPendingPick)));
      },
    );

    test(
      'sign-out leaves a bare tombstone, which the next pick hears of',
      () async {
        final storage = _Storage();
        final tokens = TokenStore(storage);
        await tokens.exchangePendingPick(
          'identityDocument:abc',
          expectedIdentityGeneration: tokens.identityGeneration,
        );

        await tokens.clear();

        expect(storage.values[_kPendingPick], 'signed-out');
        expect(
          storage.values.values.join(),
          isNot(contains('identityDocument')),
        );
        final next = await tokens.exchangePendingPick(
          'profilePhoto:new',
          expectedIdentityGeneration: tokens.identityGeneration,
        );
        expect(next.previous, 'signed-out');
      },
    );

    test('sign-out with no pick open leaves nothing', () async {
      final storage = _Storage();
      final tokens = TokenStore(storage);

      await tokens.clear();

      expect(storage.values, isNot(contains(_kPendingPick)));
    });

    test(
      'a sign-out queued behind a marker write is applied after it',
      () async {
        final hold = Completer<void>();
        final storage = _Storage()
          ..holdPickWrite = hold
          ..pickWriteReached = Completer<void>();
        final tokens = TokenStore(storage);
        final generation = tokens.identityGeneration;

        final exchange = tokens.exchangePendingPick(
          'profilePhoto:a',
          expectedIdentityGeneration: generation,
        );
        await storage.pickWriteReached!.future;
        final signOut = tokens.clear();
        expect(storage.values, isNot(contains(_kPendingPick)));

        hold.complete();
        await exchange;
        await signOut;

        expect(
          storage.values[_kPendingPick],
          'signed-out',
          reason: 'the marker was written first and the sign-out came after it',
        );
      },
    );

    test(
      'storage that refuses a write opens no picker and reads nothing',
      () async {
        final storage = _Storage()..failWrites = true;
        final picker = FakeImagePicker(lost: XFile('/never/read.jpg'));
        final container = ProviderContainer(
          overrides: [
            tokenStoreProvider.overrideWithValue(TokenStore(storage)),
            imagePickerProvider.overrideWithValue(picker),
          ],
        );
        addTearDown(container.dispose);

        await expectLater(
          container
              .read(pickGuardProvider)
              .run(PickPurpose.profilePhoto, () async => XFile('/never.jpg')),
          throwsA(isA<PickBlockedException>()),
        );
        await expectLater(
          container
              .read(pickGuardProvider)
              .pickImage(
                PickPurpose.identityDocument,
                source: ImageSource.camera,
              ),
          throwsA(isA<PickBlockedException>()),
        );

        expect(picker.picks, isEmpty, reason: 'no marker, no picker');
        expect(picker.lostReads, 0);
        expect(picker.lost, isNotNull);
      },
    );
  });

  // ---------------------------------------------------------------------------
  group('4. a sign-in that lands while a step waits ends the flow', () {
    testWidgets('while the picker is open: nothing is prepared or sent', (
      tester,
    ) async {
      // Another member's tokens are saved (the credential generation moves)
      // while the role-context storage that would publish their account is
      // still being held: the account provider still says member 42.
      final open = await _gate<XFile?>(tester);
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('v2')));
      final prepared = <String>[];
      final rig = PhotoRig(
        backend,
        picker: (_) => open.future,
        preparer: preparerWriting(jpegBytes, calls: prepared),
      );
      await rig.start(tester);
      final file = sourceFile();

      await tester.runAsync(() async {
        final pick = _photo(rig).pick(ImageSource.gallery);
        await _until(() => rig.container.read(profilePhotoProvider).picking);
        rig.tokenStore.invalidateIdentity();
        expect(rig.account.id, 42, reason: 'the account has not moved yet');
        open.complete(XFile(file));
        expect(await pick, isFalse);
      });

      expect(prepared, isEmpty, reason: 'never prepared');
      expect(backend.to('PUT', _put), isEmpty, reason: 'never sent');
      expect(
        rig.container.read(profilePhotoProvider),
        const ProfilePhotoState(),
        reason: 'the flow starts over, not stuck busy',
      );
    });

    testWidgets('while the photo is prepared: the file goes, nothing is sent', (
      tester,
    ) async {
      final held = await _gate<void>(tester);
      final outputs = <String>[];
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('v2')));
      final inner = preparerWriting(jpegBytes, outputs: outputs);
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(sourceFile()),
        preparer: (source) async {
          final out = await inner(source);
          await held.future;
          return out;
        },
      );
      await rig.start(tester);

      await tester.runAsync(() async {
        final pick = _photo(rig).pick(ImageSource.gallery);
        await _until(() => outputs.isNotEmpty);
        rig.tokenStore.invalidateIdentity();
        held.complete();
        expect(await pick, isFalse);
      });

      expect(backend.to('PUT', _put), isEmpty);
      expect(File(outputs.single).existsSync(), isFalse, reason: 'deleted');
      expect(
        rig.container.read(profilePhotoProvider),
        const ProfilePhotoState(),
      );
    });

    testWidgets('a pick after the credentials settled works as usual', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('v3')));
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.start(tester);
      rig.tokenStore.invalidateIdentity();

      final saved = await tester.runAsync(
        () => _photo(rig).pick(ImageSource.gallery),
      );

      expect(saved, isTrue, reason: 'the generation is read at the press');
      expect(backend.to('PUT', _put), hasLength(1));
    });
  });

  // ---------------------------------------------------------------------------
  group('5. after a wait on a file, the flow checks it is still live', () {
    testWidgets(
      'a failed upload whose file check is overtaken by a sign-in writes nothing',
      (tester) async {
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
        final gate = await _gate<void>(tester);

        await tester.runAsync(() async {
          await IOOverrides.runZoned(
            () async {
              final pick = _photo(rig).pick(ImageSource.gallery);
              // The server refused with a retryable answer; the flow is now
              // asking whether the file is still there.
              await _until(() => backend.to('PUT', _put).isNotEmpty);
              await Future<void>.delayed(const Duration(milliseconds: 60));
              rig.tokenStore.invalidateIdentity();
              gate.complete();
              expect(await pick, isFalse);
            },
            createFile: (path) => outputs.isNotEmpty && path == outputs.single
                ? _GatedFile(_realFile(path), gate)
                : _realFile(path),
          );
        });

        expect(
          rig.container.read(profilePhotoProvider),
          const ProfilePhotoState(),
          reason: 'no retry notice for a flow that is no longer the member\'s',
        );
        expect(File(outputs.single).existsSync(), isFalse);
        expect(backend.to('PUT', _put), hasLength(1), reason: 'sent once');
      },
    );
  });

  // ---------------------------------------------------------------------------
  group('6. the launch confirmation after a failed photo write', () {
    testWidgets('still carries the server\'s photo and removal notice', (
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
        ..on('PUT', _put, const FakeResponse(500, {'code': 'server_error'}));
      final rig = PhotoRig(
        backend,
        tokens: FakeTokenStore(accountSnapshot: snapshot),
      );
      await rig.start(tester, restore: false);
      backend.handle('GET', '/api/me', (_) => held.future);
      final file = sourceFile();
      Object? failure;

      await tester.runAsync(() async {
        final session = rig.container.read(sessionProvider.notifier);
        await _until(() => rig.container.read(accountProvider) != null);
        expect(rig.account.photo, isNull, reason: 'the snapshot has no photo');
        try {
          await session.uploadPhoto(
            filePath: file,
            fileName: 'photo.jpg',
            contentType: 'image/jpeg',
            expectedIdentity: rig.tokenStore.identityGeneration,
          );
        } on ApiException catch (error) {
          failure = error;
        }
        // The confirmation lands after the failed write: the server has a photo.
        held.complete(
          FakeResponse(200, {
            ...meFixture(photo: photoActive('v7')),
            'full_name': 'Amina Bouzid',
          }),
        );
        await _until(() => rig.account.fullName == 'Amina Bouzid');
      });

      expect(failure, isA<ApiException>());
      expect(
        rig.account.photo?.version,
        'v7',
        reason: 'a write that failed changed nothing, so it decides nothing',
      );
    });

    testWidgets(
      'a removal notice from the server survives a failed write too',
      (tester) async {
        final held = await _gate<FakeResponse>(tester);
        final snapshot = jsonEncode(
          Account.fromJson(meFixture()).toSnapshotJson(),
        );
        final backend = FakeBackend()
          ..on(
            'DELETE',
            _put,
            const FakeResponse(500, {'code': 'server_error'}),
          );
        final rig = PhotoRig(
          backend,
          tokens: FakeTokenStore(accountSnapshot: snapshot),
        );
        await rig.start(tester, restore: false);
        backend.handle('GET', '/api/me', (_) => held.future);

        await tester.runAsync(() async {
          final session = rig.container.read(sessionProvider.notifier);
          await _until(() => rig.container.read(accountProvider) != null);
          try {
            await session.removePhoto();
          } on ApiException {
            // The server refused.
          }
          held.complete(
            FakeResponse(
              200,
              meFixture(photo: photoRemoved(reason: 'Not a face')),
            ),
          );
          await _until(() => rig.account.photo != null);
        });

        expect(rig.account.photo?.isRemoved, isTrue);
      },
    );
  });

  // ---------------------------------------------------------------------------
  group('11. a refusal of the picture and a failed preparation differ', () {
    testWidgets(
      'a decoder that refuses the file says the type is not accepted',
      (tester) async {
        final rig = PhotoRig(
          FakeBackend(),
          picker: pickerReturning(sourceFile()),
          preparer: (_) async => throw const UnsupportedPhoto(),
        );
        await rig.pump(tester);
        final l = rig.l(tester);

        await tester.tap(photoButton(l.profilePhotoChoose));
        await untilReached(
          tester,
          () => find.text(l.profilePhotoTypeNotAllowed).evaluate().isNotEmpty,
        );

        expect(find.text(l.profilePhotoPrepareFailed), findsNothing);
      },
    );

    testWidgets('a failed preparation says so, and the picture is not blamed', (
      tester,
    ) async {
      final rig = PhotoRig(
        FakeBackend(),
        picker: pickerReturning(sourceFile()),
        preparer: (_) async => throw const PhotoPrepareFailed(),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChoose));
      await untilReached(
        tester,
        () => find.text(l.profilePhotoPrepareFailed).evaluate().isNotEmpty,
      );

      expect(find.text(l.profilePhotoTypeNotAllowed), findsNothing);
    });

    testWidgets(
      'a prepared file that is not an image is a failed preparation',
      (tester) async {
        final rig = PhotoRig(
          FakeBackend(),
          picker: pickerReturning(sourceFile()),
          preparer: preparerWriting(gifBytes),
        );
        await rig.pump(tester);
        final l = rig.l(tester);

        await tester.tap(photoButton(l.profilePhotoChoose));
        await untilReached(
          tester,
          () => find.text(l.profilePhotoPrepareFailed).evaluate().isNotEmpty,
        );
      },
    );
  });
}
