/// L5B: trip progress, from the traveler's button to the sender's timeline.
///
/// A report is a statement. The tests assert what is sent (only `{kind}`),
/// what the screens offer (exactly what the server lists), and that no
/// failure is turned into a fake success or queued for later.
library;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/notification.dart';
import 'package:shiptrip/domain/progress.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/features/journeys/journey_detail_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

const _tall = DeviceProfile(name: 'tall (412x3000)', size: Size(412, 3000));

Map<String, dynamic> _report(
  int id,
  String kind, {
  bool canRetract = false,
  String reportedAt = '2026-12-02T10:05:00Z',
  String? retractedAt,
}) => {
  'id': id,
  'kind': kind,
  'source': 'traveler',
  'reported_at': reportedAt,
  'retracted_at': retractedAt,
  'can_retract': canRetract,
  'retractable_until': '2026-12-02T10:15:00Z',
};

Map<String, dynamic> _action(
  String kind, {
  bool now = true,
  String at = '2026-12-01T10:00:00Z',
}) => {'kind': kind, 'available_at': at, 'can_report_now': now};

Map<String, dynamic> _leg(
  int id,
  int position,
  String from,
  String to, {
  List<Map<String, dynamic>> reports = const [],
  List<Map<String, dynamic>> actions = const [],
}) => {
  'leg_id': id,
  'position': position,
  'mode': 'DRIVE',
  'origin_name': from,
  'destination_name': to,
  'depart_at': '2026-12-02T10:00:00Z',
  'arrive_at': '2026-12-02T13:00:00Z',
  'reports': reports,
  'next_actions': actions,
};

Map<String, dynamic> _progress(List<Map<String, dynamic>> legs) => {
  'journey_id': 9,
  'status': 'active',
  'legs': legs,
};

Map<String, dynamic> _journey() {
  final base = liveJourneyFixture(9);
  return {
    ...base,
    'legs': [
      {
        'id': 100,
        'position': 0,
        'mode': 'DRIVE',
        'origin_place': base['start_place'],
        'destination_place': base['destination_place'],
        'depart_at': '2026-12-02T10:00:00Z',
        'arrive_at': '2026-12-02T13:00:00Z',
        'capacity_kg': '10.00',
        'flight_number': '',
        'proof_required': false,
        'proof_state': 'not_required',
        'proofs': const <Object>[],
        'distance_meters': 1500000,
      },
    ],
  };
}

FakeBackend _journeyBackend(Map<String, dynamic> progress) => discoveryBackend()
  ..on('GET', '/api/journeys/9', FakeResponse(200, _journey()))
  ..on('GET', '/api/journeys/9/progress', FakeResponse(200, progress))
  ..on(
    'GET',
    '/api/matches/compatible-requests',
    FakeResponse(200, {'candidates': <Object>[]}),
  );

L _l(WidgetTester tester) => L.of(tester.element(find.byType(Scaffold).first));

Future<void> _pumpJourney(
  WidgetTester tester,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
  int? askLegId,
  ProgressKind? askKind,
}) => pumpDiscovery(
  tester,
  JourneyDetailScreen(journeyId: 9, askLegId: askLegId, askKind: askKind),
  backend,
  locale: locale,
  role: RoleContext.traveler,
  device: _tall,
);

