/// L9B: problem reports, the no-show action and route changes, on the app.
///
/// What the tests hold to: the screens offer exactly what the server says
/// (`can_report_no_show`, `reportable_kinds`, `can_answer`, `informed`,
/// `actions`); a report sends only `{kind, note}`; a decline never cancels;
/// nothing is turned into a fake success; and the new channels reach the right
/// screen.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/notification.dart';
import 'package:shiptrip/domain/problems.dart';
import 'package:shiptrip/domain/schedule_change.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/deals/schedule_change_answer_screen.dart';
import 'package:shiptrip/features/journeys/change_times_screen.dart';
import 'package:shiptrip/features/journeys/journey_detail_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

const _tall = DeviceProfile(name: 'tall (412x3000)', size: Size(412, 3000));

Map<String, dynamic> _problem(
  int id,
  String kind, {
  String status = 'open',
  bool mine = true,
  String note = '',
}) => {
  'id': id,
  'kind': kind,
  'status': status,
  'reporter_role': 'traveler',
  'reported_by_me': mine,
  'note': note,
  'escalated': status == 'escalated',
  'created_at': '2026-12-02T10:30:00Z',
  'acknowledged_at': null,
  'closed_at': null,
};

Map<String, dynamic> _problems({
  String role = 'traveler',
  bool canNoShow = false,
  String noShowReason = 'pickup_time_not_reached',
  List<String> kinds = const [],
  List<Map<String, dynamic>> results = const [],
}) => {
  'deal_id': 7,
  'tracking_number': 'WSL-3NZ5FHHQ',
  'viewer_role': role,
  'no_show_kind': role == 'sender' ? 'traveler_no_show' : 'sender_unavailable',
  'can_report_no_show': canNoShow,
  'no_show_reason': canNoShow ? '' : noShowReason,
  'no_show_available_at': '2026-12-02T10:00:00Z',
  'reportable_kinds': [
    if (canNoShow) role == 'sender' ? 'traveler_no_show' : 'sender_unavailable',
    ...kinds,
  ],
  'results': results,
};

Map<String, dynamic> _legChange(int id, {bool changed = true}) => {
  'leg_id': id,
  'position': 0,
  'mode': 'DRIVE',
  'origin_name': 'Marseille',
  'destination_name': 'Algiers',
  'depart_at_before': '2026-12-02T10:00:00Z',
  'arrive_at_before': '2026-12-02T13:00:00Z',
  'depart_at_after': changed ? '2026-12-02T14:00:00Z' : '2026-12-02T10:00:00Z',
  'arrive_at_after': changed ? '2026-12-02T17:00:00Z' : '2026-12-02T13:00:00Z',
  'changed': changed,
};

Map<String, dynamic> _senderChange({
  String status = 'pending_senders',
  String consent = 'pending',
  bool canAnswer = true,
  bool informed = false,
  List<String> actions = const [],
  List<String> reasons = const ['shift'],
}) => {
  'deal_id': 7,
  'tracking_number': 'WSL-3NZ5FHHQ',
  'change': {
    'id': 3,
    'status': status,
    'reason': 'The airline moved my flight.',
    'created_at': '2026-12-01T09:00:00Z',
    'applied_at': null,
    'withdrawn_at': null,
    'material': !informed,
    'informed': informed,
    'reasons': reasons,
    'arrival_before': '2026-12-02T13:00:00Z',
    'arrival_after': '2026-12-02T17:00:00Z',
    'pickup_before': '2026-12-02T10:00:00Z',
    'pickup_after': '2026-12-02T14:00:00Z',
    'deadline_at': '2026-12-02T20:00:00Z',
    'consent_state': consent,
    'can_answer': canAnswer,
    'actions': actions,
    'legs': [_legChange(100)],
  },
};

Map<String, dynamic> _quote({String causedBy = 'traveler'}) => {
  'deal_id': 7,
  'actor_role': 'sender',
  'caused_by': causedBy,
  'allowed': true,
  'refusal_code': '',
  'collected_eur_cents': 4000,
  'sender_refund_eur_cents': 4000,
  'traveler_compensation_eur_cents': 0,
  'platform_fee_eur_cents': 0,
  'is_late': false,
  'cutoff_at': null,
  'agreed_pickup_at': '2026-12-02T10:00:00Z',
};

