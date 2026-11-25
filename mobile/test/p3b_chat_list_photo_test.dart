/// P3B: the chat list shows each counterparty's photo.
///
/// Thread rows carry `counterparty_photo`. A row with a photo draws it; a row
/// without one, and a row whose counterparty deleted their account, is initials.
/// Message bubbles never carry an avatar.
library;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/features/chat/chat_list_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';
import 'support/photo_cache.dart';

Map<String, dynamic> _thread(
  int matchId,
  String name, {
  Map<String, dynamic>? photo,
  bool deleted = false,
  bool canSend = true,
}) => {
  'match_id': matchId,
  'deal_id': matchId,
  'counterparty_id': 100 + matchId,
  'counterparty_name': name,
  'counterparty_photo': photo,
  'counterparty_deleted': deleted,
  'route': 'Paris - Algiers',
  'status': 'accepted',
  'can_send': canSend,
  'unread_count': 0,
};

Future<void> _pump(
  WidgetTester tester,
  List<Map<String, dynamic>> threads, {
  Locale locale = const Locale('en'),
  DeviceProfile device = DeviceProfile.android,
}) async {
  final backend = FakeBackend()
    ..on('GET', '/api/me', FakeResponse(200, meFixture()))
    ..on('GET', '/api/chat/threads', FakeResponse(200, threads));
  await pumpApp(
    tester,
    const ChatListScreen(),
    container: containerFor(backend),
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
  await settlePhotos(tester);
}

Finder get _pictures => find.descendant(
  of: find.byType(AppAvatar),
  matching: find.byType(RawImage),
);

/// A test, ending with the screen gone and its polling timer let run out.
void _test(String description, Future<void> Function(WidgetTester) body) =>
    testWidgets(description, (tester) async {
      await body(tester);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(seconds: 5));
    });

void main() {
  setUp(() => imageCache.clear());

  _test('a row with a photo draws it, a row without shows initials', (
    tester,
  ) async {
    installPhotoCache(PhotoCacheBehavior.serve);
    await _pump(tester, [
      _thread(1, 'Karim', photo: photoFixture('k1')),
      _thread(2, 'Yacine'),
    ]);

    expect(find.byType(AppAvatar), findsNWidgets(2));
    expect(find.byType(CachedNetworkImage), findsOneWidget);
    expect(_pictures, findsOneWidget);
    // Both initials are in the tree: the photo covers Karim's.
    expect(find.text('K'), findsOneWidget);
    expect(find.text('Y'), findsOneWidget);
  });

  _test('a deleted counterparty is initials, whatever the row carries', (
    tester,
  ) async {
    installPhotoCache(PhotoCacheBehavior.serve);
    await _pump(tester, [
      _thread(1, 'Karim', photo: photoFixture('k1'), deleted: true),
    ]);

    expect(find.byType(CachedNetworkImage), findsNothing);
    expect(find.text('Deleted account'), findsOneWidget);
  });

  _test('a closed thread still shows the photo', (tester) async {
    installPhotoCache(PhotoCacheBehavior.serve);
    await _pump(tester, [
      _thread(1, 'Karim', photo: photoFixture('k1'), canSend: false),
    ]);

    expect(_pictures, findsOneWidget);
  });

  _test('a photo that cannot load leaves the initials', (tester) async {
    installPhotoCache(PhotoCacheBehavior.fail);
    await _pump(tester, [_thread(1, 'Karim', photo: photoFixture('k1'))]);

    expect(_pictures, findsNothing);
    expect(find.text('K'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  _test('a malformed photo block is no photo', (tester) async {
    await _pump(tester, [
      _thread(1, 'Karim', photo: {'url': 'https://media.test/x.jpg'}),
    ]);

    expect(find.byType(CachedNetworkImage), findsNothing);
    expect(find.text('K'), findsOneWidget);
  });

  _test('the row reads as the person and fits 360 px in Arabic', (
    tester,
  ) async {
    installPhotoCache(PhotoCacheBehavior.serve);
    final handle = tester.ensureSemantics();
    await _pump(
      tester,
      [_thread(1, 'Karim', photo: photoFixture('k1')), _thread(2, 'Yacine')],
      locale: const Locale('ar'),
      device: const DeviceProfile(name: '360x740', size: Size(360, 740)),
    );

    expect(find.bySemanticsLabel('Karim'), findsOneWidget);
    // The avatar leads the row, so in Arabic it sits to the right of the name.
    expect(
      tester.getCenter(find.byType(AppAvatar).first).dx,
      greaterThan(tester.getCenter(find.text('Karim')).dx),
    );
    expect(tester.takeException(), isNull);
    handle.dispose();
  });
}
