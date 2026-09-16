/// The posting deposit.
///
/// A request that owes a deposit is not published. That is the whole point of
/// this screen, and the reason it exists as its own destination rather than a
/// banner: until the deposit settles, no traveller sees the parcel, and a
/// sender who does not understand that will sit waiting for offers that were
/// never going to come.
///
/// The deposit is **credit, not a fee**. It comes off the final balance when a
/// traveller is accepted, and it comes back in full if nobody takes the parcel
/// or the sender cancels first. Both of those sentences are on screen, because
/// "pay to post" reads like a listing charge otherwise.
///
/// J2 adds sender-selected deposit amount (Min, Recommended, Full, Custom),
/// live balance calculation, and wax-seal PaymentSuccessView on settlement.
library;

import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/money/money.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';
import '../common/payment_success_view.dart';
import 'checkout_section.dart';

class DepositScreen extends ConsumerStatefulWidget {
  const DepositScreen({required this.requestId, super.key});

  final int requestId;

  @override
  ConsumerState<DepositScreen> createState() => _DepositScreenState();
}

class _DepositScreenState extends ConsumerState<DepositScreen> {
  PaymentOrder? _created;
  bool _creating = false;
  int? _chosenDepositCents;
  final _customAmountController = TextEditingController();
  bool _isCustom = false;

  @override
  void dispose() {
    _customAmountController.dispose();
    super.dispose();
  }

  void _syncInitial(DepositQuote quote) {
    if (_chosenDepositCents == null && !_isCustom) {
      final rec = quote.recommended?.minorUnits ??
          quote.amount?.minorUnits ??
          300;
      _chosenDepositCents = rec;
    }
  }

