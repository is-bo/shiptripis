import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/features/deals/rate_screen.dart';
import 'package:shiptrip/features/disputes/dispute_open_screen.dart';
import 'package:shiptrip/features/journeys/journey_create_screen.dart';
import 'package:shiptrip/features/journeys/journey_route_draft.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

Future<void> _pumpUntil(WidgetTester tester, bool Function() done) async {
  for (var i = 0; i < 20 && !done(); i++) {
    await tester.pump(const Duration(milliseconds: 10));
  }
}

CanonicalPlace _place(int id, String name) => CanonicalPlace.fromJson({
  'id': id,
  'name': name,
  'display_label': name,
  'place_type': 'locality',
  'country_code': 'DZ',
  'matching_locality_id': id,
  'matching_locality_name': name,
});

Map<String, dynamic> _deal({bool rating = false}) => {
  'id': 7,
  'sender_id': 42,
  'traveler_id': 99,
  'status': rating ? 'completed' : 'picked_up',
  'is_legacy': false,
  'leg_allocations': <Object>[],
  'available_actions': rating ? <String>[] : ['open_dispute'],
  'pickup_confirmed_at': '2026-09-01T08:00:00Z',
  if (rating)
    'ratings': {
      'state': 'available',
      'deal_id': 7,
      'window_open': true,
      'can_rate': true,
      'submitted': false,
      'counterparty_submitted': false,
      'both_sides_submitted': false,
      'allowed_tags': <String>[],
      'ratings': <Object>[],
    },
};

void main() {
  testWidgets(
    'rapid Journey Save taps create one draft and failure allows retry',
    (tester) async {
      final now = DateTime.utc(2100, 1, 1);
      final draft = JourneyRouteDraft()
        ..setOrigin(_place(1, 'Jijel'))
        ..setDestination(_place(2, 'Algiers'));
      draft.setSegmentDeparture(0, now.add(const Duration(days: 2)));
      draft.setSegmentArrival(0, now.add(const Duration(days: 2, hours: 2)));
      draft.segments.first.capacity.text = '10.00';
      final release = Completer<void>();
      var calls = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/journeys', (_) async {
          calls++;
          if (calls == 1) await release.future;
          return const FakeResponse(503, {'code': 'journey_unavailable'});
        });
      await pumpApp(
        tester,
        JourneyCreateScreen(debugDraft: draft, debugNow: () => now),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(JourneyCreateScreen)));
      final save = find.text(l.journeySaveDraft);
      final action = tester
          .widget<FilledButton>(
            find.ancestor(of: save, matching: find.byType(FilledButton)),
          )
          .onPressed!;
      action();
      action();
      await _pumpUntil(tester, () => calls == 1);
      expect(calls, 1);
      release.complete();
      await tester.pumpAndSettle();
      tester
          .widget<FilledButton>(
            find.ancestor(of: save, matching: find.byType(FilledButton)),
          )
          .onPressed!();
      await tester.pumpAndSettle();
      expect(calls, 2);
    },
  );

  testWidgets(
    'rapid Dispute Submit taps open one dispute and failure allows retry',
    (tester) async {
      final release = Completer<void>();
      var calls = 0;
      final backend = FakeBackend()
        ..on('GET', '/api/deals/7', FakeResponse(200, _deal()))
        ..handle('POST', '/api/deals/7/disputes', (_) async {
          calls++;
          if (calls == 1) await release.future;
          return const FakeResponse(503, {'code': 'dispute_unavailable'});
        });
      await pumpApp(
        tester,
        const DisputeOpenScreen(dealId: 7),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(DisputeOpenScreen)));
      await tester.tap(find.text(l.actionSelect));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.disputeCategoryNotDelivered));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byType(TextFormField),
        'The parcel never arrived',
      );
      final submit = find.text(l.disputeSubmit);
      final action = tester
          .widget<FilledButton>(
            find.ancestor(of: submit, matching: find.byType(FilledButton)),
          )
          .onPressed!;
      action();
      action();
      await _pumpUntil(tester, () => calls == 1);
      expect(calls, 1);
      release.complete();
      await tester.pumpAndSettle();
      tester
          .widget<FilledButton>(
            find.ancestor(of: submit, matching: find.byType(FilledButton)),
          )
          .onPressed!();
      await tester.pumpAndSettle();
      expect(calls, 2);
    },
  );

  testWidgets(
    'rapid Rating Submit taps write one rating and failure allows retry',
    (tester) async {
      final release = Completer<void>();
      var calls = 0;
      final backend = FakeBackend()
        ..on('GET', '/api/deals/7', FakeResponse(200, _deal(rating: true)))
        ..handle('POST', '/api/deals/7/ratings', (_) async {
          calls++;
          if (calls == 1) await release.future;
          return const FakeResponse(503, {'code': 'rating_unavailable'});
        });
      await pumpApp(
        tester,
        const RateScreen(dealId: 7),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(RateScreen)));
      await tester.tap(find.byIcon(Icons.star_outline_rounded).first);
      await tester.pump();
      final submit = find.text(l.ratingSubmit);
      final action = tester
          .widget<FilledButton>(
            find.ancestor(of: submit, matching: find.byType(FilledButton)),
          )
          .onPressed!;
      action();
      action();
      await _pumpUntil(tester, () => calls == 1);
      expect(calls, 1);
      release.complete();
      await tester.pumpAndSettle();
      tester
          .widget<FilledButton>(
            find.ancestor(of: submit, matching: find.byType(FilledButton)),
          )
          .onPressed!();
      await tester.pumpAndSettle();
      expect(calls, 2);
    },
  );
}
