import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/matching/matching_providers.dart';
import '../../core/matching/matching_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/ws/live_event_router.dart';

class MyRequestsScreen extends ConsumerWidget {
  const MyRequestsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Re-fetch whenever a match-affecting event lands on the WS.
    ref.watch(liveEventProvider.select((s) => s.matchTick));
    final matchesAsync =
        ref.watch(matchListProvider(const MatchListParams(role: 'sender')));

    return Scaffold(
      backgroundColor: AppColors.parchment,
      appBar: AppBar(
        backgroundColor: AppColors.parchment,
        elevation: 0,
        title: const Text('My requests'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () => context.pop(),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(
              matchListProvider(const MatchListParams(role: 'sender')));
          await ref.read(matchListProvider(
              const MatchListParams(role: 'sender')).future);
        },
        child: matchesAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(
            children: [
              const SizedBox(height: 80),
              Center(child: Text('Could not load — $e')),
            ],
          ),
          data: (matches) {
            if (matches.isEmpty) {
              return ListView(
                children: const [
                  SizedBox(height: 120),
                  Center(
                    child: Padding(
                      padding: EdgeInsets.symmetric(horizontal: 32),
                      child: Text(
                        'You have no requests yet. Tap "New request" on the home screen.',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                ],
              );
            }
            return ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
              itemCount: matches.length,
              separatorBuilder: (_, _) => const SizedBox(height: 12),
              itemBuilder: (_, i) => _MatchTile(m: matches[i]),
            );
          },
        ),
      ),
    );
  }
}

class _MatchTile extends ConsumerWidget {
  const _MatchTile({required this.m});
  final MatchSummary m;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final liveCode = liveCodeFor(ref, m.id);
    final parcel = m.parcel;
    final route = parcel == null
        ? 'Parcel #${m.parcelId}'
        : '${parcel.originIata} → ${parcel.destinationIata}';

    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        onTap: () => context.push('/match/${m.id}'),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(route,
                        style: AppType.body(15, w: FontWeight.w700)),
                  ),
                  _StatusChip(status: m.status),
                ],
              ),
              const SizedBox(height: 6),
              Text(_subline(m), style: AppType.body(12.5, color: AppColors.inkSoft)),
              if (liveCode != null) ...[
                const SizedBox(height: 12),
                InkWell(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  onTap: () => context
                      .push('/handover/code/${m.id}?kind=${liveCode.kind}'),
                  child: _CodeBanner(code: liveCode),
                ),
              ] else if (m.status == MatchStatus.accepted) ...[
                const SizedBox(height: 12),
                _ViewCodePrompt(
                  onTap: () =>
                      context.push('/handover/code/${m.id}?kind=pickup'),
                ),
              ],
              const SizedBox(height: 10),
              Row(
                children: [
                  _ActionButton(
                    label: _primaryActionLabel(m),
                    onTap: () => _onPrimary(context, m),
                  ),
                  const Spacer(),
                  Icon(Icons.chevron_right_rounded,
                      color: AppColors.inkMute, size: 20),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  static String _subline(MatchSummary m) {
    final off = m.acceptedOffer ?? m.latestOffer;
    if (off == null) return 'Awaiting first offer';
    final amount = '${off.totalDzd} DZD';
    switch (m.status) {
      case MatchStatus.pending:
        return 'Offer ${off.status.name} — $amount';
      case MatchStatus.accepted:
        return 'Accepted — $amount. Tap to pay or coordinate pickup.';
      case MatchStatus.inTransit:
        return 'In transit — wait for delivery code.';
      case MatchStatus.delivered:
      case MatchStatus.completed:
        return 'Delivered. Funds released.';
      case MatchStatus.cancelled:
        return 'Cancelled.';
      case MatchStatus.expired:
        return 'Expired.';
    }
  }

  static String _primaryActionLabel(MatchSummary m) {
    switch (m.status) {
      case MatchStatus.pending:
        return 'Review offer';
      case MatchStatus.accepted:
        return 'Pay & track';
      case MatchStatus.inTransit:
        return 'Track';
      default:
        return 'Open';
    }
  }

  void _onPrimary(BuildContext ctx, MatchSummary m) {
    switch (m.status) {
      case MatchStatus.accepted:
        final off = m.acceptedOffer ?? m.latestOffer;
        if (off != null) {
          ctx.push('/payment/${off.id}?match=${m.id}');
          return;
        }
        ctx.push('/match/${m.id}');
        return;
      case MatchStatus.inTransit:
        ctx.push('/tracking/${m.id}');
        return;
      default:
        ctx.push('/match/${m.id}');
    }
  }
}

class _CodeBanner extends StatelessWidget {
  const _CodeBanner({required this.code});
  final LiveHandoverCode code;

  @override
  Widget build(BuildContext context) {
    final isPickup = code.kind == 'pickup';
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.sun.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.sun, width: 1.5),
      ),
      child: Row(
        children: [
          const Icon(Icons.qr_code_2_rounded, color: AppColors.ink),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isPickup ? 'Pickup code' : 'Delivery code',
                  style: AppType.body(11.5,
                      w: FontWeight.w700, color: AppColors.inkSoft),
                ),
                const SizedBox(height: 2),
                Text(
                  code.code,
                  style: const TextStyle(
                    fontFeatures: [FontFeature.tabularFigures()],
                    fontSize: 22,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 4,
                    color: AppColors.ink,
                  ),
                ),
              ],
            ),
          ),
          Text(
            isPickup ? 'show at pickup' : 'show at delivery',
            style: AppType.body(11, color: AppColors.inkMute),
          ),
        ],
      ),
    );
  }
}

class _ViewCodePrompt extends StatelessWidget {
  const _ViewCodePrompt({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(AppRadius.md),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: AppColors.emerald.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(
              color: AppColors.emerald.withValues(alpha: 0.3), width: 1),
        ),
        child: Row(
          children: [
            Icon(Icons.qr_code_2_rounded,
                size: 18, color: AppColors.emeraldDeep),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'View pickup code',
                style: AppType.body(13,
                    w: FontWeight.w700, color: AppColors.emeraldDeep),
              ),
            ),
            Icon(Icons.chevron_right_rounded,
                size: 18, color: AppColors.emeraldDeep),
          ],
        ),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});
  final MatchStatus status;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      MatchStatus.pending => ('Pending', AppColors.inkMute),
      MatchStatus.accepted => ('Accepted', AppColors.emerald),
      MatchStatus.inTransit => ('In transit', AppColors.gold),
      MatchStatus.delivered ||
      MatchStatus.completed => ('Delivered', AppColors.emerald),
      MatchStatus.cancelled => ('Cancelled', AppColors.terracotta),
      MatchStatus.expired => ('Expired', AppColors.terracotta),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({required this.label, required this.onTap});
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.pill),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: AppColors.ink,
          borderRadius: BorderRadius.circular(AppRadius.pill),
        ),
        child: Text(
          label,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 12.5,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}
