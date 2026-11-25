/// Profile → Route alerts.
///
/// A route alert is a standing question: "tell me when a trip, or a request,
/// appears on this route". The server fans it out and caps it at one
/// notification per alert every six hours, so this screen only lists the
/// member's alerts, adds one and removes one. Following one person is created
/// from their page and shows here with their name.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/discovery_state.dart';
import '../../app/router.dart';
import '../../data/discovery_repository.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/public_discovery.dart';
import '../../l10n/app_localizations.dart';
import '../common/traveler_candidate_card.dart' show travelerInitial;
import 'discovery_actions.dart';
import 'discovery_widgets.dart';

class AlertsScreen extends ConsumerWidget {
  const AlertsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final alerts = ref.watch(routeAlertsProvider);

    return AppScaffold(
      topBar: AppTopBar(
        title: l.alertsTitle,
        showBack: true,
        actions: [
          AppIconButton(
            icon: Icons.add_rounded,
            label: l.alertAdd,
            onPressed: () => _add(context, ref),
          ),
        ],
      ),
      body: DiscoverySection<List<RouteAlert>>(
        value: alerts,
        onRetry: () => ref.invalidate(routeAlertsProvider),
        skeleton: ListView(
          padding: AppScrollPadding.page(context),
          children: const [SkeletonCardList(count: 3)],
        ),
        data: (data) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(routeAlertsProvider),
          child: data.isEmpty
              ? ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  children: [
                    AppEmptyState(
                      title: l.alertsEmptyTitle,
                      body: l.alertsEmptyBody,
                      icon: Icons.notifications_none_rounded,
                      actionLabel: l.alertAdd,
                      onAction: () => _add(context, ref),
                    ),
                  ],
                )
              : ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: AppScrollPadding.page(context),
                  children: [
                    Text(
                      l.alertsIntro,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: context.colors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: AppSpace.lg),
                    for (final alert in data) ...[
                      _AlertCard(alert: alert),
                      const SizedBox(height: AppSpace.md),
                    ],
                  ],
                ),
        ),
      ),
    );
  }

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final created = await showAppSheet<bool>(
      context,
      fullHeight: false,
      builder: (_) => const _AddAlertSheet(),
    );
    if (created == true) ref.invalidate(routeAlertsProvider);
  }
}

class _AlertCard extends ConsumerStatefulWidget {
  const _AlertCard({required this.alert});

  final RouteAlert alert;

  @override
  ConsumerState<_AlertCard> createState() => _AlertCardState();
}

class _AlertCardState extends ConsumerState<_AlertCard> {
  bool _busy = false;

  void _open() {
    final alert = widget.alert;
    final person = alert.subjectProfileId;
    if (person != null) {
      context.openPerson(person);
    } else if (alert.watches == AlertWatch.trips) {
      context.openBrowseTrips(alertId: alert.id);
    } else {
      context.openBrowseRequests(alertId: alert.id);
    }
  }

  Future<void> _remove() async {
    final l = L.of(context);
    setState(() => _busy = true);
    try {
      await ref.read(discoveryRepositoryProvider).deleteAlert(widget.alert.id);
      ref.invalidate(routeAlertsProvider);
      if (mounted) AppSnack.success(context, l.alertRemoved);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _busy = false);
      AppSnack.failure(
        context,
        error,
        fallback: discoveryFailureMessage(context, error),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final alert = widget.alert;
    final stops = placeStops([alert.origin, alert.destination]);
    final watching = alert.followsPerson
        ? l.alertFollowing(alert.subjectName ?? '')
        : alert.watches == AlertWatch.trips
        ? l.alertWatchesTrips
        : l.alertWatchesRequests;

    return AppCard(
      onTap: _busy ? null : _open,
      padding: const EdgeInsetsDirectional.only(
        start: AppSpace.md,
        end: AppSpace.xs,
      ),
      semanticLabel:
          '$watching, '
          '${routeSemanticLabel(stops: stops, locale: Localizations.localeOf(context))}',
      child: Row(
        children: [
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  InlineRoute(
                    stops: stops,
                    style: text.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: AppSpace.xs),
                  Row(
                    children: [
                      if (alert.followsPerson) ...[
                        AppAvatar(
                          initials: travelerInitial(alert.subjectName ?? ''),
                          name: alert.subjectName ?? '',
                          photo: alert.subjectPhoto,
                          size: 20,
                        ),
                        const SizedBox(width: AppSpace.sm),
                      ],
                      Expanded(
                        child: Text(
                          watching,
                          style: text.bodySmall?.copyWith(
                            color: c.textSecondary,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          AppIconButton(
            icon: Icons.delete_outline_rounded,
            label: l.alertRemoveA11y(
              '${alert.origin.label} → ${alert.destination.label}',
            ),
            onPressed: _busy ? null : _remove,
          ),
        ],
      ),
    );
  }
}

/// Create a route alert: what to watch, and between which two cities.
class _AddAlertSheet extends ConsumerStatefulWidget {
  const _AddAlertSheet();

  @override
  ConsumerState<_AddAlertSheet> createState() => _AddAlertSheetState();
}

class _AddAlertSheetState extends ConsumerState<_AddAlertSheet> {
  AlertWatch _watches = AlertWatch.trips;
  PlaceRef? _origin;
  PlaceRef? _destination;
  bool _busy = false;
  String? _error;

  Future<void> _pick({required bool origin}) async {
    final l = L.of(context);
    final place = await context.pickCanonicalPlace(
      title: origin ? l.browseFilterFrom : l.browseFilterTo,
      current: (origin ? _origin : _destination)?.toLocality(),
    );
    if (place == null || !mounted) return;
    setState(() {
      final city = PlaceRef.fromCanonical(place);
      if (origin) {
        _origin = city;
      } else {
        _destination = city;
      }
      _error = null;
    });
  }

  Future<void> _create() async {
    final origin = _origin;
    final destination = _destination;
    if (origin == null || destination == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(discoveryRepositoryProvider)
          .createAlert(
            watches: _watches,
            originPlaceId: origin.placeId,
            destinationPlaceId: destination.placeId,
          );
      if (mounted) Navigator.of(context).pop(true);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = discoveryFailureMessage(context, error);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final ready = _origin != null && _destination != null;

    return AppSheet(
      title: l.alertAddTitle,
      subtitle: l.alertAddSubtitle,
      footer: AppButton(
        label: l.alertCreate,
        isLoading: _busy,
        onPressed: ready && !_busy ? _create : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppSegmentedChoice<AlertWatch>(
            label: l.alertWatchLabel,
            selected: _watches,
            onSelect: (value) => setState(() => _watches = value),
            options: [
              AppChoice(
                value: AlertWatch.trips,
                label: l.alertWatchesTrips,
                icon: Icons.flight_takeoff_rounded,
              ),
              AppChoice(
                value: AlertWatch.requests,
                label: l.alertWatchesRequests,
                icon: Icons.inventory_2_outlined,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.lg),
          AppSelectField(
            label: l.browseFilterFrom,
            placeholder: l.alertPickCity,
            value: _origin?.label,
            icon: Icons.trip_origin_rounded,
            onTap: () => _pick(origin: true),
          ),
          const SizedBox(height: AppSpace.md),
          AppSelectField(
            label: l.browseFilterTo,
            placeholder: l.alertPickCity,
            value: _destination?.label,
            icon: Icons.place_outlined,
            onTap: () => _pick(origin: false),
          ),
          if (_error != null) ...[
            const SizedBox(height: AppSpace.md),
            InfoNotice(message: _error!, icon: Icons.info_outline_rounded),
          ],
        ],
      ),
    );
  }
}
