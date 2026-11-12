/// Browse trips, Browse requests and the People list.
///
/// Full lists behind Home's "Browse all" and "See all". They page lazily on the
/// server's own `next_offset`, filter by from, to and date with the canonical
/// place picker, and keep the filter bar on screen while a page loads.
///
/// The client never filters or sorts a row. A filter is sent to the server and
/// the answer is shown as it came; an empty answer is a designed state with a
/// way forward, not a blank list.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/discovery_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/canonical_place.dart';
import '../../domain/public_discovery.dart';
import '../../l10n/app_localizations.dart';
import 'discovery_actions.dart';
import 'discovery_widgets.dart';

// ---------------------------------------------------------------------------
// Trips
// ---------------------------------------------------------------------------

class BrowseTripsScreen extends ConsumerWidget {
  const BrowseTripsScreen({
    this.corridor,
    this.alertId,
    this.focusJourneyId,
    super.key,
  });

  final Corridor? corridor;

  /// The route alert that sent the member here: its route becomes the filter.
  final int? alertId;

  /// The trip that triggered the alert. Opened once the list holds it.
  final int? focusJourneyId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    return _BrowseView<TripCard>(
      title: l.browseTripsTitle,
      corridor: corridor,
      alertId: alertId,
      focusId: focusJourneyId,
      feed: (ref, filter) => ref.watch(tripFeedProvider(filter)),
      loadMore: (ref, filter) =>
          ref.read(tripFeedProvider(filter).notifier).loadMore(),
      reload: (ref, filter) => ref.invalidate(tripFeedProvider(filter)),
      idOf: (card) => card.journeyId,
      itemBuilder: (context, card) => TripListingCard(
        card: card,
        onTap: () => showTripPreview(context, card),
      ),
      openItem: showTripPreview,
      alertWatches: AlertWatch.trips,
      emptyTitle: l.browseTripsEmptyTitle,
      emptyBody: l.browseTripsEmptyBody,
      emptyAction: l.browseTripsEmptyAction,
      onEmptyAction: () => context.openRequestCreate(),
      emptyIcon: Icons.flight_takeoff_rounded,
    );
  }
}

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

class BrowseRequestsScreen extends ConsumerWidget {
  const BrowseRequestsScreen({
    this.corridor,
    this.alertId,
    this.focusRequestId,
    super.key,
  });

  final Corridor? corridor;
  final int? alertId;
  final int? focusRequestId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    return _BrowseView<RequestCard>(
      title: l.browseRequestsTitle,
      corridor: corridor,
      alertId: alertId,
      focusId: focusRequestId,
      feed: (ref, filter) => ref.watch(requestFeedProvider(filter)),
      loadMore: (ref, filter) =>
          ref.read(requestFeedProvider(filter).notifier).loadMore(),
      reload: (ref, filter) => ref.invalidate(requestFeedProvider(filter)),
      idOf: (card) => card.requestId,
      itemBuilder: (context, card) => RequestListingCard(
        card: card,
        onTap: () => showRequestPreview(context, card),
      ),
      openItem: showRequestPreview,
      alertWatches: AlertWatch.requests,
      emptyTitle: l.browseRequestsEmptyTitle,
      emptyBody: l.browseRequestsEmptyBody,
      emptyAction: l.browseRequestsEmptyAction,
      onEmptyAction: () => context.openJourneyCreate(),
      emptyIcon: Icons.inventory_2_outlined,
    );
  }
}

// ---------------------------------------------------------------------------
// The shared list
// ---------------------------------------------------------------------------

class _BrowseView<T> extends ConsumerStatefulWidget {
  const _BrowseView({
    required this.title,
    required this.corridor,
    required this.alertId,
    required this.focusId,
    required this.feed,
    required this.loadMore,
    required this.reload,
    required this.idOf,
    required this.itemBuilder,
    required this.openItem,
    required this.alertWatches,
    required this.emptyTitle,
    required this.emptyBody,
    required this.emptyAction,
    required this.onEmptyAction,
    required this.emptyIcon,
  });

