import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/matching/matching_providers.dart';
import '../../core/matching/matching_repository.dart';
import '../../core/parcels/parcels_providers.dart';
import '../../core/parcels/parcels_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/ws/live_event_router.dart';

/// "All my requests" — a clean summary list.
///
/// Each row is just route + status chip + sub-line + chevron. Tapping a row
/// opens `/sender/requests/<parcelId>`, the per-request management hub
/// where codes, traveler info, chat, and cancel live.
class MyRequestsScreen extends ConsumerWidget {
  const MyRequestsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(liveEventProvider.select((s) => s.matchTick));

    final parcelsAsync = ref.watch(myParcelsProvider);
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
          ref
            ..invalidate(myParcelsProvider)
            ..invalidate(
                matchListProvider(const MatchListParams(role: 'sender')));
          await Future.wait([
            ref.read(myParcelsProvider.future),
            ref.read(matchListProvider(const MatchListParams(role: 'sender'))
                .future),
          ]);
        },
        child: parcelsAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(
            children: [
              const SizedBox(height: 80),
              Center(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 32),
                  child: Text('Could not load — $e',
                      textAlign: TextAlign.center,
                      style: AppType.body(13, color: AppColors.inkSoft)),
                ),
              ),
            ],
          ),
          data: (parcels) {
            if (parcels.isEmpty) return const _EmptyState();
            final matches = matchesAsync.value ?? const <MatchSummary>[];
            final byParcel = <int, List<MatchSummary>>{};
            for (final m in matches) {
              byParcel.putIfAbsent(m.parcelId, () => []).add(m);
            }
            final sorted = [...parcels]..sort((a, b) {
                int rank(Parcel p) {
                  final ms = byParcel[p.id] ?? const <MatchSummary>[];
                  final hasInTransit =
                      ms.any((m) => m.status == MatchStatus.inTransit);
                  if (hasInTransit) return 0;
                  final hasAccepted =
                      ms.any((m) => m.status == MatchStatus.accepted);
                  if (hasAccepted) return 1;
                  final hasPending = ms.any(
                      (m) => m.status == MatchStatus.pending);
                  if (hasPending) return 2;
                  if (p.status == 'open') return 3;
                  if (p.status == 'cancelled') return 5;
                  return 4;
                }

                final ra = rank(a);
                final rb = rank(b);
                if (ra != rb) return ra.compareTo(rb);
                return b.createdAt.compareTo(a.createdAt);
              });

            return ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
              itemCount: sorted.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (_, i) => _SummaryCard(
                parcel: sorted[i],
                matches: byParcel[sorted[i].id] ?? const <MatchSummary>[],
              ),
            );
          },
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return ListView(
      children: [
        const SizedBox(height: 80),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 28),
          child: Column(
            children: [
              Container(
                width: 80,
                height: 80,
                decoration: BoxDecoration(
                  color: AppColors.parchmentSoft,
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.hairline),
                ),
                child: const Icon(Icons.inventory_2_outlined,
                    size: 36, color: AppColors.inkMute),
              ),
              const SizedBox(height: 16),
              Text('No requests yet',
                  style: AppType.display(20, w: FontWeight.w500)),
              const SizedBox(height: 6),
              Text(
                'Post a parcel and we\'ll match you with travelers heading your way.',
                textAlign: TextAlign.center,
                style: AppType.body(13.5,
                    color: AppColors.inkSoft, height: 1.45),
              ),
              const SizedBox(height: 18),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.ink,
                  foregroundColor: AppColors.parchment,
                  padding: const EdgeInsets.symmetric(
                      horizontal: 22, vertical: 14),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                  ),
                ),
                onPressed: () => context.push('/sender/new'),
                child: const Text('Post a request'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Summary-only card. No inline CTAs, no inline code, no find-travelers
/// here — all of that lives on the per-request detail page.
class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.parcel, required this.matches});
  final Parcel parcel;
  final List<MatchSummary> matches;

  @override
  Widget build(BuildContext context) {
    final (label, color) = _statusChip();
    final route = '${parcel.origin.iata} → ${parcel.destination.iata}';
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        onTap: () => context.push('/sender/requests/${parcel.id}'),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(route,
                              style:
                                  AppType.body(15, w: FontWeight.w700)),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: color.withValues(alpha: 0.12),
                            borderRadius:
                                BorderRadius.circular(AppRadius.pill),
                          ),
                          child: Text(
                            label,
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                              color: color,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _subline(),
                      style: AppType.body(12.5, color: AppColors.inkSoft),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(Icons.chevron_right_rounded,
                  color: AppColors.inkMute),
            ],
          ),
        ),
      ),
    );
  }

  String _subline() {
    final inTransit =
        matches.where((m) => m.status == MatchStatus.inTransit).isNotEmpty;
    if (inTransit) return 'On the road — tap to follow.';
    final accepted = matches
        .where((m) => m.status == MatchStatus.accepted)
        .toList();
    if (accepted.isNotEmpty) {
      final paid = accepted.first.acceptedOffer != null;
      return paid
          ? 'Ready for pickup — your code is inside.'
          : 'Accepted — pay to confirm.';
    }
    final pending = matches
        .where((m) =>
            m.status == MatchStatus.pending && m.latestOffer != null)
        .length;
    if (pending > 0) {
      return '$pending new offer${pending == 1 ? '' : 's'} — tap to review.';
    }
    if (parcel.status == 'cancelled') return 'Cancelled.';
    if (parcel.status == 'open') return 'Waiting for travelers to apply.';
    return 'Posted ${_relative(parcel.createdAt)}.';
  }

  (String, Color) _statusChip() {
    if (matches.any((m) => m.status == MatchStatus.inTransit)) {
      return ('In transit', AppColors.emerald);
    }
    if (matches.any((m) =>
        m.status == MatchStatus.delivered ||
        m.status == MatchStatus.completed)) {
      return ('Delivered', AppColors.emerald);
    }
    final accepted = matches.where((m) => m.status == MatchStatus.accepted);
    if (accepted.isNotEmpty) {
      final paid = accepted.first.acceptedOffer != null;
      return paid ? ('Ready', AppColors.emerald) : ('Accepted', AppColors.gold);
    }
    if (matches.any((m) => m.status == MatchStatus.pending)) {
      return ('Offer pending', AppColors.gold);
    }
    if (parcel.status == 'cancelled') {
      return ('Cancelled', AppColors.terracotta);
    }
    return ('Live', AppColors.gold);
  }

  static String _relative(DateTime t) {
    final diff = DateTime.now().difference(t);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }
}
