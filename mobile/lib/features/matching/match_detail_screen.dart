import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/matching/matching_providers.dart';
import '../../core/matching/matching_repository.dart';
import '../../core/auth/auth_notifier.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/util/safe_back.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/primary_button.dart';

/// Negotiation surface for a single Match.
///
/// Shows the Offer chain top-to-bottom and -- when the latest pending offer
/// was proposed by the OTHER party -- gives the viewer three buttons:
/// Accept, Decline, Counter. Counter opens a price input that creates a new
/// Offer (which is what the backend's `matches/[id]/offers/counter` endpoint
/// does — it never mutates the prior offer).
///
/// The viewer who proposed the current pending offer can Withdraw it.
class MatchDetailScreen extends ConsumerStatefulWidget {
  const MatchDetailScreen({super.key, required this.matchId});
  final int matchId;

  @override
  ConsumerState<MatchDetailScreen> createState() => _MatchDetailScreenState();
}

class _MatchDetailScreenState extends ConsumerState<MatchDetailScreen> {
  bool _counterOpen = false;
  final _counterCtl = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _counterCtl.dispose();
    super.dispose();
  }

  Future<void> _doAccept(int offerId) async {
    setState(() => _busy = true);
    try {
      await ref.read(matchingRepositoryProvider).accept(offerId);
      _refreshAll();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Offer accepted — proceed to payment.')),
      );
    } on MatchingFailure catch (e) {
      _toast(e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _doDecline(int offerId) async {
    setState(() => _busy = true);
    try {
      await ref.read(matchingRepositoryProvider).decline(offerId);
      _refreshAll();
    } on MatchingFailure catch (e) {
      _toast(e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _doWithdraw(int offerId) async {
    setState(() => _busy = true);
    try {
      await ref.read(matchingRepositoryProvider).withdraw(offerId);
      _refreshAll();
    } on MatchingFailure catch (e) {
      _toast(e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _doCounter() async {
    final raw = _counterCtl.text.trim();
    final amount = int.tryParse(raw);
    if (amount == null || amount < 100) {
      _toast('Enter an amount of at least 100 DZD.');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref
          .read(matchingRepositoryProvider)
          .counter(matchId: widget.matchId, baseAmountDzd: amount);
      _counterCtl.clear();
      setState(() => _counterOpen = false);
      _refreshAll();
    } on MatchingFailure catch (e) {
      _toast(e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _refreshAll() {
    ref.invalidate(matchDetailProvider(widget.matchId));
    ref.invalidate(offerListProvider(widget.matchId));
    ref.invalidate(chatEligibilityProvider(widget.matchId));
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    final detailAsync = ref.watch(matchDetailProvider(widget.matchId));
    final offersAsync = ref.watch(offerListProvider(widget.matchId));
    final authState = ref.watch(authNotifierProvider);
    final myId = authState is AuthSignedIn ? authState.user.id : null;

    return Scaffold(
      backgroundColor: AppColors.parchment,
      appBar: AppBar(
        backgroundColor: AppColors.parchment,
        foregroundColor: AppColors.ink,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () => safeBack(context),
        ),
        title: Text('Negotiation', style: AppType.display(18)),
      ),
      body: detailAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _ErrorView(message: e.toString(), onRetry: _refreshAll),
        data: (match) {
          return offersAsync.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) =>
                _ErrorView(message: e.toString(), onRetry: _refreshAll),
            data: (offers) => _MatchBody(
              match: match,
              offers: offers,
              myId: myId,
              busy: _busy,
              counterOpen: _counterOpen,
              counterCtl: _counterCtl,
              onAccept: _doAccept,
              onDecline: _doDecline,
              onWithdraw: _doWithdraw,
              onCounterToggle: () =>
                  setState(() => _counterOpen = !_counterOpen),
              onCounterSubmit: _doCounter,
              onGoToPayment: (offerId) =>
                  context.push('/payment/$offerId?match=${match.id}'),
            ),
          );
        },
      ),
    );
  }
}

class _MatchBody extends StatelessWidget {
  const _MatchBody({
    required this.match,
    required this.offers,
    required this.myId,
    required this.busy,
    required this.counterOpen,
    required this.counterCtl,
    required this.onAccept,
    required this.onDecline,
    required this.onWithdraw,
    required this.onCounterToggle,
    required this.onCounterSubmit,
    required this.onGoToPayment,
  });

  final MatchSummary match;
  final List<Offer> offers;
  final int? myId;
  final bool busy;
  final bool counterOpen;
  final TextEditingController counterCtl;
  final void Function(int offerId) onAccept;
  final void Function(int offerId) onDecline;
  final void Function(int offerId) onWithdraw;
  final VoidCallback onCounterToggle;
  final VoidCallback onCounterSubmit;
  final void Function(int offerId) onGoToPayment;

  @override
  Widget build(BuildContext context) {
    final pending = offers
        .where((o) => o.status == OfferStatus.pending)
        .toList(growable: false);
    final accepted = offers
        .where((o) => o.status == OfferStatus.accepted)
        .toList(growable: false);
    final currentPending = pending.isEmpty ? null : pending.first;

    final iAmCounterparty = currentPending != null &&
        myId != null &&
        currentPending.proposerId != myId;
    final iAmProposer = currentPending != null &&
        myId != null &&
        currentPending.proposerId == myId;

    final canCounter = match.parcel?.targetTravelerId != null;

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        _StatusStrip(status: match.status),
        const SizedBox(height: 16),

        // Accepted offer banner + pay button (sender only)
        if (accepted.isNotEmpty)
          _AcceptedBanner(
            offer: accepted.first,
            isSender: myId == match.senderId,
            onPay: onGoToPayment,
          ),

        // Handover code entry points -- visible once the match is paid +
        // accepted (server gates this anyway; we only show buttons when the
        // status makes the action legal).
        if (match.status == MatchStatus.accepted ||
            match.status == MatchStatus.inTransit)
          _HandoverPanel(
            matchId: match.id,
            status: match.status,
            isSender: myId == match.senderId,
          ),

        // The chain
        Text('Offer history', style: AppType.display(16)),
        const SizedBox(height: 8),
        for (final o in offers)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _OfferCard(offer: o, viewerId: myId),
          ),

        // Action surface for the current pending offer
        if (currentPending != null && match.status == MatchStatus.pending) ...[
          const SizedBox(height: 12),
          if (iAmCounterparty) ...[
            if (canCounter)
              Row(
                children: [
                  Expanded(
                    child: _SecondaryButton(
                      label: 'Decline',
                      onTap: busy ? null : () => onDecline(currentPending.id),
                      color: AppColors.danger,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: _SecondaryButton(
                      label: counterOpen ? 'Cancel' : 'Counter',
                      onTap: busy ? null : onCounterToggle,
                      color: AppColors.terracotta,
                    ),
                  ),
                ],
              )
            else
              _SecondaryButton(
                label: 'Decline',
                onTap: busy ? null : () => onDecline(currentPending.id),
                color: AppColors.danger,
              ),
            const SizedBox(height: 10),
            PrimaryButton(
              label: busy ? 'Working…' : 'Accept ${_dzd(currentPending.totalDzd)} DZD',
              expand: true,
              onTap: busy ? null : () => onAccept(currentPending.id),
            ),
          ] else if (iAmProposer) ...[
            _SecondaryButton(
              label: 'Withdraw my offer',
              onTap: busy ? null : () => onWithdraw(currentPending.id),
              color: AppColors.inkSoft,
            ),
          ],
          if (counterOpen && iAmCounterparty && canCounter) ...[
            const SizedBox(height: 14),
            Text(
              'Your counter (traveler payout, DZD)',
              style: AppType.body(12, color: AppColors.inkMute),
            ),
            const SizedBox(height: 6),
            AppInput(
              controller: counterCtl,
              hint: 'e.g. 4000',
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 4),
            Text(
              'A 25% platform commission is added on top — the sender sees the total.',
              style: AppType.body(12, color: AppColors.inkMute),
            ),
            const SizedBox(height: 10),
            PrimaryButton(
              label: busy ? 'Sending…' : 'Send counter',
              expand: true,
              onTap: busy ? null : onCounterSubmit,
            ),
          ],
        ],
      ],
    );
  }

  static String _dzd(int n) {
    final s = n.toString();
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
      buf.write(s[i]);
    }
    return buf.toString();
  }
}

class _StatusStrip extends StatelessWidget {
  const _StatusStrip({required this.status});
  final MatchStatus status;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      MatchStatus.pending => ('Negotiating', AppColors.gold),
      MatchStatus.accepted => ('Accepted — awaiting payment', AppColors.emerald),
      MatchStatus.inTransit => ('In transit', AppColors.emerald),
      MatchStatus.delivered => ('Delivered', AppColors.success),
      MatchStatus.completed => ('Completed', AppColors.success),
      MatchStatus.cancelled => ('Cancelled', AppColors.inkMute),
      MatchStatus.expired => ('Expired', AppColors.inkMute),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 10),
          Text(label, style: AppType.body(14, color: color, w: FontWeight.w600)),
        ],
      ),
    );
  }
}

