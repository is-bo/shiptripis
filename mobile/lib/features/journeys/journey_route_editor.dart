/// The stop editor.
///
/// One vertical line of stops, with the leg between each pair rendered on the
/// connector — the same motif the rest of the product uses for a route, made
/// editable. There is no separate "preview": the thing you edit *is* the
/// picture of your journey, because two renderings of one route on a phone is
/// one too many.
///
/// The affordance the old screen was missing sits between every pair of
/// stops: **Add a stop here**. Inserting Algiers between Jijel and Paris is
/// one tap on the gap it belongs in, and the destination is never taken apart
/// to reach the middle. See [JourneyRouteDraft] for why stops rather than
/// legs.
///
/// Two things this screen refuses to do quietly:
///
/// * It never offers a mode the geography cannot support. An Algeria ↔ Europe
///   segment shows flight only, and says why, rather than accepting a drive
///   the server will refuse.
/// * It never turns a city into an airport behind the traveller's back. When
///   a segment has to fly, it asks which airport, and the stop then reads
///   "Algiers · ALG" — the city they chose, and how they leave it.
library;

import 'package:flutter/material.dart';

import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../design/components/forms.dart';
import '../../design/components/place.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/transport_rules.dart';
import '../../l10n/app_localizations.dart';
import 'journey_route_draft.dart';

/// Builds the localised strings [JourneyRouteDraft] validates with.
RouteCopy routeCopyOf(BuildContext context) {
  final l = L.of(context);
  return (
    departRequired: l.journeyLegDepartRequired,
    departNotAfterPrevious: l.journeyLegDepartNotAfterPrevious,
    departBeforePreviousArrival: l.journeyLegDepartBeforePreviousArrival,
    arriveBeforeDepart: l.journeyLegArriveBeforeDepart,
    capacityInvalid: l.journeyCapacityInvalid,
    required: l.validationRequired,
  );
}

class JourneyRouteEditor extends StatelessWidget {
  const JourneyRouteEditor({
    required this.draft,
    required this.enabled,
    required this.showErrors,
    super.key,
  });

  final JourneyRouteDraft draft;
  final bool enabled;

  /// Errors stay hidden until the first submit. A form that turns red before
  /// it has been filled in teaches people to ignore red.
  final bool showErrors;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    return ListenableBuilder(
      listenable: draft,
      builder: (context, _) {
        final stops = draft.stops;

        if (stops.isEmpty) {
          return _EndpointField(
            label: l.journeyFrom,
            stop: null,
            enabled: enabled,
            isRequired: true,
            errorText: showErrors ? l.validationRequired : null,
            onTap: () => _pickEndpoint(context, isOrigin: true),
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < stops.length; i++) ...[
              _StopBlock(
                draft: draft,
                index: i,
                enabled: enabled,
                showErrors: showErrors,
              ),
              if (i < draft.segments.length)
                _SegmentBlock(
                  draft: draft,
                  index: i,
                  enabled: enabled,
                  showErrors: showErrors,
                ),
            ],
            if (stops.length == 1) ...[
              const SizedBox(height: AppSpace.lg),
              _EndpointField(
                label: l.journeyTo,
                stop: null,
                enabled: enabled,
                isRequired: true,
                errorText: showErrors ? l.validationRequired : null,
                onTap: () => _pickEndpoint(context, isOrigin: false),
              ),
            ],
            if (!draft.canAddStop) ...[
              const SizedBox(height: AppSpace.md),
              InfoNotice(
                message: l.journeyMaxLegsReached,
                tone: StatusTone.waiting,
                icon: Icons.linear_scale_rounded,
              ),
            ],
          ],
        );
      },
    );
  }

  /// Asks for an endpoint the route does not have yet.
  ///
  /// Only reached before the route exists: once both ends are chosen, every
  /// stop — endpoints included — is changed from its own row on the line.
  Future<void> _pickEndpoint(
    BuildContext context, {
    required bool isOrigin,
  }) async {
    final l = L.of(context);
    final picked = await context.pickCanonicalPlace(
      title: isOrigin ? l.journeyFrom : l.journeyTo,
    );
    if (picked == null) return;
    if (isOrigin) {
      draft.setOrigin(picked);
    } else {
      draft.setDestination(picked);
    }
  }
}

