import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/matching/matching_providers.dart';
import '../../core/matching/matching_repository.dart';
import '../../core/parcels/parcels_providers.dart';
import '../../core/parcels/parcels_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/verification/verification_providers.dart';
import '../../core/verification/verification_repository.dart';
import '../../core/ws/live_event_router.dart';
import '../../shared/util/safe_back.dart';

/// Per-request management hub.
///
/// One screen, sections appear/disappear based on the parcel's derived state.
/// This is the single place a sender goes to: check status, see codes, view
/// the assigned traveler, message them, see parcel info, and cancel.
class RequestDetailScreen extends ConsumerWidget {
  const RequestDetailScreen({super.key, required this.parcelId});
  final int parcelId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Any live event that touches matches re-renders so we pick up codes,
    // status transitions, etc.
    ref.watch(liveEventProvider.select((s) => s.matchTick));

    final parcelAsync = ref.watch(parcelByIdProvider(parcelId));
    final matchesAsync =
        ref.watch(matchListProvider(const MatchListParams(role: 'sender')));

    return Scaffold(
      backgroundColor: AppColors.parchment,
      appBar: AppBar(
        backgroundColor: AppColors.parchment,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () => safeBack(context, fallback: '/sender/requests'),
        ),
        title: const Text('Request'),
      ),
      body: parcelAsync.when(
        loading: () =>
            const Center(child: CircularProgressIndicator(strokeWidth: 2)),
        error: (e, _) => _ErrorState(message: '$e'),
        data: (parcel) {
          final matches = (matchesAsync.value ?? const <MatchSummary>[])
              .where((m) => m.parcelId == parcel.id)
              .toList();
          final state = _derive(parcel, matches);
          return RefreshIndicator(
            onRefresh: () async {
              ref
                ..invalidate(parcelByIdProvider(parcelId))
                ..invalidate(
                    matchListProvider(const MatchListParams(role: 'sender')));
              await ref.read(parcelByIdProvider(parcelId).future);
            },
            color: AppColors.ink,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
              children: [
                _Header(parcel: parcel, state: state),
                const SizedBox(height: 16),
                ..._sectionsFor(context, ref, parcel, matches, state),
              ],
            ),
          );
        },
      ),
    );
  }

  _RequestState _derive(Parcel parcel, List<MatchSummary> matches) {
    if (parcel.status == 'cancelled') return _RequestState.cancelled;
    final inTransit = matches.firstWhere(
      (m) => m.status == MatchStatus.inTransit,
      orElse: () => _none(parcel.id),
    );
    if (inTransit.id != -1) return _RequestState.onTheRoad;

    final delivered = matches.firstWhere(
      (m) =>
          m.status == MatchStatus.delivered ||
          m.status == MatchStatus.completed,
      orElse: () => _none(parcel.id),
    );
    if (delivered.id != -1) return _RequestState.delivered;

    final accepted = matches.firstWhere(
      (m) => m.status == MatchStatus.accepted,
      orElse: () => _none(parcel.id),
    );
    if (accepted.id != -1) {
      final paid = accepted.acceptedOffer != null;
      return paid ? _RequestState.readyForPickup : _RequestState.awaitingPayment;
    }
    return _RequestState.open;
  }

  MatchSummary _none(int parcelId) => MatchSummary(
        id: -1,
        parcelId: parcelId,
        tripId: -1,
        senderId: -1,
        travelerId: -1,
        status: MatchStatus.pending,
        parcel: null,
        latestOffer: null,
        acceptedOffer: null,
        createdAt: DateTime.now(),
      );

  List<Widget> _sectionsFor(
    BuildContext context,
    WidgetRef ref,
    Parcel parcel,
    List<MatchSummary> matches,
    _RequestState state,
  ) {
    MatchSummary? activeMatch() {
      for (final s in [
        MatchStatus.inTransit,
        MatchStatus.accepted,
        MatchStatus.delivered,
        MatchStatus.completed,
      ]) {
        final hit = matches.where((m) => m.status == s);
        if (hit.isNotEmpty) return hit.first;
      }
      return null;
    }

    final active = activeMatch();

    switch (state) {
      case _RequestState.open:
        final pending = matches
            .where((m) =>
                m.status == MatchStatus.pending && m.latestOffer != null)
            .toList();
        return [
          if (pending.isEmpty)
            const _WaitingCard()
          else
            _OffersSection(offers: pending),
          const SizedBox(height: 16),
          _ParcelInfoCard(parcel: parcel),
          const SizedBox(height: 24),
          _CancelButton(parcelId: parcel.id, enabled: true),
        ];
      case _RequestState.awaitingPayment:
        return [
          _AwaitingPaymentCard(match: active!),
          const SizedBox(height: 16),
          _TravelerCard(match: active),
          const SizedBox(height: 16),
          _ParcelInfoCard(parcel: parcel),
          const SizedBox(height: 24),
          _CancelButton(
            parcelId: parcel.id,
            enabled: true,
            warning: 'This voids the accepted offer.',
          ),
        ];
      case _RequestState.readyForPickup:
        return [
          _CodeCard(
            matchId: active!.id,
            kind: HandoverKind.pickup,
          ),
          const SizedBox(height: 16),
          _TravelerCard(match: active),
          const SizedBox(height: 16),
          _ParcelInfoCard(parcel: parcel),
          const SizedBox(height: 24),
          const _HelpRow(),
        ];
      case _RequestState.onTheRoad:
        return [
          _FollowPackageTile(matchId: active!.id),
          const SizedBox(height: 16),
          _CodeCard(
            matchId: active.id,
            kind: HandoverKind.delivery,
          ),
          const SizedBox(height: 16),
          _TravelerCard(match: active),
          const SizedBox(height: 16),
          _ParcelInfoCard(parcel: parcel),
        ];
      case _RequestState.delivered:
        return [
          _DeliveredHero(match: active!),
          const SizedBox(height: 16),
          _ReceiptCard(match: active),
          const SizedBox(height: 16),
          _TravelerCard(match: active),
          const SizedBox(height: 16),
          _ParcelInfoCard(parcel: parcel),
        ];
      case _RequestState.cancelled:
        return [
          const _CancelledBanner(),
          const SizedBox(height: 16),
          _ParcelInfoCard(parcel: parcel),
        ];
    }
  }
}

