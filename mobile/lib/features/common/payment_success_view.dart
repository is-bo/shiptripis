/// Purpose-aware Payment Success view.
///
/// Displayed after an order settles (posting deposit or deal balance).
/// Features the ShipTrip terracotta WaxSeal, parchment receipt card,
/// purpose-driven next steps, and contextual route summary.
library;

import 'package:flutter/material.dart';

import '../../core/format/locale_formats.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/identity.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';

class PaymentSuccessView extends StatelessWidget {
  const PaymentSuccessView({
    required this.order,
    this.settlement,
    this.title,
    this.originPlaceName,
    this.destinationPlaceName,
    this.onPrimaryAction,
    this.primaryActionLabel,
    super.key,
  });

  final PaymentOrder order;
  final PaymentSettlement? settlement;
  final String? title;
  final String? originPlaceName;
  final String? destinationPlaceName;
  final VoidCallback? onPrimaryAction;
  final String? primaryActionLabel;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);

    final activeSettlement = settlement ?? order.settlement;
    final paidAmount = activeSettlement?.paid ?? order.paid;
    final depositCredited = activeSettlement?.depositCredited ?? order.depositCredit;
    final remainingDue = activeSettlement?.remaining ?? order.outstanding;
    final paidByGuest = activeSettlement?.paidBy == 'guest';
    final isDeposit = order.purpose == PaymentPurpose.postingDeposit ||
        activeSettlement?.purpose == PaymentPurpose.postingDeposit;

    final nextStep = activeSettlement?.nextStep ??
        (isDeposit
            ? PaymentSettlementNextStep.awaitOffers
            : PaymentSettlementNextStep.awaitPickup);

    final nextStepBody = switch (nextStep) {
      PaymentSettlementNextStep.awaitOffers =>
        l.paymentSuccessDepositNextBody,
      PaymentSettlementNextStep.awaitPickup =>
        l.paymentSuccessDealNextBody,
      _ => isDeposit
          ? l.paymentSuccessDepositNextBody
          : l.paymentSuccessDealNextBody,
    };

    final buttonLabel = primaryActionLabel ??
        (isDeposit
            ? l.paymentSuccessViewRequestAction
            : l.paymentSuccessViewDeliveryAction);

    return ListView(
      padding: AppScrollPadding.pageWithFooter(context),
      children: [
        const SizedBox(height: AppSpace.lg),
        Center(
          child: WaxSeal(
            glyph: '✓',
            diameter: 68,
            color: c.attentionVivid,
          ),
        ),
        const SizedBox(height: AppSpace.md),
        Center(
          child: Text(
            title ?? l.paymentSuccessTitle,
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.bold,
              color: c.textPrimary,
            ),
            textAlign: TextAlign.center,
          ),
        ),
        if (originPlaceName != null && destinationPlaceName != null) ...[
          const SizedBox(height: AppSpace.xs),
          Center(
            child: Text(
              '$originPlaceName → $destinationPlaceName',
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                color: c.textSecondary,
                fontWeight: FontWeight.w500,
              ),
              textAlign: TextAlign.center,
            ),
          ),
        ],
        const SizedBox(height: AppSpace.xl),

        // Parchment Receipt Card
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Text(
                      l.paymentSuccessReceiptTitle,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                  const SizedBox(width: AppSpace.xs),
                  StatusPill(
                    label: l.paymentSuccessWaxSeal,
                    tone: StatusTone.good,
                    icon: Icons.check_circle_outline_rounded,
                    compact: true,
                  ),
                ],
              ),
              const SizedBox(height: AppSpace.md),
              if (paidAmount != null)
                DetailRow(
                  label: l.paymentSuccessAmountPaid,
                  value: Text(
                    paidAmount.format(locale),
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: c.brand,
                    ),
                  ),
                ),
              if (depositCredited != null && depositCredited.isPositive)
                DetailRow(
                  label: l.paymentSuccessDepositCredit,
                  value: Text(
                    depositCredited.format(locale),
                    style: const TextStyle(fontWeight: FontWeight.w500),
                  ),
                ),
              DetailRow(
                label: paidByGuest
                    ? l.paymentSuccessPaidByGuest
                    : l.paymentSuccessPaidBySelf,
                value: Text(
                  paidByGuest ? 'Guest' : 'Self',
                  style: TextStyle(color: c.textSecondary),
                ),
              ),
              if (remainingDue != null && remainingDue.isPositive) ...[
                const Divider(),
                DetailRow(
                  label: l.paymentSuccessRemainingDue,
                  value: Text(
                    remainingDue.format(locale),
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
              ],
              if (order.paidAt != null) ...[
                const SizedBox(height: AppSpace.xs),
                Text(
                  LocaleFormats.dateTime(locale, order.paidAt!),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: c.textTertiary,
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpace.lg),

        // What happens next card
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.info_outline_rounded,
                    size: 20,
                    color: c.brand,
                  ),
                  const SizedBox(width: AppSpace.xs),
                  Expanded(
                    child: Text(
                      l.paymentSuccessNextStepsTitle,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpace.sm),
              Text(
                nextStepBody,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: c.textSecondary,
                  height: 1.4,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpace.xl),

        if (onPrimaryAction != null)
          AppButton(
            label: buttonLabel,
            onPressed: onPrimaryAction,
            icon: isDeposit ? Icons.explore_rounded : Icons.local_shipping_outlined,
          ),
      ],
    );
  }
}