// ---------------------------------------------------------------------------
// One stop
// ---------------------------------------------------------------------------

class _StopBlock extends StatelessWidget {
  const _StopBlock({
    required this.draft,
    required this.index,
    required this.enabled,
    required this.showErrors,
  });

  final JourneyRouteDraft draft;
  final int index;
  final bool enabled;
  final bool showErrors;

  bool get _isFirst => index == 0;
  bool get _isLast => index == draft.stops.length - 1;

  Future<void> _change(BuildContext context) async {
    final l = L.of(context);
    final stop = draft.stops[index];
    final picked = await context.pickCanonicalPlace(
      title: _isFirst
          ? l.journeyFrom
          : (_isLast ? l.journeyTo : l.routeChangeStopTitle),
      current: stop.place,
    );
    if (picked == null) return;
    draft.setStop(index, picked);
  }

  Future<void> _chooseAirport(BuildContext context) async {
    final stop = draft.stops[index];
    final picked = await context.pickCanonicalPlace(
      title: L.of(context).routeChooseAirportTitle,
      airportOnly: true,
      // Seeds the picker's country from the city, so choosing the airport for
      // Algiers does not start from a blank country list.
      current: stop.airport ?? stop.place,
    );
    if (picked == null) return;
    draft.setStopAirport(index, picked);
  }

