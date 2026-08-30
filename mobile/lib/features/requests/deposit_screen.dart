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
/// Nothing here computes an amount. `quote.percent_bps` is published so the
/// policy can be explained, never so the client can multiply by it — the
/// server already clamped the figure to its floor and cap and told us which,
/// via `clamped`.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';
import 'checkout_section.dart';

class DepositScreen extends ConsumerStatefulWidget {
  const DepositScreen({required this.requestId, super.key});

  final int requestId;

  @override
  ConsumerState<DepositScreen> createState() => _DepositScreenState();
}

class _DepositScreenState extends ConsumerState<DepositScreen> {
  /// The order this screen just created, held only until the provider catches
  /// up. Without it the user taps "pay" and watches the same button for a
  /// round trip.
  PaymentOrder? _created;

  bool _creating = false;

  Future<void> _createOrder() async {
    setState(() => _creating = true);
    try {
      final order = await ref
          .read(paymentRepositoryProvider)
          .createPostingDeposit(widget.requestId);
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

    return AppScaffold(
      topBar: AppTopBar(title: l.depositTitle, showBack: true),
      body: AsyncView<PostingDepositState>(
        value: deposit,
        onRetry: () => ref.invalidate(postingDepositProvider(widget.requestId)),
        loading: () => ListView(
          padding: AppScrollPadding.page(context),
          children: const [SkeletonDetail()],
        ),
        data: (state) => _body(context, l, state),
      ),
    );
  }

  Widget _body(BuildContext context, L l, PostingDepositState state) {
    final order = state.order ?? _created;

    if (order != null) {
      return order.status.isSettled
          ? _paid(context, l)
          : _outstanding(context, l, order);
    }

    if (!state.depositRequired) return _notRequired(context, l);

    final quote = state.quote;
    if (quote == null) return _notRequired(context, l);

    return _quoted(context, l, quote);
  }

  // -------------------------------------------------------------------------
  // States
  // -------------------------------------------------------------------------

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
    final amount = quote.amount;

    // The policy can put a floor or a cap on the figure. Saying so quietly is
    // the difference between "that seems arbitrary" and "that is the rule".
    final clampNote = switch (quote.clamped) {
      'min' => l.depositClampedMin,
      'max' => l.depositClampedMax,
      _ => null,
    };

    return ListView(
      padding: AppScrollPadding.page(context),
      children: [
        if (amount != null) ...[
          MoneyHero(
            amount: amount,
            label: l.depositAmount,
            caption: clampNote,
            tone: StatusTone.action,
          ),
          const SizedBox(height: AppSpace.xl),
        ],
        Text(l.depositExplainer, style: Theme.of(context).textTheme.bodyLarge),
        const SizedBox(height: AppSpace.lg),
        InfoNotice(
          message: l.depositCreditedNote,
          tone: StatusTone.good,
          icon: Icons.savings_outlined,
        ),
        const SizedBox(height: AppSpace.md),
        InfoNotice(message: l.depositRefundNote, icon: Icons.undo_rounded),
        const SizedBox(height: AppSpace.xl),
        AppButton(
          label: l.depositPayAction,
          icon: Icons.lock_rounded,
          isLoading: _creating,
          onPressed: _createOrder,
        ),
      ],
    );
  }

  Widget _outstanding(BuildContext context, L l, PaymentOrder order) =>
      ListView(
        padding: AppScrollPadding.page(context),
        children: [
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

  Widget _paid(BuildContext context, L l) => ListView(
    padding: AppScrollPadding.pageWithFooter(context),
    children: [
      InfoNotice(
        title: l.depositPaidTitle,
        message: l.depositPaidBody,
        tone: StatusTone.good,
        icon: Icons.check_circle_outline_rounded,
      ),
      const SizedBox(height: AppSpace.xl),
      AppButton(
        label: l.requestFindTravelers,
        icon: Icons.travel_explore_rounded,
        onPressed: () => context.pushReplacementNamed(
          Routes.requestDiscovery,
          pathParameters: {'id': '${widget.requestId}'},
        ),
      ),
    ],
  );
}
