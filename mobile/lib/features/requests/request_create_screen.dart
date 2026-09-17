/// Posting a delivery request.
///
/// Four steps, in the order a sender actually thinks: where it goes, what it
/// is, when it has to happen, and only then what they are willing to pay. Put
/// the money first and every other answer gets bent to fit it.
///
/// **There is no price on this screen and there cannot be one.** Pricing needs
/// a journey to price against, and none exists yet — the pre-creation quote
/// endpoint was retired and now answers 410. So the last field is a *proposal*,
/// labelled as a starting point, and the real numbers appear in discovery
/// where a candidate traveller gives them meaning.
///
/// ## Validation, and why it is written this way (Phase 8F-B)
///
/// Device QA found a four-step form that could trap the person filling it in.
/// Three separate defects compounded:
///
/// 1. **The client and the server disagreed about what was required.** Parcel
///    dimensions were optional here and mandatory there, so a sender who left
///    them blank was waved through three steps and refused at the end.
/// 2. **The refusal was invisible.** The server answers a missing set with
///    `length_cm`/`width_cm`/`height_cm`, and no input on this screen was
///    bound to those keys. The form jumped back to the parcel step and said
///    nothing at all.
/// 3. **Correcting the field did not help.** [AppTextField] hands its
///    `errorText` to `TextFormField.validator`, so a standing server error
///    kept `Form.validate()` false; step validity was gated on `validate()`;
///    and the map of server errors was only ever cleared inside `_submit`,
///    which the gate made unreachable. The Next button was dead for the rest
///    of the form's life, with no way out but to abandon it.
///
/// The repair is structural rather than another `setState`:
///
/// * **This screen owns its validation.** There is no `Form` and no
///   `GlobalKey<FormState>`; every message shown is computed in
///   [_localProblems] or read from [_errors] and passed down as `errorText`.
///   One source of truth, and no widget-tree state that can go stale.
/// * **A server error is superseded the moment its field is edited.** A
///   verdict on a value that no longer exists is not a verdict; see
///   [FieldErrorMap.without].
/// * **A step is validated when the user tries to leave it**, and the first
///   invalid field is scrolled to and focused. Nothing is deferred to Post.
/// * **Post cannot bounce silently.** Every step is re-checked locally before
///   submitting, and a server field error moves to the owning step *and* says
///   so, in a notice, next to the marked field.
library;

import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:dio/dio.dart' show CancelToken;
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/place.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/delivery_request.dart';
import '../../domain/canonical_place.dart';
import '../../domain/location.dart';
import '../../domain/pricing.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../location/preferred_point_field.dart';

/// The smallest and largest parcel the V1 contract accepts, in kilograms.
/// Enforced here only so an obvious typo never becomes a round trip; the
/// server remains the authority.
const _minWeightKg = 0.01;
const _maxWeightKg = 100.0;

const _maxTitleLength = 160;
const _maxDescriptionLength = 2000;

/// The server's own ceiling (`MAX_UPLOAD_BYTES`). Checked here as well so a
/// 12 MB camera original is refused before it is pushed up a mobile uplink.
const _maxPhotoBytes = 10 * 1024 * 1024;

const _allowedPhotoTypes = {'image/jpeg', 'image/png', 'image/webp'};

/// Long edge and JPEG quality for a picked image.
///
/// A modern phone camera produces something like 4000×3000 and 6 MB. None of
/// that survives being looked at on a 400-point-wide card, and all of it has
/// to cross a connection this corridor cannot rely on. `image_picker` does the
/// resize in native code before the bytes ever reach Dart.
const _photoMaxEdge = 2048.0;
const _photoQuality = 88;

/// Opens the device's photo picker.
typedef ItemPhotoPicker = Future<XFile?> Function(ImageSource source);

/// The picker, behind a provider.
///
/// Two reasons rather than one. It keeps the resize policy in a single place
/// instead of at each call site, and it is the seam a widget test overrides —
/// there is no camera in a test runner, and a required photo whose only code
/// path is unreachable under test is a requirement nobody is checking.
final itemPhotoPickerProvider = Provider<ItemPhotoPicker>((ref) {
  final picker = ImagePicker();
  return (source) => picker.pickImage(
    source: source,
    maxWidth: _photoMaxEdge,
    maxHeight: _photoMaxEdge,
    imageQuality: _photoQuality,
  );
});

/// Pricing inputs a widget test can start the form with.
///
/// Reaching the pricing step through the UI means driving date and time dials
/// three times over, which tests the pickers rather than the price. This opens
/// the real screen on its last step with the inputs a quote needs, so the
/// quote refresh, the stale-response guard and the totals card are exercised
/// exactly as they run on a phone (J6.3). Never used by the app.
@visibleForTesting
class RequestCreatePricingSeed {
  const RequestCreatePricingSeed({
    required this.pickup,
    required this.delivery,
    required this.weightKg,
    required this.readyStart,
    required this.readyEnd,
    required this.deadline,
  });

  final CanonicalPlace pickup;
  final CanonicalPlace delivery;
  final String weightKg;
  final DateTime readyStart;
  final DateTime readyEnd;
  final DateTime deadline;
}

class RequestCreateScreen extends ConsumerStatefulWidget {
  const RequestCreateScreen({super.key, this.debugPricingSeed});

  /// Test-only. See [RequestCreatePricingSeed].
  @visibleForTesting
  final RequestCreatePricingSeed? debugPricingSeed;

  @override
  ConsumerState<RequestCreateScreen> createState() =>
      _RequestCreateScreenState();
}

/// What has happened to the required item photo so far.
enum _PhotoState { empty, uploading, ready, failed }

class _RequestCreateScreenState extends ConsumerState<RequestCreateScreen> {
  /// Every server field key this form has an input for. Anything outside it is
  /// surfaced as a form-level notice rather than silently dropped.
  ///
  /// Claiming a key is a promise that some widget renders it. `length_cm` and
  /// friends were claimed here while nothing displayed them, which is what
  /// turned a server refusal into a silent jump between steps — so the promise
  /// is asserted in [initState] rather than remembered.
  static const _claimedFields = {
    'pickup_location_id',
    'delivery_location_id',
    'pickup_place_id',
    'delivery_place_id',
    'ready_window_start',
    'ready_window_end',
    'deadline_at',
    'actual_weight_kg',
    'dimensions',
    'length_cm',
    'width_cm',
    'height_cm',
    'declared_value_eur_cents',
    'sender_proposed_reward_eur_cents',
    'title',
    'description',
    'category',
    'handling_notes',
    'fragile',
    'item_photo_media_id',
    'target_traveler_id',
    'description_is_accurate',
    'item_is_legal',
    'no_prohibited_goods',
    'declared_value_is_accurate',
    'customs_responsibilities_understood',
  };

  /// Which step owns which field, in the order the fields appear on screen.
  ///
  /// Read in both directions: to decide where a server error belongs, and to
  /// decide which invalid field to scroll to first. Keeping one ordered list
  /// rather than two is what stops the two answers drifting apart.
  static const _fieldsByStep = <int, List<String>>{
    0: [
      'pickup_place_id',
      'pickup_location_id',
      'delivery_place_id',
      'delivery_location_id',
      'target_traveler_id',
    ],
    1: [
      'item_photo_media_id',
      'title',
      'description',
      'category',
      'actual_weight_kg',
      'dimensions',
      'length_cm',
      'width_cm',
      'height_cm',
      'declared_value_eur_cents',
      'fragile',
      'handling_notes',
    ],
    2: ['ready_window_start', 'ready_window_end', 'deadline_at'],
    3: [
      'description_is_accurate',
      'item_is_legal',
      'no_prohibited_goods',
      'declared_value_is_accurate',
      'customs_responsibilities_understood',
      'sender_proposed_reward_eur_cents',
    ],
  };

  static const _lastStep = 3;

  final _title = TextEditingController();
  final _description = TextEditingController();
  final _weight = TextEditingController();
  final _length = TextEditingController();
  final _width = TextEditingController();
  final _height = TextEditingController();
  final _declaredValue = TextEditingController();
  final _handlingNotes = TextEditingController();
  final _reward = TextEditingController();

  /// One anchor per field that can carry an error, so an invalid field can be
  /// scrolled into view rather than merely coloured red somewhere off-screen.
  final _anchors = <String, GlobalKey>{};
  final _focusNodes = <String, FocusNode>{};

  CanonicalPlace? _pickup;
  CanonicalPlace? _delivery;
  AppLocation? _pickupPreferred;
  AppLocation? _deliveryPreferred;
  ItemCategory? _category;
  bool _fragile = false;

  DateTime? _readyStart;
  DateTime? _readyEnd;
  DateTime? _deadline;

  bool _ackDescription = false;
  bool _ackLegal = false;
  bool _ackProhibited = false;
  bool _ackValue = false;
  bool _ackCustoms = false;

  // ---- the required item photo ---------------------------------------------

  /// The file as picked. Kept across a failed upload so a storage hiccup never
  /// sends the sender back to the gallery for a photo they already chose.
  XFile? _photoFile;
  String? _photoMime;

  /// Identifies the *file*, not the attempt. Regenerated only when a different
  /// image is chosen, so Retry re-attaches to the row the first attempt may
  /// already have written instead of leaving a duplicate behind.
  String? _photoIdempotencyKey;

