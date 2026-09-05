/// The negotiation on one match.
///
/// ## The rule this screen exists to obey
///
/// **It never decides whose turn it is.** The server publishes
/// `awaiting_party`, `awaiting_user_id` and a per-viewer `allowed_actions` on
/// every offer, and every button here is gated on exactly that. Recomputing
/// the state machine locally is how a client ends up offering "Accept" on an
/// offer the user proposed themselves, or a moment after a race has closed it.
///
/// The consequence is that a stale screen degrades safely: worst case the
/// server refuses, the refusal carries a machine code, and the screen refreshes
/// and explains rather than insisting.
///
/// The sender proposes first in V1. A traveller therefore never sees a
/// "propose" affordance here — only accept, counter or decline on what arrived.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/money/money.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/offer.dart';
import '../../domain/money_perspective.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../common/status_copy.dart';

class NegotiationScreen extends ConsumerStatefulWidget {
  const NegotiationScreen({required this.matchId, super.key});

  final int matchId;

  @override
  ConsumerState<NegotiationScreen> createState() => _NegotiationScreenState();
}

class _NegotiationScreenState extends ConsumerState<NegotiationScreen> {
  bool _busy = false;

  Future<void> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } on ApiException catch (error) {
      if (!mounted) return;
      // A stale-state refusal means this screen's picture of the world moved
      // on. Refreshing is the fix, and the explanation comes from the code.
      if (error.code.impliesStaleClientState) refreshVolatileState(ref);
      AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _accept(Offer offer) async {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final account = ref.read(accountProvider);
    final match = ref.read(matchDetailProvider(widget.matchId)).value;
    if (account == null || match == null) return;

    final perspective = match.moneyPerspectiveFor(account.id);
    if (perspective == null) return;
    final amount = offer.amountFor(perspective);
    final isSender = perspective.isSender;
    final confirmed = await confirmAction(
      context,
      title: amount == null
          ? l.offerAccept
          : isSender
          ? l.offerAcceptSenderConfirmTitle(amount.format(locale))
          : l.offerAcceptTravelerConfirmTitle(amount.format(locale)),
      body: isSender ? l.offerAcceptSenderBody : l.offerAcceptTravelerBody,
      confirmLabel: l.offerAccept,
    );
    if (!confirmed || !mounted) return;

    await _run(() async {
      final deal = await ref.read(matchingRepositoryProvider).accept(offer.id);
      if (!mounted) return;
      refreshVolatileState(ref);
      // The sender's next step is paying; the traveller's is waiting. Both
      // belong on the deal, so send the sender straight to the payment screen
      // and the traveller to the deal itself.
      if (isSender) {
        context
          ..pop()
          ..openDealPayment(deal.id);
      } else {
        context
          ..pop()
          ..openDeal(deal.id);
      }
    });
  }

  Future<void> _decline(Offer offer) async {
    final l = L.of(context);
    final confirmed = await confirmAction(
      context,
      title: l.offerDeclineConfirmTitle,
      body: l.offerDeclineConfirmBody,
      confirmLabel: l.offerDecline,
      isDestructive: true,
    );
    if (!confirmed || !mounted) return;
    await _run(() async {
      await ref.read(matchingRepositoryProvider).decline(offer.id);
      if (!mounted) return;
      refreshVolatileState(ref);
      ref.invalidate(matchOffersProvider(widget.matchId));
    });
  }

  Future<void> _withdraw(Offer offer) async {
    await _run(() async {
      await ref.read(matchingRepositoryProvider).withdraw(offer.id);
      if (!mounted) return;
      refreshVolatileState(ref);
      ref.invalidate(matchOffersProvider(widget.matchId));
    });
  }

  Future<void> _counter(Offer offer) async {
    final account = ref.read(accountProvider);
    final match = ref.read(matchDetailProvider(widget.matchId)).value;
    if (account == null || match == null) return;
    final perspective = match.moneyPerspectiveFor(account.id);
    if (perspective == null) return;

    final cents = await showAppSheet<int>(
      context,
      builder: (sheetContext) => _CounterSheet(
        current: offer.travelerReward,
        perspective: perspective,
      ),
    );
    if (cents == null || !mounted) return;

    await _run(() async {
      await ref
          .read(matchingRepositoryProvider)
          .counter(offerId: offer.id, travelerRewardEurCents: cents);
      if (!mounted) return;
      refreshVolatileState(ref);
      ref.invalidate(matchOffersProvider(widget.matchId));
    });
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final match = ref.watch(matchDetailProvider(widget.matchId));
    final offers = ref.watch(matchOffersProvider(widget.matchId));

    return AppScaffold(
      topBar: AppTopBar(title: l.offerHistoryTitle, showBack: true),
      body: AsyncView<Match>(
        value: match,
        onRetry: () => ref.invalidate(matchDetailProvider(widget.matchId)),
        loading: () => const Padding(
          padding: EdgeInsets.all(AppSpace.gutter),
          child: SkeletonDetail(),
        ),
        data: (data) {
          if (account == null) return const SkeletonDetail();
          final perspective = data.moneyPerspectiveFor(account.id);
          if (perspective == null) return const SizedBox.shrink();
          final current = data.latestOffer;

          return RefreshIndicator(
            onRefresh: () async {
              ref
                ..invalidate(matchDetailProvider(widget.matchId))
                ..invalidate(matchOffersProvider(widget.matchId));
            },
            child: ListView(
              padding: AppScrollPadding.pageWithFooter(context),
              children: [
                _Header(match: data, viewerId: account.id),
                const SizedBox(height: AppSpace.xl),

                if (current == null)
                  AppEmptyState(
                    title: l.offerEmptyTitle,
                    body: l.offerEmptyBody,
                    icon: Icons.local_offer_outlined,
                    compact: true,
                  )
                else ...[
                  _CurrentOffer(
                    offer: current,
                    viewerId: account.id,
                    perspective: perspective,
                  ),
                  const SizedBox(height: AppSpace.xl),
                ],

                _History(
                  matchId: widget.matchId,
                  offers: offers,
                  perspective: perspective,
                ),
              ],
            ),
          );
        },
      ),
      footer: _Actions(
        matchId: widget.matchId,
        busy: _busy,
        onAccept: _accept,
        onCounter: _counter,
        onDecline: _decline,
        onWithdraw: _withdraw,
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.match, required this.viewerId});

  final Match match;
  final int viewerId;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final parcel = match.parcel;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              AppAvatar(
                initials: initialsFor(match.counterpartyName(viewerId)),
                name: match.counterpartyName(viewerId),
              ),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: Text(
                  match.counterpartyName(viewerId),
                  style: text.titleSmall,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          if (parcel?.origin != null && parcel?.destination != null) ...[
            const SizedBox(height: AppSpace.lg),
            // Coarse labels only: locations stay city-level until the deal is
            // funded, and this screen is by definition before that.
            RouteSummary(
              from: parcel!.origin!.coarseLabel,
              to: parcel.destination!.coarseLabel,
            ),
          ],
          if (parcel?.actualWeightKg != null) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              formatWeight(context, parcel!.actualWeightKg),
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
          ],
          if (match.matchedDistanceBand != null) ...[
            const SizedBox(height: AppSpace.xs),
            Text(
              formatDistanceBand(context, match.matchedDistanceBand),
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],
        ],
      ),
    );
  }
}

