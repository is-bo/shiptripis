import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth_notifier.dart';
import '../../core/auth/auth_repository.dart';
import '../../core/constants/wilayas.dart';
import '../../core/kyc/kyc_providers.dart';
import '../../core/state/role_provider.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/stamp_chip.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authNotifierProvider);
    final role = ref.watch(effectiveRoleProvider);
    final canSwitch = ref.watch(canSwitchRoleProvider);

    final user = auth is AuthSignedIn ? auth.user : null;

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
          child: _PassportCard(user: user),
        ),
        if (canSwitch) ...[
          const SizedBox(height: AppSpacing.x5),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
            child: _RoleSwitcher(role: role, ref: ref)
                .animate()
                .fadeIn(delay: 100.ms, duration: 400.ms),
          ),
        ],
        const SizedBox(height: AppSpacing.x5),
        _SettingsList(user: user),
        const SizedBox(height: 110),
      ],
    );
  }
}

class _PassportCard extends StatelessWidget {
  const _PassportCard({required this.user});
  final AuthUser? user;

  @override
  Widget build(BuildContext context) {
    final wilayaName = _wilayaName(user?.wilaya);
    final memberSince = user?.dateJoined;
    final memberLabel = memberSince == null
        ? "PASSPORT · MEMBER"
        : "MEMBER SINCE ${_monthYear(memberSince)}".toUpperCase();

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
              StampChip(label: memberLabel, color: AppColors.gold),
              const Spacer(),
              if (user != null)
                Text("№ ST-${user!.id.toString().padLeft(4, '0')}",
                    style:
                        AppType.mono(11, color: AppColors.parchmentDeep)),
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
                child: Text(user?.initials ?? "—",
                    style: AppType.display(28,
                        color: AppColors.parchment, w: FontWeight.w500)),
              ),
              const SizedBox(width: AppSpacing.x4),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      user?.fullName.isNotEmpty == true
                          ? user!.fullName
                          : (user?.email ?? "Guest"),
                      style: AppType.display(20,
                          color: AppColors.parchment, w: FontWeight.w500),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(wilayaName ?? "Algeria",
                        style: AppType.body(13,
                            color: AppColors.parchmentDeep)),
                    const SizedBox(height: AppSpacing.x3),
                    Row(
                      children: [
                        Icon(
                          user?.isKycVerified == true
                              ? Icons.verified_rounded
                              : Icons.shield_outlined,
                          size: 14,
                          color: user?.isKycVerified == true
                              ? AppColors.gold
                              : AppColors.parchmentDeep,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          user?.isKycVerified == true
                              ? "KYC verified"
                              : "KYC not verified",
                          style: AppType.body(12.5,
                              color: AppColors.parchment,
                              w: FontWeight.w600),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static String? _wilayaName(String? code) {
    if (code == null || code.isEmpty) return null;
    for (final w in kWilayas) {
      if (w.code == code) return "${w.name} · DZ";
    }
    return null;
  }

  static String _monthYear(DateTime d) {
    const months = [
      'jan',
      'feb',
      'mar',
      'apr',
      'may',
      'jun',
      'jul',
      'aug',
      'sep',
      'oct',
      'nov',
      'dec'
    ];
    return "${months[d.month - 1]} ${d.year}";
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
                _seg(
                    role == AppRole.sender,
                    "Sender",
                    Icons.inventory_2_outlined,
                    () => ref.read(roleProvider.notifier).set(AppRole.sender)),
                _seg(
                    role == AppRole.traveler,
                    "Traveler",
                    Icons.flight_takeoff_rounded,
                    () =>
                        ref.read(roleProvider.notifier).set(AppRole.traveler)),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Text(
            "Switch anytime — your account, KYC, and history don't change.",
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
                  size: 15,
                  color: selected ? AppColors.parchment : AppColors.ink),
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

class _SettingsList extends ConsumerWidget {
  const _SettingsList({required this.user});
  final AuthUser? user;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // `is_kyc_verified` only flips on approval, and the kyc-service exposes no
    // status-read endpoint — so we can't distinguish "never submitted" from
    // "pending review" across restarts. Don't claim either: show the approved
    // state when we have it, the in-review state when this session submitted,
    // and otherwise an invitation to act.
    final submittedThisSession =
        ref.watch(kycDraftProvider.select((d) => d.result != null));
    final kycLabel = user?.isKycVerified == true
        ? "Approved"
        : submittedThisSession
            ? "In review"
            : "Verify now";

    final rows = <_Row>[
      _Row(
        label: "Wallet",
        icon: Icons.account_balance_wallet_outlined,
        trailing: "Coming soon",
        enabled: false,
      ),
      _Row(
        label: "Payment methods",
        icon: Icons.credit_card_outlined,
        trailing: "Coming soon",
        enabled: false,
      ),
      _Row(
        label: "Identity verification",
        icon: Icons.fingerprint_rounded,
        trailing: kycLabel,
        onTap: () => context.push('/kyc'),
      ),
      _Row(
        label: "Help center",
        icon: Icons.help_outline_rounded,
        trailing: "",
        onTap: () => _showHelp(context),
      ),
      _Row(
        label: "Sign out",
        icon: Icons.logout_rounded,
        trailing: "",
        isDanger: true,
        onTap: () => _confirmSignOut(context, ref),
      ),
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
            for (int i = 0; i < rows.length; i++) ...[
              _rowWidget(context, rows[i]),
              if (i < rows.length - 1)
                Divider(height: 1, color: AppColors.hairline),
            ],
          ],
        ),
      ),
    );
  }

  Widget _rowWidget(BuildContext context, _Row r) {
    final color = !r.enabled
        ? AppColors.inkMute
        : (r.isDanger ? AppColors.danger : AppColors.ink);
    final content = Padding(
      padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.x4, vertical: 14),
      child: Row(
        children: [
          Icon(r.icon, size: 18, color: color),
          const SizedBox(width: 12),
          Text(r.label,
              style: AppType.body(14, w: FontWeight.w600, color: color)),
          const Spacer(),
          if (r.trailing.isNotEmpty)
            Text(r.trailing,
                style: AppType.mono(12,
                    color: AppColors.inkMute, w: FontWeight.w500)),
          const SizedBox(width: 6),
          if (r.enabled)
            Icon(Icons.chevron_right_rounded,
                color: AppColors.inkMute, size: 18),
        ],
      ),
    );
    if (!r.enabled || r.onTap == null) return content;
    return InkWell(
      onTap: r.onTap,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: content,
    );
  }

