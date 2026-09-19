/// Phase J8.1 Pre-Launch UI/i18n Remediation Test Suite.
///
/// Validates the remediation of defects identified during J8 Deep Pre-Launch
/// Certification:
/// - DEF-SND-01: Correct Arabic RTL route progression (Origin physically right,
///   destination physically left, arrow pointing left, semantic order preserved).
/// - DEF-SND-02: Localized RouteSummary screen-reader accessibility semantics
///   (EN: "to", FR: "vers", AR: "إلى", with decorative arrow excluded).
/// - DEF-SND-03: Interactive Profile legal links (Terms and Privacy) with
///   canonical URL resolution, graceful failure UX, and hidden Contact Support
///   row awaiting authoritative destination.
/// - DEF-SND-05: Clean removal of unused _chosenDepositCents in RequestCreateScreen.
/// - Responsive visual QA across 320x640, 390x844, 411x869 and 1.6x text scaling.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/env/app_config.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/components/route.dart';
import 'package:shiptrip/design/components/status.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/domain/rating.dart';
import 'package:shiptrip/features/deliveries/deliveries_screen.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';
import 'package:shiptrip/features/requests/request_create_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

void _stubBrowser(
  WidgetTester tester, {
  required List<String> opened,
  bool succeed = true,
}) {
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    const MethodChannel('plugins.flutter.io/url_launcher'),
    (call) async {
      if (call.method == 'launch') {
        opened.add((call.arguments as Map)['url'] as String);
        return succeed;
      }
      return true;
    },
  );
  addTearDown(
    () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/url_launcher'),
      null,
    ),
  );
}

Map<String, dynamic> _locality(int id, String name, String country) => {
  'id': id,
  'name': name,
  'display_label': name,
  'place_type': 'locality',
  'iata_code': null,
  'country_code': country,
  'parent_name': null,
  'matching_locality_id': id,
  'matching_locality_name': name,
};

Map<String, dynamic> _parcelFixture({
  required String pickupName,
  required String deliveryName,
  String pickupCountry = 'DZ',
  String deliveryCountry = 'FR',
  String title = 'Documents for Paris',
}) => {
  'id': 77,
  'sender_id': 42,
  'target_traveler_id': null,
  'kind': 'delivery',
  'status': 'open',
  'schema_version': 3,
  'title': title,
  'description': 'A sealed folder of documents.',
  'category': 'documents',
  'fragile': false,
  'handling_notes': '',
  'actual_weight_kg': '2.50',
  'declared_value_eur_cents': 5000,
  'sender_proposed_reward_eur_cents': 4000,
  'boost_eur_cents': 0,
  'total_offered_reward_eur_cents': 4000,
  'pickup_place': _locality(11, pickupName, pickupCountry),
  'delivery_place': _locality(22, deliveryName, deliveryCountry),
  'created_at': '2026-09-19T08:00:00Z',
};

Future<void> _pumpScreenWithRoute(
  WidgetTester tester,
  Widget screen, {
  Locale locale = const Locale('en'),
  DeviceProfile device = DeviceProfile.android,
  String pickupName = 'Algiers',
  String deliveryName = 'Paris',
  String title = 'Documents for Paris',
}) async {
  final parcel = _parcelFixture(
    pickupName: pickupName,
    deliveryName: deliveryName,
    title: title,
  );

  final backend = FakeBackend()
    ..on('GET', '/api/me', FakeResponse(200, meFixture()))
    ..on('GET', '/api/deals', FakeResponse(200, <Object>[]))
    ..on('GET', '/api/matches', FakeResponse(200, <Object>[]))
    ..on('GET', '/api/journeys', FakeResponse(200, <Object>[]))
    ..on(
      'GET',
      '/api/notifications/unread-count',
      FakeResponse(200, {'unread': 0}),
    )
    ..on('GET', '/api/parcels', FakeResponse(200, [parcel]));

  final container = containerFor(backend);
  addTearDown(container.dispose);
  await tester.runAsync(
    () => container.read(sessionProvider.notifier).restore(),
  );
  await pumpApp(
    tester,
    screen,
    container: container,
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
}

ProviderContainer _profileContainer({
  Account? account,
  int completedDeals = 0,
  List<Rating> ratings = const [],
}) {
  final me =
      account ??
      Account(
        id: 42,
        email: 'user@example.com',
        fullName: 'Test User',
        phone: '',
        wilaya: '',
        role: AccountRole.both,
        preferredLanguage: CommunicationLanguage.english,
        isEmailVerified: true,
        isPhoneVerified: false,
        isKycVerified: true,
        kycStatus: KycStatus.verified,
        dateJoined: DateTime(2026, 1, 1),
      );

  return ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(FakeTokenStore()),
      accountProvider.overrideWithValue(me),
      completedDealsCountProvider.overrideWith(
        (ref) => AsyncData(completedDeals),
      ),
      receivedRatingsProvider.overrideWith((ref) => AsyncData(ratings)),
      unreadNotificationsProvider.overrideWith((ref) => const AsyncData(0)),
    ],
  );
}

