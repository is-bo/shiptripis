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
/// Local validation exists to spare the user a round trip on mistakes the
/// device can already see: a deadline before the parcel is ready, two identical
/// locations, one dimension out of three. Everything with a business meaning —
/// whether a corridor is servable, whether a weight is allowed — stays the
/// server's call and comes back through [FieldErrorMap]. When it does, the form
/// jumps to the step that owns the field rather than showing a banner about a
/// question three screens back.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/delivery_request.dart';
import '../../domain/location.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';

/// The smallest and largest parcel the V1 contract accepts, in kilograms.
/// Enforced here only so an obvious typo never becomes a round trip; the
/// server remains the authority.
const _minWeightKg = 0.01;
const _maxWeightKg = 100.0;

const _maxTitleLength = 160;
const _maxDescriptionLength = 2000;

class RequestCreateScreen extends ConsumerStatefulWidget {
  const RequestCreateScreen({super.key});

  @override
  ConsumerState<RequestCreateScreen> createState() =>
      _RequestCreateScreenState();
}

class _RequestCreateScreenState extends ConsumerState<RequestCreateScreen> {
  /// Every server field key this form has an input for. Anything outside it is
  /// surfaced as a form-level notice rather than silently dropped.
  static const _claimedFields = {
    'pickup_location_id',
    'delivery_location_id',
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
    'target_traveler_id',
    'description_is_accurate',
    'item_is_legal',
    'no_prohibited_goods',
    'declared_value_is_accurate',
    'customs_responsibilities_understood',
  };

  final _formKey = GlobalKey<FormState>();

  final _title = TextEditingController();
  final _description = TextEditingController();
  final _weight = TextEditingController();
  final _length = TextEditingController();
  final _width = TextEditingController();
  final _height = TextEditingController();
  final _declaredValue = TextEditingController();
  final _handlingNotes = TextEditingController();
  final _reward = TextEditingController();

  AppLocation? _pickup;
  AppLocation? _delivery;
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

  int _step = 0;
  bool _busy = false;

  /// True once the user has tried to leave a step. Before that, an untouched
  /// form should not be shouting at them.
  bool _touched = false;

  FieldErrorMap _errors = const FieldErrorMap.empty();

