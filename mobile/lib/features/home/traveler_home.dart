import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/mock/mock_data.dart';
import '../../shared/widgets/boarding_card.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/stamp_chip.dart';

class TravelerHome extends StatelessWidget {
  const TravelerHome({super.key});

  @override
  Widget build(BuildContext context) {
    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(child: _Header()),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
          sliver: SliverToBoxAdapter(child: _CreateTripCta()),
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
          sliver: SliverToBoxAdapter(child: _MyTripCard(t: mockMyTrips.first)),
        ),
        const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x6)),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
          sliver: SliverToBoxAdapter(
            child: _SectionHeader(title: "Offers received", action: "Filter"),
          ),
        ),
        const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x3)),
        SliverList.separated(
          separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.x4),
          itemCount: mockOffers.length,
          itemBuilder: (_, i) => Padding(
            padding: EdgeInsets.fromLTRB(AppSpacing.x6, 0, AppSpacing.x6,
                i == mockOffers.length - 1 ? 110 : 0),
            child: _OfferCard(o: mockOffers[i])
                .animate()
                .fadeIn(delay: Duration(milliseconds: 80 * i), duration: 400.ms)
                .moveY(begin: 14, end: 0, curve: kAppCurve),
          ),
        ),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
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
                _Stat(label: "Earnings (mo)", value: "12 400", unit: "DZD", accent: AppColors.emerald),
                const SizedBox(width: AppSpacing.x3),
                _Stat(label: "Active trips", value: "1", unit: "", accent: AppColors.terracotta),
                const SizedBox(width: AppSpacing.x3),
                _Stat(label: "Rating", value: "4.9", unit: "★", accent: AppColors.gold),
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

class _MyTripCard extends StatelessWidget {
  const _MyTripCard({required this.t});
  final MockTrip t;
  @override
  Widget build(BuildContext context) {
    final pct = t.booked / t.total;
    return BoardingCard(
      color: AppColors.ink,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StampChip(label: t.status.toUpperCase(), color: AppColors.gold),
              const Spacer(),
              Text("Trip #A1004",
                  style: AppType.mono(11, color: AppColors.parchmentDeep)),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              CountryPill(code: t.originCode, label: t.origin, dense: true),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: CustomPaint(
                    painter: _DashOnDarkPainter(),
                    size: const Size.fromHeight(20),
                  ),
                ),
              ),
              CountryPill(code: t.destCode, label: t.dest, dense: true),
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
                  Text("DEPARTURE", style: AppType.eyebrow(color: AppColors.parchmentDeep)),
                  const SizedBox(height: 4),
                  Text(t.date, style: AppType.mono(13.5, color: AppColors.parchment, w: FontWeight.w700)),
                ],
              ),
              const SizedBox(width: AppSpacing.x6),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("CAPACITY", style: AppType.eyebrow(color: AppColors.parchmentDeep)),
                  const SizedBox(height: 4),
                  Text("${t.booked} / ${t.total} kg",
                      style: AppType.mono(13.5, color: AppColors.parchment, w: FontWeight.w700)),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          // capacity progress
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.pill),
            child: Stack(
              children: [
                Container(height: 8, color: AppColors.parchment.withValues(alpha: 0.15)),
                FractionallySizedBox(
                  widthFactor: pct,
                  child: Container(
                    height: 8,
                    decoration: const BoxDecoration(color: AppColors.terracotta),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _OfferCard extends StatelessWidget {
  const _OfferCard({required this.o});
  final MockOffer o;
  @override
  Widget build(BuildContext context) {
    final isCounter = o.status == "Counter";
    return GestureDetector(
      onTap: () => context.push('/offer', extra: o),
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
                  o.senderName.split(' ').map((s) => s[0]).take(2).join(),
                  style: AppType.display(13, w: FontWeight.w600, color: AppColors.terracottaDeep),
                ),
              ),
              const SizedBox(width: 12),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(o.senderName, style: AppType.display(16, w: FontWeight.w500)),
                  Text(o.when, style: AppType.body(12, color: AppColors.inkMute)),
                ],
              ),
              const Spacer(),
              StampChip(
                label: o.status,
                color: isCounter ? AppColors.warning : AppColors.terracotta,
                angle: 0.06,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("ITEM", style: AppType.eyebrow()),
                    const SizedBox(height: 4),
                    Text(o.item, style: AppType.body(13.5, w: FontWeight.w600)),
                    const SizedBox(height: 4),
                    Text("${o.weightKg} kg · ${o.pickupCity} → ${o.deliveryCity}",
                        style: AppType.body(11.5, color: AppColors.inkMute)),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text("PROPOSED", style: AppType.eyebrow()),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Text(_fmt(o.proposedPrice),
                          style: AppType.mono(18, w: FontWeight.w700)),
                      const SizedBox(width: 4),
                      Text("DZD", style: AppType.mono(11, color: AppColors.inkMute)),
                    ],
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          const DashedDivider(),
          const SizedBox(height: AppSpacing.x4),
          Row(
            children: [
              Expanded(
                child: GestureDetector(
                  onTap: () {},
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(AppRadius.pill),
                      border: Border.all(color: AppColors.hairline, width: 1.4),
                    ),
                    alignment: Alignment.center,
                    child: Text("Counter",
                        style: AppType.body(13, w: FontWeight.w600)),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  decoration: BoxDecoration(
                    color: AppColors.ink,
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                  ),
                  alignment: Alignment.center,
                  child: Text("Accept",
                      style: AppType.body(13,
                          color: AppColors.parchment, w: FontWeight.w700)),
                ),
              ),
            ],
          ),
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
