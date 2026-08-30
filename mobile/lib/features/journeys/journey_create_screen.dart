/// Building a journey.
///
/// A journey is a *chain*, and a chain is the part users get wrong. So this
/// screen never asks anyone to assemble one from scratch: pick where you start
/// and where you end, and the app proposes the obvious single leg. Adding a
/// stop splits the chain; it does not restart it.
///
/// ## The chain cannot come apart
///
/// Only a leg's **destination** is editable. Leg 0's origin is the journey's
/// start, and every other leg's origin is the previous leg's destination —
/// derived, never typed. That makes three of the server's rules structurally
/// impossible to break rather than merely validated: positions are contiguous
/// from 0, the first leg begins where the journey does, and each leg starts
/// where the last one ended.
///
/// The one endpoint that *can* drift is the far end, and deliberately: a
/// traveller whose flight lands in Algiers but whose journey is to Jijel has a
/// real gap, and pretending otherwise would either forbid the flight leg or
/// silently invent a road leg. Instead the gap is named and a drive leg is
/// offered — pre-filled from two places the user already chose, with no time
/// on it, because the app does not know when they will drive.
///
/// ## Everything the server checks is checked here first
///
/// Times strictly increasing, no leg departing before the previous one lands,
/// arrival after departure, a flight number on flights and none on drives,
/// capacity of at least 0.01 kg, at most 20 legs. Not because the server's
/// answer is doubted, but because being bounced by a 400 after filling in six
/// fields is the worst version of this screen.
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
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/location.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../common/status_copy.dart';

/// The server's own ceiling, enforced here so nobody builds a 21st leg only to
/// have the whole journey refused.
const _maxLegs = 20;

/// What a leg looks like while it is being edited.
///
/// Holds no origin: that is always derived from the leg before it, which is
/// what keeps the chain connected by construction.
class _LegDraft {
  _LegDraft({required this.destination, this.mode = TransportModeDraft.flight});

  AppLocation destination;
  TransportModeDraft mode;
  DateTime? departAt;
  DateTime? arriveAt;

  final capacity = TextEditingController();
  final flightNumber = TextEditingController();

  TransportMode get displayMode => mode == TransportModeDraft.flight
      ? TransportMode.flight
      : TransportMode.drive;

  void dispose() {
    capacity.dispose();
    flightNumber.dispose();
  }
}

/// Everything wrong with one leg, per field, so each message lands on the
/// input that caused it.
typedef _LegIssues = ({
  String? depart,
  String? arrive,
  String? capacity,
  String? flightNumber,
});

class JourneyCreateScreen extends ConsumerStatefulWidget {
  const JourneyCreateScreen({super.key});

  @override
  ConsumerState<JourneyCreateScreen> createState() =>
      _JourneyCreateScreenState();
}

class _JourneyCreateScreenState extends ConsumerState<JourneyCreateScreen> {
  final _notes = TextEditingController();
  final _legs = <_LegDraft>[];

  AppLocation? _start;
  AppLocation? _destination;

  bool _busy = false;

  /// Errors stay hidden until the first submit. A form that turns red before
  /// it has been filled in teaches people to ignore red.
  bool _showErrors = false;

  FieldErrorMap _fieldErrors = const FieldErrorMap.empty();

  static const _claimedFields = {
    'start_location',
    'destination_location',
    'legs',
    'notes',
  };

