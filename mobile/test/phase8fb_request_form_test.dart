/// Phase 8F-B: the posting form's validation, and the required item photo.
///
/// The device findings these cover, in the owner's words:
///
/// > A required field was left empty. The app allowed progression. Later it
/// > warned about the field and returned to that step. After the owner filled
/// > the field, the Next button would no longer progress.
///
/// > Pressing Post with dimensions missing returned the owner to the parcel
/// > step. But nothing clearly explained the problem.
///
/// Three defects compounded into that. The client treated dimensions as
/// optional while the server required them, so the form waved the sender past
/// a step the server would refuse. The refusal came back keyed to `length_cm`,
/// `width_cm` and `height_cm` — keys no widget on the screen rendered — so the
/// jump back to the parcel step said nothing at all. And [AppTextField] feeds
/// its server `errorText` straight into `TextFormField.validator`, so one
/// standing server error kept `Form.validate()` false while the only code that
/// cleared server errors sat behind that same gate: the Next button was dead
/// for the rest of the form's life, with no way out but to abandon it.
///
/// So these tests are about *recovery* rather than happy paths. Does the button
/// work the instant the field is fixed; is the reason ever invisible; can a
/// step be skipped. Plus the new rule — one photo of the actual item, required,
/// uploaded before the request exists so a failed upload can never leave a live
/// request with nothing to show.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/components/status.dart';
import 'package:shiptrip/design/theme.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/delivery_request.dart';
import 'package:shiptrip/features/requests/request_create_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';

const _stagePath = '/api/parcels/media';
const _createPath = '/api/parcels/delivery/v1';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/// The smallest thing that is really a JPEG, so `MultipartFile.fromFile` has
/// bytes to read and the transport is exercised rather than stubbed.
final _jpeg = <int>[0xFF, 0xD8, 0xFF, 0xE0, ...List<int>.filled(64, 0)];

/// A real file on disk. Cleanup is best-effort: Windows keeps the handle open
/// until the multipart stream is collected, so a strict delete would fail the
/// test on teardown rather than on anything it asserts.
String _photoFile([String name = 'item.jpg']) {
  final dir = Directory.systemTemp.createTempSync('shiptrip-item-photo');
  addTearDown(() {
    try {
      dir.deleteSync(recursive: true);
    } on FileSystemException {
      // The OS reclaims it; the assertions above have already run.
    }
  });
  // `Platform.pathSeparator`, not `/`: a mixed-separator path on Windows makes
  // `XFile.name` hand back a directory segment too, which would be the test
  // lying about what the app sends.
  final file = File('${dir.path}${Platform.pathSeparator}$name');
  return (file..writeAsBytesSync(_jpeg)).path;
}

Map<String, dynamic> _stagedMedia({int id = 501}) => {
  'id': id,
  'purpose': 'item_photo',
  'content_type': 'image/jpeg',
  'bytes': 2048,
  'created_at': '2026-09-04T09:00:00Z',
};

CanonicalPlace _place(int id, String name, String country) =>
    CanonicalPlace.fromJson({
      'id': id,
      'country_code': country,
      'place_type': 'locality',
      'name': name,
      'display_label': name,
      'parent_name': '',
      'matching_locality': {'id': id, 'name': name},
    });

final _paris = _place(101, 'Paris', 'FR');
final _algiers = _place(202, 'Algiers', 'DZ');

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

/// The form under test, on a router that can actually answer its pickers.
///
/// The screen reaches the canonical-place picker through a *named route*, so a
/// bare `MaterialApp` cannot drive it at all and every interesting step sits
/// behind step one. This stands a stub in for that route which pops a canned
/// place, which is what makes the rest of the form reachable from a test.
class _FormHarness {
  _FormHarness(this.backend, {this.picker});

  final FakeBackend backend;
  final ItemPhotoPicker? picker;

  /// Places the stub picker route hands back, in order.
  final places = <CanonicalPlace>[_paris, _algiers];

