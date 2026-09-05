/// Pay for a delivery.
///
/// The sender pays the balance on the deal. Two things this screen is careful
/// about:
///
/// * **There is no `POST /api/deals/<id>/payment`.** That route is read-only.
///   Paying goes through the generic checkout against the `deal_balance`
///   order's reference, which is what `GET` returns. The screen therefore
///   reads the order first and then hands it to the shared checkout section.
///
/// * **The traveller sees a different, deliberately reduced payload** — a
///   status and an outstanding amount, no attempts and nothing about who paid
///   or how. `DealPaymentState.viewerIsTraveler` records which projection
///   arrived so this screen never reads the absence of attempts as "never
///   attempted".
///
/// A deposit already paid on the request shows up here as
/// `deposit_credit_eur_cents`, rendered as a subtraction labelled as already
/// paid — never as a second charge.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../domain/money_perspective.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';
import '../requests/checkout_section.dart';

final _dealPaymentProvider = FutureProvider.autoDispose
    .family<DealPaymentState, ({int dealId, bool isTraveler})>((
      ref,
      key,
    ) async {
      final repo = ref.watch(paymentRepositoryProvider);
      return repo.dealPayment(key.dealId, viewerIsTraveler: key.isTraveler);
    });

class DealPaymentScreen extends ConsumerWidget {
  const DealPaymentScreen({required this.dealId, super.key});

  final int dealId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final deal = ref.watch(dealDetailProvider(dealId)).value;

    // Until the deal is loaded we cannot know which projection to ask for, so
    // the screen waits rather than guessing and getting the reduced one.
    if (account == null || deal == null) {
      return AppScaffold(
        topBar: AppTopBar(title: l.paymentTitle, showBack: true),
        body: const Padding(
          padding: EdgeInsets.all(AppSpace.gutter),
          child: SkeletonDetail(),
        ),
      );
    }

    final perspective = deal.moneyPerspectiveFor(account.id);
    if (perspective == null) {
      return AppScaffold(
        topBar: AppTopBar(title: l.paymentTitle, showBack: true),
        body: const SizedBox.shrink(),
      );
    }
    final isTraveler = perspective == MoneyPerspective.traveler;
    final key = (dealId: dealId, isTraveler: isTraveler);
    final payment = ref.watch(_dealPaymentProvider(key));

    return AppScaffold(
      topBar: AppTopBar(
        title: isTraveler ? l.moneyYourEarnings : l.paymentTitle,
        showBack: true,
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(_dealPaymentProvider(key)),
        child: AsyncView<DealPaymentState>(
          value: payment,
          onRetry: () => ref.invalidate(_dealPaymentProvider(key)),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonDetail()],
          ),
          data: (state) => ListView(
            padding: AppScrollPadding.page(context),
            children: [
              _Summary(state: state, isTraveler: isTraveler),
              const SizedBox(height: AppSpace.xl),

              if (isTraveler)
                _TravelerView(state: state)
              else
                _SenderView(
                  state: state,
                  onSettled: () {
                    ref.invalidate(_dealPaymentProvider(key));
                    refreshVolatileState(ref);
                  },
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Summary extends StatelessWidget {
  const _Summary({required this.state, required this.isTraveler});

  final DealPaymentState state;
  final bool isTraveler;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final order = state.order;

    // The traveller is told what they earn; the sender what they owe. Same
    // deal, two true sentences.
    final hero = isTraveler ? state.travelerTotal : order?.outstanding;
    final heroLabel = isTraveler
        ? l.moneyTotalYouReceive
        : l.moneyRemainingToPay;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (hero != null)
          AppCard(
            child: MoneyHero(amount: hero, label: heroLabel),
          ),

        if (!isTraveler) ...[
          const SizedBox(height: AppSpace.lg),
          MoneyBreakdown(
            title: l.moneyBreakdownTitle,
            // The deposit is credit, not another fee. `MoneyLine.credit`
            // renders it as a subtraction in the success tone precisely so it
            // cannot be misread as one.
            explainer: (order?.hasCredit ?? false)
                ? l.moneyDepositNotExtra
                : l.moneyRewardNotReduced,
            lines: [
              if (state.travelerReward != null)
                MoneyLine(
                  label: l.moneyBaseReward,
                  amount: state.travelerReward!,
                ),
              if (state.travelerBoostBonus?.isPositive ?? false)
                MoneyLine(
                  label: l.moneyBoostBonus,
                  amount: state.travelerBoostBonus!,
                ),
              if (state.travelerTotal != null)
                MoneyLine.total(
                  label: l.moneyTravelerReceives,
                  amount: state.travelerTotal!,
                ),
              if (state.platformFee != null)
                MoneyLine(
                  label: l.moneyPlatformFee,
                  amount: state.platformFee!,
                ),
              if (state.platformBoostRevenue?.isPositive ?? false)
                MoneyLine(
                  label: l.moneyPlatformBoostRevenue,
                  amount: state.platformBoostRevenue!,
                ),
              if (state.senderTotalWithBoost != null)
                MoneyLine(
                  label: l.moneyTotal,
                  amount: state.senderTotalWithBoost!,
                ),
              if (order?.depositCredit != null &&
                  order!.depositCredit!.isPositive)
                MoneyLine.credit(
                  label: l.moneyDepositPaid,
                  amount: order.depositCredit!,
                ),
              if (order?.outstanding != null)
                MoneyLine.total(
                  label: l.moneyRemainingToPay,
                  amount: order!.outstanding!,
                ),
            ],
          ),
        ],
      ],
    );
  }
}

/// What the traveller may know: whether it is funded, and nothing else.
class _TravelerView extends StatelessWidget {
  const _TravelerView({required this.state});

  final DealPaymentState state;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final order = state.order;

    if (order == null) {
      return InfoNotice(
        message: l.paymentStatusRequired,
        tone: StatusTone.waiting,
        icon: Icons.hourglass_top_rounded,
      );
    }

    final copy = paymentOrderStatusCopy(context, order.status);
    return AppInsetGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StatusPill(label: copy.label, tone: copy.tone, icon: copy.icon),
          const SizedBox(height: AppSpace.md),
          Text(
            order.status.isSettled
                ? l.dealTravelerPaymentFunded
                : l.dealTravelerAwaitingPayment,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.colors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _SenderView extends StatelessWidget {
  const _SenderView({required this.state, required this.onSettled});

  final DealPaymentState state;
  final VoidCallback onSettled;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final order = state.order;

    if (order == null) {
      // No balance order yet — the deal is not at a payable stage. Saying so
      // is better than an empty screen with a dead button.
      return InfoNotice(
        message: l.staleDealClosed,
        tone: StatusTone.waiting,
        icon: Icons.hourglass_top_rounded,
      );
    }

    if (order.status.isSettled) {
      return AppEmptyState(
        title: l.paymentSucceededTitle,
        body: l.paymentSucceededBody,
        icon: Icons.check_circle_outline_rounded,
        compact: true,
      );
    }

    return CheckoutSection(
      orderReference: order.publicReference,
      order: order,
      onSettled: onSettled,
    );
  }
}
