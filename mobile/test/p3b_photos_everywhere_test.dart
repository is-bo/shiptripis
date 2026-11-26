/// P3B: a person's photo wherever the person appears.
///
/// The owner decided that everyone sees photos, guests included, so a guest's
/// Browse draws them as a member's does. Each surface gets the server's `photo`
/// block; no photo, or no usable block, is the initials.
library;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/media/avatar_cache.dart' show versionOf;
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/domain/find_travelers.dart';
import 'package:shiptrip/domain/person_photo.dart';
import 'package:shiptrip/domain/public_discovery.dart';
import 'package:shiptrip/features/common/traveler_candidate_card.dart';
import 'package:shiptrip/features/discovery/alerts_screen.dart';
import 'package:shiptrip/features/discovery/browse_screens.dart';
import 'package:shiptrip/features/discovery/discovery_widgets.dart';
import 'package:shiptrip/features/discovery/person_screen.dart';
import 'package:shiptrip/features/offers/negotiation_screen.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';
import 'support/photo_cache.dart';

/// Every picture painted inside an avatar.
Finder get _pictures => find.descendant(
  of: find.byType(AppAvatar),
  matching: find.byType(RawImage),
);

Finder get _images => find.byType(CachedNetworkImage);

void main() {
  setUp(() => imageCache.clear());

  group('cards', () {
    testWidgets('a trip card draws the traveler\'s photo', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final card = TripCard.fromJson(tripCardFixture(1, photo: photoFixture()));
      await pumpApp(tester, TripListingCard(card: card, onTap: () {}));
      await settlePhotos(tester);

      expect(_pictures, findsOneWidget);
    });

    testWidgets('a trip card with no photo is the initials', (tester) async {
      final card = TripCard.fromJson(tripCardFixture(1));
      await pumpApp(tester, TripListingCard(card: card, onTap: () {}));

      expect(_images, findsNothing);
      expect(find.text('S'), findsOneWidget);
    });

    testWidgets('a request card shows the sender\'s photo beside "From"', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final card = RequestCard.fromJson(
        requestCardFixture(5, photo: photoFixture()),
      );
      await pumpApp(tester, RequestListingCard(card: card, onTap: () {}));
      await settlePhotos(tester);

      expect(_pictures, findsOneWidget);
      expect(find.text('From Yacine'), findsOneWidget);
    });

    testWidgets('a request card with no photo keeps its words and initials', (
      tester,
    ) async {
      final card = RequestCard.fromJson(requestCardFixture(5));
      await pumpApp(tester, RequestListingCard(card: card, onTap: () {}));

      expect(_images, findsNothing);
      expect(find.text('From Yacine'), findsOneWidget);
    });

    testWidgets('a Find Travelers card draws the traveler\'s photo', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final candidate = TravelerCandidate.fromJson({
        'journey_id': 3,
        'traveler': {
          ...discoveryPersonFields(name: 'Amina', photo: photoFixture()),
          'id': 203,
        },
        'route': {'stops': <Object>[]},
      });
      await pumpApp(
        tester,
        TravelerCandidateCard(candidate: candidate, onTap: () {}),
      );
      await settlePhotos(tester);

      expect(_pictures, findsOneWidget);
    });

    testWidgets('a profile card draws the person\'s photo', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final card = ProfileCard.fromJson(
        profileCardFixture(photo: photoFixture()),
      );
      await pumpApp(tester, ProfileTile(card: card, onTap: () {}));
      await settlePhotos(tester);

      expect(_pictures, findsOneWidget);
    });
  });

  group('a guest', () {
    Future<void> pumpAsGuest(
      WidgetTester tester,
      Widget screen,
      FakeBackend backend,
    ) async {
      final store = FakeTokenStore(refresh: null);
      final container = ProviderContainer(
        retry: (_, _) => null,
        overrides: [
          tokenStoreProvider.overrideWithValue(store),
          apiClientProvider.overrideWithValue(apiClientFor(backend, store)),
        ],
      );
      addTearDown(container.dispose);
      await tester.runAsync(
        () => container.read(sessionProvider.notifier).restore(),
      );
      expect(container.read(isGuestProvider), isTrue);
      await pumpApp(
        tester,
        screen,
        container: container,
        routed: true,
        extraRoutes: discoveryMarkers(),
      );
      await tester.pumpAndSettle();
      await settlePhotos(tester);
    }

    testWidgets('sees traveler photos in Browse trips', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips',
          discoveryPage([
            tripCardFixture(1, photo: photoFixture('a')),
            tripCardFixture(2, name: 'Nadia'),
          ]),
        );
      await pumpAsGuest(tester, const BrowseTripsScreen(), backend);

      expect(_pictures, findsOneWidget, reason: 'one traveler has a photo');
      expect(find.text('Samira'), findsOneWidget);
      expect(find.text('Nadia'), findsOneWidget);
    });

    testWidgets('sees sender photos in Browse requests', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/requests',
          discoveryPage([requestCardFixture(5, photo: photoFixture('b'))]),
        );
      await pumpAsGuest(tester, const BrowseRequestsScreen(), backend);

      expect(_pictures, findsOneWidget);
    });
  });

  group('the person page', () {
    testWidgets('draws the photo in the header and on their trip', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(200, {
            'state': 'results',
            'profile': profileCardFixture(photo: photoFixture('p')),
            'trips': [tripCardFixture(11, photo: photoFixture('p'))],
            'requests': <Object>[],
          }),
        );
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );
      await settlePhotos(tester);

      // Header and trip card: the same version, so one image in the cache.
      expect(_pictures, findsNWidgets(2));
    });

    testWidgets('fits 360 px in Arabic with a photo', (tester) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(200, {
            'state': 'results',
            'profile': profileCardFixture(photo: photoFixture('p')),
            'trips': <Object>[],
            'requests': <Object>[],
          }),
        );
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
        locale: const Locale('ar'),
        device: const DeviceProfile(name: '360x740', size: Size(360, 740)),
      );
      await settlePhotos(tester);

      expect(_pictures, findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('alerts', () {
    testWidgets('an alert that follows a person shows their photo', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/alerts',
          FakeResponse(200, {
            'results': [
              alertFixture(
                4,
                subject: {
                  'id': 'p-1',
                  'display_name': 'Samira',
                  'photo': photoFixture(),
                },
              ),
              alertFixture(5),
            ],
          }),
        );
      await pumpDiscovery(tester, const AlertsScreen(), backend);
      await settlePhotos(tester);

      expect(_pictures, findsOneWidget);
      expect(find.text('Following Samira'), findsOneWidget);
    });
  });

  group('proposals', () {
    Map<String, dynamic> matchJson() => {
      'id': 77,
      'parcel_id': 12,
      'sender_id': 42,
      'traveler_id': 99,
      'sender_name': 'Amina',
      'traveler_name': 'Karim',
      'sender_photo': photoFixture('mine'),
      'traveler_photo': photoFixture('karim'),
      'status': 'pending',
    };

    testWidgets('the negotiation header shows the other party\'s photo', (
      tester,
    ) async {
      final cache = installPhotoCache(PhotoCacheBehavior.serve);
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on('GET', '/api/matches/77', FakeResponse(200, matchJson()))
        ..on('GET', '/api/matches/77/offers', FakeResponse(200, <Object>[]));
      await pumpApp(
        tester,
        const NegotiationScreen(matchId: 77),
        container: containerFor(backend),
        device: const DeviceProfile(name: '360x740', size: Size(360, 740)),
      );
      await tester.pumpAndSettle();
      await settlePhotos(tester);

      // The viewer is the sender (id 42), so the counterparty is the traveler.
      expect(cache.keys.map(versionOf), ['karim']);
      expect(_pictures, findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(seconds: 5));
    });
  });

  group('my own profile', () {
    Account account({OwnPhoto? photo}) => Account(
      id: 42,
      email: 'amina@example.com',
      fullName: 'Amina Bouzid',
      phone: '',
      wilaya: '',
      role: AccountRole.both,
      preferredLanguage: CommunicationLanguage.french,
      isEmailVerified: true,
      isPhoneVerified: false,
      isKycVerified: true,
      kycStatus: KycStatus.verified,
      photo: photo,
    );

    ProviderContainer container(Account account) => ProviderContainer(
      overrides: [
        tokenStoreProvider.overrideWithValue(FakeTokenStore()),
        accountProvider.overrideWithValue(account),
        completedDealsCountProvider.overrideWith((ref) => const AsyncData(0)),
        ownRatingSummaryProvider.overrideWith(
          (ref) => const AsyncData(
            TravelerRating(state: TravelerRatingState.unrated, count: 0),
          ),
        ),
        supportEmailProvider.overrideWith((ref) async => null),
        unreadNotificationsProvider.overrideWith((ref) => const AsyncData(0)),
      ],
    );

    testWidgets('the passport and the photo section draw the same photo', (
      tester,
    ) async {
      installPhotoCache(PhotoCacheBehavior.serve);
      await pumpApp(
        tester,
        const ProfileScreen(),
        container: container(
          account(
            photo: const OwnPhoto.active(
              url: 'https://media.test/me.jpg?sig=1',
              version: 'm1',
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await settlePhotos(tester);

      expect(find.text('Profile photo'), findsOneWidget);
      expect(_pictures, findsNWidgets(2));
    });

    testWidgets('a member with no photo gets the section and initials', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const ProfileScreen(),
        container: container(account()),
      );
      await tester.pumpAndSettle();

      expect(find.text('Profile photo'), findsOneWidget);
      expect(find.text('Take a photo'), findsOneWidget);
      expect(_images, findsNothing);
    });
  });
}
