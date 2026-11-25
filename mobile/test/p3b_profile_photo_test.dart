/// P3B: the Profile photo section, state by state.
///
/// The real session, repository, client and screen run over a fake server, so
/// what is asserted is what would reach Django: a single `PUT /api/me/photo`
/// with the declared type, and a `DELETE` for a removal or a dismissal.
///
/// The rules from the server's second pass are checked here too: an upload is
/// never retried by the app (every retry is the member pressing the button),
/// and any 413 means "too large", whatever its body.
library;

import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/features/profile/profile_photo_section.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';
import 'support/photo_cache.dart';
import 'support/photo_rig.dart';

const _put = photoPut;

const _small = DeviceProfile(name: '360x740', size: Size(360, 740));

void main() {
  setUp(() => imageCache.clear());

  group('empty', () {
    testWidgets(
      'invites a photo, says who sees it, and offers camera and library',
      (tester) async {
        final rig = PhotoRig(FakeBackend());
        await rig.pump(tester);
        final l = rig.l(tester);

        expect(find.text(l.profilePhotoTitle), findsOneWidget);
        expect(find.text(l.profilePhotoHelpEmpty), findsOneWidget);
        expect(find.text(l.profilePhotoFormatRule), findsOneWidget);
        expect(photoButton(l.profilePhotoTake), findsOneWidget);
        expect(photoButton(l.profilePhotoChoose), findsOneWidget);
        expect(photoButton(l.profilePhotoRemove), findsNothing);
        expect(photoButton(l.profilePhotoChange), findsNothing);
        // The initials stand in for the picture.
        expect(find.text('AB'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('closing the picker changes nothing', (tester) async {
      final backend = FakeBackend();
      final rig = PhotoRig(backend, picker: (_) async => null);
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChoose));
      await tester.pump();

      expect(backend.to('PUT', _put), isEmpty);
      expect(find.text(l.profilePhotoUploading), findsNothing);
    });
  });

  group('uploading', () {
    testWidgets(
      'sends one PUT with the declared type, shows progress, then the photo',
      (tester) async {
        installPhotoCache(PhotoCacheBehavior.serve);
        final gate = Completer<FakeResponse>();
        final backend = FakeBackend()..handle('PUT', _put, (_) => gate.future);
        final calls = <ImageSource>[];
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile(), calls: calls),
        );
        await rig.pump(tester);
        final l = rig.l(tester);

        await tester.tap(photoButton(l.profilePhotoChoose));
        await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);

        expect(calls, [ImageSource.gallery]);
        // Mid-flight: the preview and the words, and nothing can be pressed.
        expect(find.text(l.profilePhotoUploading), findsOneWidget);
        expect(find.byType(Image), findsOneWidget);
        expect(photoButtonEnabled(tester, l.profilePhotoTake), isFalse);
        expect(photoButtonEnabled(tester, l.profilePhotoChoose), isFalse);

        final request = backend.lastTo('PUT', _put)!;
        expect(request.body['photo__filename'], 'photo.jpg');
        expect(request.body['photo__content_type'], 'image/jpeg');

        gate.complete(FakeResponse(200, photoActive()));
        await untilReached(
          tester,
          () => find.text(l.profilePhotoChange).evaluate().isNotEmpty,
        );

        await untilReached(
          tester,
          () => find.text(l.profilePhotoUpdated).evaluate().isNotEmpty,
        );

        expect(backend.to('PUT', _put), hasLength(1));
        expect(rig.account.photo?.photo?.version, 'v1');
        expect(find.text(l.profilePhotoUpdated), findsOneWidget);
        expect(find.text(l.profilePhotoUploading), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('the camera button opens the camera', (tester) async {
      final calls = <ImageSource>[];
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive()));
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(sourceFile(), calls: calls),
      );
      await rig.pump(tester);

      await tester.tap(photoButton(rig.l(tester).profilePhotoTake));
      await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);

      expect(calls, [ImageSource.camera]);
    });

    testWidgets('the type is read from the bytes, and the name follows it', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive()));
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(sourceFile(name: 'me.heic')),
        preparer: preparerWriting(pngBytes, name: 'prepared.png'),
      );
      await rig.pump(tester);

      await tester.tap(photoButton(rig.l(tester).profilePhotoChoose));
      await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);

      final body = backend.lastTo('PUT', _put)!.body;
      expect(body['photo__content_type'], 'image/png');
      expect(body['photo__filename'], 'photo.png');
    });

    testWidgets('a .webp name on JPEG bytes is sent as a JPEG', (tester) async {
      // The native resizer keeps the source's suffix but writes JPEG.
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive()));
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(sourceFile(name: 'camera.webp')),
        preparer: preparerWriting(jpegBytes, name: 'scaled_camera.webp'),
      );
      await rig.pump(tester);

      await tester.tap(photoButton(rig.l(tester).profilePhotoChoose));
      await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);

      final body = backend.lastTo('PUT', _put)!.body;
      expect(body['photo__content_type'], 'image/jpeg');
      expect(body['photo__filename'], 'photo.jpg');
    });
  });

  group('active', () {
    testWidgets('offers change and remove, and says who sees the photo', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final rig = PhotoRig(FakeBackend(), photo: photoActive());
      await rig.pump(tester);
      await settlePhotos(tester);
      final l = rig.l(tester);

      expect(find.text(l.profilePhotoHelpActive), findsOneWidget);
      expect(photoButton(l.profilePhotoChange), findsOneWidget);
      expect(photoButton(l.profilePhotoRemove), findsOneWidget);
      expect(photoButton(l.profilePhotoTake), findsNothing);
      // The photo is drawn in the section and on the passport-sized avatar.
      expect(
        find.descendant(
          of: find.byType(ProfilePhotoSection),
          matching: find.byType(RawImage),
        ),
        findsOneWidget,
      );
    });

    testWidgets('"Change photo" asks camera or library, then uploads', (
      tester,
    ) async {
      final calls = <ImageSource>[];
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('v2')));
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(sourceFile(), calls: calls),
        photo: photoActive(),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChange));
      await tester.pumpAndSettle();
      expect(find.text(l.profilePhotoTake), findsOneWidget);
      await tester.tap(find.text(l.profilePhotoTake));
      await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);

      expect(calls, [ImageSource.camera]);
      await untilReached(
        tester,
        () => rig.account.photo?.photo?.version == 'v2',
      );
    });

    testWidgets('removing asks first, and Cancel leaves the photo', (
      tester,
    ) async {
      final backend = FakeBackend();
      final rig = PhotoRig(backend, photo: photoActive());
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoRemove));
      await tester.pumpAndSettle();
      expect(find.text(l.profilePhotoRemoveTitle), findsOneWidget);
      expect(find.text(l.profilePhotoRemoveBody), findsOneWidget);

      await tester.tap(find.text(l.actionCancel));
      await tester.pumpAndSettle();

      expect(backend.to('DELETE', _put), isEmpty);
      expect(rig.account.photo?.photo?.version, 'v1');
    });

    testWidgets('confirming removes it and the initials return', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(204));
      final rig = PhotoRig(backend, photo: photoActive());
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

      expect(backend.to('DELETE', _put), hasLength(1));
      expect(rig.account.photo, isNull);
      expect(find.text(l.profilePhotoRemoved), findsOneWidget);
      expect(photoButton(l.profilePhotoTake), findsOneWidget);
      expect(photoButton(l.profilePhotoRemove), findsNothing);
    });

    testWidgets('a removal the server refuses keeps the photo and says so', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(500, {'detail': 'boom'}));
      final rig = PhotoRig(backend, photo: photoActive());
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

      expect(rig.account.photo?.photo?.version, 'v1');
      expect(photoButton(l.profilePhotoRemove), findsOneWidget);
      expect(photoButtonEnabled(tester, l.profilePhotoRemove), isTrue);
      expect(find.byType(SnackBar), findsOneWidget);
    });
  });

  group('removed by Wassla', () {
    testWidgets(
      'shows the server\'s reason and offers a new photo or dismissal',
      (tester) async {
        final rig = PhotoRig(FakeBackend(), photo: photoRemoved());
        await rig.pump(tester);
        final l = rig.l(tester);

        expect(find.text(l.profilePhotoWassla), findsOneWidget);
        expect(find.textContaining('Not a photo of you.'), findsOneWidget);
        expect(find.text(l.profilePhotoDismiss), findsOneWidget);
        expect(photoButton(l.profilePhotoTake), findsOneWidget);
        expect(photoButton(l.profilePhotoChoose), findsOneWidget);
        // Nothing of the removed photo is drawn.
        expect(find.text('AB'), findsOneWidget);
      },
    );

    testWidgets('no reason given reads as the generic sentence, not a blank', (
      tester,
    ) async {
      final rig = PhotoRig(FakeBackend(), photo: photoRemoved(reason: null));
      await rig.pump(tester);
      final l = rig.l(tester);

      expect(find.text(l.profilePhotoWasslaBody), findsOneWidget);
      expect(find.textContaining('Reason:'), findsNothing);
    });

    testWidgets('dismissing sends a DELETE and clears the notice', (
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
      expect(find.text(l.profilePhotoWassla), findsNothing);
      expect(rig.account.photo, isNull);
    });

    testWidgets('a new photo replaces the notice', (tester) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, photoActive('v9')));
      final rig = PhotoRig(
        backend,
        picker: pickerReturning(sourceFile()),
        photo: photoRemoved(),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChoose));
      await untilReached(tester, () => rig.account.photo?.photo != null);

      expect(find.text(l.profilePhotoWassla), findsNothing);
      expect(photoButton(l.profilePhotoChange), findsOneWidget);
    });
  });

  group('refusals', () {
    Future<(PhotoRig, FakeBackend)> failing(
      WidgetTester tester,
      FakeResponse response,
    ) async {
      final backend = FakeBackend()..on('PUT', _put, response);
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester);
      await tester.tap(photoButton(rig.l(tester).profilePhotoChoose));
      await untilReached(
        tester,
        () => find.byType(InfoNotice).evaluate().isNotEmpty,
      );
      return (rig, backend);
    }

    testWidgets('profile_photo_too_large reads as too large, with no retry', (
      tester,
    ) async {
      final (rig, _) = await failing(
        tester,
        const FakeResponse(413, {
          'code': 'profile_photo_too_large',
          'detail': 'Too big.',
          'max_bytes': 10485760,
        }),
      );
      final l = rig.l(tester);

      expect(find.text(l.profilePhotoTooLarge), findsOneWidget);
      expect(find.text(l.actionRetry), findsNothing);
      expect(find.byType(Image), findsNothing, reason: 'the file is dropped');
    });

    testWidgets('any 413 is too large, even with no JSON body', (tester) async {
      // The edge proxy refuses an oversized body before Django sees it.
      final (rig, _) = await failing(
        tester,
        const FakeResponse(413, '<html>413 Request Entity Too Large</html>'),
      );

      expect(find.text(rig.l(tester).profilePhotoTooLarge), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('an unsupported type is refused with its own words', (
      tester,
    ) async {
      final (rig, _) = await failing(
        tester,
        const FakeResponse(415, {
          'code': 'profile_photo_media_type_unsupported',
          'detail': 'No.',
        }),
      );

      expect(
        find.text(rig.l(tester).profilePhotoTypeNotAllowed),
        findsOneWidget,
      );
      expect(find.text(rig.l(tester).actionRetry), findsNothing);
    });

    testWidgets('an inactive or banned account is told so, without a retry', (
      tester,
    ) async {
      final (rig, _) = await failing(
        tester,
        const FakeResponse(403, {
          'code': 'account_inactive',
          'detail': 'Inactive.',
        }),
      );

      expect(
        find.text(rig.l(tester).profilePhotoAccountInactive),
        findsOneWidget,
      );
      expect(find.text(rig.l(tester).actionRetry), findsNothing);
    });

    testWidgets(
      'a prepared file over 10 MB is refused on the phone, never sent',
      (tester) async {
        final backend = FakeBackend();
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile()),
          preparer: preparerWriting(
            Uint8List.fromList([...jpegBytes, ...Uint8List(10 * 1024 * 1024)]),
          ),
        );
        await rig.pump(tester);
        final l = rig.l(tester);

        await tester.tap(photoButton(l.profilePhotoChoose));
        await untilReached(
          tester,
          () => find.text(l.profilePhotoTooLarge).evaluate().isNotEmpty,
        );

        expect(backend.to('PUT', _put), isEmpty);
      },
    );

    testWidgets(
      'a result that is not JPEG, PNG or WebP is refused on the phone',
      (tester) async {
        final backend = FakeBackend();
        final rig = PhotoRig(
          backend,
          picker: pickerReturning(sourceFile(name: 'me.gif')),
          preparer: preparerWriting(gifBytes, name: 'prepared.jpg'),
        );
        await rig.pump(tester);
        final l = rig.l(tester);

        await tester.tap(photoButton(l.profilePhotoChoose));
        await untilReached(
          tester,
          () => find.text(l.profilePhotoTypeNotAllowed).evaluate().isNotEmpty,
        );

        expect(backend.to('PUT', _put), isEmpty);
      },
    );

    testWidgets('the camera or library refusing to open says so', (
      tester,
    ) async {
      final backend = FakeBackend();
      final rig = PhotoRig(
        backend,
        picker: (_) async =>
            throw PlatformException(code: 'camera_access_denied'),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoTake));
      await tester.pump();
      await tester.pump();

      expect(find.text(l.profilePhotoPickFailed), findsOneWidget);
      expect(backend.to('PUT', _put), isEmpty);
    });
  });

  group('retry is the member pressing the button', () {
    testWidgets('storage unavailable keeps the photo and waits for a tap', (
      tester,
    ) async {
      var failing = true;
      final backend = FakeBackend()
        ..handle(
          'PUT',
          _put,
          (_) => failing
              ? const FakeResponse(503, {
                  'code': 'profile_photo_storage_unavailable',
                  'detail': 'Down.',
                })
              : FakeResponse(200, photoActive()),
        );
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChoose));
      await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);
      await untilReached(
        tester,
        () => find.byType(InfoNotice).evaluate().isNotEmpty,
      );

      expect(find.text(l.profilePhotoStorageUnavailable), findsOneWidget);
      expect(
        find.byType(Image),
        findsOneWidget,
        reason: 'the file stays selected',
      );

      // Time passing never sends it again.
      await tester.pump(const Duration(minutes: 5));
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 50)),
      );
      expect(backend.to('PUT', _put), hasLength(1));

      failing = false;
      await tester.tap(find.text(l.actionRetry));
      await untilReached(tester, () => rig.account.photo?.photo != null);

      expect(backend.to('PUT', _put), hasLength(2));
      expect(find.text(l.profilePhotoStorageUnavailable), findsNothing);
    });

    testWidgets('a server error offers "try again" and sends once per tap', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, const FakeResponse(500, {'detail': 'boom'}));
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChoose));
      await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);
      await untilReached(
        tester,
        () => find.byType(InfoNotice).evaluate().isNotEmpty,
      );

      expect(find.text(l.profilePhotoFailed), findsOneWidget);
      expect(backend.to('PUT', _put), hasLength(1));

      await tester.tap(find.text(l.actionRetry));
      await untilReached(tester, () => backend.to('PUT', _put).length == 2);
      await untilReached(
        tester,
        () => find.byType(InfoNotice).evaluate().isNotEmpty,
      );

      expect(backend.to('PUT', _put), hasLength(2));
    });

    testWidgets('offline says so, keeps the photo and offers "try again"', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle(
          'PUT',
          _put,
          (_) => throw DioException.connectionError(
            requestOptions: RequestOptions(path: _put),
            reason: 'offline',
          ),
        );
      final rig = PhotoRig(backend, picker: pickerReturning(sourceFile()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(photoButton(l.profilePhotoChoose));
      await untilReached(tester, () => backend.to('PUT', _put).isNotEmpty);
      await untilReached(
        tester,
        () => find.byType(InfoNotice).evaluate().isNotEmpty,
      );

      expect(find.text(l.profilePhotoOffline), findsOneWidget);
      expect(find.text(l.actionRetry), findsOneWidget);
      expect(backend.to('PUT', _put), hasLength(1));
    });
  });

  // Every state on every phone shape and language, and inside the real Profile
  // screen under the bottom navigation, is `p3b_photo_layout_test.dart`.
  group('layout', () {
    testWidgets('Arabic: right to left, Modern Standard Arabic, no overflow', (
      tester,
    ) async {
      final rig = PhotoRig(FakeBackend(), photo: photoRemoved());
      await rig.pump(tester, locale: const Locale('ar'), device: _small);
      final l = rig.l(tester);

      expect(find.text(l.profilePhotoTitle), findsOneWidget);
      expect(find.text('الصورة الشخصية'), findsOneWidget);
      // The avatar leads, so it sits on the right.
      expect(
        tester.getCenter(find.byType(AppAvatar)).dx,
        greaterThan(tester.getCenter(find.text(l.profilePhotoHelpEmpty)).dx),
      );
      expect(tester.takeException(), isNull);
    });
  });
}