class _AcceptedBanner extends StatelessWidget {
  const _AcceptedBanner({
    required this.offer,
    required this.isSender,
    required this.onPay,
  });
  final Offer offer;
  final bool isSender;
  final void Function(int offerId) onPay;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 18),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.emerald.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.emerald.withValues(alpha: 0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Agreed price',
              style: AppType.body(12, color: AppColors.emerald, w: FontWeight.w600)),
          const SizedBox(height: 4),
          Text(
            '${_MatchBody._dzd(offer.totalDzd)} DZD',
            style: AppType.display(22, color: AppColors.emeraldDeep),
          ),
          if (isSender) ...[
            const SizedBox(height: 12),
            PrimaryButton(
                label: 'Pay to start delivery',
                expand: true,
                onTap: () => onPay(offer.id)),
          ] else
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                'Waiting for the sender to complete payment. Chat opens once paid.',
                style: AppType.body(12, color: AppColors.inkMute),
              ),
            ),
        ],
      ),
    );
  }
}

class _OfferCard extends StatelessWidget {
  const _OfferCard({required this.offer, required this.viewerId});
  final Offer offer;
  final int? viewerId;

  @override
  Widget build(BuildContext context) {
    final mine = viewerId == offer.proposerId;
    final color = switch (offer.status) {
      OfferStatus.accepted => AppColors.emerald,
      OfferStatus.declined || OfferStatus.withdrawn || OfferStatus.expired =>
        AppColors.inkMute,
      OfferStatus.countered => AppColors.inkSoft,
      OfferStatus.pending => mine ? AppColors.gold : AppColors.terracotta,
    };
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${mine ? 'You' : 'They'} proposed',
                  style: AppType.body(12, color: AppColors.inkMute),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: Text(
                  offer.status.name,
                  style: AppType.body(11, color: color, w: FontWeight.w600),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '${_MatchBody._dzd(offer.totalDzd)} DZD',
            style: AppType.display(20),
          ),
          Text(
            'Traveler payout ${_MatchBody._dzd(offer.baseAmountDzd)} • Commission ${_MatchBody._dzd(offer.commissionDzd)}',
            style: AppType.body(12, color: AppColors.inkMute),
          ),
          if (offer.note.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(offer.note, style: AppType.body(13)),
          ],
        ],
      ),
    );
  }
}