  @override
  void dispose() {
    _notes.dispose();
    for (final leg in _legs) {
      leg.dispose();
    }
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // Chain
  // -------------------------------------------------------------------------

  AppLocation? _originOf(int index) =>
      index == 0 ? _start : _legs[index - 1].destination;

  /// Where the legs currently end, which is not necessarily the destination.
  AppLocation? get _chainEnd => _legs.isEmpty ? _start : _legs.last.destination;

  bool get _hasGap {
    final end = _chainEnd;
    final destination = _destination;
    if (end == null || destination == null) return false;
    return end.id != destination.id;
  }

  /// Proposes the single obvious leg the moment both ends are known.
  void _proposeFirstLegIfPossible() {
    if (_legs.isNotEmpty) return;
    final destination = _destination;
    if (_start == null || destination == null) return;
    _legs.add(_LegDraft(destination: destination));
  }

  Future<void> _pickStart() async {
    final picked = await context.pickLocation(
      title: L.of(context).journeyFrom,
      requireExact: false,
    );
    if (picked == null || !mounted) return;
    setState(() {
      _start = picked;
      _proposeFirstLegIfPossible();
    });
  }

  Future<void> _pickDestination() async {
    final picked = await context.pickLocation(
      title: L.of(context).journeyTo,
      requireExact: false,
    );
    if (picked == null || !mounted) return;
    setState(() {
      _destination = picked;
      _proposeFirstLegIfPossible();
    });
  }

  Future<void> _pickLegDestination(int index) async {
    final picked = await context.pickLocation(
      title: L.of(context).journeyAddLegDestinationTitle,
      requireExact: false,
    );
    if (picked == null || !mounted) return;
    setState(() => _legs[index].destination = picked);
  }

  Future<void> _addLeg() async {
    if (_legs.length >= _maxLegs) return;
    final picked = await context.pickLocation(
      title: L.of(context).journeyAddLegDestinationTitle,
      requireExact: false,
    );
    if (picked == null || !mounted) return;
    setState(
      () => _legs.add(
        _LegDraft(destination: picked, mode: TransportModeDraft.drive),
      ),
    );
  }

  void _removeLeg(int index) {
    setState(() {
      // Origins are derived, so dropping an entry re-links the chain on its
      // own — the next leg simply starts where the removed one did.
      _legs.removeAt(index).dispose();
    });
  }

  /// Closes the gap with the drive leg the ARB copy offers.
  ///
  /// Pre-filled only from places the user already chose. No time is guessed:
  /// the app does not know when somebody plans to drive.
  void _acceptSuggestedLeg() {
    final destination = _destination;
    if (destination == null || _legs.length >= _maxLegs) return;
    setState(
      () => _legs.add(
        _LegDraft(destination: destination, mode: TransportModeDraft.drive),
      ),
    );
  }

  /// "No, I stop there" — the journey ends where the legs end.
  void _declineSuggestedLeg() {
    final end = _chainEnd;
    if (end == null) return;
    setState(() => _destination = end);
  }

  // -------------------------------------------------------------------------
  // Validation
  // -------------------------------------------------------------------------

  _LegIssues _issuesFor(int index) {
    final l = L.of(context);
    final leg = _legs[index];
    final previous = index == 0 ? null : _legs[index - 1];

    String? depart;
    final departAt = leg.departAt;
    if (departAt == null) {
      depart = l.journeyLegDepartRequired;
    } else if (previous != null) {
      final previousDepart = previous.departAt;
      final previousArrive = previous.arriveAt;
      if (previousDepart != null && !departAt.isAfter(previousDepart)) {
        depart = l.journeyLegDepartNotAfterPrevious;
      } else if (previousArrive != null && departAt.isBefore(previousArrive)) {
        depart = l.journeyLegDepartBeforePreviousArrival;
      }
    }

    final arriveAt = leg.arriveAt;
    final arrive =
        (arriveAt != null && departAt != null && !arriveAt.isAfter(departAt))
        ? l.journeyLegArriveBeforeDepart
        : null;

    // The wire format is two decimal places, so the check is on what will
    // actually be sent — 0.004 kg rounds to 0.00 and would be refused.
    final capacityValue = parseDecimalInput(leg.capacity.text);
    final capacity =
        (capacityValue == null || (capacityValue * 100).round() < 1)
        ? l.journeyCapacityInvalid
        : null;

    // Required on a flight, and required to be *empty* on a drive — which is
    // why the field is not merely hidden but cleared with the mode.
    final flightNumber =
        leg.mode == TransportModeDraft.flight &&
            leg.flightNumber.text.trim().isEmpty
        ? l.validationRequired
        : null;

    return (
      depart: depart,
      arrive: arrive,
      capacity: capacity,
      flightNumber: flightNumber,
    );
  }

  bool get _isValid {
    if (_start == null || _destination == null) return false;
    if (_legs.isEmpty || _legs.length > _maxLegs) return false;
    if (_hasGap) return false;
    for (var i = 0; i < _legs.length; i++) {
      final issues = _issuesFor(i);
      if (issues.depart != null ||
          issues.arrive != null ||
          issues.capacity != null ||
          issues.flightNumber != null) {
        return false;
      }
    }
    return true;
  }

  // -------------------------------------------------------------------------
  // Submit
  // -------------------------------------------------------------------------

  Future<void> _submit() async {
    final l = L.of(context);
    if (!_isValid) {
      setState(() => _showErrors = true);
      return;
    }

    setState(() {
      _busy = true;
      _showErrors = true;
      _fieldErrors = const FieldErrorMap.empty();
    });

    try {
      final drafts = <JourneyLegDraft>[
        for (var i = 0; i < _legs.length; i++)
          JourneyLegDraft(
            position: i,
            mode: _legs[i].mode,
            originId: _originOf(i)!.id,
            destinationId: _legs[i].destination.id,
            departAt: _legs[i].departAt!,
            arriveAt: _legs[i].arriveAt,
            capacityKg: parseDecimalInput(_legs[i].capacity.text)!,
            flightNumber: _legs[i].mode == TransportModeDraft.flight
                ? _legs[i].flightNumber.text.trim()
                : '',
          ),
      ];

      final journey = await ref
          .read(journeyRepositoryProvider)
          .create(
            startLocationId: _start!.id,
            destinationLocationId: _destination!.id,
            legs: drafts,
            notes: _notes.text.trim(),
          );

      if (!mounted) return;
      refreshVolatileState(ref);
      AppSnack.success(context, l.journeyCreatedDraft);
      // A new journey is a draft, never live. Replacing rather than pushing
      // means Back from the detail screen returns where the user started, not
      // to a form whose work is already saved.
      context.pushReplacementNamed(
        Routes.journeyDetail,
        pathParameters: {'id': '${journey.id}'},
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _fieldErrors = FieldErrorMap.from(error));
      AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final unclaimed = _fieldErrors.unclaimed(_claimedFields);
    final hasBothEnds = _start != null && _destination != null;

    return AppScaffold(
      topBar: AppTopBar(title: l.journeyCreateTitle, showBack: true),
      body: DismissKeyboardOnTap(
        child: ListView(
          padding: AppScrollPadding.pageWithFooter(context),
          children: [
            if (unclaimed.isNotEmpty) ...[
              InfoNotice(
                message: unclaimed.join('\n'),
                tone: StatusTone.bad,
                icon: Icons.error_outline_rounded,
              ),
              const SizedBox(height: AppSpace.xl),
            ],

            SectionHeader(title: l.journeyOverallRoute),
            AppSelectField(
              label: l.journeyFrom,
              placeholder: l.locationSearchTitle,
              icon: Icons.trip_origin_rounded,
              isRequired: true,
              enabled: !_busy,
              value: _start?.displayLabel,
              secondary: _start?.coarseLabel,
              errorText: _showErrors && _start == null
                  ? l.validationRequired
                  : _fieldErrors['start_location'],
              onTap: _pickStart,
            ),
            AppSelectField(
              label: l.journeyTo,
              placeholder: l.locationSearchTitle,
              icon: Icons.place_outlined,
              isRequired: true,
              enabled: !_busy,
              value: _destination?.displayLabel,
              secondary: _destination?.coarseLabel,
              errorText: _showErrors && _destination == null
                  ? l.validationRequired
                  : _fieldErrors['destination_location'],
              onTap: _pickDestination,
            ),

            if (!hasBothEnds || _legs.isEmpty) ...[
              const SizedBox(height: AppSpace.lg),
              AppEmptyState(
                title: l.journeyEmptyLegsTitle,
                body: l.journeyEmptyLegsBody,
                icon: Icons.route_rounded,
                compact: true,
              ),
            ] else ...[
              const SizedBox(height: AppSpace.lg),
              _ChainPreview(start: _start!, legs: _legs),
              const SizedBox(height: AppSpace.xl),

              SectionHeader(
                title: l.journeyLegs,
                subtitle: l.journeyCapacityHelp,
              ),
              for (var i = 0; i < _legs.length; i++) ...[
                _LegEditor(
                  position: i,
                  origin: _originOf(i),
                  leg: _legs[i],
                  issues: _showErrors ? _issuesFor(i) : null,
                  enabled: !_busy,
                  canRemove: _legs.length > 1,
                  onChanged: () => setState(() {}),
                  onPickDestination: () => _pickLegDestination(i),
                  onPickDepart: () => _pickTime(i, arrival: false),
                  onPickArrive: () => _pickTime(i, arrival: true),
                  onRemove: () => _removeLeg(i),
                ),
                const SizedBox(height: AppSpace.md),
              ],

              if (_hasGap) ...[
                const SizedBox(height: AppSpace.sm),
                _GapSuggestion(
                  arrival: _chainEnd!.coarseLabel,
                  destination: _destination!.coarseLabel,
                  canAccept: _legs.length < _maxLegs,
                  onAccept: _acceptSuggestedLeg,
                  onDecline: _declineSuggestedLeg,
                ),
                const SizedBox(height: AppSpace.md),
              ],

              if (_legs.length >= _maxLegs)
                InfoNotice(
                  message: l.journeyMaxLegsReached,
                  tone: StatusTone.waiting,
                  icon: Icons.linear_scale_rounded,
                )
              else
                AppButton(
                  label: l.journeyAddLeg,
                  icon: Icons.add_rounded,
                  variant: AppButtonVariant.secondary,
                  onPressed: _busy ? null : _addLeg,
                ),

              const SizedBox(height: AppSpace.xl),
              AppTextField(
                label: l.journeyNotesLabel,
                controller: _notes,
                hint: l.journeyNotesHint,
                enabled: !_busy,
                maxLines: 3,
                minLines: 2,
                maxLength: 500,
                textCapitalization: TextCapitalization.sentences,
                errorText: _fieldErrors['notes'],
              ),
            ],
          ],
        ),
      ),
      footer: AppButton(
        label: l.journeySaveDraft,
        isLoading: _busy,
        onPressed: _busy ? null : _submit,
      ),
    );
  }

  Future<void> _pickTime(int index, {required bool arrival}) async {
    final leg = _legs[index];
    final current = arrival ? leg.arriveAt : leg.departAt;
    final picked = await _pickDateTime(current ?? leg.departAt);
    if (picked == null || !mounted) return;
    setState(() {
      if (arrival) {
        leg.arriveAt = picked;
      } else {
        leg.departAt = picked;
      }
    });
  }

  Future<DateTime?> _pickDateTime(DateTime? initial) async {
    final now = DateTime.now();
    final seed = (initial == null || initial.isBefore(now)) ? now : initial;

    final date = await showDatePicker(
      context: context,
      initialDate: seed,
      firstDate: DateTime(now.year, now.month, now.day),
      lastDate: now.add(const Duration(days: 365)),
    );
    if (date == null || !mounted) return null;

    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(seed),
    );
    if (time == null || !mounted) return null;

    return DateTime(date.year, date.month, date.day, time.hour, time.minute);
  }
}

// ---------------------------------------------------------------------------
// The shape of the chain
// ---------------------------------------------------------------------------

/// The route as it currently stands, drawn rather than described.
///
/// A list of leg cards tells you what you typed; this tells you what you built,
/// which is the thing a multi-leg journey makes easy to get wrong.
class _ChainPreview extends StatelessWidget {
  const _ChainPreview({required this.start, required this.legs});

