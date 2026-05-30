import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/matching/matching_providers.dart';
import '../../core/matching/matching_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/trips/trips_providers.dart';
import '../../core/trips/trips_repository.dart';
import '../../shared/widgets/boarding_card.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/stamp_chip.dart';

class TravelerHome extends ConsumerWidget {
  const TravelerHome({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tripsAsync = ref.watch(myTripsProvider);
    return RefreshIndicator(
      onRefresh: () => ref.read(myTripsProvider.notifier).refresh(),
      child: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(child: _Header(activeTrips: tripsAsync.value)),
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
            sliver: SliverToBoxAdapter(child: _CreateTripCta()),
          ),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(child: _FindParcelsCta()),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x6)),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(
              child: _SectionHeader(title: "Your trips", action: "Manage"),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x3)),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(
              child: tripsAsync.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(20),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (e, _) => _ErrorTile(
                  message: e.toString(),
                  onRetry: () => ref.read(myTripsProvider.notifier).refresh(),
                ),
                data: (trips) => trips.isEmpty
                    ? const _EmptyTrips()
                    : Column(
                        children: [
                          for (final t in trips.take(3))
                            Padding(
                              padding: const EdgeInsets.only(bottom: AppSpacing.x3),
                              child: _MyTripCard(t: t),
                            ),
                        ],
                      ),
              ),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x6)),
          const _AwaitingPickupSection(),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(
              child: _SectionHeader(title: "Senders interested in your trips", action: ""),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x3)),
          const _IncomingOffersSection(),
        ],
      ),
    );
  }
}

class _IncomingOffersSection extends ConsumerWidget {
  const _IncomingOffersSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    const params = MatchListParams(role: 'traveler', status: 'pending');
    final async = ref.watch(matchListProvider(params));
    return async.when(
      loading: () => const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.all(20),
          child: Center(child: CircularProgressIndicator()),
        ),
      ),
      error: (e, _) => SliverPadding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
        sliver: SliverToBoxAdapter(
          child: _ErrorTile(
            message: "Couldn't load incoming offers.",
            onRetry: () => ref.invalidate(matchListProvider(params)),
          ),
        ),
      ),
      data: (matches) {
        if (matches.isEmpty) {
          return const SliverPadding(
            padding: EdgeInsets.fromLTRB(
                AppSpacing.x6, 0, AppSpacing.x6, 110),
            sliver: SliverToBoxAdapter(child: _NoIncomingTile()),
          );
        }
        return SliverList.separated(
          separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.x4),
          itemCount: matches.length,
          itemBuilder: (_, i) => Padding(
            padding: EdgeInsets.fromLTRB(AppSpacing.x6, 0, AppSpacing.x6,
                i == matches.length - 1 ? 110 : 0),
            child: _IncomingMatchCard(match: matches[i])
                .animate()
                .fadeIn(delay: Duration(milliseconds: 60 * i), duration: 350.ms)
                .moveY(begin: 14, end: 0, curve: kAppCurve),
          ),
        );
      },
    );
  }
}

/// Matches the traveler accepted that the sender then PAID — the sender is
/// now looking at the pickup code, and the traveler needs to coordinate
/// pickup and enter the code. Surfaces above the offer-shopping list so it
/// always wins the eye.
class _AwaitingPickupSection extends ConsumerWidget {
  const _AwaitingPickupSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    const params = MatchListParams(role: 'traveler', status: 'accepted');
    final async = ref.watch(matchListProvider(params));
    return async.maybeWhen(
      data: (matches) {
        if (matches.isEmpty) {
          return const SliverToBoxAdapter(child: SizedBox.shrink());
        }
        return SliverPadding(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x6),
          sliver: SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _SectionHeader(title: "Awaiting pickup", action: ""),
                const SizedBox(height: AppSpacing.x3),
                for (final m in matches)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.x3),
                    child: _AwaitingPickupCard(match: m),
                  ),
              ],
            ),
          ),
        );
      },
      orElse: () => const SliverToBoxAdapter(child: SizedBox.shrink()),
    );
  }
}

