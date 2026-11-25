/// P3B second pass: what happens to a photo between the picker and the server,
/// and to everything that shows the member's own photo afterwards.
///
/// Each group is one finding of the review. The real session, repository,
/// client, interceptor, providers and screen run over a fake server, so what is
/// asserted is what would reach Django and what the member would see.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/discovery_state.dart';
import 'package:shiptrip/app/profile_photo_state.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/components/sheets.dart' show AppSheet;
import 'package:shiptrip/features/discovery/browse_screens.dart';
import 'package:shiptrip/features/discovery/public_profile_screen.dart';
import 'package:shiptrip/features/profile/profile_photo_section.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';
import 'support/photo_cache.dart';
import 'support/photo_rig.dart';

const _put = photoPut;

Finder get _notice => find.byType(InfoNotice);

Future<void> _untilNotice(WidgetTester tester) =>
    untilReached(tester, () => _notice.evaluate().isNotEmpty);

/// Taps "Choose from library" and waits for the server to be asked.
Future<void> _chooseAndSend(
  WidgetTester tester,
  PhotoRig rig,
  FakeBackend backend,
) async {
  await tester.tap(photoButton(rig.l(tester).profilePhotoChoose));
  await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);
}

/// The path of the picture the preview draws, or null when none is drawn.
String? _previewPath(WidgetTester tester) {
  final images = find.descendant(
    of: find.byType(ProfilePhotoSection),
    matching: find.byType(Image),
  );
  if (images.evaluate().isEmpty) return null;
  var provider = tester.widget<Image>(images.first).image;
  // The preview decodes at its drawn width, so the file is wrapped.
  if (provider is ResizeImage) provider = provider.imageProvider;
  return provider is FileImage ? provider.file.path : null;
}

