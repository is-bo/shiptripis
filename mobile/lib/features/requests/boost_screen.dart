/// Paid visibility.
///
/// The copy on this screen is the product's honesty test. A boost moves a
/// request **up a list of travellers who already match it**. It cannot widen
/// the set of matches, and it cannot produce a delivery. The server states
/// that as a literal contract field — `affects_compatibility` is hard-coded
/// false — and this screen surfaces that rather than making the promise in
/// prose nobody checks.
///
/// Buying is also not paying. A purchase creates a `PaymentOrder` and stops
/// there; the boost activates when a webhook confirms that order. Leaving the
/// checkout page activates nothing, and the screen says so before the user
/// leaves rather than after they come back confused.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/boost.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import 'checkout_section.dart';

final _catalogueProvider = FutureProvider.autoDispose<BoostCatalogue>((
  ref,
) async {
  final repo = ref.watch(boostRepositoryProvider);
  return repo.catalogue();
});

final _boostStateProvider = FutureProvider.autoDispose.family<BoostState, int>((
  ref,
  requestId,
) async {
  final repo = ref.watch(boostRepositoryProvider);
  return repo.forRequest(requestId);
});

class BoostScreen extends ConsumerStatefulWidget {
  const BoostScreen({required this.requestId, super.key});

  final int requestId;

  @override
  ConsumerState<BoostScreen> createState() => _BoostScreenState();
}

class _BoostScreenState extends ConsumerState<BoostScreen> {
  String? _selectedCode;
  bool _busy = false;

  /// Set once a purchase exists and the user is paying for it, so the screen
  /// switches from a catalogue to a checkout.
  String? _payingForReference;

  Future<void> _buy(BoostPackage package) async {
    setState(() => _busy = true);
    try {
      final purchase = await ref
          .read(boostRepositoryProvider)
          .purchase(requestId: widget.requestId, packageCode: package.code);
      if (!mounted) return;
      ref.invalidate(_boostStateProvider(widget.requestId));
      setState(() => _payingForReference = purchase.paymentOrderReference);
    } on ApiException catch (error) {
      if (!mounted) return;
      _explain(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Each refusal has a different meaning and a different next step, so each
  /// gets its own sentence instead of a shared "couldn't do that".
  void _explain(ApiException error) {
    final l = L.of(context);
    final message = switch (error.code.raw) {
      'boost_disabled' => l.boostDisabledBody,
      'boost_limit_reached' => l.boostLimitReachedBody(
        error.intExtra('max_active_per_request') ?? 1,
      ),
      'boost_request_not_active' => l.boostNotEligible,
      'boost_request_expired' => l.boostRequestExpiredBody,
      'boost_package_unknown' => l.boostPackageUnknownBody,
      'boost_request_not_eligible' => l.boostNotEligible,
      _ => null,
    };
    AppSnack.failure(context, error, fallback: message);
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final catalogue = ref.watch(_catalogueProvider);
    final state = ref.watch(_boostStateProvider(widget.requestId));

    return AppScaffold(
      topBar: AppTopBar(title: l.boostTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async {
          ref
            ..invalidate(_catalogueProvider)
            ..invalidate(_boostStateProvider(widget.requestId));
        },
        child: AsyncView<BoostCatalogue>(
          value: catalogue,
          onRetry: () => ref.invalidate(_catalogueProvider),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (packages) {
            if (!packages.enabled) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.boostDisabledTitle,
                    body: l.boostDisabledBody,
                    icon: Icons.speed_rounded,
                  ),
                ],
              );
            }

            final reference = _payingForReference;
            if (reference != null) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  InfoNotice(
                    message: l.boostActivatesOnPayment,
                    tone: StatusTone.waiting,
                    icon: Icons.info_outline_rounded,
                  ),
                  const SizedBox(height: AppSpace.xl),
                  CheckoutSection(
                    orderReference: reference,
                    order: null,
                    onSettled: () {
                      ref.invalidate(_boostStateProvider(widget.requestId));
                      refreshVolatileState(ref);
                      if (mounted) {
                        setState(() => _payingForReference = null);
                      }
                    },
                  ),
                ],
              );
            }

            return ListView(
              padding: AppScrollPadding.pageWithFooter(context),
              children: [
                _Explainer(state: state.value),
                const SizedBox(height: AppSpace.xl),

                if (packages.packages.isEmpty)
                  AppEmptyState(
                    title: l.boostNoPackagesTitle,
                    body: l.boostNoPackagesBody,
                    icon: Icons.speed_rounded,
                    compact: true,
                  )
                else ...[
                  SectionHeader(title: l.boostChoosePackage),
                  for (final package in packages.packages) ...[
                    _PackageCard(
                      package: package,
                      selected: package.code == _selectedCode,
                      onTap: () => setState(() => _selectedCode = package.code),
                    ),
                    const SizedBox(height: AppSpace.md),
                  ],
                ],

                _Purchases(
                  state: state,
                  onPay: (reference) =>
                      setState(() => _payingForReference = reference),
                ),
              ],
            );
          },
        ),
      ),
      footer: _payingForReference != null || _selectedCode == null
          ? null
          : Builder(
              builder: (context) {
                final package = catalogue.value?.packages
                    .where((p) => p.code == _selectedCode)
                    .firstOrNull;
                if (package == null) return const SizedBox.shrink();
                final locale = Localizations.localeOf(context);
                return AppButton(
                  label: package.price == null
                      ? l.boostBuyAction
                      : l.boostPurchase(package.price!.format(locale)),
                  isLoading: _busy,
                  onPressed: () => _buy(package),
                );
              },
            ),
    );
  }
}

