/// Phase 8C: a labelled control is still an *operable* control.
///
/// `Semantics(button: true, label: ...)` wrapped around an `ExcludeSemantics`
/// produces a node a screen reader announces correctly and cannot activate:
/// the tap action lives on the `InkWell` underneath, and `ExcludeSemantics`
/// throws it away on the way up. The label survives, the button survives, and
/// double-tap does nothing — which is worse than an unlabelled control,
/// because it looks fixed.
library;

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/place.dart';
import 'package:shiptrip/domain/canonical_place.dart';

import '../support/harness.dart';

final _jijel = CanonicalPlace.fromJson(const {
  'id': 1801,
  'country_code': 'DZ',
  'place_type': 'locality',
  'name': 'Jijel',
  'display_label': 'Jijel · Jijel',
  'parent_name': 'Jijel',
  'matching_locality': {'id': 1801, 'name': 'Jijel'},
  'available_for_matching': true,
});

/// Activates the control the way assistive technology does — through the
/// semantics tree — rather than by synthesising a touch the tree knows
/// nothing about.
void activateByScreenReader(WidgetTester tester) {
  final node = tester.getSemantics(find.byType(InkWell));
  expect(
    node.getSemanticsData().hasAction(SemanticsAction.tap),
    isTrue,
    reason: 'the node is announced as a button but has no tap action',
  );
  tester.binding.performSemanticsAction(
    SemanticsActionEvent(
      type: SemanticsAction.tap,
      nodeId: node.id,
      viewId: tester.view.viewId,
    ),
  );
}

void main() {
  testWidgets('a place result row can be activated by a screen reader', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    var taps = 0;
    await pumpApp(
      tester,
      Scaffold(
        body: PlaceResultRow(place: _jijel, onTap: () => taps++),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.bySemanticsLabel('Jijel, Algeria'), findsOneWidget);
    activateByScreenReader(tester);
    await tester.pump();
    expect(taps, 1);
    handle.dispose();
  });

  testWidgets('a country choice can be activated by a screen reader', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    var taps = 0;
    await pumpApp(
      tester,
      Scaffold(
        body: CountryChoiceTile(
          code: 'DZ',
          name: 'Algeria',
          selected: false,
          onTap: () => taps++,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.bySemanticsLabel('Algeria'), findsOneWidget);
    activateByScreenReader(tester);
    await tester.pump();
    expect(taps, 1);
    handle.dispose();
  });

  testWidgets('a select field can be activated by a screen reader', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    var taps = 0;
    await pumpApp(
      tester,
      Scaffold(
        body: AppSelectField(
          label: 'Pickup place',
          placeholder: 'Select',
          onTap: () => taps++,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.bySemanticsLabel('Pickup place'), findsWidgets);
    activateByScreenReader(tester);
    await tester.pump();
    expect(taps, 1);
    handle.dispose();
  });
}