  final String title;
  final Corridor? corridor;
  final int? alertId;
  final int? focusId;
  final AsyncValue<DiscoveryFeed<T>> Function(WidgetRef, BrowseFilter) feed;
  final Future<void> Function(WidgetRef, BrowseFilter) loadMore;
  final void Function(WidgetRef, BrowseFilter) reload;
  final int Function(T) idOf;
  final Widget Function(BuildContext, T) itemBuilder;
  final Future<void> Function(BuildContext, T) openItem;
  final AlertWatch alertWatches;
  final String emptyTitle;
  final String emptyBody;
  final String emptyAction;
  final VoidCallback onEmptyAction;
  final IconData emptyIcon;

  @override
  ConsumerState<_BrowseView<T>> createState() => _BrowseViewState<T>();
}

class _BrowseViewState<T> extends ConsumerState<_BrowseView<T>> {
  late BrowseFilter _filter = widget.corridor?.filter ?? const BrowseFilter();

  /// A route alert's own route is the filter. Until the alert is read, nothing
  /// is fetched: an unfiltered first page would be thrown away a moment later.
  late bool _alertResolved = widget.alertId == null;
  bool _focusDone = false;

  void _resolveAlert(AsyncValue<List<RouteAlert>> alerts) {
    if (_alertResolved) return;
    if (!alerts.hasValue && !alerts.hasError) return;
    final alert = alerts.value
        ?.where((a) => a.id == widget.alertId)
        .firstOrNull;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      setState(() {
        _alertResolved = true;
        if (alert != null) {
          _filter = BrowseFilter(
            origin: alert.origin,
            destination: alert.destination,
          );
        }
      });
    });
  }

  void _openFocus(DiscoveryFeed<T> feed) {
    final focus = widget.focusId;
    if (focus == null || _focusDone) return;
    _focusDone = true;
    final item = feed.items.where((i) => widget.idOf(i) == focus).firstOrNull;
    if (item == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) unawaited(widget.openItem(context, item));
    });
  }

  Future<void> _pickPlace({required bool origin}) async {
    final l = L.of(context);
    final current = origin ? _filter.origin : _filter.destination;
    final CanonicalPlace? chosen = await context.pickCanonicalPlace(
      title: origin ? l.browseFilterFrom : l.browseFilterTo,
      current: current?.toLocality(),
    );
    if (chosen == null || !mounted) return;
    final city = PlaceRef.fromCanonical(chosen);
    setState(() {
      // A city is narrower than a country: choosing one replaces the country
      // that the Home corridor chip set on the same side.
      _filter = BrowseFilter(
        originCountry: origin ? null : _filter.originCountry,
        destinationCountry: origin ? _filter.destinationCountry : null,
        origin: origin ? city : _filter.origin,
        destination: origin ? _filter.destination : city,
        departingAfter: _filter.departingAfter,
      );
    });
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final chosen = await showDatePicker(
      context: context,
      initialDate: _filter.departingAfter ?? today,
      firstDate: today,
      lastDate: today.add(const Duration(days: 365)),
    );
    if (chosen == null || !mounted) return;
    setState(() => _filter = _filter.copyWith(departingAfter: chosen));
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    if (!_alertResolved) {
      _resolveAlert(ref.watch(routeAlertsProvider).ofCurrentAccount);
      return AppScaffold(
        topBar: AppTopBar(title: widget.title, showBack: true),
        body: ListView(
          padding: AppScrollPadding.page(context),
          children: const [SkeletonCardList(count: 3)],
        ),
      );
    }

    final feed = widget.feed(ref, _filter);

    return AppScaffold(
      topBar: AppTopBar(title: widget.title, showBack: true),
      body: Column(
        children: [
          _FilterBar(
            filter: _filter,
            onFrom: () => _pickPlace(origin: true),
            onTo: () => _pickPlace(origin: false),
            onDate: _pickDate,
            onClearFrom: () => setState(
              () => _filter = BrowseFilter(
                destinationCountry: _filter.destinationCountry,
                destination: _filter.destination,
                departingAfter: _filter.departingAfter,
              ),
            ),
            onClearTo: () => setState(
              () => _filter = BrowseFilter(
                originCountry: _filter.originCountry,
                origin: _filter.origin,
                departingAfter: _filter.departingAfter,
              ),
            ),
            onClearDate: () =>
                setState(() => _filter = _filter.copyWith(clearDate: true)),
          ),
          Expanded(
            child: DiscoverySection<DiscoveryFeed<T>>(
              value: feed,
              onRetry: () => widget.reload(ref, _filter),
              skeleton: ListView(
                padding: AppScrollPadding.page(context),
                children: const [SkeletonCardList(count: 4)],
              ),
              data: (data) {
                _openFocus(data);
                return RefreshIndicator(
                  onRefresh: () async => widget.reload(ref, _filter),
                  child: _list(context, data, l),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _list(BuildContext context, DiscoveryFeed<T> feed, L l) {
    if (feed.disabled) {
      return AppEmptyState(
        title: l.discoveryListingsOffTitle,
        body: l.discoveryListingsOff,
        icon: Icons.pause_circle_outline_rounded,
      );
    }
    if (feed.items.isEmpty) {
      return _filter.isEmpty
          ? AppEmptyState(
              title: widget.emptyTitle,
              body: widget.emptyBody,
              icon: widget.emptyIcon,
              actionLabel: widget.emptyAction,
              onAction: widget.onEmptyAction,
            )
          : AppEmptyState(
              title: l.browseNoMatchTitle,
              body: l.browseNoMatchBody,
              icon: Icons.search_off_rounded,
              actionLabel: l.browseClearFilters,
              onAction: () => setState(() => _filter = const BrowseFilter()),
            );
    }
    return _PagedList<T>(
      feed: feed,
      itemBuilder: widget.itemBuilder,
      onLoadMore: () => widget.loadMore(ref, _filter),
    );
  }
}

/// A lazy list that asks for the next page when the end comes into reach.
class _PagedList<T> extends StatelessWidget {
  const _PagedList({
    required this.feed,
    required this.itemBuilder,
    required this.onLoadMore,
  });

  final DiscoveryFeed<T> feed;
  final Widget Function(BuildContext, T) itemBuilder;
  final Future<void> Function() onLoadMore;

  @override
  Widget build(BuildContext context) =>
      NotificationListener<ScrollNotification>(
        onNotification: (notification) {
          if (feed.hasMore &&
              !feed.loadingMore &&
              feed.loadMoreError == null &&
              notification.metrics.pixels >=
                  notification.metrics.maxScrollExtent - 240) {
            unawaited(onLoadMore());
          }
          return false;
        },
        child: ListView.builder(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: AppScrollPadding.page(context, top: AppSpace.sm),
          itemCount: feed.items.length + 1,
          itemBuilder: (context, index) {
            if (index == feed.items.length) {
              return FeedFooter(
                loadingMore: feed.loadingMore,
                error: feed.loadMoreError,
                onRetry: () => unawaited(onLoadMore()),
              );
            }
            return Padding(
              padding: const EdgeInsets.only(bottom: AppSpace.md),
              child: itemBuilder(context, feed.items[index]),
            );
          },
        ),
      );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

class _FilterBar extends StatelessWidget {
  const _FilterBar({
    required this.filter,
    required this.onFrom,
    required this.onTo,
    required this.onDate,
    required this.onClearFrom,
    required this.onClearTo,
    required this.onClearDate,
  });

  final BrowseFilter filter;
  final VoidCallback onFrom;
  final VoidCallback onTo;
  final VoidCallback onDate;
  final VoidCallback onClearFrom;
  final VoidCallback onClearTo;
  final VoidCallback onClearDate;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    final from =
        filter.origin?.label ??
        (filter.originCountry == null
            ? null
            : countryName(l, filter.originCountry!));
    final to =
        filter.destination?.label ??
        (filter.destinationCountry == null
            ? null
            : countryName(l, filter.destinationCountry!));
    final date = filter.departingAfter;

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(
        AppSpace.gutter,
        AppSpace.sm,
        AppSpace.gutter,
        AppSpace.xs,
      ),
      child: Row(
        children: [
          _FilterPill(
            icon: Icons.trip_origin_rounded,
            label: l.browseFilterFrom,
            value: from,
            onTap: onFrom,
            onClear: onClearFrom,
          ),
          const SizedBox(width: AppSpace.sm),
          _FilterPill(
            icon: Icons.place_outlined,
            label: l.browseFilterTo,
            value: to,
            onTap: onTo,
            onClear: onClearTo,
          ),
          const SizedBox(width: AppSpace.sm),
          _FilterPill(
            icon: Icons.event_outlined,
            label: l.browseFilterDate,
            value: date == null ? null : LocaleFormats.dayMonth(locale, date),
            onTap: onDate,
            onClear: onClearDate,
          ),
        ],
      ),
    );
  }
}

class _FilterPill extends StatelessWidget {
  const _FilterPill({
    required this.icon,
    required this.label,
    required this.value,
    required this.onTap,
    required this.onClear,
  });

  final IconData icon;
  final String label;
  final String? value;
  final VoidCallback onTap;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final active = value != null;
    final spoken = active ? '$label: $value' : label;

    return Material(
      color: active ? c.brandSoft : c.surface,
      borderRadius: AppRadius.rPill,
      child: Container(
        constraints: const BoxConstraints(minHeight: AppSpace.minTapTarget),
        decoration: BoxDecoration(
          borderRadius: AppRadius.rPill,
          border: Border.all(color: active ? c.brandInk : c.hairline),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Semantics(
              button: true,
              label: spoken,
              excludeSemantics: true,
              onTap: onTap,
              child: InkWell(
                onTap: onTap,
                borderRadius: AppRadius.rPill,
                child: Padding(
                  padding: EdgeInsetsDirectional.only(
                    start: AppSpace.lg,
                    end: active ? AppSpace.xs : AppSpace.lg,
                    top: AppSpace.sm,
                    bottom: AppSpace.sm,
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        icon,
                        size: 16,
                        color: active ? c.brandInk : c.textTertiary,
                      ),
                      const SizedBox(width: AppSpace.sm),
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 160),
                        child: Text(
                          value ?? label,
                          style: text.labelLarge?.copyWith(
                            color: active ? c.brandInk : c.textSecondary,
                            fontWeight: active
                                ? FontWeight.w700
                                : FontWeight.w500,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            if (active)
              AppIconButton(
                icon: Icons.close_rounded,
                label: l.browseClearFilter(label),
                onPressed: onClear,
              ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// People
// ---------------------------------------------------------------------------

/// Everyone who opted in to a public profile on the side the viewer looks at.
class BrowsePeopleScreen extends ConsumerWidget {
  const BrowsePeopleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final isSender = ref.watch(roleContextProvider) == RoleContext.sender;
    final feed = ref.watch(peopleFeedProvider(isSender));

    return AppScaffold(
      topBar: AppTopBar(
        title: isSender ? l.homePeopleSenderTitle : l.homePeopleTravelerTitle,
        showBack: true,
      ),
      body: DiscoverySection<DiscoveryFeed<ProfileCard>>(
        value: feed,
        onRetry: () => ref.invalidate(peopleFeedProvider(isSender)),
        skeleton: ListView(
          padding: AppScrollPadding.page(context),
          children: const [SkeletonCardList(count: 4)],
        ),
        data: (data) {
          if (data.disabled) {
            return AppEmptyState(
              title: l.discoveryProfilesOffTitle,
              body: l.discoveryProfilesOff,
              icon: Icons.pause_circle_outline_rounded,
            );
          }
          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(peopleFeedProvider(isSender)),
            child: data.items.isEmpty
                ? AppEmptyState(
                    title: l.homePeopleEmptyTitle,
                    body: l.homePeopleEmptyBody,
                    icon: Icons.groups_2_outlined,
                  )
                : _PagedList<ProfileCard>(
                    feed: data,
                    onLoadMore: () => ref
                        .read(peopleFeedProvider(isSender).notifier)
                        .loadMore(),
                    itemBuilder: (context, card) => ProfileTile(
                      card: card,
                      width: null,
                      onTap: card.id == null
                          ? null
                          : () => context.openPerson(card.id!),
                    ),
                  ),
          );
        },
      ),
    );
  }
}
