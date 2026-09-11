/// Payout detail screen.
///
/// Renders an authoritative view of a single payout from `GET /api/payouts/<ref>`.
/// Displays canonical EUR amount, snapshotted DZD conversion if applicable,
/// authoritative display state pill, rail, timestamps, and safe blocking reasons.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../core/money/money.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payout.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';

class PayoutDetailScreen extends ConsumerWidget {
  const PayoutDetailScreen({
    required this.reference,
    super.key,
  });

  final String reference;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    final payoutAsync = ref.watch(payoutDetailProvider(reference));

    return AppScaffold(
      topBar: AppTopBar(
        title: l.payoutDetailTitle,
        subtitle: reference,
        showBack: true,
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(payoutDetailProvider(reference)),
        child: AsyncView<PayoutMobile>(
          value: payoutAsync,
          onRetry: () => ref.invalidate(payoutDetailProvider(reference)),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (payout) {
            final stateCopy =
                payoutDisplayStateCopy(context, payout.displayState);
            final blockingText =
                payoutBlockingReasonLabel(context, payout.blockingReason);
            final dzdAmount = payout.dzdAmount;
            final isDzd = dzdAmount != null && dzdAmount > 0;
            final fxRate = payout.formattedFxRate;

            return ListView(
              padding: AppScrollPadding.page(context),
              children: [
                // Top Financial Overview Card
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  l.moneyYourEarnings,
                                  style: text.bodySmall?.copyWith(
                                    color: c.textSecondary,
                                  ),
                                ),
                                const SizedBox(height: AppSpace.xs),
                                MoneyText(
                                  payout.canonicalEurAmount,
                                  semanticPrefix: l.moneyYourEarnings,
                                  size: 28,
                                ),
                              ],
                            ),
                          ),
                          StatusPill(
                            label: stateCopy.label,
                            tone: stateCopy.tone,
                            icon: stateCopy.icon,
                          ),
                        ],
                      ),

                      // DZD conversion snapshot if applicable
                      if (isDzd) ...[
                        const SizedBox(height: AppSpace.md),
                        Divider(height: 1, color: c.hairline),
                        const SizedBox(height: AppSpace.md),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              l.payoutDzdTitle,
                              style: text.bodySmall?.copyWith(
                                color: c.textSecondary,
                              ),
                            ),
                            const SizedBox(height: AppSpace.xs),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              crossAxisAlignment: CrossAxisAlignment.baseline,
                              textBaseline: TextBaseline.alphabetic,
                              children: [
                                MoneyText(
                                  Money.minor(dzdAmount, 'DZD', 0),
                                  size: 22,
                                ),
                                if (fxRate != null)
                                  Flexible(
                                    child: Text(
                                      l.payoutRateLabel(fxRate),
                                      style: text.bodySmall?.copyWith(
                                        color: c.textTertiary,
                                        fontFeatures: const [
                                          FontFeature.tabularFigures(),
                                        ],
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: AppSpace.xl),

                // Blocking Reason Notice (if present)
                if (blockingText != null) ...[
                  InfoNotice(
                    title: l.payoutStatusNeedsAttention,
                    message: blockingText,
                    tone:
                        payout.displayState == PayoutDisplayState.needsAttention
                            ? StatusTone.bad
                            : StatusTone.waiting,
                    icon:
                        payout.displayState == PayoutDisplayState.needsAttention
                            ? Icons.error_outline_rounded
                            : Icons.lock_clock_rounded,
                  ),
                  const SizedBox(height: AppSpace.xl),
                ],

                // Method / Rail Info
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        l.payoutRailLabel,
                        style: text.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: AppSpace.md),
                      DetailRow(
                        label: l.payoutRailLabel,
                        value: Text(
                          _railName(context, payout.rail),
                          style: text.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w500),
                        ),
                      ),
                      const SizedBox(height: AppSpace.sm),
                      DetailRow(
                        label: l.payoutReferenceLabel,
                        value: Text(
                          payout.reference,
                          style:
                              text.bodySmall?.copyWith(color: c.textTertiary),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpace.xl),

                // Timestamps Card
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        l.deliveriesFilterHistory,
                        style: text.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w600),
                      ),
                      if (payout.eligibleAt != null) ...[
                        const SizedBox(height: AppSpace.md),
                        DetailRow(
                          label: l.payoutEligibleAtLabel,
                          value: Text(
                            LocaleFormats.dateTime(locale, payout.eligibleAt!),
                            style: text.bodyMedium,
                          ),
                        ),
                      ],
                      if (payout.sentAt != null) ...[
                        const SizedBox(height: AppSpace.sm),
                        DetailRow(
                          label: l.payoutSentAtLabel,
                          value: Text(
                            LocaleFormats.dateTime(locale, payout.sentAt!),
                            style: text.bodyMedium,
                          ),
                        ),
                      ],
                      if (payout.paidAt != null) ...[
                        const SizedBox(height: AppSpace.sm),
                        DetailRow(
                          label: l.payoutPaidAtLabel,
                          value: Text(
                            LocaleFormats.dateTime(locale, payout.paidAt!),
                            style: text.bodyMedium,
                          ),
                        ),
                      ],
                      if (payout.protectionEndsAt != null &&
                          payout.protectionActive) ...[
                        const SizedBox(height: AppSpace.sm),
                        DetailRow(
                          label: l.payoutProtectionEndsAtLabel,
                          value: Text(
                            LocaleFormats.dateTime(
                                locale, payout.protectionEndsAt!),
                            style: text.bodyMedium,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: AppSpace.xxl),

                // Contextual Actions
                if (payout.availableActions
                    .contains('configure_payout_method')) ...[
                  AppButton(
                    label: l.payoutMethodsTitle,
                    icon: Icons.account_balance_rounded,
                    onPressed: () => context.openPayoutMethods(),
                  ),
                  const SizedBox(height: AppSpace.md),
                ],

                if (payout.dealId > 0) ...[
                  AppButton(
                    label: l.payoutDeliveryLabel,
                    variant: AppButtonVariant.secondary,
                    icon: Icons.handshake_outlined,
                    onPressed: () => context.openDeal(payout.dealId),
                  ),
                  const SizedBox(height: AppSpace.md),
                ],
              ],
            );
          },
        ),
      ),
    );
  }

  String _railName(BuildContext context, PayoutRail rail) {
    final l = L.of(context);
    return switch (rail) {
      PayoutRail.stripeEur => l.payoutRailStripeEur,
      PayoutRail.manualDzd => l.payoutRailManualDzd,
      PayoutRail.unavailable || PayoutRail.unknown => l.payoutRailUnavailable,
    };
  }
}
