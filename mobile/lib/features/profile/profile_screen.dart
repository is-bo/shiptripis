/// Profile.
///
/// The account, and the settings that belong to it. Ordered by how often a
/// person actually comes here: verification first (because it gates carrying),
/// then money, then preferences, then the legal and support links, then the
/// way out.
///
/// Verification is not buried in a list row. For a traveller it is the
/// difference between a journey that can go live and one that cannot, so it
/// gets its own card with its real status and a way to act on it.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_settings.dart';
import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/identity.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/account.dart';
import '../../domain/rating.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../shell/app_shell.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final completedDeals = ref.watch(completedDealsCountProvider);
    final ratings = ref.watch(receivedRatingsProvider);

    if (account == null) {
      return const AppScaffold(
        body: Padding(
          padding: EdgeInsets.all(AppSpace.gutter),
          child: SkeletonDetail(),
        ),
      );
    }

    return AppScaffold(
      topBar: AppTopBar(
        title: l.profileTitle,
        actions: const [NotificationBell()],
      ),
      body: RefreshIndicator(
        onRefresh: () => ref.read(sessionProvider.notifier).refreshAccount(),
        child: ListView(
          padding: AppScrollPadding.page(context),
          children: [
            _PassportCard(
              account: account,
              completedDeals: completedDeals,
              ratings: ratings,
            ),
            const SizedBox(height: AppSpace.xl),

            _VerificationCard(account: account),
            const SizedBox(height: AppSpace.xl),

            SectionHeader(title: l.profilePayments),
            _Row(
              icon: Icons.payments_outlined,
              label: l.payoutTitle,
              onTap: () => context.pushNamed(Routes.profilePayouts),
            ),
            _Row(
              icon: Icons.account_balance_outlined,
              label: l.payoutMethodsTitle,
              onTap: () => context.pushNamed(Routes.profilePayoutMethods),
            ),
            _Row(
              icon: Icons.star_outline_rounded,
              label: l.profileRatings,
              onTap: () => context.pushNamed(Routes.profileRatings),
            ),
            const SizedBox(height: AppSpace.xl),

            SectionHeader(title: l.profileAccount),
            _Row(
              icon: Icons.notifications_active_outlined,
              label: l.profileNotificationSettings,
              onTap: () => context.pushNamed(Routes.profileNotifications),
            ),
            _Row(
              icon: Icons.translate_rounded,
              label: l.profileLanguage,
              value: _localeLabel(context, ref),
              onTap: () => context.pushNamed(Routes.profileLanguage),
            ),
            _Row(
              icon: Icons.contrast_rounded,
              label: l.profileAppearance,
              value: _themeLabel(context, ref.watch(themeModeProvider)),
              onTap: () => context.pushNamed(Routes.profileAppearance),
            ),
            const SizedBox(height: AppSpace.xl),

            SectionHeader(title: l.profileSupport),
            _Row(icon: Icons.description_outlined, label: l.profileTerms),
            _Row(icon: Icons.privacy_tip_outlined, label: l.profilePrivacy),
            _Row(
              icon: Icons.support_agent_rounded,
              label: l.actionContactSupport,
            ),
            const SizedBox(height: AppSpace.xxl),

            AppButton(
              label: l.authSignOut,
              variant: AppButtonVariant.destructive,
              icon: Icons.logout_rounded,
              onPressed: () => _signOut(context, ref),
            ),
            const SizedBox(height: AppSpace.lg),
            Center(
              child: Text(
                l.profileVersion(_appVersion),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: context.colors.textTertiary,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Pinned rather than read from the package at runtime: the value is
  /// baked at build time and reading it asynchronously would make the whole
  /// screen wait on a platform channel for a footnote.
  static const _appVersion = '1.0.0';

  String _localeLabel(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final chosen = ref.watch(localeProvider);
    if (chosen == null) return l.profileLanguageSystem;
    return switch (chosen.languageCode) {
      'fr' => 'Français',
      'ar' => 'العربية',
      _ => 'English',
    };
  }

  String _themeLabel(BuildContext context, ThemeMode mode) {
    final l = L.of(context);
    return switch (mode) {
      ThemeMode.light => l.profileAppearanceLight,
      ThemeMode.dark => l.profileAppearanceDark,
      ThemeMode.system => l.profileAppearanceSystem,
    };
  }

  Future<void> _signOut(BuildContext context, WidgetRef ref) async {
    final l = L.of(context);
    final confirmed = await confirmAction(
      context,
      title: l.authSignOutConfirmTitle,
      body: l.authSignOutConfirmBody,
      confirmLabel: l.authSignOut,
      isDestructive: true,
    );
    if (!confirmed || !context.mounted) return;
    await ref.read(sessionProvider.notifier).signOut();
  }
}

/// The useful account-passport concept from the original pre-Phase-5 client,
/// mapped onto current V1 authority.
///
/// The historical card's hard-coded member number, DZD wallet and demo trip
/// counts are deliberately gone. In their place are only facts supplied by
/// current endpoints: identity, capabilities, verification, received ratings,
/// completed Deals, join date and the stored communication language.
class _PassportCard extends StatelessWidget {
  const _PassportCard({
    required this.account,
    required this.completedDeals,
    required this.ratings,
  });

  final Account account;
  final AsyncValue<int> completedDeals;
  final AsyncValue<List<Rating>> ratings;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final joined = account.dateJoined;
    final displayName = account.fullName.trim().isEmpty
        ? account.email
        : account.fullName;
    final completed = completedDeals.value;
    final revealedRatings = ratings.value ?? const <Rating>[];
    final average = revealedRatings.isEmpty
        ? null
        : revealedRatings.fold<int>(0, (sum, rating) => sum + rating.score) /
              revealedRatings.length;

    return Semantics(
      container: true,
      label: '${l.profileAccount}, $displayName',
      child: ClipRRect(
        borderRadius: AppRadius.rLg,
        child: ColoredBox(
          color: c.surfaceInverse,
          child: Stack(
            children: [
              const Positioned.fill(child: PaperGrain(density: 0.7)),
              Padding(
                padding: const EdgeInsets.all(AppSpace.xl),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    StampChip(
                      label: l.profilePassportStamp,
                      color: c.accent,
                      angle: -0.025,
                    ),
                    const SizedBox(height: AppSpace.xl),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        AppAvatar(
                          initials: initialsFor(displayName),
                          name: displayName,
                          size: 64,
                          isVerified: account.isKycVerified,
                        ),
                        const SizedBox(width: AppSpace.lg),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                displayName,
                                style: text.titleLarge?.copyWith(
                                  color: c.textOnInverse,
                                ),
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                              ),
                              const SizedBox(height: AppSpace.xs),
                              Text(
                                account.email,
                                style: text.bodySmall?.copyWith(
                                  color: c.textOnInverse.withValues(
                                    alpha: 0.72,
                                  ),
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              const SizedBox(height: AppSpace.md),
                              Wrap(
                                spacing: AppSpace.sm,
                                runSpacing: AppSpace.sm,
                                children: [
                                  _PassportMarker(
                                    label: account.isKycVerified
                                        ? l.kycStatusApproved
                                        : _kycLabel(context, account.kycStatus),
                                    icon: account.isKycVerified
                                        ? Icons.verified_rounded
                                        : Icons.badge_outlined,
                                    highlighted: account.isKycVerified,
                                  ),
                                  _PassportMarker(
                                    label: account.isEmailVerified
                                        ? l.profileEmailVerified
                                        : l.profileEmailUnverified,
                                    icon: account.isEmailVerified
                                        ? Icons.mark_email_read_rounded
                                        : Icons.mark_email_unread_rounded,
                                    highlighted: account.isEmailVerified,
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpace.xl),
                    Divider(
                      height: 1,
                      color: c.textOnInverse.withValues(alpha: 0.16),
                    ),
                    const SizedBox(height: AppSpace.lg),
                    LayoutBuilder(
                      builder: (context, constraints) {
                        final width =
                            (constraints.maxWidth - AppSpace.lg * 2) / 3;
                        return Wrap(
                          spacing: AppSpace.lg,
                          runSpacing: AppSpace.lg,
                          children: [
                            _PassportFact(
                              width: width,
                              label: l.profileRoles,
                              value: _roleLabel(context, account.role),
                            ),
                            _PassportFact(
                              width: width,
                              label: l.profileCompletedDeliveries,
                              value: completed?.toString() ?? '—',
                            ),
                            _PassportFact(
                              width: width,
                              label: l.profileRecentRating,
                              value: !ratings.hasValue
                                  ? '—'
                                  : average == null
                                  ? l.discoveryNoRatingsYet
                                  : '${average.toStringAsFixed(1)} ★',
                            ),
                          ],
                        );
                      },
                    ),
                    const SizedBox(height: AppSpace.lg),
                    Text(
                      '${l.profileEmailLanguage}: '
                      '${account.preferredLanguage.nativeLabel}',
                      style: text.bodySmall?.copyWith(
                        color: c.textOnInverse.withValues(alpha: 0.78),
                      ),
                    ),
                    if (joined != null) ...[
                      const SizedBox(height: AppSpace.xs),
                      Text(
                        l.profileMemberSince(
                          LocaleFormats.fullDate(locale, joined),
                        ),
                        style: text.bodySmall?.copyWith(
                          color: c.textOnInverse.withValues(alpha: 0.62),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _kycLabel(BuildContext context, KycStatus status) {
    final l = L.of(context);
    return switch (status) {
      KycStatus.verified => l.kycStatusApproved,
      KycStatus.pending => l.kycStatusPending,
      KycStatus.rejected => l.kycStatusRejected,
      KycStatus.unverified || KycStatus.unknown => l.kycStatusNotStarted,
    };
  }

  String _roleLabel(BuildContext context, AccountRole role) {
    final l = L.of(context);
    return switch (role) {
      AccountRole.sender => l.roleSender,
      AccountRole.traveler => l.roleTraveler,
      // The most common case, and the one the product is actually about: one
      // account, both jobs.
      AccountRole.both => '${l.roleSender} · ${l.roleTraveler}',
      AccountRole.admin || AccountRole.unknown => l.profileAccount,
    };
  }
}

class _PassportMarker extends StatelessWidget {
  const _PassportMarker({
    required this.label,
    required this.icon,
    required this.highlighted,
  });

  final String label;
  final IconData icon;
  final bool highlighted;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          icon,
          size: 14,
          color: highlighted
              ? c.accent
              : c.textOnInverse.withValues(alpha: 0.65),
        ),
        const SizedBox(width: AppSpace.xs),
        Flexible(
          child: Text(
            label,
            style: Theme.of(
              context,
            ).textTheme.labelSmall?.copyWith(color: c.textOnInverse),
          ),
        ),
      ],
    );
  }
}

class _PassportFact extends StatelessWidget {
  const _PassportFact({
    required this.width,
    required this.label,
    required this.value,
  });

  final double width;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    return SizedBox(
      width: width,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label.toUpperCase(),
            style: text.labelSmall?.copyWith(
              color: c.textOnInverse.withValues(alpha: 0.58),
              letterSpacing: 0.7,
            ),
          ),
          const SizedBox(height: AppSpace.xs),
          Text(
            value,
            style: text.titleSmall?.copyWith(color: c.textOnInverse),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}

/// Verification gets a card, not a list row.
///
/// `is_kyc_verified` is the authoritative gate on carrying, and a traveller who
/// cannot see why their journey will not publish has no way to fix it.
class _VerificationCard extends StatelessWidget {
  const _VerificationCard({required this.account});

  final Account account;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    final (label, tone, icon, action) = switch (account.kycStatus) {
      KycStatus.verified => (
        l.kycStatusApproved,
        StatusTone.good,
        Icons.verified_rounded,
        null,
      ),
      KycStatus.pending => (
        l.kycStatusPending,
        StatusTone.waiting,
        Icons.hourglass_top_rounded,
        null,
      ),
      KycStatus.rejected => (
        l.kycStatusRejected,
        StatusTone.bad,
        Icons.error_outline_rounded,
        l.kycRetryAction,
      ),
      KycStatus.unverified || KycStatus.unknown => (
        l.kycStatusNotStarted,
        StatusTone.action,
        Icons.badge_outlined,
        l.kycStartAction,
      ),
    };

    return AppCard(
      accent: tone,
      onTap: action == null ? null : () => context.openKyc(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  l.profileVerification,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              StatusPill(label: label, tone: tone, icon: icon, compact: true),
            ],
          ),
          if (account.kycRejectionReason != null &&
              account.kycRejectionReason!.isNotEmpty) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              account.kycRejectionReason!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ],
          if (action != null) ...[
            const SizedBox(height: AppSpace.md),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: AppButton(
                label: action,
                variant: AppButtonVariant.secondary,
                expand: false,
                onPressed: () => context.openKyc(),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.icon, required this.label, this.value, this.onTap});

  final IconData icon;
  final String label;
  final String? value;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final enabled = onTap != null;

    return Semantics(
      button: enabled,
      enabled: enabled,
      label: value == null ? label : '$label, $value',
      onTap: onTap,
      child: ExcludeSemantics(
        child: InkWell(
          onTap: onTap,
          borderRadius: AppRadius.rSm,
          child: Container(
            constraints: const BoxConstraints(minHeight: AppSpace.minTapTarget),
            padding: const EdgeInsets.symmetric(vertical: AppSpace.sm),
            child: Row(
              children: [
                Icon(icon, size: 20, color: c.textTertiary),
                const SizedBox(width: AppSpace.lg),
                Expanded(child: Text(label, style: text.bodyLarge)),
                if (value != null) ...[
                  const SizedBox(width: AppSpace.sm),
                  Text(
                    value!,
                    style: text.bodyMedium?.copyWith(color: c.textSecondary),
                  ),
                ],
                const SizedBox(width: AppSpace.sm),
                Icon(
                  Icons.chevron_right_rounded,
                  size: 20,
                  color: enabled ? c.textTertiary : c.hairlineStrong,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