class _AwaitingPickupCard extends StatelessWidget {
  const _AwaitingPickupCard({required this.match});
  final MatchSummary match;

  @override
  Widget build(BuildContext context) {
    final parcel = match.parcel;
    final route = parcel != null
        ? "${parcel.originIata} → ${parcel.destinationIata}"
        : "Match #${match.id}";
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        onTap: () =>
            context.push('/handover/verify/${match.id}?kind=pickup'),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border:
                Border.all(color: AppColors.gold.withValues(alpha: 0.5), width: 1.5),
            color: AppColors.gold.withValues(alpha: 0.05),
          ),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: AppColors.gold.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(Icons.inventory_2_outlined,
                    color: AppColors.goldDeep),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(route,
                        style: AppType.body(14.5, w: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(
                      "Sender paid — ask for the pickup code",
                      style: AppType.body(12, color: AppColors.inkSoft),
                    ),
                  ],
                ),
              ),
              Icon(Icons.arrow_forward_rounded,
                  size: 18, color: AppColors.goldDeep),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoIncomingTile extends StatelessWidget {
  const _NoIncomingTile();
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x5),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          const Icon(Icons.mark_email_unread_outlined,
              color: AppColors.inkMute),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("No incoming offers yet",
                    style: AppType.body(13.5, w: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(
                  "Apply to open parcels — when a sender accepts, they'll appear here.",
                  style: AppType.body(11.5,
                      color: AppColors.inkMute, height: 1.4),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _IncomingMatchCard extends StatelessWidget {
  const _IncomingMatchCard({required this.match});
  final MatchSummary match;

  @override
  Widget build(BuildContext context) {
    final latestOffer = match.latestOffer;
    final parcel = match.parcel;
    final route = parcel != null
        ? "${parcel.originIata} → ${parcel.destinationIata}"
        : "Match #${match.id}";
    final subtitle = parcel != null
        ? "${parcel.weightKg} kg · ${parcel.kind == 'product' ? 'product' : 'delivery'}"
        : "Parcel #${match.parcelId}";
    return GestureDetector(
      onTap: () => context.push('/match/${match.id}'),
      child: BoardingCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(
                    color: AppColors.terracotta.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    "S${match.senderId}",
                    style: AppType.body(11,
                        w: FontWeight.w700, color: AppColors.terracottaDeep),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(route,
                          style: AppType.display(16, w: FontWeight.w500)),
                      Text(subtitle,
                          style: AppType.body(12, color: AppColors.inkMute)),
                    ],
                  ),
                ),
                StampChip(label: "PENDING", color: AppColors.terracotta, angle: 0.06),
              ],
            ),
            if (latestOffer != null) ...[
              const SizedBox(height: AppSpacing.x4),
              const DashedDivider(),
              const SizedBox(height: AppSpacing.x4),
              Row(
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text("YOUR PAYOUT", style: AppType.eyebrow()),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Text(_fmt(latestOffer.baseAmountDzd),
                              style:
                                  AppType.mono(18, w: FontWeight.w700)),
                          const SizedBox(width: 4),
                          Text("DZD",
                              style: AppType.mono(11,
                                  color: AppColors.inkMute)),
                        ],
                      ),
                    ],
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 10),
                    decoration: BoxDecoration(
                      color: AppColors.ink,
                      borderRadius: BorderRadius.circular(AppRadius.pill),
                    ),
                    child: Row(
                      children: [
                        Text("Review",
                            style: AppType.body(12.5,
                                color: AppColors.parchment,
                                w: FontWeight.w700)),
                        const SizedBox(width: 6),
                        const Icon(Icons.arrow_forward_rounded,
                            size: 14, color: AppColors.parchment),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  static String _fmt(int n) {
    final s = n.toString();
    return s.replaceAllMapped(
        RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => "${m[1]} ");
  }
}

class _FindParcelsCta extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/traveler/find'),
      child: Container(
        padding: const EdgeInsets.fromLTRB(20, 16, 12, 16),
        decoration: BoxDecoration(
          color: AppColors.ink,
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        child: Row(
          children: [
            const Icon(Icons.travel_explore_rounded, color: AppColors.parchment),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("Find parcels to carry",
                      style: AppType.body(15,
                          color: AppColors.parchment, w: FontWeight.w600)),
                  Text("Browse open requests and apply with your trip",
                      style: AppType.body(12, color: AppColors.parchmentDeep)),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: AppColors.parchmentSoft.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(AppRadius.pill),
              ),
              child: const Icon(Icons.arrow_forward_rounded,
                  color: AppColors.parchment, size: 16),
            ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({this.activeTrips});
  final List<Trip>? activeTrips;
  @override
  Widget build(BuildContext context) {
    final activeCount = activeTrips
            ?.where((t) =>
                t.status == 'active' ||
                t.status == 'in_transit' ||
                t.status == 'draft')
            .length ??
        0;
    return SafeArea(
      bottom: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.x6, AppSpacing.x6, AppSpacing.x6, AppSpacing.x4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("Bon voyage · Traveler mode",
                        style: AppType.eyebrow().copyWith(letterSpacing: 1.4)),
                    const SizedBox(height: 6),
                    Text("Earn from\nyour empty kilos.",
                        style: AppType.display(34, w: FontWeight.w400, height: 1.05)),
                  ],
                ),
                const Spacer(),
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: AppColors.parchmentSoft,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: AppColors.hairline),
                  ),
                  child: const Icon(Icons.tune_rounded, size: 20, color: AppColors.ink),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.x6),
            Row(
              children: [
                _Stat(label: "Earnings (mo)", value: "0", unit: "DZD", accent: AppColors.emerald),
                const SizedBox(width: AppSpacing.x3),
                _Stat(
                    label: "Active trips",
                    value: "$activeCount",
                    unit: "",
                    accent: AppColors.terracotta),
                const SizedBox(width: AppSpacing.x3),
                _Stat(label: "Rating", value: "—", unit: "", accent: AppColors.gold),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, required this.unit, required this.accent});
  final String label;
  final String value;
  final String unit;
  final Color accent;
  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.x4),
        decoration: BoxDecoration(
          color: AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: AppColors.hairline),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(width: 6, height: 6, decoration: BoxDecoration(color: accent, shape: BoxShape.circle)),
            const SizedBox(height: 10),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Flexible(
                  child: Text(value,
                      style: AppType.display(22, w: FontWeight.w500),
                      overflow: TextOverflow.ellipsis),
                ),
                if (unit.isNotEmpty) ...[
                  const SizedBox(width: 3),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(unit,
                        style: AppType.mono(10, color: AppColors.inkMute, w: FontWeight.w600)),
                  ),
                ],
              ],
            ),
            Text(label, style: AppType.body(11, color: AppColors.inkMute, w: FontWeight.w500)),
          ],
        ),
      ),
    );
  }
}

