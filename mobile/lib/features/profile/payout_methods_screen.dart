/// Payout methods management screen.
///
/// Gives travelers full visibility and control over their payout rails
/// (Stripe Connect for EUR, CCP/RIP for DZD) and their payout preference.
///
/// Adheres strictly to the H6A contract:
/// - Never calculates readiness or eligibility client-side.
/// - Dynamic actions driven entirely by server `available_actions`.
/// - Re-checks Stripe readiness on return from browser onboarding/dashboard.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payout.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';

class PayoutMethodsScreen extends ConsumerStatefulWidget {
  const PayoutMethodsScreen({super.key});

  @override
  ConsumerState<PayoutMethodsScreen> createState() =>
      _PayoutMethodsScreenState();
}

class _PayoutMethodsScreenState extends ConsumerState<PayoutMethodsScreen>
    with WidgetsBindingObserver {
  bool _launchedExternalFlow = false;
  bool _isActionBusy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _launchedExternalFlow) {
      _launchedExternalFlow = false;
      _handleRefreshStripe();
    }
  }

  Future<void> _handleRefreshStripe() async {
    try {
      await ref.read(paymentRepositoryProvider).refreshStripeReadiness();
    } on Object {
      // Ignored: silent background refresh on return
    } finally {
      if (mounted) {
        ref.invalidate(payoutMethodsProvider);
      }
    }
  }

  Future<String?> _legalCountry(PayoutMethodsSummary summary) async {
    final existing = summary.eur?.country;
    if (existing != null && existing.isNotEmpty) return existing;
    final l = L.of(context);
    return showDialog<String>(
      context: context,
      builder: (ctx) => SimpleDialog(
        title: Text(l.payoutLegalCountryTitle),
        children: [
          Padding(
            padding: const EdgeInsets.all(AppSpace.md),
            child: Text(l.payoutLegalCountryBody),
          ),
          for (final country in summary.eur?.supportedCountries ?? <String>[])
            SimpleDialogOption(
              onPressed: () => Navigator.of(ctx).pop(country),
              child: Text(country == 'FR' ? l.countryNameFrance : country),
            ),
          SimpleDialogOption(
            onPressed: () => Navigator.of(ctx).pop(),
            child: Text(l.actionCancel),
          ),
        ],
      ),
    );
  }

  Future<void> _updatePreference(PayoutPreference newPref) async {
    if (_isActionBusy) return;
    setState(() => _isActionBusy = true);
    final l = L.of(context);
    try {
      final summary = await ref.read(paymentRepositoryProvider).payoutMethods();
      if (!mounted) return;
      final country = newPref == PayoutPreference.dzdOnly
          ? null
          : await _legalCountry(summary);
      if (newPref != PayoutPreference.dzdOnly && country == null) return;
      final eurRev = summary.revisionFor('EUR');
      final dzdRev = summary.revisionFor('DZD');
      await ref
          .read(paymentRepositoryProvider)
          .updatePayoutPreference(
            preference: newPref,
            eurRevision: eurRev,
            dzdRevision: dzdRev,
            country: country,
          );
      if (!mounted) return;
      ref.invalidate(payoutMethodsProvider);
      AppSnack.success(context, l.actionDone);
    } on Object catch (e) {
      if (!mounted) return;
      AppSnack.failure(context, e);
    } finally {
      if (mounted) setState(() => _isActionBusy = false);
    }
  }

  Future<void> _handleEurAction(String action) async {
    if (_isActionBusy) return;
    setState(() => _isActionBusy = true);
    final l = L.of(context);
    try {
      final repo = ref.read(paymentRepositoryProvider);
      if (action == 'configure_eur' ||
          action == 'setup_eur' ||
          action == 'resume_eur_setup') {
        final summary = await repo.payoutMethods();
        if (!mounted) return;
        final country = await _legalCountry(summary);
        if (country == null) return;
        if (summary.preference != PayoutPreference.eurOnly &&
            summary.preference != PayoutPreference.both) {
          await repo.updatePayoutPreference(
            preference: summary.preference == PayoutPreference.dzdOnly
                ? PayoutPreference.both
                : PayoutPreference.eurOnly,
            eurRevision: summary.revisionFor('EUR'),
            dzdRevision: summary.revisionFor('DZD'),
            country: country,
          );
        }
        final result = await repo.startStripeOnboarding(country: country);
        final url = result.onboardingUrl;
        if (url.isNotEmpty) {
          final uri = Uri.parse(url);
          _launchedExternalFlow = true;
          final opened = await launchUrl(
            uri,
            mode: LaunchMode.externalApplication,
          );
          if (!opened && mounted) {
            _launchedExternalFlow = false;
            AppSnack.failure(context, l.payoutOpenStripeError);
          }
        }
      } else if (action == 'manage_eur') {
        final url = await repo.openStripeDashboard();
        if (url.isNotEmpty) {
          final uri = Uri.parse(url);
          _launchedExternalFlow = true;
          final opened = await launchUrl(
            uri,
            mode: LaunchMode.externalApplication,
          );
          if (!opened && mounted) {
            _launchedExternalFlow = false;
            AppSnack.failure(context, l.payoutOpenStripeError);
          }
        }
      } else if (action == 'refresh') {
        await repo.refreshStripeReadiness();
        if (!mounted) return;
        ref.invalidate(payoutMethodsProvider);
        AppSnack.info(context, l.actionRefresh);
      }
    } on Object catch (e) {
      if (!mounted) return;
      AppSnack.failure(context, e);
    } finally {
      if (mounted) setState(() => _isActionBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final summaryAsync = ref.watch(payoutMethodsProvider);

    return AppScaffold(
      topBar: AppTopBar(title: l.payoutMethodsTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(payoutMethodsProvider),
        child: AsyncView<PayoutMethodsSummary>(
          value: summaryAsync,
          onRetry: () => ref.invalidate(payoutMethodsProvider),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (summary) {
            return ListView(
              padding: AppScrollPadding.page(context),
              children: [
                _PreferenceCard(
                  current: summary.preference,
                  isBusy: _isActionBusy,
                  onSelect: _updatePreference,
                ),
                const SizedBox(height: AppSpace.xl),

                if (summary.eur != null) ...[
                  _EurCard(
                    eur: summary.eur!,
                    isBusy: _isActionBusy,
                    onAction: _handleEurAction,
                  ),
                  const SizedBox(height: AppSpace.xl),
                ],

                if (summary.dzd != null) ...[
                  _DzdCard(dzd: summary.dzd!, isBusy: _isActionBusy),
                  const SizedBox(height: AppSpace.xxl),
                ],

                AppButton(
                  label: l.payoutViewHistoryAction,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.history_rounded,
                  onPressed: () => context.pushNamed(Routes.profilePayouts),
                ),
                const SizedBox(height: AppSpace.lg),
              ],
            );
          },
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Preference Card
// ---------------------------------------------------------------------------

class _PreferenceCard extends StatelessWidget {
  const _PreferenceCard({
    required this.current,
    required this.isBusy,
    required this.onSelect,
  });

  final PayoutPreference? current;
  final bool isBusy;
  final ValueChanged<PayoutPreference> onSelect;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.tune_rounded, size: 20, color: c.brand),
              const SizedBox(width: AppSpace.sm),
              Expanded(
                child: Text(
                  l.payoutPreferenceTitle,
                  style: text.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpace.xs),
          Text(
            l.payoutPreferenceScopeNote,
            style: text.bodySmall?.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: AppSpace.md),

          _PreferenceRadioOption(
            title: l.payoutPreferenceEurOnly,
            value: PayoutPreference.eurOnly,
            groupValue: current,
            enabled: !isBusy,
            onChanged: onSelect,
          ),
          Divider(height: 1, color: c.hairline),
          _PreferenceRadioOption(
            title: l.payoutPreferenceDzdOnly,
            value: PayoutPreference.dzdOnly,
            groupValue: current,
            enabled: !isBusy,
            onChanged: onSelect,
          ),
          Divider(height: 1, color: c.hairline),
          _PreferenceRadioOption(
            title: l.payoutPreferenceBoth,
            subtitle: l.payoutPreferenceBothExplainer,
            value: PayoutPreference.both,
            groupValue: current,
            enabled: !isBusy,
            onChanged: onSelect,
          ),
        ],
      ),
    );
  }
}

class _PreferenceRadioOption extends StatelessWidget {
  const _PreferenceRadioOption({
    required this.title,
    this.subtitle,
    required this.value,
    required this.groupValue,
    required this.enabled,
    required this.onChanged,
  });

  final String title;
  final String? subtitle;
  final PayoutPreference value;
  final PayoutPreference? groupValue;
  final bool enabled;
  final ValueChanged<PayoutPreference> onChanged;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final c = context.colors;
    final isSelected = value == groupValue;

    return InkWell(
      onTap: enabled ? () => onChanged(value) : null,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpace.sm),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              isSelected
                  ? Icons.radio_button_checked_rounded
                  : Icons.radio_button_unchecked_rounded,
              size: 20,
              color: isSelected ? c.brand : c.textTertiary,
            ),
            const SizedBox(width: AppSpace.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: text.bodyMedium?.copyWith(
                      fontWeight: isSelected
                          ? FontWeight.w600
                          : FontWeight.w400,
                    ),
                  ),
                  if (subtitle != null) ...[
                    const SizedBox(height: AppSpace.xs),
                    Text(
                      subtitle!,
                      style: text.bodySmall?.copyWith(color: c.textSecondary),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// EUR Card (Stripe Connect)
// ---------------------------------------------------------------------------

class _EurCard extends StatelessWidget {
  const _EurCard({
    required this.eur,
    required this.isBusy,
    required this.onAction,
  });

  final EurPayoutMethod eur;
  final bool isBusy;
  final ValueChanged<String> onAction;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;
    final stateCopy = eurMethodStateCopy(context, eur.state);

    final explainer = switch (eur.state) {
      EurPayoutState.notConfigured => l.payoutEurNotConfiguredBody,
      EurPayoutState.setupRequired => l.payoutEurSetupRequiredBody,
      EurPayoutState.pendingVerification => l.payoutEurPendingVerificationBody,
      EurPayoutState.ready => l.payoutEurReadyBody,
      EurPayoutState.needsAttention => l.payoutEurNeedsAttentionBody,
      EurPayoutState.unknown => l.stateUnexpectedTitle,
    };

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.euro_rounded, size: 22, color: c.brand),
              const SizedBox(width: AppSpace.sm),
              Expanded(
                child: Text(
                  l.payoutEurTitle,
                  style: text.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              StatusPill(
                label: stateCopy.label,
                tone: stateCopy.tone,
                icon: stateCopy.icon,
                compact: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.xs),
          Text(
            explainer,
            style: text.bodySmall?.copyWith(color: c.textSecondary),
          ),

          if (eur.country != null && eur.country!.isNotEmpty) ...[
            const SizedBox(height: AppSpace.md),
            DetailRow(
              // This row names the account's legal country, not a role. It was
              // labelled "Switch role" on the live page.
              label: l.payoutLegalCountryTitle,
              value: Text(
                eur.country!.toUpperCase(),
                style: text.bodySmall?.copyWith(color: c.textTertiary),
              ),
            ),
          ],

          if (eur.availableActions.isNotEmpty) ...[
            const SizedBox(height: AppSpace.lg),
            for (final action in eur.availableActions) ...[
              _buildEurActionButton(context, action),
              const SizedBox(height: AppSpace.sm),
            ],
          ],
        ],
      ),
    );
  }

  Widget _buildEurActionButton(BuildContext context, String action) {
    final l = L.of(context);
    final (label, icon, variant) = switch (action) {
      'configure_eur' || 'setup_eur' => (
        l.payoutActionSetupEur,
        Icons.add_link_rounded,
        AppButtonVariant.primary,
      ),
      'resume_eur_setup' => (
        l.payoutActionResumeEur,
        Icons.play_arrow_rounded,
        AppButtonVariant.primary,
      ),
      'manage_eur' => (
        l.payoutActionManageEur,
        Icons.open_in_new_rounded,
        AppButtonVariant.secondary,
      ),
      'refresh' => (
        l.payoutActionRefresh,
        Icons.refresh_rounded,
        AppButtonVariant.tertiary,
      ),
      _ => (action, Icons.touch_app_rounded, AppButtonVariant.secondary),
    };

    return AppButton(
      label: label,
      variant: variant,
      icon: icon,
      isLoading: isBusy,
      onPressed: isBusy ? null : () => onAction(action),
    );
  }
}

// ---------------------------------------------------------------------------
// DZD Card (CCP / RIP)
// ---------------------------------------------------------------------------

class _DzdCard extends StatelessWidget {
  const _DzdCard({required this.dzd, required this.isBusy});

  final DzdPayoutMethod dzd;
  final bool isBusy;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;
    final locale = Localizations.localeOf(context);
    final stateCopy = dzdMethodStateCopy(context, dzd.state);
    final profile = dzd.profile;

    final explainer = switch (dzd.state) {
      DzdPayoutState.notConfigured => l.payoutDzdNotConfiguredBody,
      DzdPayoutState.setupRequired => l.payoutDzdSetupRequiredBody,
      DzdPayoutState.pendingReview => l.payoutDzdPendingReviewBody,
      DzdPayoutState.ready => l.payoutDzdReadyBody,
      DzdPayoutState.needsAttention => l.payoutDzdNeedsAttentionBody,
      DzdPayoutState.inactive => l.payoutDzdInactiveBody,
      DzdPayoutState.unknown => l.stateUnexpectedTitle,
    };

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.account_balance_rounded, size: 22, color: c.brand),
              const SizedBox(width: AppSpace.sm),
              Expanded(
                child: Text(
                  l.payoutDzdTitle,
                  style: text.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              StatusPill(
                label: stateCopy.label,
                tone: stateCopy.tone,
                icon: stateCopy.icon,
                compact: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.xs),
          Text(
            explainer,
            style: text.bodySmall?.copyWith(color: c.textSecondary),
          ),

          if (profile != null) ...[
            if (profile.ccpLastFour != null &&
                profile.ccpLastFour!.isNotEmpty) ...[
              const SizedBox(height: AppSpace.md),
              DetailRow(
                label: l.payoutDzdCcpLabel,
                value: Text(
                  '•••• ${profile.ccpLastFour}',
                  style: text.bodyMedium,
                ),
              ),
            ],
            if (profile.ripLastFour != null &&
                profile.ripLastFour!.isNotEmpty) ...[
              const SizedBox(height: AppSpace.xs),
              DetailRow(
                label: l.payoutDzdRipLabel,
                value: Text(
                  '•••• ${profile.ripLastFour}',
                  style: text.bodyMedium,
                ),
              ),
            ],
            if (profile.submittedAt != null) ...[
              const SizedBox(height: AppSpace.xs),
              DetailRow(
                label: l.timelineDone,
                value: Text(
                  LocaleFormats.fullDate(locale, profile.submittedAt!),
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                ),
              ),
            ],
          ],

          if (dzd.availableActions.isNotEmpty) ...[
            const SizedBox(height: AppSpace.lg),
            for (final action in dzd.availableActions) ...[
              _buildDzdActionButton(context, action),
              const SizedBox(height: AppSpace.sm),
            ],
          ],
        ],
      ),
    );
  }

  Widget _buildDzdActionButton(BuildContext context, String action) {
    final l = L.of(context);
    final (label, icon, variant) = switch (action) {
      'setup_dzd' || 'configure_dzd' => (
        l.payoutActionSetupDzd,
        Icons.add_card_rounded,
        AppButtonVariant.primary,
      ),
      'replace_dzd_profile' => (
        l.payoutActionReplaceDzd,
        Icons.edit_note_rounded,
        AppButtonVariant.secondary,
      ),
      _ => (action, Icons.touch_app_rounded, AppButtonVariant.secondary),
    };

    return AppButton(
      label: label,
      variant: variant,
      icon: icon,
      isLoading: isBusy,
      onPressed: isBusy
          ? null
          : () => context.pushNamed(Routes.dzdProfileSetup),
    );
  }
}
