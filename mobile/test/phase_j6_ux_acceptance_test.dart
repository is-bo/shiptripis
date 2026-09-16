/// Phase J6 — the defects the final UX pass found, held down.
///
/// Every test here corresponds to something that shipped wrong and was visible
/// on a device. They are grouped by what was actually broken rather than by
/// screen, because several of them are one mistake made in several places.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/design/components/route.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/domain/find_travelers.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/features/common/payment_success_view.dart';
import 'package:shiptrip/features/requests/boost_screen.dart';
import 'package:shiptrip/features/requests/deposit_screen.dart';
import 'package:shiptrip/features/requests/discovery_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'phase_j5_find_travelers_test.dart' as j5;
import 'support/fake_api.dart';
import 'support/harness.dart';

// ---------------------------------------------------------------------------
// Directional icons
// ---------------------------------------------------------------------------

/// Material's directional glyphs carry `matchTextDirection`, so Flutter already
/// mirrors them under an RTL `Directionality`. Ten call sites also flipped the
/// constant by hand, which mirrored a second time: in Arabic every route arrow
/// and every row chevron pointed back the way it came. `Paris → Algiers`
/// rendered as `Algiers → Paris` on the Sender's main discovery screen.
void main() {
  group('a directional glyph is mirrored once, not twice', () {
    testWidgets('the inline route arrow runs with Arabic, not against it', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Directionality(
          textDirection: TextDirection.rtl,
          child: Scaffold(
            body: InlineRoute(
              stops: [
                InlineRouteStop(label: 'Paris'),
                InlineRouteStop(label: 'Algiers'),
              ],
            ),
          ),
        ),
        locale: const Locale('ar'),
      );

      expect(find.byIcon(Icons.arrow_back_rounded), findsNothing);
      final arrow = tester.widget<Icon>(
        find.byIcon(Icons.arrow_forward_rounded),
      );
      expect(arrow.icon!.matchTextDirection, isTrue);
      expect(
        Directionality.of(
          tester.element(find.byIcon(Icons.arrow_forward_rounded)),
        ),
        TextDirection.rtl,
      );
    });

    test('no screen hand-flips a glyph the framework already mirrors', () {
      // A regression guard rather than a render check: the bug was cheap to
      // reintroduce one screen at a time, and it is invisible unless somebody
      // reads Arabic.
      final offenders = <String>[];
      for (final file in dartSourcesUnder('lib')) {
        final source = file.readAsStringSync().replaceAll(RegExp(r'\s+'), ' ');
        final flips = RegExp(
          r'isRtl\s*\?\s*Icons\.(chevron_left_rounded|arrow_back_rounded)',
        );
        if (flips.hasMatch(source)) offenders.add(file.path);
      }
      expect(offenders, isEmpty);
    });
  });

  // -------------------------------------------------------------------------
  // Boost economics
  // -------------------------------------------------------------------------

  group('the Boost screen names Boost money as Boost money', () {
    testWidgets('the breakdown is not a balance and not the whole reward', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const BoostScreen(requestId: 42),
        container: containerFor(j6BoostBackend()),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(BoostScreen)));

      expect(find.text(l.boostBreakdownTitle), findsOneWidget);
      expect(find.text(l.boostTravelerBonusLabel), findsOneWidget);
      expect(find.text(l.boostYourCostLabel), findsOneWidget);

      // The card used to be headed "Remaining balance at delivery", to label
      // the Boost alone "Traveler receives", to call Boost plus its fee the
      // "Total sender cost", and to close with the deposit screen's paid-in-full
      // notice. Four sentences about other money, on the Boost screen.
      expect(find.text(l.depositRemainingBalance), findsNothing);
      expect(find.text(l.pricingTravelerReceives), findsNothing);
      expect(find.text(l.pricingTotalSenderCost), findsNothing);
      expect(find.text(l.depositFullDepositNotice), findsNothing);
    });

    testWidgets('base reward plus Boost is stated, not left to be worked out', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const BoostScreen(requestId: 42),
        container: containerFor(j6BoostBackend()),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(BoostScreen)));
      expect(find.text(l.boostAddsOnTop), findsOneWidget);
    });

    testWidgets('a saved Boost takes the split the server computed', (
      tester,
    ) async {
      // 2500 bps was hard-coded in the client as a fallback rate. Here the
      // server charges 4000 and the screen has to say EUR 4.00, not EUR 2.50.
      await pumpApp(
        tester,
        const BoostScreen(requestId: 42),
        container: containerFor(
          j6BoostBackend(
            boostCents: 1000,
            platformFeeCents: 400,
            senderCostCents: 1400,
            commissionBps: 4000,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('€4.00'), findsOneWidget);
      expect(find.text('€14.00'), findsOneWidget);
      expect(find.text('€2.50'), findsNothing);
    });

    testWidgets('history reads as sentences, not as wire codes', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const BoostScreen(requestId: 42),
        container: containerFor(
          j6BoostBackend(
            history: [
              {
                'reason': 'sender_increased',
                'previous_eur_cents': 0,
                'amount_eur_cents': 500,
                'created_at': '2026-09-14T10:00:00Z',
              },
              {
                'reason': 'a_code_from_a_later_phase',
                'previous_eur_cents': 500,
                'amount_eur_cents': 500,
                'created_at': '2026-09-15T10:00:00Z',
              },
            ],
          ),
        ),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(BoostScreen)));

      await tester.scrollUntilVisible(
        find.text(l.boostHistoryReasonOther),
        220,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('sender_increased'), findsNothing);
      expect(find.text('a_code_from_a_later_phase'), findsNothing);
      expect(find.text(l.boostHistoryReasonSenderIncreased), findsOneWidget);
      expect(find.text(l.boostHistoryReasonOther), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  // The receipt
  // -------------------------------------------------------------------------

  group('the payment receipt is translated and points the right way', () {
    testWidgets('the payer is a translated word, not a wire value', (
      tester,
    ) async {
      for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
        await pumpApp(
          tester,
          Scaffold(
            body: PaymentSuccessView(
              order: PaymentOrder.fromJson(j6SettledOrder()),
              originPlaceName: 'Paris',
              destinationPlaceName: 'Algiers',
            ),
          ),
          locale: locale,
        );
        await tester.pumpAndSettle();

        // 'Guest' and 'Self' were hard-coded English and reached every locale.
        expect(find.text('Guest'), findsNothing);
        expect(find.text('Self'), findsNothing);
      }
    });

    testWidgets('the route turns round in Arabic', (tester) async {
      await pumpApp(
        tester,
        Scaffold(
          body: PaymentSuccessView(
            order: PaymentOrder.fromJson(j6SettledOrder()),
            originPlaceName: 'Paris',
            destinationPlaceName: 'Algiers',
          ),
        ),
        locale: const Locale('ar'),
      );
      await tester.pumpAndSettle();

      expect(find.text('Algiers ← Paris'), findsOneWidget);
      expect(find.text('Paris → Algiers'), findsNothing);
    });
  });

  // -------------------------------------------------------------------------
  // Find Travelers
  // -------------------------------------------------------------------------

  group('Find Travelers says what it means', () {
    Future<void> pumpDiscovery(
      WidgetTester tester, {
      Map<String, dynamic>? page,
    }) async {
      final repo = j5.FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async =>
                FindTravelersPage.fromJson(page ?? j5.pageFixture()),
      );
      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: ProviderContainer(
          overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('the result count carries a noun', (tester) async {
      await pumpDiscovery(
        tester,
        page: j5.pageFixture(
          total: 2,
          candidates: [
            j5.candidateFixture(journeyId: 101),
            j5.candidateFixture(journeyId: 102, travelerName: 'Amina'),
          ],
        ),
      );
      // Was a bare "2" hanging over the list.
      expect(find.text('2'), findsNothing);
      expect(find.text('2 travelers'), findsOneWidget);
    });

    testWidgets('an unknown route fit is not renamed "Compatible route"', (
      tester,
    ) async {
      await pumpDiscovery(
        tester,
        page: j5.pageFixture(
          candidates: [j5.candidateFixture(routeFit: 'a_later_classification')],
        ),
      );
      final l = L.of(tester.element(find.byType(DiscoveryScreen)));
      expect(find.text(l.findTravelersRouteFitCompatible), findsNothing);
      // The rest of the card still renders.
      expect(find.text('Karim'), findsOneWidget);
    });

    testWidgets('a nameless Traveler is not called "View trip"', (
      tester,
    ) async {
      await pumpDiscovery(
        tester,
        page: j5.pageFixture(
          candidates: [j5.candidateFixture(travelerName: '')],
        ),
      );
      final l = L.of(tester.element(find.byType(DiscoveryScreen)));
      // Once for the action, never as somebody's name.
      expect(find.text(l.findTravelersViewTrip), findsOneWidget);
    });

    testWidgets('an unreadable ineligible reason does not claim "closed"', (
      tester,
    ) async {
      await pumpDiscovery(
        tester,
        page: j5.pageFixture(
          state: 'request_ineligible',
          reason: 'a_reason_from_a_later_phase',
          candidates: [],
          total: 0,
        ),
      );
      final l = L.of(tester.element(find.byType(DiscoveryScreen)));
      expect(find.text(l.findTravelersIneligibleClosed), findsNothing);
      expect(find.text(l.findTravelersIneligibleUnknown), findsOneWidget);
    });

    testWidgets('the trip sheet separates checks from route reasons', (
      tester,
    ) async {
      await pumpDiscovery(tester);
      await tester.tap(find.text('View trip').first);
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(DiscoveryScreen)));

      expect(find.text(l.findTravelersWhyThisFits), findsOneWidget);
      expect(find.text(l.findTravelersTrustTitle), findsOneWidget);
      expect(find.text(l.findTravelersIdentityVerified), findsOneWidget);

      // "Identity verified" used to sit in the ticked list under "Why this
      // trip fits", where it read as a reason the route suited the parcel.
      final checksY = tester
          .getTopLeft(find.text(l.findTravelersTrustTitle))
          .dy;
      final verifiedY = tester
          .getTopLeft(find.text(l.findTravelersIdentityVerified))
          .dy;
      expect(verifiedY, greaterThan(checksY));
    });

    testWidgets('the trip sheet keeps the schedule the card showed', (
      tester,
    ) async {
      await pumpDiscovery(tester);
      await tester.tap(find.text('View trip').first);
      await tester.pumpAndSettle();

      // The sheet used to render no departure at all when the stops carried no
      // per-stop times, so opening a row lost information.
      expect(find.textContaining('Departs'), findsOneWidget);
      expect(find.textContaining('Arrives Sep'), findsOneWidget);
    });

    testWidgets('proposing closes the sheet it was launched from', (
      tester,
    ) async {
      await pumpDiscovery(tester);
      await tester.tap(find.text('View trip').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Make an offer').first);
      await tester.pumpAndSettle();

      final l = L.of(tester.element(find.byType(DiscoveryScreen)));
      expect(find.text(l.offerSend), findsOneWidget);
      // The trip sheet used to stay mounted underneath, so returning from the
      // negotiation screen landed on a live "Make an offer" for a Traveler the
      // sender had already proposed to.
      expect(find.text(l.findTravelersWhyThisFits), findsNothing);
    });

    testWidgets('the offer opens on the sender\'s own reward, not a raise', (
      tester,
    ) async {
      await pumpDiscovery(tester);
      await tester.tap(find.text('View trip').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Make an offer').first);
      await tester.pumpAndSettle();

      final l = L.of(tester.element(find.byType(DiscoveryScreen)));
      // The request offers EUR 30.00 and the recommendation is EUR 35.00. The
      // sheet used to open on the recommendation, so a sender who tapped Send
      // offer raised their own reward by five euro without being told.
      expect(find.widgetWithText(TextField, '30.00'), findsOneWidget);
      expect(find.text(l.offerBaseRewardLabel), findsWidgets);
      expect(find.text(l.offerRewardLabel), findsNothing);
    });
  });

  // -------------------------------------------------------------------------
  // Deposit bounds
  // -------------------------------------------------------------------------

  testWidgets('a custom deposit under the floor is refused at the field', (
    tester,
  ) async {
    await pumpApp(
      tester,
      const DepositScreen(requestId: 42),
      container: containerFor(j6DepositBackend()),
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DepositScreen)));

    await tester.ensureVisible(find.text(l.depositPresetCustom));
    await tester.pumpAndSettle();
    await tester.tap(find.text(l.depositPresetCustom));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.byType(TextField).first);
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, '1.00');
    await tester.pumpAndSettle();

    // Was accepted locally and refused by the server a round trip later, as a
    // failure snackbar with no connection to the field that caused it.
    expect(
      find.text(
        l.depositBelowMinimum(Money.eurCents(300).format(const Locale('en'))),
      ),
      findsOneWidget,
    );
  });
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