  Future<void> _insertAfter(BuildContext context) async {
    final picked = await context.pickCanonicalPlace(
      title: L.of(context).routeAddStopTitle,
    );
    if (picked == null) return;
    draft.insertStopAfter(index, picked);
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final stop = draft.stops[index];
    final isIntermediate = draft.isIntermediate(index);

    // A stop is a duplicate when it resolves to the same city as its
    // neighbour, which is not a leg — it is the same place twice.
    final duplicatesPrevious =
        showErrors &&
        index > 0 &&
        draft.issuesFor(index - 1, routeCopyOf(context)).stopsAreTheSamePlace;

    return _RailRow(
      isFirst: _isFirst,
      isLast: _isLast && draft.segments.length == index,
      node: _StopNode(
        colour: _isFirst || _isLast ? c.brand : c.textTertiary,
        isEndpoint: _isFirst || _isLast,
      ),
      child: Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  // The label goes on the Semantics node and so does the tap
                  // action: `excludeSemantics` discards the InkWell's action
                  // on the way up, which produces a row TalkBack announces as
                  // a button and cannot activate. Same shape as the location
                  // picker's rows.
                  child: Semantics(
                    button: true,
                    label: [
                      _roleLabel(l),
                      placeSemanticLabel(context, stop.place),
                      if (stop.airport != null)
                        placeSemanticLabel(context, stop.airport!),
                    ].join(', '),
                    onTap: enabled ? () => _change(context) : null,
                    child: ExcludeSemantics(
                      child: InkWell(
                        onTap: enabled ? () => _change(context) : null,
                        borderRadius: AppRadius.rSm,
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                            vertical: AppSpace.xs,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _roleLabel(l),
                                style: text.labelSmall?.copyWith(
                                  color: c.textTertiary,
                                ),
                              ),
                              const SizedBox(height: AppSpace.xxs),
                              Text(_stopTitle(stop), style: text.titleSmall),
                              const SizedBox(height: AppSpace.xxs),
                              Text(
                                placeContext(context, stop.place),
                                style: text.bodySmall?.copyWith(
                                  color: c.textSecondary,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                if (isIntermediate) ...[
                  AppIconButton(
                    icon: Icons.arrow_upward_rounded,
                    label: l.routeMoveStopEarlier,
                    onPressed: enabled && draft.isIntermediate(index - 1)
                        ? () => draft.moveStop(index, earlier: true)
                        : null,
                  ),
                  AppIconButton(
                    icon: Icons.arrow_downward_rounded,
                    label: l.routeMoveStopLater,
                    onPressed: enabled && draft.isIntermediate(index + 1)
                        ? () => draft.moveStop(index, earlier: false)
                        : null,
                  ),
                  AppIconButton(
                    icon: Icons.close_rounded,
                    label: l.routeRemoveStop,
                    onPressed: enabled ? () => draft.removeStop(index) : null,
                  ),
                ] else
                  AppIconButton(
                    icon: Icons.edit_outlined,
                    label: l.routeChangeStopTitle,
                    onPressed: enabled ? () => _change(context) : null,
                  ),
              ],
            ),
            if (duplicatesPrevious)
              Padding(
                padding: const EdgeInsets.only(top: AppSpace.xs),
                child: Text(
                  l.routeStopSameAsPrevious,
                  style: text.bodySmall?.copyWith(color: c.danger),
                ),
              ),
            if (_needsAirport) ...[
              const SizedBox(height: AppSpace.sm),
              _AirportPrompt(
                stop: stop,
                enabled: enabled,
                onChoose: () => _chooseAirport(context),
              ),
            ],
            if (!_isLast) ...[
              const SizedBox(height: AppSpace.sm),
              _AddStopButton(
                enabled: enabled && draft.canAddStop,
                onPressed: () => _insertAfter(context),
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// Whether this stop should show the airport question, or the answer.
  ///
  /// Shown when a segment touching the stop flies and the stop is still a
  /// city; kept visible afterwards so the chosen airport can be changed. A
  /// stop that is itself an airport needs neither.
  bool get _needsAirport {
    final flies = [index - 1, index]
        .where((i) => i >= 0 && i < draft.segments.length)
        .any((i) => draft.segments[i].mode.isFlight);
    if (!flies) return false;
    final stop = draft.stops[index];
    return !stop.resolvesToAirport || stop.airport != null;
  }

  String _roleLabel(L l) {
    if (_isFirst) return l.journeyFrom;
    if (_isLast) return l.journeyTo;
    return l.routeStopLabel;
  }

  String _stopTitle(RouteStopDraft stop) {
    final airport = stop.airport;
    if (airport == null) return placeLabel(stop.place);
    final code = airport.iataCode;
    // IATA codes stay left-to-right inside an Arabic line; the design system
    // already isolates them in `placeLabel`.
    return code == null || code.isEmpty
        ? '${stop.place.name} · ${airport.name}'
        : '${stop.place.name} · $code';
  }
}

class _AirportPrompt extends StatelessWidget {
  const _AirportPrompt({
    required this.stop,
    required this.enabled,
    required this.onChoose,
  });

  final RouteStopDraft stop;
  final bool enabled;
  final VoidCallback onChoose;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final chosen = stop.airport;

    if (chosen != null) {
      return Row(
        children: [
          Expanded(
            child: Text(
              l.routeAirportChosen(placeLabel(chosen)),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ),
          AppButton(
            label: l.routeChangeAirport,
            variant: AppButtonVariant.tertiary,
            expand: false,
            onPressed: enabled ? onChoose : null,
          ),
        ],
      );
    }

    return InfoNotice(
      title: l.routeAirportNeededTitle,
      message: l.routeAirportNeededBody(placeLabel(stop.place)),
      tone: StatusTone.action,
      icon: Icons.flight_takeoff_rounded,
      actionLabel: l.routeChooseAirport,
      onAction: enabled ? onChoose : null,
    );
  }
}

class _AddStopButton extends StatelessWidget {
  const _AddStopButton({required this.enabled, required this.onPressed});

  final bool enabled;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => Align(
    alignment: AlignmentDirectional.centerStart,
    child: AppButton(
      label: L.of(context).routeAddStopHere,
      icon: Icons.add_rounded,
      variant: AppButtonVariant.tertiary,
      expand: false,
      onPressed: enabled ? onPressed : null,
    ),
  );
}

// ---------------------------------------------------------------------------
// One segment
// ---------------------------------------------------------------------------

class _SegmentBlock extends StatelessWidget {
  const _SegmentBlock({
    required this.draft,
    required this.index,
    required this.enabled,
    required this.showErrors,
  });

  final JourneyRouteDraft draft;
  final int index;
  final bool enabled;
  final bool showErrors;

  Future<void> _pickTime(BuildContext context, {required bool arrival}) async {
    final segment = draft.segments[index];
    final current = arrival ? segment.arriveAt : segment.departAt;
    final picked = await _pickDateTime(context, current ?? segment.departAt);
    if (picked == null) return;
    if (arrival) {
      draft.setSegmentArrival(index, picked);
    } else {
      draft.setSegmentDeparture(index, picked);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);
    final segment = draft.segments[index];
    final issues = showErrors
        ? draft.issuesFor(index, routeCopyOf(context))
        : null;
    final modes = draft.modesFor(index);
    final mustFly = draft.segmentMustFly(index);
    final isFlight = segment.mode.isFlight;

    return _RailRow(
      isFirst: false,
      isLast: false,
      node: const SizedBox(height: 0),
      child: Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.md),
        child: AppCard(
          accent:
              issues != null &&
                  (issues.needsAirports || issues.stopsAreTheSamePlace)
              ? StatusTone.bad
              : null,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    segment.displayMode.icon,
                    size: 18,
                    color: isFlight ? c.modeFlight : c.modeDrive,
                  ),
                  const SizedBox(width: AppSpace.sm),
                  Expanded(
                    child: Text(
                      l.routeSegmentBetween(
                        placeLabel(draft.stops[index].endpoint),
                        placeLabel(draft.stops[index + 1].endpoint),
                      ),
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpace.lg),

              if (mustFly)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpace.lg),
                  child: InfoNotice(
                    message: l.routeFlightOnlyExplainer,
                    icon: Icons.info_outline_rounded,
                  ),
                )
              else
                AppSegmentedChoice<LegMode>(
                  label: l.journeyModeLabel,
                  selected: segment.mode,
                  onSelect: enabled
                      ? (value) => draft.setSegmentMode(index, value)
                      : (_) {},
                  options: [
                    for (final mode in LegMode.values)
                      if (modes.contains(mode))
                        AppChoice(
                          value: mode,
                          label: mode.isFlight
                              ? l.journeyModeFlight
                              : l.journeyModeDrive,
                          icon: mode.isFlight
                              ? TransportMode.flight.icon
                              : TransportMode.drive.icon,
                        ),
                  ],
                ),

              if (issues?.stopsAreTheSamePlace ?? false) ...[
                InfoNotice(
                  message: l.routeStopSameAsPrevious,
                  tone: StatusTone.bad,
                  icon: Icons.error_outline_rounded,
                ),
                const SizedBox(height: AppSpace.lg),
              ],

              if (issues?.needsAirports ?? false) ...[
                InfoNotice(
                  message: l.routeFlightAirportsRequired,
                  tone: StatusTone.bad,
                  icon: Icons.flight_takeoff_rounded,
                ),
                const SizedBox(height: AppSpace.lg),
              ],

              if (isFlight)
                AppTextField(
                  label: l.journeyFlightNumber,
                  controller: segment.flightNumber,
                  hint: l.journeyFlightNumberHint,
                  isRequired: true,
                  enabled: enabled,
                  textCapitalization: TextCapitalization.characters,
                  errorText: issues?.flightNumber,
                  onChanged: (_) => draft.touch(),
                )
              else ...[
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
                value: segment.departAt == null
                    ? null
                    : LocaleFormats.preciseDateTime(locale, segment.departAt!),
                errorText: issues?.depart,
                onTap: () => _pickTime(context, arrival: false),
              ),

              AppSelectField(
                label: l.journeyArrives,
                placeholder: l.journeyChooseDateTime,
                icon: Icons.flag_outlined,
                enabled: enabled,
                helper: l.journeyArriveOptionalHelp,
                value: segment.arriveAt == null
                    ? null
                    : LocaleFormats.preciseDateTime(locale, segment.arriveAt!),
                errorText: issues?.arrive,
                onTap: () => _pickTime(context, arrival: true),
              ),

              AppTextField(
                label: l.journeyCapacity,
                controller: segment.capacity,
                isRequired: true,
                enabled: enabled,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                errorText: issues?.capacity,
                onChanged: (_) => draft.touch(),
                unit: l.requestWeightUnit,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// The rail
// ---------------------------------------------------------------------------

const double _railWidth = 26;

/// One row against the vertical route rail, so stops and segments read as one
/// continuous line rather than as a stack of cards.
class _RailRow extends StatelessWidget {
  const _RailRow({
    required this.isFirst,
    required this.isLast,
    required this.node,
    required this.child,
  });

  final bool isFirst;
  final bool isLast;
  final Widget node;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: _railWidth,
            child: Column(
              children: [
                SizedBox(
                  height: 10,
                  child: isFirst
                      ? null
                      : Center(child: _Rail(colour: c.hairlineStrong)),
                ),
                node,
                Expanded(
                  child: isLast
                      ? const SizedBox.shrink()
                      : Center(child: _Rail(colour: c.hairlineStrong)),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(child: child),
        ],
      ),
    );
  }
}

class _Rail extends StatelessWidget {
  const _Rail({required this.colour});

  final Color colour;

  @override
  Widget build(BuildContext context) => Container(width: 2, color: colour);
}

class _StopNode extends StatelessWidget {
  const _StopNode({required this.colour, required this.isEndpoint});

  final Color colour;
  final bool isEndpoint;

  @override
  Widget build(BuildContext context) => Container(
    width: 12,
    height: 12,
    decoration: BoxDecoration(
      color: isEndpoint ? colour : context.colors.surface,
      shape: BoxShape.circle,
      border: Border.all(color: colour, width: 2),
    ),
  );
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

class _EndpointField extends StatelessWidget {
  const _EndpointField({
    required this.label,
    required this.stop,
    required this.enabled,
    required this.isRequired,
    required this.errorText,
    required this.onTap,
  });

  final String label;
  final RouteStopDraft? stop;
  final bool enabled;
  final bool isRequired;
  final String? errorText;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final place = stop?.place;
    return AppSelectField(
      label: label,
      placeholder: l.locationSearchTitle,
      icon: label == l.journeyFrom
          ? Icons.trip_origin_rounded
          : Icons.place_outlined,
      isRequired: isRequired,
      enabled: enabled,
      value: place == null ? null : placeLabel(place),
      secondary: place == null ? null : placeContext(context, place),
      errorText: errorText,
      onTap: onTap,
    );
  }
}

Future<DateTime?> _pickDateTime(BuildContext context, DateTime? initial) async {
  final now = DateTime.now();
  final seed = (initial == null || initial.isBefore(now)) ? now : initial;

  final date = await showDatePicker(
    context: context,
    initialDate: seed,
    firstDate: DateTime(now.year, now.month, now.day),
    lastDate: now.add(const Duration(days: 365)),
  );
  if (date == null || !context.mounted) return null;

  final time = await showTimePicker(
    context: context,
    initialTime: TimeOfDay.fromDateTime(seed),
  );
  if (time == null) return null;

  return DateTime(date.year, date.month, date.day, time.hour, time.minute);
}
