import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/stamp_chip.dart';

enum _Kind { offer, payment, code, delivered, kyc }

class _Notif {
  final _Kind kind;
  final String title;
  final String body;
  final String time;
  final bool unread;
  const _Notif(this.kind, this.title, this.body, this.time, this.unread);
}

const _today = <_Notif>[
  _Notif(_Kind.offer, "New offer · 4 500 DZD",
      "Nadia H. wants to send 2 kg via your Algiers → Paris trip.", "12:04", true),
  _Notif(_Kind.payment, "Payment received",
      "Escrow confirmed for trip ALG → CDG · 6 200 DZD held until delivery.", "10:22", true),
];

const _earlier = <_Notif>[
  _Notif(_Kind.code, "Pickup code requested",
      "Yacine M. is at the pickup point — share code 4192.", "yesterday", true),
  _Notif(_Kind.delivered, "Delivered to Lyon",
      "Soraya A. confirmed delivery. 9 000 DZD released to wallet.", "Apr 23", false),
  _Notif(_Kind.kyc, "KYC approved",
      "You can now publish trips. Welcome aboard.", "Apr 21", false),
];

class NotificationsScreen extends StatelessWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, AppSpacing.x6, AppSpacing.x6, AppSpacing.x4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text("Inbox", style: AppType.eyebrow()),
                      const Spacer(),
                      Text("Mark all read",
                          style: AppType.body(12, color: AppColors.inkMute, w: FontWeight.w600)),
                    ],
                  ),
                  Text("Stamps & seals",
                      style: AppType.display(34, w: FontWeight.w400, height: 1)),
                ],
              ),
            ),
          ),
        ),
        const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x3)),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
          sliver: SliverToBoxAdapter(child: _Header(label: "TODAY")),
        ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.x6, 8, AppSpacing.x6, 0),
          sliver: SliverList.separated(
            separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.x3),
            itemCount: _today.length,
            itemBuilder: (_, i) => _NotifTile(n: _today[i])
                .animate()
                .fadeIn(delay: Duration(milliseconds: 60 * i), duration: 350.ms),
          ),
        ),
        const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x6)),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
          sliver: SliverToBoxAdapter(child: _Header(label: "EARLIER")),
        ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.x6, 8, AppSpacing.x6, 110),
          sliver: SliverList.separated(
            separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.x3),
            itemCount: _earlier.length,
            itemBuilder: (_, i) => _NotifTile(n: _earlier[i])
                .animate()
                .fadeIn(delay: Duration(milliseconds: 60 * i), duration: 350.ms),
          ),
        ),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(label, style: AppType.eyebrow().copyWith(letterSpacing: 1.8)),
        const SizedBox(width: 10),
        Expanded(child: Container(height: 1, color: AppColors.hairline)),
      ],
    );
  }
}

class _NotifTile extends StatelessWidget {
  const _NotifTile({required this.n});
  final _Notif n;

  String? _routeFor(_Kind k) => switch (k) {
        _Kind.offer => '/payment/OF-001',
        _Kind.payment => '/code/OF-001',
        _Kind.code => '/tracking/TR-001',
        _Kind.delivered => '/tracking/TR-001',
        _Kind.kyc => null,
      };

  ({IconData icon, Color color, String stamp}) get _meta => switch (n.kind) {
        _Kind.offer => (icon: Icons.local_offer_rounded, color: AppColors.terracotta, stamp: "OFFER"),
        _Kind.payment => (icon: Icons.payments_rounded, color: AppColors.emerald, stamp: "PAID"),
        _Kind.code => (icon: Icons.pin_rounded, color: AppColors.gold, stamp: "CODE"),
        _Kind.delivered => (icon: Icons.check_circle_rounded, color: AppColors.emerald, stamp: "DONE"),
        _Kind.kyc => (icon: Icons.verified_user_rounded, color: AppColors.ink, stamp: "KYC"),
      };

  @override
  Widget build(BuildContext context) {
    final m = _meta;
    final route = _routeFor(n.kind);
    return GestureDetector(
      onTap: route == null ? null : () => context.push(route),
      child: Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: n.unread ? AppColors.parchmentSoft : AppColors.parchment,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: m.color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(m.icon, color: m.color, size: 20),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(n.title,
                          style: AppType.body(14, w: FontWeight.w700)),
                    ),
                    StampChip(label: m.stamp, color: m.color),
                  ],
                ),
                const SizedBox(height: 4),
                Text(n.body,
                    style: AppType.body(12.5, color: AppColors.inkSoft, height: 1.4)),
                const SizedBox(height: 6),
                Text(n.time, style: AppType.mono(10.5, color: AppColors.inkMute)),
              ],
            ),
          ),
          if (n.unread) ...[
            const SizedBox(width: 8),
            Container(
              width: 8,
              height: 8,
              decoration: const BoxDecoration(
                color: AppColors.terracotta,
                shape: BoxShape.circle,
              ),
            ),
          ],
        ],
      ),
      ),
    );
  }
}
