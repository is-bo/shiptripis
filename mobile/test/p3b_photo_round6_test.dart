/// P3B, round six: the findings of the independent review of the fifth round.
///
/// * **A result the phone restored is bound to no launch and is dropped at the
///   source.** The Dart side announces each launch on `wassla/pick_launch`
///   (`PickLaunchGate.kt` holds the other half and has its own JUnit tests), and
///   the request codes the native gate lets through are pinned here against the
///   plugin's own source. A result is judged the moment the picker answers, not
///   after the marker's release has waited.
/// * **A press belongs to the published member.** The session stores the
///   credential generation with the account, so a press during a switch from A
///   to B never pairs A's id with B's generation, and a removal is checked like
///   an upload.
/// * **A refused tombstone commit does not stop a sign-out.**
///
/// Everything that waits on a held write or file runs on real time inside
/// `runAsync`, with completers made there.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/profile_photo_state.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/media/pick_guard.dart';
import 'package:shiptrip/core/session/pending_pick_store.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/token_store.dart';

import 'support/fake_api.dart';
import 'support/fake_image_picker.dart';
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

ProfilePhotoController _photo(PhotoRig rig) =>
    rig.container.read(profilePhotoProvider.notifier);

/// A guard that announces its launches, over a container of its own.
({PickGuard guard, FakeImagePicker picker}) _announcingGuard(
  FakeTokenStore tokens, {
  DateTime Function()? now,
}) {
  final picker = FakeImagePicker();
  final provider = Provider<PickGuard>(
    (ref) => PickGuard(ref, now: now, nativeLaunchGate: true),
  );
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      imagePickerProvider.overrideWithValue(picker),
    ],
  );
  addTearDown(container.dispose);
  return (guard: container.read(provider), picker: picker);
}

/// Records every call on `wassla/pick_launch` into [log]; [refuse] names the
/// calls that fail like a native side that errored.
void _listenToLaunches(
  WidgetTester tester,
  List<String> log, {
  Set<String> refuse = const {},
}) {
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    _launchChannel,
    (call) async {
      log.add(call.method);
      if (refuse.contains(call.method)) {
        throw PlatformException(code: 'gate', message: 'refused');
      }
      return null;
    },
  );
  addTearDown(
    () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      _launchChannel,
      null,
    ),
  );
}

/// A keystore whose pick release can run something while it waits: the moment a
/// real store spends on the disk.
class _SlowReleaseStore extends FakeTokenStore {
  void Function()? whileReleasing;

  @override
  Future<void> releasePendingPick(String marker) async {
    whileReleasing?.call();
    await super.releasePendingPick(marker);
  }
}

/// A marker store that refuses the tombstone, as a disk that cannot commit.
class _RefusingTombstone implements PendingPickStore {
  int closes = 0;

  @override
  Future<String?> read() async => 'profilePhoto:abc';

  @override
  Future<String?> exchange(String marker) async => null;

  @override
  Future<void> release(String marker) async {}

  @override
  Future<void> closeBySignOut() async {
    closes++;
    throw PlatformException(code: 'storage', message: 'commit failed');
  }
}

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

FakeResponse _signInAs(int id, String name) => FakeResponse(200, {
  'access': 'access-$id',
  'refresh': 'refresh-$id',
  'user': {...meFixture(), 'id': id, 'full_name': name},
});

