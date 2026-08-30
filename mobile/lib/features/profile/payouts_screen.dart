/// Earnings.
///
/// A traveller's money, and — more importantly — *why it has not arrived yet*.
/// Payout is gated on a 48-hour protection window and frozen outright by an
/// active dispute, and both of those are states the app must name rather than
/// leave as a silence.
///
/// `frozen` gets its own treatment for that reason. It is not a failure and
/// must never read as one: the money exists, and something is holding it.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../design/components/codes.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';

class PayoutsScreen extends ConsumerWidget {
  const PayoutsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final payouts = ref.watch(payoutsProvider);

    return AppScaffold(
      topBar: AppTopBar(title: l.payoutTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(payoutsProvider),
        child: AsyncView<List<Payout>>(
          value: payouts,
          onRetry: () => ref.invalidate(payoutsProvider),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (all) {
            if (all.isEmpty) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.payoutEmptyTitle,
                    body: l.payoutEmptyBody,
                    icon: Icons.payments_outlined,
                  ),
                ],
              );
            }

            final pending = all
                .where((p) => p.status.isPending)
                .toList(growable: false);
            final settled = all
                .where((p) => !p.status.isPending)
                .toList(growable: false);

            return ListView(
              padding: AppScrollPadding.page(context),
              children: [
                if (pending.isNotEmpty) ...[
                  SectionHeader(title: l.payoutPendingTitle),
                  for (final payout in pending) ...[
                    _PayoutCard(payout: payout),
                    const SizedBox(height: AppSpace.md),
                  ],
                  const SizedBox(height: AppSpace.lg),
                ],
                if (settled.isNotEmpty) ...[
                  SectionHeader(title: l.deliveriesFilterHistory),
                  for (final payout in settled) ...[
                    _PayoutCard(payout: payout),
                    const SizedBox(height: AppSpace.md),
                  ],
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _PayoutCard extends StatelessWidget {
  const _PayoutCard({required this.payout});

  final Payout payout;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final copy = payoutStatusCopy(context, payout.status);
    final amount = payout.amount;
    final dealId = payout.dealId;

    return AppCard(
      onTap: dealId == null ? null : () => context.openDeal(dealId),
      accent: payout.status == PayoutStatus.frozen ? StatusTone.waiting : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (amount != null)
                Expanded(
                  child: MoneyText(
                    amount,
                    semanticPrefix: l.moneyYourReward,
                    size: 20,
                  ),
                )
              else
                const Spacer(),
              StatusPill(
                label: copy.label,
                tone: copy.tone,
                icon: copy.icon,
                compact: true,
              ),
            ],
          ),

          // The one question a traveller actually has. Answered from the
          // server's own instant, never from a locally computed 48 hours.
          if (payout.status == PayoutStatus.notEligible &&
              payout.eligibleAt != null) ...[
            const SizedBox(height: AppSpace.md),
            CodeCountdown(
              target: payout.eligibleAt!,
              label: l.payoutEligibleIn,
              compact: true,
            ),
          ],

          if (payout.status == PayoutStatus.frozen) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              l.payoutFrozenBody,
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
          ],

          if (payout.paidAt != null) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              LocaleFormats.fullDate(locale, payout.paidAt!),
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],

          // Settled in whatever currency the transfer used. The server sends a
          // pre-rendered string; it is never re-derived here.
          if (payout.payoutAmountLabel != null &&
              payout.payoutCurrency != null &&
              payout.payoutCurrency!.isNotEmpty) ...[
            const SizedBox(height: AppSpace.xs),
            Text(
              '${payout.payoutAmountLabel} ${payout.payoutCurrency}',
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],
        ],
      ),
    );
  }
}