enum _RequestState {
  open,
  awaitingPayment,
  readyForPickup,
  onTheRoad,
  delivered,
  cancelled,
}

class _Header extends StatelessWidget {
  const _Header({required this.parcel, required this.state});
  final Parcel parcel;
  final _RequestState state;

  @override
  Widget build(BuildContext context) {
    final (label, color) = _chip();
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${parcel.origin.iata} → ${parcel.destination.iata}',
                  style: AppType.display(22, w: FontWeight.w600, height: 1.1),
                ),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
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
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '${parcel.weightKg} kg · ${parcel.itemType.isEmpty ? parcel.kind : parcel.itemType}',
            style: AppType.body(13, color: AppColors.inkSoft, height: 1.4),
          ),
        ],
      ),
    );
  }

  (String, Color) _chip() {
    switch (state) {
      case _RequestState.open:
        return ('Live', AppColors.gold);
      case _RequestState.awaitingPayment:
        return ('Awaiting payment', AppColors.gold);
      case _RequestState.readyForPickup:
        return ('Ready for pickup', AppColors.emerald);
      case _RequestState.onTheRoad:
        return ('On the road', AppColors.emerald);
      case _RequestState.delivered:
        return ('Delivered', AppColors.emerald);
      case _RequestState.cancelled:
        return ('Cancelled', AppColors.terracotta);
    }
  }
}

class _WaitingCard extends StatelessWidget {
  const _WaitingCard();

  @override
  Widget build(BuildContext context) {
    return _SectionCard(
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: AppColors.sun.withValues(alpha: 0.18),
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.hourglass_top_rounded,
                size: 22, color: AppColors.ink),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Waiting for travelers',
                    style: AppType.body(14.5, w: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(
                  'We\'ll notify you the moment someone applies to carry your parcel.',
                  style: AppType.body(12,
                      color: AppColors.inkSoft, height: 1.45),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _OffersSection extends StatelessWidget {
  const _OffersSection({required this.offers});
  final List<MatchSummary> offers;

  @override
  Widget build(BuildContext context) {
    return _SectionCard(
      padded: false,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
            child: Row(
              children: [
                Text('Offers (${offers.length})',
                    style: AppType.body(14.5, w: FontWeight.w700)),
                const Spacer(),
                Text(
                  'Tap to review',
                  style: AppType.body(11.5, color: AppColors.inkMute),
                ),
              ],
            ),
          ),
          for (var i = 0; i < offers.length; i++) ...[
            if (i > 0)
              const Divider(height: 1, color: AppColors.hairline),
            _OfferRow(match: offers[i]),
          ],
        ],
      ),
    );
  }
}

class _OfferRow extends StatelessWidget {
  const _OfferRow({required this.match});
  final MatchSummary match;

