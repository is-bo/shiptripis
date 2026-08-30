/// Shared SkeletonDetail responsive regression coverage.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/design/components/navigation.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/layout/app_scaffold.dart';

import 'support/harness.dart';

void main() {
  const shortLandscape = DeviceProfile(
    name: 'short landscape (844x240)',
    size: Size(844, 240),
    viewPadding: EdgeInsets.only(left: 47, right: 34),
  );

  for (final device in [...DeviceProfile.all, shortLandscape]) {
    testWidgets('detail skeleton fits or scrolls on ${device.name}', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const AppScaffold(
          topBar: AppTopBar(title: 'Loading'),
          body: Padding(padding: EdgeInsets.all(24), child: SkeletonDetail()),
          footer: AppButton(label: 'Continue', onPressed: null),
        ),
        device: device,
      );
      // SkeletonBox deliberately animates forever, so pump a frame rather
      // than waiting for pumpAndSettle.
      await tester.pump(const Duration(milliseconds: 100));

      expect(
        tester.takeException(),
        isNull,
        reason: 'SkeletonDetail overflowed on ${device.name}',
      );
    });
  }
}
