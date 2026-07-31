import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:shiptrip/main.dart';

void main() {
  testWidgets('App boots', (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: ShipTripApp()));
    await tester.pump();
    expect(find.byType(WidgetsApp), findsOneWidget);

    // Booting the real app starts long-lived timers (WS reconnect backoff,
    // the match poll). They never settle, so the test framework's pending-timer
    // assertion fires at teardown unless we tear the tree down first — this is
    // a smoke test for "does it boot", not for timer lifecycle.
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(seconds: 1));
  });
}
