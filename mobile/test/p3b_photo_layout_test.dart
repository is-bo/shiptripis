/// P3B second pass: every state the photo section can be in, on every phone
/// shape and in every language, and the same states inside the real Profile
/// screen under the bottom navigation.
///
/// Each state is driven the way a member reaches it (a real pick against a fake
/// server), then three things are asserted: the message the member should read
/// is on screen, every action they should be able to take is reachable (inside
/// the viewport, not covered by anything), and nothing overflowed.
library;

import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/core/media/photo_prepare.dart' show PhotoPrepareFailed;
import 'package:shiptrip/design/components/navigation.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/features/profile/profile_photo_section.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';
import 'support/photo_cache.dart';
import 'support/photo_rig.dart';

const _put = photoPut;

const _phone360 = DeviceProfile(name: '360x740', size: Size(360, 740));

const _devices = [
  _phone360,
  DeviceProfile.smallAndroid,
  DeviceProfile.landscape,
  DeviceProfile.largeText,
];

const _locales = [Locale('en'), Locale('fr'), Locale('ar')];

/// One state of the section: how to reach it, what is said, what can be done.
class _Scenario {
  const _Scenario(
    this.name, {
    required this.make,
    required this.messages,
    required this.actions,
    this.drive = _noDrive,
    this.disabled = const [],
  });

  final String name;

  /// A rig whose fake server, picker and preparer lead to this state.
  final PhotoRig Function() make;

  /// Brings the screen to the state, from what [make] pumped.
  final Future<void> Function(WidgetTester tester, PhotoRig rig) drive;

  /// Text that must be on screen (found as a substring of a line).
  final List<String Function(L l)> messages;

  /// Labels of the buttons or links a member can press here.
  final List<String Function(L l)> actions;

  /// Labels that must be on screen but not pressable (busy).
  final List<String Function(L l)> disabled;

  static Future<void> _noDrive(WidgetTester tester, PhotoRig rig) async {}
}

Future<void> _choose(WidgetTester tester, PhotoRig rig) async {
  final l = rig.l(tester);
  final button = photoButton(l.profilePhotoChoose);
  await tester.ensureVisible(button);
  await tester.pump();
  await tester.tap(button);
}

/// Picks, then waits for a notice (a refusal or a failure) to appear.
Future<void> _chooseUntilNotice(WidgetTester tester, PhotoRig rig) async {
  await _choose(tester, rig);
  await untilReached(
    tester,
    () => find.byType(InfoNotice).evaluate().isNotEmpty,
  );
}

PhotoRig _rigFailing(FakeResponse response, {Map<String, dynamic>? photo}) {
  final backend = FakeBackend()..on('PUT', _put, response);
  return PhotoRig(backend, picker: pickerReturning(sourceFile()), photo: photo);
}