  @override
  Widget build(BuildContext context) {
    final amount = match.latestOffer?.totalDzd;
    return InkWell(
      onTap: () => context.push('/match/${match.id}'),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
        child: Row(
          children: [
            const CircleAvatar(
              radius: 18,
              backgroundColor: AppColors.parchmentSoft,
              child: Icon(Icons.person_rounded,
                  size: 20, color: AppColors.inkSoft),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Traveler #${match.travelerId}',
                      style: AppType.body(13.5, w: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Text(
                    amount == null
                        ? 'Offer pending'
                        : '$amount DZD · trip #${match.tripId}',
                    style: AppType.body(12, color: AppColors.inkSoft),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded,
                color: AppColors.inkMute),
          ],
        ),
      ),
    );
  }
}

class _AwaitingPaymentCard extends StatelessWidget {
  const _AwaitingPaymentCard({required this.match});
  final MatchSummary match;

  @override
  Widget build(BuildContext context) {
    final offer = match.acceptedOffer ?? match.latestOffer;
    final total = offer?.totalDzd;
    return _SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Confirm with payment',
              style: AppType.body(14.5, w: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(
            total == null
                ? 'Complete payment to lock in this match.'
                : 'Pay $total DZD to lock in the traveler. Funds are held in escrow until delivery.',
            style: AppType.body(12.5, color: AppColors.inkSoft, height: 1.45),
          ),
          const SizedBox(height: 14),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.ink,
                foregroundColor: AppColors.parchment,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
              ),
              onPressed: offer == null
                  ? null
                  : () => context.push(
                      '/payment/${offer.id}?match=${match.id}'),
              child: Text(total == null ? 'Open match' : 'Pay $total DZD'),
            ),
          ),
        ],
      ),
    );
  }
}

/// Big sun-yellow (pickup) or emerald (delivery) code card.
///
/// Plaintext lives in [LiveEventState.codesByMatch]; the server-side GET only
/// confirms an ACTIVE code exists without rotating. If the code isn't in
/// memory yet (e.g. app cold-started after the WS event), we fall back to
/// "Tap to view full screen" which navigates to the existing
/// `/handover/code/<id>?kind=...` screen.
class _CodeCard extends ConsumerWidget {
  const _CodeCard({required this.matchId, required this.kind});
  final int matchId;
  final HandoverKind kind;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final live = liveCodeFor(ref, matchId);
    final hasLive = live != null && live.kind == kind.wire;
    final isPickup = kind == HandoverKind.pickup;
    final accent = isPickup ? AppColors.sun : AppColors.emerald;
    final title = isPickup ? 'Pickup code' : 'Delivery code';
    final caption = isPickup
        ? 'Show this to the traveler at pickup.'
        : 'Show this when the traveler delivers.';

    return Container(
      decoration: BoxDecoration(
        color: accent.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: accent.withValues(alpha: 0.55), width: 1.4),
      ),
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.qr_code_2_rounded,
                  size: 20, color: AppColors.ink),
              const SizedBox(width: 8),
              Text(title, style: AppType.body(13.5, w: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 6),
          Text(caption,
              style:
                  AppType.body(12, color: AppColors.inkSoft, height: 1.4)),
          const SizedBox(height: 14),
          if (hasLive)
            _CodeDisplay(code: live.code)
          else
            _CodePlaceholder(matchId: matchId, kind: kind),
        ],
      ),
    );
  }
}