FakeBackend _dealBackend({
  bool traveler = false,
  Map<String, dynamic>? problems,
  Map<String, dynamic>? change,
}) {
  final backend = discoveryBackend()
    ..on('GET', '/api/me', FakeResponse(200, {...meFixture(), 'id': 99}))
    ..on(
      'GET',
      '/api/deals/7',
      FakeResponse(200, {...dealFixture(), 'match_id': 5}),
    )
    ..on(
      'GET',
      '/api/deals/7/problems',
      FakeResponse(
        200,
        problems ?? _problems(role: traveler ? 'traveler' : 'sender'),
      ),
    );
  if (!traveler) {
    backend
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on(
        'GET',
        '/api/deals/7/schedule-change',
        FakeResponse(
          200,
          change ?? {'deal_id': 7, 'tracking_number': null, 'change': null},
        ),
      );
  }
  return backend;
}

Future<void> _pumpDeal(
  WidgetTester tester,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
}) => pumpDiscovery(
  tester,
  const DealScreen(dealId: 7),
  backend,
  locale: locale,
  device: _tall,
  extraRoutes: [marker('deal-schedule-change', '/deals/:id/schedule-change')],
);

L _l(WidgetTester tester) => L.of(tester.element(find.byType(Scaffold).first));

void main() {
  // -------------------------------------------------------------------------
  group('the contract', () {
    test(
      'a problems read keeps the server answers and skips unknown kinds',
      () {
        final problems = DealProblems.fromJson(
          _problems(
            role: 'sender',
            canNoShow: true,
            kinds: ['parcel_damaged', 'a_kind_from_the_future'],
            results: [
              _problem(1, 'traveler_no_show', mine: true),
              _problem(2, 'a_kind_from_the_future'),
              _problem(
                3,
                'sender_unavailable',
                mine: false,
                status: 'escalated',
              ),
            ],
          ),
        );
        expect(problems.isSender, isTrue);
        expect(problems.noShowKind, ProblemKind.travelerNoShow);
        expect(problems.canReportNoShow, isTrue);
        expect(problems.reportableKinds, [
          ProblemKind.travelerNoShow,
          ProblemKind.parcelDamaged,
        ]);
        expect(problems.reports.map((r) => r.id), [1, 3]);
        expect(problems.myNoShowReport?.id, 1);
        expect(problems.noShowAgainstMe?.id, 3);
      },
    );

    test('a closed report is neither mine nor against me', () {
      final problems = DealProblems.fromJson(
        _problems(
          results: [_problem(1, 'sender_unavailable', status: 'closed')],
        ),
      );
      expect(problems.myNoShowReport, isNull);
      expect(problems.noShowAgainstMe, isNull);
    });

    test('a sender change keeps the server flags as given', () {
      final change = SenderScheduleChange.maybe(
        7,
        _senderChange(consent: 'declined', informed: false)['change'],
      )!;
      expect(change.declinedAndWaiting, isTrue);
      expect(change.canAnswer, isTrue);
      expect(change.reasons, [ChangeReason.shift]);
      expect(change.legs.single.changed, isTrue);
    });

    test('a preview splits who must agree from who is told', () {
      final preview = SchedulePreview.fromJson({
        'legs': [_legChange(100)],
        'parcels': [
          {'deal_id': 1, 'material': true, 'informed': false, 'reasons': []},
          {'deal_id': 2, 'material': false, 'informed': true, 'reasons': []},
        ],
        'applies_at_once': false,
        'notices': [
          {'code': 'ticket_recheck', 'text': 'Your ticket will be checked.'},
          {'code': 'empty', 'text': ' '},
        ],
      });
      expect(preview.mustAgree.map((p) => p.dealId), [1]);
      expect(preview.onlyTold.map((p) => p.dealId), [2]);
      expect(preview.notices.single.text, 'Your ticket will be checked.');
    });

    test('the new channels refresh the right things', () {
      final proposed = resourcesForLiveEvent(
        'journey.schedule_change_proposed',
        {'journey_id': 9, 'deal_id': 7},
      );
      expect(proposed, contains(LiveResource.deal(7)));
      expect(proposed, contains(LiveResource.journey(9)));
      final traveler = resourcesForLiveEvent(
        'journey.schedule_change_answered',
        {'journey_id': 9},
      );
      expect(traveler, contains(LiveResource.journey(9)));
      expect(
        resourcesForLiveEvent('deal.problem_reported', {'deal_id': 7}),
        contains(LiveResource.deal(7)),
      );
    });

    test(
      'a push opens the answer for a sender and the journey for a traveler',
      () {
        expect(
          pushLocation({
            'channel': 'journey.schedule_change_proposed',
            'deal_id': '7',
            'journey_id': '9',
          }),
          '/deals/7/schedule-change',
        );
        expect(
          pushLocation({
            'channel': 'journey.schedule_change_applied',
            'deal_id': '7',
            'journey_id': '9',
          }),
          '/deals/7',
        );
        expect(
          pushLocation({
            'channel': 'journey.schedule_change_answered',
            'journey_id': '9',
          }),
          '/journeys/9',
        );
        expect(
          pushLocation({'channel': 'deal.problem_reported', 'deal_id': '7'}),
          '/deals/7',
        );
      },
    );

    test('inbox rows open the same places', () {
      AppNotification row(String channel, Map<String, dynamic> payload) =>
          AppNotification.fromJson({
            'id': 1,
            'channel': channel,
            'payload': payload,
            'created_at': '2026-12-02T10:00:00Z',
          });
      final proposed = row('journey.schedule_change_proposed', {
        'deal_id': 7,
        'journey_id': 9,
      }).destination;
      expect(proposed, isA<OpenScheduleChange>());
      expect(
        row('journey.schedule_change_applied', {'journey_id': 9}).destination,
        isA<OpenJourney>(),
      );
      expect(
        row('deal.problem_reported', {'deal_id': 7}).destination,
        isA<OpenDeal>(),
      );
    });
  });

  // -------------------------------------------------------------------------
  group('the no-show action', () {
    testWidgets('the traveler reports that the sender did not come', (
      tester,
    ) async {
      final backend =
          _dealBackend(
            traveler: true,
            problems: _problems(canNoShow: true),
          )..on(
            'POST',
            '/api/deals/7/problems',
            FakeResponse(201, {
              'problem': _problem(9, 'sender_unavailable', status: 'escalated'),
              'created': true,
            }),
          );
      await _pumpDeal(tester, backend);
      final l = _l(tester);

      await tester.tap(find.text(l.noShowActionSender));
      await tester.pumpAndSettle();
      // What happens next is said before the button is pressed.
      expect(find.text(l.noShowNextBody), findsOneWidget);
      await tester.enterText(find.byType(TextField), 'I waited at the gate.');
      await tester.tap(find.text(l.noShowSendAction));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('POST', '/api/deals/7/problems')!;
      expect(sent.body, {
        'kind': 'sender_unavailable',
        'note': 'I waited at the gate.',
      });
      // Nothing else was written: no cancel, no dispute, no deal write.
      expect(backend.requests.where((r) => r.method == 'POST'), hasLength(1));
      expect(find.text(l.noShowSendAction), findsNothing);
    });

    testWidgets('the sender gets the traveler wording', (tester) async {
      final backend = _dealBackend(
        problems: _problems(role: 'sender', canNoShow: true),
      );
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      expect(find.text(l.noShowActionTraveler), findsOneWidget);
      expect(find.text(l.noShowActionSender), findsNothing);
    });

    testWidgets('no action while the server says the window is shut', (
      tester,
    ) async {
      final backend = _dealBackend(traveler: true, problems: _problems());
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      expect(find.text(l.noShowActionSender), findsNothing);
      expect(find.text(l.noShowActionTraveler), findsNothing);
    });

    testWidgets('after reporting, the state and chat are offered', (
      tester,
    ) async {
      final backend = _dealBackend(
        traveler: true,
        problems: _problems(
          results: [_problem(9, 'sender_unavailable', status: 'escalated')],
        ),
      );
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      expect(find.text(l.noShowReportedSender), findsOneWidget);
      expect(find.text(l.problemStatusEscalated), findsWidgets);
      expect(find.text(l.noShowNextBody), findsOneWidget);
      expect(find.text(l.noShowMessageInChat), findsOneWidget);
      // One live report per person: the action button is gone. The kind's
      // name remains once, in the list of reports.
      expect(find.text(l.noShowActionSender), findsOneWidget);
      expect(find.byType(AppButton), findsWidgets);
      expect(
        find.widgetWithText(AppButton, l.noShowActionSender),
        findsNothing,
      );
    });

    testWidgets(
      'the other person sees a banner with chat and their own action',
      (tester) async {
        final backend = _dealBackend(
          traveler: true,
          problems: _problems(
            canNoShow: true,
            results: [
              _problem(4, 'traveler_no_show', mine: false, status: 'escalated'),
            ],
          ),
        );
        await _pumpDeal(tester, backend);
        final l = _l(tester);
        expect(find.text(l.noShowAgainstTravelerTitle), findsOneWidget);
        expect(find.text(l.noShowReplyInChat), findsOneWidget);
        expect(find.text(l.noShowActionSender), findsOneWidget);
      },
    );

    testWidgets('a refusal stays in the sheet and refreshes the answer', (
      tester,
    ) async {
      final backend =
          _dealBackend(traveler: true, problems: _problems(canNoShow: true))
            ..on(
              'POST',
              '/api/deals/7/problems',
              const FakeResponse(409, {
                'code': 'no_show_report_not_allowed',
                'detail': 'closed',
                'reason': 'pickup_already_confirmed',
              }),
            );
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text(l.noShowActionSender));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.noShowSendAction));
      await tester.pumpAndSettle();
      expect(find.text(l.problemErrorNoShowClosed), findsOneWidget);
      // The sheet is still open, nothing was reported.
      expect(find.text(l.noShowSendAction), findsOneWidget);
      expect(backend.to('GET', '/api/deals/7/problems').length, greaterThan(1));
    });
  });

  // -------------------------------------------------------------------------
  group('problem reports', () {
    testWidgets('the list shows both people\'s reports, notes included', (
      tester,
    ) async {
      final backend = _dealBackend(
        problems: _problems(
          role: 'sender',
          kinds: ['parcel_damaged', 'other'],
          results: [
            _problem(
              1,
              'parcel_damaged',
              note: 'The box is crushed.',
              mine: false,
            ),
          ],
        ),
      );
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      expect(find.text(l.problemKindParcelDamaged), findsOneWidget);
      expect(find.text('The box is crushed.'), findsOneWidget);
      expect(find.textContaining(l.problemReportedByOther), findsOneWidget);
    });

    testWidgets('reporting needs a kind, then sends kind and note only', (
      tester,
    ) async {
      final backend =
          _dealBackend(
            problems: _problems(
              role: 'sender',
              kinds: ['parcel_damaged', 'customs_delay'],
            ),
          )..on(
            'POST',
            '/api/deals/7/problems',
            FakeResponse(201, {
              'problem': _problem(2, 'customs_delay'),
              'created': true,
            }),
          );
      await _pumpDeal(tester, backend);
      final l = _l(tester);

      await tester.tap(find.text(l.problemReportAction));
      await tester.pumpAndSettle();
      // No kind chosen yet: the button is dead.
      await tester.tap(find.text(l.problemSendAction));
      await tester.pumpAndSettle();
      expect(backend.to('POST', '/api/deals/7/problems'), isEmpty);

      await tester.tap(find.text(l.problemKindCustomsDelay));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.problemSendAction));
      await tester.pumpAndSettle();
      expect(backend.lastTo('POST', '/api/deals/7/problems')!.body, {
        'kind': 'customs_delay',
        'note': '',
      });
    });

    testWidgets('the general list never offers the no-show kinds', (
      tester,
    ) async {
      final backend = _dealBackend(
        problems: _problems(role: 'sender', canNoShow: true, kinds: ['other']),
      );
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text(l.problemReportAction));
      await tester.pumpAndSettle();
      expect(find.text(l.problemKindOther), findsOneWidget);
      expect(
        find.descendant(
          of: find.byType(BottomSheet),
          matching: find.text(l.problemKindTravelerNoShow),
        ),
        findsNothing,
      );
    });

    testWidgets('an offline send says nothing was sent', (tester) async {
      final backend =
          _dealBackend(
            problems: _problems(role: 'sender', kinds: ['other']),
          )..handle(
            'POST',
            '/api/deals/7/problems',
            (_) => throw StateError('offline'),
          );
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text(l.problemReportAction));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.problemKindOther));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.problemSendAction));
      await tester.pumpAndSettle();
      // Whatever the failure, the sheet stays open with a sentence.
      expect(find.text(l.problemSendAction), findsOneWidget);
      expect(find.text(l.problemSent), findsNothing);
    });

    testWidgets('no problems block when the server lists none', (tester) async {
      final backend = _dealBackend(problems: _problems(role: 'sender'));
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      expect(find.text(l.problemsTitle), findsNothing);
      expect(find.text(l.problemReportAction), findsNothing);
    });
  });

  // -------------------------------------------------------------------------
  group('the sender and new times', () {
    Future<FakeBackend> pumpAnswer(
      WidgetTester tester,
      Map<String, dynamic> change, {
      Locale locale = const Locale('en'),
      Map<String, dynamic>? problems,
    }) async {
      final backend = _dealBackend(change: change, problems: problems)
        ..on('GET', '/api/deals/7/cancellation', FakeResponse(200, _quote()));
      await pumpDiscovery(
        tester,
        const ScheduleChangeAnswerScreen(dealId: 7),
        backend,
        locale: locale,
        device: _tall,
        extraRoutes: [
          marker('deal-cancel', '/deals/:id/cancel'),
          marker('deal', '/deals/:id'),
        ],
      );
      return backend;
    }

    testWidgets('the deal shows a prompt when the sender is asked', (
      tester,
    ) async {
      final backend = _dealBackend(change: _senderChange());
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      expect(find.text(l.scheduleAskedHeadline), findsOneWidget);
      expect(find.text(l.scheduleReviewAction), findsOneWidget);
    });

    testWidgets('the deal shows nothing when no change touched it', (
      tester,
    ) async {
      final backend = _dealBackend();
      await _pumpDeal(tester, backend);
      final l = _l(tester);
      expect(find.text(l.scheduleAskedHeadline), findsNothing);
    });

    testWidgets('old and new times, why, and the two answers', (tester) async {
      await pumpAnswer(tester, _senderChange());
      final l = _l(tester);
      expect(find.text(l.scheduleReasonShift), findsOneWidget);
      expect(find.text('The airline moved my flight.'), findsOneWidget);
      expect(find.text(l.scheduleAcceptAction), findsOneWidget);
      expect(find.text(l.scheduleDeclineAction), findsOneWidget);
    });

    testWidgets('accept sends accept and nothing else', (tester) async {
      final backend = await pumpAnswer(tester, _senderChange());
      backend.handle('POST', '/api/deals/7/schedule-change/accept', (_) {
        return FakeResponse(
          200,
          _senderChange(consent: 'accepted', canAnswer: true),
        );
      });
      final l = _l(tester);
      await tester.tap(find.text(l.scheduleAcceptAction));
      await tester.pumpAndSettle();
      expect(
        backend.to('POST', '/api/deals/7/schedule-change/accept'),
        hasLength(1),
      );
      expect(backend.requests.where((r) => r.method == 'POST'), hasLength(1));
    });

    testWidgets('decline asks first, cancels nothing, then shows the quote', (
      tester,
    ) async {
      final backend = await pumpAnswer(tester, _senderChange());
      var declined = false;
      backend
        ..handle('POST', '/api/deals/7/schedule-change/decline', (_) {
          declined = true;
          return FakeResponse(200, _senderChange(consent: 'declined'));
        })
        ..handle(
          'GET',
          '/api/deals/7/schedule-change',
          (_) => FakeResponse(
            200,
            declined ? _senderChange(consent: 'declined') : _senderChange(),
          ),
        );
      final l = _l(tester);

      await tester.tap(find.text(l.scheduleDeclineAction));
      await tester.pumpAndSettle();
      expect(find.text(l.scheduleDeclineConfirmTitle), findsOneWidget);
      // Backing out writes nothing.
      await tester.tap(find.text(l.scheduleDeclineKeep));
      await tester.pumpAndSettle();
      expect(
        backend.to('POST', '/api/deals/7/schedule-change/decline'),
        isEmpty,
      );

      await tester.tap(find.text(l.scheduleDeclineAction));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(l.scheduleDeclineAction),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        backend.to('POST', '/api/deals/7/schedule-change/decline'),
        hasLength(1),
      );
      expect(backend.to('POST', '/api/deals/7/cancel'), isEmpty);
      // The server's quote, with the line that says whose cancellation it is.
      expect(find.text(l.scheduleIfYouCancelTitle), findsOneWidget);
      expect(find.text(l.scheduleCancelCountsAsTraveler), findsOneWidget);
      expect(find.text(l.scheduleAcceptInstead), findsOneWidget);
    });

    testWidgets('a collected parcel is told, not asked', (tester) async {
      await pumpAnswer(
        tester,
        _senderChange(
          status: 'applied',
          canAnswer: false,
          informed: true,
          actions: ['report_problem', 'open_dispute'],
          reasons: const [],
        ),
        problems: _problems(role: 'sender', kinds: ['other']),
      );
      final l = _l(tester);
      expect(find.text(l.scheduleInformedHeadline), findsOneWidget);
      expect(find.text(l.scheduleAcceptAction), findsNothing);
      expect(find.text(l.scheduleDeclineAction), findsNothing);
      // The two actions the server names, and no cancel.
      expect(find.text(l.problemReportAction), findsOneWidget);
      expect(find.text(l.dealActionDispute), findsOneWidget);
      expect(find.text(l.dealActionCancel), findsNothing);
    });

    testWidgets('a change that was withdrawn offers no answer', (tester) async {
      await pumpAnswer(
        tester,
        _senderChange(status: 'withdrawn', canAnswer: false),
      );
      final l = _l(tester);
      expect(find.text(l.scheduleWithdrawnHeadline), findsOneWidget);
      expect(find.text(l.scheduleAcceptAction), findsNothing);
    });

    testWidgets('no change at all is an honest empty state', (tester) async {
      await pumpAnswer(tester, {'deal_id': 7, 'change': null});
      final l = _l(tester);
      expect(find.text(l.scheduleNoneTitle), findsOneWidget);
    });

    testWidgets('Arabic renders right to left', (tester) async {
      await pumpAnswer(tester, _senderChange(), locale: const Locale('ar'));
      final l = _l(tester);
      expect(find.text(l.scheduleAcceptAction), findsOneWidget);
      expect(
        Directionality.of(tester.element(find.byType(Scaffold).first)),
        TextDirection.rtl,
      );
    });
  });

  // -------------------------------------------------------------------------
  group('the traveler and new times', () {
    Map<String, dynamic> journey() {
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

    Map<String, dynamic> change({
      String status = 'pending_senders',
      int waitingFor = 1,
      String withdrawnBy = '',
    }) => {
      'id': 3,
      'journey_id': 9,
      'status': status,
      'reason': '',
      'created_at': '2026-12-01T09:00:00Z',
      'applied_at': null,
      'withdrawn_at': status == 'withdrawn' ? '2026-12-01T10:00:00Z' : null,
      'withdrawn_by': withdrawnBy,
      'legs': [_legChange(100)],
      'parcels': [
        {
          'deal_id': 7,
          'tracking_number': 'WSL-3NZ5FHHQ',
          'material': true,
          'informed': false,
          'reasons': ['shift'],
          'arrival_before': '2026-12-02T13:00:00Z',
          'arrival_after': '2026-12-02T17:00:00Z',
          'pickup_before': '2026-12-02T10:00:00Z',
          'pickup_after': '2026-12-02T14:00:00Z',
          'consent_state': 'pending',
        },
      ],
      'waiting_for': waitingFor,
    };

    FakeBackend backend0({List<Map<String, dynamic>> changes = const []}) =>
        discoveryBackend()
          ..on('GET', '/api/journeys/9', FakeResponse(200, journey()))
          ..on(
            'GET',
            '/api/journeys/9/progress',
            const FakeResponse(200, {
              'journey_id': 9,
              'status': 'active',
              'legs': <Object>[],
            }),
          )
          ..on(
            'GET',
            '/api/journeys/9/schedule-changes',
            FakeResponse(200, {'results': changes}),
          )
          ..on(
            'GET',
            '/api/matches/compatible-requests',
            FakeResponse(200, {'candidates': <Object>[]}),
          );

    testWidgets('the journey offers "Change times" when nothing waits', (
      tester,
    ) async {
      await pumpDiscovery(
        tester,
        const JourneyDetailScreen(journeyId: 9),
        backend0(),
        role: RoleContext.traveler,
        device: _tall,
        extraRoutes: [
          marker('journey-change-times', '/journeys/:id/change-times'),
        ],
      );
      final l = _l(tester);
      expect(find.text(l.scheduleChangeAction), findsOneWidget);
      expect(find.text(l.scheduleWithdrawAction), findsNothing);
    });

    testWidgets('a waiting change shows who is asked and can be withdrawn', (
      tester,
    ) async {
      final backend = backend0(changes: [change()])
        ..on(
          'POST',
          '/api/journeys/9/schedule-changes/3/withdraw',
          FakeResponse(
            200,
            change(status: 'withdrawn', withdrawnBy: 'traveler'),
          ),
        );
      await pumpDiscovery(
        tester,
        const JourneyDetailScreen(journeyId: 9),
        backend,
        role: RoleContext.traveler,
        device: _tall,
      );
      final l = _l(tester);
      expect(find.text(l.scheduleWaitingPill(1)), findsOneWidget);
      expect(find.text('WSL-3NZ5FHHQ'), findsOneWidget);
      // No second change while one waits.
      expect(find.text(l.scheduleChangeAction), findsNothing);
      await tester.ensureVisible(find.text(l.scheduleWithdrawAction));
      await tester.tap(find.text(l.scheduleWithdrawAction));
      await tester.pumpAndSettle();
      expect(
        backend.to('POST', '/api/journeys/9/schedule-changes/3/withdraw'),
        hasLength(1),
      );
    });

    testWidgets('a change dropped by the server says the trip moved on', (
      tester,
    ) async {
      await pumpDiscovery(
        tester,
        const JourneyDetailScreen(journeyId: 9),
        backend0(
          changes: [
            change(status: 'withdrawn', withdrawnBy: 'no_longer_valid'),
          ],
        ),
        role: RoleContext.traveler,
        device: _tall,
        extraRoutes: [
          marker('journey-change-times', '/journeys/:id/change-times'),
        ],
      );
      final l = _l(tester);
      expect(find.text(l.scheduleWithdrawnNoLongerValid), findsOneWidget);
      expect(find.text(l.scheduleChangeAction), findsOneWidget);
    });

    Future<void> pickNextDay(WidgetTester tester, String label) async {
      await tester.tap(find.text(label).first);
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(DatePickerDialog),
          matching: find.text('3'),
        ),
      );
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
    }

    testWidgets('review needs a changed time, previews, then sends', (
      tester,
    ) async {
      final backend = backend0()
        ..on(
          'POST',
          '/api/journeys/9/schedule-changes/preview',
          FakeResponse(200, {
            'journey_id': 9,
            'legs': [_legChange(100)],
            'parcels': change()['parcels'],
            'applies_at_once': false,
            'notices': [
              {
                'code': 'ticket_recheck',
                'text': 'Your ticket will be checked again.',
              },
            ],
          }),
        )
        ..on(
          'POST',
          '/api/journeys/9/schedule-changes',
          FakeResponse(201, change()),
        );
      await pumpDiscovery(
        tester,
        const ChangeTimesScreen(journeyId: 9),
        backend,
        role: RoleContext.traveler,
        device: _tall,
      );
      final l = _l(tester);

      // Nothing changed yet: the review button is dead.
      await tester.tap(find.text(l.scheduleReviewAction));
      await tester.pumpAndSettle();
      expect(
        backend.to('POST', '/api/journeys/9/schedule-changes/preview'),
        isEmpty,
      );

      await pickNextDay(tester, l.scheduleDeparture);
      await tester.tap(find.text(l.scheduleReviewAction));
      await tester.pumpAndSettle();

      final preview = backend.lastTo(
        'POST',
        '/api/journeys/9/schedule-changes/preview',
      )!;
      final legs = preview.body['legs'] as List;
      expect(legs, hasLength(1));
      expect((legs.single as Map)['id'], 100);
      // Instants, with a zone.
      expect((legs.single as Map)['depart_at'], endsWith('Z'));

      // The review: who must agree, the server's notice, nothing written yet.
      expect(find.text(l.scheduleMustAgreeTitle), findsOneWidget);
      expect(find.text(l.scheduleWaitsTitle(1)), findsOneWidget);
      expect(find.text('Your ticket will be checked again.'), findsOneWidget);
      expect(backend.to('POST', '/api/journeys/9/schedule-changes'), isEmpty);

      await tester.enterText(
        find.byType(TextField),
        'Airline moved the flight',
      );
      await tester.tap(find.text(l.scheduleSendAction));
      await tester.pumpAndSettle();
      final sent = backend.lastTo('POST', '/api/journeys/9/schedule-changes')!;
      expect(sent.body['reason'], 'Airline moved the flight');
      expect((sent.body['legs'] as List), hasLength(1));
    });

    testWidgets('a change that applies at once says so', (tester) async {
      final backend = backend0()
        ..on(
          'POST',
          '/api/journeys/9/schedule-changes/preview',
          FakeResponse(200, {
            'journey_id': 9,
            'legs': [_legChange(100)],
            'parcels': <Object>[],
            'applies_at_once': true,
            'notices': <Object>[],
          }),
        );
      await pumpDiscovery(
        tester,
        const ChangeTimesScreen(journeyId: 9),
        backend,
        role: RoleContext.traveler,
        device: _tall,
      );
      final l = _l(tester);
      await pickNextDay(tester, l.scheduleArrival);
      await tester.tap(find.text(l.scheduleReviewAction));
      await tester.pumpAndSettle();
      expect(find.text(l.scheduleAppliesAtOnceTitle), findsOneWidget);
      expect(find.text(l.scheduleNoParcelsAffected), findsOneWidget);
      expect(find.text(l.scheduleApplyAction), findsOneWidget);
    });

    testWidgets('a refused preview shows the server reason on the times', (
      tester,
    ) async {
      final backend = backend0()
        ..on(
          'POST',
          '/api/journeys/9/schedule-changes/preview',
          const FakeResponse(409, {
            'code': 'leg_already_departed',
            'detail': 'departed',
          }),
        );
      await pumpDiscovery(
        tester,
        const ChangeTimesScreen(journeyId: 9),
        backend,
        role: RoleContext.traveler,
        device: _tall,
      );
      final l = _l(tester);
      await pickNextDay(tester, l.scheduleDeparture);
      await tester.tap(find.text(l.scheduleReviewAction));
      await tester.pumpAndSettle();
      expect(find.text(l.scheduleErrorLegDeparted), findsOneWidget);
      // Still editing.
      expect(find.text(l.scheduleReviewAction), findsOneWidget);
    });
  });
}
