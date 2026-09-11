/// Payout history screen.
///
/// Displays a traveler's payout history powered by H6A paginated endpoint
/// `GET /api/payouts`.
///
/// Each item displays canonical EUR amount, snapshotted DZD conversion if
/// applicable, authoritative display state pill, rail, and created date.
/// Tapping an item navigates to the authoritative [PayoutDetailScreen].
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

class PayoutsScreen extends ConsumerWidget {
  const PayoutsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final historyAsync = ref.watch(payoutHistoryProvider);

    return AppScaffold(
      topBar: AppTopBar(
        title: l.payoutHistoryTitle,
        showBack: true,
        actions: [
          IconButton(
            tooltip: l.payoutMethodsTitle,
            icon: const Icon(Icons.account_balance_outlined),
            onPressed: () => context.openPayoutMethods(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(payoutHistoryProvider),
        child: AsyncView<PayoutHistoryPage>(
          value: historyAsync,
          onRetry: () => ref.invalidate(payoutHistoryProvider),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (page) {
            if (page.results.isEmpty) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.payoutEmptyTitle,
                    body: l.payoutEmptyBody,
                    icon: Icons.payments_outlined,
                  ),
                  const SizedBox(height: AppSpace.xl),
                  AppButton(
                    label: l.payoutMethodsTitle,
                    variant: AppButtonVariant.secondary,
                    icon: Icons.account_balance_rounded,
                    onPressed: () => context.openPayoutMethods(),
                  ),
                ],
              );
            }

            return ListView.separated(
              padding: AppScrollPadding.page(context),
              itemCount: page.results.length,
              separatorBuilder: (context, _) =>
                  const SizedBox(height: AppSpace.md),
              itemBuilder: (context, index) {
                final item = page.results[index];
                return _PayoutItemCard(item: item);
              },
            );
          },
        ),
      ),
    );
  }
}

class _PayoutItemCard extends StatelessWidget {
  const _PayoutItemCard({required this.item});

  final PayoutListItem item;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final mobile = item.mobile;
    final displayState =
        mobile?.displayState ?? PayoutDisplayState.parse(item.status);
    final stateCopy = payoutDisplayStateCopy(context, displayState);
    final dzdAmount = mobile?.dzdAmount;
    final isDzd = dzdAmount != null && dzdAmount > 0;
    final fxRate = mobile?.formattedFxRate;
    final blockingCopy =
        payoutBlockingReasonLabel(context, mobile?.blockingReason);

    return AppCard(
      onTap: () => context.openPayoutDetail(item.reference),
      accent: displayState == PayoutDisplayState.needsAttention
          ? StatusTone.bad
          : (displayState == PayoutDisplayState.protectionActive
              ? StatusTone.waiting
              : null),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: MoneyText(
                  item.amountEur,
                  semanticPrefix: l.moneyYourEarnings,
                  size: 20,
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
          if (isDzd) ...[
            const SizedBox(height: AppSpace.xs),
            Row(
              children: [
                MoneyText(
                  Money.minor(dzdAmount, 'DZD', 0),
                  size: 16,
                ),
                if (fxRate != null) ...[
                  const SizedBox(width: AppSpace.sm),
                  Expanded(
                    child: Text(
                      '(${l.payoutRateLabel(fxRate)})',
                      overflow: TextOverflow.ellipsis,
                      style: text.bodySmall?.copyWith(color: c.textTertiary),
                    ),
                  ),
                ],
              ],
            ),
          ] else if (item.payoutAmountLabel != null &&
              item.payoutCurrency != null &&
              item.payoutCurrency!.isNotEmpty) ...[
            const SizedBox(height: AppSpace.xs),
            Text(
              '${item.payoutAmountLabel} ${item.payoutCurrency}',
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],
          const SizedBox(height: AppSpace.sm),
          Row(
            children: [
              Icon(
                item.method == 'stripe'
                    ? Icons.credit_card_rounded
                    : Icons.account_balance_rounded,
                size: 14,
                color: c.textTertiary,
              ),
              const SizedBox(width: AppSpace.xs),
              Expanded(
                child: Text(
                  item.method == 'stripe'
                      ? l.payoutRailStripeEur
                      : (item.method == 'dzd_manual'
                          ? l.payoutRailManualDzd
                          : l.payoutRailUnavailable),
                  overflow: TextOverflow.ellipsis,
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                ),
              ),
              const SizedBox(width: AppSpace.sm),
              if (item.createdAt != null)
                Text(
                  LocaleFormats.fullDate(locale, item.createdAt!),
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                ),
            ],
          ),
          if (blockingCopy != null && blockingCopy.isNotEmpty) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              blockingCopy,
              style: text.bodySmall?.copyWith(color: c.danger),
            ),
          ],
        ],
      ),
    );
  }
}