List<_Scenario> _scenarios() => [
  _Scenario(
    'empty',
    make: () => PhotoRig(FakeBackend()),
    messages: [(l) => l.profilePhotoHelpEmpty],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'active',
    make: () => PhotoRig(FakeBackend(), photo: photoActive()),
    messages: [(l) => l.profilePhotoHelpActive],
    actions: [(l) => l.profilePhotoChange, (l) => l.profilePhotoRemove],
  ),
  _Scenario(
    'active, address not signed',
    make: () => PhotoRig(FakeBackend(), photo: photoActiveUnsigned()),
    messages: [(l) => l.profilePhotoHelpActive],
    actions: [(l) => l.profilePhotoChange, (l) => l.profilePhotoRemove],
  ),
  _Scenario(
    'removed by Wassla, with a reason',
    make: () => PhotoRig(FakeBackend(), photo: photoRemoved()),
    messages: [
      (l) => l.profilePhotoWassla,
      (l) => l.profilePhotoWasslaBody,
      (l) => 'Not a photo of you.',
    ],
    actions: [
      (l) => l.profilePhotoDismiss,
      (l) => l.profilePhotoTake,
      (l) => l.profilePhotoChoose,
    ],
  ),
  _Scenario(
    'removed by Wassla, no reason',
    make: () => PhotoRig(FakeBackend(), photo: photoRemoved(reason: null)),
    messages: [(l) => l.profilePhotoWassla, (l) => l.profilePhotoWasslaBody],
    actions: [
      (l) => l.profilePhotoDismiss,
      (l) => l.profilePhotoTake,
      (l) => l.profilePhotoChoose,
    ],
  ),
  _Scenario(
    'uploading',
    make: () {
      final gate = Completer<FakeResponse>();
      final backend = FakeBackend()..handle('PUT', _put, (_) => gate.future);
      return PhotoRig(backend, picker: pickerReturning(sourceFile()));
    },
    drive: (tester, rig) async {
      await _choose(tester, rig);
      await untilReached(tester, () => rig.backend.to('PUT', _put).isNotEmpty);
    },
    messages: [(l) => l.profilePhotoUploading],
    actions: const [],
    disabled: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'too large (413, no JSON)',
    make: () => _rigFailing(FakeResponse.raw(413, '<html>413</html>')),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoTooLarge],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'unsupported type (415)',
    make: () => _rigFailing(
      const FakeResponse(415, {'code': 'profile_photo_media_type_unsupported'}),
    ),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoTypeNotAllowed],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'account inactive (403)',
    make: () => _rigFailing(
      const FakeResponse(403, {'code': 'account_inactive', 'detail': 'No.'}),
    ),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoAccountInactive],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'storage unavailable (503)',
    make: () => _rigFailing(
      const FakeResponse(503, {'code': 'profile_photo_storage_unavailable'}),
    ),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoStorageUnavailable],
    actions: [
      (l) => l.actionRetry,
      (l) => l.profilePhotoTake,
      (l) => l.profilePhotoChoose,
      (l) => l.profilePhotoDiscard,
    ],
  ),
  _Scenario(
    'offline',
    make: () {
      final backend = FakeBackend()
        ..handle(
          'PUT',
          _put,
          (_) => throw DioException.connectionError(
            requestOptions: RequestOptions(path: _put),
            reason: 'offline',
          ),
        );
      return PhotoRig(backend, picker: pickerReturning(sourceFile()));
    },
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoOffline],
    actions: [
      (l) => l.actionRetry,
      (l) => l.profilePhotoTake,
      (l) => l.profilePhotoChoose,
      (l) => l.profilePhotoDiscard,
    ],
  ),
  _Scenario(
    'general error (500)',
    make: () => _rigFailing(const FakeResponse(500, {'detail': 'boom'})),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoFailed],
    actions: [
      (l) => l.actionRetry,
      (l) => l.profilePhotoTake,
      (l) => l.profilePhotoChoose,
      (l) => l.profilePhotoDiscard,
    ],
  ),
  _Scenario(
    'session expired mid-upload (401)',
    make: () {
      final backend = FakeBackend()
        ..on('PUT', _put, const FakeResponse(401, {'detail': 'Expired.'}))
        ..on(
          'POST',
          '/api/auth/refresh',
          const FakeResponse(200, {'access': 'fresh'}),
        );
      return PhotoRig(backend, picker: pickerReturning(sourceFile()));
    },
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoFailed],
    actions: [
      (l) => l.actionRetry,
      (l) => l.profilePhotoTake,
      (l) => l.profilePhotoChoose,
      (l) => l.profilePhotoDiscard,
    ],
  ),
  _Scenario(
    'the picked file is gone',
    make: () => PhotoRig(
      FakeBackend(),
      picker: pickerReturning(sourceFile()),
      preparer: (path) async => throw FileSystemException('gone', path),
    ),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoUnreadable],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'the camera or library refused',
    make: () => PhotoRig(
      FakeBackend(),
      picker: (_) async => throw PlatformException(code: 'denied'),
    ),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoPickFailed],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'a pick that an earlier pick may have answered',
    make: () => PhotoRig(
      FakeBackend(),
      tokens: FakeTokenStore()..pendingPick = 'identityDocument:abc',
      picker: (_) async => XFile(sourceFile()),
    ),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoUncertain],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'a photo the phone could not get ready',
    make: () => PhotoRig(
      FakeBackend(),
      picker: (_) async => XFile(sourceFile()),
      preparer: (_) async => throw const PhotoPrepareFailed(),
    ),
    drive: _chooseUntilNotice,
    messages: [(l) => l.profilePhotoPrepareFailed],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'the pick could not be given an owner',
    make: () => PhotoRig(
      FakeBackend(),
      tokens: FakeTokenStore()..pendingPickWritesFail = true,
    ),
    drive: _chooseUntilNotice,
    messages: [(l) => l.photoPickBlocked],
    actions: [(l) => l.profilePhotoTake, (l) => l.profilePhotoChoose],
  ),
  _Scenario(
    'a failed replacement of an active photo',
    make: () => _rigFailing(
      const FakeResponse(503, {'code': 'profile_photo_storage_unavailable'}),
      photo: photoActive(),
    ),
    drive: (tester, rig) async {
      final l = rig.l(tester);
      await tester.ensureVisible(photoButton(l.profilePhotoChange));
      await tester.pump();
      await tester.tap(photoButton(l.profilePhotoChange));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.profilePhotoChoose));
      await untilReached(
        tester,
        () => find.byType(InfoNotice).evaluate().isNotEmpty,
      );
    },
    messages: [(l) => l.profilePhotoStorageUnavailable],
    actions: [
      (l) => l.actionRetry,
      (l) => l.profilePhotoChange,
      (l) => l.profilePhotoRemove,
      (l) => l.profilePhotoDiscard,
    ],
  ),
];