  @override
  void dispose() {
    _title.dispose();
    _description.dispose();
    _weight.dispose();
    _length.dispose();
    _width.dispose();
    _height.dispose();
    _declaredValue.dispose();
    _handlingNotes.dispose();
    _reward.dispose();
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // Local validation
  // -------------------------------------------------------------------------

  bool get _dimensionsPartial {
    final filled = [
      _length,
      _width,
      _height,
    ].where((c) => c.text.trim().isNotEmpty).length;
    return filled != 0 && filled != 3;
  }

  String? _routeError(L l) {
    if (_pickup == null || _delivery == null) return l.validationRequired;
    if (_pickup!.id == _delivery!.id) return l.validationSelectOne;
    return null;
  }

  String? _readyEndError(L l) {
    if (_readyStart == null || _readyEnd == null) return l.validationRequired;
    if (!_readyEnd!.isAfter(_readyStart!)) return l.validationReadyWindowOrder;
    return null;
  }

  String? _deadlineError(L l) {
    final deadline = _deadline;
    if (deadline == null) return l.validationRequired;
    if (!deadline.isAfter(DateTime.now())) return l.validationDateInPast;
    final end = _readyEnd;
    if (end != null && deadline.isBefore(end)) {
      return l.validationDeadlineBeforeReady;
    }
    return null;
  }

  bool get _allAcknowledged =>
      _ackDescription &&
      _ackLegal &&
      _ackProhibited &&
      _ackValue &&
      _ackCustoms;

  bool _stepIsValid(L l) {
    final formOk = _formKey.currentState?.validate() ?? false;
    return switch (_step) {
      0 => _routeError(l) == null,
      1 =>
        formOk &&
            _category != null &&
            !_dimensionsPartial &&
            (AppAmountField.centsOf(_declaredValue) ?? 0) > 0,
      2 =>
        _readyStart != null &&
            _readyEndError(l) == null &&
            _deadlineError(l) == null,
      _ =>
        formOk &&
            _allAcknowledged &&
            (AppAmountField.centsOf(_reward) ?? 0) > 0,
    };
  }

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  Future<void> _pickPlace({required bool isPickup}) async {
    final l = L.of(context);
    // The picker creates the location under this account, which is what makes
    // it a legal `pickup_location_id` — the server refuses one owned by
    // anybody else.
    final chosen = await context.pickLocation(
      title: isPickup ? l.requestPickupLocation : l.requestDeliveryLocation,
    );
    if (!mounted || chosen == null) return;
    setState(() {
      if (isPickup) {
        _pickup = chosen;
      } else {
        _delivery = chosen;
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
    setState(() => _category = chosen);
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

  void _next() {
    final l = L.of(context);
    setState(() => _touched = true);
    if (!_stepIsValid(l)) return;
    if (_step < 3) {
      setState(() {
        _step++;
        _touched = false;
      });
      return;
    }
    _submit();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _errors = const FieldErrorMap.empty();
    });

    try {
      final draft = DeliveryRequestDraft(
        pickupLocationId: _pickup!.id,
        deliveryLocationId: _delivery!.id,
        readyWindowStart: _readyStart!,
        readyWindowEnd: _readyEnd!,
        deadlineAt: _deadline!,
        actualWeightKg: parseDecimalInput(_weight.text)!,
        lengthCm: parseDecimalInput(_length.text),
        widthCm: parseDecimalInput(_width.text),
        heightCm: parseDecimalInput(_height.text),
        declaredValueEurCents: AppAmountField.centsOf(_declaredValue) ?? 0,
        senderProposedRewardEurCents: AppAmountField.centsOf(_reward) ?? 0,
        title: _title.text.trim(),
        description: _description.text.trim(),
        category: _category!,
        handlingNotes: _handlingNotes.text.trim(),
        fragile: _fragile,
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
      final errors = FieldErrorMap.from(error);
      setState(() {
        _errors = errors;
        _touched = true;
        _step = _stepOwning(errors) ?? _step;
      });
      if (errors.isEmpty) AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// The earliest step that owns a rejected field, so the user lands on the
  /// question rather than on a banner about it.
  int? _stepOwning(FieldErrorMap errors) {
    const byStep = <int, List<String>>{
      0: ['pickup_location_id', 'delivery_location_id', 'target_traveler_id'],
      1: [
        'title',
        'description',
        'category',
        'actual_weight_kg',
        'dimensions',
        'length_cm',
        'width_cm',
        'height_cm',
        'declared_value_eur_cents',
        'handling_notes',
        'fragile',
      ],
      2: ['ready_window_start', 'ready_window_end', 'deadline_at'],
      3: [
        'sender_proposed_reward_eur_cents',
        'description_is_accurate',
        'item_is_legal',
        'no_prohibited_goods',
        'declared_value_is_accurate',
        'customs_responsibilities_understood',
      ],
    };
    for (final entry in byStep.entries) {
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

    return DismissKeyboardOnTap(
      child: AppScaffold(
        topBar: AppTopBar(title: l.requestCreateTitle, showBack: true),
        body: Form(
          key: _formKey,
          child: ListView(
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
                onStepTapped: (index) => setState(() {
                  _step = index;
                  _touched = false;
                }),
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

              ...switch (_step) {
                0 => _routeStep(l),
                1 => _parcelStep(l),
                2 => _timingStep(l),
                _ => _reviewStep(l),
              },
            ],
          ),
        ),
        footer: Row(
          children: [
            if (_step > 0) ...[
              Expanded(
                child: AppButton(
                  label: l.actionBack,
                  variant: AppButtonVariant.secondary,
                  onPressed: _busy
                      ? null
                      : () => setState(() {
                          _step--;
                          _touched = false;
                        }),
                ),
              ),
              const SizedBox(width: AppSpace.md),
            ],
            Expanded(
              flex: 2,
              child: AppButton(
                label: _step == 3 ? l.requestPostAction : l.actionNext,
                isLoading: _busy,
                onPressed: _next,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ---- Step 1: route -------------------------------------------------------

  List<Widget> _routeStep(L l) {
    final routeProblem = _touched ? _routeError(l) : null;
    final sameProblem =
        _pickup != null && _delivery != null && _pickup!.id == _delivery!.id;

    return [
      AppSelectField(
        label: l.requestPickupLocation,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _pickup == null ? null : _placeLabel(_pickup!),
        secondary: _pickup?.region.isEmpty ?? true ? null : _pickup!.region,
        helper: l.requestPickupHint,
        errorText:
            _errors['pickup_location_id'] ??
            (_touched && _pickup == null ? routeProblem : null),
        icon: Icons.outbox_rounded,
        onTap: () => _pickPlace(isPickup: true),
      ),
      AppSelectField(
        label: l.requestDeliveryLocation,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _delivery == null ? null : _placeLabel(_delivery!),
        secondary: _delivery?.region.isEmpty ?? true ? null : _delivery!.region,
        helper: l.requestDeliveryHint,
        errorText:
            _errors['delivery_location_id'] ??
            (_touched && (_delivery == null || sameProblem)
                ? routeProblem
                : null),
        icon: Icons.place_outlined,
        onTap: () => _pickPlace(isPickup: false),
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

  List<Widget> _parcelStep(L l) {
    final validators = Validators.of(context);

    return [
      AppTextField(
        label: l.requestTitle,
        controller: _title,
        hint: l.requestTitleHint,
        isRequired: true,
        maxLength: _maxTitleLength,
        errorText: _errors['title'],
        textCapitalization: TextCapitalization.sentences,
        textInputAction: TextInputAction.next,
        validator: (value) =>
            validators.required(value) ??
            validators.maxLength(value, _maxTitleLength),
      ),
      AppTextField(
        label: l.requestDescription,
        controller: _description,
        hint: l.requestDescriptionHint,
        isRequired: true,
        maxLines: 4,
        minLines: 3,
        maxLength: _maxDescriptionLength,
        errorText: _errors['description'],
        textCapitalization: TextCapitalization.sentences,
        validator: (value) =>
            validators.required(value) ??
            validators.maxLength(value, _maxDescriptionLength),
      ),
      AppSelectField(
        label: l.requestCategory,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _category == null ? null : _categoryLabel(l, _category!),
        errorText:
            _errors['category'] ??
            (_touched && _category == null ? l.validationSelectOne : null),
        icon: Icons.category_outlined,
        onTap: _pickCategory,
      ),
      AppTextField(
        label: l.requestWeight,
        controller: _weight,
        isRequired: true,
        helper: l.requestWeightHelp,
        errorText: _errors['actual_weight_kg'],
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        textInputAction: TextInputAction.next,
        suffix: _UnitSuffix(label: l.requestWeightUnit),
        validator: (value) {
          final shape = validators.positiveNumber(value);
          if (shape != null) return shape;
          final kg = parseDecimalInput(value)!;
          if (kg < _minWeightKg || kg > _maxWeightKg) {
            return l.validationWeightRange(
              _minWeightKg.toStringAsFixed(2),
              _maxWeightKg.toStringAsFixed(0),
            );
          }
          return null;
        },
      ),

      SectionHeader(
        title: l.requestDimensions,
        subtitle: l.requestDimensionsHelp,
      ),
      Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: _DimensionField(
              label: l.requestLength,
              controller: _length,
              unit: l.requestDimensionUnit,
              onChanged: (_) => setState(() {}),
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: _DimensionField(
              label: l.requestWidth,
              controller: _width,
              unit: l.requestDimensionUnit,
              onChanged: (_) => setState(() {}),
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: _DimensionField(
              label: l.requestHeight,
              controller: _height,
              unit: l.requestDimensionUnit,
              onChanged: (_) => setState(() {}),
            ),
          ),
        ],
      ),
      // The server stores all three or none and answers a partial set with a
      // `dimensions` key. Catching it here saves a round trip and lands the
      // message next to the boxes rather than at the top of the form.
      if (_dimensionsPartial || _errors['dimensions'] != null) ...[
        InfoNotice(
          message: _errors['dimensions'] ?? l.requestDimensionsPartial,
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
        label: l.requestDeclaredValue,
        controller: _declaredValue,
        helper: l.requestDeclaredValueHelp,
        errorText:
            _errors['declared_value_eur_cents'] ??
            (_touched && (AppAmountField.centsOf(_declaredValue) ?? 0) <= 0
                ? l.validationMustBePositive
                : null),
        onChanged: (_) => setState(() {}),
      ),
      const SizedBox(height: AppSpace.sm),
      AppCheckTile(
        value: _fragile,
        onChanged: (value) => setState(() => _fragile = value),
        title: l.requestFragile,
        errorText: _errors['fragile'],
      ),
      const SizedBox(height: AppSpace.lg),
      AppTextField(
        label: l.requestHandlingNotes,
        controller: _handlingNotes,
        hint: l.requestHandlingNotesHint,
        maxLines: 3,
        minLines: 2,
        errorText: _errors['handling_notes'],
        textCapitalization: TextCapitalization.sentences,
      ),
    ];
  }

  // ---- Step 3: timing ------------------------------------------------------

  List<Widget> _timingStep(L l) {
    final locale = Localizations.localeOf(context);

    return [
      AppSelectField(
        label: l.requestReadyFrom,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _readyStart == null
            ? null
            : LocaleFormats.dateTime(locale, _readyStart!),
        helper: l.requestReadyWindowHelp,
        errorText:
            _errors['ready_window_start'] ??
            (_touched && _readyStart == null ? l.validationRequired : null),
        icon: Icons.event_available_rounded,
        onTap: () => _pickMoment(
          current: _readyStart,
          notBefore: null,
          onPicked: (value) => setState(() {
            _readyStart = value;
            if (_readyEnd != null && !_readyEnd!.isAfter(value)) {
              _readyEnd = null;
            }
          }),
        ),
      ),
      AppSelectField(
        label: l.requestReadyUntil,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _readyEnd == null
            ? null
            : LocaleFormats.dateTime(locale, _readyEnd!),
        errorText:
            _errors['ready_window_end'] ??
            (_touched ? _readyEndError(l) : null),
        icon: Icons.event_busy_rounded,
        onTap: () => _pickMoment(
          current: _readyEnd,
          notBefore: _readyStart,
          onPicked: (value) => setState(() {
            _readyEnd = value;
            if (_deadline != null && _deadline!.isBefore(value)) {
              _deadline = null;
            }
          }),
        ),
      ),
      AppSelectField(
        label: l.requestDeadline,
        isRequired: true,
        placeholder: l.actionSelect,
        value: _deadline == null
            ? null
            : LocaleFormats.dateTime(locale, _deadline!),
        helper: l.requestDeadlineHelp,
        errorText:
            _errors['deadline_at'] ?? (_touched ? _deadlineError(l) : null),
        icon: Icons.flag_outlined,
        onTap: () => _pickMoment(
          current: _deadline,
          notBefore: _readyEnd,
          onPicked: (value) => setState(() => _deadline = value),
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
              RouteSummary(
                from: _placeLabel(pickup),
                to: _placeLabel(delivery),
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
        value: _ackDescription,
        onChanged: (v) => setState(() => _ackDescription = v),
        title: l.requestAckDescriptionAccurate,
        errorText: _errors['description_is_accurate'],
      ),
      AppCheckTile(
        value: _ackLegal,
        onChanged: (v) => setState(() => _ackLegal = v),
        title: l.requestAckItemLegal,
        errorText: _errors['item_is_legal'],
      ),
      AppCheckTile(
        value: _ackProhibited,
        onChanged: (v) => setState(() => _ackProhibited = v),
        title: l.requestAckNoProhibited,
        errorText: _errors['no_prohibited_goods'],
        linkLabel: l.requestProhibitedItemsLink,
        onLink: _showProhibited,
      ),
      AppCheckTile(
        value: _ackValue,
        onChanged: (v) => setState(() => _ackValue = v),
        title: l.requestAckValueAccurate,
        errorText: _errors['declared_value_is_accurate'],
      ),
      AppCheckTile(
        value: _ackCustoms,
        onChanged: (v) => setState(() => _ackCustoms = v),
        title: l.requestAckCustoms,
        errorText: _errors['customs_responsibilities_understood'],
      ),
      if (_touched && !_allAcknowledged) ...[
        const SizedBox(height: AppSpace.md),
        InfoNotice(
          message: l.requestAckAllRequired,
          tone: StatusTone.bad,
          icon: Icons.error_outline_rounded,
        ),
      ],
      const SizedBox(height: AppSpace.xl),

      AppAmountField(
        label: l.requestProposedReward,
        controller: _reward,
        helper: l.requestProposedRewardHelp,
        errorText:
            _errors['sender_proposed_reward_eur_cents'] ??
            (_touched && (AppAmountField.centsOf(_reward) ?? 0) <= 0
                ? l.validationMustBePositive
                : null),
        onChanged: (_) => setState(() {}),
      ),
      InfoNotice(
        message: l.requestRewardIsIntent,
        icon: Icons.info_outline_rounded,
      ),
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

  String _placeLabel(AppLocation place) =>
      place.isExact ? place.displayLabel : place.coarseLabel;
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

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
    required this.label,
    required this.controller,
    required this.unit,
    required this.onChanged,
  });

  final String label;
  final TextEditingController controller;
  final String unit;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final validators = Validators.of(context);
    return AppTextField(
      label: label,
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      textInputAction: TextInputAction.next,
      onChanged: onChanged,
      suffix: _UnitSuffix(label: unit),
      validator: (value) => validators.positiveNumber(value, allowEmpty: true),
    );
  }
}

class _UnitSuffix extends StatelessWidget {
  const _UnitSuffix({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsetsDirectional.only(end: AppSpace.lg),
    child: Text(
      label,
      style: Theme.of(
        context,
      ).textTheme.bodyMedium?.copyWith(color: context.colors.textSecondary),
    ),
  );
}