class _SecondaryButton extends StatelessWidget {
  const _SecondaryButton({
    required this.label,
    required this.onTap,
    required this.color,
  });
  final String label;
  final VoidCallback? onTap;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.md),
      child: Container(
        height: 48,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: color, width: 1.5),
        ),
        child: Text(
          label,
          style: AppType.body(14, color: color, w: FontWeight.w600),
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, color: AppColors.danger, size: 36),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center, style: AppType.body(14)),
            const SizedBox(height: 16),
            PrimaryButton(label: 'Retry', onTap: onRetry),
          ],
        ),
      ),
    );
  }
}

class _HandoverPanel extends StatelessWidget {
  const _HandoverPanel({
    required this.matchId,
    required this.status,
    required this.isSender,
  });
  final int matchId;
  final MatchStatus status;
  final bool isSender;

  @override
  Widget build(BuildContext context) {
    // Which code is relevant right now:
    //   accepted   -> PICKUP
    //   in_transit -> DELIVERY
    final isPickup = status == MatchStatus.accepted;
    final kindParam = isPickup ? 'pickup' : 'delivery';
    final actionLabel = isSender
        ? (isPickup ? 'View pickup code' : 'Follow package')
        : (isPickup ? 'Enter pickup code' : 'Enter delivery code');
    final blurb = isSender
        ? (isPickup
            ? 'Show the traveler this code when they arrive to collect the parcel. You can come back here anytime — we won\'t change it.'
            : 'Your parcel is on the move. Track it live and stay reachable for the recipient.')
        : (isPickup
            ? 'Ask the sender for the pickup code and enter it here to confirm you have the parcel.'
            : 'Ask the recipient for the delivery code. Verifying it releases your payment from escrow.');
    // Sender-PICKUP uses the view-only screen (no rotation); sender-DELIVERY
    // routes to follow-package since the recipient owns the delivery code
    // surface, not the sender. Traveler always verifies.
    final route = isSender
        ? (isPickup
            ? '/handover/code/$matchId?kind=$kindParam'
            : '/tracking/$matchId')
        : '/handover/verify/$matchId?kind=$kindParam';

    return Container(
      margin: const EdgeInsets.only(bottom: 18),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.gold.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.gold.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isPickup ? Icons.inventory_2_outlined : Icons.local_shipping_outlined,
                color: AppColors.goldDeep,
                size: 18,
              ),
              const SizedBox(width: 8),
              Text(
                isPickup ? 'Pickup' : 'Delivery',
                style: AppType.eyebrow(color: AppColors.goldDeep),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(blurb, style: AppType.body(13, color: AppColors.inkSoft)),
          const SizedBox(height: 12),
          PrimaryButton(
            label: actionLabel,
            expand: true,
            color: AppColors.emerald,
            onTap: () => GoRouter.of(context).push(route),
          ),
        ],
      ),
    );
  }
}
