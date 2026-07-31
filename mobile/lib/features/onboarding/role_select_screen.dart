import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/state/role_provider.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/util/safe_back.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class RoleSelectScreen extends ConsumerStatefulWidget {
  const RoleSelectScreen({super.key});
  @override
  ConsumerState<RoleSelectScreen> createState() => _RoleSelectScreenState();
}

class _RoleSelectScreenState extends ConsumerState<RoleSelectScreen> {
  AppRole? _picked;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.x6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              IconButton(
                // Reached via `context.go('/role')` from sign-in/sign-up, so
                // the stack is empty here and a bare pop() would exit the app.
                onPressed: () => safeBack(context),
                icon: const Icon(Icons.arrow_back_rounded),
                style: IconButton.styleFrom(
                  backgroundColor: AppColors.parchmentSoft,
                  shape: const CircleBorder(),
                ),
              ),
              const SizedBox(height: AppSpacing.x6),
              Text("Step 01 / 03", style: AppType.eyebrow()),
              const SizedBox(height: AppSpacing.x3),
              Text("How do you\nwant to ship?",
                      style: AppType.display(38, w: FontWeight.w400, height: 1.05))
                  .animate()
                  .fadeIn(duration: 500.ms)
                  .moveY(begin: 8, end: 0),
              const SizedBox(height: AppSpacing.x3),
              Text(
                "Pick a role to start. You can switch from your profile anytime — most members do both.",
                style: AppType.body(14, color: AppColors.inkSoft, height: 1.5),
              ).animate().fadeIn(delay: 150.ms, duration: 500.ms),
              const SizedBox(height: AppSpacing.x6),
              _RoleCard(
                role: AppRole.sender,
                title: "Send",
                subtitle: "Post a parcel or product. Pay only when delivered.",
                emoji: "📦",
                accent: AppColors.terracotta,
                selected: _picked == AppRole.sender,
                onTap: () => setState(() => _picked = AppRole.sender),
              ).animate().fadeIn(delay: 200.ms).slideX(begin: -0.05, end: 0),
              const SizedBox(height: AppSpacing.x4),
              _RoleCard(
                role: AppRole.traveler,
                title: "Travel",
                subtitle: "List a trip. Earn from the empty space in your luggage.",
                emoji: "✈️",
                accent: AppColors.emerald,
                selected: _picked == AppRole.traveler,
                onTap: () => setState(() => _picked = AppRole.traveler),
              ).animate().fadeIn(delay: 320.ms).slideX(begin: 0.05, end: 0),
              const Spacer(),
              Center(
                child: AnimatedOpacity(
                  duration: AppDurations.med,
                  opacity: _picked == null ? 0.4 : 1,
                  child: PrimaryButton(
                    label: "Continue",
                    icon: Icons.arrow_forward_rounded,
                    onTap: _picked == null
                        ? null
                        : () {
                            ref.read(roleProvider.notifier).set(_picked!);
                            context.go('/app');
                          },
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RoleCard extends StatelessWidget {
  const _RoleCard({
    required this.role,
    required this.title,
    required this.subtitle,
    required this.emoji,
    required this.accent,
    required this.selected,
    required this.onTap,
  });

  final AppRole role;
  final String title;
  final String subtitle;
  final String emoji;
  final Color accent;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: AppDurations.med,
        curve: kAppCurve,
        padding: const EdgeInsets.all(AppSpacing.x5),
        decoration: BoxDecoration(
          color: selected ? AppColors.ink : AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(
            color: selected ? AppColors.ink : AppColors.hairline,
            width: 1.2,
          ),
          boxShadow: selected ? AppShadows.elevated : AppShadows.card,
        ),
        child: Row(
          children: [
            AnimatedContainer(
              duration: AppDurations.med,
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: accent.withValues(alpha: selected ? 1 : 0.12),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              alignment: Alignment.center,
              child: Text(emoji, style: const TextStyle(fontSize: 30)),
            ),
            const SizedBox(width: AppSpacing.x4),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        title,
                        style: AppType.display(26,
                            w: FontWeight.w500,
                            color: selected ? AppColors.parchment : AppColors.ink),
                      ),
                      const SizedBox(width: 8),
                      if (selected)
                        StampChip(
                          label: "Selected",
                          color: accent,
                          angle: -0.06,
                        ).animate().scale(duration: 250.ms, curve: kAppCurve),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subtitle,
                    style: AppType.body(13.5,
                        color: selected ? AppColors.parchmentDeep : AppColors.inkSoft,
                        height: 1.4),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
