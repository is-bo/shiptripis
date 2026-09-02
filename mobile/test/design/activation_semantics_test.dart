/// Phase 8E: every announced control is an *operable* control.
///
/// `Semantics(button: true, …)` wrapped around `ExcludeSemantics` produces a
/// node a screen reader announces correctly and cannot activate — the tap
/// action lives on the `InkWell` underneath and `ExcludeSemantics` discards it
/// on the way up. Phase 8C fixed the location path; this covers the rest of the
/// app, control by control, by driving each one the way assistive technology
/// does rather than by synthesising a touch the semantics tree knows nothing
/// about.
library;

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/navigation.dart';
import 'package:shiptrip/design/components/sheets.dart';

import '../support/harness.dart';

/// The semantics node carrying [label], asserted to actually carry [action].
SemanticsNode _operable(
  WidgetTester tester,
  String label, {
  SemanticsAction action = SemanticsAction.tap,
}) {
  final node = tester.getSemantics(find.bySemanticsLabel(label).first);
  expect(
    node.getSemanticsData().hasAction(action),
    isTrue,
    reason: '"$label" is announced but carries no $action',
  );
  return node;
}

void _invoke(
  WidgetTester tester,
  SemanticsNode node, {
  SemanticsAction action = SemanticsAction.tap,
}) {
  tester.binding.performSemanticsAction(
    SemanticsActionEvent(
      type: action,
      nodeId: node.id,
      viewId: tester.view.viewId,
    ),
  );
}

void main() {
  testWidgets('a segmented choice option activates', (tester) async {
    final handle = tester.ensureSemantics();
    String? picked;
    await pumpApp(
      tester,
      Scaffold(
        body: AppSegmentedChoice<String>(
          options: const [
            AppChoice(value: 'flight', label: 'Flight'),
            AppChoice(value: 'drive', label: 'Drive'),
          ],
          selected: 'flight',
          onSelect: (value) => picked = value,
        ),
      ),
    );
    await tester.pumpAndSettle();

    _invoke(tester, _operable(tester, 'Drive'));
    await tester.pump();
    expect(picked, 'drive');
    handle.dispose();
  });

  testWidgets('a check tile toggles', (tester) async {
    final handle = tester.ensureSemantics();
    var value = false;
    await pumpApp(
      tester,
      StatefulBuilder(
        builder: (context, setState) => Scaffold(
          body: AppCheckTile(
            value: value,
            title: 'I accept the terms',
            onChanged: (next) => setState(() => value = next),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    _invoke(tester, _operable(tester, 'I accept the terms'));
    await tester.pumpAndSettle();
    expect(value, isTrue);
    handle.dispose();
  });

  testWidgets('a completed step can be returned to, a future step cannot', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    var returnedTo = -1;
    await pumpApp(
      tester,
      Scaffold(
        body: AppStepIndicator(
          steps: const ['Parcel', 'Route', 'Review'],
          currentIndex: 2,
          onStepTapped: (index) => returnedTo = index,
        ),
      ),
    );
    await tester.pumpAndSettle();

    _invoke(tester, _operable(tester, 'Parcel'));
    await tester.pump();
    expect(returnedTo, 0);

    // The step the user has not reached is not offered as a control at all —
    // the progress readout above already names where they are.
    expect(find.bySemanticsLabel('Review'), findsNothing);
    handle.dispose();
  });

  testWidgets('a bottom navigation destination activates', (tester) async {
    final handle = tester.ensureSemantics();
    var index = -1;
    await pumpApp(
      tester,
      Scaffold(
        bottomNavigationBar: AppNavigationBar(
          currentIndex: 0,
          onSelect: (next) => index = next,
          destinations: const [
            NavDestination(
              icon: Icons.home_outlined,
              selectedIcon: Icons.home_rounded,
              label: 'Home',
            ),
            NavDestination(
              icon: Icons.local_shipping_outlined,
              selectedIcon: Icons.local_shipping_rounded,
              label: 'Deliveries',
            ),
          ],
        ),
      ),
    );
    await tester.pumpAndSettle();

    _invoke(tester, _operable(tester, 'Deliveries'));
    await tester.pump();
    expect(index, 1);
    handle.dispose();
  });

  testWidgets('an option sheet row is named and selectable', (tester) async {
    final handle = tester.ensureSemantics();
    String? chosen;
    await pumpApp(
      tester,
      Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () async {
              chosen = await showAppSheet<String>(
                context,
                builder: (_) => const AppChoiceSheet<String>(
                  title: 'Reason',
                  selected: 'damaged',
                  options: [
                    AppSheetOption(value: 'damaged', label: 'Damaged'),
                    AppSheetOption(value: 'late', label: 'Late'),
                  ],
                ),
              );
            },
            child: const Text('open'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    // The row used to announce only "not selected": `ExcludeSemantics` ate the
    // ListTile title along with the tap.
    _invoke(tester, _operable(tester, 'Late'));
    await tester.pumpAndSettle();
    expect(chosen, 'late');
    handle.dispose();
  });
}