  late final ProviderContainer container;

  Future<void> pump(
    WidgetTester tester, {
    Locale locale = const Locale('en'),
  }) async {
    backend.on('GET', '/api/me', FakeResponse(200, meFixture()));
    final tokens = FakeTokenStore();
    container = ProviderContainer(
      overrides: [
        tokenStoreProvider.overrideWithValue(tokens),
        apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
        if (picker != null) itemPhotoPickerProvider.overrideWithValue(picker!),
      ],
    );
    addTearDown(container.dispose);
    await tester.runAsync(
      () => container.read(sessionProvider.notifier).restore(),
    );

    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(411, 869);
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp.router(
          locale: locale,
          supportedLocales: const [Locale('en'), Locale('fr'), Locale('ar')],
          localizationsDelegates: const [
            L.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          theme: buildAppTheme(brightness: Brightness.light, locale: locale),
          builder: (context, inner) => MediaQuery(
            data: MediaQuery.of(context).copyWith(
              size: const Size(411, 869),
              viewPadding: const EdgeInsets.only(top: 24),
              padding: const EdgeInsets.only(top: 24),
            ),
            child: inner ?? const SizedBox.shrink(),
          ),
          routerConfig: GoRouter(
            initialLocation: '/host/screen',
            routes: [
              GoRoute(
                path: '/host',
                builder: (_, _) => const Scaffold(body: SizedBox.shrink()),
                routes: [
                  GoRoute(
                    path: 'screen',
                    builder: (_, _) => const RequestCreateScreen(),
                  ),
                ],
              ),
              GoRoute(
                path: '/location/pick',
                name: Routes.locationPicker,
                builder: (_, _) => _StubPlacePicker(
                  onReady: () => places.isEmpty ? null : places.removeAt(0),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  L l(WidgetTester tester) =>
      L.of(tester.element(find.byType(RequestCreateScreen)));
}

/// Pops a canned place as soon as it is pushed.
class _StubPlacePicker extends StatefulWidget {
  const _StubPlacePicker({required this.onReady});

  final CanonicalPlace? Function() onReady;

  @override
  State<_StubPlacePicker> createState() => _StubPlacePickerState();
}

class _StubPlacePickerState extends State<_StubPlacePicker> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.pop(widget.onReady());
    });
  }

  @override
  Widget build(BuildContext context) => const Scaffold(body: SizedBox.shrink());
}

/// A picker that always hands back the same file, and records how it was asked.
ItemPhotoPicker _pickerReturning(String path, {List<ImageSource>? calls}) =>
    (source) async {
      calls?.add(source);
      return XFile(path, mimeType: 'image/jpeg', name: 'item.jpg');
    };

// ---------------------------------------------------------------------------
// Finders and assertions
// ---------------------------------------------------------------------------

Finder _button(String label) => find.widgetWithText(AppButton, label);

/// Every error string the user can currently read.
///
/// Assembled from the three places this design puts one — a text field's own
/// decoration, a select field's footnote, and a notice — because the original
/// defect was a form that knew something was wrong and rendered it nowhere.
List<String> _visibleErrors(WidgetTester tester) => [
  for (final field in tester.widgetList<TextField>(find.byType(TextField)))
    if (field.decoration?.errorText != null) field.decoration!.errorText!,
  for (final field in tester.widgetList<AppSelectField>(
    find.byType(AppSelectField),
  ))
    if (field.errorText != null) field.errorText!,
  for (final tile in tester.widgetList<AppCheckTile>(find.byType(AppCheckTile)))
    if (tile.errorText != null) tile.errorText!,
  for (final notice in tester.widgetList<InfoNotice>(find.byType(InfoNotice)))
    // Tone is what separates a complaint from a fact. The route step carries
    // a privacy notice that is neither wrong nor the user's to fix.
    if (notice.tone == StatusTone.bad) notice.message,
];

bool _showsError(WidgetTester tester, String message) =>
    _visibleErrors(tester).contains(message);

/// Scrolls [target] into the tree if it is not already there.
///
/// A `ListView` elements only what it lays out, so a field below the fold is
/// not merely invisible to the user — it is absent from the widget tree and
/// therefore from every finder. Anything asserted about the lower half of the
/// parcel step has to be scrolled to first.
Future<void> _reveal(WidgetTester tester, Finder target) async {
  if (target.evaluate().isNotEmpty) return;
  await tester.scrollUntilVisible(
    target,
    120,
    // Named rather than inferred: the page holds more than one Scrollable and
    // the default picks none of them.
    scrollable: find.byType(Scrollable).first,
    maxScrolls: 40,
  );
  await tester.pumpAndSettle();
}

/// Taps a photo control and waits for the work it starts to show up.
///
/// Deliberately not `pumpAndSettle`: while an upload is in flight the section
/// shows an indeterminate progress indicator, which never settles, so
/// `pumpAndSettle` would time out on a screen that is behaving correctly.
/// Picking also touches the filesystem and the network, and neither obeys the
/// pumped clock — hence the `runAsync` pauses between frames. [until] is a
/// question about what the user can see, so it is answered by the same tree
/// the assertions read.
Future<void> _tapPhotoAction(
  WidgetTester tester,
  Finder control, {
  required bool Function() until,
  int maxFrames = 200,
}) async {
  await tester.tap(control);
  for (var frame = 0; frame < maxFrames; frame++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 10)),
    );
    await tester.pump(const Duration(milliseconds: 16));
    if (until()) return;
  }
  fail('the photo action never reached the state the test was waiting for');
}

