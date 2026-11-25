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
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/features/profile/profile_photo_section.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';
import 'support/photo_cache.dart';

const _put = '/api/me/photo';

const _small = DeviceProfile(name: '360x740', size: Size(360, 740));

Map<String, dynamic> _active([String version = 'v1']) => {
  'state': 'active',
  'url': 'https://media.test/profile-photos/abc.jpg?sig=1',
  'version': version,
  'removed_at': null,
  'reason': null,
};

Map<String, dynamic> _removed({String? reason = 'Not a photo of you.'}) => {
  'state': 'removed',
  'url': null,
  'version': 'v0',
  'removed_at': '2026-11-24T10:00:00Z',
  'reason': reason,
};

/// A real file the multipart body reads from.
String _file({String name = 'me.jpg', int? size}) {
  final dir = Directory.systemTemp.createTempSync('shiptrip-profile-photo');
  addTearDown(() {
    try {
      dir.deleteSync(recursive: true);
    } on FileSystemException {
      // The OS reclaims it; the assertions have already run.
    }
  });
  final file = File('${dir.path}${Platform.pathSeparator}$name');
  file.writeAsBytesSync(size == null ? tinyPng : Uint8List(size));
  return file.path;
}

ProfilePhotoPicker _pickerReturning(
  String path, {
  String mime = 'image/jpeg',
  List<ImageSource>? calls,
}) => (source) async {
  calls?.add(source);
  return XFile(
    path,
    mimeType: mime,
    name: path.split(Platform.pathSeparator).last,
  );
};

/// Lets real I/O (the file read behind a multipart body) and fake time both
/// move, until [until] holds.
Future<void> _until(
  WidgetTester tester,
  bool Function() until, {
  int maxFrames = 200,
}) async {
  for (var frame = 0; frame < maxFrames; frame++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 10)),
    );
    await tester.pump(const Duration(milliseconds: 16));
    if (until()) return;
  }
  fail('the screen never reached the state the test was waiting for');
}

class _Rig {
  _Rig(this.backend, {this.picker, Map<String, dynamic>? photo})
    : _photo = photo;

  final FakeBackend backend;
  final ProfilePhotoPicker? picker;
  final Map<String, dynamic>? _photo;

  late final ProviderContainer container;

  L l(WidgetTester tester) =>
      L.of(tester.element(find.byType(ProfilePhotoSection)));

  Future<void> pump(
    WidgetTester tester, {
    Locale locale = const Locale('en'),
    DeviceProfile device = DeviceProfile.android,
  }) async {
    backend.on('GET', '/api/me', FakeResponse(200, meFixture(photo: _photo)));
    final tokens = FakeTokenStore();
    container = ProviderContainer(
      overrides: [
        tokenStoreProvider.overrideWithValue(tokens),
        apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
        if (picker != null)
          profilePhotoPickerProvider.overrideWithValue(picker!),
      ],
    );
    addTearDown(container.dispose);
    await tester.runAsync(
      () => container.read(sessionProvider.notifier).restore(),
    );
    await pumpApp(
      tester,
      Scaffold(
        body: Consumer(
          builder: (context, ref, _) => ListView(
            padding: const EdgeInsets.all(20),
            children: [
              ProfilePhotoSection(account: ref.watch(accountProvider)!),
            ],
          ),
        ),
      ),
      container: container,
      locale: locale,
      device: device,
    );
  }

  Account get account => container.read(accountProvider)!;
}

Finder _button(String label) => find.widgetWithText(AppButton, label);

bool _enabled(WidgetTester tester, String label) =>
    tester.widget<AppButton>(_button(label)).onPressed != null;