void main() {
  // ---------------------------------------------------------------------------
  group('1. a restored result is bound to no launch', () {
    testWidgets('the launch is announced before the picker opens, and ended '
        'after it answers', (tester) async {
      final log = <String>[];
      _listenToLaunches(tester, log);
      final (:guard, :picker) = _announcingGuard(FakeTokenStore());
      picker.onPick = (_) async {
        log.add('picker');
        return null;
      };

      await tester.runAsync(
        () => guard.pickImage(
          PickPurpose.profilePhoto,
          source: ImageSource.gallery,
        ),
      );

      expect(log, ['opened', 'picker', 'closed']);
    });

    testWidgets('a picker that throws still ends the launch', (tester) async {
      final log = <String>[];
      _listenToLaunches(tester, log);
      final (:guard, :picker) = _announcingGuard(FakeTokenStore());
      picker.onPick = (_) async =>
          throw PlatformException(code: 'camera_access_denied');

      await tester.runAsync(() async {
        await expectLater(
          guard.pickImage(PickPurpose.profilePhoto, source: ImageSource.camera),
          throwsA(isA<PlatformException>()),
        );
      });

      expect(log, ['opened', 'closed']);
    });

    testWidgets('a native side that refuses the opening opens no picker', (
      tester,
    ) async {
      final log = <String>[];
      _listenToLaunches(tester, log, refuse: {'opened'});
      final tokens = FakeTokenStore();
      final (:guard, :picker) = _announcingGuard(tokens);

      await tester.runAsync(() async {
        await expectLater(
          guard.pickImage(
            PickPurpose.profilePhoto,
            source: ImageSource.gallery,
          ),
          throwsA(isA<PickBlockedException>()),
        );
      });

      expect(picker.picks, isEmpty, reason: 'a launch the gate does not know');
      expect(tokens.pendingPick, isNull, reason: 'the marker was released');
      expect(guard.busy, isFalse);
    });

    testWidgets('a refusal of the closing does not fail the pick', (
      tester,
    ) async {
      final log = <String>[];
      _listenToLaunches(tester, log, refuse: {'closed'});
      final (:guard, :picker) = _announcingGuard(FakeTokenStore());

      final picked = await tester.runAsync(
        () => guard.pickImage(
          PickPurpose.profilePhoto,
          source: ImageSource.gallery,
        ),
      );

      expect(picked, isNull, reason: 'the member picked nothing');
      expect(log, ['opened', 'closed']);
    });

    testWidgets('a pick the caller no longer wants announces nothing', (
      tester,
    ) async {
      final log = <String>[];
      _listenToLaunches(tester, log);
      final (:guard, :picker) = _announcingGuard(FakeTokenStore());

      await tester.runAsync(
        () => guard.run(
          PickPurpose.profilePhoto,
          () async => throw StateError('must not open'),
          proceed: () => false,
        ),
      );

      expect(log, isEmpty);
      expect(picker.picks, isEmpty);
    });

    testWidgets('without the native gate nothing is announced', (tester) async {
      final log = <String>[];
      _listenToLaunches(tester, log);
      final picker = FakeImagePicker();
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(FakeTokenStore()),
          imagePickerProvider.overrideWithValue(picker),
        ],
      );
      addTearDown(container.dispose);

      await tester.runAsync(
        () => container
            .read(pickGuardProvider)
            .pickImage(PickPurpose.itemPhoto, source: ImageSource.gallery),
      );

      expect(picker.picks, hasLength(1));
      expect(log, isEmpty, reason: 'this host is not Android');
    });

    test('the request codes the native gate knows are the plugin\'s own', () {
      final plugin = _pluginSource('image_picker_android');
      final java = File(
        '$plugin/android/src/main/java/io/flutter/plugins/imagepicker/'
        'ImagePickerDelegate.java',
      ).readAsStringSync();
      // The codes a picker is launched with. The two permission codes are
      // answered through another callback and are not results of a launch.
      final pluginCodes = RegExp(
        r'static final int REQUEST_CODE_\w+ = (\d+);',
      ).allMatches(java).map((m) => int.parse(m.group(1)!)).toSet();
      final kotlin = File(
        'android/app/src/main/kotlin/eu/wassla/app/PickLaunchGate.kt',
      ).readAsStringSync();
      final listed = RegExp(
        r'PICKER_REQUEST_CODES: Set<Int> = setOf\(([^)]*)\)',
      ).firstMatch(kotlin)!.group(1)!;
      final gateCodes = listed
          .split(',')
          .map((code) => int.parse(code.trim()))
          .toSet();

      expect(pluginCodes, isNotEmpty);
      expect(gateCodes, pluginCodes);
    });

    test('the pinned plugin is the one the gate was written for', () {
      expect(
        _pluginSource('image_picker_android'),
        contains('image_picker_android-0.8.13+21'),
      );
    });
  });

  // ---------------------------------------------------------------------------
  group('2. a result is judged when the picker answers', () {
    testWidgets('a window that ends while the marker is released does not '
        'make the result believable', (tester) async {
      var now = DateTime(2026, 11, 26, 12);
      final tokens = _SlowReleaseStore()..pendingPick = 'identityDocument:old';
      _listenToLaunches(tester, <String>[]);
      final (:guard, :picker) = _announcingGuard(tokens, now: () => now);
      final first = sourceFile(name: 'first.jpg');
      final second = sourceFile(name: 'second.jpg');
      final answers = [first, second];
      picker.onPick = (_) async => XFile(answers.removeAt(0));

      await tester.runAsync(() async {
        // The stale marker taints the first pick and opens the window.
        await expectLater(
          guard.pickImage(PickPurpose.itemPhoto, source: ImageSource.gallery),
          throwsA(isA<PickBlockedException>()),
        );
        // The second picker answers 29 s into the window; the marker's release
        // then takes long enough to pass the window's end.
        now = now.add(const Duration(seconds: 29));
        tokens.whileReleasing = () => now = now.add(const Duration(seconds: 5));
        await expectLater(
          guard.pickImage(PickPurpose.itemPhoto, source: ImageSource.gallery),
          throwsA(
            isA<PickBlockedException>().having(
              (e) => e.uncertain,
              'uncertain',
              true,
            ),
          ),
          reason: 'it answered inside the window',
        );
      });

      expect(File(second).existsSync(), isFalse, reason: 'deleted, not kept');
    });
  });

  // ---------------------------------------------------------------------------
  group('3. a press belongs to the published member', () {
    testWidgets('a restored session publishes the generation it was read '
        'under, and so does a sign-in', (tester) async {
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(backend);
      await rig.start(tester);

      SessionSignedIn published() =>
          rig.container.read(sessionProvider) as SessionSignedIn;
      expect(published().identity, rig.tokenStore.identityGeneration);

      await tester.runAsync(
        () => rig.container
            .read(sessionProvider.notifier)
            .signIn(email: 'b@example.test', password: 'password-b'),
      );

      expect(published().account.id, 99);
      expect(published().identity, rig.tokenStore.identityGeneration);
    });

    testWidgets('a press while A is being replaced by B opens no picker and '
        'sends nothing', (tester) async {
      final held = await _gate<FakeResponse>(tester);
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('a-photo')))
        ..on('DELETE', _put, const FakeResponse(204))
        ..handle('POST', '/api/auth/sign-in', (_) => held.future);
      final picker = FakeImagePicker(onPick: null);
      final file = sourceFile();
      picker.onPick = (_) async => XFile(file);
      final rig = PhotoRig(backend, imagePicker: picker);
      await rig.start(tester);

      await tester.runAsync(() async {
        // B's sign-in starts: the store's generation moves at once, and A is
        // still the published member.
        final signIn = rig.container
            .read(sessionProvider.notifier)
            .signIn(email: 'b@example.test', password: 'password-b');
        await _until(() => backend.to('POST', '/api/auth/sign-in').isNotEmpty);
        expect(rig.account.id, 42, reason: 'A is still published');

        final picked = await _photo(rig).pick(ImageSource.gallery);
        final removed = await _photo(rig).remove();

        expect(picked, isFalse);
        expect(removed, isNull);
        held.complete(_signInAs(99, 'Karim Hadj'));
        await signIn;
      });

      expect(picker.picks, isEmpty, reason: 'no picker for A under B\'s login');
      expect(backend.to('PUT', _put), isEmpty);
      expect(backend.to('DELETE', _put), isEmpty);
      expect(
        rig.container.read(profilePhotoProvider),
        const ProfilePhotoState(),
        reason: 'not stuck busy',
      );
    });

    testWidgets('B can use the photo flow once the sign-in settled', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('b-photo')))
        ..on('POST', '/api/auth/sign-in', _signInAs(99, 'Karim Hadj'));
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.start(tester);

      final saved = await tester.runAsync(() async {
        await rig.container
            .read(sessionProvider.notifier)
            .signIn(email: 'b@example.test', password: 'password-b');
        return _photo(rig).pick(ImageSource.gallery);
      });

      expect(saved, isTrue);
      expect(backend.to('PUT', _put), hasLength(1));
    });

    testWidgets('a removal after a sign-out sends nothing', (tester) async {
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204));
      final rig = PhotoRig(backend);
      await rig.start(tester);
      final session = rig.container.read(sessionProvider.notifier);
      final pressed = rig.tokenStore.identityGeneration;
      rig.tokenStore.invalidateIdentity();

      await tester.runAsync(() async {
        await expectLater(
          session.removePhoto(expectedIdentity: pressed),
          throwsA(isA<ApiException>()),
        );
      });

      expect(backend.to('DELETE', _put), isEmpty);
    });
  });

  // ---------------------------------------------------------------------------
  group('4. a refused tombstone commit does not stop a sign-out', () {
    testWidgets('the credentials go and the expiry follows', (tester) async {
      final storage = _Storage();
      final marker = _RefusingTombstone();
      final tokens = TokenStore(storage, marker);
      await tester.runAsync(() async {
        await tokens.save(access: 'a', refresh: 'r');
        expect(storage.values, isNotEmpty);

        final generation = tokens.identityGeneration;
        expect(await tokens.clearIfIdentityCurrent(generation), isTrue);
        expect(storage.values, isEmpty, reason: 'the credentials are gone');
        expect(marker.closes, 1, reason: 'the tombstone was tried');

        await tokens.save(access: 'a', refresh: 'r');
        await tokens.clear();
        expect(storage.values, isEmpty);
        expect(marker.closes, 2);
      });
    });
  });
}

/// The directory of the pinned plugin [name], from the package configuration.
String _pluginSource(String name) {
  final config =
      jsonDecode(File('.dart_tool/package_config.json').readAsStringSync())
          as Map<String, dynamic>;
  final package = (config['packages'] as List)
      .cast<Map<String, dynamic>>()
      .firstWhere((p) => p['name'] == name);
  final root = Uri.parse(package['rootUri'] as String);
  final base = Uri.file('${Directory.current.path}/.dart_tool/');
  return Directory.fromUri(base.resolveUri(root)).path;
}