  /// The staged media id the create call will consume. Non-null exactly when
  /// the photo requirement is locally satisfied.
  int? _photoMediaId;

  _PhotoState _photoState = _PhotoState.empty;
  double _photoProgress = 0;

  /// A client-side refusal (too big, wrong type) — not a server one.
  String? _photoLocalError;
  ApiException? _photoFailure;

  int _step = 0;
  bool _busy = false;

  /// Steps whose problems should be visible. A step joins this set once the
  /// user has tried to leave it, or once the server has refused something on
  /// it — and never leaves, so walking back to a step still shows what is
  /// wrong with it.
  final _revealed = <int>{};

  /// True when the last submission was refused with a field error, so the
  /// jump back to the owning step can explain itself instead of just
  /// happening.
  bool _bouncedBySubmit = false;

  FieldErrorMap _errors = const FieldErrorMap.empty();

  PostingPricingQuote? _pricingQuote;
  bool _pricingLoading = false;
  String? _pricingError;
  Timer? _rewardDebounceTimer;

  /// Which request is the latest. A response from any earlier one is dropped,
  /// so a slow quote for +€5 can never land after a quick one for no Boost and
  /// put the wrong total on screen (J6.3).
  int _quoteSeq = 0;
  CancelToken? _quoteCancel;

  /// The reward and Boost [_pricingQuote] was priced for. While the form holds
  /// anything else, its totals are not this form's totals.
  int? _quotedRewardCents;
  int _quotedBoostCents = 0;
  int _chosenBoostCents = 0;
  int? _chosenDepositCents;

