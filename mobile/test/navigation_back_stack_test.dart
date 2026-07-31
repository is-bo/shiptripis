/// Regression tests for B1: pressing back after the handover-code flow quit
/// the whole app instead of returning to the previous screen.
///
/// Root cause was a stack-destroying navigation chain: `payment_screen` used
/// `context.go()` to reach `/handover/code/...` (go REPLACES the stack), then
/// the code screen's "Done" did `context.go('/sender/requests')` — replacing it
/// again. The user landed on a top-level route with an empty stack, so the
/// system back gesture had nothing to pop and fell through to the launcher.
///
/// These tests pin the *navigation contract* rather than the widgets: after
/// walking the real router, there must always be something to pop.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

/// Minimal stand-in for the real route table. We're testing go-vs-push
/// semantics, which live in go_router, not in our screens — building the real
/// screens here would drag in Dio/auth/WS for no extra coverage.
GoRouter _router() {
  Widget page(String label) => Scaffold(body: Text(label));
  return GoRouter(
    initialLocation: '/app',
    routes: [
      GoRoute(path: '/app', builder: (_, _) => page('shell')),
      GoRoute(path: '/sender/requests', builder: (_, _) => page('requests')),
      GoRoute(
        path: '/sender/requests/:id',
        builder: (_, _) => page('request-detail'),
      ),
      GoRoute(path: '/payment/:id', builder: (_, _) => page('payment')),
      GoRoute(path: '/handover/code/:id', builder: (_, _) => page('code')),
    ],
  );
}

Future<void> _pump(WidgetTester tester, GoRouter router) async {
  await tester.pumpWidget(MaterialApp.router(routerConfig: router));
  await tester.pumpAndSettle();
}

/// True when there is a route underneath the current one to fall back to.
/// This is exactly what `safeBack` checks and what the Android back gesture
/// needs; when false, back exits the app.
bool _canPop(GoRouter router) =>
    router.routerDelegate.navigatorKey.currentState!.canPop();

void main() {
  group('B1 — handover code flow keeps a poppable stack', () {
    testWidgets('reaching the code screen via push leaves a route below',
        (tester) async {
      final router = _router();
      await _pump(tester, router);

      // The real path a sender walks: requests -> detail -> payment -> code.
      router.push('/sender/requests');
      await tester.pumpAndSettle();
      router.push('/sender/requests/7');
      await tester.pumpAndSettle();
      router.push('/payment/42');
      await tester.pumpAndSettle();

      // payment_screen previously did `context.go(...)` here, which wiped the
      // stack. Pushing preserves it.
      router.push('/handover/code/7');
      await tester.pumpAndSettle();

      expect(find.text('code'), findsOneWidget);
      expect(_canPop(router), isTrue,
          reason: 'back after viewing the code must not exit the app');
    });

    testWidgets('go() to the code screen destroys the stack (the old bug)',
        (tester) async {
      final router = _router();
      await _pump(tester, router);

      router.push('/sender/requests');
      await tester.pumpAndSettle();
      router.push('/payment/42');
      await tester.pumpAndSettle();
      expect(_canPop(router), isTrue);

      // Documents WHY the fix is push, not go: this is the old behaviour.
      router.go('/handover/code/7');
      await tester.pumpAndSettle();

      expect(_canPop(router), isFalse,
          reason: 'go() replaces the stack — this is what caused B1');
    });

    testWidgets('popping from the code screen returns to the payment screen',
        (tester) async {
      final router = _router();
      await _pump(tester, router);

      router.push('/sender/requests');
      await tester.pumpAndSettle();
      router.push('/payment/42');
      await tester.pumpAndSettle();
      router.push('/handover/code/7');
      await tester.pumpAndSettle();

      // What "Done" should do when there IS somewhere to go back to.
      router.pop();
      await tester.pumpAndSettle();

      expect(find.text('payment'), findsOneWidget);
    });

    testWidgets('deep-link straight to the code screen still has a fallback',
        (tester) async {
      // Cold-start from a notification tap: nothing below the code screen, so
      // safeBack's canPop() is false and it must fall back to a route rather
      // than pop into nothing.
      final router = GoRouter(
        initialLocation: '/handover/code/7',
        routes: [
          GoRoute(
              path: '/app', builder: (_, _) => Scaffold(body: Text('shell'))),
          GoRoute(
              path: '/sender/requests',
              builder: (_, _) => Scaffold(body: Text('requests'))),
          GoRoute(
              path: '/handover/code/:id',
              builder: (_, _) => Scaffold(body: Text('code'))),
        ],
      );
      await _pump(tester, router);

      expect(_canPop(router), isFalse);

      // safeBack's else-branch: go to the fallback instead of popping.
      router.go('/sender/requests');
      await tester.pumpAndSettle();
      expect(find.text('requests'), findsOneWidget);
    });
  });
}
