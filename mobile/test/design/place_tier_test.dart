/// Phase 8E: a parent is named with the tier the catalogue records for it.
///
/// Phase 8C could only show a bare parent name, because the geography API did
/// not serve the parent's `admin_level`. "Jijel" over "Jijel" told a reader
/// nothing; "Jijel Wilaya" tells them the row is a commune inside a wilaya of
/// the same name. The tier is always the reviewed source's — a tier the
/// catalogue does not name, or one this app has no phrasing for, falls back to
/// the bare name rather than being inferred from the country.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/place.dart';
import 'package:shiptrip/domain/canonical_place.dart';

import '../support/harness.dart';

CanonicalPlace _place({
  String country = 'DZ',
  String name = 'Jijel',
  String parent = 'Jijel',
  String parentTier = 'wilaya',
}) => CanonicalPlace.fromJson({
  'id': 1801,
  'country_code': country,
  'place_type': 'locality',
  'name': name,
  'display_label': '$name · $parent',
  'parent_name': parent,
  'parent_admin_level': parentTier,
  'matching_locality': {'id': 1801, 'name': name},
  'available_for_matching': true,
});

/// Renders [placeContext] inside the real localisations for [locale].
Future<String> _context(
  WidgetTester tester,
  CanonicalPlace place, {
  Locale locale = const Locale('en'),
}) async {
  late String label;
  await pumpApp(
    tester,
    Builder(
      builder: (context) {
        label = placeContext(context, place);
        return const SizedBox.shrink();
      },
    ),
    locale: locale,
  );
  await tester.pumpAndSettle();
  return label;
}

void main() {
  testWidgets('an Algerian commune names its wilaya as a wilaya', (
    tester,
  ) async {
    // Same name, different tier: the case that read as two copies of one word.
    expect(await _context(tester, _place()), 'Jijel Wilaya');
  });

  testWidgets('each launch country gets its own tier word', (tester) async {
    expect(
      await _context(
        tester,
        _place(
          country: 'FR',
          name: 'Lille',
          parent: 'Nord',
          parentTier: 'department',
        ),
      ),
      'Nord department',
    );
    expect(
      await _context(
        tester,
        _place(
          country: 'ES',
          name: 'Alcalá de Henares',
          parent: 'Madrid',
          parentTier: 'province',
        ),
      ),
      'Madrid province',
    );
    expect(
      await _context(
        tester,
        _place(
          country: 'DE',
          name: 'Offenbach',
          parent: 'Darmstadt',
          parentTier: 'district',
        ),
      ),
      'Darmstadt district',
    );
  });

  testWidgets('a tier the catalogue does not record is never invented', (
    tester,
  ) async {
    // A distinct parent still reads as itself, untiered.
    expect(
      await _context(tester, _place(name: 'Taher', parentTier: '')),
      'Jijel',
    );
    expect(
      await _context(
        tester,
        _place(name: 'Taher', parentTier: 'canton_of_something_new'),
      ),
      'Jijel',
    );
    // Without a tier, a same-named parent is still just a duplicate, so the
    // country remains the honest answer.
    expect(await _context(tester, _place(parentTier: '')), 'Algeria');
  });

  testWidgets('a place with no parent still falls back to its country', (
    tester,
  ) async {
    expect(
      await _context(tester, _place(parent: '', parentTier: '')),
      'Algeria',
    );
  });

  testWidgets('the tier is phrased in the reader’s language', (tester) async {
    expect(
      await _context(tester, _place(), locale: const Locale('fr')),
      'Jijel (wilaya)',
    );
    expect(
      await _context(tester, _place(), locale: const Locale('ar')),
      'ولاية Jijel',
    );
  });

  testWidgets('a missing parent_admin_level does not break an old payload', (
    tester,
  ) async {
    final legacy = CanonicalPlace.fromJson(const {
      'id': 1801,
      'country_code': 'DZ',
      'place_type': 'locality',
      'name': 'Taher',
      'display_label': 'Taher · Jijel',
      'parent_name': 'Jijel',
      'matching_locality': {'id': 1801, 'name': 'Taher'},
      'available_for_matching': true,
    });
    expect(legacy.parentAdminLevel, '');
    expect(await _context(tester, legacy), 'Jijel');
  });
}