void main() {
  setUp(() => imageCache.clear());

  // ---------------------------------------------------------------------------
  group('3. an active photo the server could not sign', () {
    testWidgets('is still the member\'s photo: initials, change and remove', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final rig = PhotoRig(FakeBackend(), photo: photoActiveUnsigned());
      await rig.pump(tester);
      final l = rig.l(tester);

      expect(find.text('AB'), findsOneWidget);
      expect(find.byType(RawImage), findsNothing, reason: 'nothing to draw');
      expect(photoButton(l.profilePhotoChange), findsOneWidget);
      expect(photoButton(l.profilePhotoRemove), findsOneWidget);
      expect(photoButton(l.profilePhotoTake), findsNothing);
      expect(find.text(l.profilePhotoHelpActive), findsOneWidget);
    });

    testWidgets('a PUT answered with no address is a success', (tester) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActiveUnsigned('v7')));
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await _chooseAndSend(tester, rig, backend);
      await untilReached(
        tester,
        () => find.text(l.profilePhotoUpdated).evaluate().isNotEmpty,
      );

      expect(rig.account.photo?.version, 'v7');
      expect(rig.account.photo?.photo, isNull);
      expect(_notice, findsNothing, reason: 'not a malformed answer');
      expect(photoButton(l.profilePhotoChange), findsOneWidget);
    });
  });

  // ---------------------------------------------------------------------------
  group('4. a 401 on the photo PUT', () {
    testWidgets('refreshes the token but never sends the file again', (
      tester,
    ) async {
      var puts = 0;
      final backend = FakeBackend()
        ..handle('PUT', _put, (_) {
          puts++;
          return puts == 1
              ? const FakeResponse(401, {'detail': 'Token expired.'})
              : FakeResponse(200, photoActive());
        })
        ..on(
          'POST',
          '/api/auth/refresh',
          const FakeResponse(200, {'access': 'fresh-access'}),
        );
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await _chooseAndSend(tester, rig, backend);
      await _untilNotice(tester);

      // The token was refreshed, and that is all that happened.
      expect(backend.to('POST', '/api/auth/refresh'), hasLength(1));
      expect(backend.to('PUT', _put), hasLength(1));
      expect(find.text(l.profilePhotoFailed), findsOneWidget);
      expect(find.text(l.actionRetry), findsOneWidget);

      // Time passing never sends it.
      await tester.pump(const Duration(minutes: 5));
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 50)),
      );
      expect(backend.to('PUT', _put), hasLength(1));

      // The member's next press does, with the refreshed token.
      await tester.tap(find.text(l.actionRetry));
      await untilReached(tester, () => rig.account.photo != null);
      expect(backend.to('PUT', _put), hasLength(2));
    });

    testWidgets('a read that meets a 401 is still replayed', (tester) async {
      // Only the upload is exempt: the rule must not break ordinary reads.
      var reads = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/support', (_) {
          reads++;
          return reads == 1
              ? const FakeResponse(401, {'detail': 'Token expired.'})
              : const FakeResponse(200, {'email': 'help@example.test'});
        })
        ..on(
          'POST',
          '/api/auth/refresh',
          const FakeResponse(200, {'access': 'fresh-access'}),
        );
      final rig = PhotoRig(backend);
      await rig.start(tester);

      final answer = await tester.runAsync(
        () => rig.container.read(apiClientProvider).getObject('/api/support'),
      );

      expect(answer?['email'], 'help@example.test');
      expect(reads, 2);
    });
  });

  // ---------------------------------------------------------------------------
  group('5. a refusal is read by its status, not by its body', () {
    for (final (label, body) in [
      ('HTML', '<html><body>413 Request Entity Too Large</body></html>'),
      ('broken JSON', '{"code": "profile_photo_too_l'),
      ('an empty body', ''),
      ('JSON of another shape', '["too","large"]'),
    ]) {
      testWidgets('a 413 with $label is too large', (tester) async {
        final backend = FakeBackend()
          ..on('PUT', _put, FakeResponse.raw(413, body));
        final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
        await rig.pump(tester);
        final l = rig.l(tester);

        await _chooseAndSend(tester, rig, backend);
        await _untilNotice(tester);

        expect(find.text(l.profilePhotoTooLarge), findsOneWidget);
        expect(find.text(l.actionRetry), findsNothing);
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('a 502 from the proxy is a general failure with a retry', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse.raw(502, '<html>Bad gateway</html>'));
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await _chooseAndSend(tester, rig, backend);
      await _untilNotice(tester);

      expect(find.text(l.profilePhotoFailed), findsOneWidget);
      expect(find.text(l.actionRetry), findsOneWidget);
    });

    testWidgets('a 200 that is not JSON is a failure, not a photo', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse.raw(200, '<html>captive portal</html>'));
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester);

      await _chooseAndSend(tester, rig, backend);
      await _untilNotice(tester);

      expect(rig.account.photo, isNull);
      expect(find.text(rig.l(tester).profilePhotoFailed), findsOneWidget);
    });
  });

  // ---------------------------------------------------------------------------
  group('6. the member\'s own photo in other screens', () {
    Map<String, dynamic> ownProfile(Map<String, dynamic>? photo) => {
      ...ownProfileFixture(state: 'visible', discoverable: true),
      'card': profileCardFixture(id: 'me', name: 'Amina', photo: photo),
    };

    testWidgets('removing it refreshes the own profile read Home keeps', (
      tester,
    ) async {
      Map<String, dynamic>? shown = photoFixture('v1');
      final backend = FakeBackend()
        ..emptyDiscovery()
        ..handle(
          'GET',
          '/api/discovery/profile/me',
          (_) => FakeResponse(200, ownProfile(shown)),
        )
        ..handle('DELETE', _put, (_) {
          shown = null;
          return const FakeResponse(204);
        });
      final rig = PhotoRig(backend, photo: photoActive());
      await rig.start(tester);
      // Home keeps this read alive while the member visits Profile.
      final before = await tester.runAsync(() async {
        final keep = rig.container.listen(ownProfileProvider, (_, _) {});
        addTearDown(keep.close);
        return rig.container.read(ownProfileProvider.future);
      });
      expect(before!.card.person.photo?.version, 'v1');

      await tester.runAsync(
        () => rig.container.read(profilePhotoProvider.notifier).remove(),
      );
      final after = await tester.runAsync(
        () => rig.container.read(ownProfileProvider.future),
      );

      expect(after!.card.person.photo, isNull);
    });

    testWidgets('Home, then Profile removes, then Home: no stale picture', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      Map<String, dynamic>? shown = photoFixture('v1');
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/me',
          FakeResponse(200, meFixture(photo: photoActive())),
        )
        ..handle(
          'GET',
          '/api/discovery/profile/me',
          (_) => FakeResponse(200, ownProfile(shown)),
        )
        ..handle('DELETE', _put, (_) {
          shown = null;
          return const FakeResponse(204);
        });
      final container = await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        // Tall, so the preview at the foot of the page is built.
        device: const DeviceProfile(name: 'tall', size: Size(412, 2400)),
      );
      await settlePhotos(tester);
      Finder pictures() => find.descendant(
        of: find.byType(AppAvatar),
        matching: find.byType(RawImage),
      );
      expect(pictures(), findsOneWidget, reason: 'the warm cache paints it');

      // The member removes their photo from Profile.
      await tester.runAsync(
        () => container.read(profilePhotoProvider.notifier).remove(),
      );
      await untilReached(tester, () => pictures().evaluate().isEmpty);

      expect(pictures(), findsNothing);
      expect(
        find.text('A'),
        findsWidgets,
        reason: 'initials, not the old photo',
      );
    });
  });

  // ---------------------------------------------------------------------------
  group('7. a late /api/me read never overwrites a newer photo', () {
    /// A signed-in session showing photo v1, whose next `/api/me` read is held
    /// back by the returned gate (and will answer with the photo as it was).
    Future<(PhotoRig, FakeBackend, Completer<FakeResponse>)> rigWithGate(
      WidgetTester tester,
    ) async {
      // Made on real time: a completer born in a test's fake-async zone is
      // completed from the zone that scheduled it, and so never from outside.
      final gate = (await tester.runAsync(
        () async => Completer<FakeResponse>(),
      ))!;
      final backend = FakeBackend();
      final rig = PhotoRig(backend, photo: photoActive('v1'));
      await rig.start(tester);
      backend.handle('GET', '/api/me', (_) => gate.future);
      return (rig, backend, gate);
    }

    testWidgets('a refresh begun before a completed PUT', (tester) async {
      final (rig, backend, gate) = await rigWithGate(tester);
      backend.on('PUT', _put, FakeResponse(200, photoActive('v2')));
      final file = sourceFile();

      await tester.runAsync(() async {
        final session = rig.container.read(sessionProvider.notifier);
        final refresh = session.refreshAccount();
        await Future<void>.delayed(const Duration(milliseconds: 30));
        await session.uploadPhoto(
          filePath: file,
          fileName: 'photo.jpg',
          contentType: 'image/jpeg',
        );
        // The older answer arrives last: it says v1.
        gate.complete(FakeResponse(200, meFixture(photo: photoActive('v1'))));
        await refresh;
      });

      expect(rig.account.photo?.version, 'v2');
    });

    testWidgets('a refresh begun before a completed DELETE', (tester) async {
      final (rig, backend, gate) = await rigWithGate(tester);
      backend.on('DELETE', _put, const FakeResponse(204));

      await tester.runAsync(() async {
        final session = rig.container.read(sessionProvider.notifier);
        final refresh = session.refreshAccount();
        await Future<void>.delayed(const Duration(milliseconds: 30));
        await session.removePhoto();
        gate.complete(FakeResponse(200, meFixture(photo: photoActive('v1'))));
        await refresh;
      });

      expect(rig.account.photo, isNull);
    });

    testWidgets('the rest of a late read still applies', (tester) async {
      final (rig, backend, gate) = await rigWithGate(tester);
      backend.on('DELETE', _put, const FakeResponse(204));

      await tester.runAsync(() async {
        final session = rig.container.read(sessionProvider.notifier);
        final refresh = session.refreshAccount();
        await Future<void>.delayed(const Duration(milliseconds: 30));
        await session.removePhoto();
        gate.complete(
          FakeResponse(200, {
            ...meFixture(photo: photoActive('v1')),
            'full_name': 'Amina B.',
          }),
        );
        await refresh;
      });

      expect(
        rig.account.fullName,
        'Amina B.',
        reason: 'only the photo is kept',
      );
      expect(rig.account.photo, isNull);
    });

    testWidgets('a refresh begun after the write is believed', (tester) async {
      final (rig, backend, gate) = await rigWithGate(tester);
      backend.on('DELETE', _put, const FakeResponse(204));
      gate.complete(FakeResponse(200, meFixture(photo: photoActive('v3'))));

      await tester.runAsync(() async {
        final session = rig.container.read(sessionProvider.notifier);
        await session.removePhoto();
        await session.refreshAccount();
      });

      expect(rig.account.photo?.version, 'v3');
    });
  });

  // ---------------------------------------------------------------------------
  group('8. the upload outlives its widget', () {
    final tall = <Widget>[const SizedBox(height: 3000)];

    Future<void> scrollAway(WidgetTester tester) async {
      await tester.drag(find.byType(ListView), const Offset(0, -2500));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byType(ProfilePhotoSection), findsNothing);
    }

    Future<void> scrollBack(WidgetTester tester) async {
      await tester.drag(find.byType(ListView), const Offset(0, 2500));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byType(ProfilePhotoSection), findsOneWidget);
    }

    testWidgets('scrolling away and back does not offer a second upload', (
      tester,
    ) async {
      final gate = Completer<FakeResponse>();
      final backend = FakeBackend()..handle('PUT', _put, (_) => gate.future);
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester, below: tall);
      final l = rig.l(tester);

      await _chooseAndSend(tester, rig, backend);
      await scrollAway(tester);
      await scrollBack(tester);

      expect(find.text(l.profilePhotoUploading), findsOneWidget);
      expect(photoButtonEnabled(tester, l.profilePhotoTake), isFalse);
      expect(photoButtonEnabled(tester, l.profilePhotoChoose), isFalse);
      expect(backend.to('PUT', _put), hasLength(1));

      gate.complete(FakeResponse(200, photoActive()));
      await untilReached(tester, () => rig.account.photo != null);
      expect(backend.to('PUT', _put), hasLength(1));
    });

    testWidgets('a failure that happens while scrolled away is still shown', (
      tester,
    ) async {
      final gate = Completer<FakeResponse>();
      final backend = FakeBackend()..handle('PUT', _put, (_) => gate.future);
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester, below: tall);
      final l = rig.l(tester);

      await _chooseAndSend(tester, rig, backend);
      await scrollAway(tester);
      gate.complete(
        const FakeResponse(503, {
          'code': 'profile_photo_storage_unavailable',
          'detail': 'Down.',
        }),
      );
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 80)),
      );
      await scrollBack(tester);

      expect(find.text(l.profilePhotoStorageUnavailable), findsOneWidget);
      expect(find.text(l.actionRetry), findsOneWidget);
      expect(_previewPath(tester), isNotNull, reason: 'the pick is kept');
      expect(photoButtonEnabled(tester, l.profilePhotoChoose), isTrue);
    });

    testWidgets('signing in as someone else starts from nothing', (
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
      await tester.runAsync(
        () => rig.container
            .read(profilePhotoProvider.notifier)
            .pick(ImageSource.gallery),
      );
      expect(rig.container.read(profilePhotoProvider).picked, isNotNull);

      // The member signs out (another may sign in on this phone).
      await tester.runAsync(
        () => rig.container.read(sessionProvider.notifier).signOut(),
      );

      expect(rig.container.read(profilePhotoProvider).picked, isNull);
      expect(rig.container.read(profilePhotoProvider).failure, isNull);
    });
  });

  // ---------------------------------------------------------------------------
  group('9. the picked file is gone', () {
    testWidgets('before it is prepared: pick again, and nothing is stuck', (
      tester,
    ) async {
      final backend = FakeBackend();
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(sourceFile()),
        preparer: (path) async =>
            throw FileSystemException('The temp file is gone', path),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChoose));
      await _untilNotice(tester);

      expect(find.text(l.profilePhotoUnreadable), findsOneWidget);
      expect(photoButtonEnabled(tester, l.profilePhotoTake), isTrue);
      expect(photoButtonEnabled(tester, l.profilePhotoChoose), isTrue);
      expect(find.text(l.actionRetry), findsNothing, reason: 'pick again');
      expect(rig.container.read(profilePhotoProvider).picked, isNull);
      expect(backend.to('PUT', _put), isEmpty);
    });

    testWidgets('after a failed upload, when "Try again" finds it gone', (
      tester,
    ) async {
      // Without a preview on screen: Windows keeps a file open while a picture
      // of it is drawn, and this is about the state, not the picture.
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
      final photo = rig.container.read(profilePhotoProvider.notifier);

      final first = await tester.runAsync(
        () => photo.pick(ImageSource.gallery),
      );
      expect(first, isFalse);
      final kept = rig.container.read(profilePhotoProvider);
      expect(kept.failure, ProfilePhotoFailure.storageUnavailable);
      expect(kept.picked, isNotNull);
      File(kept.picked!.path).deleteSync();

      final again = await tester.runAsync(photo.upload);

      expect(again, isFalse);
      final after = rig.container.read(profilePhotoProvider);
      expect(after.failure, ProfilePhotoFailure.unreadable);
      expect(after.picked, isNull, reason: 'the selection is cleared');
      expect(after.busy, isFalse, reason: 'the buttons are usable again');
      expect(backend.to('PUT', _put), hasLength(1), reason: 'nothing was sent');
    });

    testWidgets('a picker that answers with a missing file is the same', (
      tester,
    ) async {
      final backend = FakeBackend();
      final rig = PhotoRig(
        backend,
        picker: (_) async => XFile(
          '${Directory.systemTemp.path}${Platform.pathSeparator}vanished.jpg',
        ),
        preparer: (path) async {
          if (!File(path).existsSync()) {
            throw FileSystemException('The picked photo is gone', path);
          }
          return path;
        },
      );
      await rig.pump(tester);

      await tester.tap(photoButton(rig.l(tester).profilePhotoTake));
      await _untilNotice(tester);

      expect(find.text(rig.l(tester).profilePhotoUnreadable), findsOneWidget);
    });
  });

  // ---------------------------------------------------------------------------
  group('11. a new pick is never previewed as the old one', () {
    testWidgets('two picks of the same name draw their own files', (
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
      // The same source path both times, as a camera that reuses its name does.
      final source = sourceFile(name: 'IMG_0001.jpg');
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(source),
        preparer: preparerWriting(jpegBytes, name: 'scaled_IMG_0001.jpg'),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await _chooseAndSend(tester, rig, backend);
      await _untilNotice(tester);
      final first = rig.container.read(profilePhotoProvider).picked!.path;
      expect(_previewPath(tester), first);

      await tester.tap(photoButton(l.profilePhotoChoose));
      await untilReached(tester, () => backend.to('PUT', _put).length == 2);
      await untilReached(
        tester,
        () => rig.container.read(profilePhotoProvider).picked?.path != first,
      );
      await untilReached(tester, () => _notice.evaluate().isNotEmpty);
      final second = rig.container.read(profilePhotoProvider).picked!.path;

      expect(second, isNot(first));
      expect(_previewPath(tester), second, reason: 'not the first photo');
    });
  });

  // ---------------------------------------------------------------------------
  group('12. a failed replacement', () {
    PhotoRig failingReplacement(FakeBackend backend) => PhotoRig(
      backend,
      picker: pickerReturning(sourceFile()),
      photo: photoActive(),
    );

    Future<void> failOnce(WidgetTester tester, PhotoRig rig) async {
      final l = rig.l(tester);
      await tester.tap(photoButton(l.profilePhotoChange));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.profilePhotoChoose));
      await _untilNotice(tester);
    }

    testWidgets('can be discarded, and "Remove photo" stays available', (
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
      final rig = failingReplacement(backend);
      await rig.pump(tester);
      final l = rig.l(tester);

      await failOnce(tester, rig);

      expect(find.text(l.profilePhotoStorageUnavailable), findsOneWidget);
      expect(photoButtonEnabled(tester, l.profilePhotoRemove), isTrue);
      expect(photoButtonEnabled(tester, l.profilePhotoChange), isTrue);
      expect(photoButton(l.profilePhotoDiscard), findsOneWidget);

      await tester.tap(photoButton(l.profilePhotoDiscard));
      await untilReached(tester, () => _notice.evaluate().isEmpty);

      expect(_previewPath(tester), isNull);
      expect(photoButton(l.profilePhotoDiscard), findsNothing);
      expect(photoButton(l.profilePhotoRemove), findsOneWidget);
      expect(
        rig.account.photo?.version,
        'v1',
        reason: 'the photo is untouched',
      );
      expect(backend.to('DELETE', _put), isEmpty);
    });

    testWidgets('removing the photo clears the obsolete error', (tester) async {
      final backend = FakeBackend()
        ..on(
          'PUT',
          _put,
          const FakeResponse(503, {
            'code': 'profile_photo_storage_unavailable',
          }),
        )
        ..on('DELETE', _put, const FakeResponse(204));
      final rig = failingReplacement(backend);
      await rig.pump(tester);
      final l = rig.l(tester);

      await failOnce(tester, rig);
      await tester.tap(photoButton(l.profilePhotoRemove));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(l.profilePhotoRemove),
        ),
      );
      await untilReached(tester, () => rig.account.photo == null);
      await untilReached(
        tester,
        () => find.text(l.profilePhotoStorageUnavailable).evaluate().isEmpty,
      );

      expect(backend.to('DELETE', _put), hasLength(1));
      expect(_previewPath(tester), isNull);
      expect(find.text(l.actionRetry), findsNothing);
      expect(photoButton(l.profilePhotoTake), findsOneWidget);
      expect(rig.container.read(profilePhotoProvider).picked, isNull);
    });

    testWidgets('a removal that fails keeps the pick and says so', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'PUT',
          _put,
          const FakeResponse(503, {
            'code': 'profile_photo_storage_unavailable',
          }),
        )
        ..on('DELETE', _put, const FakeResponse(500, {'detail': 'boom'}));
      final rig = failingReplacement(backend);
      await rig.pump(tester);
      final l = rig.l(tester);

      await failOnce(tester, rig);
      await tester.tap(photoButton(l.profilePhotoRemove));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(l.profilePhotoRemove),
        ),
      );
      await untilReached(
        tester,
        () => find.byType(SnackBar).evaluate().isNotEmpty,
      );

      expect(rig.account.photo?.version, 'v1');
      expect(photoButtonEnabled(tester, l.profilePhotoRemove), isTrue);
      expect(find.text(l.profilePhotoStorageUnavailable), findsOneWidget);
    });
  });

  // ---------------------------------------------------------------------------
  group('13. the request preview sheet', () {
    testWidgets('shows the sender\'s photo beside "From", to a guest too', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final store = FakeTokenStore(refresh: null);
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/requests',
          discoveryPage([requestCardFixture(5, photo: photoFixture('b'))]),
        );
      final container = ProviderContainer(
        retry: (_, _) => null,
        overrides: [
          tokenStoreProvider.overrideWithValue(store),
          apiClientProvider.overrideWithValue(apiClientFor(backend, store)),
        ],
      );
      addTearDown(container.dispose);
      await tester.runAsync(
        () => container.read(sessionProvider.notifier).restore(),
      );
      await pumpApp(
        tester,
        const BrowseRequestsScreen(),
        container: container,
        routed: true,
        extraRoutes: discoveryMarkers(),
      );
      await tester.pumpAndSettle();
      await settlePhotos(tester);
      final onTheCard = find.byType(AppAvatar).evaluate().length;

      await tester.tap(find.text('Documents'));
      await tester.pumpAndSettle();
      await settlePhotos(tester);

      expect(find.byType(AppAvatar), findsNWidgets(onTheCard + 1));
      final sheet = find.descendant(
        of: find.byType(AppSheet),
        matching: find.byType(AppAvatar),
      );
      expect(sheet, findsOneWidget);
      expect(
        find.descendant(of: sheet, matching: find.byType(RawImage)),
        findsOneWidget,
        reason: 'the photo, not initials, in the sheet',
      );
      expect(
        find.descendant(
          of: find.byType(AppSheet),
          matching: find.text('From Yacine'),
        ),
        findsOneWidget,
      );
    });
  });

  // ---------------------------------------------------------------------------
  group('14. the phone ended the app while the picker was open', () {
    testWidgets(
      'the photo is offered to the same account, never sent unasked',
      (tester) async {
        final backend = FakeBackend()
          ..on('PUT', _put, FakeResponse(200, photoActive('v5')));
        final tokens = FakeTokenStore()..pendingPhotoPick = '42';
        final rig = PhotoRig(
          backend,
          tokens: tokens,
          lostData: () async => XFile(sourceFile(name: 'lost.jpg')),
        );
        await rig.pump(tester);
        final l = rig.l(tester);
        await untilReached(
          tester,
          () => find.text(l.profilePhotoRecovered).evaluate().isNotEmpty,
        );

        expect(backend.to('PUT', _put), isEmpty, reason: 'asked first');
        expect(photoButton(l.profilePhotoUse), findsOneWidget);
        expect(photoButton(l.profilePhotoDiscard), findsOneWidget);
        expect(_previewPath(tester), isNotNull, reason: 'the member sees it');
        expect(tokens.pendingPhotoPick, isNull, reason: 'the marker is spent');

        await tester.tap(photoButton(l.profilePhotoUse));
        await untilReached(tester, () => rig.account.photo != null);

        expect(backend.to('PUT', _put), hasLength(1));
        expect(rig.account.photo?.version, 'v5');
      },
    );

    testWidgets('the member may discard it', (tester) async {
      final backend = FakeBackend();
      final tokens = FakeTokenStore()..pendingPhotoPick = '42';
      final rig = PhotoRig(
        backend,
        tokens: tokens,
        lostData: () async => XFile(sourceFile(name: 'lost.jpg')),
      );
      await rig.pump(tester);
      final l = rig.l(tester);
      await untilReached(
        tester,
        () => find.text(l.profilePhotoRecovered).evaluate().isNotEmpty,
      );

      await tester.tap(photoButton(l.profilePhotoDiscard));
      await untilReached(
        tester,
        () => find.text(l.profilePhotoRecovered).evaluate().isEmpty,
      );

      expect(backend.to('PUT', _put), isEmpty);
      expect(photoButton(l.profilePhotoTake), findsOneWidget);
    });

    testWidgets('another account\'s pick is not offered to this one', (
      tester,
    ) async {
      var asked = 0;
      final tokens = FakeTokenStore()..pendingPhotoPick = '7';
      final rig = PhotoRig(
        FakeBackend(),
        tokens: tokens,
        lostData: () async {
          asked++;
          return XFile(sourceFile());
        },
      );
      await rig.pump(tester);
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 80)),
      );
      await tester.pump();

      expect(asked, 0, reason: 'the picker\'s leftovers stay unread');
      expect(find.text(rig.l(tester).profilePhotoRecovered), findsNothing);
      expect(tokens.pendingPhotoPick, isNull);
    });

    testWidgets('no marker, no offer', (tester) async {
      var asked = 0;
      final rig = PhotoRig(
        FakeBackend(),
        lostData: () async {
          asked++;
          return XFile(sourceFile());
        },
      );
      await rig.pump(tester);
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 80)),
      );

      expect(asked, 0);
      expect(find.text(rig.l(tester).profilePhotoRecovered), findsNothing);
    });

    testWidgets('a marker with nothing lost offers nothing', (tester) async {
      final tokens = FakeTokenStore()..pendingPhotoPick = '42';
      final rig = PhotoRig(FakeBackend(), tokens: tokens);
      await rig.pump(tester);
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 80)),
      );
      await tester.pump();

      expect(find.text(rig.l(tester).profilePhotoRecovered), findsNothing);
      expect(tokens.pendingPhotoPick, isNull);
    });

    testWidgets(
      'opening the picker marks the account, and a normal answer clears it',
      (tester) async {
        final tokens = FakeTokenStore();
        String? whileOpen;
        final backend = FakeBackend()
          ..on('PUT', _put, FakeResponse(200, photoActive()));
        final rig = PhotoRig(
          backend,
          tokens: tokens,
          picker: (source) async {
            whileOpen = tokens.pendingPhotoPick;
            return XFile(sourceFile());
          },
        );
        await rig.pump(tester);

        await tester.tap(photoButton(rig.l(tester).profilePhotoChoose));
        await untilReached(tester, () => rig.account.photo != null);

        expect(whileOpen, '42');
        expect(tokens.pendingPhotoPick, isNull);
      },
    );

    testWidgets('a refused picker clears the marker too', (tester) async {
      final tokens = FakeTokenStore();
      final rig = PhotoRig(
        FakeBackend(),
        tokens: tokens,
        picker: (_) async =>
            throw PlatformException(code: 'camera_access_denied'),
      );
      await rig.pump(tester);

      await tester.tap(photoButton(rig.l(tester).profilePhotoTake));
      await _untilNotice(tester);

      expect(tokens.pendingPhotoPick, isNull);
    });
  });
}
