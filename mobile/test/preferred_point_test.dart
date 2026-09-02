/// Phase 8C: the optional preferred meeting point stays optional.
///
/// The product distinction these tests defend is the one the flow is easiest
/// to get wrong: the **canonical place** decides matching and is required, and
/// the **preferred point** decides nothing and is not. A form that renders the
/// second like the first quietly makes every sender believe they must drop a
/// map pin before they can post anything.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/place.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/location.dart';
import 'package:shiptrip/features/location/location_picker_screen.dart';
import 'package:shiptrip/features/location/preferred_point_field.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

final _jijel = CanonicalPlace.fromJson(const {
  'id': 1801,
  'country_code': 'DZ',
  'place_type': 'locality',
  'name': 'Jijel',
  'display_label': 'Jijel · Jijel',
  'parent_name': 'Jijel',
  'latitude': '36.820600',
  'longitude': '5.766700',
  'matching_locality': {'id': 1801, 'name': 'Jijel'},
  'available_for_matching': true,
});

/// A catalogue row with no coordinates — the case the geography catalogue
/// warns about for some administrative rows.
final _uncentred = CanonicalPlace.fromJson(const {
  'id': 4242,
  'country_code': 'DE',
  'place_type': 'locality',
  'name': 'Hamburg',
  'display_label': 'Hamburg',
  'parent_name': 'Hamburg',
  'matching_locality': {'id': 4242, 'name': 'Hamburg'},
  'available_for_matching': true,
});

final _point = AppLocation.fromJson(const {
  'id': 77,
  'kind': 'map_point',
  'public_label': 'Jijel, DZ',
  'city': 'Jijel',
  'region': 'Jijel',
  'country_code': 'DZ',
  'precision': 'approximate',
  'coordinates_trusted': false,
  'private_label': 'The café by the port',
  'latitude': '36.82',
  'longitude': '5.76',
  'canonical_place': 1801,
});

void main() {
  group('Preferred point field', () {
    testWidgets('reads as answered before the user has chosen anything', (
      tester,
    ) async {
      await pumpApp(
        tester,
        Scaffold(
          body: PreferredPointField(
            place: _jijel,
            point: null,
            onChoose: () {},
            onRemove: () {},
          ),
        ),
      );
      await tester.pumpAndSettle();

      // A complete, valid answer — not an empty required field.
      expect(find.text('Flexible within Jijel'), findsOneWidget);
      expect(find.text('No exact point needed'), findsOneWidget);
      expect(find.text('Optional'), findsOneWidget);

      // And the reason it is optional is stated, not implied.
      expect(
        find.text(
          'Travellers are matched on Jijel. A preferred point only says where '
          'you would rather meet inside it.',
        ),
        findsOneWidget,
      );

      // Nothing to remove yet.
      expect(find.bySemanticsLabel('Remove preferred point'), findsNothing);
    });

    testWidgets('a chosen point can be removed, not only replaced', (
      tester,
    ) async {
      var removed = 0;
      await pumpApp(
        tester,
        Scaffold(
          body: PreferredPointField(
            place: _jijel,
            point: _point,
            onChoose: () {},
            onRemove: () => removed++,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('The café by the port'), findsOneWidget);
      expect(find.text('Change point'), findsOneWidget);

      await tester.tap(find.byIcon(Icons.close_rounded));
      await tester.pump();
      expect(removed, 1);
    });
  });

  group('Map step', () {
    Future<void> pumpMap(WidgetTester tester, CanonicalPlace place) async {
      final backend = FakeBackend()
        ..on('GET', '/api/locations', const FakeResponse(200, <Object>[]));
      await pumpRouted(
        tester,
        LocationPickerScreen(canonicalPlace: place),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('keeps the chosen place on screen and names it in the help', (
      tester,
    ) async {
      await pumpMap(tester, _jijel);

      // The map narrows a point *inside* a place that is already decided; the
      // screen has to say which, or it reads as the map defining the city.
      expect(find.byType(PlaceContextStrip), findsOneWidget);
      expect(find.text('Point inside'), findsOneWidget);
      expect(find.text('Jijel'), findsOneWidget);
      expect(
        find.text(
          'Move the map until the crosshair sits where you mean inside Jijel, '
          'then confirm.',
        ),
        findsOneWidget,
      );

      // Leaving without a point is an offered move, not a deduction from the
      // back arrow.
      expect(find.text('Decide later'), findsOneWidget);
    });

    testWidgets('says so when the catalogue has no centre to open on', (
      tester,
    ) async {
      await pumpMap(tester, _uncentred);
      expect(
        find.textContaining('no centre on file for Hamburg'),
        findsWidgets,
      );
    });

    testWidgets('a place with a centre carries no such warning', (
      tester,
    ) async {
      await pumpMap(tester, _jijel);
      expect(find.textContaining('no centre on file'), findsNothing);
    });
  });
}