  final AppLocation start;
  final List<_LegDraft> legs;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l.journeyRouteShape,
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: AppSpace.lg),
          RouteLine(
            compactSegments: true,
            stops: [
              RouteStop(label: start.coarseLabel),
              for (final leg in legs)
                RouteStop(
                  label: leg.destination.coarseLabel,
                  timeLabel: leg.arriveAt == null
                      ? null
                      : '${l.journeyArrives} '
                            '${LocaleFormats.dateTime(locale, leg.arriveAt!)}',
                ),
            ],
            segments: [
              for (final leg in legs)
                RouteSegment(
                  mode: leg.displayMode,
                  modeLabel: transportModeLabel(context, leg.displayMode),
                  detail: _segmentDetail(context, locale, leg),
                  capacityLabel: formatCapacity(
                    context,
                    parseDecimalInput(leg.capacity.text),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  String? _segmentDetail(BuildContext context, Locale locale, _LegDraft leg) {
    final l = L.of(context);
    final parts = <String>[
      if (leg.mode == TransportModeDraft.flight &&
          leg.flightNumber.text.trim().isNotEmpty)
        leg.flightNumber.text.trim(),
      if (leg.departAt != null)
        '${l.journeyDeparts} ${LocaleFormats.dateTime(locale, leg.departAt!)}',
    ];
    return parts.isEmpty ? null : parts.join(' · ');
  }
}

// ---------------------------------------------------------------------------
// One leg
// ---------------------------------------------------------------------------

class _LegEditor extends StatelessWidget {
  const _LegEditor({
    required this.position,
    required this.origin,
    required this.leg,
    required this.issues,
    required this.enabled,
    required this.canRemove,
    required this.onChanged,
    required this.onPickDestination,
    required this.onPickDepart,
    required this.onPickArrive,
    required this.onRemove,
  });

  final int position;
  final AppLocation? origin;
  final _LegDraft leg;

  /// Null until the user has tried to submit.
  final _LegIssues? issues;

  final bool enabled;
  final bool canRemove;
  final VoidCallback onChanged;
  final VoidCallback onPickDestination;
  final VoidCallback onPickDepart;
  final VoidCallback onPickArrive;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final isFlight = leg.mode == TransportModeDraft.flight;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  l.journeyLegPosition(position + 1),
                  style: text.titleSmall,
                ),
              ),
              if (canRemove)
                AppIconButton(
                  icon: Icons.delete_outline_rounded,
                  label: l.journeyRemoveLeg,
                  onPressed: enabled ? onRemove : null,
                ),
            ],
          ),
          const SizedBox(height: AppSpace.md),

