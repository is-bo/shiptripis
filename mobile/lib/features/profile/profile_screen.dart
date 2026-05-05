import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/state/role_provider.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/stamp_chip.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final role = ref.watch(roleProvider);
    return ListView(
      padding: EdgeInsets.zero,
      children: [
        SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.x6, AppSpacing.x6, AppSpacing.x6, AppSpacing.x4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("Profile", style: AppType.eyebrow()),
                Text("Your passport.",
                    style: AppType.display(34, w: FontWeight.w400, height: 1)),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
          child: _PassportCard(),
        ),
        const SizedBox(height: AppSpacing.x5),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
          child: _RoleSwitcher(role: role, ref: ref)
              .animate()
              .fadeIn(delay: 100.ms, duration: 400.ms),
        ),
        const SizedBox(height: AppSpacing.x5),
        const _SettingsList(),
        const SizedBox(height: 110),
      ],
    );
  }
}

class _PassportCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x5),
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(AppRadius.xl),
        boxShadow: AppShadows.elevated,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StampChip(label: "PASSPORT · MEMBER", color: AppColors.gold),
              const Spacer(),
              Text("№ ST-1042",
                  style: AppType.mono(11, color: AppColors.parchmentDeep)),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 76,
                height: 92,
                decoration: BoxDecoration(
                  color: AppColors.parchmentSoft.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                alignment: Alignment.center,
                child: Text("IM",
                    style: AppType.display(28,
                        color: AppColors.parchment, w: FontWeight.w500)),
              ),
              const SizedBox(width: AppSpacing.x4),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("Islam Merabet",
                        style: AppType.display(20,
                            color: AppColors.parchment, w: FontWeight.w500)),
                    const SizedBox(height: 2),
                    Text("Algiers · DZ",
                        style: AppType.body(13, color: AppColors.parchmentDeep)),
                    const SizedBox(height: AppSpacing.x3),
                    Row(
                      children: [
                        const Icon(Icons.verified_rounded,
                            size: 14, color: AppColors.gold),
                        const SizedBox(width: 4),
                        Text("KYC verified · 4.9 ★",
                            style: AppType.body(12.5,
                                color: AppColors.parchment, w: FontWeight.w600)),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          Container(height: 1, color: AppColors.parchment.withValues(alpha: 0.15)),
          const SizedBox(height: AppSpacing.x4),
          Row(
            children: [
              _PassStat("Trips", "23"),
              _PassStat("Senders helped", "18"),
              _PassStat("Wallet", "12 400", unit: "DZD"),
            ],
          ),
        ],
      ),
    );
  }
}

class _PassStat extends StatelessWidget {
  const _PassStat(this.label, this.value, {this.unit = ""});
  final String label;
  final String value;
  final String unit;
  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(),
              style: AppType.eyebrow(color: AppColors.parchmentDeep)
                  .copyWith(letterSpacing: 1.4)),
          const SizedBox(height: 4),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Flexible(
                child: Text(value,
                    style: AppType.display(20,
                        color: AppColors.parchment, w: FontWeight.w500),
                    overflow: TextOverflow.ellipsis),
              ),
              if (unit.isNotEmpty) ...[
                const SizedBox(width: 3),
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(unit,
                      style: AppType.mono(9.5,
                          color: AppColors.parchmentDeep, w: FontWeight.w600)),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

class _RoleSwitcher extends StatelessWidget {
  const _RoleSwitcher({required this.role, required this.ref});
  final AppRole role;
  final WidgetRef ref;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text("ACTIVE MODE", style: AppType.eyebrow()),
              const Spacer(),
              Text(role == AppRole.sender ? "Sender" : "Traveler",
                  style: AppType.body(13, w: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
              color: AppColors.parchment,
              borderRadius: BorderRadius.circular(AppRadius.pill),
              border: Border.all(color: AppColors.hairline),
            ),
            child: Row(
              children: [
                _seg(role == AppRole.sender, "Sender", Icons.inventory_2_outlined,
                    () => ref.read(roleProvider.notifier).set(AppRole.sender)),
                _seg(role == AppRole.traveler, "Traveler", Icons.flight_takeoff_rounded,
                    () => ref.read(roleProvider.notifier).set(AppRole.traveler)),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Text(
            "You can switch anytime — your stats, KYC, and wallet stay the same.",
            style: AppType.body(11.5, color: AppColors.inkMute),
          ),
        ],
      ),
    );
  }

  Widget _seg(bool selected, String label, IconData icon, VoidCallback onTap) {
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: AppDurations.fast,
          padding: const EdgeInsets.symmetric(vertical: 11),
          decoration: BoxDecoration(
            color: selected ? AppColors.ink : Colors.transparent,
            borderRadius: BorderRadius.circular(AppRadius.pill),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon,
                  size: 15, color: selected ? AppColors.parchment : AppColors.ink),
              const SizedBox(width: 8),
              Text(label,
                  style: AppType.body(12.5,
                      w: FontWeight.w600,
                      color: selected ? AppColors.parchment : AppColors.ink)),
            ],
          ),
        ),
      ),
    );
  }
}

class _SettingsList extends StatelessWidget {
  const _SettingsList();

  @override
  Widget build(BuildContext context) {
    final items = [
      ("Wallet", Icons.account_balance_wallet_outlined, "12 400 DZD"),
      ("Payment methods", Icons.credit_card_outlined, "Visa · 1234"),
      ("KYC documents", Icons.fingerprint_rounded, "Approved"),
      ("Language", Icons.translate_rounded, "English"),
      ("Notifications", Icons.notifications_outlined, "On"),
      ("Help center", Icons.help_outline_rounded, ""),
      ("Sign out", Icons.logout_rounded, ""),
    ];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppColors.hairline),
        ),
        child: Column(
          children: [
            for (int i = 0; i < items.length; i++) ...[
              _row(items[i].$1, items[i].$2, items[i].$3,
                  isDanger: items[i].$1 == "Sign out"),
              if (i < items.length - 1)
                Divider(height: 1, color: AppColors.hairline),
            ],
          ],
        ),
      ),
    );
  }

  Widget _row(String label, IconData icon, String trailing, {bool isDanger = false}) {
    final color = isDanger ? AppColors.danger : AppColors.ink;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x4, vertical: 14),
      child: Row(
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 12),
          Text(label,
              style: AppType.body(14, w: FontWeight.w600, color: color)),
          const Spacer(),
          if (trailing.isNotEmpty)
            Text(trailing,
                style: AppType.mono(12, color: AppColors.inkMute, w: FontWeight.w500)),
          const SizedBox(width: 6),
          Icon(Icons.chevron_right_rounded, color: AppColors.inkMute, size: 18),
        ],
      ),
    );
  }
}
