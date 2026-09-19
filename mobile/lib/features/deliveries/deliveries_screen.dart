/// Deliveries — everything this account is party to.
///
/// One tab, not two. An account that both sends and carries has one set of
/// deliveries in flight, and splitting them across separate destinations would
/// mean checking two places to answer one question. The role context reorders
/// this screen; it never hides half of it.
///
/// Journeys live here too, under their own heading. A traveller's journeys and
/// the parcels they are carrying are the same concern — "what am I committed
/// to" — and the product would be worse for making them navigate between two
/// screens to see it.
///
/// The three filters are states of *attention*, not of data: what is live,
/// what is stuck on you, and what is over. "Needs you" is the server's answer,
/// gathered in `attentionProvider`, not a rule invented here.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/deal.dart';
import '../../domain/delivery_request.dart';
import '../../domain/journey.dart';
import '../../domain/offer.dart';
import '../../l10n/app_localizations.dart';
import '../common/delivery_card.dart';
import '../common/status_copy.dart';
import '../requests/request_labels.dart';
import '../shell/app_shell.dart';

enum _Filter { active, awaitingYou, history }

class DeliveriesScreen extends ConsumerStatefulWidget {
  const DeliveriesScreen({super.key});

  @override
  ConsumerState<DeliveriesScreen> createState() => _DeliveriesScreenState();
}

class _DeliveriesScreenState extends ConsumerState<DeliveriesScreen> {
  _Filter _filter = _Filter.active;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final role = ref.watch(roleContextProvider);
    final deals = switch (_filter) {
      _Filter.active || _Filter.awaitingYou => ref.watch(activeDealsProvider),
      _Filter.history => ref.watch(historyDealsProvider),
    };
    final attention = ref.watch(attentionProvider);

    if (account == null) return const AppScaffold(body: SkeletonCardList());

    final attentionDealIds = attention
        .map((item) => item.dealId)
        .whereType<int>()
        .toSet();

    return AppScaffold(
      topBar: AppTopBar(
        title: l.deliveriesTitle,
        actions: const [NotificationBell()],
      ),
      body: RefreshIndicator(
        onRefresh: () async => refreshVolatileState(ref),
        child: AsyncView<List<Deal>>(
          value: deals,
          onRetry: () => switch (_filter) {
            _Filter.active ||
            _Filter.awaitingYou => ref.invalidate(activeDealsProvider),
            _Filter.history => ref.invalidate(historyDealsProvider),
          },
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (all) {
            final visible = _apply(all, attentionDealIds);

            return ListView(
              padding: AppScrollPadding.page(context),
              children: [
                AppSegmentedChoice<_Filter>(
                  selected: _filter,
                  onSelect: (value) => setState(() => _filter = value),
                  options: [
                    AppChoice(
                      value: _Filter.active,
                      label: l.deliveriesFilterActive,
                    ),
                    AppChoice(
                      value: _Filter.awaitingYou,
                      label: l.deliveriesFilterAwaitingYou,
                    ),
                    AppChoice(
                      value: _Filter.history,
                      label: l.deliveriesFilterHistory,
                    ),
                  ],
                ),
                const SizedBox(height: AppSpace.xl),

                if (visible.isEmpty)
                  _emptyFor(context, _filter)
                else
                  for (final deal in visible) ...[
                    DeliveryCard(
                      deal: deal,
                      viewerId: account.id,
                      needsYou: attentionDealIds.contains(deal.id),
                      needsYouLabel: attentionDealIds.contains(deal.id)
                          ? l.offerAwaitingYou
                          : null,
                      onTap: () => context.openDeal(deal.id),
                    ),
                    const SizedBox(height: AppSpace.md),
                  ],

                // Negotiations have no Deal yet, so they would otherwise be
                // invisible here — and a pending offer is exactly the sort of
                // thing a user comes to this screen to find.
                if (_filter != _Filter.history) ...[
                  const SizedBox(height: AppSpace.lg),
                  const _OpenNegotiations(),
                ],

                if (_filter != _Filter.awaitingYou) ...[
                  const SizedBox(height: AppSpace.lg),
                  if (role == RoleContext.sender)
                    _RequestsSection(showFinished: _filter == _Filter.history)
                  else
                    _JourneysSection(showFinished: _filter == _Filter.history),
                ],
              ],
            );
          },
        ),
      ),
    );
  }

  List<Deal> _apply(List<Deal> all, Set<int> attentionDealIds) =>
      switch (_filter) {
        _Filter.active =>
          all
              .where(
                (d) =>
                    d.activityState == ActivityState.unknown ||
                    d.activityState == ActivityState.active,
              )
              .toList(growable: false),
        _Filter.awaitingYou =>
          all
              .where((d) => attentionDealIds.contains(d.id))
              .toList(growable: false),
        _Filter.history =>
          all
              .where(
                (d) =>
                    d.activityState == ActivityState.unknown ||
                    d.activityState == ActivityState.completed ||
                    d.activityState == ActivityState.cancelled,
              )
              .toList(growable: false),
      };

  Widget _emptyFor(BuildContext context, _Filter filter) {
    final l = L.of(context);
    return switch (filter) {
      _Filter.active => AppEmptyState(
        title: l.deliveriesEmptyActiveTitle,
        body: l.deliveriesEmptyActiveBody,
        icon: Icons.inventory_2_outlined,
        compact: true,
      ),
      _Filter.awaitingYou => AppEmptyState(
        title: l.deliveriesEmptyAwaitingTitle,
        body: l.deliveriesEmptyAwaitingBody,
        icon: Icons.check_circle_outline_rounded,
        compact: true,
      ),
      _Filter.history => AppEmptyState(
        title: l.deliveriesEmptyHistoryTitle,
        body: l.deliveriesEmptyHistoryBody,
        icon: Icons.history_rounded,
        compact: true,
      ),
    };
  }
}

