/// P3B: a person's photo in `AppAvatar`, and the top bar's avatar slot.
///
/// The picture covers the initials, and the initials are the fallback while it
/// loads and when it cannot be loaded. The cache key is the photo's version,
/// never its signed address, because the address changes on every payload.
library;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/navigation.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/person_photo.dart';
import 'package:shiptrip/domain/public_discovery.dart';
import 'package:shiptrip/features/discovery/discovery_widgets.dart';

import 'support/harness.dart';
import 'support/photo_cache.dart';

const _photo = PersonPhoto(
  url: 'https://media.test/a.jpg?sig=1',
  version: 'v1',
);

Widget _avatar({PersonPhoto? photo = _photo}) =>
    AppAvatar(initials: 'SA', name: 'Samira', photo: photo, size: 48);

/// Every painted picture inside the avatar.
Finder get _picture => find.descendant(
  of: find.byType(AppAvatar),
  matching: find.byType(RawImage),
);

void main() {
  // The image cache is process-wide and keyed by the photo's version, which is
  // the point of it; a test starts from an empty one.
  setUp(() => imageCache.clear());

  group('AppAvatar with a photo', () {
    testWidgets('no photo is initials only, with no image widget', (
      tester,
    ) async {
      await pumpApp(tester, _avatar(photo: null));

      expect(find.text('SA'), findsOneWidget);
      expect(find.byType(CachedNetworkImage), findsNothing);
    });

    testWidgets('the photo is cached by its version, not its address', (
      tester,
    ) async {
      final cache = installPhotoCache(PhotoCacheBehavior.serve);
      await pumpApp(tester, _avatar());
      await settlePhotos(tester);

      final image = tester.widget<CachedNetworkImage>(
        find.byType(CachedNetworkImage),
      );
      expect(image.imageUrl, _photo.url);
      expect(image.cacheKey, 'v1');
      expect(cache.keys, ['v1']);

      // A refreshed payload brings a new signed address for the same picture:
      // the cache key is unchanged, so nothing is asked of the network.
      await pumpApp(
        tester,
        _avatar(
          photo: const PersonPhoto(
            url: 'https://media.test/a.jpg?sig=2',
            version: 'v1',
          ),
        ),
      );
      await settlePhotos(tester);
      expect(cache.keys, ['v1']);
      expect(cache.urls, [_photo.url]);
      expect(_picture, findsOneWidget);
    });

    testWidgets('a loaded photo is painted over the initials', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      await pumpApp(tester, _avatar());
      await settlePhotos(tester);

      expect(_picture, findsOneWidget);
    });

    testWidgets('initials show while the photo is still loading', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.stall);
      await pumpApp(tester, _avatar());
      await settlePhotos(tester);

      expect(find.text('SA'), findsOneWidget);
      expect(_picture, findsNothing);
    });

    testWidgets('initials stay when the photo cannot be loaded', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.fail);
      await pumpApp(tester, _avatar());
      await settlePhotos(tester);

      expect(find.text('SA'), findsOneWidget);
      expect(_picture, findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('it is read as the person, and the image is not in semantics', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final handle = tester.ensureSemantics();
      await pumpApp(tester, _avatar());
      await settlePhotos(tester);

      expect(find.bySemanticsLabel('Samira'), findsOneWidget);
      final node = tester.getSemantics(find.byType(AppAvatar));
      expect(node.label, 'Samira');
      // The initials and the picture are folded into the one name.
      expect(find.bySemanticsLabel('SA'), findsNothing);
      handle.dispose();
    });
  });

  group('a person row', () {
    PublicPerson person({PersonPhoto? photo}) =>
        PublicPerson(displayName: 'Samira', photo: photo);

    testWidgets('draws the person\'s photo', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      await pumpApp(tester, PublicPersonRow(person: person(photo: _photo)));
      await settlePhotos(tester);

      expect(_picture, findsOneWidget);
    });

    testWidgets('puts the avatar first in both directions', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      await pumpApp(tester, PublicPersonRow(person: person(photo: _photo)));
      await settlePhotos(tester);
      expect(
        tester.getCenter(find.byType(AppAvatar)).dx,
        lessThan(tester.getCenter(find.text('Samira')).dx),
      );

      await pumpApp(
        tester,
        PublicPersonRow(person: person(photo: _photo)),
        locale: const Locale('ar'),
      );
      await settlePhotos(tester);
      expect(
        tester.getCenter(find.byType(AppAvatar)).dx,
        greaterThan(tester.getCenter(find.text('Samira')).dx),
      );
    });
  });

  group('the top bar avatar slot', () {
    Widget bar({Widget? titleLeading}) => Scaffold(
      appBar: AppTopBar(
        title: 'Samira',
        subtitle: 'Alger → Paris',
        titleLeading: titleLeading,
        showBack: true,
      ),
    );

    testWidgets('nothing in the slot leaves the bar as it was', (tester) async {
      await pumpApp(tester, bar());

      expect(find.byType(AppAvatar), findsNothing);
      expect(find.text('Samira'), findsOneWidget);
    });

    testWidgets('the avatar comes before the title and is not announced', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final handle = tester.ensureSemantics();
      await pumpApp(tester, bar(titleLeading: _avatar()));
      await settlePhotos(tester);

      expect(
        tester.getCenter(find.byType(AppAvatar)).dx,
        lessThan(tester.getCenter(find.text('Samira')).dx),
      );
      // The title is the bar's name; the avatar adds no second "Samira".
      expect(find.bySemanticsLabel('Samira'), findsOneWidget);
      handle.dispose();
    });

    testWidgets('it mirrors in Arabic', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      await pumpApp(
        tester,
        bar(titleLeading: _avatar()),
        locale: const Locale('ar'),
      );
      await settlePhotos(tester);

      expect(
        tester.getCenter(find.byType(AppAvatar)).dx,
        greaterThan(tester.getCenter(find.text('Samira')).dx),
      );
    });
  });
}