class _CurrentOffer extends StatelessWidget {
  const _CurrentOffer({
    required this.offer,
    required this.viewerId,
    required this.perspective,
  });

  final Offer offer;
  final int viewerId;
  final MoneyPerspective perspective;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final reward = offer.travelerReward;
    final fee = offer.platformFee;
    final total = offer.senderTotal;
    final isSender = perspective.isSender;

    final mine = offer.wasProposedBy(viewerId);
    final heading = mine && offer.parentOfferId != null
        ? l.offerYourCounterTitle
        : switch ((perspective, mine)) {
            (MoneyPerspective.sender, true) => l.offerYourOfferTitle,
            (MoneyPerspective.sender, false) => l.offerTravelerCounterTitle,
            (MoneyPerspective.traveler, true) => l.offerYourCounterTitle,
            (MoneyPerspective.traveler, false) => l.offerSenderOfferTitle,
          };

    final awaitingLabel = switch (offer.awaitingParty) {
      OfferParty.sender =>
        offer.isAwaiting(viewerId) ? l.offerAwaitingYou : l.offerAwaitingSender,
      OfferParty.traveler =>
        offer.isAwaiting(viewerId)
            ? l.offerAwaitingYou
            : l.offerAwaitingTraveler,
      OfferParty.unknown => offerStatusCopy(context, offer.status).label,
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                heading,
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            StatusPill(
              label: awaitingLabel,
              tone: offer.isAwaiting(viewerId)
                  ? StatusTone.action
                  : offerStatusCopy(context, offer.status).tone,
              icon: offer.isAwaiting(viewerId)
                  ? Icons.reply_rounded
                  : offerStatusCopy(context, offer.status).icon,
              compact: true,
            ),
          ],
        ),
        const SizedBox(height: AppSpace.lg),

        // Every figure is a server field. The sender gets the payment build-up;
        // the traveller gets the one amount they earn and no checkout framing.
        if (isSender)
          MoneyBreakdown(
            title: l.moneyBreakdownTitle,
            explainer: l.moneyRewardNotReduced,
            lines: [
              if (reward != null)
                MoneyLine(label: l.moneyTravelerReceives, amount: reward),
              if (fee != null)
                MoneyLine(label: l.moneyPlatformFee, amount: fee),
              if (total != null)
                MoneyLine.total(label: l.moneyYouPay, amount: total),
            ],
          )
        else if (reward != null)
          AppCard(
            child: MoneyHero(amount: reward, label: l.moneyYouReceive),
          ),

        if (offer.note.isNotEmpty) ...[
          const SizedBox(height: AppSpace.lg),
          AppInsetGroup(
            child: Text(
              offer.note,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ),
        ],
      ],
    );
  }
}