/// What a boost is, and — just as importantly — what it is not.
class _Explainer extends StatelessWidget {
  const _Explainer({this.state});

  final BoostState? state;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppInsetGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l.boostExplainer, style: text.bodyMedium),
          const SizedBox(height: AppSpace.md),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.info_outline_rounded, size: 15, color: c.textTertiary),
              const SizedBox(width: AppSpace.sm),
              Expanded(
                child: Text(
                  l.boostDoesNotGuarantee,
                  style: text.bodySmall?.copyWith(color: c.textSecondary),
                ),
              ),
            ],
          ),
          // Backed by the API's own assertion rather than by this paragraph.
          if (state != null && !state!.affectsCompatibility) ...[
            const SizedBox(height: AppSpace.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.verified_outlined, size: 15, color: c.success),
                const SizedBox(width: AppSpace.sm),
                Expanded(
                  child: Text(
                    l.boostCompatibilityNote,
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _PackageCard extends StatelessWidget {
  const _PackageCard({
    required this.package,
    required this.selected,
    required this.onTap,
  });

  final BoostPackage package;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    // Qualitative, not a raw weight. "5" means nothing to a sender; "higher in
    // the list" does, and it is the honest reading of a ranking bonus.
    final visibility = switch (package.rankingWeight) {
      >= 10 => l.boostRankingTop,
      >= 5 => l.boostRankingStrong,
      _ => l.boostRankingModest,
    };

    return Semantics(
      button: true,
      selected: selected,
      label: package.label,
      hint: selected ? l.a11ySelected : l.a11yNotSelected,
      onTap: onTap,
      child: ExcludeSemantics(
        child: AppCard(
          onTap: onTap,
          accent: selected ? StatusTone.progress : null,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(child: Text(package.label, style: text.titleSmall)),
                  if (package.price != null)
                    MoneyText(
                      package.price!,
                      semanticPrefix: l.boostPriceLabel,
                      size: 17,
                    ),
                ],
              ),
              const SizedBox(height: AppSpace.md),
              DetailRow(
                label: l.boostDurationLabel,
                value: Text(
                  formatBoostDuration(context, package.durationSeconds),
                ),
              ),
              DetailRow(label: l.boostRankingLabel, value: Text(visibility)),
              const SizedBox(height: AppSpace.sm),
              Row(
                children: [
                  Icon(
                    selected
                        ? Icons.radio_button_checked_rounded
                        : Icons.radio_button_unchecked_rounded,
                    size: 18,
                    color: selected ? c.brand : c.hairlineStrong,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Purchases extends StatelessWidget {
  const _Purchases({required this.state, required this.onPay});

  final AsyncValue<BoostState> state;
  final ValueChanged<String> onPay;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    return AsyncView<BoostState>(
      value: state,
      loading: SizedBox.shrink,
      error: (_) => const SizedBox.shrink(),
      data: (data) {
        if (data.purchases.isEmpty) return const SizedBox.shrink();

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: AppSpace.xl),
            SectionHeader(title: l.boostPurchasesSection),
            for (final purchase in data.purchases) ...[
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            purchase.packageLabel ?? purchase.packageCode,
                            style: Theme.of(context).textTheme.titleSmall,
                          ),
                        ),
                        Builder(
                          builder: (context) {
                            final (label, tone, icon) = _describe(
                              context,
                              purchase.status,
                            );
                            return StatusPill(
                              label: label,
                              tone: tone,
                              icon: icon,
                              compact: true,
                            );
                          },
                        ),
                      ],
                    ),
                    if (purchase.expiresAt != null) ...[
                      const SizedBox(height: AppSpace.sm),
                      Text(
                        l.boostActiveUntil(
                          MaterialLocalizations.of(
                            context,
                          ).formatFullDate(purchase.expiresAt!),
                        ),
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: context.colors.textSecondary,
                        ),
                      ),
                    ],
                    if (purchase.awaitsPayment &&
                        purchase.paymentOrderReference != null) ...[
                      const SizedBox(height: AppSpace.md),
                      AppButton(
                        label: purchase.price == null
                            ? l.boostPayAction
                            : l.boostPurchase(purchase.price!.format(locale)),
                        variant: AppButtonVariant.secondary,
                        expand: false,
                        onPressed: () => onPay(purchase.paymentOrderReference!),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: AppSpace.md),
            ],
          ],
        );
      },
    );
  }

  (String, StatusTone, IconData) _describe(
    BuildContext context,
    BoostStatus status,
  ) {
    final l = L.of(context);
    return switch (status) {
      BoostStatus.active => (
        l.boostActive,
        StatusTone.good,
        Icons.trending_up_rounded,
      ),
      BoostStatus.pendingPayment => (
        l.boostPendingPayment,
        StatusTone.action,
        Icons.credit_card_rounded,
      ),
      BoostStatus.expired => (
        l.boostExpired,
        StatusTone.neutral,
        Icons.timer_off_rounded,
      ),
      BoostStatus.cancelled => (
        l.boostStatusCancelled,
        StatusTone.neutral,
        Icons.cancel_rounded,
      ),
      // Paid, then the request stopped being boostable — automatically
      // refunded. Neutral, not a failure the sender caused.
      BoostStatus.unusable => (
        l.boostStatusUnusable,
        StatusTone.neutral,
        Icons.undo_rounded,
      ),
      BoostStatus.refunded => (
        l.boostStatusRefunded,
        StatusTone.neutral,
        Icons.undo_rounded,
      ),
      BoostStatus.unknown => (
        l.stateUnexpectedTitle,
        StatusTone.neutral,
        Icons.help_outline_rounded,
      ),
    };
  }
}
