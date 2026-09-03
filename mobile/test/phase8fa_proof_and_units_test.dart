/// Phase 8F-A: the flight-proof upload, and the unit glyphs in a field.
///
/// Two separate device findings, both about the same thing — the app saying
/// something untrue about what just happened.
///
/// **Proof.** On the deployed environment every upload answered
/// `500`, and the app rendered "This isn't your fault. Try again in a moment."
/// The root cause was a storage grant, fixed on the server; what is tested
/// here is the client half — that a specific refusal now reads specifically,
/// that a transient one keeps the chosen file, and that a retry re-uses one
/// idempotency key so the reviewer does not end up with three copies.
///
/// **Units.** `€` and `kg` sat visibly above the digits they belonged to,
/// because a unit label was going through Material's `suffixIcon` slot — a
/// 48-point tap target that pins a bare `Padding` child to its top edge. The
/// geometry is asserted rather than eyeballed.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/design/components/forms.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _proofPath = '/api/journeys/7/legs/102/proof';

Future<ProviderContainer> _signedIn(
  WidgetTester tester,
  FakeBackend backend,
) async {
  backend.on('GET', '/api/me', FakeResponse(200, meFixture()));
  final container = containerFor(backend);
  addTearDown(container.dispose);
  await tester.runAsync(
    () => container.read(sessionProvider.notifier).restore(),
  );
  return container;
}

Map<String, dynamic> _proofResponse() => {
  'id': 900,
  'kind': 'boarding_pass',
  'content_type': 'image/png',
  'bytes': 2048,
  'status': 'pending',
  'reviewed_at': null,
  'rejection_reason': '',
};

/// A real file on disk, because `MultipartFile.fromFile` reads one.
///
/// Cleanup is best-effort: Windows keeps the handle open until the multipart
/// stream is collected, so a strict delete would fail the test on the teardown
/// rather than on anything it was asserting.
String _boardingPassFile(WidgetTester tester) {
  final dir = Directory.systemTemp.createTempSync('shiptrip-proof');
  addTearDown(() {
    try {
      dir.deleteSync(recursive: true);
    } on FileSystemException {
      // The OS will reclaim it; the assertion above already ran.
    }
  });
  final file = File('${dir.path}/pass.png')..writeAsBytesSync(_png);
  return file.path;
}

/// The smallest valid PNG, so the transport has real bytes to send.
final List<int> _png = [
  0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, // signature
  ...List<int>.filled(64, 0),
];