/// Matches still in negotiation — proposed, countered, waiting.
class _OpenNegotiations extends ConsumerWidget {
  const _OpenNegotiations();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final matches = ref.watch(matchesProvider);
    if (account == null) return const SizedBox.shrink();

    return AsyncView<List<Match>>(
      value: matches,
      onRetry: () => ref.invalidate(matchesProvider),
      loading: SizedBox.shrink,
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(matchesProvider),
      ),
      data: (all) {
        final open = all
            .where((m) => m.status.isNegotiating && !m.hasDeal)
            .toList(growable: false);
        if (open.isEmpty) return const SizedBox.shrink();

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // These are live negotiations awaiting somebody's move. The
            // heading used to read "Offer history", which told the sender the
            // one thing they are not: over.
            SectionHeader(title: l.deliveriesOpenOffersSection),
            for (final match in open) ...[
              _NegotiationRow(match: match, viewerId: account.id),
              const SizedBox(height: AppSpace.md),
            ],
          ],
        );
      },
    );
  }
}

class _NegotiationRow extends StatelessWidget {
  const _NegotiationRow({required this.match, required this.viewerId});

  final Match match;
  final int viewerId;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final awaitsMe = match.awaitsViewer(viewerId);
    final offer = match.latestOffer;
    final perspective = match.moneyPerspectiveFor(viewerId);
    final amount = perspective == null ? null : offer?.amountFor(perspective);

