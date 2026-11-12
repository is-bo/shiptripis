/// The route part of the journey form: the stops and legs, the ferry lines
/// they depend on, and what the traveller carries.
///
/// Shared by the create and edit screens so the two can never drift apart. This
/// widget owns the one thing neither screen should: getting the server's ferry
/// lines into the [JourneyRouteDraft] and telling the traveller, plainly, when
/// they could not be had.
///
/// The ferry lines are deliberately a separate read. When it fails the editor
/// keeps working for flight and road legs and a notice says Sea is not
/// available right now, with a button to try again; a failed list never
/// blocks the form and never turns a ferry leg the traveller already has into
/// something else.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../design/components/forms.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/delivery_request.dart' show ItemCategory;
import '../../domain/transport_rules.dart';
import '../../l10n/app_localizations.dart';
import '../requests/request_labels.dart' show itemCategoryLabel;
import 'journey_route_draft.dart';
import 'journey_route_editor.dart';

class JourneyRouteSection extends ConsumerStatefulWidget {
  const JourneyRouteSection({
    required this.draft,
    required this.enabled,
    required this.showErrors,
    this.validateFutureDepartures = false,
    super.key,
  });

  final JourneyRouteDraft draft;
  final bool enabled;
  final bool showErrors;
  final bool validateFutureDepartures;

  @override
  ConsumerState<JourneyRouteSection> createState() =>
      _JourneyRouteSectionState();
}

class _JourneyRouteSectionState extends ConsumerState<JourneyRouteSection> {
  @override
  void initState() {
    super.initState();
    // Fires now with whatever is cached and again when the answer changes. The
    // draft only records the list; it never rewrites a leg because of it.
    ref.listenManual(
      seaCrossingsProvider,
      (_, next) => widget.draft.setSeaCrossings(next.value),
      fireImmediately: true,
    );
  }

  /// Sea matters only where a ferry could be chosen or already is, so the
  /// failure notice stays quiet for a route that is entirely European road.
  bool _seaCouldMatter(JourneyRouteDraft draft) {
    final stops = draft.stops;
    for (var i = 0; i < draft.segments.length; i++) {
      if (draft.segments[i].mode.isSea) return true;
      if (flightIsRequired(
        stops[i].place.countryCode,
        stops[i + 1].place.countryCode,
      )) {
        return true;
      }
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final crossings = ref.watch(seaCrossingsProvider);
    final failed = crossings.hasError && !crossings.hasValue;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.routeStopsTitle, subtitle: l.routeStopsHelp),
        ListenableBuilder(
          listenable: widget.draft,
          builder: (context, _) => failed && _seaCouldMatter(widget.draft)
              ? Padding(
                  padding: const EdgeInsets.only(bottom: AppSpace.lg),
                  child: InfoNotice(
                    title: l.routeSeaLinesFailedTitle,
                    message: l.routeSeaLinesFailedBody,
                    tone: StatusTone.waiting,
                    icon: Icons.directions_boat_outlined,
                    actionLabel: l.actionRetry,
                    onAction: crossings.isLoading
                        ? null
                        : () => ref.invalidate(seaCrossingsProvider),
                  ),
                )
              : const SizedBox.shrink(),
        ),
        JourneyRouteEditor(
          draft: widget.draft,
          enabled: widget.enabled,
          showErrors: widget.showErrors,
          validateFutureDepartures: widget.validateFutureDepartures,
        ),
        ListenableBuilder(
          listenable: widget.draft,
          builder: (context, _) => widget.draft.stops.length >= 2
              ? _CarrySection(draft: widget.draft, enabled: widget.enabled)
              : const SizedBox.shrink(),
        ),
      ],
    );
  }
}

/// What the traveller will and will not take.
///
/// Everything is on by default, so the section only asks for a decision when
/// someone wants to refuse something. The last remaining category cannot be
/// switched off: a journey that takes nothing is not a journey.
class _CarrySection extends StatelessWidget {
  const _CarrySection({required this.draft, required this.enabled});

  final JourneyRouteDraft draft;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return ListenableBuilder(
      listenable: draft,
      builder: (context, _) {
        final last =
            draft.refusedCategories.length >= carryableCategories.length - 1;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(title: l.routeCarryTitle, subtitle: l.routeCarryHelp),
            for (final category in carryableCategories)
              _CarryTile(
                category: category,
                carries: !draft.refusedCategories.contains(category),
                // The one category left on cannot be turned off.
                locked:
                    enabled &&
                    last &&
                    !draft.refusedCategories.contains(category),
                enabled: enabled,
                draft: draft,
                label: itemCategoryLabel(l, category),
              ),
            AppCheckTile(
              value: draft.acceptsFragile,
              title: l.routeCarryFragile,
              onChanged: enabled ? draft.setAcceptsFragile : (_) {},
            ),
            if (last)
              Padding(
                padding: const EdgeInsets.only(top: AppSpace.xs),
                child: Text(
                  l.routeCarryLastOne,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: context.colors.textSecondary,
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _CarryTile extends StatelessWidget {
  const _CarryTile({
    required this.category,
    required this.carries,
    required this.locked,
    required this.enabled,
    required this.draft,
    required this.label,
  });

  final ItemCategory category;
  final bool carries;
  final bool locked;
  final bool enabled;
  final JourneyRouteDraft draft;
  final String label;

  @override
  Widget build(BuildContext context) => AppCheckTile(
    value: carries,
    title: label,
    onChanged: !enabled || locked
        ? (_) {}
        : (value) => draft.setCarries(category, carries: value),
  );
}
