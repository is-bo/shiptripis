import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/mock/mock_data.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

/// Traveler-side full detail of a sender's offer.
/// Shows sender info, item photos, pickup/dropoff, accept/counter/reject.
class OfferDetailScreen extends StatelessWidget {
  const OfferDetailScreen({super.key, required this.offer});
  final MockOffer offer;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Column(
          children: [
            _topBar(context),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
                children: [
                  Text("Offer", style: AppType.eyebrow()),
                  const SizedBox(height: 6),
                  Text(offer.item,
                      style: AppType.display(30, w: FontWeight.w400, height: 1.05)),
                  const SizedBox(height: AppSpacing.x5),
                  _priceBlock()
                      .animate()
                      .fadeIn(duration: 320.ms)
                      .slideY(begin: 0.05),
                  const SizedBox(height: AppSpacing.x5),
                  _senderCard(),
                  const SizedBox(height: AppSpacing.x5),
                  _label("Photos"),
                  const SizedBox(height: 10),
                  _photoGallery(),
                  const SizedBox(height: AppSpacing.x5),
                  _label("Trip details"),
                  const SizedBox(height: 10),
                  _detailRows(),
                  const SizedBox(height: AppSpacing.x5),
                  _label("Notes from sender"),
                  const SizedBox(height: 10),
                  _notes(),
                  const SizedBox(height: AppSpacing.x6),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
              child: Row(
                children: [
                  GhostButton(
                    label: "Decline",
                    icon: Icons.close_rounded,
                    onTap: () => context.pop(),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: PrimaryButton(
                      label: "Accept · ${_fmt(offer.proposedPrice)} DZD",
                      icon: Icons.check_rounded,
                      expand: true,
                      color: AppColors.emerald,
                      onTap: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            backgroundColor: AppColors.emerald,
                            content: Text(
                                "Accepted — ${offer.senderName} will pay now",
                                style: AppType.body(13.5,
                                    color: AppColors.parchment,
                                    w: FontWeight.w500)),
                          ),
                        );
                        context.pop();
                      },
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _topBar(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x4, AppSpacing.x4, AppSpacing.x4, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => context.pop(),
            icon: const Icon(Icons.arrow_back_rounded),
            style: IconButton.styleFrom(
              backgroundColor: AppColors.parchmentSoft,
              shape: const CircleBorder(),
            ),
          ),
          const Spacer(),
          StampChip(label: offer.status.toUpperCase(), color: AppColors.terracotta),
          const SizedBox(width: 6),
          IconButton(
            onPressed: () {},
            icon: const Icon(Icons.flag_outlined, size: 18),
            style: IconButton.styleFrom(
              backgroundColor: AppColors.parchmentSoft,
              shape: const CircleBorder(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _priceBlock() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x5),
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Row(
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text("PROPOSED PAYMENT",
                  style: AppType.eyebrow().copyWith(
                      color: AppColors.parchmentDeep, letterSpacing: 1.6)),
              const SizedBox(height: 6),
              Row(
                crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic,
                children: [
                  Text(_fmt(offer.proposedPrice),
                      style: AppType.display(34,
                          w: FontWeight.w400,
                          color: AppColors.parchment,
                          height: 1)),
                  const SizedBox(width: 6),
                  Text("DZD",
                      style: AppType.mono(13,
                          color: AppColors.parchmentDeep,
                          w: FontWeight.w600)),
                ],
              ),
              const SizedBox(height: 4),
              Text("Held in escrow until delivery",
                  style: AppType.body(11.5,
                      color: AppColors.parchmentDeep, w: FontWeight.w500)),
            ],
          ),
          const Spacer(),
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: AppColors.sun,
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Icon(Icons.lock_outline_rounded,
                color: AppColors.ink, size: 26),
          ),
        ],
      ),
    );
  }

  Widget _senderCard() {
    final initials =
        offer.senderName.split(' ').map((s) => s[0]).take(2).join();
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: AppColors.emerald,
              borderRadius: BorderRadius.circular(14),
            ),
            alignment: Alignment.center,
            child: Text(initials,
                style: AppType.display(15,
                    color: AppColors.parchment, w: FontWeight.w500)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(offer.senderName,
                        style: AppType.body(15, w: FontWeight.w700)),
                    const SizedBox(width: 6),
                    const Icon(Icons.verified_rounded,
                        size: 14, color: AppColors.emerald),
                  ],
                ),
                const SizedBox(height: 2),
                Text("ID verified · 12 deliveries · ★ 4.9",
                    style: AppType.body(11.5,
                        color: AppColors.inkMute, w: FontWeight.w500)),
              ],
            ),
          ),
          IconButton(
            onPressed: () {},
            icon: const Icon(Icons.chat_bubble_outline_rounded, size: 18),
            style: IconButton.styleFrom(
              backgroundColor: AppColors.parchment,
              shape: const CircleBorder(),
              side: const BorderSide(color: AppColors.hairline),
            ),
          ),
        ],
      ),
    );
  }

  Widget _photoGallery() {
    final colors = [
      AppColors.terracotta,
      AppColors.gold,
      AppColors.emerald,
    ];
    return SizedBox(
      height: 110,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: 3,
        separatorBuilder: (_, __) => const SizedBox(width: 10),
        itemBuilder: (_, i) => Container(
          width: 110,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.md),
            gradient: LinearGradient(
              colors: [colors[i].withValues(alpha: 0.85), colors[i]],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Stack(
            children: [
              const Center(
                child: Icon(Icons.image_outlined,
                    color: Colors.white70, size: 32),
              ),
              Positioned(
                bottom: 8,
                left: 8,
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.ink.withValues(alpha: 0.6),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text("${i + 1}/3",
                      style: AppType.mono(9.5,
                          color: AppColors.parchment, w: FontWeight.w600)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _detailRows() {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        children: [
          _detailRow(Icons.scale_outlined, "Weight", "${offer.weightKg} kg"),
          _div(),
          _detailRow(Icons.place_outlined, "Pickup", offer.pickupCity),
          _div(),
          _detailRow(Icons.flag_outlined, "Drop-off", offer.deliveryCity),
          _div(),
          _detailRow(Icons.event_outlined, "Window", offer.when),
        ],
      ),
    );
  }

  Widget _detailRow(IconData icon, String l, String v) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          Icon(icon, size: 16, color: AppColors.inkMute),
          const SizedBox(width: 10),
          Text(l,
              style: AppType.body(12.5,
                  color: AppColors.inkMute, w: FontWeight.w500)),
          const Spacer(),
          Flexible(
            child: Text(v,
                textAlign: TextAlign.right,
                style: AppType.body(13, w: FontWeight.w600)),
          ),
        ],
      ),
    );
  }

  Widget _div() => Container(height: 1, color: AppColors.hairline);

  Widget _notes() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Text(
        "Please handle with care — fragile. I'll be available between 9 AM and 6 PM at the pickup point. Many thanks!",
        style: AppType.body(13, color: AppColors.inkSoft, height: 1.5),
      ),
    );
  }

  Widget _label(String t) =>
      Text(t.toUpperCase(), style: AppType.eyebrow());

  static String _fmt(int n) {
    final s = n.toString();
    return s.replaceAllMapped(
        RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => "${m[1]} ");
  }
}