  Future<void> _createOrder(int amountCents) async {
    setState(() => _creating = true);
    try {
      final order = await ref
          .read(paymentRepositoryProvider)
          .createPostingDeposit(
            widget.requestId,
            amountEurCents: amountCents,
          );
      if (!mounted) return;
      setState(() => _created = order);
      ref.invalidate(postingDepositProvider(widget.requestId));
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.code.impliesStaleClientState) {
        refreshVolatileState(ref);
      }
      AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  void _onSettled() {
    if (!mounted) return;
    refreshVolatileState(ref);
    ref.invalidate(postingDepositProvider(widget.requestId));
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final deposit = ref.watch(postingDepositProvider(widget.requestId));
    final order = deposit.asData?.value.order ?? _created;
    final request = (order?.status.isSettled ?? false)
        ? ref.watch(requestDetailProvider(widget.requestId)).asData?.value
        : null;

    return AppScaffold(
      topBar: AppTopBar(title: l.depositTitle, showBack: true),
      body: AsyncView<PostingDepositState>(
        value: deposit,
        onRetry: () => ref.invalidate(postingDepositProvider(widget.requestId)),
        loading: () => ListView(
          padding: AppScrollPadding.page(context),
          children: const [SkeletonDetail()],
        ),
        data: (state) => _body(context, l, state, request),
      ),
    );
  }

  Widget _body(
    BuildContext context,
    L l,
    PostingDepositState state,
    dynamic request,
  ) {
    final order = state.order ?? _created;

    if (order != null) {
      return order.status.isSettled
          ? _paid(context, l, order, request)
          : _outstanding(context, l, order, state.quote);
    }

    if (!state.depositRequired) return _notRequired(context, l);

    final quote = state.quote;
    if (quote == null) return _notRequired(context, l);

    return _quoted(context, l, quote);
  }

  Widget _notRequired(BuildContext context, L l) => ListView(
        padding: AppScrollPadding.page(context),
        children: [
          AppEmptyState(
            title: l.depositNotRequiredTitle,
            body: l.depositNotRequiredBody,
            icon: Icons.check_circle_outline_rounded,
            actionLabel: l.actionGoBack,
            onAction: () => context.pop(),
          ),
        ],
      );

  Widget _quoted(BuildContext context, L l, DepositQuote quote) {
    _syncInitial(quote);
    final locale = Localizations.localeOf(context);
    final suggestedTotal = quote.estimatedSenderTotal;

    final minCents = quote.minimum?.minorUnits ?? 300;
    final recCents = quote.recommended?.minorUnits ??
        quote.amount?.minorUnits ??
        300;
    final fullCents = suggestedTotal?.minorUnits;

    final hasSeparateMin = minCents < recCents;
    final hasSeparateFull = fullCents != null && fullCents > recCents;

    final effectiveDeposit = _isCustom
        ? (AppAmountField.centsOf(_customAmountController) ?? minCents)
        : (_chosenDepositCents ?? recCents);

    final remainingBalanceCents = fullCents != null
        ? max(0, fullCents - effectiveDeposit)
        : null;
    final isFull = fullCents != null && effectiveDeposit >= fullCents;

    final clampNote = switch (quote.clamped) {
      'min' => l.depositClampedMin,
      'max' => l.depositClampedMax,
      _ => null,
    };

    return ListView(
      padding: AppScrollPadding.pageWithFooter(context),
      children: [
        if (suggestedTotal != null) ...[
          MoneyHero(
            amount: suggestedTotal,
            label: l.depositSuggestedTotal,
            tone: StatusTone.neutral,
          ),
          const SizedBox(height: AppSpace.xl),
        ],

        _DepositGuidance(
          quote: quote,
          showSuggestedTotal: suggestedTotal == null,
          recommendationNote: clampNote,
        ),
        const SizedBox(height: AppSpace.lg),

        Text(l.depositExplainer, style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: AppSpace.md),

        SectionHeader(title: l.depositSectionTitle),
        Wrap(
          spacing: AppSpace.sm,
          children: [
            if (hasSeparateMin)
              ChoiceChip(
                label: Text(
                  l.depositPresetMin(Money.eurCents(minCents).format(locale)),
                ),
                selected: !_isCustom && _chosenDepositCents == minCents,
                onSelected: (selected) {
                  if (selected) {
                    setState(() {
                      _isCustom = false;
                      _chosenDepositCents = minCents;
                    });
                  }
                },
              ),
            ChoiceChip(
              label: Text(
                l.depositPresetRecommended(
                  Money.eurCents(recCents).format(locale),
                ),
              ),
              selected: !_isCustom && _chosenDepositCents == recCents,
              onSelected: (selected) {
                if (selected) {
                  setState(() {
                    _isCustom = false;
                    _chosenDepositCents = recCents;
                  });
                }
              },
            ),
            if (hasSeparateFull)
              ChoiceChip(
                label: Text(
                  l.depositPresetFull(
                    Money.eurCents(fullCents).format(locale),
                  ),
                ),
                selected: !_isCustom && _chosenDepositCents == fullCents,
                onSelected: (selected) {
                  if (selected) {
                    setState(() {
                      _isCustom = false;
                      _chosenDepositCents = fullCents;
                    });
                  }
                },
              ),
            ChoiceChip(
              label: Text(l.depositPresetCustom),
              selected: _isCustom,
              onSelected: (selected) {
                if (selected) {
                  setState(() {
                    _isCustom = true;
                    if (_customAmountController.text.isEmpty) {
                      _customAmountController.text =
                          Money.eurCents(recCents).editableString;
                    }
                  });
                }
              },
            ),
          ],
        ),
        const SizedBox(height: AppSpace.md),

        if (_isCustom) ...[
          AppAmountField(
            label: l.depositCustomAmountLabel,
            controller: _customAmountController,
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: AppSpace.md),
        ],

        // Live Breakdown Card
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DetailRow(
                label: l.depositAmount,
                value: Text(
                  Money.eurCents(effectiveDeposit).format(locale),
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: context.colors.brand,
                      ),
                ),
              ),
              DetailRow(
                label: l.depositCreditedNote,
                value: Text(
                  Money.eurCents(effectiveDeposit).format(locale),
                  style: const TextStyle(fontWeight: FontWeight.w500),
                ),
              ),
              if (remainingBalanceCents != null) ...[
                const Divider(),
                DetailRow(
                  label: l.depositRemainingBalance,
                  value: Text(
                    Money.eurCents(remainingBalanceCents).format(locale),
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      color: remainingBalanceCents == 0
                          ? context.colors.success
                          : context.colors.textPrimary,
                    ),
                  ),
                ),
              ],
              if (isFull) ...[
                const SizedBox(height: AppSpace.sm),
                Text(
                  l.depositFullDepositNotice,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: context.colors.textSecondary,
                      ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpace.lg),

        InfoNotice(
          message: l.depositRefundNote,
          icon: Icons.undo_rounded,
        ),
        const SizedBox(height: AppSpace.xl),

        AppButton(
          label: l.depositPayAction,
          icon: Icons.lock_rounded,
          isLoading: _creating,
          onPressed: () => _createOrder(effectiveDeposit),
        ),
      ],
    );
  }

