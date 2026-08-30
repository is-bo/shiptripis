/// Cancel a delivery.
///
/// **The consequence is shown before the confirmation, and every figure in it
/// comes from the server.** `GET /api/deals/<id>/cancellation` returns a quote
/// — what is refunded, what the traveller keeps, what the platform takes — and
/// this screen renders exactly that. No percentage, no cap and no cutoff is
/// hard-coded, because they are policy frozen onto the deal at funding time
/// and two deals a day apart can differ.
///
/// The quote answers `200` even when cancellation is refused, because the
/// refusal is the thing the user came to find out.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/cancellation.dart';
import '../../l10n/app_localizations.dart';

final _quoteProvider = FutureProvider.autoDispose
    .family<CancellationQuote, int>((ref, dealId) async {
      final repo = ref.watch(dealRepositoryProvider);
      return repo.cancellationQuote(dealId);
    });

class CancelScreen extends ConsumerStatefulWidget {
  const CancelScreen({required this.dealId, super.key});

  final int dealId;

  @override
  ConsumerState<CancelScreen> createState() => _CancelScreenState();
}

class _CancelScreenState extends ConsumerState<CancelScreen> {
  bool _busy = false;

  Future<void> _cancel(CancellationQuote quote) async {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    final confirmed = await confirmAction(
      context,
      title: l.cancelTitle,
      body: quote.isMoneyless
          ? l.cancelKeepAction
          : (quote.compensatesTraveler
                ? l.cancelWithCompensation
                : l.cancelFullRefund),
      confirmLabel: l.cancelConfirmAction,
      cancelLabel: l.cancelKeepAction,
      isDestructive: true,
      // The numbers are repeated inside the dialog, not left behind on the
      // screen: this is the moment the money actually moves.
      consequence: quote.isMoneyless
          ? null
          : _Outcome(quote: quote, locale: locale),
    );
    if (!confirmed || !mounted) return;

    setState(() => _busy = true);
    try {
      final result = await ref
          .read(dealRepositoryProvider)
          .cancel(dealId: widget.dealId);
      if (!mounted) return;
      refreshVolatileState(ref);
      AppSnack.success(
        context,
        result.outcome.settlement?.compensatesTraveler ?? false
            ? l.cancelCancelledTitle
            : l.cancelRefundOnWay,
      );
      context
        ..pop()
        ..openDeal(widget.dealId);
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.code.impliesStaleClientState) refreshVolatileState(ref);
      ref.invalidate(_quoteProvider(widget.dealId));
      AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final quote = ref.watch(_quoteProvider(widget.dealId));

    return AppScaffold(
      topBar: AppTopBar(title: l.cancelTitle, showBack: true),
      body: AsyncView<CancellationQuote>(
        value: quote,
        onRetry: () => ref.invalidate(_quoteProvider(widget.dealId)),
        loading: () => const Padding(
          padding: EdgeInsets.all(AppSpace.gutter),
          child: SkeletonDetail(),
        ),
        data: (data) {
          if (!data.allowed) return _Refused(quote: data);

          return ListView(
            padding: AppScrollPadding.pageWithFooter(context),
            children: [
              SectionHeader(title: l.cancelOutcomeTitle),

              if (data.isMoneyless)
                InfoNotice(
                  message: l.depositRefundNote,
                  icon: Icons.info_outline_rounded,
                )
              else
                _Outcome(quote: data, locale: locale),

              if (data.isLate) ...[
                const SizedBox(height: AppSpace.lg),
                InfoNotice(
                  message: l.cancelWithCompensation,
                  tone: StatusTone.waiting,
                  icon: Icons.schedule_rounded,
                ),
              ],

              if (data.cutoffAt != null && !data.isLate) ...[
                const SizedBox(height: AppSpace.lg),
                Text(
                  LocaleFormats.dateTime(locale, data.cutoffAt!),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: context.colors.textTertiary,
                  ),
                ),
              ],
            ],
          );
        },
      ),
      footer: quote.value?.allowed ?? false
          ? AppButton(
              label: l.cancelConfirmAction,
              variant: AppButtonVariant.destructive,
              isLoading: _busy,
              onPressed: () => _cancel(quote.value!),
            )
          : null,
    );
  }
}

/// The server's numbers, rendered. Nothing here is derived.
class _Outcome extends StatelessWidget {
  const _Outcome({required this.quote, required this.locale});

  final CancellationQuote quote;
  final Locale locale;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    return MoneyBreakdown(
      lines: [
        if (quote.collected != null)
          MoneyLine(label: l.moneyTotal, amount: quote.collected!),
        if (quote.travelerCompensation != null &&
            quote.travelerCompensation!.isPositive)
          MoneyLine(
            label: l.moneyTravelerCompensation,
            amount: quote.travelerCompensation!,
          ),
        if (quote.platformFee != null && quote.platformFee!.isPositive)
          MoneyLine(label: l.moneyPlatformFee, amount: quote.platformFee!),
        if (quote.senderRefund != null)
          MoneyLine.total(
            label: l.moneyRefundToYou,
            amount: quote.senderRefund!,
          ),
      ],
    );
  }
}

/// Cancellation is not available. The refusal code says why, and each reason
/// has a different next step.
class _Refused extends StatelessWidget {
  const _Refused({required this.quote});

  final CancellationQuote quote;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    final body = switch (quote.refusalCode) {
      'cancellation_not_available_after_pickup' => l.cancelAfterPickupBody,
      'use_pre_funding_cancellation' => l.depositRefundNote,
      'not_authorized' => l.stateForbiddenBody,
      _ => l.staleDealClosed,
    };

    final isAfterPickup =
        quote.refusalCode == 'cancellation_not_available_after_pickup';

    return ListView(
      padding: AppScrollPadding.page(context),
      children: [
        AppEmptyState(
          title: l.cancelNotAllowedTitle,
          body: body,
          icon: Icons.block_rounded,
          // After pickup there is still a route: a dispute.
          actionLabel: isAfterPickup ? l.disputeOpenTitle : null,
          onAction: isAfterPickup
              ? () => context.openDisputeForm(quote.dealId)
              : null,
        ),
      ],
    );
  }
}
