/// Regression coverage for the shared [AppScaffold] system-inset contract.
///
/// Auth and onboarding routes intentionally have no AppBar, so the scaffold
/// must protect their first and last pixels itself. Keeping this at the shared
/// primitive level catches a device-specific regression before it is repeated
/// across every form and shell surface.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/layout/app_scaffold.dart';

import 'support/harness.dart';

const _topKey = Key('safe-area-top');
const _bottomKey = Key('safe-area-bottom');
const _leftKey = Key('safe-area-left');

Widget _surface() => AppScaffold(
  body: Stack(
    children: [
      const Align(
        alignment: Alignment.topCenter,
        child: SizedBox(key: _topKey, height: 2, width: 40),
      ),
      const Align(
        alignment: Alignment.bottomCenter,
        child: SizedBox(key: _bottomKey, height: 2, width: 40),
      ),
      const Align(
        alignment: Alignment.centerLeft,
        child: SizedBox(key: _leftKey, height: 2, width: 2),
      ),
    ],
  ),
);

void main() {
  for (final device in DeviceProfile.all) {
    testWidgets('clears system edges on ${device.name}', (tester) async {
      await pumpApp(tester, _surface(), device: device);

      final top = tester.getTopLeft(find.byKey(_topKey));
      final bottom = tester.getBottomLeft(find.byKey(_bottomKey));
      final left = tester.getTopLeft(find.byKey(_leftKey));

      expect(top.dy, greaterThanOrEqualTo(device.viewPadding.top));
      expect(
        bottom.dy,
        lessThanOrEqualTo(device.size.height - device.viewPadding.bottom),
      );
      expect(left.dx, greaterThanOrEqualTo(device.viewPadding.left));
    });
  }

  testWidgets('body remains above the keyboard while typing', (tester) async {
    const keyboard = 280.0;
    final device = DeviceProfile.androidGesture;
    await pumpApp(tester, _surface(), device: device, keyboardInset: keyboard);

    final bottom = tester.getBottomLeft(find.byKey(_bottomKey));
    expect(bottom.dy, lessThanOrEqualTo(device.size.height - keyboard));
  });
}