void main() {
  setUp(() => imageCache.clear());

  group('empty', () {
    testWidgets(
      'invites a photo, says who sees it, and offers camera and library',
      (tester) async {
        final rig = _Rig(FakeBackend());
        await rig.pump(tester);
        final l = rig.l(tester);

        expect(find.text(l.profilePhotoTitle), findsOneWidget);
        expect(find.text(l.profilePhotoHelpEmpty), findsOneWidget);
        expect(find.text(l.profilePhotoFormatRule), findsOneWidget);
        expect(_button(l.profilePhotoTake), findsOneWidget);
        expect(_button(l.profilePhotoChoose), findsOneWidget);
        expect(_button(l.profilePhotoRemove), findsNothing);
        expect(_button(l.profilePhotoChange), findsNothing);
        // The initials stand in for the picture.
        expect(find.text('AB'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('closing the picker changes nothing', (tester) async {
      final backend = FakeBackend();
      final rig = _Rig(backend, picker: (_) async => null);
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoChoose));
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
        final rig = _Rig(
          backend,
          picker: _pickerReturning(_file(), calls: calls),
        );
        await rig.pump(tester);
        final l = rig.l(tester);

        await tester.tap(_button(l.profilePhotoChoose));
        await _until(tester, () => backend.to('PUT', _put).isNotEmpty);

        expect(calls, [ImageSource.gallery]);
        // Mid-flight: the preview and the words, and nothing can be pressed.
        expect(find.text(l.profilePhotoUploading), findsOneWidget);
        expect(find.byType(Image), findsOneWidget);
        expect(_enabled(tester, l.profilePhotoTake), isFalse);
        expect(_enabled(tester, l.profilePhotoChoose), isFalse);

        final request = backend.lastTo('PUT', _put)!;
        expect(request.body['photo__filename'], 'me.jpg');
        expect(request.body['photo__content_type'], 'image/jpeg');

        gate.complete(FakeResponse(200, _active()));
        await _until(
          tester,
          () => find.text(l.profilePhotoChange).evaluate().isNotEmpty,
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
        ..on('PUT', _put, FakeResponse(200, _active()));
      final rig = _Rig(
        backend,
        picker: _pickerReturning(_file(), calls: calls),
      );
      await rig.pump(tester);

      await tester.tap(_button(rig.l(tester).profilePhotoTake));
      await _until(tester, () => backend.to('PUT', _put).isNotEmpty);

      expect(calls, [ImageSource.camera]);
    });

    testWidgets('a PNG is declared as a PNG', (tester) async {
      final backend = FakeBackend()
        ..on('PUT', _put, FakeResponse(200, _active()));
      final rig = _Rig(
        backend,
        picker: _pickerReturning(_file(name: 'me.png'), mime: 'image/png'),
      );
      await rig.pump(tester);

      await tester.tap(_button(rig.l(tester).profilePhotoChoose));
      await _until(tester, () => backend.to('PUT', _put).isNotEmpty);

      expect(
        backend.lastTo('PUT', _put)!.body['photo__content_type'],
        'image/png',
      );
    });
  });

  group('active', () {
    testWidgets('offers change and remove, and says who sees the photo', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final rig = _Rig(FakeBackend(), photo: _active());
      await rig.pump(tester);
      await settlePhotos(tester);
      final l = rig.l(tester);

      expect(find.text(l.profilePhotoHelpActive), findsOneWidget);
      expect(_button(l.profilePhotoChange), findsOneWidget);
      expect(_button(l.profilePhotoRemove), findsOneWidget);
      expect(_button(l.profilePhotoTake), findsNothing);
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
        ..on('PUT', _put, FakeResponse(200, _active('v2')));
      final rig = _Rig(
        backend,
        picker: _pickerReturning(_file(), calls: calls),
        photo: _active(),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoChange));
      await tester.pumpAndSettle();
      expect(find.text(l.profilePhotoTake), findsOneWidget);
      await tester.tap(find.text(l.profilePhotoTake));
      await _until(tester, () => backend.to('PUT', _put).isNotEmpty);

      expect(calls, [ImageSource.camera]);
      await _until(tester, () => rig.account.photo?.photo?.version == 'v2');
    });

    testWidgets('removing asks first, and Cancel leaves the photo', (
      tester,
    ) async {
      final backend = FakeBackend();
      final rig = _Rig(backend, photo: _active());
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoRemove));
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
      final rig = _Rig(backend, photo: _active());
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoRemove));
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
      expect(_button(l.profilePhotoTake), findsOneWidget);
      expect(_button(l.profilePhotoRemove), findsNothing);
    });

    testWidgets('a removal the server refuses keeps the photo and says so', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('DELETE', _put, const FakeResponse(500, {'detail': 'boom'}));
      final rig = _Rig(backend, photo: _active());
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoRemove));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(l.profilePhotoRemove),
        ),
      );
      await tester.pumpAndSettle();

      expect(rig.account.photo?.photo?.version, 'v1');
      expect(_button(l.profilePhotoRemove), findsOneWidget);
      expect(_enabled(tester, l.profilePhotoRemove), isTrue);
      expect(find.byType(SnackBar), findsOneWidget);
    });
  });

  group('removed by Wassla', () {
    testWidgets(
      'shows the server\'s reason and offers a new photo or dismissal',
      (tester) async {
        final rig = _Rig(FakeBackend(), photo: _removed());
        await rig.pump(tester);
        final l = rig.l(tester);

        expect(find.text(l.profilePhotoWassla), findsOneWidget);
        expect(find.textContaining('Not a photo of you.'), findsOneWidget);
        expect(find.text(l.profilePhotoDismiss), findsOneWidget);
        expect(_button(l.profilePhotoTake), findsOneWidget);
        expect(_button(l.profilePhotoChoose), findsOneWidget);
        // Nothing of the removed photo is drawn.
        expect(find.text('AB'), findsOneWidget);
      },
    );

    testWidgets('no reason given reads as the generic sentence, not a blank', (
      tester,
    ) async {
      final rig = _Rig(FakeBackend(), photo: _removed(reason: null));
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
      final rig = _Rig(backend, photo: _removed());
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
        ..on('PUT', _put, FakeResponse(200, _active('v9')));
      final rig = _Rig(
        backend,
        picker: _pickerReturning(_file()),
        photo: _removed(),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoChoose));
      await _until(tester, () => rig.account.photo?.photo != null);

      expect(find.text(l.profilePhotoWassla), findsNothing);
      expect(_button(l.profilePhotoChange), findsOneWidget);
    });
  });

  group('refusals', () {
    Future<(_Rig, FakeBackend)> failing(
      WidgetTester tester,
      FakeResponse response, {
      String? mime,
      String? path,
    }) async {
      final backend = FakeBackend()..on('PUT', _put, response);
      final rig = _Rig(
        backend,
        picker: _pickerReturning(path ?? _file(), mime: mime ?? 'image/jpeg'),
      );
      await rig.pump(tester);
      await tester.tap(_button(rig.l(tester).profilePhotoChoose));
      await _until(tester, () => backend.to('PUT', _put).isNotEmpty);
      await tester.pump(const Duration(milliseconds: 100));
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

    testWidgets('a file over 10 MB is refused on the phone, never sent', (
      tester,
    ) async {
      final backend = FakeBackend();
      final rig = _Rig(
        backend,
        picker: _pickerReturning(_file(size: 10 * 1024 * 1024 + 1)),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoChoose));
      await _until(
        tester,
        () => find.text(l.profilePhotoTooLarge).evaluate().isNotEmpty,
      );

      expect(backend.to('PUT', _put), isEmpty);
    });

    testWidgets(
      'a file that is not JPEG, PNG or WebP is refused on the phone',
      (tester) async {
        final backend = FakeBackend();
        final rig = _Rig(
          backend,
          picker: _pickerReturning(_file(name: 'me.gif'), mime: 'image/gif'),
        );
        await rig.pump(tester);
        final l = rig.l(tester);

        await tester.tap(_button(l.profilePhotoChoose));
        await _until(
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
      final rig = _Rig(
        backend,
        picker: (_) async =>
            throw PlatformException(code: 'camera_access_denied'),
      );
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoTake));
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
              : FakeResponse(200, _active()),
        );
      final rig = _Rig(backend, picker: _pickerReturning(_file()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoChoose));
      await _until(tester, () => backend.to('PUT', _put).isNotEmpty);
      await tester.pump(const Duration(milliseconds: 100));

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
      await _until(tester, () => rig.account.photo?.photo != null);

      expect(backend.to('PUT', _put), hasLength(2));
      expect(find.text(l.profilePhotoStorageUnavailable), findsNothing);
    });

    testWidgets('a server error offers "try again" and sends once per tap', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('PUT', _put, const FakeResponse(500, {'detail': 'boom'}));
      final rig = _Rig(backend, picker: _pickerReturning(_file()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoChoose));
      await _until(tester, () => backend.to('PUT', _put).isNotEmpty);
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text(l.profilePhotoFailed), findsOneWidget);
      expect(backend.to('PUT', _put), hasLength(1));

      await tester.tap(find.text(l.actionRetry));
      await _until(tester, () => backend.to('PUT', _put).length == 2);
      await tester.pump(const Duration(milliseconds: 100));

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
      final rig = _Rig(backend, picker: _pickerReturning(_file()));
      await rig.pump(tester);
      final l = rig.l(tester);

      await tester.tap(_button(l.profilePhotoChoose));
      await _until(tester, () => backend.to('PUT', _put).isNotEmpty);
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text(l.profilePhotoOffline), findsOneWidget);
      expect(find.text(l.actionRetry), findsOneWidget);
      expect(backend.to('PUT', _put), hasLength(1));
    });
  });

  group('layout', () {
    testWidgets('Arabic: right to left, Modern Standard Arabic, no overflow', (
      tester,
    ) async {
      final rig = _Rig(FakeBackend(), photo: _removed());
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

    for (final device in [
      _small,
      DeviceProfile.smallAndroid,
      DeviceProfile.landscape,
      DeviceProfile.largeText,
    ]) {
      for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
        testWidgets(
          '${device.name} / ${locale.languageCode}: every state fits',
          (tester) async {
            final rig = _Rig(
              FakeBackend()..on('PUT', _put, const FakeResponse(500)),
              picker: _pickerReturning(_file()),
              photo: _removed(),
            );
            await rig.pump(tester, locale: locale, device: device);
            final l = rig.l(tester);
            expect(tester.takeException(), isNull, reason: 'removed notice');

            await tester.ensureVisible(_button(l.profilePhotoChoose));
            await tester.pump();
            await tester.tap(_button(l.profilePhotoChoose));
            await _until(tester, () => rig.backend.to('PUT', _put).isNotEmpty);
            await tester.pump(const Duration(milliseconds: 100));
            expect(tester.takeException(), isNull, reason: 'upload failed');
          },
        );
      }
    }
  });
}
