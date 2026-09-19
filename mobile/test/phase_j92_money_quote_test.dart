import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/features/requests/request_create_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/harness.dart';

RequestQuoteInputs _inputs({
  int origin = 1,
  int destination = 2,
  double weight = 2,
  double? length,
  DateTime? deadline,
  int? reward = 3000,
}) => (
  pickupPlaceId: origin,
  deliveryPlaceId: destination,
  weightKg: weight,
  lengthCm: length,
  widthCm: null,
  heightCm: null,
  readyWindowEnd: DateTime.utc(2026, 10, 1),
  deadlineAt: deadline ?? DateTime.utc(2026, 10, 2),
  rewardCents: reward,
);

void main() {
  test('a quote is current only for every input sent to pricing', () {
    final quoted = _inputs();
    expect(requestQuoteIsCurrent(quoted, quoted), isTrue);
    expect(requestQuoteIsCurrent(quoted, _inputs(weight: 3)), isFalse);
    expect(requestQuoteIsCurrent(quoted, _inputs(origin: 4)), isFalse);
    expect(requestQuoteIsCurrent(quoted, _inputs(destination: 5)), isFalse);
    expect(requestQuoteIsCurrent(quoted, _inputs(length: 10)), isFalse);
    expect(
      requestQuoteIsCurrent(
        quoted,
        _inputs(deadline: DateTime.utc(2026, 10, 3)),
      ),
      isFalse,
    );
    expect(requestQuoteIsCurrent(quoted, _inputs(reward: 3500)), isFalse);
    expect(requestQuoteIsCurrent(quoted, null), isFalse);
  });

  test('only the newest response for the current inputs may apply', () {
    final a = _inputs(weight: 2);
    final b = _inputs(weight: 3);
    expect(
      requestQuoteResponseMayApply(
        responseSequence: 2,
        latestSequence: 2,
        requested: b,
        current: b,
      ),
      isTrue,
    );
    expect(
      requestQuoteResponseMayApply(
        responseSequence: 1,
        latestSequence: 2,
        requested: a,
        current: b,
      ),
      isFalse,
    );
    expect(
      requestQuoteResponseMayApply(
        responseSequence: 2,
        latestSequence: 2,
        requested: b,
        current: _inputs(weight: 4),
      ),
      isFalse,
    );
  });

  test('EUR cents parse exactly without rounding fractional cents', () {
    final controller = TextEditingController();
    addTearDown(controller.dispose);
    for (final entry in <String, int>{
      '12': 1200,
      '12.3': 1230,
      '12.30': 1230,
      '0.50': 50,
      '12,30': 1230,
      '0,5': 50,
    }.entries) {
      controller.text = entry.key;
      expect(AppAmountField.centsOf(controller), entry.value);
    }
    for (final invalid in ['12.345', '1.999', '0.001', '12,345', '1.2.3']) {
      controller.text = invalid;
      expect(AppAmountField.centsOf(controller), isNull);
    }
  });

  for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
    testWidgets(
      'fractional cents show localized validation in ${locale.languageCode}',
      (tester) async {
        final controller = TextEditingController();
        addTearDown(controller.dispose);
        await pumpApp(
          tester,
          StatefulBuilder(
            builder: (context, setState) => Scaffold(
              body: AppAmountField(
                label: 'Amount',
                controller: controller,
                onChanged: (_) => setState(() {}),
              ),
            ),
          ),
          locale: locale,
        );
        await tester.enterText(find.byType(TextFormField), '12.345');
        await tester.pump();
        final l = L.of(tester.element(find.byType(AppAmountField)));
        expect(find.text(l.validationMoneyPrecision), findsOneWidget);
      },
    );
  }
}