class _CodeDisplay extends StatelessWidget {
  const _CodeDisplay({required this.code});
  final String code;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            code,
            style: const TextStyle(
              fontFeatures: [FontFeature.tabularFigures()],
              fontSize: 36,
              fontWeight: FontWeight.w800,
              letterSpacing: 6,
              color: AppColors.ink,
            ),
          ),
        ),
        Material(
          color: AppColors.ink,
          shape: const StadiumBorder(),
          child: InkWell(
            customBorder: const StadiumBorder(),
            onTap: () async {
              await Clipboard.setData(ClipboardData(text: code));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Code copied to clipboard'),
                    duration: Duration(seconds: 1),
                  ),
                );
              }
            },
            child: const Padding(
              padding: EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.copy_rounded,
                      size: 14, color: Colors.white),
                  SizedBox(width: 6),
                  Text('Copy',
                      style: TextStyle(
                          color: Colors.white,
                          fontSize: 12,
                          fontWeight: FontWeight.w700)),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _CodePlaceholder extends ConsumerWidget {
  const _CodePlaceholder({required this.matchId, required this.kind});
  final int matchId;
  final HandoverKind kind;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final infoAsync = ref.watch(activeCodeProvider(
        ActiveCodeParams(matchId: matchId, kind: kind)));
    return infoAsync.when(
      loading: () => const Padding(
        padding: EdgeInsets.symmetric(vertical: 6),
        child: SizedBox(
          height: 24,
          width: 24,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      ),
      error: (_, __) => Text(
        'Code unavailable right now.',
        style: AppType.body(12.5,
            color: AppColors.inkSoft, height: 1.4),
      ),
      data: (info) {
        if (info == null) {
          return Text(
            'Waiting on code…',
            style: AppType.body(12.5,
                color: AppColors.inkSoft, height: 1.4),
          );
        }
        return Row(
          children: [
            Expanded(
              child: Text(
                'Code ready · tap to view',
                style: AppType.body(13.5,
                    w: FontWeight.w700, color: AppColors.ink),
              ),
            ),
            InkWell(
              onTap: () => context.push(
                  '/handover/code/$matchId?kind=${kind.wire}'),
              borderRadius: BorderRadius.circular(AppRadius.pill),
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: AppColors.ink,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: const Text(
                  'View',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 12,
                      fontWeight: FontWeight.w700),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _TravelerCard extends StatelessWidget {
  const _TravelerCard({required this.match});
  final MatchSummary match;

  @override
  Widget build(BuildContext context) {
    return _SectionCard(
      child: Row(
        children: [
          const CircleAvatar(
            radius: 22,
            backgroundColor: AppColors.parchmentSoft,
            child: Icon(Icons.person_rounded,
                size: 22, color: AppColors.inkSoft),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Traveler #${match.travelerId}',
                    style: AppType.body(14, w: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(
                  'Trip #${match.tripId}',
                  style: AppType.body(12, color: AppColors.inkSoft),
                ),
              ],
            ),
          ),
          Material(
            color: AppColors.parchmentSoft,
            shape: const StadiumBorder(),
            child: InkWell(
              customBorder: const StadiumBorder(),
              onTap: () => context.push('/chat/${match.id}'),
              child: const Padding(
                padding:
                    EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.chat_bubble_outline_rounded,
                        size: 14, color: AppColors.ink),
                    SizedBox(width: 6),
                    Text('Message',
                        style: TextStyle(
                            color: AppColors.ink,
                            fontSize: 12,
                            fontWeight: FontWeight.w700)),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _FollowPackageTile extends StatelessWidget {
  const _FollowPackageTile({required this.matchId});
  final int matchId;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.ink,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        onTap: () => context.push('/tracking/$matchId'),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(
            children: [
              const Icon(Icons.flight_takeoff_rounded,
                  color: Colors.white, size: 22),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Follow package',
                        style: AppType.body(15,
                            w: FontWeight.w700,
                            color: Colors.white)),
                    const SizedBox(height: 2),
                    Text('Live trip progress',
                        style: AppType.body(12,
                            color: Colors.white.withValues(alpha: 0.8))),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: Colors.white),
            ],
          ),
        ),
      ),
    );
  }
}

class _DeliveredHero extends StatelessWidget {
  const _DeliveredHero({required this.match});
  final MatchSummary match;

  @override
  Widget build(BuildContext context) {
    return _SectionCard(
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: AppColors.emerald.withValues(alpha: 0.15),
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.task_alt_rounded,
                color: AppColors.emeraldDeep, size: 26),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Delivered',
                    style: AppType.body(15, w: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(
                  'Funds were released to the traveler.',
                  style: AppType.body(12,
                      color: AppColors.inkSoft, height: 1.4),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ReceiptCard extends StatelessWidget {
  const _ReceiptCard({required this.match});
  final MatchSummary match;

  @override
  Widget build(BuildContext context) {
    final offer = match.acceptedOffer;
    if (offer == null) return const SizedBox.shrink();
    return _SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Receipt', style: AppType.body(13.5, w: FontWeight.w700)),
          const SizedBox(height: 12),
          _ReceiptRow('Traveler payout', '${offer.baseAmountDzd} DZD'),
          _ReceiptRow('Platform fee',
              '${offer.commissionDzd + offer.baseFeeDzd} DZD'),
          const Divider(height: 18, color: AppColors.hairline),
          _ReceiptRow('Total paid', '${offer.totalDzd} DZD', bold: true),
        ],
      ),
    );
  }
}

class _ReceiptRow extends StatelessWidget {
  const _ReceiptRow(this.label, this.value, {this.bold = false});
  final String label;
  final String value;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(
              child: Text(label,
                  style: AppType.body(12.5,
                      color:
                          bold ? AppColors.ink : AppColors.inkSoft))),
          Text(value,
              style: AppType.body(13,
                  w: bold ? FontWeight.w800 : FontWeight.w600)),
        ],
      ),
    );
  }
}

class _ParcelInfoCard extends StatelessWidget {
  const _ParcelInfoCard({required this.parcel});
  final Parcel parcel;

  @override
  Widget build(BuildContext context) {
    return _SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Parcel info',
              style: AppType.body(13.5, w: FontWeight.w700)),
          const SizedBox(height: 10),
          _InfoRow('Route',
              '${parcel.origin.iata} → ${parcel.destination.iata}'),
          _InfoRow('Weight', '${parcel.weightKg} kg'),
          _InfoRow('Type',
              parcel.itemType.isEmpty ? parcel.kind : parcel.itemType),
          if (parcel.pickupCity.isNotEmpty)
            _InfoRow('Pickup city', parcel.pickupCity),
          if (parcel.deliveryCity.isNotEmpty)
            _InfoRow('Delivery city', parcel.deliveryCity),
          if (parcel.deadlineAt != null)
            _InfoRow('Deadline', _date(parcel.deadlineAt!)),
          if (parcel.description.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Notes',
                style: AppType.body(11.5,
                    color: AppColors.inkMute, w: FontWeight.w700)),
            const SizedBox(height: 2),
            Text(parcel.description,
                style: AppType.body(12.5,
                    color: AppColors.inkSoft, height: 1.45)),
          ],
        ],
      ),
    );
  }

  String _date(DateTime t) =>
      '${t.year}-${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')}';
}

