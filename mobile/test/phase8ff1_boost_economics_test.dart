/// Phase 8F-F1: variable boost economics are reviewed before checkout.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/features/requests/boost_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

FakeBackend boostBackend({int expectedAmountEurCents = 500}) => FakeBackend()
  ..on(
    'GET',
    '/api/boosts/packages',
    const FakeResponse(200, {
      'enabled': true,
      'max_active_per_request': 2,
      'currency': 'EUR',
      'settings_version': 6,
      'minimum_amount_eur_cents': 500,
      'traveler_share_bps': 7500,
      'packages': [
        {
          'code': 'boost_24h',
          'label': '24 hours',
          'duration_seconds': 86400,
          'ranking_weight': 2,
          'currency': 'EUR',
        },
      ],
    }),
  )
  ..on(
    'GET',
    '/api/parcels/42/boosts',
    const FakeResponse(200, {
      'delivery_request_id': 42,
      'request_status': 'open',
      'is_owner': true,
      'ranking_boost_active': false,
      'ranking_boost_weight': 0,
      'affects_compatibility': false,
      'active_count': 0,
      'occupied_slots': 0,
      'purchases': <Object>[],
    }),
  )
  ..handle('POST', '/api/boosts/preview', (request) {
    expect(request.body, {
      'package_code': 'boost_24h',
      'amount_eur_cents': expectedAmountEurCents,
    });
    final traveler = (expectedAmountEurCents * 7500) ~/ 10000;
    return FakeResponse(200, {
      'settings_version': 6,
      'amount_eur_cents': expectedAmountEurCents,
      'traveler_boost_eur_cents': traveler,
      'platform_boost_eur_cents': expectedAmountEurCents - traveler,
      'traveler_share_bps': 7500,
      'visibility': {
        'duration_seconds': 86400,
        'ranking_weight': 2,
        'affects_compatibility': false,
      },
    });
  });

Future<L> pumpReviewed(
  WidgetTester tester,
  Locale locale, {
  DeviceProfile device = DeviceProfile.android,
}) async {
  await pumpApp(
    tester,
    const BoostScreen(requestId: 42),
    container: containerFor(boostBackend()),
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
  final l = L.of(tester.element(find.byType(BoostScreen)));
  await tester.scrollUntilVisible(
    find.text('24 hours'),
    180,
    scrollable: find.byType(Scrollable).first,
  );
  await tester.tap(find.text('24 hours'));
  await tester.pump();
  final review = find.text(l.boostReviewAction);
  // The label sits inside AppButton's >=48dp semantic tap target.
  expect(
    tester
        .getSize(
          find.ancestor(of: review, matching: find.byType(AppButton)).first,
        )
        .height,
    greaterThanOrEqualTo(AppSpace.minTapTarget),
  );
  await tester.tap(review);
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(
    find.text(l.boostPreviewTitle),
    180,
    scrollable: find.byType(Scrollable).first,
  );
  return l;
}

void main() {
  for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
    testWidgets(
      'review renders the authoritative split in ${locale.languageCode}',
      (tester) async {
        final l = await pumpReviewed(tester, locale);
        expect(find.text(l.boostPreviewTitle), findsWidgets);
        expect(find.text(l.boostSenderPays), findsOneWidget);
        expect(find.text(l.boostTravelerGets), findsOneWidget);
        expect(find.text(l.boostPlatformKeeps), findsOneWidget);
        expect(find.text(l.boostConfirmAction), findsOneWidget);
        expect(
          find.bySemanticsLabel(RegExp(RegExp.escape(l.boostPreviewTitle))),
          findsWidgets,
        );
      },
    );
  }

  testWidgets('Arabic review keeps the whole screen RTL', (tester) async {
    await pumpReviewed(tester, const Locale('ar'));
    expect(
      Directionality.of(tester.element(find.byType(BoostScreen))),
      TextDirection.rtl,
    );
  });

  testWidgets('sender can increase the default €5 amount before review', (
    tester,
  ) async {
    await pumpApp(
      tester,
      const BoostScreen(requestId: 42),
      container: containerFor(boostBackend(expectedAmountEurCents: 1234)),
      locale: const Locale('en'),
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(BoostScreen)));
    await tester.scrollUntilVisible(
      find.text('24 hours'),
      180,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('24 hours'));
    await tester.pump();
    await tester.enterText(find.byType(TextFormField), '12.34');
    await tester.tap(find.text(l.boostReviewAction));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text(l.boostPreviewTitle),
      180,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.textContaining('€12.34'), findsOneWidget);
  });

  testWidgets('review remains scrollable with large accessible text', (
    tester,
  ) async {
    await pumpReviewed(
      tester,
      const Locale('en'),
      device: DeviceProfile.largeText,
    );
    expect(tester.takeException(), isNull);
    expect(find.byType(Scrollable), findsWidgets);
  });
}