Future<void> _pumpProfileScreen(
  WidgetTester tester, {
  Locale locale = const Locale('en'),
  DeviceProfile device = DeviceProfile.android,
}) async {
  final container = _profileContainer();
  addTearDown(container.dispose);
  await pumpApp(
    tester,
    const ProfileScreen(),
    container: container,
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
}

Future<void> _pumpCreateScreen(
  WidgetTester tester, {
  Locale locale = const Locale('en'),
}) async {
  final backend = FakeBackend()
    ..on('GET', '/api/me', FakeResponse(200, meFixture()))
    ..on('GET', '/api/places/popular', FakeResponse(200, <Object>[]));

  final container = containerFor(backend);
  addTearDown(container.dispose);
  await tester.runAsync(
    () => container.read(sessionProvider.notifier).restore(),
  );
  await pumpApp(
    tester,
    const RequestCreateScreen(),
    container: container,
    locale: locale,
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('DEF-SND-01: Route Visual Order & RTL Progression', () {
    testWidgets('RouteSummary in LTR places origin left, destination right', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: RouteSummary(from: 'Algiers', to: 'Paris'),
        ),
        locale: const Locale('en'),
      );

      final originPos = tester.getTopLeft(find.text('Algiers'));
      final destPos = tester.getTopLeft(find.text('Paris'));

      // In LTR: origin must be strictly to the left of destination
      expect(
        originPos.dx < destPos.dx,
        isTrue,
        reason:
            'Origin (Algiers) should appear to the left of destination (Paris) in LTR',
      );

      // Arrow points right
      final arrow = tester.widget<Icon>(
        find.byIcon(Icons.arrow_forward_rounded),
      );
      expect(arrow.icon!.matchTextDirection, isTrue);
      expect(
        Directionality.of(
          tester.element(find.byIcon(Icons.arrow_forward_rounded)),
        ),
        TextDirection.ltr,
      );
    });

    testWidgets('RouteSummary in RTL places origin right, destination left', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: RouteSummary(from: 'الجزائر', to: 'باريس'),
        ),
        locale: const Locale('ar'),
      );

      final originPos = tester.getTopLeft(find.text('الجزائر'));
      final destPos = tester.getTopLeft(find.text('باريس'));

      // In Arabic RTL: reading runs right-to-left.
      // Origin must physically appear to the RIGHT of destination!
      expect(
        originPos.dx > destPos.dx,
        isTrue,
        reason:
            'Origin (الجزائر) must appear to the right of destination (باريس) in RTL',
      );

      // Directional arrow mirrors under RTL to point left (towards destination)
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

    testWidgets('Regression check: swapped Arabic order (old defect) would fail', (
      tester,
    ) async {
      // Simulating the old defect where to/from were swapped: Destination ← Origin
      await pumpApp(
        tester,
        const Scaffold(
          // If someone passes destination first in RTL:
          body: RouteSummary(from: 'باريس', to: 'الجزائر'),
        ),
        locale: const Locale('ar'),
      );

      final parisPos = tester.getTopLeft(find.text('باريس'));
      final algiersPos = tester.getTopLeft(find.text('الجزائر'));

      // If someone passed Paris as 'from' and Algiers as 'to', Paris is on the right.
      // For a trip from Algiers to Paris, Algiers MUST be on the right.
      final bool isAlgiersOriginOnRight = algiersPos.dx > parisPos.dx;
      expect(
        isAlgiersOriginOnRight,
        isFalse,
        reason:
            'Passing Paris as from places Paris on right, which is the inverted failure mode',
      );
    });

    testWidgets(
      'HomeScreen request card renders RouteSummary with correct RTL progression',
      (tester) async {
        await _pumpScreenWithRoute(
          tester,
          const HomeScreen(),
          locale: const Locale('ar'),
          pickupName: 'الجزائر',
          deliveryName: 'باريس',
        );

        expect(find.byType(RouteSummary), findsWidgets);
        final originPos = tester.getTopLeft(find.text('الجزائر'));
        final destPos = tester.getTopLeft(find.text('باريس'));

        expect(
          originPos.dx > destPos.dx,
          isTrue,
          reason: 'HomeScreen card: origin must be on the right in Arabic RTL',
        );
      },
    );

    testWidgets(
      'DeliveriesScreen card renders RouteSummary with correct RTL progression',
      (tester) async {
        await _pumpScreenWithRoute(
          tester,
          const DeliveriesScreen(),
          locale: const Locale('ar'),
          pickupName: 'الجزائر',
          deliveryName: 'باريس',
        );

        expect(find.byType(RouteSummary), findsWidgets);
        final originPos = tester.getTopLeft(find.text('الجزائر'));
        final destPos = tester.getTopLeft(find.text('باريس'));

        expect(
          originPos.dx > destPos.dx,
          isTrue,
          reason:
              'DeliveriesScreen card: origin must be on the right in Arabic RTL',
        );
      },
    );
  });

  group('DEF-SND-02: Route Accessibility Semantics Localization', () {
    testWidgets('RouteSummary announces English "to" connector', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: RouteSummary(from: 'Algiers', to: 'Paris'),
        ),
        locale: const Locale('en'),
      );

      final semantics = tester.getSemantics(find.byType(RouteSummary));
      expect(semantics.label, 'Algiers to Paris');
    });

    testWidgets('RouteSummary announces French "vers" connector', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: RouteSummary(from: 'Alger', to: 'Paris'),
        ),
        locale: const Locale('fr'),
      );

      final semantics = tester.getSemantics(find.byType(RouteSummary));
      expect(semantics.label, 'Alger vers Paris');
    });

    testWidgets('RouteSummary announces Arabic "إلى" connector', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: RouteSummary(from: 'الجزائر', to: 'باريس'),
        ),
        locale: const Locale('ar'),
      );

      final semantics = tester.getSemantics(find.byType(RouteSummary));
      expect(semantics.label, 'الجزائر إلى باريس');
    });

    testWidgets(
      'RouteSummary excludes child semantics to prevent duplicate screen reader readings',
      (tester) async {
        await pumpApp(
          tester,
          const Scaffold(
            body: RouteSummary(from: 'Algiers', to: 'Paris'),
          ),
          locale: const Locale('en'),
        );

        final semanticsWidget = tester.widget<Semantics>(
          find
              .descendant(
                of: find.byType(RouteSummary),
                matching: find.byType(Semantics),
              )
              .first,
        );
        expect(semanticsWidget.excludeSemantics, isTrue);
      },
    );

    testWidgets(
      'InlineRoute announces localized connectors in EN, FR, and AR',
      (tester) async {
        const stops = [
          InlineRouteStop(label: 'Algiers'),
          InlineRouteStop(label: 'Paris'),
        ];

        expect(
          routeSemanticLabel(stops: stops, locale: const Locale('en')),
          'Algiers to Paris',
        );
        expect(
          routeSemanticLabel(stops: stops, locale: const Locale('fr')),
          'Algiers vers Paris',
        );
        expect(
          routeSemanticLabel(stops: stops, locale: const Locale('ar')),
          'Algiers إلى Paris',
        );
      },
    );
  });

  group('DEF-SND-03: Profile Legal & Support Rows', () {
    testWidgets(
      'Terms of Service row is interactive and launches resolved canonical /terms URL',
      (tester) async {
        final opened = <String>[];
        _stubBrowser(tester, opened: opened);

        await _pumpProfileScreen(tester, locale: const Locale('en'));

        final termsFinder = find.text('Terms of service');
        await tester.scrollUntilVisible(termsFinder, 200);
        expect(termsFinder, findsOneWidget);

        await tester.tap(termsFinder);
        await tester.pumpAndSettle();

        expect(opened, hasLength(1));
        final expectedUrl = Uri.parse(
          AppConfig.webBaseUrl,
        ).resolve('/terms').toString();
        expect(opened.first, expectedUrl);
      },
    );

    testWidgets(
      'Privacy Policy row is interactive and launches resolved canonical /privacy URL',
      (tester) async {
        final opened = <String>[];
        _stubBrowser(tester, opened: opened);

        await _pumpProfileScreen(tester, locale: const Locale('en'));

        final privacyFinder = find.text('Privacy policy');
        await tester.scrollUntilVisible(privacyFinder, 200);
        expect(privacyFinder, findsOneWidget);

        await tester.tap(privacyFinder);
        await tester.pumpAndSettle();

        expect(opened, hasLength(1));
        final expectedUrl = Uri.parse(
          AppConfig.webBaseUrl,
        ).resolve('/privacy').toString();
        expect(opened.first, expectedUrl);
      },
    );

    testWidgets(
      'External link failure displays graceful localized snackbar without crashing',
      (tester) async {
        final opened = <String>[];
        _stubBrowser(tester, opened: opened, succeed: false);

        await _pumpProfileScreen(tester, locale: const Locale('en'));

        final termsFinder = find.text('Terms of service');
        await tester.scrollUntilVisible(termsFinder, 200);
        await tester.tap(termsFinder);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 100));

        expect(
          find.text(
            "We couldn't open that page. Check that you have a browser installed.",
          ),
          findsOneWidget,
        );

        // Drain snackbar timer before teardown
        await tester.pump(const Duration(seconds: 5));
      },
    );

    testWidgets('Contact Support is hidden awaiting authoritative destination', (
      tester,
    ) async {
      await _pumpProfileScreen(tester, locale: const Locale('en'));

      // Contact Support must not appear as an interactive row with no destination
      expect(find.byIcon(Icons.support_agent_rounded), findsNothing);
      expect(find.text('Contact support'), findsNothing);
    });

    testWidgets('Interactive legal rows meet 48dp minimum tap target floor', (
      tester,
    ) async {
      await _pumpProfileScreen(tester, locale: const Locale('en'));

      final termsFinder = find.text('Terms of service');
      await tester.scrollUntilVisible(termsFinder, 200);

      final termsBox = tester.getSize(
        find.ancestor(of: termsFinder, matching: find.byType(InkWell)),
      );
      expect(termsBox.height, greaterThanOrEqualTo(48.0));

      final privacyFinder = find.text('Privacy policy');
      await tester.scrollUntilVisible(privacyFinder, 200);

      final privacyBox = tester.getSize(
        find.ancestor(of: privacyFinder, matching: find.byType(InkWell)),
      );
      expect(privacyBox.height, greaterThanOrEqualTo(48.0));
    });
  });

  group('DEF-SND-05: Dead Deposit Field Cleanup Verification', () {
    testWidgets(
      'RequestCreateScreen mounts cleanly without _chosenDepositCents',
      (tester) async {
        await _pumpCreateScreen(tester, locale: const Locale('en'));
        expect(find.byType(RequestCreateScreen), findsOneWidget);
      },
    );
  });

  group('Responsive Matrix: Viewports and Text Scale Floors', () {
    const profiles = [
      DeviceProfile.smallAndroid, // 320x640
      DeviceProfile.iphone, // 390x844
      DeviceProfile.android, // 411x869
      DeviceProfile.largeText, // 1.6x text scale
    ];

    for (final profile in profiles) {
      testWidgets(
        'RouteSummary wraps cleanly without overflow on ${profile.name}',
        (tester) async {
          await pumpApp(
            tester,
            const Scaffold(
              body: Padding(
                padding: EdgeInsets.all(16),
                child: RouteSummary(
                  from: 'Constantine, Algeria (Near 12 Rue Didouche Mourad)',
                  to: 'Marseille, France (Provence-Alpes-Côte d\'Azur)',
                ),
              ),
            ),
            device: profile,
            locale: const Locale('ar'),
          );

          expect(tester.takeException(), isNull);
          expect(find.byType(RouteSummary), findsOneWidget);
        },
      );

      testWidgets(
        'Request card with RouteSummary does not overflow on ${profile.name}',
        (tester) async {
          await pumpApp(
            tester,
            Scaffold(
              body: Padding(
                padding: const EdgeInsets.all(AppSpace.gutter),
                child: AppCard(
                  onTap: () {},
                  child: const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              'Colis volumineux avec des documents importants',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w600,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          SizedBox(width: AppSpace.sm),
                          StatusPill(
                            label: 'Pending',
                            tone: StatusTone.waiting,
                            icon: Icons.hourglass_top_rounded,
                            compact: true,
                          ),
                        ],
                      ),
                      SizedBox(height: AppSpace.sm),
                      RouteSummary(
                        from:
                            'Constantine, Algeria (Near 12 Rue Didouche Mourad)',
                        to: 'Marseille, France (Provence-Alpes-Côte d\'Azur)',
                      ),
                    ],
                  ),
                ),
              ),
            ),
            device: profile,
            locale: const Locale('ar'),
          );

          expect(tester.takeException(), isNull);
          expect(find.byType(RouteSummary), findsOneWidget);
        },
      );

      testWidgets('ProfileScreen legal section renders on ${profile.name}', (
        tester,
      ) async {
        await _pumpProfileScreen(
          tester,
          device: profile,
          locale: const Locale('ar'),
        );

        final termsFinder = find.text('شروط الخدمة');
        await tester.scrollUntilVisible(termsFinder, 200);
        expect(termsFinder, findsOneWidget);

        final privacyFinder = find.text('سياسة الخصوصية');
        await tester.scrollUntilVisible(privacyFinder, 200);
        expect(privacyFinder, findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  });
}
