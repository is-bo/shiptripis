/// N2: the bell names the ticket decision.
///
/// The server publishes `leg_proof.status_changed` with the journey, the mode,
/// the stored status and, for "ask for a new upload", an `outcome`. The row
/// says what was decided ("Flight ticket approved") from those fields alone,
/// and falls back to the generic label when they are missing or unknown.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/domain/notification.dart';
import 'package:shiptrip/features/notifications/notifications_screen.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

Map<String, dynamic> _row(int id, Map<String, dynamic> payload) => {
  'id': id,
  'channel': 'leg_proof.status_changed',
  'payload': payload,
  'read_at': null,
  'created_at': '2026-11-26T09:00:00Z',
};

Map<String, dynamic> _payload(String mode, String status, [String? outcome]) =>
    {
      'proof_id': 9,
      'journey_id': 11,
      'mode': mode,
      'status': status,
      'outcome': ?outcome,
    };

FakeBackend _inbox(List<Map<String, dynamic>> rows) => discoveryBackend()
  ..on(
    'GET',
    '/api/notifications',
    FakeResponse(200, {'count': rows.length, 'next': null, 'results': rows}),
  )
  ..handle(
    'POST',
    '/api/notifications/1/read',
    (_) => const FakeResponse(204, {}),
  );

void main() {
  group('the decision read from the payload', () {
    final cases =
        <String, (Map<String, dynamic>, TicketMode?, TicketDecision?)>{
          'approved flight': (
            _payload('FLIGHT', 'approved', 'approved'),
            TicketMode.flight,
            TicketDecision.approved,
          ),
          'rejected flight': (
            _payload('FLIGHT', 'rejected', 'rejected'),
            TicketMode.flight,
            TicketDecision.rejected,
          ),
          'new upload asked, stored as rejected': (
            _payload('FLIGHT', 'rejected', 'resubmission_requested'),
            TicketMode.flight,
            TicketDecision.resubmissionRequested,
          ),
          'approved ferry': (
            _payload('SEA', 'approved', 'approved'),
            TicketMode.ferry,
            TicketDecision.approved,
          ),
          'no outcome: the stored status decides': (
            _payload('FLIGHT', 'approved'),
            TicketMode.flight,
            TicketDecision.approved,
          ),
          'a drive has no ticket': (
            _payload('DRIVE', 'approved', 'approved'),
            null,
            TicketDecision.approved,
          ),
          'unknown outcome': (
            _payload('FLIGHT', 'approved', 'banana'),
            TicketMode.flight,
            null,
          ),
          'nothing but the journey': ({'journey_id': 11}, null, null),
        };

    cases.forEach((name, spec) {
      test(name, () {
        final n = AppNotification.fromJson(_row(1, spec.$1));
        expect(n.ticketMode, spec.$2);
        expect(n.ticketDecision, spec.$3);
      });
    });

    test('another channel never reads a ticket decision', () {
      final n = AppNotification.fromJson({
        'id': 1,
        'channel': 'kyc.status_changed',
        'payload': _payload('FLIGHT', 'approved'),
      });
      expect(n.ticketMode, isNull);
      expect(n.ticketDecision, isNull);
    });
  });

  group('the bell row', () {
    final english = <(Map<String, dynamic>, String)>[
      (_payload('FLIGHT', 'approved', 'approved'), 'Flight ticket approved'),
      (
        _payload('FLIGHT', 'rejected', 'rejected'),
        'Flight ticket needs attention',
      ),
      (
        _payload('FLIGHT', 'rejected', 'resubmission_requested'),
        'We need a new flight ticket',
      ),
      (_payload('SEA', 'approved', 'approved'), 'Ferry ticket approved'),
      (_payload('SEA', 'rejected', 'rejected'), 'Ferry ticket needs attention'),
      (
        _payload('SEA', 'rejected', 'resubmission_requested'),
        'We need a new ferry ticket',
      ),
    ];

    for (final (payload, title) in english) {
      testWidgets('says "$title"', (tester) async {
        await pumpDiscovery(
          tester,
          const NotificationsScreen(),
          _inbox([_row(1, payload)]),
          device: DeviceProfile.smallAndroid,
        );

        expect(find.text(title), findsOneWidget);
        expect(find.text('Verification update'), findsNothing);
      });
    }

    testWidgets('keeps the generic label when the fields are unknown', (
      tester,
    ) async {
      await pumpDiscovery(
        tester,
        const NotificationsScreen(),
        _inbox([
          _row(1, {'journey_id': 11}),
          _row(2, _payload('DRIVE', 'approved')),
          _row(3, _payload('FLIGHT', 'approved', 'banana')),
        ]),
      );

      expect(find.text('Verification update'), findsNWidgets(3));
    });

    testWidgets('shows no reason, evidence or document identifier', (
      tester,
    ) async {
      await pumpDiscovery(
        tester,
        const NotificationsScreen(),
        _inbox([
          _row(1, {
            ..._payload('FLIGHT', 'rejected', 'rejected'),
            'reason': 'Passport number P1234567 is visible',
            'document_id': 'doc-77',
          }),
        ]),
      );

      expect(find.textContaining('P1234567'), findsNothing);
      expect(find.textContaining('doc-77'), findsNothing);
      expect(find.textContaining('rejected'), findsNothing);
    });

    testWidgets('a tap still opens the journey', (tester) async {
      await pumpDiscovery(
        tester,
        const NotificationsScreen(),
        _inbox([_row(1, _payload('FLIGHT', 'approved', 'approved'))]),
      );

      await tester.tap(find.text('Flight ticket approved'));
      await tester.pumpAndSettle();

      expect(find.textContaining('at journey-detail'), findsOneWidget);
    });

    for (final (locale, title, other) in [
      ('fr', 'Billet d’avion approuvé', 'Mise à jour de la vérification'),
      ('ar', 'تمت الموافقة على تذكرة الطيران', 'تحديث التحقق'),
    ]) {
      testWidgets('is translated into $locale', (tester) async {
        await pumpDiscovery(
          tester,
          const NotificationsScreen(),
          _inbox([_row(1, _payload('FLIGHT', 'approved', 'approved'))]),
          locale: Locale(locale),
          device: DeviceProfile.smallAndroid,
        );

        expect(find.text(title), findsOneWidget);
        expect(find.text(other), findsNothing);
        if (locale == 'ar') {
          expect(
            Directionality.of(tester.element(find.text(title))),
            TextDirection.rtl,
          );
        }
        expect(tester.takeException(), isNull);
      });
    }
  });
}