  void _showHelp(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppColors.parchment,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => const _HelpSheet(),
    );
  }

  Future<void> _confirmSignOut(BuildContext context, WidgetRef ref) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.parchment,
        title: Text("Sign out?", style: AppType.display(20)),
        content: Text(
          "You'll need to sign in again to see your requests, trips, and messages.",
          style: AppType.body(14, color: AppColors.inkSoft),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text("Sign out",
                style: TextStyle(color: AppColors.danger)),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await ref.read(authNotifierProvider.notifier).signOut();
    // Router redirect fires off the auth state change; nothing else needed.
  }
}

class _Row {
  _Row({
    required this.label,
    required this.icon,
    required this.trailing,
    this.enabled = true,
    this.isDanger = false,
    this.onTap,
  });
  final String label;
  final IconData icon;
  final String trailing;
  final bool enabled;
  final bool isDanger;
  final VoidCallback? onTap;
}

class _HelpSheet extends StatelessWidget {
  const _HelpSheet();
  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.hairline,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text("Need a hand?", style: AppType.display(22)),
            const SizedBox(height: 6),
            Text(
              "We're a small team. Reach us and we'll get back within 24h.",
              style: AppType.body(13.5, color: AppColors.inkSoft),
            ),
            const SizedBox(height: 18),
            _HelpRow(
              icon: Icons.mail_outline_rounded,
              label: "Email",
              value: "support@shiptrip.dz",
            ),
            const SizedBox(height: 10),
            _HelpRow(
              icon: Icons.phone_outlined,
              label: "Phone",
              value: "+213 770 000 000",
            ),
            const SizedBox(height: 18),
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
                onPressed: () => Navigator.of(context).pop(),
                child: const Text("Got it"),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _HelpRow extends StatelessWidget {
  const _HelpRow({required this.icon, required this.label, required this.value});
  final IconData icon;
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          Icon(icon, size: 18, color: AppColors.ink),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: AppType.eyebrow()),
                const SizedBox(height: 2),
                Text(value,
                    style: AppType.body(13.5, w: FontWeight.w600)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
