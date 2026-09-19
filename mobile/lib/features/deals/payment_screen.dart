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
///
/// J7D: once the server reports the balance paid, the page *is* the result —
/// the shared [PaymentResultView] with the amount just paid, the credited
/// deposit, *Paid in full* (never "Remaining €0.00"), *Payment protected* and
/// **View delivery**. Opened again later, it says the payment is already
/// complete rather than offering anything to pay.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/live/live_updates.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../domain/money_perspective.dart';
import '../../l10n/app_localizations.dart';
import '../common/payment_result.dart';
import '../common/status_copy.dart';
import '../requests/checkout_section.dart';
import '../requests/request_labels.dart';

typedef _DealPaymentKey = ({int dealId, bool isTraveler});
typedef _AccountDealPaymentKey = ({int? accountId, _DealPaymentKey payment});

final _dealPaymentQuery = FutureProvider.autoDispose
    .family<DealPaymentState, _AccountDealPaymentKey>((ref, key) async {
      final unsubscribe = ref
          .read(liveUpdatesProvider)
          .register(
            LiveResource.payment(key.payment.dealId),
            ref.invalidateSelf,
          );
      ref.onDispose(unsubscribe);
      final repo = ref.watch(paymentRepositoryProvider);
      final result = await repo.dealPayment(
        key.payment.dealId,
        viewerIsTraveler: key.payment.isTraveler,
      );
      if (ref.read(accountProvider)?.id != key.accountId) {
        throw StateError('Discarded a payment read from an older session.');
      }
      return result;
    });
final _dealPaymentProvider = Provider.autoDispose
    .family<AsyncValue<DealPaymentState>, _DealPaymentKey>((ref, payment) {
      final accountId = ref.watch(
        accountProvider.select((account) => account?.id),
      );
      final query = _dealPaymentQuery((accountId: accountId, payment: payment));
      // ignore: experimental_member_use
      ref.onManualInvalidation(() => ref.invalidate(query));
      return ref.watch(query);
    });

class DealPaymentScreen extends ConsumerStatefulWidget {
  const DealPaymentScreen({required this.dealId, super.key});

  final int dealId;

  @override
  ConsumerState<DealPaymentScreen> createState() => _DealPaymentScreenState();
}

class _DealPaymentScreenState extends ConsumerState<DealPaymentScreen> {
  /// Whether this screen has shown the balance still owed. A balance that
  /// settles while the Sender watches is "Payment received"; one already
  /// settled when they arrived is "This payment is already complete".
  bool _sawOutstanding = false;

  /// The checkout is showing a result, so the "what you owe" summary above it
  /// steps aside.
  bool _checkoutShowsResult = false;

  int get dealId => widget.dealId;

  void _onCheckoutPhase(CheckoutPhase phase) {
    final showing = phase.showsResult;
    if (!mounted || showing == _checkoutShowsResult) return;
    setState(() => _checkoutShowsResult = showing);
  }

  @override
  Widget build(BuildContext context) {
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
          data: (state) {
            final order = state.order;
            if (!isTraveler && order != null && order.status.isSettled) {
              return _SettledResult(
                order: order,
                dealId: order.dealId ?? dealId,
                requestId: deal.deliveryRequestId,
                justPaid: _sawOutstanding,
              );
            }
            if (!isTraveler && order != null) _sawOutstanding = true;
            final showsResult = !isTraveler && _checkoutShowsResult;
            return ListView(
              padding: AppScrollPadding.page(context),
              children: [
                // The summary steps aside while a result shows, but its slot
                // stays: shifting the checkout to another index would rebuild
                // it and lose the payment it is waiting on.
                if (showsResult)
                  const SizedBox.shrink()
                else
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpace.xl),
                    child: _Summary(state: state, isTraveler: isTraveler),
                  ),

                if (isTraveler)
                  _TravelerView(state: state)
                else
                  _SenderView(
                    state: state,
                    dealId: dealId,
                    onPhaseChanged: _onCheckoutPhase,
                    onSettled: () {
                      ref.invalidate(_dealPaymentProvider(key));
                      refreshVolatileState(ref);
                    },
                  ),
              ],
            );
          },
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
                  label: l.moneyBoostFee,
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

/// The page once the server reports the balance paid.
class _SettledResult extends ConsumerWidget {
  const _SettledResult({
    required this.order,
    required this.dealId,
    required this.requestId,
    required this.justPaid,
  });

  final PaymentOrder order;

  /// The order's own Deal. A result never manufactures one.
  final int dealId;

  final int? requestId;
  final bool justPaid;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    // The parcel's route is its request's two canonical places (J7B), shown
    // only when both are recorded. Nothing is assembled from other data.
    final request = requestId == null
        ? null
        : ref.watch(requestDetailProvider(requestId!)).asData?.value;
    final route = request != null && requestHasRoute(request)
        ? [
            InlineRouteStop(label: requestPickupLabel(l, request)),
            InlineRouteStop(label: requestDeliveryLabel(l, request)),
          ]
        : null;
    return ListView(
      padding: AppScrollPadding.page(context),
      children: [
        PaymentResultView(
          content: settledPaymentResult(
            l: l,
            locale: locale,
            order: order,
            justPaid: justPaid,
          ),
          routeStops: route,
          primary: PaymentResultAction(
            label: l.paymentSuccessViewDeliveryAction,
            icon: Icons.arrow_forward_rounded,
            onPressed: () => context.leavePaymentForDeal(dealId),
          ),
        ),
      ],
    );
  }
}

class _SenderView extends StatelessWidget {
  const _SenderView({
    required this.state,
    required this.dealId,
    required this.onSettled,
    required this.onPhaseChanged,
  });

  final DealPaymentState state;
  final int dealId;
  final VoidCallback onSettled;
  final ValueChanged<CheckoutPhase> onPhaseChanged;

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

    return CheckoutSection(
      key: ValueKey(order.publicReference),
      orderReference: order.publicReference,
      order: order,
      onSettled: onSettled,
      onPhaseChanged: onPhaseChanged,
      exitAction: PaymentResultAction(
        label: l.paymentSuccessViewDeliveryAction,
        onPressed: () => context.leavePaymentForDeal(order.dealId ?? dealId),
      ),
    );
  }
}
