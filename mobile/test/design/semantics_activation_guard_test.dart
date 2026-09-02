/// A source-level guard for one specific accessibility defect.
///
/// `Semantics(button: true, …, child: ExcludeSemantics(child: InkWell(onTap:
/// …)))` reads correctly to a sighted reviewer and to a screen reader — and is
/// dead. `ExcludeSemantics` drops the descendant tap action, so the node is
/// announced as a button that cannot be pressed, which is worse than an
/// unlabelled control because it looks finished.
///
/// It was found in about a dozen places across the app in Phase 8C and fixed
/// app-wide in Phase 8E. Pumping every screen that contains one would be a slow
/// and incomplete way to keep it fixed, so this reads the source instead: any
/// `Semantics` that claims an interactive role must also carry the matching
/// action next to the claim.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Flags that promise the node can be operated.
const _interactiveFlags = ['button:', 'checked:', 'toggled:', 'slider:'];

/// Actions that make good on that promise.
const _actions = [
  'onTap:',
  'onIncrease:',
  'onDecrease:',
  'onLongPress:',
  'onDismiss:',
];

/// Opens a `Semantics(` node: `return Semantics(`, `child: Semantics(`,
/// `=> Semantics(` or a bare `Semantics(` in a list of children. Deliberately
/// not the `*Semantics(` wrappers, which are handled separately.
bool _opensSemantics(String trimmed) =>
    trimmed.endsWith('Semantics(') &&
    !trimmed.endsWith('ExcludeSemantics(') &&
    !trimmed.endsWith('MergeSemantics(') &&
    !trimmed.endsWith('BlockSemantics(');

void main() {
  test('no interactive Semantics node hides its own tap action', () {
    final root = Directory('lib');
    expect(root.existsSync(), isTrue, reason: 'run from the mobile/ package');

    final offenders = <String>[];
    final files =
        root
            .listSync(recursive: true)
            .whereType<File>()
            .where((file) => file.path.endsWith('.dart'))
            .toList()
          ..sort((a, b) => a.path.compareTo(b.path));

    for (final file in files) {
      final lines = file.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        if (!lines[i].contains('ExcludeSemantics(')) continue;
        // Walk back to the nearest `Semantics(` opener; anything further away
        // than this is a different node with widgets in between.
        for (var j = i - 1; j >= 0 && j >= i - 30; j--) {
          final trimmed = lines[j].trim();
          if (trimmed.contains('ExcludeSemantics(') ||
              trimmed.contains('MergeSemantics(') ||
              trimmed.contains('BlockSemantics(')) {
            break;
          }
          if (!_opensSemantics(trimmed)) continue;
          final block = lines.sublist(j, i + 1).join('\n');
          final claimsInteractive = _interactiveFlags.any(block.contains);
          final carriesAction = _actions.any(block.contains);
          if (claimsInteractive && !carriesAction) {
            offenders.add('${file.path}:${j + 1}');
          }
          break;
        }
      }
    }

    expect(
      offenders,
      isEmpty,
      reason:
          'These Semantics nodes announce an interactive control but carry no '
          'action, and the ExcludeSemantics beneath them discards the one on '
          'the widget underneath. Add the callback to the Semantics node too:\n'
          '${offenders.join('\n')}',
    );
  });
}