  @override
  void initState() {
    super.initState();
    // Suppressing a key from the catch-all notice is only safe if some step
    // owns it, because owning it is what puts it on screen and what decides
    // where a refusal sends the user. An unowned claim is a silent rejection
    // waiting to happen, so it fails here in debug rather than on a phone.
    assert(() {
      final owned = {for (final fields in _fieldsByStep.values) ...fields};
      final orphans = _claimedFields.difference(owned);
      if (orphans.isEmpty) return true;
      throw StateError(
        'These server fields are claimed but no step renders them: '
        '${orphans.toList()..sort()}',
      );
    }());
    final seed = widget.debugPricingSeed;
    if (seed != null) {
      _pickup = seed.pickup;
      _delivery = seed.delivery;
      _weight.text = seed.weightKg;
      _readyStart = seed.readyStart;
      _readyEnd = seed.readyEnd;
      _deadline = seed.deadline;
      _step = _lastStep;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _fetchPricingQuote();
      });
    }
  }

  @override
  void dispose() {
    _rewardDebounceTimer?.cancel();
    _quoteCancel?.cancel();
    _title.dispose();
    _description.dispose();
    _weight.dispose();
    _length.dispose();
    _width.dispose();
    _height.dispose();
    _declaredValue.dispose();
    _handlingNotes.dispose();
    _reward.dispose();
    for (final node in _focusNodes.values) {
      node.dispose();
    }
    super.dispose();
  }

  GlobalKey _anchor(String field) => _anchors.putIfAbsent(field, GlobalKey.new);

  FocusNode _focus(String field) =>
      _focusNodes.putIfAbsent(field, FocusNode.new);

  // -------------------------------------------------------------------------
  // Local validation
  //
  // Every rule the device can decide for itself lives here, keyed by the same
  // field names the server uses. Anything with a business meaning — whether a
  // corridor is servable, whether a place is matchable — stays the server's
  // call and arrives through [FieldErrorMap].
  // -------------------------------------------------------------------------

  bool get _dimensionsPartial {
    final filled = [
      _length,
      _width,
      _height,
    ].where((c) => c.text.trim().isNotEmpty).length;
    return filled != 0 && filled != 3;
  }

  bool get _allAcknowledged =>
      _ackDescription &&
      _ackLegal &&
      _ackProhibited &&
      _ackValue &&
      _ackCustoms;

  String? _requiredText(L l, TextEditingController controller, int maxLength) {
    final value = controller.text.trim();
    if (value.isEmpty) return l.validationRequired;
    if (value.characters.length > maxLength) {
      return l.validationTooLong(maxLength);
    }
    return null;
  }

  String? _weightProblem(L l) {
    final raw = _weight.text.trim();
    if (raw.isEmpty) return l.validationRequired;
    final kg = parseDecimalInput(raw);
    if (kg == null) return l.validationNumberInvalid;
    if (kg <= 0) return l.validationMustBePositive;
    if (kg < _minWeightKg || kg > _maxWeightKg) {
      return l.validationWeightRange(
        _minWeightKg.toStringAsFixed(2),
        _maxWeightKg.toStringAsFixed(0),
      );
    }
    return null;
  }

  /// A single dimension's *shape*. Emptiness is fine — the group rule below
  /// decides whether an empty box is a problem.
  String? _dimensionShape(L l, TextEditingController controller) {
    final raw = controller.text.trim();
    if (raw.isEmpty) return null;
    final value = parseDecimalInput(raw);
    if (value == null) return l.validationNumberInvalid;
    return value > 0 ? null : l.validationMustBePositive;
  }

  String? _amountProblem(L l, TextEditingController controller) {
    if (controller.text.trim().isEmpty) return l.validationRequired;
    final cents = AppAmountField.centsOf(controller);
    return (cents == null || cents <= 0) ? l.validationMustBePositive : null;
  }

  /// Everything wrong with [step] right now, keyed by server field name.
  ///
  /// Pure: it reads controllers and state and nothing else. That is what
  /// makes "the button works the instant the field is fixed" true rather than
  /// hopeful — there is no cached verdict anywhere to go stale.
  Map<String, String> _localProblems(L l, int step) {
    final problems = <String, String>{};
    switch (step) {
      case 0:
        if (_pickup == null) problems['pickup_place_id'] = l.validationRequired;
        if (_delivery == null) {
          problems['delivery_place_id'] = l.validationRequired;
        } else if (_pickup != null && _pickup!.id == _delivery!.id) {
          problems['delivery_place_id'] = l.validationSelectOne;
        }
      case 1:
        if (_photoMediaId == null) {
          problems['item_photo_media_id'] = switch (_photoState) {
            _PhotoState.uploading => l.requestItemPhotoUploading,
            _PhotoState.failed => l.requestItemPhotoUploadFailed,
            _ => _photoLocalError ?? l.requestItemPhotoRequired,
          };
        }
        final title = _requiredText(l, _title, _maxTitleLength);
        if (title != null) problems['title'] = title;
        final description = _requiredText(
          l,
          _description,
          _maxDescriptionLength,
        );
        if (description != null) problems['description'] = description;
        if (_category == null) problems['category'] = l.validationSelectOne;
        final weight = _weightProblem(l);
        if (weight != null) problems['actual_weight_kg'] = weight;

        // Dimensions are optional, so the only thing that can be wrong with
        // them is an unusable number or a half-filled set.
        for (final (field, controller) in <(String, TextEditingController)>[
          ('length_cm', _length),
          ('width_cm', _width),
          ('height_cm', _height),
        ]) {
          final shape = _dimensionShape(l, controller);
          if (shape != null) problems[field] = shape;
        }
        if (_dimensionsPartial) {
          problems['dimensions'] = l.requestDimensionsPartialFix;
        }
        final declared = _amountProblem(l, _declaredValue);
        if (declared != null) problems['declared_value_eur_cents'] = declared;
      case 2:
        if (_readyStart == null) {
          problems['ready_window_start'] = l.validationRequired;
        }
        if (_readyEnd == null) {
          problems['ready_window_end'] = l.validationRequired;
        } else if (_readyStart != null && !_readyEnd!.isAfter(_readyStart!)) {
          problems['ready_window_end'] = l.validationReadyWindowOrder;
        }
        final deadline = _deadline;
        if (deadline == null) {
          problems['deadline_at'] = l.validationRequired;
        } else if (!deadline.isAfter(DateTime.now())) {
          problems['deadline_at'] = l.validationDateInPast;
        } else if (_readyEnd != null && deadline.isBefore(_readyEnd!)) {
          problems['deadline_at'] = l.validationDeadlineBeforeReady;
        }
      default:
        if (!_ackDescription) {
          problems['description_is_accurate'] = l.validationRequired;
        }
        if (!_ackLegal) problems['item_is_legal'] = l.validationRequired;
        if (!_ackProhibited) {
          problems['no_prohibited_goods'] = l.validationRequired;
        }
        if (!_ackValue) {
          problems['declared_value_is_accurate'] = l.validationRequired;
        }
        if (!_ackCustoms) {
          problems['customs_responsibilities_understood'] =
              l.validationRequired;
        }
        final reward = _amountProblem(l, _reward);
        if (reward != null) {
          problems['sender_proposed_reward_eur_cents'] = reward;
        } else if (_pricingQuote != null) {
          final rewardCents = AppAmountField.centsOf(_reward) ?? 0;
          final minCents = _pricingQuote!.minimumReward.minorUnits;
          if (rewardCents < minCents) {
            problems['sender_proposed_reward_eur_cents'] = l
                .pricingBelowMinimumError(
                  _pricingQuote!.minimumReward.format(
                    Localizations.localeOf(context),
                  ),
                );
          }
        }
    }
    return problems;
  }

  /// Server errors still standing on [step].
  ///
  /// A standing error blocks the step, because the value it refused has not
  /// been changed. Editing the field clears it — see [_supersede].
  Iterable<String> _serverProblems(int step) =>
      _fieldsByStep[step]!.where((field) => _errors[field] != null);

  bool _stepIsValid(L l, int step) =>
      _localProblems(l, step).isEmpty && _serverProblems(step).isEmpty;

  /// Every step before [step] that is not yet valid — what stops the user
  /// jumping ahead, and what the final Post consults so it can never submit
  /// data the device already knows is incomplete.
  List<int> _incompleteStepsBefore(L l, int step) => [
    for (var i = 0; i < step; i++)
      if (!_stepIsValid(l, i)) i,
  ];

  /// The message to show for [field], or null.
  ///
  /// The server's verdict wins while it stands: it knows things the device
  /// does not. Local problems appear only once the step has been revealed, so
  /// an untouched form is not shouting at anyone.
  String? _errorFor(L l, String field, {int? step}) {
    final server = _errors[field];
    if (server != null) return server;
    final owner = step ?? _step;
    if (!_revealed.contains(owner)) return null;
    return _localProblems(l, owner)[field];
  }

  // -------------------------------------------------------------------------
  // Superseding stale server errors
  // -------------------------------------------------------------------------

  /// A text field's `onChanged`: drop the server errors on [fields] because
  /// the user just changed them, and re-render so the step's own validity —
  /// and with it the footer — reflects the new text.
  ///
  /// This is the fix for the dead Next button. The server refused a value; the
  /// value is now different; the refusal no longer describes anything. Keeping
  /// it would go on blocking the step over data the server has never seen. It
  /// is deliberately per-field: correcting a weight says nothing about a
  /// title, so a title's error survives.
  void Function(String) _onEdit(List<String> fields) => (_) {
    setState(() => _errors = _errors.without(fields));
  };

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  Future<void> _pickPlace({required bool isPickup}) async {
    final l = L.of(context);
    final chosen = await context.pickCanonicalPlace(
      title: isPickup ? l.requestPickupLocation : l.requestDeliveryLocation,
      current: isPickup ? _pickup : _delivery,
    );
    if (!mounted || chosen == null) return;

    // A preferred point belongs to one canonical place; changing the place has
    // to drop it. Dropping it silently is the part that is not acceptable —
    // the user set that pin deliberately and would otherwise submit without it
    // and without knowing.
    final droppedPoint = isPickup
        ? (_pickup?.id != chosen.id && _pickupPreferred != null)
        : (_delivery?.id != chosen.id && _deliveryPreferred != null);

    setState(() {
      if (isPickup) {
        if (_pickup?.id != chosen.id) _pickupPreferred = null;
        _pickup = chosen;
        _errors = _errors.without(const [
          'pickup_place_id',
          'pickup_location_id',
        ]);
      } else {
        if (_delivery?.id != chosen.id) _deliveryPreferred = null;
        _delivery = chosen;
        _errors = _errors.without(const [
          'delivery_place_id',
          'delivery_location_id',
        ]);
      }
    });

    if (droppedPoint) {
      AppSnack.info(context, l.locationPreferredClearedByPlace);
    }
  }

  void _removePreferredPoint({required bool isPickup}) {
    setState(() {
      if (isPickup) {
        _pickupPreferred = null;
      } else {
        _deliveryPreferred = null;
      }
    });
    AppSnack.info(context, L.of(context).locationPreferredRemoved);
  }

  Future<void> _pickPreferredPoint({required bool isPickup}) async {
    final place = isPickup ? _pickup : _delivery;
    if (place == null) return;
    final chosen = await context.pickPreferredLocation(
      place,
      title: L.of(context).locationPreferredMeetingPoint,
    );
    if (!mounted || chosen == null) return;
    setState(() {
      if (isPickup) {
        _pickupPreferred = chosen;
        _errors = _errors.without(const ['pickup_location_id']);
      } else {
        _deliveryPreferred = chosen;
        _errors = _errors.without(const ['delivery_location_id']);
      }
    });
  }

  Future<void> _pickCategory() async {
    final chosen = await showAppSheet<ItemCategory>(
      context,
      builder: (sheetContext) {
        final sheetL = L.of(sheetContext);
        return AppChoiceSheet<ItemCategory>(
          title: sheetL.requestCategory,
          selected: _category,
          options: [
            for (final category in _offeredCategories)
              AppSheetOption(
                value: category,
                label: _categoryLabel(sheetL, category),
              ),
          ],
        );
      },
    );
    if (!mounted || chosen == null) return;
    setState(() {
      _category = chosen;
      _errors = _errors.without(const ['category']);
    });
  }

  Future<void> _pickMoment({
    required DateTime? current,
    required DateTime? notBefore,
    required ValueChanged<DateTime> onPicked,
  }) async {
    final now = DateTime.now();
    final floor = notBefore ?? now;
    final initial = current ?? floor;

    final date = await showDatePicker(
      context: context,
      initialDate: initial.isBefore(floor) ? floor : initial,
      firstDate: DateTime(floor.year, floor.month, floor.day),
      lastDate: now.add(const Duration(days: 365)),
    );
    if (!mounted || date == null) return;

    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(initial),
    );
    if (!mounted || time == null) return;

    onPicked(DateTime(date.year, date.month, date.day, time.hour, time.minute));
  }

  // ---- the item photo ------------------------------------------------------

  Future<void> _pickPhoto(ImageSource source) async {
    final l = L.of(context);
    final picked = await ref.read(itemPhotoPickerProvider)(source);
    if (picked == null || !mounted) return;

    final bytes = await File(picked.path).length();
    if (!mounted) return;
    if (bytes > _maxPhotoBytes) {
      setState(() {
        _photoLocalError = l.requestItemPhotoTooLarge;
        _photoState = _PhotoState.empty;
      });
      return;
    }
    final mime = picked.mimeType ?? _mimeFromPath(picked.path);
    if (!_allowedPhotoTypes.contains(mime)) {
      setState(() {
        _photoLocalError = l.requestItemPhotoTypeNotAllowed;
        _photoState = _PhotoState.empty;
      });
      return;
    }

    setState(() {
      _photoFile = picked;
      _photoMime = mime;
      // A different file is a different upload, so it gets its own key. Two
      // photos of the same box can be byte-identical after the picker
      // re-encodes them, and collapsing those into one row would be worse
      // than an extra one.
      _photoIdempotencyKey = _newIdempotencyKey();
      _photoMediaId = null;
      _photoLocalError = null;
      _photoFailure = null;
      _errors = _errors.without(const ['item_photo_media_id']);
    });
    await _uploadPhoto();
  }

  /// Uploads the chosen photo and keeps the id the request will consume.
  ///
  /// Deliberately on pick rather than on Post: by the time the sender reaches
  /// the last step the photo is already stored, so Post is one call, and a
  /// failure here costs a retry rather than a half-created request.
  Future<void> _uploadPhoto() async {
    final file = _photoFile;
    if (file == null) return;

    setState(() {
      _photoState = _PhotoState.uploading;
      _photoProgress = 0;
      _photoFailure = null;
    });

    try {
      final media = await ref
          .read(requestRepositoryProvider)
          .stageItemPhoto(
            filePath: file.path,
            fileName: file.name,
            contentType: _photoMime,
            idempotencyKey: _photoIdempotencyKey,
            onProgress: (sent, total) {
              if (mounted && total > 0) {
                setState(() => _photoProgress = sent / total);
              }
            },
          );
      if (!mounted) return;
      setState(() {
        _photoMediaId = media.id;
        _photoState = _PhotoState.ready;
        _errors = _errors.without(const ['item_photo_media_id']);
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      // The file stays selected. A dropped connection is not a reason to make
      // someone photograph their parcel again.
      setState(() {
        _photoFailure = error;
        _photoState = _PhotoState.failed;
      });
    }
  }

  void _removePhoto() {
    setState(() {
      _photoFile = null;
      _photoMime = null;
      _photoMediaId = null;
      _photoIdempotencyKey = null;
      _photoState = _PhotoState.empty;
      _photoLocalError = null;
      _photoFailure = null;
    });
  }

  static String _newIdempotencyKey() {
    final random = Random.secure();
    return List.generate(
      4,
      (_) => random.nextInt(1 << 32).toRadixString(36),
    ).join();
  }

  static String _mimeFromPath(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.webp')) return 'image/webp';
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
    return '';
  }

  String _photoFailureCopy(L l, ApiException error) => switch (error.code.raw) {
    'parcel_photo_too_large' => l.requestItemPhotoTooLarge,
    'parcel_photo_media_type_unsupported' => l.requestItemPhotoTypeNotAllowed,
    'parcel_photo_storage_unavailable' => l.requestItemPhotoStorageUnavailable,
    'parcel_photo_missing' => l.requestItemPhotoRequired,
    _ => switch (error.statusCode) {
      413 => l.requestItemPhotoTooLarge,
      415 => l.requestItemPhotoTypeNotAllowed,
      _ => l.requestItemPhotoUploadFailed,
    },
  };

  // ---- navigation ----------------------------------------------------------

  /// Returns to a completed step.
  ///
  /// Backward only, and deliberately with no forward branch to be tempted by.
  /// [AppStepIndicator] does not turn a step the user has not reached into a
  /// control at all, so a future step cannot be tapped in the first place;
  /// every forward move goes through [_next], which validates the step being
  /// left. A step skipped is a required answer missing, and the only place
  /// that could surface is a 400 at the very end.
  void _goBackToStep(int target) {
    assert(target < _step, 'forward navigation must go through _next');
    if (target >= _step) return;
    setState(() {
      _step = target;
      _bouncedBySubmit = false;
    });
  }

  void _next() {
    final l = L.of(context);
    setState(() {
      _revealed.add(_step);
      _bouncedBySubmit = false;
    });

    if (!_stepIsValid(l, _step)) {
      _announceAndFocusFirstProblem(l, _step);
      return;
    }
    if (_step < _lastStep) {
      setState(() => _step++);
      if (_step == _lastStep) {
        _fetchPricingQuote();
      }
      return;
    }

    // Post re-checks every step, not just this one. Discovering on the server
    // that step 1 was incomplete is exactly the round trip that made the form
    // feel like a trap.
    final blocking = _incompleteStepsBefore(l, _lastStep);
    if (blocking.isNotEmpty) {
      final first = blocking.first;
      setState(() {
        _revealed.addAll(blocking);
        _step = first;
      });
      _announceAndFocusFirstProblem(l, first);
      return;
    }
    _submit();
  }

  Future<void> _fetchPricingQuote() async {
    final pickup = _pickup;
    final delivery = _delivery;
    final weight = parseDecimalInput(_weight.text);
    final readyEnd = _readyEnd;
    final deadline = _deadline;
    if (pickup == null ||
        delivery == null ||
        weight == null ||
        weight <= 0 ||
        readyEnd == null ||
        deadline == null) {
      return;
    }

    final seq = ++_quoteSeq;
    _quoteCancel?.cancel();
    final cancel = _quoteCancel = CancelToken();

    setState(() {
      _pricingLoading = true;
      _pricingError = null;
    });

    final currentRewardCents = AppAmountField.centsOf(_reward);
    final boostCents = _chosenBoostCents;

    try {
      final quote = await ref
          .read(requestRepositoryProvider)
          .quotePricingDraft(
            pickupPlaceId: pickup.id,
            deliveryPlaceId: delivery.id,
            actualWeightKg: weight,
            lengthCm: parseDecimalInput(_length.text),
            widthCm: parseDecimalInput(_width.text),
            heightCm: parseDecimalInput(_height.text),
            readyWindowEnd: readyEnd,
            deadlineAt: deadline,
            chosenRewardEurCents: currentRewardCents,
            boostEurCents: boostCents > 0 ? boostCents : null,
            cancelToken: cancel,
          );
      if (!mounted || seq != _quoteSeq) return;
      var prefilled = false;
      setState(() {
        _pricingQuote = quote;
        _quotedRewardCents = currentRewardCents;
        _quotedBoostCents = boostCents;
        _pricingLoading = false;
        // If reward is empty, prefill with recommended
        if (_reward.text.trim().isEmpty) {
          _reward.text = quote.recommendedReward.editableString;
          prefilled = true;
        }
      });
      // The prefill chose a reward, and a quote without a chosen reward has
      // no totals. One follow-up read prices it; the server does the sums.
      if (prefilled) unawaited(_fetchPricingQuote());
    } on ApiException catch (e) {
      if (!mounted || seq != _quoteSeq) return;
      setState(() {
        _pricingLoading = false;
        _pricingError = e.serverDetail ?? L.of(context).stateUnexpectedBody;
      });
    } catch (_) {
      if (!mounted || seq != _quoteSeq) return;
      setState(() {
        _pricingLoading = false;
        _pricingError = L.of(context).stateUnexpectedBody;
      });
    }
  }

  /// True when [_pricingQuote] was priced for exactly what the form holds.
  bool get _quoteIsCurrent =>
      _pricingQuote != null &&
      _quotedRewardCents == AppAmountField.centsOf(_reward) &&
      _quotedBoostCents == _chosenBoostCents;

  void _chooseBoost(int cents) {
    if (_chosenBoostCents == cents) return;
    setState(() => _chosenBoostCents = cents);
    // A tap is one discrete choice, not a keystroke: price it now, and let
    // the sequence guard drop whatever an earlier tap was still waiting on.
    _rewardDebounceTimer?.cancel();
    _fetchPricingQuote();
  }

  void _adjustReward(int deltaCents) {
    final currentCents =
        AppAmountField.centsOf(_reward) ??
        _pricingQuote?.recommendedReward.minorUnits ??
        1000;
    final minCents = _pricingQuote?.minimumReward.minorUnits ?? 50;
    final newCents = max(minCents, currentCents + deltaCents);
    _reward.text = (newCents / 100.0).toStringAsFixed(2);
    _onEdit(const ['sender_proposed_reward_eur_cents'])('');
    _rewardDebounceTimer?.cancel();
    _fetchPricingQuote();
  }

  void _onRewardChanged(String text) {
    _onEdit(const ['sender_proposed_reward_eur_cents'])(text);
    _rewardDebounceTimer?.cancel();
    _rewardDebounceTimer = Timer(const Duration(milliseconds: 350), () {
      if (mounted) _fetchPricingQuote();
    });
  }

  /// Says what is wrong, then puts the cursor on it.
  ///
  /// Both halves matter. The announcement is the only feedback a screen-reader
  /// user gets from a button that declines to advance; the scroll is the only
  /// feedback a sighted user gets when the offending field is below the fold.
  void _announceAndFocusFirstProblem(L l, int step) {
    final problems = _localProblems(l, step);
    final standing = _serverProblems(step).toList();
    final ordered = _fieldsByStep[step]!
        .where(
          (field) => problems.containsKey(field) || standing.contains(field),
        )
        .toList();
    if (ordered.isEmpty) return;

    final count = ordered.length;
    final view = View.maybeOf(context);
    if (view != null) {
      // `sendAnnouncement` rather than the deprecated `announce`: the latter
      // reaches for the implicit view, which does not exist under multiple
      // windows. The message is the field's own error when there is one
      // problem, because "Fix 1 field" is strictly less useful than the
      // sentence that says what is wrong with it.
      unawaited(
        SemanticsService.sendAnnouncement(
          view,
          count == 1
              ? (problems[ordered.first] ??
                    _errors[ordered.first] ??
                    l.formFixBeforeContinuing)
              : l.formFixCountBeforeContinuing(count),
          Directionality.of(context),
        ),
      );
    }

    // After the frame, because the error text this scrolls to has only just
    // been asked for and is not laid out yet.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final target = ordered.first;
      final anchorContext = _anchors[target]?.currentContext;
      if (anchorContext != null) {
        unawaited(
          Scrollable.ensureVisible(
            anchorContext,
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeOut,
            alignment: 0.15,
          ),
        );
      }
      _focusNodes[target]?.requestFocus();
    });
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _errors = const FieldErrorMap.empty();
      _bouncedBySubmit = false;
    });

    try {
      final draft = DeliveryRequestDraft(
        pickupPlaceId: _pickup!.id,
        deliveryPlaceId: _delivery!.id,
        pickupLocationId: _pickupPreferred?.id,
        deliveryLocationId: _deliveryPreferred?.id,
        readyWindowStart: _readyStart!,
        readyWindowEnd: _readyEnd!,
        deadlineAt: _deadline!,
        actualWeightKg: parseDecimalInput(_weight.text)!,
        lengthCm: parseDecimalInput(_length.text),
        widthCm: parseDecimalInput(_width.text),
        heightCm: parseDecimalInput(_height.text),
        declaredValueEurCents: AppAmountField.centsOf(_declaredValue) ?? 0,
        senderProposedRewardEurCents: AppAmountField.centsOf(_reward) ?? 0,
        boostEurCents: _chosenBoostCents,
        postingDepositEurCents: _chosenDepositCents,
        title: _title.text.trim(),
        description: _description.text.trim(),
        category: _category!,
        handlingNotes: _handlingNotes.text.trim(),
        fragile: _fragile,
        itemPhotoMediaId: _photoMediaId!,
        acknowledgements: SafetyAcknowledgements(
          descriptionIsAccurate: _ackDescription,
          itemIsLegal: _ackLegal,
          noProhibitedGoods: _ackProhibited,
          declaredValueIsAccurate: _ackValue,
          customsResponsibilitiesUnderstood: _ackCustoms,
        ),
      );

      final created = await ref.read(requestRepositoryProvider).create(draft);
      if (!mounted) return;
      refreshVolatileState(ref);
      AppSnack.success(context, L.of(context).requestCreated);

      // A request that owes a deposit is `awaiting_deposit`: it exists, but no
      // traveller can see it. Sending the sender anywhere other than the
      // deposit would leave them believing they had posted something.
      final id = '${created.request.id}';
      if (created.postingDeposit != null) {
        context.pushReplacementNamed(
          Routes.requestDeposit,
          pathParameters: {'id': id},
        );
      } else {
        context.pushReplacementNamed(
          Routes.requestDetail,
          pathParameters: {'id': id},
        );
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      _handleSubmitFailure(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// A refused submission has to leave the user somewhere they can act.
  ///
  /// Moving to another step without a word is what the device QA saw. So the
  /// step is revealed, a notice at its head says the server refused this and
  /// the problem is marked below, and the first refused field is scrolled to.
  void _handleSubmitFailure(ApiException error) {
    final l = L.of(context);
    final errors = FieldErrorMap.from(error);
    final owner = _stepOwning(errors);

    // A staged photo the server no longer recognises has to be re-taken; the
    // id we hold is worthless, and pretending otherwise would leave Post
    // failing forever on a photo that looks present.
    final photoGone =
        error.code == ApiErrorCode.parcelItemPhotoUnavailable ||
        errors['item_photo_media_id'] != null;

    setState(() {
      _errors = errors;
      if (photoGone) {
        _photoMediaId = null;
        _photoState = _photoFile == null
            ? _PhotoState.empty
            : _PhotoState.failed;
      }
      if (owner != null) {
        _revealed.add(owner);
        _bouncedBySubmit = owner != _step;
        _step = owner;
      }
    });

    if (errors.isEmpty) {
      AppSnack.failure(context, error);
      return;
    }
    if (owner != null) _announceAndFocusFirstProblem(l, owner);
  }

  /// The earliest step that owns a rejected field, so the user lands on the
  /// question rather than on a banner about it.
  int? _stepOwning(FieldErrorMap errors) {
    for (final entry in _fieldsByStep.entries) {
      if (entry.value.any((field) => errors[field] != null)) return entry.key;
    }
    return null;
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final unclaimed = _errors.unclaimed(_claimedFields);
    final stepValid = _stepIsValid(l, _step);

    // There is deliberately no `Form` here. Its `validate()` was the vehicle
    // for the stale-error deadlock: `AppTextField` feeds its server
    // `errorText` into the validator, so one standing server error kept
    // `validate()` false forever while the only code that cleared server
    // errors sat behind that same gate. Validation is this screen's, computed
    // fresh in `_localProblems` and handed down as `errorText`.
    return DismissKeyboardOnTap(
      child: AppScaffold(
        topBar: AppTopBar(title: l.requestCreateTitle, showBack: true),
        body: ListView(
          padding: AppScrollPadding.pageWithFooter(context),
          children: [
            AppStepIndicator(
              currentIndex: _step,
              steps: [
                l.requestStepRoute,
                l.requestStepParcel,
                l.requestStepTiming,
                l.requestStepReview,
              ],
              onStepTapped: _goBackToStep,
            ),
            const SizedBox(height: AppSpace.xl),

            if (unclaimed.isNotEmpty) ...[
              InfoNotice(
                message: unclaimed.join('\n'),
                tone: StatusTone.bad,
                icon: Icons.error_outline_rounded,
              ),
              const SizedBox(height: AppSpace.lg),
            ],

            // The explanation for a jump the user did not ask for. Without it
            // a rejected Post simply teleports them backwards.
            if (_bouncedBySubmit) ...[
              InfoNotice(
                message: l.formServerRefusedOnStep,
                tone: StatusTone.bad,
                icon: Icons.report_problem_outlined,
              ),
              const SizedBox(height: AppSpace.lg),
            ],

            ...switch (_step) {
              0 => _routeStep(l),
              1 => _parcelStep(l),
              2 => _timingStep(l),
              _ => _reviewStep(l),
            },
          ],
        ),
        footer: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // The button stays enabled on purpose. A disabled primary action
            // with nothing to explain it is the most common dead end in a form
            // like this; pressing it reveals exactly which fields are missing
            // and takes the user to the first one. What it will never do is
            // submit data the device already knows is incomplete.
            if (_revealed.contains(_step) && !stepValid) ...[
              InfoNotice(
                message: _footerProblemMessage(l),
                tone: StatusTone.bad,
                icon: Icons.error_outline_rounded,
              ),
              const SizedBox(height: AppSpace.md),
            ],
            Row(
              children: [
                if (_step > 0) ...[
                  Expanded(
                    child: AppButton(
                      label: l.actionBack,
                      variant: AppButtonVariant.secondary,
                      onPressed: _busy ? null : () => _goBackToStep(_step - 1),
                    ),
                  ),
                  const SizedBox(width: AppSpace.md),
                ],
                Expanded(
                  flex: 2,
                  child: AppButton(
                    label: _step == _lastStep
                        ? l.requestPostAction
                        : l.actionNext,
                    isLoading: _busy,
                    onPressed: _busy ? null : _next,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _footerProblemMessage(L l) {
    final count =
        _localProblems(l, _step).length + _serverProblems(_step).length;
    return count <= 1
        ? l.formFixBeforeContinuing
        : l.formFixCountBeforeContinuing(count);
  }

  // ---- Step 1: route -------------------------------------------------------

  List<Widget> _routeStep(L l) {
    final sameProblem =
        _pickup != null && _delivery != null && _pickup!.id == _delivery!.id;

    return [
      AppSelectField(
        key: _anchor('pickup_place_id'),
        label: l.requestPickupLocation,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _pickup == null ? null : placeLabel(_pickup!),
        secondary: _pickup == null ? null : placeContext(context, _pickup!),
        helper: l.requestPickupHint,
        errorText:
            _errorFor(l, 'pickup_place_id') ?? _errors['pickup_location_id'],
        icon: Icons.outbox_rounded,
        onTap: () => _pickPlace(isPickup: true),
      ),
      if (_pickup != null)
        PreferredPointField(
          place: _pickup!,
          point: _pickupPreferred,
          enabled: !_busy,
          onChoose: () => _pickPreferredPoint(isPickup: true),
          onRemove: () => _removePreferredPoint(isPickup: true),
        ),
      AppSelectField(
        key: _anchor('delivery_place_id'),
        label: l.requestDeliveryLocation,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _delivery == null ? null : placeLabel(_delivery!),
        secondary: _delivery == null ? null : placeContext(context, _delivery!),
        helper: l.requestDeliveryHint,
        errorText:
            _errorFor(l, 'delivery_place_id') ??
            _errors['delivery_location_id'],
        icon: Icons.place_outlined,
        onTap: () => _pickPlace(isPickup: false),
      ),
      if (_delivery != null)
        PreferredPointField(
          place: _delivery!,
          point: _deliveryPreferred,
          enabled: !_busy,
          onChoose: () => _pickPreferredPoint(isPickup: false),
          onRemove: () => _removePreferredPoint(isPickup: false),
        ),
      if (sameProblem) ...[
        const SizedBox(height: AppSpace.sm),
        InfoNotice(
          message: l.validationSelectOne,
          tone: StatusTone.bad,
          icon: Icons.error_outline_rounded,
        ),
      ],
      const SizedBox(height: AppSpace.lg),
      InfoNotice(
        message: l.locationPrivacyBeforeFunding,
        icon: Icons.lock_outline_rounded,
      ),
    ];
  }

  // ---- Step 2: parcel ------------------------------------------------------
  //
  // Order is deliberate: the photo first, because it is the thing the sender
  // is holding and the thing a traveller will look at; then what it is called
  // and what it is; then the physical facts; then value and handling. Required
  // fields carry the asterisk and the screen-reader word; optional ones say
  // "Optional" in the label rather than leaving the user to find out by
  // pressing Next.

  List<Widget> _parcelStep(L l) {
    return [
      _ItemPhotoSection(
        anchorKey: _anchor('item_photo_media_id'),
        state: _photoState,
        file: _photoFile,
        progress: _photoProgress,
        // Shown the instant it happens, not held back until the step is
        // revealed. A sender who picks a 12 MB original and sees the sheet
        // close with nothing on screen has been told their phone is broken.
        localError: _photoLocalError,
        errorText: _errorFor(l, 'item_photo_media_id'),
        failureCopy: _photoFailure == null
            ? null
            : _photoFailureCopy(l, _photoFailure!),
        canRetry: _photoFailure?.isRetryable ?? false,
        busy: _busy,
        onGallery: () => _pickPhoto(ImageSource.gallery),
        onCamera: () => _pickPhoto(ImageSource.camera),
        onRetry: _uploadPhoto,
        onRemove: _removePhoto,
      ),
      const SizedBox(height: AppSpace.xl),

      AppTextField(
        key: _anchor('title'),
        focusNode: _focus('title'),
        label: l.requestTitle,
        controller: _title,
        hint: l.requestTitleHint,
        isRequired: true,
        maxLength: _maxTitleLength,
        errorText: _errorFor(l, 'title'),
        textCapitalization: TextCapitalization.sentences,
        textInputAction: TextInputAction.next,
        onChanged: _onEdit(const ['title']),
      ),
      AppTextField(
        key: _anchor('description'),
        focusNode: _focus('description'),
        label: l.requestDescription,
        controller: _description,
        hint: l.requestDescriptionHint,
        isRequired: true,
        maxLines: 4,
        minLines: 3,
        maxLength: _maxDescriptionLength,
        errorText: _errorFor(l, 'description'),
        textCapitalization: TextCapitalization.sentences,
        onChanged: _onEdit(const ['description']),
      ),
      AppSelectField(
        key: _anchor('category'),
        label: l.requestCategory,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _category == null ? null : _categoryLabel(l, _category!),
        errorText: _errorFor(l, 'category'),
        icon: Icons.category_outlined,
        onTap: _pickCategory,
      ),
      AppTextField(
        key: _anchor('actual_weight_kg'),
        focusNode: _focus('actual_weight_kg'),
        label: l.requestWeight,
        controller: _weight,
        isRequired: true,
        helper: l.requestWeightHelp,
        errorText: _errorFor(l, 'actual_weight_kg'),
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        textInputAction: TextInputAction.next,
        unit: l.requestWeightUnit,
        onChanged: _onEdit(const ['actual_weight_kg']),
      ),

      SectionHeader(
        title: '${l.requestDimensions} · ${l.fieldOptional}',
        subtitle: l.requestDimensionsOptionalHelp,
      ),
      Row(
        key: _anchor('dimensions'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: _DimensionField(
              anchorKey: _anchor('length_cm'),
              focusNode: _focus('length_cm'),
              label: l.requestLength,
              controller: _length,
              unit: l.requestDimensionUnit,
              errorText: _errorFor(l, 'length_cm'),
              onChanged: _onEdit(const ['length_cm', 'dimensions']),
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: _DimensionField(
              anchorKey: _anchor('width_cm'),
              focusNode: _focus('width_cm'),
              label: l.requestWidth,
              controller: _width,
              unit: l.requestDimensionUnit,
              errorText: _errorFor(l, 'width_cm'),
              onChanged: _onEdit(const ['width_cm', 'dimensions']),
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: _DimensionField(
              anchorKey: _anchor('height_cm'),
              focusNode: _focus('height_cm'),
              label: l.requestHeight,
              controller: _height,
              unit: l.requestDimensionUnit,
              errorText: _errorFor(l, 'height_cm'),
              onChanged: _onEdit(const ['height_cm', 'dimensions']),
            ),
          ),
        ],
      ),
      // Empty is fine and always was meant to be. What is refused is a half
      // filled set, and the message says which way out to take.
      if (_errorFor(l, 'dimensions') != null) ...[
        InfoNotice(
          message: _errorFor(l, 'dimensions')!,
          tone: StatusTone.bad,
          icon: Icons.error_outline_rounded,
        ),
        const SizedBox(height: AppSpace.md),
      ],
      Text(
        l.requestSizeExplainer,
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(color: context.colors.textTertiary),
      ),
      const SizedBox(height: AppSpace.xl),

      AppAmountField(
        key: _anchor('declared_value_eur_cents'),
        focusNode: _focus('declared_value_eur_cents'),
        label: l.requestDeclaredValue,
        controller: _declaredValue,
        helper: l.requestDeclaredValueHelp,
        errorText: _errorFor(l, 'declared_value_eur_cents'),
        onChanged: _onEdit(const ['declared_value_eur_cents']),
      ),
      const SizedBox(height: AppSpace.sm),
      AppCheckTile(
        value: _fragile,
        onChanged: (value) => setState(() {
          _fragile = value;
          _errors = _errors.without(const ['fragile']);
        }),
        title: l.requestFragile,
        errorText: _errors['fragile'],
      ),
      const SizedBox(height: AppSpace.lg),
      AppTextField(
        key: _anchor('handling_notes'),
        label: '${l.requestHandlingNotes} · ${l.fieldOptional}',
        controller: _handlingNotes,
        hint: l.requestHandlingNotesHint,
        maxLines: 3,
        minLines: 2,
        errorText: _errors['handling_notes'],
        textCapitalization: TextCapitalization.sentences,
        onChanged: _onEdit(const ['handling_notes']),
      ),
    ];
  }

  // ---- Step 3: timing ------------------------------------------------------

  List<Widget> _timingStep(L l) {
    final locale = Localizations.localeOf(context);

    return [
      AppSelectField(
        key: _anchor('ready_window_start'),
        label: l.requestReadyFrom,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _readyStart == null
            ? null
            : LocaleFormats.dateTime(locale, _readyStart!),
        helper: l.requestReadyWindowHelp,
        errorText: _errorFor(l, 'ready_window_start'),
        icon: Icons.event_available_rounded,
        onTap: () => _pickMoment(
          current: _readyStart,
          notBefore: null,
          onPicked: (value) => setState(() {
            _readyStart = value;
            if (_readyEnd != null && !_readyEnd!.isAfter(value)) {
              _readyEnd = null;
            }
            _errors = _errors.without(const [
              'ready_window_start',
              'ready_window_end',
            ]);
          }),
        ),
      ),
      AppSelectField(
        key: _anchor('ready_window_end'),
        label: l.requestReadyUntil,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _readyEnd == null
            ? null
            : LocaleFormats.dateTime(locale, _readyEnd!),
        errorText: _errorFor(l, 'ready_window_end'),
        icon: Icons.event_busy_rounded,
        onTap: () => _pickMoment(
          current: _readyEnd,
          notBefore: _readyStart,
          onPicked: (value) => setState(() {
            _readyEnd = value;
            if (_deadline != null && _deadline!.isBefore(value)) {
              _deadline = null;
            }
            _errors = _errors.without(const [
              'ready_window_end',
              'deadline_at',
            ]);
          }),
        ),
      ),
      AppSelectField(
        key: _anchor('deadline_at'),
        label: l.requestDeadline,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _deadline == null
            ? null
            : LocaleFormats.dateTime(locale, _deadline!),
        helper: l.requestDeadlineHelp,
        errorText: _errorFor(l, 'deadline_at'),
        icon: Icons.flag_outlined,
        onTap: () => _pickMoment(
          current: _deadline,
          notBefore: _readyEnd,
          onPicked: (value) => setState(() {
            _deadline = value;
            _errors = _errors.without(const ['deadline_at']);
          }),
        ),
      ),
    ];
  }

  // ---- Step 4: review ------------------------------------------------------

  List<Widget> _reviewStep(L l) {
    final locale = Localizations.localeOf(context);
    final pickup = _pickup;
    final delivery = _delivery;

    return [
      SectionHeader(title: l.requestReviewTitle),
      AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (pickup != null && delivery != null)
              RouteSummary(from: placeLabel(pickup), to: placeLabel(delivery)),
            // Two rows both labelled "Preferred meeting point" are two rows
            // the reader cannot tell apart. The label names the end; the
            // flexible case is stated rather than left as an absence, because
            // "no row" and "no point" look identical on a review screen.
            if (pickup != null)
              DetailRow(
                label: l.requestPickupLocation,
                value: Text(
                  _pickupPreferred?.displayLabel ??
                      l.locationFlexibleWithin(pickup.name),
                  textAlign: TextAlign.end,
                ),
              ),
            if (delivery != null)
              DetailRow(
                label: l.requestDeliveryLocation,
                value: Text(
                  _deliveryPreferred?.displayLabel ??
                      l.locationFlexibleWithin(delivery.name),
                  textAlign: TextAlign.end,
                ),
              ),
            const SizedBox(height: AppSpace.md),
            DetailRow(label: l.requestTitle, value: Text(_title.text.trim())),
            if (_category != null)
              DetailRow(
                label: l.requestCategory,
                value: Text(_categoryLabel(l, _category!)),
              ),
            DetailRow(
              label: l.requestWeight,
              value: Text(
                formatWeight(context, parseDecimalInput(_weight.text)),
              ),
            ),
            if (!_dimensionsPartial && _length.text.trim().isNotEmpty)
              DetailRow(
                label: l.requestDimensions,
                value: Text(
                  formatDimensions(
                    context,
                    parseDecimalInput(_length.text),
                    parseDecimalInput(_width.text),
                    parseDecimalInput(_height.text),
                  ),
                ),
              ),
            DetailRow(
              label: l.requestItemPhoto,
              value: Text(
                _photoMediaId != null
                    ? l.requestItemPhotoReady
                    : l.requestItemPhotoRequired,
                textAlign: TextAlign.end,
              ),
            ),
            if (_readyStart != null && _readyEnd != null)
              DetailRow(
                label: l.requestReadyWindow,
                value: Text(
                  LocaleFormats.range(locale, _readyStart!, _readyEnd!),
                ),
              ),
            if (_deadline != null)
              DetailRow(
                label: l.requestDeadline,
                value: Text(LocaleFormats.dateTime(locale, _deadline!)),
              ),
          ],
        ),
      ),
      const SizedBox(height: AppSpace.xl),

      SectionHeader(title: l.requestAcknowledgementsTitle),
      // Five separate statements, not one blanket agreement: each is a
      // distinct claim about a physical object crossing a border, and a
      // dispute can turn on exactly one of them.
      AppCheckTile(
        key: _anchor('description_is_accurate'),
        value: _ackDescription,
        onChanged: (v) => setState(() {
          _ackDescription = v;
          _errors = _errors.without(const ['description_is_accurate']);
        }),
        title: l.requestAckDescriptionAccurate,
        errorText: _errors['description_is_accurate'],
      ),
      AppCheckTile(
        key: _anchor('item_is_legal'),
        value: _ackLegal,
        onChanged: (v) => setState(() {
          _ackLegal = v;
          _errors = _errors.without(const ['item_is_legal']);
        }),
        title: l.requestAckItemLegal,
        errorText: _errors['item_is_legal'],
      ),
      AppCheckTile(
        key: _anchor('no_prohibited_goods'),
        value: _ackProhibited,
        onChanged: (v) => setState(() {
          _ackProhibited = v;
          _errors = _errors.without(const ['no_prohibited_goods']);
        }),
        title: l.requestAckNoProhibited,
        errorText: _errors['no_prohibited_goods'],
        linkLabel: l.requestProhibitedItemsLink,
        onLink: _showProhibited,
      ),
      AppCheckTile(
        key: _anchor('declared_value_is_accurate'),
        value: _ackValue,
        onChanged: (v) => setState(() {
          _ackValue = v;
          _errors = _errors.without(const ['declared_value_is_accurate']);
        }),
        title: l.requestAckValueAccurate,
        errorText: _errors['declared_value_is_accurate'],
      ),
      AppCheckTile(
        key: _anchor('customs_responsibilities_understood'),
        value: _ackCustoms,
        onChanged: (v) => setState(() {
          _ackCustoms = v;
          _errors = _errors.without(const [
            'customs_responsibilities_understood',
          ]);
        }),
        title: l.requestAckCustoms,
        errorText: _errors['customs_responsibilities_understood'],
      ),
      if (_revealed.contains(_lastStep) && !_allAcknowledged) ...[
        const SizedBox(height: AppSpace.md),
        InfoNotice(
          message: l.requestAckAllRequired,
          tone: StatusTone.bad,
          icon: Icons.error_outline_rounded,
        ),
      ],
      SectionHeader(
        title: l.pricingYourOfferLabel,
        subtitle: l.requestProposedRewardHelp,
      ),
      if (_pricingLoading && _pricingQuote == null)
        const Center(
          child: Padding(
            padding: EdgeInsets.symmetric(vertical: AppSpace.lg),
            child: CircularProgressIndicator(),
          ),
        )
      else ...[
        if (_pricingQuote != null) ...[
          Builder(
            builder: (context) {
              final locale = Localizations.localeOf(context);
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Container(
                          padding: const EdgeInsets.all(AppSpace.md),
                          decoration: BoxDecoration(
                            color: context.colors.surfaceSunken,
                            borderRadius: AppRadius.rMd,
                            border: Border.all(color: context.colors.hairline),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                l.pricingMinimumLabel,
                                style: Theme.of(context).textTheme.bodySmall
                                    ?.copyWith(
                                      color: context.colors.textSecondary,
                                    ),
                              ),
                              const SizedBox(height: AppSpace.xs),
                              Text(
                                _pricingQuote!.minimumReward.format(locale),
                                style: Theme.of(context).textTheme.titleMedium
                                    ?.copyWith(fontWeight: FontWeight.bold),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(width: AppSpace.md),
                      Expanded(
                        child: Container(
                          padding: const EdgeInsets.all(AppSpace.md),
                          decoration: BoxDecoration(
                            color: context.colors.surfaceSunken,
                            borderRadius: AppRadius.rMd,
                            border: Border.all(
                              color: context.colors.hairlineStrong,
                            ),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                l.pricingRecommendedLabel,
                                style: Theme.of(context).textTheme.bodySmall
                                    ?.copyWith(
                                      color: context.colors.brand,
                                      fontWeight: FontWeight.w600,
                                    ),
                              ),
                              const SizedBox(height: AppSpace.xs),
                              Text(
                                _pricingQuote!.recommendedReward.format(locale),
                                style: Theme.of(context).textTheme.titleMedium
                                    ?.copyWith(
                                      fontWeight: FontWeight.bold,
                                      color: context.colors.brand,
                                    ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              );
            },
          ),
          const SizedBox(height: AppSpace.md),
        ],

        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 8.0),
              child: IconButton.outlined(
                icon: const Icon(Icons.remove_rounded),
                tooltip: l.pricingDecrement50c,
                onPressed: () => _adjustReward(-50),
              ),
            ),
            const SizedBox(width: AppSpace.sm),
            Expanded(
              child: AppAmountField(
                key: _anchor('sender_proposed_reward_eur_cents'),
                focusNode: _focus('sender_proposed_reward_eur_cents'),
                label: l.pricingYourOfferLabel,
                controller: _reward,
                errorText: _errorFor(l, 'sender_proposed_reward_eur_cents'),
                onChanged: _onRewardChanged,
              ),
            ),
            const SizedBox(width: AppSpace.sm),
            Padding(
              padding: const EdgeInsets.only(top: 8.0),
              child: IconButton.outlined(
                icon: const Icon(Icons.add_rounded),
                tooltip: l.pricingIncrement50c,
                onPressed: () => _adjustReward(50),
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpace.sm),

        if (_pricingQuote != null &&
            _errorFor(l, 'sender_proposed_reward_eur_cents') == null) ...[
          if ((AppAmountField.centsOf(_reward) ?? 0) <
              _pricingQuote!.recommendedReward.minorUnits)
            InfoNotice(
              message: l.pricingBelowRecommended,
              tone: StatusTone.neutral,
              icon: Icons.info_outline_rounded,
            )
          else
            InfoNotice(
              message: l.pricingCompetitive,
              tone: StatusTone.good,
              icon: Icons.check_circle_outline_rounded,
            ),
          const SizedBox(height: AppSpace.md),
        ],

        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                l.boostSectionTitle,
                style: Theme.of(
                  context,
                ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: AppSpace.xs),
              Text(
                l.boostExplainer,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: context.colors.textSecondary,
                ),
              ),
              const SizedBox(height: AppSpace.sm),
              Wrap(
                spacing: AppSpace.sm,
                children: [
                  ChoiceChip(
                    label: Text(l.boostPresetNone),
                    selected: _chosenBoostCents == 0,
                    onSelected: (selected) {
                      if (selected) _chooseBoost(0);
                    },
                  ),
                  ChoiceChip(
                    label: Text(l.boostPreset5),
                    selected: _chosenBoostCents == 500,
                    onSelected: (selected) {
                      if (selected) _chooseBoost(500);
                    },
                  ),
                  ChoiceChip(
                    label: Text(l.boostPreset10),
                    selected: _chosenBoostCents == 1000,
                    onSelected: (selected) {
                      if (selected) _chooseBoost(1000);
                    },
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpace.md),

        if (_pricingQuote != null)
          _PricingTotalsCard(quote: _pricingQuote!, isCurrent: _quoteIsCurrent),

        if (_pricingError != null) ...[
          const SizedBox(height: AppSpace.sm),
          InfoNotice(
            message: _pricingError!,
            tone: StatusTone.bad,
            icon: Icons.error_outline_rounded,
            actionLabel: l.actionRetry,
            onAction: _fetchPricingQuote,
          ),
        ],
      ],
    ];
  }

  void _showProhibited() {
    showAppSheet<void>(
      context,
      builder: (sheetContext) {
        final sheetL = L.of(sheetContext);
        return AppSheet(
          title: sheetL.requestProhibitedItemsLink,
          child: Text(
            sheetL.requestAckNoProhibited,
            style: Theme.of(sheetContext).textTheme.bodyMedium,
          ),
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

/// The required photograph of the item.
///
/// Sits at the head of the parcel step because it is the first thing a
/// traveller looks at and the first thing the sender has to hand. One image,
/// not a gallery: V1 needs evidence of what is being carried, and a
/// multi-image manager would be a bigger surface with no more truth in it.
class _ItemPhotoSection extends StatelessWidget {
  const _ItemPhotoSection({
    required this.anchorKey,
    required this.state,
    required this.file,
    required this.progress,
    required this.localError,
    required this.errorText,
    required this.failureCopy,
    required this.canRetry,
    required this.busy,
    required this.onGallery,
    required this.onCamera,
    required this.onRetry,
    required this.onRemove,
  });

  final GlobalKey anchorKey;
  final _PhotoState state;
  final XFile? file;
  final double progress;

  /// A refusal this device made — too large, wrong type. Always shown,
  /// because it is the answer to a tap the user just made.
  final String? localError;

  final String? errorText;
  final String? failureCopy;
  final bool canRetry;
  final bool busy;
  final VoidCallback onGallery;
  final VoidCallback onCamera;
  final VoidCallback onRetry;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final uploading = state == _PhotoState.uploading;
    final hasFile = file != null;

    return Column(
      key: anchorKey,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(
          title: l.requestItemPhoto,
          subtitle: l.requestItemPhotoHelp,
        ),
        if (hasFile) ...[
          _PhotoPreview(file: file!, state: state, progress: progress),
          const SizedBox(height: AppSpace.md),
          Row(
            children: [
              Expanded(
                child: AppButton(
                  label: l.requestItemPhotoReplace,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_library_outlined,
                  onPressed: busy || uploading ? null : onGallery,
                ),
              ),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: AppButton(
                  label: l.requestItemPhotoRemove,
                  variant: AppButtonVariant.tertiary,
                  icon: Icons.delete_outline_rounded,
                  onPressed: busy || uploading ? null : onRemove,
                ),
              ),
            ],
          ),
        ] else ...[
          Row(
            children: [
              Expanded(
                child: AppButton(
                  label: l.requestItemPhotoFromGallery,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_library_outlined,
                  onPressed: busy ? null : onGallery,
                ),
              ),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: AppButton(
                  label: l.requestItemPhotoTakePhoto,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_camera_outlined,
                  onPressed: busy ? null : onCamera,
                ),
              ),
            ],
          ),
        ],
        const SizedBox(height: AppSpace.sm),
        Text(
          l.requestItemPhotoFormatRule,
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
        ),

        if (uploading) ...[
          const SizedBox(height: AppSpace.md),
          Semantics(
            liveRegion: true,
            label: l.requestItemPhotoUploading,
            child: LinearProgressIndicator(
              value: progress == 0 ? null : progress,
            ),
          ),
        ],

        // A failed upload keeps the file and offers Retry beside it. The retry
        // carries the same idempotency key, so an attempt that actually
        // reached the server before the connection died re-attaches to that
        // row instead of creating a second one.
        if (state == _PhotoState.failed && failureCopy != null) ...[
          const SizedBox(height: AppSpace.md),
          InfoNotice(
            message: failureCopy!,
            tone: canRetry ? StatusTone.waiting : StatusTone.bad,
            icon: Icons.refresh_rounded,
            actionLabel: canRetry ? l.actionRetry : null,
            onAction: canRetry && !busy ? onRetry : null,
          ),
        ],

        if (localError != null) ...[
          const SizedBox(height: AppSpace.md),
          InfoNotice(
            message: localError!,
            tone: StatusTone.bad,
            icon: Icons.error_outline_rounded,
          ),
        ],

        if (localError == null &&
            errorText != null &&
            state != _PhotoState.failed) ...[
          const SizedBox(height: AppSpace.md),
          InfoNotice(
            message: errorText!,
            // An upload still in flight blocks the step but is nobody's
            // mistake, and colouring it as one sends the sender looking for a
            // different photograph.
            tone: uploading ? StatusTone.waiting : StatusTone.bad,
            icon: uploading
                ? Icons.hourglass_top_rounded
                : Icons.error_outline_rounded,
          ),
        ],

        const SizedBox(height: AppSpace.sm),
        Text(
          l.requestItemPhotoPrivacy,
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
        ),
      ],
    );
  }
}

/// The chosen image, at a size worth looking at.
///
/// Reads from the local file rather than from the server: the bytes are on the
/// device already, and asking the API for a signed URL to show the user their
/// own photograph would be a round trip for nothing.
class _PhotoPreview extends StatelessWidget {
  const _PhotoPreview({
    required this.file,
    required this.state,
    required this.progress,
  });

  final XFile file;
  final _PhotoState state;
  final double progress;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    final (label, tone, icon) = switch (state) {
      _PhotoState.ready => (
        l.requestItemPhotoReady,
        StatusTone.good,
        Icons.check_circle_rounded,
      ),
      _PhotoState.uploading => (
        l.requestItemPhotoUploading,
        StatusTone.waiting,
        Icons.cloud_upload_outlined,
      ),
      _PhotoState.failed => (
        l.requestItemPhotoUploadFailed,
        StatusTone.bad,
        Icons.error_outline_rounded,
      ),
      _PhotoState.empty => (
        l.requestItemPhotoChoose,
        StatusTone.neutral,
        Icons.image_outlined,
      ),
    };
    final style = StatusStyle.of(context, tone);

    return Semantics(
      image: true,
      label: '${l.requestItemPhoto}. $label',
      child: ExcludeSemantics(
        child: Container(
          decoration: BoxDecoration(
            color: c.surfaceSunken,
            borderRadius: AppRadius.rMd,
            border: Border.all(color: c.hairlineStrong),
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            children: [
              SizedBox(
                height: 180,
                width: double.infinity,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Image.file(
                      File(file.path),
                      fit: BoxFit.cover,
                      // A picked file can be gone by the time it is drawn —
                      // a share-sheet temporary, a revoked permission. A grey
                      // placeholder is a far better answer than a red box of
                      // framework text.
                      errorBuilder: (_, _, _) => ColoredBox(
                        color: c.surfaceSunken,
                        child: Icon(
                          Icons.image_not_supported_outlined,
                          color: c.textTertiary,
                        ),
                      ),
                    ),
                    if (state == _PhotoState.uploading)
                      ColoredBox(
                        color: c.surface.withValues(alpha: 0.55),
                        child: Center(
                          child: SizedBox(
                            width: 42,
                            height: 42,
                            child: CircularProgressIndicator(
                              value: progress == 0 ? null : progress,
                              strokeWidth: 3,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpace.lg,
                  vertical: AppSpace.md,
                ),
                child: Row(
                  children: [
                    Icon(icon, size: 18, color: style.accent),
                    const SizedBox(width: AppSpace.sm),
                    Expanded(
                      child: Text(
                        label,
                        style: Theme.of(
                          context,
                        ).textTheme.bodySmall?.copyWith(color: c.textSecondary),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The categories a sender may choose. `unknown` is a parse fallback for rows
/// this build does not recognise, never an option.
const _offeredCategories = <ItemCategory>[
  ItemCategory.documents,
  ItemCategory.smallBox,
  ItemCategory.electronics,
  ItemCategory.clothing,
  ItemCategory.other,
];

String _categoryLabel(L l, ItemCategory category) => switch (category) {
  ItemCategory.documents => l.requestCategoryDocuments,
  ItemCategory.smallBox => l.requestCategorySmallBox,
  ItemCategory.electronics => l.requestCategoryElectronics,
  ItemCategory.clothing => l.requestCategoryClothing,
  ItemCategory.other || ItemCategory.unknown => l.requestCategoryOther,
};

class _DimensionField extends StatelessWidget {
  const _DimensionField({
    required this.anchorKey,
    required this.focusNode,
    required this.label,
    required this.controller,
    required this.unit,
    required this.errorText,
    required this.onChanged,
  });

  final GlobalKey anchorKey;
  final FocusNode focusNode;
  final String label;
  final TextEditingController controller;
  final String unit;

  /// Bound at last. The server answers a bad measurement with `length_cm`,
  /// and until 8F-B nothing on this screen rendered that key — which is how a
  /// refusal became a silent jump back to this step.
  final String? errorText;

  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => AppTextField(
    key: anchorKey,
    focusNode: focusNode,
    label: label,
    controller: controller,
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    textInputAction: TextInputAction.next,
    onChanged: onChanged,
    unit: unit,
    errorText: errorText,
  );
}

/// The request's price, as the server states it (J6.3).
///
/// Every figure is a `chosen_terms` field: the same terms, under the same
/// names, that the Offer and the Deal will carry. Nothing here adds the Boost
/// to a reward or a fee to a total. With a Boost the card reads in the Offer
/// and Deal order — Base delivery reward, Boost bonus, Traveler receives,
/// ShipTrip fee, Boost fee, You pay. Without one it stays three lines.
///
/// While the form holds a reward or Boost the quote was not priced for, the
/// old figures are dimmed, hidden from screen readers and marked as updating:
/// a stale total must never read as this request's total.
class _PricingTotalsCard extends StatelessWidget {
  const _PricingTotalsCard({required this.quote, required this.isCurrent});

  final PostingPricingQuote quote;
  final bool isCurrent;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final terms = quote.chosenTerms;

    final lines = <MoneyLine>[];
    if (terms.hasTotals) {
      if (terms.hasBoost) {
        if (terms.baseReward case final base?) {
          lines.add(MoneyLine(label: l.moneyBaseReward, amount: base));
        }
        lines
          ..add(MoneyLine(label: l.moneyBoostBonus, amount: terms.boostAmount!))
          ..add(
            MoneyLine.total(
              label: l.moneyTravelerReceives,
              amount: terms.travelerTotal!,
            ),
          );
      } else {
        lines.add(
          MoneyLine(
            label: l.moneyTravelerReceives,
            amount: terms.travelerTotal!,
          ),
        );
      }
      if (terms.platformFee case final fee?) {
        lines.add(MoneyLine(label: l.moneyPlatformFee, amount: fee));
      }
      if (terms.boostFee case final boostFee? when boostFee.isPositive) {
        lines.add(MoneyLine(label: l.moneyBoostFee, amount: boostFee));
      }
      lines.add(
        MoneyLine.total(
          label: l.moneyYouPay,
          amount: terms.senderTotalWithBoost!,
        ),
      );
    }

    final figures = Column(
      key: const ValueKey('request-pricing-totals'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (lines.isNotEmpty)
          MoneyBreakdown(title: l.moneyBreakdownTitle, lines: lines),
        const SizedBox(height: AppSpace.sm),
        AppCard(
          child: DetailRow(
            label: l.depositSectionTitle,
            value: Text(
              quote.deposit.recommendedDeposit.format(locale),
              style: const TextStyle(fontWeight: FontWeight.w500),
            ),
          ),
        ),
      ],
    );

    if (isCurrent) return figures;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          liveRegion: true,
          label: l.pricingUpdating,
          child: const LinearProgressIndicator(minHeight: 2),
        ),
        const SizedBox(height: AppSpace.xs),
        ExcludeSemantics(child: Opacity(opacity: 0.4, child: figures)),
      ],
    );
  }
}