void main() {
  // -------------------------------------------------------------------------
  group('the contract', () {
    test('a journey progress read keeps reports, actions and order', () {
      final progress = JourneyProgress.fromJson(
        _progress([
          _leg(2, 1, 'Marseille', 'Algiers', actions: [_action('departed')]),
          _leg(
            1,
            0,
            'Paris',
            'Marseille',
            reports: [
              _report(5, 'departed'),
              _report(6, 'arrived', retractedAt: '2026-12-02T11:00:00Z'),
            ],
            actions: [_action('arrived')],
          ),
        ]),
      );

      expect(progress.legs.map((l) => l.legId), [1, 2]);
      final first = progress.legs.first;
      expect(first.liveReports.map((r) => r.kind), [ProgressKind.departed]);
      expect(first.primaryAction?.kind, ProgressKind.arrived);
      expect(first.isFinished, isFalse);
    });

    test('an unknown kind is dropped, not guessed', () {
      expect(ProgressKind.parse('teleported'), isNull);
      final progress = JourneyProgress.fromJson(
        _progress([
          _leg(
            1,
            0,
            'A',
            'B',
            reports: [_report(5, 'teleported')],
            actions: [_action('teleported')],
          ),
        ]),
      );
      expect(progress.legs.single.reports, isEmpty);
      expect(progress.legs.single.nextActions, isEmpty);
    });

    test('a retraction removes the report from a deal timeline', () {
      Map<String, dynamic> event(String kind, int id, {String? at}) => {
        'kind': kind,
        'created_at': '2026-12-02T10:05:00Z',
        'payload': {
          'source': 'traveler_reported',
          'progress_id': id,
          'progress_kind': 'departed',
          'reported_at': ?at,
        },
      };

      final updates = DealProgressUpdate.fromTimeline([
        event('traveler_progress', 5, at: '2026-12-02T10:05:00Z'),
        event('traveler_progress', 6),
        event('traveler_progress_retracted', 5),
        {'kind': 'funded', 'payload': <String, dynamic>{}},
      ]);

      expect(updates.map((u) => u.progressId), [6]);
      // No `reported_at` in the payload: the event's own time stands in.
      expect(updates.single.reportedAt, isNotNull);
    });
  });

  // -------------------------------------------------------------------------
  group('where a reminder goes', () {
    const reminder = {
      'journey_id': '9',
      'leg_id': '100',
      'progress_kind': 'departed',
      'channel': 'journey.leg_reminder',
    };

    test('a push opens the journey with the question for that leg', () {
      final uri = Uri.parse(pushLocation(reminder)!);
      expect(uri.path, '/journeys/9');
      expect(uri.queryParameters, {'leg': '100', 'ask': 'departed'});
    });

    test('a push missing the leg still opens the journey', () {
      expect(
        pushLocation({'channel': 'journey.leg_reminder', 'journey_id': '9'}),
        '/journeys/9',
      );
      expect(
        pushLocation({'channel': 'journey.leg_reminder'}),
        '/notifications',
      );
    });

    test('the inbox row resolves to the same question', () {
      final row = AppNotification.fromJson({
        'id': 1,
        'channel': 'journey.leg_reminder',
        'payload': {'journey_id': 9, 'leg_id': 100, 'progress_kind': 'arrived'},
      });
      final destination = row.destination;
      expect(destination, isA<OpenProgressQuestion>());
      destination as OpenProgressQuestion;
      expect(
        (destination.journeyId, destination.legId, destination.kind),
        (9, 100, ProgressKind.arrived),
      );
    });

    test('a sender row opens the deal', () {
      final row = AppNotification.fromJson({
        'id': 2,
        'channel': 'deal.progress_reported',
        'payload': {'deal_id': 7, 'progress_kind': 'departed'},
      });
      expect(row.destination, isA<OpenDeal>());
    });

    test('both channels reach the live layer', () {
      final reminderResources = resourcesForLiveEvent('journey.leg_reminder', {
        'journey_id': 9,
        'leg_id': 100,
      });
      expect(
        reminderResources,
        containsAll([
          const LiveResource.journey(9),
          const LiveResource.progress(),
          const LiveResource.notifications(),
        ]),
      );
      expect(
        resourcesForLiveEvent('deal.progress_reported', {'deal_id': 7}),
        contains(const LiveResource.deal(7)),
      );
    });
  });

  // -------------------------------------------------------------------------
  group('the stepper on the journey', () {
    testWidgets('one button for the next step, and it sends only the kind', (
      tester,
    ) async {
      final backend =
          _journeyBackend(
            _progress([
              _leg(100, 0, 'Paris', 'Algiers', actions: [_action('departed')]),
            ]),
          )..handle(
            'POST',
            '/api/journeys/9/legs/100/progress',
            (_) => FakeResponse(201, {
              'id': 5,
              'leg_id': 100,
              'kind': 'departed',
              'source': 'traveler',
              'reported_at': '2026-12-02T10:05:00Z',
              'retracted_at': null,
            }),
          );
      await _pumpJourney(tester, backend);
      final l = _l(tester);

      expect(find.text(l.progressTitle), findsOneWidget);
      await tester.tap(find.text(l.progressActionDeparted));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('POST', '/api/journeys/9/legs/100/progress');
      expect(sent?.body, {'kind': 'departed'});
    });

    testWidgets('before the window opens the button is off and says when', (
      tester,
    ) async {
      final backend = _journeyBackend(
        _progress([
          _leg(
            100,
            0,
            'Paris',
            'Algiers',
            actions: [_action('departed', now: false)],
          ),
        ]),
      );
      await _pumpJourney(tester, backend);
      final l = _l(tester);

      await tester.tap(find.text(l.progressActionDeparted));
      await tester.pumpAndSettle();

      expect(backend.to('POST', '/api/journeys/9/legs/100/progress'), isEmpty);
      expect(find.textContaining('Dec'), findsWidgets);
    });

    testWidgets('a recent report can be undone, and a late one cannot', (
      tester,
    ) async {
      final backend =
          _journeyBackend(
            _progress([
              _leg(
                100,
                0,
                'Paris',
                'Algiers',
                reports: [_report(5, 'departed', canRetract: true)],
                actions: [_action('arrived')],
              ),
            ]),
          )..handle(
            'POST',
            '/api/journeys/9/progress/5/retract',
            (_) => const FakeResponse(200, {}),
          );
      await _pumpJourney(tester, backend);
      final l = _l(tester);

      await tester.tap(find.text(l.progressUndo));
      await tester.pumpAndSettle();
      expect(
        backend.to('POST', '/api/journeys/9/progress/5/retract'),
        hasLength(1),
      );
    });

    testWidgets('no undo once the server says the window has closed', (
      tester,
    ) async {
      final backend = _journeyBackend(
        _progress([
          _leg(
            100,
            0,
            'Paris',
            'Algiers',
            reports: [_report(5, 'departed')],
            actions: [_action('arrived')],
          ),
        ]),
      );
      await _pumpJourney(tester, backend);
      expect(find.text(_l(tester).progressUndo), findsNothing);
    });

    testWidgets('offline: nothing is queued and the traveler is told', (
      tester,
    ) async {
      final backend =
          _journeyBackend(
            _progress([
              _leg(100, 0, 'Paris', 'Algiers', actions: [_action('departed')]),
            ]),
          )..handle(
            'POST',
            '/api/journeys/9/legs/100/progress',
            (_) => throw DioException(
              requestOptions: RequestOptions(path: '/'),
              type: DioExceptionType.connectionError,
            ),
          );
      await _pumpJourney(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text(l.progressActionDeparted));
      await tester.pumpAndSettle();

      // The button is back, ready for another honest attempt.
      expect(find.text(l.progressActionDeparted), findsOneWidget);
      expect(find.text(l.progressNeedsNetwork), findsWidgets);
    });

    testWidgets('a refusal reads as an instruction, not a code', (
      tester,
    ) async {
      final backend =
          _journeyBackend(
            _progress([
              _leg(100, 0, 'Paris', 'Algiers', actions: [_action('departed')]),
            ]),
          )..on(
            'POST',
            '/api/journeys/9/legs/100/progress',
            const FakeResponse(409, {
              'code': 'progress_too_early',
              'detail': 'Too early.',
            }),
          );
      await _pumpJourney(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text(l.progressActionDeparted));
      await tester.pumpAndSettle();
      expect(find.text(l.progressErrorTooEarly), findsOneWidget);
    });

    testWidgets('renders in Arabic, right to left', (tester) async {
      final backend = _journeyBackend(
        _progress([
          _leg(100, 0, 'Paris', 'Algiers', actions: [_action('departed')]),
        ]),
      );
      await _pumpJourney(tester, backend, locale: const Locale('ar'));
      final l = _l(tester);
      expect(find.text(l.progressActionDeparted), findsOneWidget);
      expect(
        Directionality.of(tester.element(find.byType(Scaffold).first)),
        TextDirection.rtl,
      );
    });

    testWidgets('a draft has no stepper', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/journeys/9',
          FakeResponse(200, {..._journey(), 'status': 'draft'}),
        );
      await _pumpJourney(tester, backend);
      expect(find.text(_l(tester).progressTitle), findsNothing);
      expect(backend.to('GET', '/api/journeys/9/progress'), isEmpty);
    });
  });

  // -------------------------------------------------------------------------
  group('the reminder sheet', () {
    testWidgets('opens the question for that leg while it is still offered', (
      tester,
    ) async {
      final backend = _journeyBackend(
        _progress([
          _leg(100, 0, 'Paris', 'Algiers', actions: [_action('departed')]),
        ]),
      );
      await _pumpJourney(
        tester,
        backend,
        askLegId: 100,
        askKind: ProgressKind.departed,
      );
      final l = _l(tester);
      expect(find.text(l.progressQuestionDeparted('Paris')), findsOneWidget);
      expect(find.text(l.progressYesDeparted), findsOneWidget);
    });

    testWidgets('an answered reminder shows the stepper and no sheet', (
      tester,
    ) async {
      final backend = _journeyBackend(
        _progress([
          _leg(
            100,
            0,
            'Paris',
            'Algiers',
            reports: [_report(5, 'departed')],
            actions: [_action('arrived')],
          ),
        ]),
      );
      await _pumpJourney(
        tester,
        backend,
        askLegId: 100,
        askKind: ProgressKind.departed,
      );
      expect(
        find.text(_l(tester).progressQuestionDeparted('Paris')),
        findsNothing,
      );
    });

    testWidgets('"Yes" reports, "Not yet" only closes', (tester) async {
      final backend =
          _journeyBackend(
            _progress([
              _leg(100, 0, 'Paris', 'Algiers', actions: [_action('departed')]),
            ]),
          )..on(
            'POST',
            '/api/journeys/9/legs/100/progress',
            const FakeResponse(201, {
              'id': 5,
              'leg_id': 100,
              'kind': 'departed',
            }),
          );
      await _pumpJourney(
        tester,
        backend,
        askLegId: 100,
        askKind: ProgressKind.departed,
      );
      final l = _l(tester);

      await tester.tap(find.text(l.progressNotYet));
      await tester.pumpAndSettle();
      expect(backend.to('POST', '/api/journeys/9/legs/100/progress'), isEmpty);
      expect(find.text(l.progressQuestionDeparted('Paris')), findsNothing);
    });
  });

  // -------------------------------------------------------------------------
  group('Home', () {
    FakeBackend home({List<Map<String, dynamic>> questions = const []}) =>
        discoveryBackend()
          ..on(
            'GET',
            '/api/journeys',
            FakeResponse(200, [liveJourneyFixture(9)]),
          )
          ..on(
            'GET',
            '/api/journeys/progress/pending',
            FakeResponse(200, {'results': questions}),
          );

    const question = {
      'journey_id': 9,
      'leg_id': 100,
      'kind': 'departed',
      'place_name': 'Paris',
      'planned_at': '2026-12-02T10:00:00Z',
    };

    Future<void> pumpHome(
      WidgetTester tester,
      FakeBackend backend, {
      Locale locale = const Locale('en'),
    }) => pumpDiscovery(
      tester,
      const HomeScreen(),
      backend,
      role: RoleContext.traveler,
      locale: locale,
      device: _tall,
    );

    testWidgets('asks "Did you depart from Paris?"', (tester) async {
      await pumpHome(tester, home(questions: [question]));
      final l = _l(tester);
      expect(find.text(l.progressQuestionDeparted('Paris')), findsOneWidget);
      expect(find.text(l.progressYesDeparted), findsOneWidget);
      expect(find.text(l.progressNotYet), findsOneWidget);
    });

    testWidgets('"Yes, departed" reports it, and the question goes away', (
      tester,
    ) async {
      var answered = false;
      final backend = home(questions: [question])
        ..handle('POST', '/api/journeys/9/legs/100/progress', (_) {
          answered = true;
          return const FakeResponse(201, {
            'id': 5,
            'leg_id': 100,
            'kind': 'departed',
          });
        })
        ..handle(
          'GET',
          '/api/journeys/progress/pending',
          (_) => FakeResponse(200, {
            'results': answered ? <Object>[] : [question],
          }),
        );
      await pumpHome(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text(l.progressYesDeparted));
      await tester.pumpAndSettle();
      expect(
        backend.lastTo('POST', '/api/journeys/9/legs/100/progress')?.body,
        {'kind': 'departed'},
      );
      expect(find.text(l.progressQuestionDeparted('Paris')), findsNothing);
    });

    testWidgets('"Not yet" hides it for now and tells the server nothing', (
      tester,
    ) async {
      final backend = home(questions: [question]);
      await pumpHome(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text(l.progressNotYet));
      await tester.pumpAndSettle();
      expect(find.text(l.progressQuestionDeparted('Paris')), findsNothing);
      expect(backend.to('POST', '/api/journeys/9/legs/100/progress'), isEmpty);
    });

    testWidgets('no question, no row', (tester) async {
      await pumpHome(tester, home());
      expect(
        find.text(_l(tester).progressQuestionDeparted('Paris')),
        findsNothing,
      );
    });

    testWidgets('a sender with no live trip never asks for questions', (
      tester,
    ) async {
      final backend = discoveryBackend();
      await pumpDiscovery(tester, const HomeScreen(), backend, device: _tall);
      expect(backend.to('GET', '/api/journeys/progress/pending'), isEmpty);
    });

    testWidgets('a failed read leaves Home calm', (tester) async {
      final backend = home()
        ..on(
          'GET',
          '/api/journeys/progress/pending',
          const FakeResponse(500, {'detail': 'boom'}),
        );
      await pumpHome(tester, backend);
      expect(find.byType(HomeScreen), findsOneWidget);
    });

    testWidgets('renders in Arabic', (tester) async {
      await pumpHome(
        tester,
        home(questions: [question]),
        locale: const Locale('ar'),
      );
      final l = _l(tester);
      expect(find.text(l.progressQuestionDeparted('Paris')), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  group("the sender's deal", () {
    Map<String, dynamic> event(
      int id,
      String kind,
      int progressId,
      String progressKind,
    ) => {
      'id': id,
      'kind': kind,
      'actor_id': 99,
      'created_at': '2026-12-02T10:05:00Z',
      'payload': {
        'source': 'traveler_reported',
        'progress_id': progressId,
        'progress_kind': progressKind,
        'reported_at': '2026-12-02T10:05:00Z',
      },
    };

    Future<void> pumpDeal(
      WidgetTester tester,
      List<Map<String, dynamic>> timeline,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/deals/7',
          FakeResponse(200, {...dealFixture(), 'timeline': timeline}),
        );
      await pumpApp(
        tester,
        const DealScreen(dealId: 7),
        container: containerFor(backend),
        device: _tall,
      );
      await tester.pumpAndSettle();
    }

    testWidgets('shows the traveler\'s update, marked as theirs', (
      tester,
    ) async {
      await pumpDeal(tester, [event(1, 'traveler_progress', 5, 'departed')]);
      final l = L.of(tester.element(find.byType(DealScreen)));
      expect(find.text(l.dealProgressDeparted), findsOneWidget);
      expect(find.text(l.dealProgressReportedBy), findsOneWidget);
    });

    testWidgets('a retracted update is not shown', (tester) async {
      await pumpDeal(tester, [
        event(1, 'traveler_progress', 5, 'departed'),
        event(2, 'traveler_progress_retracted', 5, 'departed'),
      ]);
      final l = L.of(tester.element(find.byType(DealScreen)));
      expect(find.text(l.dealProgressDeparted), findsNothing);
    });

    testWidgets('no updates, no lines', (tester) async {
      await pumpDeal(tester, const []);
      final l = L.of(tester.element(find.byType(DealScreen)));
      expect(find.text(l.dealProgressReportedBy), findsNothing);
    });
  });
}
