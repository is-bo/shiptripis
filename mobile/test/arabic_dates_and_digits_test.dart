// Wassla's Arabic is Algerian Arabic: the Maghrebi month names (جانفي, فيفري
// ... أوت) and Western digits, on every surface that prints a date or a number,
// Flutter's own pickers included.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_settings.dart';
import 'package:shiptrip/core/format/locale_formats.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

const _arabic = Locale('ar');
const _algerianMonths = [
  'جانفي',
  'فيفري',
  'مارس',
  'أفريل',
  'ماي',
  'جوان',
  'جويلية',
  'أوت',
  'سبتمبر',
  'أكتوبر',
  'نوفمبر',
  'ديسمبر',
];
const _mashriqMonths = [
  'يناير',
  'فبراير',
  'أبريل',
  'مايو',
  'يونيو',
  'يوليو',
  'أغسطس',
];
final _easternDigits = RegExp('[٠-٩۰-۹]');

void _expectAlgerian(String text) {
  expect(_easternDigits.hasMatch(text), isFalse, reason: text);
  for (final month in _mashriqMonths) {
    expect(text, isNot(contains(month)), reason: text);
  }
}

Iterable<String> _visibleText(WidgetTester tester) => tester
    .widgetList<Text>(find.byType(Text))
    .map((t) => t.data ?? t.textSpan?.toPlainText() ?? '');

Future<BuildContext> _pumpArabicApp(WidgetTester tester) async {
  late BuildContext captured;
  await tester.pumpWidget(
    MaterialApp(
      locale: _arabic,
      supportedLocales: supportedLocales,
      localizationsDelegates: appLocalizationsDelegates,
      home: Builder(
        builder: (context) {
          captured = context;
          return const Scaffold();
        },
      ),
    ),
  );
  return captured;
}

void main() {
  setUpAll(LocaleFormats.ensureInitialized);

  group('the app formatter', () {
    test('every month uses its Algerian name and Western digits', () {
      for (var month = 1; month <= 12; month++) {
        final when = DateTime(2026, month, 14, 9, 40);
        for (final text in [
          LocaleFormats.dayMonth(_arabic, when),
          LocaleFormats.fullDate(_arabic, when),
          LocaleFormats.monthYear(_arabic, when),
          LocaleFormats.preciseDateTime(_arabic, when),
        ]) {
          expect(text, contains(_algerianMonths[month - 1]));
          _expectAlgerian(text);
        }
      }
      expect(
        LocaleFormats.fullDate(_arabic, DateTime(2026, 8, 14)),
        '14 أوت 2026',
      );
    });

    test('times, money and counts keep Western digits', () {
      _expectAlgerian(LocaleFormats.time(_arabic, DateTime(2026, 8, 1, 21, 5)));
      expect(LocaleFormats.time(_arabic, DateTime(2026, 8, 1, 21, 5)), '21:05');
      expect(Money.eurCents(3750).format(_arabic), contains('37,50'));
      _expectAlgerian(Money.eurCents(123456).format(_arabic));
      _expectAlgerian(Money.minor(40500, 'DZD', 0).format(_arabic));
    });

    test('translated counts print Western digits', () async {
      final l = await L.delegate.load(_arabic);
      expect(l.findTravelersCount(12), '12 مسافرًا');
      _expectAlgerian(l.findTravelersCount(1250));
    });
  });

  group("Flutter's own widgets", () {
    testWidgets('MaterialLocalizations formats like the rest of the app', (
      tester,
    ) async {
      final context = await _pumpArabicApp(tester);
      final material = MaterialLocalizations.of(context);
      final when = DateTime(2026, 8, 14);
      for (final text in [
        material.formatFullDate(when),
        material.formatMediumDate(when),
        material.formatShortDate(when),
        material.formatMonthYear(when),
        material.formatShortMonthDay(when),
        material.formatCompactDate(when),
        material.formatYear(when),
        material.formatDecimal(1234567),
        material.formatTimeOfDay(const TimeOfDay(hour: 21, minute: 5)),
      ]) {
        _expectAlgerian(text);
      }
      expect(
        material.formatTimeOfDay(const TimeOfDay(hour: 21, minute: 5)),
        '21:05',
      );
      expect(material.formatFullDate(when), contains('أوت'));
    });

    testWidgets('the date picker shows Algerian months and Western digits', (
      tester,
    ) async {
      final context = await _pumpArabicApp(tester);
      showDatePicker(
        context: context,
        initialDate: DateTime(2026, 8, 14),
        firstDate: DateTime(2026),
        lastDate: DateTime(2027),
      );
      await tester.pumpAndSettle();

      final texts = _visibleText(tester).toList();
      expect(texts.any((t) => t.contains('أوت')), isTrue, reason: '$texts');
      expect(texts, contains('14'));
      texts.forEach(_expectAlgerian);
    });

    testWidgets('the time picker is 24-hour with Western digits', (
      tester,
    ) async {
      final context = await _pumpArabicApp(tester);
      showTimePicker(
        context: context,
        initialTime: const TimeOfDay(hour: 21, minute: 40),
      );
      await tester.pumpAndSettle();

      final texts = _visibleText(tester).toList();
      expect(texts, containsAll(['21', '40']));
      expect(texts, isNot(contains('ص')));
      texts.forEach(_expectAlgerian);
    });
  });
}
