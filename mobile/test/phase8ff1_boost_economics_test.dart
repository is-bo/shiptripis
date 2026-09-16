/// J3: Additive boost economics, server-authoritative gating, and preset chips.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/features/requests/boost_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

FakeBackend j3BoostBackend({
  bool canEdit = true,
  int currentBoostCents = 500,
  int? expectedPutCents,
}) {
  final backend = FakeBackend()
    ..on(
      'GET',
      '/api/boosts/policy',
      const FakeResponse(200, {
        'currency': 'EUR',
        'minimum_boost_eur_cents': 500,
        'maximum_boost_eur_cents': 10000,
        'preset_chips_eur_cents': [500, 1000, 1500],
      }),
    )
    ..on(
      'GET',
      '/api/parcels/42/boost',
      FakeResponse(200, {
        'delivery_request_id': 42,
        'request_status': 'open',
        'is_owner': true,
        'ranking_boost_active': currentBoostCents > 0,
        'ranking_boost_weight': 1,
        'affects_compatibility': false,
        'active_count': currentBoostCents > 0 ? 1 : 0,
        'occupied_slots': 0,
        'purchases': <Object>[],
        'boost_eur_cents': currentBoostCents,
        'can_edit': canEdit,
        'history': <Object>[],
      }),
    );

  if (expectedPutCents != null) {
    backend.handle('PUT', '/api/parcels/42/boost', (request) {
      expect(request.body, {'boost_eur_cents': expectedPutCents});
      return FakeResponse(200, {
        'delivery_request_id': 42,
        'request_status': 'open',
        'is_owner': true,
        'ranking_boost_active': expectedPutCents > 0,
        'ranking_boost_weight': 1,
        'affects_compatibility': false,
        'active_count': expectedPutCents > 0 ? 1 : 0,
        'occupied_slots': 0,
        'purchases': <Object>[],
        'boost_eur_cents': expectedPutCents,
        'can_edit': canEdit,
        'history': <Object>[],
      });
    });
  }

  return backend;
}

Future<L> pumpBoost(
  WidgetTester tester,
  Locale locale, {
  FakeBackend? backend,
  DeviceProfile device = DeviceProfile.android,
}) async {
  await pumpApp(
    tester,
    const BoostScreen(requestId: 42),
    container: containerFor(backend ?? j3BoostBackend()),
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
  return L.of(tester.element(find.byType(BoostScreen)));
}

void main() {
  for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
    testWidgets(
      'renders additive boost explainer and presets in ${locale.languageCode}',
      (tester) async {
        final l = await pumpBoost(tester, locale);
        expect(find.text(l.boostSectionTitle), findsWidgets);
        expect(find.text(l.boostExplainer), findsOneWidget);
        expect(find.text(l.actionSave), findsOneWidget);
        final action = find.ancestor(
          of: find.text(l.actionSave),
          matching: find.byType(AppButton),
        );
        expect(
          tester.getSize(action.first).height,
          greaterThanOrEqualTo(AppSpace.minTapTarget),
        );
      },
    );
  }

  testWidgets('Arabic boost screen keeps the whole screen RTL', (tester) async {
    await pumpBoost(tester, const Locale('ar'));
    expect(
      Directionality.of(tester.element(find.byType(BoostScreen))),
      TextDirection.rtl,
    );
  });

  testWidgets('sender can select a preset chip and apply boost', (
    tester,
  ) async {
    final backend = j3BoostBackend(
      currentBoostCents: 0,
      expectedPutCents: 1000,
    );
    final l = await pumpBoost(tester, const Locale('en'), backend: backend);

    await tester.tap(find.text(l.boostPreset10));
    await tester.pumpAndSettle();

    await tester.tap(find.text(l.actionSave));
    await tester.pumpAndSettle();
  });

  testWidgets('disables editing when can_edit is false from server', (
    tester,
  ) async {
    final backend = j3BoostBackend(canEdit: false);
    final l = await pumpBoost(tester, const Locale('en'), backend: backend);

    expect(find.text(l.boostNotEditable), findsWidgets);
    expect(find.byType(AppButton), findsNothing);
  });

  testWidgets('boost screen remains scrollable with large accessible text', (
    tester,
  ) async {
    await pumpBoost(
      tester,
      const Locale('en'),
      device: DeviceProfile.largeText,
    );
    expect(tester.takeException(), isNull);
    expect(find.byType(Scrollable), findsWidgets);
  });
}