    return AppCard(
      onTap: () => context.openNegotiation(match.id),
      accent: awaitsMe ? StatusTone.action : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  match.counterpartyName(viewerId),
                  style: text.titleSmall,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: AppSpace.sm),
              if (offer != null)
                StatusPill(
                  label: awaitsMe
                      ? l.offerAwaitingYou
                      : offerStatusCopy(context, offer.status).label,
                  tone: awaitsMe
                      ? StatusTone.action
                      : offerStatusCopy(context, offer.status).tone,
                  icon: awaitsMe
                      ? Icons.reply_rounded
                      : offerStatusCopy(context, offer.status).icon,
                  compact: true,
                ),
            ],
          ),
          if (amount != null && perspective != null) ...[
            const SizedBox(height: AppSpace.sm),
            Row(
              children: [
                Expanded(
                  child: Text(
                    perspective.isSender ? l.moneyYouPay : l.moneyYouReceive,
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                  ),
                ),
                const SizedBox(width: AppSpace.md),
                MoneyText(
                  amount,
                  semanticPrefix: perspective.isSender
                      ? l.moneyYouPay
                      : l.moneyYouReceive,
                  size: 14,
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _RequestsSection extends ConsumerWidget {
  const _RequestsSection({required this.showFinished});

  final bool showFinished;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final requests = ref.watch(myRequestsProvider);
    final settled = ref.watch(settledRequestIdsProvider);

    return AsyncView<List<DeliveryRequest>>(
      value: requests,
      onRetry: () => ref.invalidate(myRequestsProvider),
      loading: () => const SkeletonCardList(count: 2),
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(myRequestsProvider),
      ),
      data: (all) {
        // A matched request keeps its `matched` status for the whole life of
        // the delivery, so finishing is read from the linked Deal's activity
        // state rather than from the request's own status.
        final rows = all
            .where(
              (r) =>
                  (r.status.isFinished || settled.contains(r.id)) ==
                  showFinished,
            )
            .toList(growable: false);
        if (rows.isEmpty) return const SizedBox.shrink();

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(title: l.deliveriesSenderSection),
            for (final request in rows) ...[
              AppCard(
                onTap: () => context.openRequest(request.id),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            request.title,
                            style: Theme.of(context).textTheme.titleSmall,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          const SizedBox(height: AppSpace.xs),
                          if (!requestHasRoute(request))
                            Text(
                              l.requestRouteNotRecorded,
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(
                                    color: context.colors.textSecondary,
                                  ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            )
                          else
                            RouteSummary(
                              from: requestPickupLabel(l, request),
                              to: requestDeliveryLabel(l, request),
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(
                                    color: context.colors.textSecondary,
                                  ),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(width: AppSpace.sm),
                    Builder(
                      builder: (context) {
                        final copy = requestStatusCopy(context, request.status);
                        return StatusPill(
                          label: copy.label,
                          tone: copy.tone,
                          icon: copy.icon,
                          compact: true,
                        );
                      },
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpace.md),
            ],
          ],
        );
      },
    );
  }
}

class _JourneysSection extends ConsumerWidget {
  const _JourneysSection({required this.showFinished});

  final bool showFinished;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final journeys = ref.watch(myJourneysProvider);

    return AsyncView<List<Journey>>(
      value: journeys,
      onRetry: () => ref.invalidate(myJourneysProvider),
      loading: () => const SkeletonCardList(count: 2),
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(myJourneysProvider),
      ),
      data: (all) {
        final rows = all
            .where((j) => j.status.isFinished == showFinished)
            .toList(growable: false);
        if (rows.isEmpty) return const SizedBox.shrink();

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(
              title: l.deliveriesJourneysSection,
              // Opens the journey composer, which creates a whole trip. "Add
              // a leg" named a step inside that screen, not the screen.
              actionLabel: showFinished ? null : l.journeyPostNew,
              onAction: showFinished ? null : () => context.openJourneyCreate(),
            ),
            for (final journey in rows) ...[
              JourneyCard(
                fromLabel: journey.startLocation?.coarseLabel ?? '',
                toLabel: journey.destinationLocation?.coarseLabel ?? '',
                status: journeyStatusCopy(context, journey.status),
                legCount: journey.legs.length,
                capacityKg: journey.narrowestCapacityKg,
                departureLabel: journey.firstDeparture == null
                    ? null
                    : LocaleFormats.dateTime(locale, journey.firstDeparture!),
                legsNeedingProof: journey.legsNeedingProof.length,
                onTap: () => context.openJourney(journey.id),
              ),
              const SizedBox(height: AppSpace.md),
            ],
          ],
        );
      },
    );
  }
}
