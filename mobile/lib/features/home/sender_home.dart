import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/parcels/parcels_providers.dart';
import '../../core/parcels/parcels_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/mock/mock_data.dart';
import '../../shared/widgets/boarding_card.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/stamp_chip.dart';

class SenderHome extends ConsumerWidget {
  const SenderHome({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final parcelsAsync = ref.watch(myParcelsProvider);
    return RefreshIndicator(
      onRefresh: () => ref.read(myParcelsProvider.notifier).refresh(),
      child: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(child: _Header(parcels: parcelsAsync.value)),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(child: _NewRequestCta()),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x4)),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(child: _SearchAction()),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x6)),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(
                child: _SectionHeader(title: "Your requests", action: "All")),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x3)),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(
              child: parcelsAsync.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(20),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (_, _) => _ErrorTile(
                  onRetry: () => ref.read(myParcelsProvider.notifier).refresh(),
                ),
                data: (parcels) => parcels.isEmpty
                    ? const _EmptyParcels()
                    : Column(
                        children: [
                          for (final p in parcels.take(3))
                            Padding(
                              padding: const EdgeInsets.only(bottom: AppSpacing.x3),
                              child: _ParcelCard(p: p),
                            ),
                        ],
                      ),
              ),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x6)),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            sliver: SliverToBoxAdapter(
              child: _SectionHeader(title: "Suggested travelers", action: "See all"),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x3)),
          SliverList.separated(
            separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.x4),
            itemCount: mockTravelers.length,
            itemBuilder: (_, i) => Padding(
              padding: EdgeInsets.fromLTRB(AppSpacing.x6, 0, AppSpacing.x6,
                  i == mockTravelers.length - 1 ? 110 : 0),
              child: _TravelerCard(t: mockTravelers[i])
                  .animate()
                  .fadeIn(delay: Duration(milliseconds: 80 * i), duration: 400.ms)
                  .moveY(begin: 14, end: 0, curve: kAppCurve),
            ),
          ),
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({this.parcels});
  final List<Parcel>? parcels;
  @override
  Widget build(BuildContext context) {
    final list = parcels ?? const <Parcel>[];
    final open = list.where((p) => p.status == 'open').length;
    final inTransit =
        list.where((p) => p.status == 'matched' || p.status == 'in_transit').length;
    final delivered =
        list.where((p) => p.status == 'delivered' || p.status == 'completed').length;
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
                    Text("As-salaam · Sender mode",
                        style: AppType.eyebrow().copyWith(letterSpacing: 1.4)),
                    const SizedBox(height: 6),
                    Text("Where to,\nfriend?",
                        style: AppType.display(36, w: FontWeight.w400, height: 1.05)),
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
                _Stat(label: "Open requests", value: "$open", accent: AppColors.terracotta),
                const SizedBox(width: AppSpacing.x3),
                _Stat(label: "In transit", value: "$inTransit", accent: AppColors.emerald),
                const SizedBox(width: AppSpacing.x3),
                _Stat(label: "Delivered", value: "$delivered", accent: AppColors.gold),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, required this.accent});
  final String label;
  final String value;
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
            Text(value, style: AppType.display(28, w: FontWeight.w500)),
            Text(label, style: AppType.body(11.5, color: AppColors.inkMute, w: FontWeight.w500)),
          ],
        ),
      ),
    );
  }
}

class _NewRequestCta extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/sender/new'),
      child: Container(
        padding: const EdgeInsets.fromLTRB(20, 18, 14, 18),
        decoration: BoxDecoration(
          color: AppColors.terracotta,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          boxShadow: AppShadows.elevated,
        ),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: AppColors.parchmentSoft.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Icon(Icons.add_box_outlined, color: AppColors.parchment),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("Post a new request",
                      style: AppType.body(15, color: AppColors.parchment, w: FontWeight.w700)),
                  Text("Send a parcel or have one bought for you",
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

class _SearchAction extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/sender/search'),
      child: Container(
        padding: const EdgeInsets.fromLTRB(20, 16, 12, 16),
        decoration: BoxDecoration(
          color: AppColors.ink,
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        child: Row(
          children: [
            const Icon(Icons.search_rounded, color: AppColors.parchment),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("Find a traveler",
                      style: AppType.body(15, color: AppColors.parchment, w: FontWeight.w600)),
                  Text("Algiers → Paris · this week",
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

class _EmptyParcels extends StatelessWidget {
  const _EmptyParcels();
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
            child: const Icon(Icons.inventory_2_outlined,
                color: AppColors.inkMute, size: 24),
          ),
          const SizedBox(height: 12),
          Text("No requests yet",
              style: AppType.display(18, w: FontWeight.w500)),
          const SizedBox(height: 4),
          Text("Post a parcel or product request to get started.",
              style: AppType.body(13, color: AppColors.inkMute),
              textAlign: TextAlign.center),
        ],
      ),
    );
  }
}

class _ErrorTile extends StatelessWidget {
  const _ErrorTile({required this.onRetry});
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
            child: Text("Couldn't load your requests.",
                style: AppType.body(13, w: FontWeight.w600)),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

class _ParcelCard extends StatelessWidget {
  const _ParcelCard({required this.p});
  final Parcel p;
  @override
  Widget build(BuildContext context) {
    final amount = p.kind == 'product' ? p.productPriceDzd : p.baseAmountDzd;
    return BoardingCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: p.kind == 'product'
                      ? AppColors.gold.withValues(alpha: 0.18)
                      : AppColors.emerald.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  p.kind == 'product' ? "PRODUCT" : "DELIVERY",
                  style: AppType.mono(10,
                      color: p.kind == 'product'
                          ? AppColors.goldDeep
                          : AppColors.emeraldDeep,
                      w: FontWeight.w700),
                ),
              ),
              const Spacer(),
              StampChip(
                label: p.status.toUpperCase(),
                color: p.status == 'cancelled'
                    ? AppColors.inkMute
                    : AppColors.terracotta,
                angle: 0.04,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              CountryPill(code: p.origin.country, label: p.origin.iata, dense: true),
              const SizedBox(width: 8),
              const Icon(Icons.arrow_forward_rounded,
                  color: AppColors.inkMute, size: 14),
              const SizedBox(width: 8),
              CountryPill(code: p.destination.country, label: p.destination.iata, dense: true),
              const Spacer(),
              Text("${p.weightKg} kg",
                  style: AppType.mono(13, w: FontWeight.w700)),
            ],
          ),
          if ((p.storeName ?? '').isNotEmpty || p.description.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.x3),
            Text(
              p.kind == 'product'
                  ? (p.storeName ?? '')
                  : p.description,
              style: AppType.body(13, w: FontWeight.w500),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
          if (amount != null) ...[
            const SizedBox(height: AppSpacing.x3),
            Row(
              children: [
                Text(p.kind == 'product' ? "Price" : "Base amount",
                    style: AppType.body(12, color: AppColors.inkMute)),
                const Spacer(),
                Text("${_fmt(amount)} DZD",
                    style: AppType.mono(14, w: FontWeight.w700)),
              ],
            ),
          ],
        ],
      ),
    );
  }

  static String _fmt(int n) {
    final s = n.toString();
    return s.replaceAllMapped(
        RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => "${m[1]} ");
  }
}