class _CreateTripCta extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/traveler/new'),
      child: Container(
        padding: const EdgeInsets.fromLTRB(20, 18, 14, 18),
        decoration: BoxDecoration(
          color: AppColors.emerald,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          boxShadow: AppShadows.elevated,
        ),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: AppColors.parchmentSoft.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Icon(Icons.add_road_rounded, color: AppColors.parchment),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("List a new trip",
                      style: AppType.body(15, color: AppColors.parchment, w: FontWeight.w700)),
                  Text("Upload your ticket, set capacity, get matched",
                      style: AppType.body(12, color: AppColors.parchmentDeep)),
                ],
              ),
            ),
            const Icon(Icons.arrow_forward_rounded, color: AppColors.parchment),
            const SizedBox(width: 6),
          ],
        ),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, required this.action});
  final String title;
  final String action;
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(title, style: AppType.display(20, w: FontWeight.w500)),
        const Spacer(),
        Text(action, style: AppType.body(12.5, color: AppColors.inkMute, w: FontWeight.w600)),
        const Icon(Icons.arrow_forward_rounded, size: 14, color: AppColors.inkMute),
      ],
    );
  }
}

class _EmptyTrips extends StatelessWidget {
  const _EmptyTrips();
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x6),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: AppColors.parchment,
              borderRadius: BorderRadius.circular(AppRadius.pill),
              border: Border.all(color: AppColors.hairline),
            ),
            child: const Icon(Icons.flight_takeoff_rounded,
                color: AppColors.inkMute, size: 24),
          ),
          const SizedBox(height: 12),
          Text("No trips yet",
              style: AppType.display(18, w: FontWeight.w500)),
          const SizedBox(height: 4),
          Text("List your next flight to start earning.",
              style: AppType.body(13, color: AppColors.inkMute),
              textAlign: TextAlign.center),
        ],
      ),
    );
  }
}

