/// Phase 8C: the canonical COUNTRY → PLACE picker.
///
/// These tests hold the *product* promises, not the pixels: every launch
/// country is reachable without a hidden gesture, an airport is distinguishable
/// from a town without reading, the search is bounded to one country, a stale
/// response cannot overwrite a fresh one, no state is ever a blank page, and a
/// dependent reset is one the user watched happen.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/design/components/place.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/features/location/canonical_place_picker_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _countries = [
  {'code': 'DZ', 'name': 'Algeria', 'active': true},
  {'code': 'FR', 'name': 'France', 'active': true},
  {'code': 'ES', 'name': 'Spain', 'active': true},
  {'code': 'DE', 'name': 'Germany', 'active': true},
];

Map<String, dynamic> _place({
  int id = 1801,
  String country = 'DZ',
  String type = 'locality',
  String name = 'Jijel',
  String parent = 'Jijel Wilaya',
  String parentTier = '',
  String? iata,
  int matchingId = 1801,
  String? searchRelation,
  String? searchContext,
  double? searchDistanceKm,
}) => {
  'id': id,
  'country_code': country,
  'place_type': type,
  'name': name,
  'display_label': parent.isEmpty ? name : '$name · $parent',
  'parent_name': parent,
  'parent_admin_level': parentTier,
  'iata_code': iata,
  'latitude': '36.820600',
  'longitude': '5.766700',
  'matching_locality': {'id': matchingId, 'name': name},
  'available_for_matching': true,
  'search_relation': searchRelation,
  'search_context': searchContext == null
      ? null
      : {'id': matchingId, 'name': searchContext},
  'search_distance_km': searchDistanceKm,
};

FakeBackend _backendWithPlaces(Object places) => FakeBackend()
  ..on('GET', '/api/geography/countries', const FakeResponse(200, _countries))
  ..on(
    'GET',
    '/api/geography/places',
    FakeResponse(200, {'count': (places as List).length, 'results': places}),
  );