class _TravelerCard extends StatelessWidget {
  const _TravelerCard({required this.t});
  final MockTraveler t;

  @override
  Widget build(BuildContext context) {
    return BoardingCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: AppColors.emerald.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                alignment: Alignment.center,
                child: Text(t.avatar,
                    style: AppType.display(15, w: FontWeight.w600, color: AppColors.emerald)),
              ),
              const SizedBox(width: 12),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(t.name, style: AppType.display(17, w: FontWeight.w500)),
                      const SizedBox(width: 6),
                      if (t.kyc)
                        const Icon(Icons.verified_rounded, size: 14, color: AppColors.emerald),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    "${(t.rating / 10).toStringAsFixed(1)} ★ · ${t.trips} trips",
                    style: AppType.body(12, color: AppColors.inkMute, w: FontWeight.w500),
                  ),
                ],
              ),
              const Spacer(),
              StampChip(label: "VERIFIED", color: AppColors.emerald),
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
                    painter: _DashLinePainter(),
                    size: const Size.fromHeight(20),
                  ),
                ),
              ),
              CountryPill(code: t.destCode, label: t.dest, dense: true),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          const DashedDivider(),
          const SizedBox(height: AppSpacing.x4),
          Row(
            children: [
              _Meta(label: "FLIGHT", value: t.flightNo),
              const SizedBox(width: AppSpacing.x6),
              _Meta(label: "DATE", value: t.date),
              const Spacer(),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text("FROM", style: AppType.eyebrow()),
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      Text(_fmt(t.pricePerKg),
                          style: AppType.mono(15, w: FontWeight.w700)),
                      const SizedBox(width: 4),
                      Text("DZD/kg",
                          style: AppType.mono(11, color: AppColors.inkMute)),
                    ],
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: AppColors.gold.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.luggage_rounded, size: 14, color: AppColors.goldDeep),
                    const SizedBox(width: 4),
                    Text("${t.kgFree} kg free",
                        style: AppType.body(11.5,
                            color: AppColors.goldDeep, w: FontWeight.w700)),
                  ],
                ),
              ),
              const Spacer(),
              GestureDetector(
                onTap: () => context.push('/sender/offer', extra: t),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  decoration: BoxDecoration(
                    color: AppColors.ink,
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                  ),
                  child: Row(
                    children: [
                      Text("Request",
                          style: AppType.body(12.5,
                              color: AppColors.parchment, w: FontWeight.w600)),
                      const SizedBox(width: 6),
                      const Icon(Icons.arrow_forward_rounded,
                          size: 14, color: AppColors.parchment),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static String _fmt(int n) {
    final s = n.toString();
    return s.replaceAllMapped(
      RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
      (m) => "${m[1]} ",
    );
  }
}

class _Meta extends StatelessWidget {
  const _Meta({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: AppType.eyebrow()),
        const SizedBox(height: 2),
        Text(value, style: AppType.mono(13, w: FontWeight.w600)),
      ],
    );
  }
}

class _DashLinePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = AppColors.hairline
      ..strokeWidth = 1.2;
    const dashW = 4.0, gap = 3.0;
    double x = 0;
    while (x < size.width) {
      canvas.drawLine(Offset(x, size.height / 2), Offset(x + dashW, size.height / 2), p);
      x += dashW + gap;
    }
    final plane = Paint()..color = AppColors.ink;
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
  bool shouldRepaint(covariant _DashLinePainter old) => false;
}