class _ErrorTile extends StatelessWidget {
  const _ErrorTile({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.terracotta.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.terracotta.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          const Icon(Icons.cloud_off_rounded, color: AppColors.terracotta),
          const SizedBox(width: 12),
          Expanded(
            child: Text("Couldn't load your trips.",
                style: AppType.body(13, w: FontWeight.w600)),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

class _MyTripCard extends StatelessWidget {
  const _MyTripCard({required this.t});
  final Trip t;
  @override
  Widget build(BuildContext context) {
    return BoardingCard(
      color: AppColors.ink,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StampChip(label: t.status.toUpperCase(), color: AppColors.gold),
              const Spacer(),
              Text("Trip #${t.id}",
                  style: AppType.mono(11, color: AppColors.parchmentDeep)),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              CountryPill(
                  code: t.origin.country, label: t.origin.iata, dense: true),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: CustomPaint(
                    painter: _DashOnDarkPainter(),
                    size: const Size.fromHeight(20),
                  ),
                ),
              ),
              CountryPill(
                  code: t.destination.country,
                  label: t.destination.iata,
                  dense: true),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          DashedDivider(color: AppColors.parchment.withValues(alpha: 0.2)),
          const SizedBox(height: AppSpacing.x4),
          Row(
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("DEPARTURE",
                      style: AppType.eyebrow(color: AppColors.parchmentDeep)),
                  const SizedBox(height: 4),
                  Text(_fmtDate(t.departureAt),
                      style: AppType.mono(13.5,
                          color: AppColors.parchment, w: FontWeight.w700)),
                ],
              ),
              const SizedBox(width: AppSpacing.x6),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("CAPACITY",
                      style: AppType.eyebrow(color: AppColors.parchmentDeep)),
                  const SizedBox(height: 4),
                  Text("${t.capacityKg} kg",
                      style: AppType.mono(13.5,
                          color: AppColors.parchment, w: FontWeight.w700)),
                ],
              ),
              const SizedBox(width: AppSpacing.x6),
              if (t.flightNumber.isNotEmpty)
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("FLIGHT",
                        style: AppType.eyebrow(color: AppColors.parchmentDeep)),
                    const SizedBox(height: 4),
                    Text(t.flightNumber,
                        style: AppType.mono(13.5,
                            color: AppColors.parchment, w: FontWeight.w700)),
                  ],
                ),
            ],
          ),
        ],
      ),
    );
  }

  static String _fmtDate(DateTime d) {
    const months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec'
    ];
    final l = d.toLocal();
    return "${l.day.toString().padLeft(2, '0')} ${months[l.month - 1]} · ${l.hour.toString().padLeft(2, '0')}:${l.minute.toString().padLeft(2, '0')}";
  }
}

class _DashOnDarkPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = AppColors.parchment.withValues(alpha: 0.25)
      ..strokeWidth = 1.2;
    const dashW = 4.0, gap = 3.0;
    double x = 0;
    while (x < size.width) {
      canvas.drawLine(Offset(x, size.height / 2), Offset(x + dashW, size.height / 2), p);
      x += dashW + gap;
    }
    final plane = Paint()..color = AppColors.terracotta;
    canvas.save();
    canvas.translate(size.width / 2, size.height / 2);
    final path = Path()
      ..moveTo(8, 0)
      ..lineTo(-6, -4)
      ..lineTo(-3, 0)
      ..lineTo(-6, 4)
      ..close();
    canvas.drawPath(path, plane);
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _DashOnDarkPainter old) => false;
}