class _InfoRow extends StatelessWidget {
  const _InfoRow(this.label, this.value);
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 110,
            child: Text(label,
                style: AppType.body(12, color: AppColors.inkMute)),
          ),
          Expanded(
            child: Text(value, style: AppType.body(12.5)),
          ),
        ],
      ),
    );
  }
}

class _HelpRow extends StatelessWidget {
  const _HelpRow();

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Support: support@shiptrip.dz')),
        );
      },
      borderRadius: BorderRadius.circular(AppRadius.md),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
        child: Row(
          children: [
            const Icon(Icons.help_outline_rounded,
                size: 18, color: AppColors.inkMute),
            const SizedBox(width: 8),
            Text('Need help with this request?',
                style: AppType.body(13, color: AppColors.inkSoft)),
          ],
        ),
      ),
    );
  }
}

class _CancelledBanner extends StatelessWidget {
  const _CancelledBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.terracotta.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border:
            Border.all(color: AppColors.terracotta.withValues(alpha: 0.5)),
      ),
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          const Icon(Icons.block_rounded, color: AppColors.terracotta),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              'This request was cancelled. Any pending offers were voided.',
              style: AppType.body(12.5,
                  color: AppColors.terracottaDeep, height: 1.45),
            ),
          ),
        ],
      ),
    );
  }
}

class _CancelButton extends ConsumerWidget {
  const _CancelButton({
    required this.parcelId,
    required this.enabled,
    this.warning,
  });
  final int parcelId;
  final bool enabled;
  final String? warning;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      children: [
        if (warning != null) ...[
          Text(warning!,
              style: AppType.body(11.5,
                  color: AppColors.inkMute, height: 1.4)),
          const SizedBox(height: 6),
        ],
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.terracotta,
            side: const BorderSide(color: AppColors.terracotta),
            padding: const EdgeInsets.symmetric(
                horizontal: 22, vertical: 12),
            shape: const StadiumBorder(),
          ),
          onPressed: enabled ? () => _confirm(context, ref) : null,
          icon: const Icon(Icons.cancel_outlined, size: 18),
          label: const Text('Cancel request'),
        ),
      ],
    );
  }

  Future<void> _confirm(BuildContext context, WidgetRef ref) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancel this request?'),
        content: const Text(
            'Any pending offers will be voided. You can\'t undo this.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Keep'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: AppColors.terracotta),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Cancel request'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(myParcelsProvider.notifier).cancel(parcelId);
      ref.invalidate(parcelByIdProvider(parcelId));
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Request cancelled.')),
        );
        context.pop();
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not cancel: $e')),
        );
      }
    }
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({required this.child, this.padded = true});
  final Widget child;
  final bool padded;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      padding: padded ? const EdgeInsets.all(16) : EdgeInsets.zero,
      child: child,
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(32),
      child: Center(
        child: Text('Could not load — $message',
            textAlign: TextAlign.center,
            style: AppType.body(13, color: AppColors.inkSoft)),
      ),
    );
  }
}