Future<void> _selectAndSearch(
  WidgetTester tester, {
  required String country,
  required String query,
}) async {
  await tester.tap(find.text(country));
  await tester.pumpAndSettle();
  await tester.enterText(find.byType(TextField), query);
  await tester.pump(const Duration(milliseconds: 301));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('every launch country is reachable without a hidden gesture', (
    tester,
  ) async {
    final backend = _backendWithPlaces(<Object>[]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();

    // Present *and* hit-testable: a strip that scrolls the fourth country off
    // the edge passes a `findsOneWidget` and still loses the user.
    for (final country in const ['Algeria', 'France', 'Spain', 'Germany']) {
      expect(find.text(country), findsOneWidget);
      await tester.tap(find.text(country), warnIfMissed: false);
      await tester.pumpAndSettle();
      expect(
        find.byType(TextField),
        findsOneWidget,
        reason: '$country must be tappable, not merely rendered',
      );
      await tester.tap(find.text('Change'));
      await tester.pumpAndSettle();
    }
  });

  for (final entry in const {
    'Algeria': 'DZ',
    'France': 'FR',
    'Spain': 'ES',
    'Germany': 'DE',
  }.entries) {
    testWidgets('${entry.key} search stays bounded to the selected country', (
      tester,
    ) async {
      final backend = _backendWithPlaces([
        _place(country: entry.value, name: 'Matching result'),
      ]);
      await pumpApp(
        tester,
        const CanonicalPlacePickerScreen(),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();

      await _selectAndSearch(tester, country: entry.key, query: 'matching');

      final request = backend.lastTo('GET', '/api/geography/places');
      expect(request?.query['country'], entry.value);
      expect(request?.query['q'], 'matching');
      expect(request?.query['page_size'], '25');
      expect(request?.query['place_type'], 'locality,airport');
      expect(find.text('Matching result'), findsOneWidget);
    });
  }

  testWidgets('an airport is unmistakable and never falls back to a raw code', (
    tester,
  ) async {
    final backend = _backendWithPlaces([
      _place(
        id: 9001,
        country: 'FR',
        type: 'airport',
        name: 'Paris Charles de Gaulle',
        parent: '',
        iata: 'CDG',
        matchingId: 75056,
      ),
    ]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'France', query: 'charles');

    expect(find.text('Paris Charles de Gaulle'), findsOneWidget);
    // Three independent airport signals: the glyph, the word, the code.
    expect(find.byType(PlaceGlyph), findsOneWidget);
    expect(find.text('AIRPORT'), findsOneWidget);
    expect(find.byType(IataBadge), findsOneWidget);
    expect(find.text('CDG'), findsOneWidget);

    // With no parent the context is the country's *name*, never "FR".
    final row = find.byType(PlaceResultRow);
    expect(
      find.descendant(of: row, matching: find.text('France')),
      findsOneWidget,
    );
    expect(find.text('FR'), findsNothing);

    // The server's matching locality is not the user's business.
    expect(find.textContaining('Paris,'), findsNothing);
  });

  testWidgets('a city-enriched airport explains why it was recommended', (
    tester,
  ) async {
    final backend = _backendWithPlaces([
      _place(name: 'Alger Centre'),
      _place(
        id: 2050,
        type: 'airport',
        name: 'Houari Boumediene Airport',
        parent: 'Alger',
        iata: 'ALG',
        searchRelation: 'serves_place',
        searchContext: 'Alger Centre',
      ),
    ]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'Algeria', query: 'alger');

    expect(find.text('Alger Centre'), findsOneWidget);
    expect(find.text('Houari Boumediene Airport'), findsOneWidget);
    expect(find.text('Serves Alger Centre'), findsOneWidget);
    expect(find.text('ALG'), findsOneWidget);
    expect(
      find.bySemanticsLabel(
        'Houari Boumediene Airport, Airport, A L G, Serves Alger Centre',
      ),
      findsOneWidget,
    );
  });

  testWidgets('a proximity fallback is labelled as nearby in Arabic RTL', (
    tester,
  ) async {
    final backend = _backendWithPlaces([
      _place(
        id: 2050,
        type: 'airport',
        name: 'مطار هواري بومدين',
        parent: '',
        iata: 'ALG',
        searchRelation: 'nearby',
        searchContext: 'الجزائر الوسطى',
        searchDistanceKm: 16.4,
      ),
    ]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
      locale: const Locale('ar'),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'الجزائر', query: 'الجزائر');

    expect(find.text('بالقرب من الجزائر الوسطى'), findsOneWidget);
    expect(find.text('ALG'), findsOneWidget);
    expect(
      Directionality.of(
        tester.element(find.byType(CanonicalPlacePickerScreen)),
      ),
      TextDirection.rtl,
    );
  });

  testWidgets('a served-airport explanation is localized in French', (
    tester,
  ) async {
    final backend = _backendWithPlaces([
      _place(
        id: 2050,
        type: 'airport',
        name: 'Aéroport Houari Boumédiène',
        iata: 'ALG',
        searchRelation: 'serves_place',
        searchContext: 'Alger Centre',
      ),
    ]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
      locale: const Locale('fr'),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'Algérie', query: 'alger');

    expect(find.text('Dessert Alger Centre'), findsOneWidget);
  });

  testWidgets('duplicate API rows never become duplicate choices', (
    tester,
  ) async {
    final airport = _place(
      id: 2050,
      type: 'airport',
      name: 'Houari Boumediene Airport',
      iata: 'ALG',
      searchRelation: 'serves_place',
      searchContext: 'Alger Centre',
    );
    final backend = _backendWithPlaces([airport, airport]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'Algeria', query: 'alger');

    expect(find.byType(PlaceResultRow), findsOneWidget);
    expect(find.text('Houari Boumediene Airport'), findsOneWidget);
  });

  testWidgets('a commune never renders as two copies of its own name', (
    tester,
  ) async {
    final backend = _backendWithPlaces([
      // Jijel the commune, inside Jijel the wilaya.
      _place(name: 'Jijel', parent: 'Jijel'),
      _place(id: 1802, name: 'El Milia', parent: 'Jijel'),
    ]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'Algeria', query: 'ji');

    final rows = find.byType(PlaceResultRow);
    expect(rows, findsNWidgets(2));

    // Jijel's context falls through to the country rather than stacking a
    // second, identical "Jijel" under the first.
    expect(
      find.descendant(of: rows.at(0), matching: find.text('Jijel')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: rows.at(0), matching: find.text('Algeria')),
      findsOneWidget,
    );

    // Untiered, a same-named wilaya is only a duplicate. With the
    // catalogue's tier it becomes "Jijel Wilaya" instead; that is covered
    // in test/design/place_tier_test.dart.
    // A commune whose wilaya actually adds information still shows it.
    expect(
      find.descendant(of: rows.at(1), matching: find.text('El Milia')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: rows.at(1), matching: find.text('Jijel')),
      findsOneWidget,
    );
  });

  testWidgets('loading and no-results states are intentional', (tester) async {
    final countries = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..handle('GET', '/api/geography/countries', (_) => countries.future)
      ..on(
        'GET',
        '/api/geography/places',
        const FakeResponse(200, {'count': 0, 'results': <Object>[]}),
      );
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );

    // Shaped like the answer that is coming, not a hairline bar over nothing.
    expect(find.byType(SkeletonBox), findsWidgets);
    expect(find.bySemanticsLabel('Loading content'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNothing);

    countries.complete(const FakeResponse(200, _countries));
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'Algeria', query: 'missing');

    expect(find.text('No results'), findsOneWidget);
    // The copy quotes the query and does not send them to a map that is not
    // on this screen.
    expect(find.textContaining('missing'), findsWidgets);
    expect(find.textContaining('map'), findsNothing);
    expect(find.textContaining('internal'), findsNothing);
  });

  testWidgets('airport-only mode says so and its empty state stays honest', (
    tester,
  ) async {
    final backend = _backendWithPlaces(<Object>[]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(airportOnly: true),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('France'));
    await tester.pumpAndSettle();

    expect(
      find.text('This leg flies, so only airports are offered.'),
      findsOneWidget,
    );

    await tester.enterText(find.byType(TextField), 'lyon');
    await tester.pump(const Duration(milliseconds: 301));
    await tester.pumpAndSettle();

    final request = backend.lastTo('GET', '/api/geography/places');
    expect(request?.query['place_type'], 'airport');
    expect(find.textContaining('three-letter code'), findsOneWidget);
  });

  testWidgets('API error can be retried without leaving a blank page', (
    tester,
  ) async {
    var calls = 0;
    final backend = FakeBackend()
      ..on(
        'GET',
        '/api/geography/countries',
        const FakeResponse(200, _countries),
      )
      ..handle('GET', '/api/geography/places', (_) {
        calls++;
        return calls == 1
            ? const FakeResponse(400, {'detail': 'temporary test failure'})
            : FakeResponse(200, {
                'count': 1,
                'results': [_place()],
              });
      });
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'Algeria', query: 'jijel');

    expect(find.text('Try again'), findsOneWidget);
    await tester.tap(find.text('Try again'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(calls, 2);
    expect(find.text('Jijel'), findsOneWidget);
  });

  testWidgets('a stale slow search cannot replace the newest results', (
    tester,
  ) async {
    final backend = FakeBackend()
      ..on(
        'GET',
        '/api/geography/countries',
        const FakeResponse(200, _countries),
      )
      ..handle('GET', '/api/geography/places', (request) async {
        final query = request.query['q'];
        if (query == 'old') {
          await Future<void>.delayed(const Duration(milliseconds: 120));
          return FakeResponse(200, {
            'count': 1,
            'results': [_place(name: 'Old result')],
          });
        }
        await Future<void>.delayed(const Duration(milliseconds: 5));
        return FakeResponse(200, {
          'count': 1,
          'results': [_place(id: 2, name: 'Newest result')],
        });
      });
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Algeria'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'old');
    await tester.pump(const Duration(milliseconds: 301));
    await tester.enterText(find.byType(TextField), 'new');
    await tester.pump(const Duration(milliseconds: 301));
    await tester.pump(const Duration(milliseconds: 130));

    expect(find.text('Newest result'), findsOneWidget);
    expect(find.text('Old result'), findsNothing);
  });

  testWidgets('changing country is a visible reset, not a silent one', (
    tester,
  ) async {
    final backend = _backendWithPlaces([_place(country: 'FR', name: 'Paris')]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'France', query: 'paris');
    expect(find.text('Paris'), findsOneWidget);

    // The chosen country stays on screen after the choice, and carries its own
    // way out.
    expect(find.text('France'), findsOneWidget);
    await tester.tap(find.text('Change'));
    await tester.pumpAndSettle();

    // Back on the country question, with the query and its results gone.
    expect(find.text('Which country?'), findsOneWidget);
    expect(find.text('Paris'), findsNothing);
    expect(find.byType(TextField), findsNothing);

    await tester.tap(find.text('Algeria'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<TextField>(find.byType(TextField)).controller?.text,
      '',
    );
  });

  testWidgets('re-opening to change a place resumes instead of restarting', (
    tester,
  ) async {
    final current = CanonicalPlace.fromJson(_place(name: 'Jijel'));
    final backend = _backendWithPlaces([_place(name: 'Jijel')]);
    await pumpApp(
      tester,
      CanonicalPlacePickerScreen(current: current),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();

    // Country already answered, current choice restated rather than forgotten.
    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('Algeria'), findsOneWidget);
    expect(find.text('Currently selected'), findsOneWidget);
    expect(find.text('Jijel'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'jijel');
    await tester.pump(const Duration(milliseconds: 301));
    await tester.pumpAndSettle();

    // And the row that is already chosen is marked as such.
    final row = tester.widget<PlaceResultRow>(find.byType(PlaceResultRow));
    expect(row.selected, isTrue);
  });

  testWidgets('Arabic RTL and a short keyboard viewport remain usable', (
    tester,
  ) async {
    final backend = _backendWithPlaces(<Object>[]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
      locale: const Locale('ar'),
      device: DeviceProfile.smallAndroid,
      keyboardInset: 250,
    );
    await tester.pumpAndSettle();

    expect(
      Directionality.of(
        tester.element(find.byType(CanonicalPlacePickerScreen)),
      ),
      TextDirection.rtl,
    );

    // Countries read in Arabic, not as Latin catalogue names.
    expect(find.text('الجزائر'), findsOneWidget);
    expect(find.text('Algeria'), findsNothing);

    await tester.tap(find.text('الجزائر'));
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('an airport code is never re-ordered by an Arabic layout', (
    tester,
  ) async {
    final backend = _backendWithPlaces([
      _place(
        id: 9002,
        country: 'DZ',
        type: 'airport',
        name: 'مطار هواري بومدين',
        parent: '',
        iata: 'ALG',
      ),
    ]);
    await pumpApp(
      tester,
      const CanonicalPlacePickerScreen(),
      container: containerFor(backend),
      locale: const Locale('ar'),
    );
    await tester.pumpAndSettle();
    await _selectAndSearch(tester, country: 'الجزائر', query: 'ALG');

    final badge = find.descendant(
      of: find.byType(IataBadge),
      matching: find.byType(Directionality),
    );
    expect(
      tester.widget<Directionality>(badge).textDirection,
      TextDirection.ltr,
    );
  });

  // ---------------------------------------------------------------------------
  // Rendered
  // ---------------------------------------------------------------------------

  /// The visual pass, run at the metrics a screenshot would have been used to
  /// check: a 320-point Android, a gesture pill, a home indicator, landscape,
  /// and 1.6x text. Overflow throws in debug, so a silent run is the
  /// assertion; the explicit checks are for the two things overflow does not
  /// catch — a header that has eaten the results, and a string that never got
  /// translated.
  for (final device in DeviceProfile.all) {
    for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
      testWidgets(
        'the picker survives ${device.name} in ${locale.languageCode}',
        (tester) async {
          final backend = _backendWithPlaces([
            _place(
              name: 'Bordj Bou Arréridj',
              parent: 'Bordj Bou Arréridj',
              parentTier: 'wilaya',
            ),
            _place(
              id: 2,
              name: 'Villeneuve-d\'Ascq',
              parent: 'Nord',
              parentTier: 'department',
            ),
            _place(
              id: 3,
              name: 'Schwäbisch Gmünd',
              parent: 'Ostalbkreis',
              parentTier: 'district',
            ),
            _place(
              id: 4,
              type: 'airport',
              name: 'Aeropuerto Adolfo Suárez Madrid-Barajas',
              parent: 'Madrid',
              parentTier: 'province',
              iata: 'MAD',
            ),
          ]);
          await pumpApp(
            tester,
            const CanonicalPlacePickerScreen(),
            container: containerFor(backend),
            device: device,
            locale: locale,
          );
          await tester.pumpAndSettle();

          // Country stage: every country reachable, no English leaking into a
          // translated build.
          expect(find.byType(CountryChoiceTile), findsNWidgets(4));
          if (locale.languageCode == 'ar') {
            expect(find.text('Algeria'), findsNothing);
          }

          await tester.tap(find.byType(CountryChoiceTile).first);
          await tester.pumpAndSettle();
          await tester.enterText(find.byType(TextField), 'a');
          await tester.pump(const Duration(milliseconds: 301));
          await tester.pumpAndSettle();

          // The search box is still on screen with results under it — the whole
          // reason the header is pinned rather than scrolled.
          expect(find.byType(TextField), findsOneWidget);
          expect(find.byType(PlaceResultRow), findsWidgets);
          expect(tester.takeException(), isNull);
        },
      );
    }
  }
}
