/// The regression suite for the bug this rebuild exists to kill.
///
/// The previous build floated a navigation pill over `extendBody: true`, so
/// every screen had to guess how much space the bar was stealing — and every
/// guess was wrong on some other phone. The fix is structural: a docked
/// `bottomNavigationBar` plus `AppScaffold`'s column layout, so content
/// physically cannot be laid out underneath the bar.
///
/// These tests assert the structural property directly — that the last piece
/// of content sits above the top of the bar — on every device profile that has
/// historically broken it. They are deliberately geometric rather than
/// golden-image: a golden tells you *something* changed, this tells you the
/// exact thing that must never change.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/navigation.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/layout/app_scaffold.dart';

import 'support/harness.dart';

/// A stand-in for the shell: a docked bar plus a screen inside it.
class _ShellHarness extends StatelessWidget {
  const _ShellHarness({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    // The shell hides the bar while the keyboard is up; the harness must
    // reproduce that or the keyboard assertions test a layout that never ships.
    final visible = MediaQuery.viewInsetsOf(context).bottom == 0;

    return NavigationInsetScope(
      inset: visible ? AppNavigationBar.occupiedHeight(context) : 0,
      barIsVisible: visible,
      child: Scaffold(
        resizeToAvoidBottomInset: true,
        body: child,
        bottomNavigationBar: visible
            ? AppNavigationBar(
                destinations: const [
                  NavDestination(
                    icon: Icons.home_outlined,
                    selectedIcon: Icons.home_rounded,
                    label: 'Home',
                  ),
                  NavDestination(
                    icon: Icons.inventory_2_outlined,
                    selectedIcon: Icons.inventory_2_rounded,
                    label: 'Deliveries',
                  ),
                  NavDestination(
                    icon: Icons.forum_outlined,
                    selectedIcon: Icons.forum_rounded,
                    label: 'Chat',
                  ),
                  NavDestination(
                    icon: Icons.person_outline_rounded,
                    selectedIcon: Icons.person_rounded,
                    label: 'Profile',
                  ),
                ],
                currentIndex: 0,
                onSelect: (_) {},
              )
            : null,
      ),
    );
  }
}

const _lastItemKey = Key('last-item');
const _footerKey = Key('footer-action');

Widget _longListScreen() => Builder(
  builder: (context) {
    return AppScaffold(
      body: ListView(
        padding: AppScrollPadding.page(context),
        children: [
          for (var i = 0; i < 40; i++)
            SizedBox(height: 48, child: Text('row $i')),
          const SizedBox(key: _lastItemKey, height: 48, child: Text('last')),
        ],
      ),
    );
  },
);

Widget _footerScreen() => Builder(
  builder: (context) => AppScaffold(
    body: ListView(
      padding: AppScrollPadding.pageWithFooter(context),
      children: [
        for (var i = 0; i < 40; i++)
          SizedBox(height: 48, child: Text('row $i')),
        const SizedBox(key: _lastItemKey, height: 48, child: Text('last')),
      ],
    ),
    footer: AppButton(key: _footerKey, label: 'Continue', onPressed: () {}),
  ),
);

Widget _formScreen() => Builder(
  builder: (context) => AppScaffold(
    body: ListView(
      padding: AppScrollPadding.pageWithFooter(context),
      children: [
        for (var i = 0; i < 10; i++)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: TextField(),
          ),
      ],
    ),
    footer: AppButton(key: _footerKey, label: 'Save', onPressed: () {}),
  ),
);

void main() {
  group('content never sits under the navigation bar', () {
    for (final device in DeviceProfile.all) {
      testWidgets('scrolled to the end on ${device.name}', (tester) async {
        await pumpApp(
          tester,
          _ShellHarness(child: _longListScreen()),
          device: device,
        );

        await tester.drag(find.byType(ListView), const Offset(0, -4000));
        await tester.pumpAndSettle();

        final barTop = tester.getTopLeft(find.byType(AppNavigationBar)).dy;
        final lastBottom = tester.getBottomLeft(find.byKey(_lastItemKey)).dy;

        expect(
          lastBottom,
          lessThanOrEqualTo(barTop),
          reason:
              'the final row must end above the bar on ${device.name}; '
              'it ended at $lastBottom with the bar starting at $barTop',
        );
      });

      testWidgets('pinned footer clears the bar on ${device.name}', (
        tester,
      ) async {
        await pumpApp(
          tester,
          _ShellHarness(child: _footerScreen()),
          device: device,
        );

        final barTop = tester.getTopLeft(find.byType(AppNavigationBar)).dy;
        final footerBottom = tester.getBottomLeft(find.byKey(_footerKey)).dy;

        expect(
          footerBottom,
          lessThanOrEqualTo(barTop + 0.5),
          reason: 'the footer action must sit above the bar on ${device.name}',
        );
      });
    }
  });

  group('keyboard', () {
    for (final device in [
      DeviceProfile.smallAndroid,
      DeviceProfile.iphone,
      DeviceProfile.landscape,
    ]) {
      testWidgets('footer lifts above the keyboard on ${device.name}', (
        tester,
      ) async {
        const keyboard = 280.0;
        await pumpApp(
          tester,
          _ShellHarness(child: _formScreen()),
          device: device,
          keyboardInset: keyboard,
        );

        // The bar is deliberately gone while typing, so the footer is the
        // thing that must clear the keyboard.
        expect(find.byType(AppNavigationBar), findsNothing);

        final footerBottom = tester.getBottomLeft(find.byKey(_footerKey)).dy;
        final keyboardTop = device.size.height - keyboard;

        expect(
          footerBottom,
          lessThanOrEqualTo(keyboardTop + 0.5),
          reason:
              'the footer must sit above the keyboard on ${device.name}; '
              'it ended at $footerBottom with the keyboard at $keyboardTop',
        );
      });
    }

    testWidgets('the published inset is zero while the keyboard is up', (
      tester,
    ) async {
      late double inset;
      await pumpApp(
        tester,
        _ShellHarness(
          child: Builder(
            builder: (context) {
              inset = NavigationInsetScope.of(context);
              return const SizedBox.expand();
            },
          ),
        ),
        keyboardInset: 300,
      );

      // Anything reading the inset — a floating map control, a scroll gutter —
      // must be told the bar is not there rather than reserving space for it.
      expect(inset, 0);
    });
  });

  group('navigation inset', () {
    testWidgets('includes the system gesture inset', (tester) async {
      late double inset;
      await pumpApp(
        tester,
        _ShellHarness(
          child: Builder(
            builder: (context) {
              inset = NavigationInsetScope.of(context);
              return const SizedBox.expand();
            },
          ),
        ),
        device: DeviceProfile.iphone,
      );

      // 60dp of bar plus the 34pt home indicator. A screen reading this number
      // gets the real occupied height, not the bar's content height.
      expect(inset, kNavBarContentHeight + 34);
    });

    testWidgets('is zero outside the shell', (tester) async {
      late double inset;
      await pumpApp(
        tester,
        Builder(
          builder: (context) {
            inset = NavigationInsetScope.of(context);
            return const SizedBox.expand();
          },
        ),
      );

      // A full-screen route pushed above the shell has no bar to avoid, and
      // padding for one would leave a dead strip at the bottom.
      expect(inset, 0);
    });
  });
}
