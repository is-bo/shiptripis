/// Pumps a screen over a fake server that already answers everything Home
/// reads, with calm discovery answers a test then overrides route by route.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/time/clock.dart';
import 'package:shiptrip/domain/canonical_place.dart';

import 'fake_api.dart';
import 'harness.dart';

/// A backend that answers the reads under Home, and every discovery read with
/// an empty, valid answer. Override a route with `on` or `handle` afterwards.
FakeBackend discoveryBackend() => FakeBackend()
  ..emptyDiscovery()
  ..on('GET', '/api/me', FakeResponse(200, meFixture()))
  ..on('GET', '/api/deals', FakeResponse(200, <Object>[]))
  ..on('GET', '/api/matches', FakeResponse(200, <Object>[]))
  ..on('GET', '/api/journeys', FakeResponse(200, <Object>[]))
  ..on('GET', '/api/parcels', FakeResponse(200, <Object>[]))
  ..on(
    'GET',
    '/api/notifications/unread-count',
    FakeResponse(200, {'unread': 0}),
  );

/// A container over [backend] that does not retry a failed read, so an error
/// a test provokes is the state the test looks at, not a timer still ticking.
ProviderContainer discoveryContainer(
  FakeBackend backend, {
  DateTime Function()? now,
}) {
  final store = FakeTokenStore();
  return ProviderContainer(
    retry: (_, _) => null,
    overrides: [
      tokenStoreProvider.overrideWithValue(store),
      sessionCoreProvider.overrideWithValue(backend.session),
      fakeApiClient(backend),
      if (now != null) clockProvider.overrideWithValue(now),
    ],
  );
}

/// A route that renders a marker, so a test can see where a tap went.
GoRoute marker(String name, String path) => GoRoute(
  path: path,
  name: name,
  builder: (_, state) => Scaffold(
    body: Center(
      child: Text(
        'at $name ${state.pathParameters} ${state.uri.queryParameters}',
      ),
    ),
  ),
);

/// The destinations a discovery screen navigates to by name.
List<RouteBase> discoveryMarkers() => [
  marker(Routes.person, '/discover/people/:id'),
  marker(Routes.browseTrips, '/discover/trips'),
  marker(Routes.browseRequests, '/discover/requests'),
  marker(Routes.browsePeople, '/discover/people'),
  marker(Routes.requestDiscovery, '/requests/:id/discovery'),
  marker(Routes.requestCreate, '/requests/new'),
  marker(Routes.journeyCreate, '/journeys/new'),
  marker(Routes.journeyDetail, '/journeys/:id'),
  marker(Routes.profilePublic, '/profile/public'),
  marker(Routes.profileAlerts, '/profile/alerts'),
];

/// A place picker that answers at once with the next of [places], or with
/// nothing once they run out — the user backing out.
GoRoute stubPlacePicker(List<CanonicalPlace> places) => GoRoute(
  path: '/location/pick',
  name: Routes.locationPicker,
  builder: (_, _) =>
      _StubPicker(answer: () => places.isEmpty ? null : places.removeAt(0)),
);

class _StubPicker extends StatefulWidget {
  const _StubPicker({required this.answer});

  final CanonicalPlace? Function() answer;

  @override
  State<_StubPicker> createState() => _StubPickerState();
}

class _StubPickerState extends State<_StubPicker> {
  @override
  void initState() {
    super.initState();
    final place = widget.answer();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.pop(place);
    });
  }

  @override
  Widget build(BuildContext context) => const Scaffold();
}

/// A catalogue city as the picker returns it.
CanonicalPlace cityPlace(int id, String name, String country) => CanonicalPlace(
  id: id,
  countryCode: country,
  type: CanonicalPlaceType.locality,
  name: name,
  displayLabel: name,
  parentName: '',
  parentAdminLevel: '',
  matchingLocalityId: id,
);

/// Signs in over [backend] and pumps [screen] with the discovery markers.
Future<ProviderContainer> pumpDiscovery(
  WidgetTester tester,
  Widget screen,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
  DeviceProfile device = DeviceProfile.android,
  RoleContext role = RoleContext.sender,
  bool settle = true,
  double? keyboardInset,
  List<RouteBase> extraRoutes = const [],
  DateTime Function()? now,
}) async {
  final container = discoveryContainer(backend, now: now);
  addTearDown(container.dispose);
  await launchPumped(tester, container);
  container.read(roleContextProvider.notifier).set(role);
  await pumpApp(
    tester,
    screen,
    container: container,
    locale: locale,
    device: device,
    keyboardInset: keyboardInset,
    routed: true,
    extraRoutes: [...discoveryMarkers(), ...extraRoutes],
  );
  if (settle) await tester.pumpAndSettle();
  return container;
}
