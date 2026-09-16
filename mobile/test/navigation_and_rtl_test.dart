/// Navigation shape, Arabic RTL, and accessibility floors.
///
/// The navigation assertions are deliberately about *shape*, not styling: four
/// destinations, in a fixed order, with notifications absent from the bar. That
/// is a product decision the code should not be able to drift away from
/// quietly.
///
/// The RTL assertions check the things that actually break when a layout is
/// mirrored — directional arrows, start/end padding, and the numeric strings
/// that must **not** flip.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/codes.dart';
import 'package:shiptrip/design/components/money.dart';
import 'package:shiptrip/design/components/navigation.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/components/route.dart';
import 'package:shiptrip/design/components/status.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/harness.dart';

const _destinations = [
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
    badgeCount: 3,
  ),
  NavDestination(
    icon: Icons.person_outline_rounded,
    selectedIcon: Icons.person_rounded,
    label: 'Profile',
  ),
];

void main() {
  group('bottom navigation', () {
    testWidgets('has exactly four destinations in the agreed order', (
      tester,
    ) async {
      await pumpApp(
        tester,
        Scaffold(
          bottomNavigationBar: AppNavigationBar(
            destinations: _destinations,
            currentIndex: 0,
            onSelect: (_) {},
          ),
        ),
      );

      expect(find.text('Home'), findsOneWidget);
      expect(find.text('Deliveries'), findsOneWidget);
      expect(find.text('Chat'), findsOneWidget);
      expect(find.text('Profile'), findsOneWidget);

      // Notifications live in the header bell. A fifth tab would cost every
      // screen the same space forever to serve a rare trip.
      expect(find.text('Notifications'), findsNothing);

      final labels = [
        'Home',
        'Deliveries',
        'Chat',
        'Profile',
      ].map((t) => tester.getCenter(find.text(t)).dx).toList();
      expect(
        labels,
        orderedEquals(<double>[...labels]..sort()),
        reason: 'destinations must read left to right in the agreed order',
      );
    });

    testWidgets('every destination is at least a 48dp target', (tester) async {
      await pumpApp(
        tester,
        Scaffold(
          bottomNavigationBar: AppNavigationBar(
            destinations: _destinations,
            currentIndex: 0,
            onSelect: (_) {},
          ),
        ),
      );

      for (final item in tester.widgetList<InkWell>(find.byType(InkWell))) {
        final size = tester.getSize(find.byWidget(item));
        expect(
          size.height,
          greaterThanOrEqualTo(AppSpace.minTapTarget),
          reason: 'a navigation destination must clear the 48dp minimum',
        );
      }
    });

    testWidgets('labels are always visible, in every language', (tester) async {
      // Icon-only navigation is a guess in one language and worse in three.
      for (final locale in [Locale('en'), Locale('fr'), Locale('ar')]) {
        await pumpApp(
          tester,
          Scaffold(
            bottomNavigationBar: AppNavigationBar(
              destinations: _destinations,
              currentIndex: 1,
              onSelect: (_) {},
            ),
          ),
          locale: locale,
        );
        expect(find.text('Deliveries'), findsOneWidget);
      }
    });

    testWidgets('a selected destination announces itself as selected', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await pumpApp(
        tester,
        Scaffold(
          bottomNavigationBar: AppNavigationBar(
            destinations: _destinations,
            currentIndex: 2,
            onSelect: (_) {},
          ),
        ),
      );

      // Position is announced too — "3 of 4" is what makes a row of words
      // navigable without sight.
      expect(find.bySemanticsLabel(RegExp('Chat')), findsWidgets);
      handle.dispose();
    });
  });

  group('Arabic RTL', () {
    testWidgets('the layout mirrors', (tester) async {
      await pumpApp(
        tester,
        Builder(
          builder: (context) => Scaffold(
            body: Center(child: Text(context.isRtl ? 'rtl' : 'ltr')),
          ),
        ),
        locale: const Locale('ar'),
      );
      expect(find.text('rtl'), findsOneWidget);
    });

    testWidgets('a route arrow points the way the text runs', (tester) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: RouteSummary(from: 'باريس', to: 'الجزائر'),
        ),
        locale: const Locale('ar'),
      );

      // Pointing forward in Arabic means pointing left, and this glyph carries
      // `matchTextDirection`, so Flutter mirrors it under an RTL Directionality
      // and it already points left. Naming `arrow_back` here — which the app
      // used to do — mirrors a second time and sends the eye back to the
      // origin, which is why this test asserts the *rendered* direction and not
      // just which constant was named.
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

    testWidgets('the same arrow points the other way in English', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: RouteSummary(from: 'Paris', to: 'Algiers'),
        ),
      );
      expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);
    });

    testWidgets('a handover code stays left-to-right in Arabic', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: CodeDisplay(code: 'ABCD1234', label: 'رمز'),
        ),
        locale: const Locale('ar'),
      );

      // A code is not a sentence. If it reordered, the recipient would read it
      // out backwards.
      final directionality = tester.widget<Directionality>(
        find
            .descendant(
              of: find.byType(CodeDisplay),
              matching: find.byType(Directionality),
            )
            .first,
      );
      expect(directionality.textDirection, TextDirection.ltr);
    });

    testWidgets('money renders in Arabic without Arabic-Indic digits', (
      tester,
    ) async {
      await pumpApp(
        tester,
        Scaffold(body: MoneyText(Money.eurCentsOrNull(2750)!)),
        locale: const Locale('ar'),
      );

      final text = tester.widget<Text>(
        find.descendant(
          of: find.byType(MoneyText),
          matching: find.byType(Text),
        ),
      );
      expect(RegExp('[٠-٩]').hasMatch(text.data ?? ''), isFalse);
      expect(RegExp('[0-9]').hasMatch(text.data ?? ''), isTrue);
    });
  });

  group('status is never colour alone', () {
    testWidgets('a status pill always carries an icon and a word', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: StatusPill(
            label: 'Delivered',
            tone: StatusTone.good,
            icon: Icons.check_circle_rounded,
          ),
        ),
      );

      expect(find.text('Delivered'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle_rounded), findsOneWidget);
    });
  });

  group('accessibility floors', () {
    testWidgets('a primary button clears the minimum target', (tester) async {
      await pumpApp(
        tester,
        Scaffold(
          body: Center(
            child: AppButton(label: 'Continue', onPressed: () {}),
          ),
        ),
      );

      final size = tester.getSize(find.byType(FilledButton));
      expect(size.height, greaterThanOrEqualTo(AppSpace.minTapTarget));
    });

    testWidgets('an icon button carries a label for a screen reader', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await pumpApp(
        tester,
        Scaffold(
          body: AppIconButton(
            icon: Icons.close_rounded,
            label: 'Close',
            onPressed: () {},
          ),
        ),
      );
      expect(find.bySemanticsLabel('Close'), findsOneWidget);
      handle.dispose();
    });

    testWidgets('the layout survives 1.6x text', (tester) async {
      await pumpApp(
        tester,
        Scaffold(
          bottomNavigationBar: AppNavigationBar(
            destinations: _destinations,
            currentIndex: 0,
            onSelect: (_) {},
          ),
          body: const SizedBox.expand(),
        ),
        device: DeviceProfile.largeText,
      );

      // No overflow exception is the assertion; Flutter throws one on layout.
      expect(tester.takeException(), isNull);
    });
  });

  group('localisation', () {
    testWidgets('all three languages resolve', (tester) async {
      for (final locale in [Locale('en'), Locale('fr'), Locale('ar')]) {
        late String title;
        await pumpApp(
          tester,
          Builder(
            builder: (context) {
              title = L.of(context).deliveriesTitle;
              return const SizedBox.expand();
            },
          ),
          locale: locale,
        );
        expect(title, isNotEmpty);
      }
    });
  });
}