  Widget _outstanding(
    BuildContext context,
    L l,
    PaymentOrder order,
    DepositQuote? quote,
  ) =>
      ListView(
        padding: AppScrollPadding.page(context),
        children: [
          if (quote?.estimatedSenderTotal case final suggestedTotal?) ...[
            MoneyHero(
              amount: suggestedTotal,
              label: l.depositSuggestedTotal,
              tone: StatusTone.neutral,
            ),
            const SizedBox(height: AppSpace.lg),
          ],
          if (order.outstanding != null) ...[
            MoneyHero(
              amount: order.outstanding!,
              label: l.depositAmount,
              tone: StatusTone.action,
            ),
            const SizedBox(height: AppSpace.lg),
          ],
          InfoNotice(
            message: l.depositCreditedNote,
            tone: StatusTone.good,
            icon: Icons.savings_outlined,
          ),
          const SizedBox(height: AppSpace.xl),
          CheckoutSection(
            orderReference: order.publicReference,
            order: order,
            onSettled: _onSettled,
          ),
        ],
      );

  Widget _paid(
    BuildContext context,
    L l,
    PaymentOrder order,
    dynamic request,
  ) {
    final originName = request?.pickupPlace?.name as String?;
    final destName = request?.deliveryPlace?.name as String?;

    return PaymentSuccessView(
      order: order,
      originPlaceName: originName,
      destinationPlaceName: destName,
      onPrimaryAction: () => context.pushReplacementNamed(
        Routes.requestDiscovery,
        pathParameters: {'id': '${widget.requestId}'},
      ),
      primaryActionLabel: l.requestFindTravelers,
    );
  }
}

class _DepositGuidance extends StatelessWidget {
  const _DepositGuidance({
    required this.quote,
    this.showSuggestedTotal = true,
    this.recommendationNote,
  });

  final DepositQuote quote;
  final bool showSuggestedTotal;
  final String? recommendationNote;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    return Semantics(
      container: true,
      label: l.depositGuidanceTitle,
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(title: l.depositGuidanceTitle),
            if (showSuggestedTotal && quote.estimatedSenderTotal != null)
              DetailRow(
                label: l.depositSuggestedTotal,
                value: Text(quote.estimatedSenderTotal!.format(locale)),
              ),
            if (quote.recommended != null || quote.amount != null)
              DetailRow(
                label: l.depositRecommended,
                value: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text((quote.recommended ?? quote.amount)!.format(locale)),
                    if (recommendationNote != null)
                      Text(
                        recommendationNote!,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: context.colors.textSecondary,
                            ),
                        textAlign: TextAlign.end,
                      ),
                  ],
                ),
              ),
            if (quote.minimum != null)
              DetailRow(
                label: l.depositMinimumAllowed,
                value: Text(quote.minimum!.format(locale)),
              ),
            const SizedBox(height: AppSpace.sm),
            Text(
              l.depositGuidanceNote,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: context.colors.textSecondary,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}