class _History extends ConsumerWidget {
  const _History({
    required this.matchId,
    required this.offers,
    required this.perspective,
  });

  final int matchId;
  final AsyncValue<List<Offer>> offers;
  final MoneyPerspective perspective;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);
    final account = ref.watch(accountProvider);

    return AsyncView<List<Offer>>(
      value: offers,
      onRetry: () => ref.invalidate(matchOffersProvider(matchId)),
      loading: SizedBox.shrink,
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(matchOffersProvider(matchId)),
      ),
      data: (all) {
        // The newest offer is already shown in full above.
        final past = all.skip(1).toList(growable: false);
        if (past.isEmpty || account == null) return const SizedBox.shrink();

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(title: l.offerHistoryTitle),
            for (final offer in past)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpace.md),
                child: Row(
                  children: [
                    StatusDot(
                      tone: offerStatusCopy(context, offer.status).tone,
                    ),
                    const SizedBox(width: AppSpace.md),
                    Expanded(
                      child: Text(
                        _historyLabel(
                          l,
                          offer,
                          perspective: perspective,
                          viewerId: account.id,
                          locale: locale,
                        ),
                        style: Theme.of(
                          context,
                        ).textTheme.bodySmall?.copyWith(color: c.textSecondary),
                      ),
                    ),
                    Text(
                      offerStatusCopy(context, offer.status).label,
                      style: Theme.of(
                        context,
                      ).textTheme.labelSmall?.copyWith(color: c.textTertiary),
                    ),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }

  static String _historyLabel(
    L l,
    Offer offer, {
    required MoneyPerspective perspective,
    required int viewerId,
    required Locale locale,
  }) {
    final mine = offer.wasProposedBy(viewerId);
    if (perspective.isSender) {
      final amount = mine ? offer.senderTotal : offer.travelerReward;
      if (amount == null) {
        return mine ? l.offerYourOfferTitle : l.offerTravelerCounterTitle;
      }
      return mine
          ? l.offerYouWouldPay(amount.format(locale))
          : l.offerTravelerAsks(amount.format(locale));
    }

    final amount = offer.travelerReward;
    if (amount == null) {
      return mine ? l.offerYourCounterTitle : l.offerSenderOfferTitle;
    }
    return mine
        ? l.offerYouWouldReceive(amount.format(locale))
        : l.offerSenderOffers(amount.format(locale));
  }
}