/// True when [finder] currently matches something.
bool _present(Finder finder) => finder.evaluate().isNotEmpty;

/// The text input inside the field captioned [label].
///
/// By caption rather than by index: a field's label is a sibling of its input
/// (this design system keeps labels above the border rather than floating in
/// it), so `widgetWithText` cannot reach the input and a positional finder
/// would silently move whenever the step is reordered.
Finder _input(String label) => find.descendant(
  of: find.ancestor(of: find.text(label), matching: find.byType(AppTextField)),
  matching: find.byType(TextField),
);

/// The select field carrying [label] — the tappable control, not its caption.
Finder _select(String label) =>
    find.ancestor(of: find.text(label), matching: find.byType(AppSelectField));

Future<void> _choosePlace(WidgetTester tester, String label) async {
  await tester.tap(_select(label));
  await tester.pumpAndSettle();
}

/// Walks the form from the route step to the parcel step.
Future<void> _completeRouteStep(
  WidgetTester tester,
  _FormHarness harness,
) async {
  final l = harness.l(tester);
  await _choosePlace(tester, l.requestPickupLocation);
  await _choosePlace(tester, l.requestDeliveryLocation);
  await tester.tap(_button(l.actionNext));
  await tester.pumpAndSettle();
}

void main() {
  // -------------------------------------------------------------------------
  group('a required field blocks its own step', () {
    testWidgets('an untouched form is not already shouting', (tester) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);

      expect(_visibleErrors(tester), isEmpty);
    });

    testWidgets('Next stays on the step and says what is missing', (
      tester,
    ) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      final l = harness.l(tester);

      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();

      // Still on the route step.
      expect(find.text(l.requestPickupLocation), findsOneWidget);
      expect(find.text(l.requestTitle), findsNothing);
      // And now saying so, beside the fields and in the footer.
      expect(_showsError(tester, l.validationRequired), isTrue);
      expect(find.text(l.formFixCountBeforeContinuing(2)), findsOneWidget);
    });

    testWidgets('the reason survives coming back to the step', (tester) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      final l = harness.l(tester);

      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();
      expect(_showsError(tester, l.validationRequired), isTrue);

      // A revealed step stays revealed. Finding it silent again on a second
      // look is how a sender ends up pressing a button that does nothing with
      // no idea what it wants.
      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();
      expect(_showsError(tester, l.validationRequired), isTrue);
    });

    testWidgets('Next works the moment the fields are filled', (tester) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      final l = harness.l(tester);

      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();
      expect(find.text(l.requestTitle), findsNothing);

      await _choosePlace(tester, l.requestPickupLocation);
      await _choosePlace(tester, l.requestDeliveryLocation);

      // One press. Not two, not "press it again now that it has re-rendered".
      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();

      expect(find.text(l.requestTitle), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  group('the parcel step', () {
    testWidgets('refuses to advance without the item photo, and says which '
        'fields are missing', (tester) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      expect(find.text(l.requestItemPhoto), findsOneWidget);
      expect(_visibleErrors(tester), isEmpty);

      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();

      // Still on the parcel step, with the photo named as the thing missing.
      expect(find.text(l.requestTitle), findsOneWidget);
      expect(_showsError(tester, l.requestItemPhotoRequired), isTrue);
    });

    testWidgets('empty dimensions are accepted and never block', (
      tester,
    ) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();

      // The three boxes are empty, and nothing complains about them. What is
      // complained about is the photo, the title, the weight — the things the
      // sender genuinely has to supply.
      expect(_showsError(tester, l.requestDimensionsPartialFix), isFalse);
      expect(_showsError(tester, l.requestItemPhotoRequired), isTrue);
    });

    testWidgets('a half-filled set is explained, both ways out named', (
      tester,
    ) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await _reveal(tester, find.text(l.requestLength));
      await tester.enterText(_input(l.requestLength), '30');
      await tester.pumpAndSettle();
      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();

      expect(_showsError(tester, l.requestDimensionsPartialFix), isTrue);

      // Clearing it is one of the two ways out, and it works.
      await _reveal(tester, find.text(l.requestLength));
      await tester.enterText(_input(l.requestLength), '');
      await tester.pumpAndSettle();
      expect(_showsError(tester, l.requestDimensionsPartialFix), isFalse);
    });

    testWidgets('optional fields say so in their own label', (tester) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      // Optionality is stated, not discovered by pressing Next and seeing what
      // happens.
      final dimensions = find.text(
        '${l.requestDimensions} · ${l.fieldOptional}',
      );
      await _reveal(tester, dimensions);
      expect(dimensions, findsOneWidget);

      final notes = find.text('${l.requestHandlingNotes} · ${l.fieldOptional}');
      await _reveal(tester, notes);
      expect(notes, findsOneWidget);
    });

    testWidgets('the weight unit is still kg, in its own slot', (tester) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      // 8F-A moved `kg` and `€` off the top edge of a 48-point icon slot.
      // Nothing here may put them back.
      await _reveal(tester, find.text(l.requestWeightUnit));
      expect(find.text(l.requestWeightUnit), findsOneWidget);
      await _reveal(tester, find.text('€'));
      expect(find.text('€'), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  group('the item photo', () {
    testWidgets('gallery: picking uploads it and shows it as ready', (
      tester,
    ) async {
      final calls = <ImageSource>[];
      final backend = FakeBackend()
        ..handle('POST', _stagePath, (_) => FakeResponse(201, _stagedMedia()));
      final harness = _FormHarness(
        backend,
        picker: _pickerReturning(_photoFile(), calls: calls),
      );
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await _tapPhotoAction(
        tester,
        _button(l.requestItemPhotoFromGallery),
        until: () => _present(find.text(l.requestItemPhotoReady)),
      );

      expect(calls, [ImageSource.gallery]);
      expect(backend.to('POST', _stagePath), hasLength(1));
      expect(find.text(l.requestItemPhotoReady), findsWidgets);
      // Replace and Remove appear only once there is something to act on.
      expect(_button(l.requestItemPhotoReplace), findsOneWidget);
      expect(_button(l.requestItemPhotoRemove), findsOneWidget);
    });

    testWidgets('camera: the same path, asked of the other source', (
      tester,
    ) async {
      final calls = <ImageSource>[];
      final backend = FakeBackend()
        ..handle('POST', _stagePath, (_) => FakeResponse(201, _stagedMedia()));
      final harness = _FormHarness(
        backend,
        picker: _pickerReturning(_photoFile(), calls: calls),
      );
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await _tapPhotoAction(
        tester,
        _button(l.requestItemPhotoTakePhoto),
        until: () => _present(find.text(l.requestItemPhotoReady)),
      );

      expect(calls, [ImageSource.camera]);
      expect(find.text(l.requestItemPhotoReady), findsWidgets);
    });

    testWidgets('removing it puts the requirement back', (tester) async {
      final backend = FakeBackend()
        ..handle('POST', _stagePath, (_) => FakeResponse(201, _stagedMedia()));
      final harness = _FormHarness(
        backend,
        picker: _pickerReturning(_photoFile()),
      );
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await _tapPhotoAction(
        tester,
        _button(l.requestItemPhotoFromGallery),
        until: () => _present(find.text(l.requestItemPhotoReady)),
      );
      expect(find.text(l.requestItemPhotoReady), findsWidgets);

      await tester.tap(_button(l.requestItemPhotoRemove));
      await tester.pumpAndSettle();

      expect(_button(l.requestItemPhotoFromGallery), findsOneWidget);
      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();
      expect(_showsError(tester, l.requestItemPhotoRequired), isTrue);
    });

    testWidgets('a failed upload keeps the file and offers Retry', (
      tester,
    ) async {
      var attempt = 0;
      final backend = FakeBackend()
        ..handle('POST', _stagePath, (_) {
          attempt++;
          return attempt == 1
              ? const FakeResponse(503, {
                  'code': 'parcel_photo_storage_unavailable',
                  'detail': 'Photo storage is temporarily unavailable.',
                })
              : FakeResponse(200, _stagedMedia());
        });
      final harness = _FormHarness(
        backend,
        picker: _pickerReturning(_photoFile()),
      );
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await _tapPhotoAction(
        tester,
        _button(l.requestItemPhotoFromGallery),
        until: () => _present(find.text(l.actionRetry)),
      );

      // The photo is still selected — nobody is being sent back to the gallery
      // for a picture they already took.
      expect(_button(l.requestItemPhotoReplace), findsOneWidget);
      // A retryable failure is shown in the waiting tone rather than the error
      // one: nothing is wrong with the photo, and telling the sender otherwise
      // would send them looking for a different picture.
      expect(find.text(l.requestItemPhotoStorageUnavailable), findsOneWidget);
      expect(
        _showsError(tester, l.requestItemPhotoStorageUnavailable),
        isFalse,
      );

      await _tapPhotoAction(
        tester,
        find.text(l.actionRetry),
        until: () => _present(find.text(l.requestItemPhotoReady)),
      );

      expect(find.text(l.requestItemPhotoReady), findsWidgets);
      // Both attempts carried one key, so the server has one row, not two.
      final sends = backend.to('POST', _stagePath);
      expect(sends, hasLength(2));
      expect(
        sends.first.body['idempotency_key'],
        sends.last.body['idempotency_key'],
      );
    });

    testWidgets('the upload states its content type and sends real bytes', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle('POST', _stagePath, (_) => FakeResponse(201, _stagedMedia()));
      final harness = _FormHarness(
        backend,
        picker: _pickerReturning(_photoFile()),
      );
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await _tapPhotoAction(
        tester,
        _button(l.requestItemPhotoFromGallery),
        until: () => _present(find.text(l.requestItemPhotoReady)),
      );

      final sent = backend.lastTo('POST', _stagePath)!;
      expect(sent.body['photo__filename'], 'item.jpg');
      // Stated rather than left to the transport to infer from a gallery path
      // that may carry no extension at all.
      expect(sent.body['photo__content_type'], 'image/jpeg');
      expect((sent.body['idempotency_key'] as String).isNotEmpty, isTrue);

      // Staging a photo creates no request. That ordering is what makes "no
      // live request without an image" structurally true rather than hopeful.
      expect(backend.to('POST', _createPath), isEmpty);
    });
  });

  // -------------------------------------------------------------------------
  group('a stale server error is superseded by an edit', () {
    test('a rejected field stops blocking as soon as it is changed', () {
      const map = FieldErrorMap({
        'title': ['Titles like this are not accepted.'],
      });

      expect(map.touchesAny(const ['title']), isTrue);

      final afterEdit = map.without(const ['title']);
      expect(afterEdit['title'], isNull);
      expect(afterEdit.isEmpty, isTrue);
    });

    test('correcting one field leaves the others rejected', () {
      const map = FieldErrorMap({
        'title': ['Not accepted.'],
        'actual_weight_kg': ['Too heavy for this corridor.'],
      });

      final afterWeightEdit = map.without(const ['actual_weight_kg']);

      expect(afterWeightEdit['actual_weight_kg'], isNull);
      // Correcting a weight says nothing about a title.
      expect(afterWeightEdit['title'], 'Not accepted.');
    });

    test('an untouched map is returned unchanged rather than rebuilt', () {
      const map = FieldErrorMap({
        'title': ['Not accepted.'],
      });
      expect(identical(map.without(const ['description']), map), isTrue);
    });
  });

  // -------------------------------------------------------------------------
  group('step navigation', () {
    testWidgets('tapping a future step does not skip its prerequisites', (
      tester,
    ) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      final l = harness.l(tester);

      await tester.tap(find.text(l.requestStepReview));
      await tester.pumpAndSettle();

      expect(find.text(l.requestPickupLocation), findsOneWidget);
      expect(find.text(l.requestProposedReward), findsNothing);
    });

    testWidgets('going back preserves what was typed', (tester) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await _reveal(tester, find.text(l.requestTitle));
      await tester.enterText(_input(l.requestTitle), 'Wedding photographs');
      await tester.pumpAndSettle();

      await tester.tap(_button(l.actionBack));
      await tester.pumpAndSettle();
      expect(find.text(l.requestPickupLocation), findsOneWidget);

      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();

      await _reveal(tester, find.text(l.requestTitle));
      expect(find.text('Wedding photographs'), findsOneWidget);
    });

    testWidgets('a completed step can be returned to from the indicator', (
      tester,
    ) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      await tester.tap(find.text(l.requestStepRoute));
      await tester.pumpAndSettle();

      expect(find.text(l.requestPickupLocation), findsOneWidget);
    });

    testWidgets('Post never submits data the device knows is incomplete', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          _createPath,
          (_) => const FakeResponse(201, <String, dynamic>{}),
        );
      final harness = _FormHarness(backend);
      await harness.pump(tester);
      final l = harness.l(tester);

      for (var i = 0; i < 5; i++) {
        await tester.tap(_button(l.actionNext));
        await tester.pumpAndSettle();
      }

      // Not one request left the device. Relying on a 400 to discover what the
      // form already knew is exactly what made Post feel like a trap.
      expect(backend.to('POST', _createPath), isEmpty);
      expect(_visibleErrors(tester), isNotEmpty);
    });
  });

  // -------------------------------------------------------------------------
  group('the wire contract', () {
    test('a draft carries the staged photo and omits empty dimensions', () {
      final draft = DeliveryRequestDraft(
        pickupPlaceId: 101,
        deliveryPlaceId: 202,
        readyWindowStart: DateTime.utc(2026, 9, 5, 10),
        readyWindowEnd: DateTime.utc(2026, 9, 5, 12),
        deadlineAt: DateTime.utc(2026, 9, 8),
        actualWeightKg: 2.5,
        declaredValueEurCents: 12500,
        senderProposedRewardEurCents: 3000,
        title: 'Documents',
        description: 'A sealed folder',
        category: ItemCategory.documents,
        itemPhotoMediaId: 501,
        acknowledgements: const SafetyAcknowledgements(
          descriptionIsAccurate: true,
          itemIsLegal: true,
          noProhibitedGoods: true,
          declaredValueIsAccurate: true,
          customsResponsibilitiesUnderstood: true,
        ),
      );

      final json = draft.toJson();
      expect(json['item_photo_media_id'], 501);
      // Absent, not null: the server accepts an omitted set, and the client has
      // no business inventing a measurement nobody took.
      expect(json.containsKey('length_cm'), isFalse);
      expect(json.containsKey('width_cm'), isFalse);
      expect(json.containsKey('height_cm'), isFalse);
      expect(json['actual_weight_kg'], '2.50');
    });

    test('all three dimensions travel together when they are given', () {
      final draft = DeliveryRequestDraft(
        pickupPlaceId: 101,
        deliveryPlaceId: 202,
        readyWindowStart: DateTime.utc(2026, 9, 5, 10),
        readyWindowEnd: DateTime.utc(2026, 9, 5, 12),
        deadlineAt: DateTime.utc(2026, 9, 8),
        actualWeightKg: 2.5,
        lengthCm: 30,
        widthCm: 20,
        heightCm: 10,
        declaredValueEurCents: 12500,
        senderProposedRewardEurCents: 3000,
        title: 'Documents',
        description: 'A sealed folder',
        category: ItemCategory.documents,
        itemPhotoMediaId: 501,
        acknowledgements: const SafetyAcknowledgements(
          descriptionIsAccurate: true,
          itemIsLegal: true,
          noProhibitedGoods: true,
          declaredValueIsAccurate: true,
          customsResponsibilitiesUnderstood: true,
        ),
      );

      final json = draft.toJson();
      expect(json['length_cm'], '30.00');
      expect(json['width_cm'], '20.00');
      expect(json['height_cm'], '10.00');
    });

    test('a served request names its item photo', () {
      final request = DeliveryRequest.fromJson({
        'id': 77,
        'sender_id': 42,
        'status': 'open',
        'schema_version': 3,
        'title': 'Documents',
        'description': 'A sealed folder',
        'handling_notes': '',
        'category': 'documents',
        'fragile': false,
        'item_photo_media_id': 501,
        'media': [
          _stagedMedia(),
          {..._stagedMedia(id: 502), 'purpose': 'attachment'},
        ],
      });

      expect(request.hasItemPhoto, isTrue);
      expect(request.itemPhotoMediaId, 501);
      expect(request.media.where((m) => m.isItemPhoto).map((m) => m.id), [501]);
    });

    test('a legacy row with no purpose is not promoted to the photo slot', () {
      final media = ParcelMedia.fromJson({
        'id': 9,
        'content_type': 'image/jpeg',
        'bytes': 10,
      });
      expect(media.purpose, ParcelMediaPurpose.unknown);
      expect(media.isItemPhoto, isFalse);
    });

    testWidgets('a photo URL is fetched, never assembled from a key', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/parcels/77/media/501/url',
          const FakeResponse(200, {
            'url': 'https://storage.invalid/signed?X-Amz-Expires=300',
            'expires_in': 300,
          }),
        );
      final harness = _FormHarness(backend);
      await harness.pump(tester);

      final url = await tester.runAsync(
        () => harness.container
            .read(requestRepositoryProvider)
            .photoUrl(requestId: 77, mediaId: 501),
      );

      expect(url, startsWith('https://storage.invalid/signed'));
    });

    testWidgets('a storage failure is retryable and keeps its code', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          _stagePath,
          (_) => const FakeResponse(503, {
            'code': 'parcel_photo_storage_unavailable',
            'detail': 'Photo storage is temporarily unavailable.',
          }),
        );
      final harness = _FormHarness(backend);
      await harness.pump(tester);

      Object? thrown;
      await tester.runAsync(() async {
        try {
          await harness.container
              .read(requestRepositoryProvider)
              .stageItemPhoto(
                filePath: _photoFile(),
                fileName: 'item.jpg',
                contentType: 'image/jpeg',
              );
        } catch (error) {
          thrown = error;
        }
      });

      final failure = thrown as ApiException;
      expect(failure.code.raw, 'parcel_photo_storage_unavailable');
      expect(failure.isRetryable, isTrue);
    });

    testWidgets('a refused media type is the user\'s to fix, not ours', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          _stagePath,
          (_) => const FakeResponse(415, {
            'code': 'parcel_photo_media_type_unsupported',
            'detail': 'Only JPEG / PNG / WebP images are allowed.',
          }),
        );
      final harness = _FormHarness(backend);
      await harness.pump(tester);

      Object? thrown;
      await tester.runAsync(() async {
        try {
          await harness.container
              .read(requestRepositoryProvider)
              .stageItemPhoto(
                filePath: _photoFile('item.pdf'),
                fileName: 'item.pdf',
                contentType: 'image/jpeg',
              );
        } catch (error) {
          thrown = error;
        }
      });

      final failure = thrown as ApiException;
      expect(failure.kind, ApiFailureKind.validation);
      // Not "try again in a moment": the fix is the user's, and it is specific.
      expect(failure.isRetryable, isFalse);
    });
  });

  // -------------------------------------------------------------------------
  group('accessibility and Arabic', () {
    testWidgets('every new string is translated in French and Arabic', (
      tester,
    ) async {
      for (final locale in const [Locale('fr'), Locale('ar')]) {
        final harness = _FormHarness(FakeBackend());
        await harness.pump(tester, locale: locale);
        final l = harness.l(tester);

        // A key that fell back to English would read identically to `en`, and
        // that is exactly what a missing translation looks like at runtime.
        expect(l.requestItemPhoto, isNot('Photo of the item'));
        expect(
          l.requestItemPhotoRequired,
          isNot('A photo of the item is required.'),
        );
        expect(l.fieldOptional, isNot('Optional'));
        expect(
          l.formFixBeforeContinuing,
          isNot('Fix the highlighted field before continuing.'),
        );
        expect(l.requestDimensionsOptionalHelp.isNotEmpty, isTrue);
      }
    });

    testWidgets('the form lays out right-to-left in Arabic', (tester) async {
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester, locale: const Locale('ar'));

      expect(
        Directionality.of(tester.element(find.byType(RequestCreateScreen))),
        TextDirection.rtl,
      );
    });

    testWidgets('the photo controls are real buttons to a screen reader', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      final backend = FakeBackend()
        ..handle('POST', _stagePath, (_) => FakeResponse(201, _stagedMedia()));
      final harness = _FormHarness(
        backend,
        picker: _pickerReturning(_photoFile()),
      );
      await harness.pump(tester);
      await _completeRouteStep(tester, harness);
      final l = harness.l(tester);

      // Announced *and* operable. A control a screen reader names but cannot
      // press is the defect Phase 8E went through the app to remove.
      final gallery = find.bySemanticsLabel(l.requestItemPhotoFromGallery);
      expect(gallery, findsWidgets);
      expect(
        tester
            .getSemantics(gallery.first)
            .getSemanticsData()
            .hasAction(SemanticsAction.tap),
        isTrue,
      );
      handle.dispose();
    });

    testWidgets('a blocked step puts its reason in a live region', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      final harness = _FormHarness(FakeBackend());
      await harness.pump(tester);
      final l = harness.l(tester);

      await tester.tap(_button(l.actionNext));
      await tester.pumpAndSettle();

      // `InfoNotice` is a live region, so the refusal is spoken rather than
      // only painted — the only feedback a screen-reader user gets from a
      // button that declines to advance.
      expect(find.byType(InfoNotice), findsWidgets);
      expect(
        find.bySemanticsLabel(l.formFixCountBeforeContinuing(2)),
        findsWidgets,
      );
      handle.dispose();
    });
  });
}