          // Derived, not editable: this is what keeps the chain joined.
          DetailRow(
            label: l.journeyLegStartsAt,
            icon: Icons.trip_origin_rounded,
            value: Text(
              origin?.coarseLabel ?? '—',
              style: text.bodyMedium,
              textAlign: TextAlign.end,
            ),
          ),
          Divider(height: AppSpace.lg, color: c.hairline),

          AppSelectField(
            label: l.journeyLegEndsAt,
            placeholder: l.journeyLegEndPlaceholder,
            icon: Icons.place_outlined,
            isRequired: true,
            enabled: enabled,
            value: leg.destination.displayLabel,
            secondary: leg.destination.coarseLabel,
            onTap: onPickDestination,
          ),

          AppSegmentedChoice<TransportModeDraft>(
            label: l.journeyModeFlight,
            selected: leg.mode,
            onSelect: (value) {
              leg.mode = value;
              // A drive leg must arrive with an empty flight number, so the
              // field is cleared rather than merely hidden.
              if (value == TransportModeDraft.drive) leg.flightNumber.clear();
              onChanged();
            },
            options: [
              AppChoice(
                value: TransportModeDraft.flight,
                label: l.journeyModeFlight,
                icon: TransportMode.flight.icon,
              ),
              AppChoice(
                value: TransportModeDraft.drive,
                label: l.journeyModeDrive,
                icon: TransportMode.drive.icon,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.lg),

          if (isFlight) ...[
            AppTextField(
              label: l.journeyFlightNumber,
              controller: leg.flightNumber,
              hint: l.journeyFlightNumberHint,
              isRequired: true,
              enabled: enabled,
              textCapitalization: TextCapitalization.characters,
              errorText: issues?.flightNumber,
              onChanged: (_) => onChanged(),
            ),
          ] else ...[
            InfoNotice(
              message: l.proofDriveNotRequired,
              icon: Icons.directions_car_outlined,
            ),
            const SizedBox(height: AppSpace.lg),
          ],

          AppSelectField(
            label: l.journeyDeparts,
            placeholder: l.journeyChooseDateTime,
            icon: Icons.schedule_rounded,
            isRequired: true,
            enabled: enabled,
            value: leg.departAt == null
                ? null
                : LocaleFormats.preciseDateTime(locale, leg.departAt!),
            errorText: issues?.depart,
            onTap: onPickDepart,
          ),

          AppSelectField(
            label: l.journeyArrives,
            placeholder: l.journeyChooseDateTime,
            icon: Icons.flag_outlined,
            enabled: enabled,
            helper: l.journeyArriveOptionalHelp,
            value: leg.arriveAt == null
                ? null
                : LocaleFormats.preciseDateTime(locale, leg.arriveAt!),
            errorText: issues?.arrive,
            onTap: onPickArrive,
          ),

          AppTextField(
            label: l.journeyCapacity,
            controller: leg.capacity,
            isRequired: true,
            enabled: enabled,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            errorText: issues?.capacity,
            onChanged: (_) => onChanged(),
            suffix: Padding(
              padding: const EdgeInsetsDirectional.only(end: AppSpace.lg),
              child: Text(
                formatWeight(context, 1).replaceAll('1', '').trim(),
                style: text.bodyMedium?.copyWith(color: c.textSecondary),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// The gap
// ---------------------------------------------------------------------------

/// Offers the drive leg that would close the distance between where the legs
/// end and where the journey is supposed to end.
class _GapSuggestion extends StatelessWidget {
  const _GapSuggestion({
    required this.arrival,
    required this.destination,
    required this.canAccept,
    required this.onAccept,
    required this.onDecline,
  });

  final String arrival;
  final String destination;
  final bool canAccept;
  final VoidCallback onAccept;
  final VoidCallback onDecline;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    return AppCard(
      accent: StatusTone.action,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l.journeySuggestLegTitle,
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: AppSpace.sm),
          Text(
            l.journeySuggestLegBody(arrival, destination),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.colors.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpace.lg),
          Row(
            children: [
              Expanded(
                child: AppButton(
                  label: l.journeySuggestLegAccept,
                  variant: AppButtonVariant.secondary,
                  onPressed: canAccept ? onAccept : null,
                ),
              ),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: AppButton(
                  label: l.journeySuggestLegDecline,
                  variant: AppButtonVariant.tertiary,
                  onPressed: onDecline,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
