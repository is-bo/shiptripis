/// A real router and a mounted app for tests of the push coordinator.
///
/// The first-open prompt waits for a screen to be painted, so a coordinator
/// without a router on screen would never ask. These screens stand in for the
/// real ones and say what they are, so a test can read which one was painted
/// at the instant the system was asked.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

GoRouter pushTestRouter({String initialLocation = '/home'}) => GoRouter(
  initialLocation: initialLocation,
  routes: [
    for (final path in const [
      '/home',
      '/splash',
      '/auth/sign-in',
      '/deals/:id',
      '/guest/pay/:token',
    ])
      GoRoute(
        path: path,
        builder: (_, state) => _Marker(state.matchedLocation),
      ),
  ],
);

class _Marker extends StatelessWidget {
  const _Marker(this.location);

  final String location;

  @override
  Widget build(BuildContext context) =>
      Scaffold(body: Center(child: Text('screen:$location')));
}

/// Finds the stand-in for [location].
Finder screenAt(String location) => find.text('screen:$location');

/// Mounts [router] over [container] and draws the first frame.
Future<void> mountRouter(
  WidgetTester tester,
  ProviderContainer container,
  GoRouter router,
) => tester.pumpWidget(
  UncontrolledProviderScope(
    container: container,
    child: MaterialApp.router(routerConfig: router),
  ),
);