/// A press target the member can actually reach: it is scrolled into view and
/// nothing covers it.
Future<void> _expectReachable(
  WidgetTester tester,
  Finder target,
  String what,
) async {
  expect(target, findsWidgets, reason: '$what is on screen');
  await tester.ensureVisible(target.first);
  await tester.pump();
  expect(
    target.hitTestable(),
    findsWidgets,
    reason: '$what can be pressed (inside the screen, not covered)',
  );
}

Finder _action(String label) => find.descendant(
  of: find.byType(ProfilePhotoSection),
  matching: find.text(label),
);

void main() {
  setUp(() {
    imageCache.clear();
    // Avatars with a photo draw through the image cache.
    installPhotoCache(PhotoCacheBehavior.serve);
  });

  group('every state, on every phone shape, in every language', () {
    for (final device in _devices) {
      for (final locale in _locales) {
        testWidgets('${device.name} / ${locale.languageCode}', (tester) async {
          for (final scenario in _scenarios()) {
            final rig = scenario.make();
            await rig.pump(tester, locale: locale, device: device);
            final l = rig.l(tester);
            try {
              await scenario.drive(tester, rig);
            } on TestFailure catch (error) {
              fail('${scenario.name}: ${error.message}');
            }
            final reason =
                '${scenario.name}, ${device.name}, ${locale.languageCode}';

            for (final message in scenario.messages) {
              final text = message(l);
              expect(
                find.textContaining(text, findRichText: true),
                findsWidgets,
                reason: 'says "$text": $reason',
              );
            }
            for (final action in scenario.actions) {
              await _expectReachable(
                tester,
                _action(action(l)),
                '"${action(l)}" ($reason)',
              );
            }
            for (final label in scenario.disabled) {
              final button = photoButton(label(l));
              await tester.ensureVisible(button);
              await tester.pump();
              expect(
                photoButtonEnabled(tester, label(l)),
                isFalse,
                reason: '"${label(l)}" is busy: $reason',
              );
            }
            expect(tester.takeException(), isNull, reason: reason);
          }
        });
      }
    }
  });

  group(
    'inside the real app, on the Profile tab under the bottom navigation',
    () {
      // The states a member lives in most, and the two that add the most height.
      final shellScenarios = {
        'empty',
        'active',
        'removed by Wassla, with a reason',
        'storage unavailable (503)',
        'a failed replacement of an active photo',
      };

      Future<PhotoRig> pumpProfile(
        WidgetTester tester,
        _Scenario scenario, {
        required DeviceProfile device,
        required Locale locale,
      }) async {
        final rig = scenario.make();
        await rig.pumpRealApp(tester, locale: locale, device: device);
        return rig;
      }

      for (final device in [
        DeviceProfile.android,
        DeviceProfile.androidGesture,
        DeviceProfile.iphone,
        DeviceProfile.smallAndroid,
        DeviceProfile.landscape,
      ]) {
        for (final locale in const [Locale('en'), Locale('ar')]) {
          testWidgets('${device.name} / ${locale.languageCode}', (
            tester,
          ) async {
            for (final scenario in _scenarios().where(
              (s) => shellScenarios.contains(s.name),
            )) {
              final rig = await pumpProfile(
                tester,
                scenario,
                device: device,
                locale: locale,
              );
              final l = rig.l(tester);
              expect(
                find.text(l.navProfile),
                findsWidgets,
                reason: 'the real tab bar, in the app\'s language',
              );
              final reason =
                  '${scenario.name}, ${device.name}, ${locale.languageCode}';
              // The section is far down a lazy list: bring it into being first.
              await tester.scrollUntilVisible(
                find.text(l.profilePhotoTitle),
                300,
                scrollable: find.byType(Scrollable).first,
              );
              await scenario.drive(tester, rig);

              // Scrolled to the very end, the last line sits above the bar.
              final list = find.byType(Scrollable).first;
              await tester.fling(list, const Offset(0, -4000), 3000);
              await tester.pumpAndSettle();
              final bar = tester.getTopLeft(find.byType(AppNavigationBar)).dy;
              expect(
                tester.getRect(find.text(l.profileDeleteAccount)).bottom,
                lessThanOrEqualTo(bar + 0.5),
                reason: 'the end of the list is above the navigation: $reason',
              );

              // Back up at the section, every action is reachable, and none sits
              // under the bar.
              await tester.scrollUntilVisible(
                find.text(l.profilePhotoTitle),
                -300,
                scrollable: list,
              );
              for (final action in scenario.actions) {
                await _expectReachable(
                  tester,
                  _action(action(l)),
                  '"${action(l)}" ($reason)',
                );
                final rect = tester.getRect(_action(action(l)).first);
                expect(
                  rect.bottom,
                  lessThanOrEqualTo(bar + 0.5),
                  reason: '"${action(l)}" is above the navigation: $reason',
                );
              }
              expect(tester.takeException(), isNull, reason: reason);
            }
            // The screen's polling timers run out once it is gone.
            await tester.pumpWidget(const SizedBox.shrink());
            await tester.pump(const Duration(seconds: 10));
          });
        }
      }
    },
  );
}