/// The action bar.
///
/// Rendered entirely from `allowed_actions`. If the server sends nothing, this
/// shows nothing — which is the correct answer for a closed negotiation.
class _Actions extends ConsumerWidget {
  const _Actions({
    required this.matchId,
    required this.busy,
    required this.onAccept,
    required this.onCounter,
    required this.onDecline,
    required this.onWithdraw,
  });

  final int matchId;
  final bool busy;
  final Future<void> Function(Offer) onAccept;
  final Future<void> Function(Offer) onCounter;
  final Future<void> Function(Offer) onDecline;
  final Future<void> Function(Offer) onWithdraw;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final offer = ref.watch(matchDetailProvider(matchId)).value?.latestOffer;
    if (offer == null || !offer.hasAnyAction) return const SizedBox.shrink();

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (offer.canAccept)
          AppButton(
            label: l.offerAccept,
            isLoading: busy,
            onPressed: () => onAccept(offer),
          ),
        if (offer.canCounter) ...[
          if (offer.canAccept) const SizedBox(height: AppSpace.sm),
          AppButton(
            label: l.offerCounter,
            variant: AppButtonVariant.secondary,
            onPressed: busy ? null : () => onCounter(offer),
          ),
        ],
        if (offer.canDecline) ...[
          const SizedBox(height: AppSpace.sm),
          AppButton(
            label: l.offerDecline,
            variant: AppButtonVariant.tertiary,
            onPressed: busy ? null : () => onDecline(offer),
          ),
        ],
        if (offer.canWithdraw)
          AppButton(
            label: l.offerWithdraw,
            variant: AppButtonVariant.tertiary,
            onPressed: busy ? null : () => onWithdraw(offer),
          ),
      ],
    );
  }
}

/// Enter a different reward.
///
/// Shows the current figure for reference and nothing else — the minimum is
/// the server's to enforce, and it says so with `reward_below_minimum` and the
/// real floor if this one is too low.
class _CounterSheet extends StatefulWidget {
  const _CounterSheet({required this.perspective, this.current});

  final MoneyPerspective perspective;
  final Money? current;

  @override
  State<_CounterSheet> createState() => _CounterSheetState();
}

class _CounterSheetState extends State<_CounterSheet> {
  late final TextEditingController _amount = TextEditingController(
    text: widget.current?.editableString ?? '',
  );

  String? _error;

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  void _submit() {
    final cents = AppAmountField.centsOf(_amount);
    if (cents == null || cents <= 0) {
      setState(() => _error = L.of(context).validationMustBePositive);
      return;
    }
    Navigator.of(context).pop(cents);
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return AppSheet(
      title: l.offerCounter,
      subtitle: widget.perspective.isTraveler
          ? l.offerCounterTravelerExplainer
          : l.offerProposeExplainer,
      footer: AppButton(label: l.offerSendCounter, onPressed: _submit),
      child: AppAmountField(
        label: widget.perspective.isTraveler
            ? l.moneyYouReceive
            : l.offerRewardLabel,
        controller: _amount,
        errorText: _error,
        onChanged: (_) {
          if (_error != null) setState(() => _error = null);
        },
      ),
    );
  }
}