Iterable<File> dartSourcesUnder(String directory) sync* {
  final root = Directory(directory);
  for (final entity in root.listSync(recursive: true)) {
    if (entity is File &&
        entity.path.endsWith('.dart') &&
        !entity.path.contains('l10n')) {
      yield entity;
    }
  }
}

FakeBackend j6BoostBackend({
  int boostCents = 500,
  int platformFeeCents = 125,
  int senderCostCents = 625,
  int commissionBps = 2500,
  bool canEdit = true,
  List<Object>? history,
}) => FakeBackend()
  ..on(
    'GET',
    '/api/parcels/42/boost',
    FakeResponse(200, {
      'delivery_request_id': 42,
      'request_status': 'open',
      'is_owner': true,
      'ranking_boost_active': boostCents > 0,
      'ranking_boost_weight': 1,
      'affects_compatibility': false,
      'active_count': boostCents > 0 ? 1 : 0,
      'occupied_slots': 0,
      'purchases': <Object>[],
      'boost_eur_cents': boostCents,
      'can_edit': canEdit,
      'economics': {
        'economics_version': 'j2',
        'currency': 'EUR',
        'boost_eur_cents': boostCents,
        'boost_commission_rate_bps': commissionBps,
        'boost_traveler_bonus_eur_cents': boostCents,
        'boost_platform_fee_eur_cents': platformFeeCents,
        'boost_sender_cost_eur_cents': senderCostCents,
        'rounding_rule': 'ceil',
      },
      'policy': {
        'currency': 'EUR',
        'enabled': true,
        'minimum_boost_eur_cents': 500,
        'maximum_boost_eur_cents': 10000,
        'boost_commission_rate_bps': commissionBps,
        'settings_version': 3,
        'affects_compatibility': false,
        'has_expiry': false,
      },
      'history': history ?? <Object>[],
    }),
  );

FakeBackend j6DepositBackend() => FakeBackend()
  ..on(
    'GET',
    '/api/parcels/42/posting-deposit',
    const FakeResponse(200, {
      'timing_mode': 'posting_deposit',
      'deposit_required': true,
      'request_status': 'awaiting_deposit',
      'quote': {
        'amount_eur_cents': 500,
        'currency': 'EUR',
        'percent_bps': 1000,
        'min_eur_cents': 300,
        'max_eur_cents': 700,
        'estimated_sender_total_eur_cents': 5000,
        'clamped': '',
      },
    }),
  );

Map<String, dynamic> j6SettledOrder() => {
  'public_reference': 'ord_j6demo01',
  'status': 'paid',
  'purpose': 'posting_deposit',
  'currency': 'EUR',
  'amount_eur_cents': 500,
  'paid_eur_cents': 500,
  'outstanding_eur_cents': 0,
  'paid_at': '2026-09-16T09:00:00Z',
};