void main() {
  // -------------------------------------------------------------------------
  group('the proof upload contract', () {
    testWidgets('a successful upload sends kind, type and one key', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          _proofPath,
          (_) => FakeResponse(201, _proofResponse()),
        );
      final container = await _signedIn(tester, backend);
      final path = _boardingPassFile(tester);

      await tester.runAsync(
        () => container
            .read(journeyRepositoryProvider)
            .uploadProof(
              journeyId: 7,
              legId: 102,
              filePath: path,
              fileName: 'pass.png',
              kind: 'boarding_pass',
              contentType: 'image/png',
              idempotencyKey: 'device-abc-123',
            ),
      );

      final sent = backend.lastTo('POST', _proofPath);
      expect(sent, isNotNull);
      expect(sent!.body['kind'], 'boarding_pass');
      expect(sent.body['idempotency_key'], 'device-abc-123');
      expect(sent.body['photo__filename'], 'pass.png');
      // Stated, not left to the transport to guess from a gallery path that
      // may have no extension at all.
      expect(sent.body['photo__content_type'], 'image/png');
    });

    testWidgets('a retry re-uses the same key so nothing is duplicated', (
      tester,
    ) async {
      var attempt = 0;
      final backend = FakeBackend()
        ..handle('POST', _proofPath, (_) {
          attempt++;
          // First attempt: the storage layer is briefly unavailable. Second:
          // the server recognises the key and returns the existing row.
          return attempt == 1
              ? const FakeResponse(503, {
                  'code': 'proof_storage_unavailable',
                  'detail': 'Proof storage is temporarily unavailable.',
                })
              : FakeResponse(200, _proofResponse());
        });
      final container = await _signedIn(tester, backend);
      final path = _boardingPassFile(tester);
      final repository = container.read(journeyRepositoryProvider);

      Future<void> upload() => repository.uploadProof(
        journeyId: 7,
        legId: 102,
        filePath: path,
        fileName: 'pass.png',
        contentType: 'image/png',
        idempotencyKey: 'device-abc-123',
      );

      await tester.runAsync(() async {
        await expectLater(upload(), throwsA(isA<ApiException>()));
        await upload();
      });

      final sends = backend.to('POST', _proofPath);
      expect(sends, hasLength(2));
      expect(sends.map((r) => r.body['idempotency_key']), [
        'device-abc-123',
        'device-abc-123',
      ]);
    });

    testWidgets('a storage failure is retryable and keeps its code', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          _proofPath,
          (_) => const FakeResponse(503, {
            'code': 'proof_storage_unavailable',
            'detail': 'Proof storage is temporarily unavailable.',
          }),
        );
      final container = await _signedIn(tester, backend);
      final path = _boardingPassFile(tester);

      Object? thrown;
      await tester.runAsync(() async {
        try {
          await container
              .read(journeyRepositoryProvider)
              .uploadProof(
                journeyId: 7,
                legId: 102,
                filePath: path,
                fileName: 'pass.png',
                contentType: 'image/png',
              );
        } catch (error) {
          thrown = error;
        }
      });

      final failure = thrown as ApiException;
      expect(failure.code.raw, 'proof_storage_unavailable');
      // Retryable, so the screen offers Retry rather than a dead end.
      expect(failure.isRetryable, isTrue);
    });

    testWidgets('a file that is too large is the user\'s to fix, not ours', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          _proofPath,
          (_) => const FakeResponse(413, {
            'code': 'proof_file_too_large',
            'detail': 'File exceeds 10 MiB.',
          }),
        );
      final container = await _signedIn(tester, backend);
      final path = _boardingPassFile(tester);

      Object? thrown;
      await tester.runAsync(() async {
        try {
          await container
              .read(journeyRepositoryProvider)
              .uploadProof(
                journeyId: 7,
                legId: 102,
                filePath: path,
                fileName: 'pass.png',
                contentType: 'image/png',
              );
        } catch (error) {
          thrown = error;
        }
      });

      final failure = thrown as ApiException;
      expect(failure.code.raw, 'proof_file_too_large');
      // The bug this replaces: 413 fell through to `server`, so the app said
      // it was not the user's fault and to try again in a moment.
      expect(failure.kind, ApiFailureKind.validation);
      expect(failure.isRetryable, isFalse);
    });

    testWidgets('an unsupported type is a validation failure too', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          _proofPath,
          (_) => const FakeResponse(415, {
            'code': 'proof_media_type_unsupported',
            'detail': 'Only JPEG / PNG / WebP images are allowed.',
          }),
        );
      final container = await _signedIn(tester, backend);
      final path = _boardingPassFile(tester);

      Object? thrown;
      await tester.runAsync(() async {
        try {
          await container
              .read(journeyRepositoryProvider)
              .uploadProof(
                journeyId: 7,
                legId: 102,
                filePath: path,
                fileName: 'pass.png',
                contentType: 'image/png',
              );
        } catch (error) {
          thrown = error;
        }
      });

      final failure = thrown as ApiException;
      expect(failure.kind, ApiFailureKind.validation);
      expect(failure.code.raw, 'proof_media_type_unsupported');
    });
  });

  // -------------------------------------------------------------------------
  group('unit glyphs sit on the number they belong to', () {
    /// Renders one field with a unit and returns the two rectangles that have
    /// to line up: the entered digits, and the unit label.
    Future<({Rect input, Rect unit})> measure(
      WidgetTester tester, {
      required String unit,
      required String value,
      Locale locale = const Locale('en'),
      DeviceProfile device = DeviceProfile.android,
    }) async {
      final controller = TextEditingController(text: value);
      addTearDown(controller.dispose);

      await pumpApp(
        tester,
        Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: AppTextField(
              label: 'Capacity',
              controller: controller,
              unit: unit,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
            ),
          ),
        ),
        locale: locale,
        device: device,
      );
      await tester.pumpAndSettle();

      return (
        input: tester.getRect(find.text(value)),
        unit: tester.getRect(find.text(unit)),
      );
    }

    testWidgets('kg is centred on the digits, not floating above them', (
      tester,
    ) async {
      final rects = await measure(tester, unit: 'kg', value: '12.50');

      // The defect was ~13 logical pixels of drift, so a 2px tolerance is
      // tight enough to catch a regression and loose enough to survive a
      // font-metric difference between the two styles.
      expect(
        (rects.input.center.dy - rects.unit.center.dy).abs(),
        lessThan(2.0),
        reason: 'unit label drifted off the input line',
      );
    });

    testWidgets('€ is centred on the digits', (tester) async {
      final rects = await measure(tester, unit: '€', value: '45.00');

      expect(
        (rects.input.center.dy - rects.unit.center.dy).abs(),
        lessThan(2.0),
      );
    });

    testWidgets('cm is centred on the digits', (tester) async {
      final rects = await measure(tester, unit: 'cm', value: '30');

      expect(
        (rects.input.center.dy - rects.unit.center.dy).abs(),
        lessThan(2.0),
      );
    });

    testWidgets('the unit is visible on an empty, unfocused field', (
      tester,
    ) async {
      // Material's `suffix` slot fades to zero opacity until the field has
      // focus or content. A unit that disappears from an empty field is a
      // different bug, so the fix must not have introduced it.
      final controller = TextEditingController();
      addTearDown(controller.dispose);

      await pumpApp(
        tester,
        Scaffold(
          body: AppTextField(
            label: 'Capacity',
            controller: controller,
            unit: 'kg',
          ),
        ),
      );
      await tester.pumpAndSettle();

      final opacity = tester.widgetList<Opacity>(
        find.ancestor(of: find.text('kg'), matching: find.byType(Opacity)),
      );
      expect(find.text('kg'), findsOneWidget);
      expect(opacity.every((o) => o.opacity > 0), isTrue);
    });

    testWidgets('it holds in Arabic, on the leading edge', (tester) async {
      final rects = await measure(
        tester,
        unit: 'كغ',
        value: '12.50',
        locale: const Locale('ar'),
      );

      expect(
        (rects.input.center.dy - rects.unit.center.dy).abs(),
        lessThan(2.0),
      );
      // RTL puts the unit to the *left* of the number.
      expect(rects.unit.center.dx, lessThan(rects.input.center.dx));
    });

    testWidgets('it holds at the largest accessibility text size', (
      tester,
    ) async {
      final rects = await measure(
        tester,
        unit: 'kg',
        value: '12.50',
        device: DeviceProfile.largeText,
      );

      expect(
        (rects.input.center.dy - rects.unit.center.dy).abs(),
        lessThan(3.0),
      );
    });

    testWidgets('the euro field routes its glyph through the same slot', (
      tester,
    ) async {
      final controller = TextEditingController(text: '45.00');
      addTearDown(controller.dispose);

      await pumpApp(
        tester,
        Scaffold(
          body: AppAmountField(label: 'Reward', controller: controller),
        ),
      );
      await tester.pumpAndSettle();

      final input = tester.getRect(find.text('45.00'));
      final unit = tester.getRect(find.text('€'));
      expect((input.center.dy - unit.center.dy).abs(), lessThan(2.0));
    });
  });
}
