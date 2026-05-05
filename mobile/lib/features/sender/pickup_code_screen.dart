import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class PickupCodeScreen extends StatefulWidget {
  const PickupCodeScreen({
    super.key,
    required this.offerId,
    this.travelerName = "Yacine M.",
  });
  final String offerId;
  final String travelerName;

  @override
  State<PickupCodeScreen> createState() => _PickupCodeScreenState();
}

class _PickupCodeScreenState extends State<PickupCodeScreen> {
  late final String _code;

  @override
  void initState() {
    super.initState();
    final r = Random(widget.offerId.hashCode);
    _code = (1000 + r.nextInt(8999)).toString();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Column(
          children: [
            _topBar(),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
                children: [
                  Text("Pickup code", style: AppType.eyebrow()),
                  const SizedBox(height: 6),
                  Text("Hand it to\n${widget.travelerName}.",
                      style: AppType.display(32,
                          w: FontWeight.w400, height: 1.05)),
                  const SizedBox(height: AppSpacing.x6),
                  _codeCard()
                      .animate()
                      .fadeIn(duration: 380.ms)
                      .scale(begin: const Offset(0.95, 0.95)),
                  const SizedBox(height: AppSpacing.x5),
                  _instructions(),
                  const SizedBox(height: AppSpacing.x5),
                  _shareRow(),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
              child: PrimaryButton(
                label: "I've shared it",
                icon: Icons.check_rounded,
                expand: true,
                color: AppColors.sun,
                fg: AppColors.ink,
                onTap: () => context.go('/app'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _topBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x4, AppSpacing.x4, AppSpacing.x4, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => context.go('/app'),
            icon: const Icon(Icons.close_rounded),
            style: IconButton.styleFrom(
              backgroundColor: AppColors.parchmentSoft,
              shape: const CircleBorder(),
            ),
          ),
          const Spacer(),
          StampChip(label: "PAID · IN ESCROW", color: AppColors.emerald),
        ],
      ),
    );
  }

  Widget _codeCard() {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 24),
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(AppRadius.xl),
        boxShadow: AppShadows.elevated,
      ),
      child: Column(
        children: [
          Text("SHOW THIS NUMBER",
              style: AppType.eyebrow().copyWith(
                  color: AppColors.sun, letterSpacing: 2.4)),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: _code
                .split('')
                .map((d) => Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: Container(
                        width: 56,
                        height: 76,
                        decoration: BoxDecoration(
                          color: AppColors.inkSoft,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(
                              color: AppColors.sun.withValues(alpha: 0.3)),
                        ),
                        alignment: Alignment.center,
                        child: Text(d,
                            style: AppType.display(38,
                                color: AppColors.parchment,
                                w: FontWeight.w400,
                                height: 1)),
                      ),
                    ))
                .toList(),
          ),
          const SizedBox(height: 16),
          Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.sun.withValues(alpha: 0.18),
              borderRadius: BorderRadius.circular(AppRadius.pill),
            ),
            child: Text("Valid until pickup",
                style: AppType.mono(11,
                    color: AppColors.sun, w: FontWeight.w600)),
          ),
        ],
      ),
    );
  }

  Widget _instructions() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        children: [
          _step(1, "Meet ${widget.travelerName} at the pickup point."),
          const SizedBox(height: 10),
          _step(2, "Read this 4-digit code aloud."),
          const SizedBox(height: 10),
          _step(3,
              "They enter it in the app — your package is now in transit."),
        ],
      ),
    );
  }

  Widget _step(int n, String text) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 22,
          height: 22,
          decoration: const BoxDecoration(
              color: AppColors.ink, shape: BoxShape.circle),
          alignment: Alignment.center,
          child: Text("$n",
              style: AppType.mono(11,
                  color: AppColors.sun, w: FontWeight.w700)),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text(text,
              style: AppType.body(13.5,
                  color: AppColors.inkSoft, height: 1.45)),
        ),
      ],
    );
  }

  Widget _shareRow() {
    return Row(
      children: [
        Expanded(
          child: _shareBtn(
            icon: Icons.copy_rounded,
            label: "Copy",
            onTap: () {
              Clipboard.setData(ClipboardData(text: _code));
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  backgroundColor: AppColors.ink,
                  content: Text("Code copied",
                      style: AppType.body(13,
                          color: AppColors.parchment,
                          w: FontWeight.w500)),
                ),
              );
            },
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _shareBtn(
            icon: Icons.share_rounded,
            label: "Share",
            onTap: () {},
          ),
        ),
      ],
    );
  }

  Widget _shareBtn(
      {required IconData icon,
      required String label,
      required VoidCallback onTap}) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14),
        decoration: BoxDecoration(
          color: AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: AppColors.hairline),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 18, color: AppColors.ink),
            const SizedBox(width: 8),
            Text(label,
                style: AppType.body(13.5, w: FontWeight.w600)),
          ],
        ),
      ),
    );
  }
}
