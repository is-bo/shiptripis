/// The pre-Phase-5 passport concept restored with current V1 account facts.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/domain/rating.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

Account _account({
  String fullName = 'Amina Bouzid',
  bool verified = true,
  KycStatus kycStatus = KycStatus.verified,
  DateTime? joined,
}) => Account(
  id: 42,
  email: 'amina@example.com',
  fullName: fullName,
  phone: '',
  wilaya: '',
  role: AccountRole.both,
  preferredLanguage: CommunicationLanguage.french,
  isEmailVerified: verified,
  isPhoneVerified: false,
  isKycVerified: verified,
  kycStatus: kycStatus,
  dateJoined: joined,
);

ProviderContainer _container({
  required Account account,
  required int completedDeals,
  required List<Rating> ratings,
}) => ProviderContainer(
  overrides: [
    tokenStoreProvider.overrideWithValue(FakeTokenStore()),
    accountProvider.overrideWithValue(account),
    completedDealsCountProvider.overrideWith((ref) async => completedDeals),
    receivedRatingsProvider.overrideWith((ref) async => ratings),
    unreadNotificationsProvider.overrideWith((ref) async => 0),
  ],
);

void main() {
  test('completed activity uses the paginated server total', () async {
    final backend = FakeBackend()
      ..on(
        'GET',
        '/api/deals',
        const FakeResponse(200, {
          'count': 47,
          'next': null,
          'results': <Object>[],
        }),
      );
    final container = containerFor(backend);
    addTearDown(container.dispose);

    expect(await container.read(completedDealsCountProvider.future), 47);
  });

  testWidgets('populated passport uses current authoritative facts', (
    tester,
  ) async {
    final container = _container(
      account: _account(joined: DateTime(2026, 1, 4)),
      completedDeals: 2,
      ratings: const [
        Rating(id: 1, dealId: 1, score: 5, tags: [], isRevealed: true),
        Rating(id: 2, dealId: 2, score: 4, tags: [], isRevealed: true),
      ],
    );

    await pumpApp(tester, const ProfileScreen(), container: container);
    await tester.pumpAndSettle();

    expect(find.text('SHIPTRIP · MEMBER'), findsOneWidget);
    expect(find.text('Amina Bouzid'), findsOneWidget);
    expect(find.text('amina@example.com'), findsOneWidget);
    expect(find.text('Sending · Travelling'), findsOneWidget);
    expect(find.text('2'), findsOneWidget);
    expect(find.text('4.5 ★'), findsOneWidget);
    expect(find.textContaining('Français'), findsOneWidget);
    expect(find.textContaining('With ShipTrip since'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('partially populated passport remains explicit and stable', (
    tester,
  ) async {
    final container = _container(
      account: _account(
        fullName: '',
        verified: false,
        kycStatus: KycStatus.unknown,
      ),
      completedDeals: 0,
      ratings: const [],
    );

    await pumpApp(
      tester,
      const ProfileScreen(),
      container: container,
      device: DeviceProfile.smallAndroid,
    );
    await tester.pumpAndSettle();

    expect(find.text('amina@example.com'), findsWidgets);
    expect(find.text('Not started'), findsWidgets);
    expect(find.text('No ratings yet'), findsOneWidget);
    expect(find.textContaining('With ShipTrip since'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
