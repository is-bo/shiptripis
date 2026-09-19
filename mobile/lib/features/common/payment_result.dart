/// Every payment result in the app, in one visual system (J7D).
///
/// A deposit that just published a request, a Deal balance paid in full, a
/// payment someone else made, a return from the provider that has not been
/// confirmed yet, a declined card, an abandoned checkout, a payment opened long
/// after it was settled — each used to be a generic receipt or a one-line
/// notice. They are now one layout with different words:
///
/// ```
///            (seal ✓)                ← mark: seal / checking / failed / cancelled
///   REMAINING DELIVERY PAYMENT       ← purpose, terracotta eyebrow
///        Payment received            ← one heading, Fraunces
///            €30.00                  ← what was just paid, Fraunces hero
///         Jijel → Paris              ← only from the request's own route
///  Someone else paid €30.00 for …    ← only when they did
///  ┌──────────────────────────────┐
///  │ ✓ Payment protected           │ ← the outcome, in words
///  │ Paid now              €30.00  │
///  │ Deposit already paid  −€12.00 │
///  │ Delivery total        €42.00  │
///  │ [PAID IN FULL]                │ ← a stamp, never "Remaining €0.00"
///  └──────────────────────────────┘
///  WHAT HAPPENS NEXT
///  Funds are held pending delivery…
///  [ View delivery ]                  ← where the server's state says to go
/// ```
///
/// **Nothing here is a claim the server has not made.** A settled result is
/// only ever built from an order whose status is `paid`; every figure is a
/// server field rendered as it stands; "paid in full" is the server's
/// remaining balance being zero, not arithmetic; "someone else paid" is the
/// server's `last_paid_by`, never a name. The checking state has no seal and
/// no tick, because nothing has been confirmed.
library;

import 'package:flutter/material.dart';

import '../../core/money/money.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/identity.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';

/// Which outcome a result screen is describing.
enum PaymentResultKind {
  /// The server settled the obligation while the payer was here.
  received,

  /// The obligation was already settled when the payer arrived.
  alreadyComplete,

  /// Back from the provider; the server has not said yet.
  checking,

  /// Still not said, past the automatic re-check budget.
  stillChecking,

  /// The provider reported the payment failed.
  failed,

  /// The checkout was abandoned or expired. Not a failure.
  cancelled;

  bool get isSettled => this == received || this == alreadyComplete;
}

/// One figure in the result's ledger.
@immutable
class PaymentResultLine {
  const PaymentResultLine({
    required this.label,
    required this.amount,
    this.isCredit = false,
    this.isEmphasised = false,
  });

  final String label;
  final Money amount;

  /// Money that reduced what was owed (a credited deposit): shown with a minus
  /// sign so it can never read as a second charge.
  final bool isCredit;

  final bool isEmphasised;
}

/// A button on a result.
@immutable
class PaymentResultAction {
  const PaymentResultAction({
    required this.label,
    required this.onPressed,
    this.icon,
  });

  final String label;
  final VoidCallback onPressed;
  final IconData? icon;
}

/// The words and figures of one result. Built by [settledPaymentResult] (and
/// by the checkout for its in-flight states); rendered by [PaymentResultView].
@immutable
class PaymentResultContent {
  const PaymentResultContent({
    required this.kind,
    required this.title,
    this.eyebrow,
    this.amount,
    this.amountLabel,
    this.lead,
    this.outcome,
    this.lines = const [],
    this.paidInFull = false,
    this.ledgerNote,
    this.nextStep,
  });

  final PaymentResultKind kind;
  final String title;

  /// What the payment was for, in words.
  final String? eyebrow;

  /// The hero figure: what was just paid.
  final Money? amount;

  /// How a screen reader names [amount] ("Amount paid").
  final String? amountLabel;

  /// One supporting sentence under the heading.
  final String? lead;

  /// The payment's effect, stated as a fact ("Your request is now published").
  final String? outcome;

  final List<PaymentResultLine> lines;

  /// The server's remaining balance is zero. Rendered as a stamp.
  final bool paidInFull;

  final String? ledgerNote;

  /// What the payer does next, under "What happens next".
  final String? nextStep;
}

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------

/// What a result screen calls a payment, from the server's purpose and its own
/// figures. A Deal balance with a credited deposit, or one that has taken more
/// than one payment, is the *remaining* delivery payment. Reuses the J7C words.
String paymentResultPurposeLabel(L l, PaymentOrder order) {
  switch (order.purpose) {
    case PaymentPurpose.postingDeposit:
      return l.guestPurposeDeposit;
    case PaymentPurpose.boost:
      return l.guestPurposeBoost;
    case PaymentPurpose.unknown:
      return l.guestPurposeOther;
    case PaymentPurpose.dealBalance:
      final applied = order.attempts
          .where((a) => a.status == PaymentAttemptStatus.succeeded)
          .length;
      return order.hasCredit || applied > 1
          ? l.guestPurposeRemaining
          : l.guestPurposeDelivery;
  }
}

/// [amount] formatted for use inside a sentence. In Arabic the figure is
/// wrapped in a left-to-right isolate, so "30,00 €" is not reordered into
/// "€ 30,00" by the surrounding right-to-left text (found on a rendered screen,
/// J7D); elsewhere it is unchanged.
///
/// In J7E, [Money.format] performs this formatting universally; this helper
/// delegates directly to it.
String paymentResultFigure(Money amount, Locale locale) =>
    amount.format(locale);

/// The payment that just settled, as the server reports it.
///
/// Prefers the settlement block's `last_payment_eur_cents` (J7D); falls back
/// to the newest succeeded attempt, then to the cumulative figure, so an older
/// server still produces a truthful — if less specific — amount.
Money? lastPaymentOf(PaymentOrder order) {
  final settlement = order.settlement;
  if (settlement?.lastPayment != null) return settlement!.lastPayment;
  for (final attempt in order.attempts) {
    if (attempt.status == PaymentAttemptStatus.succeeded &&
        attempt.amount != null) {
      return attempt.amount;
    }
  }
  return settlement?.paid ?? order.paid;
}

/// Whether someone other than the Sender made the payment that just settled.
bool lastPaidByGuest(PaymentOrder order) {
  final settlement = order.settlement;
  final who = settlement?.lastPaidBy ?? settlement?.paidBy;
  if (who != null) return who == 'guest';
  for (final attempt in order.attempts) {
    if (attempt.status == PaymentAttemptStatus.succeeded) {
      return attempt.isGuestPayment;
    }
  }
  return false;
}

/// The result for an order the server reports settled.
///
/// [justPaid] distinguishes "Payment received" (the payer watched it settle)
/// from "This payment is already complete" (it was settled when they came).
/// A deposit passes [requestPublished] from the request's own status and
/// [currentObligation] from the deposit quote's live `maximum`; a Deal passes
/// neither.
PaymentResultContent settledPaymentResult({
  required L l,
  required Locale locale,
  required PaymentOrder order,
  required bool justPaid,
  bool requestPublished = false,
  Money? currentObligation,
}) {
  final settlement = order.settlement;
  final paidNow = lastPaymentOf(order);
  final guest = lastPaidByGuest(order);
  final remaining = settlement?.remaining ?? order.outstanding;
  final credit = order.depositCredit ?? settlement?.depositCredited;
  final total = order.amount ?? settlement?.amount;
  final isDeposit = order.purpose == PaymentPurpose.postingDeposit;
  final hasRemaining = remaining != null && remaining.isPositive;

  final kind = justPaid
      ? PaymentResultKind.received
      : PaymentResultKind.alreadyComplete;
  final lead = guest && paidNow != null && paidNow.isPositive
      ? l.payResultSomeoneElsePaid(paymentResultFigure(paidNow, locale))
      : null;

  if (isDeposit) {
    // Paid in full at posting: the deposit is at least the whole obligation
    // *as it stands now*. Both figures are the server's; comparing them is not
    // computing a price. The note refuses to promise that nothing can ever be
    // due again — a later Boost or reward change can still create a balance.
    final coversTotal =
        currentObligation != null &&
        order.amount != null &&
        currentObligation.currency == order.amount!.currency &&
        order.amount!.compareTo(currentObligation) >= 0;
    return PaymentResultContent(
      kind: kind,
      title: justPaid ? l.guestPaidTitle : l.payResultAlreadyCompleteTitle,
      eyebrow: paymentResultPurposeLabel(l, order),
      amount: paidNow,
      amountLabel: l.paymentSuccessAmountPaid,
      lead: lead,
      outcome: requestPublished ? l.payResultRequestPublished : null,
      paidInFull: coversTotal,
      ledgerNote: coversTotal
          ? l.payResultDepositCoversTotal
          : l.payResultDepositCredited,
      nextStep: requestPublished ? l.payResultDepositNext : null,
    );
  }

  // A Deal balance (or any other obligation on a Deal).
  // Read top to bottom like a receipt: the total, what the deposit already
  // covered, what was paid now, and anything still owed.
  final lines = <PaymentResultLine>[
    if (total != null && ((credit?.isPositive ?? false) || hasRemaining))
      PaymentResultLine(label: l.payResultDeliveryTotal, amount: total),
    if (credit != null && credit.isPositive)
      PaymentResultLine(
        label: l.moneyDepositPaid,
        amount: credit,
        isCredit: true,
      ),
    if (paidNow != null && (hasRemaining || (credit?.isPositive ?? false)))
      PaymentResultLine(label: l.payResultPaidNow, amount: paidNow),
    if (hasRemaining)
      PaymentResultLine(
        label: l.payResultRemaining,
        amount: remaining,
        isEmphasised: true,
      ),
  ];
  return PaymentResultContent(
    kind: kind,
    title: justPaid ? l.guestPaidTitle : l.payResultAlreadyCompleteTitle,
    eyebrow: paymentResultPurposeLabel(l, order),
    amount: paidNow,
    amountLabel: l.paymentSuccessAmountPaid,
    lead: lead,
    outcome: order.status.isSettled && !hasRemaining ? l.protectionTitle : null,
    lines: lines,
    // `paid` is the server saying the whole obligation is covered; a balance
    // with anything left is `partially_paid`. No subtraction here.
    paidInFull: order.status.isSettled && !hasRemaining,
    ledgerNote: hasRemaining
        ? l.payResultRemainingNote(paymentResultFigure(remaining, locale))
        : null,
    nextStep: hasRemaining ? null : l.payResultDealNext,
  );
}

// ---------------------------------------------------------------------------
// The mark
// ---------------------------------------------------------------------------

/// The one graphic on a result. Decorative: the heading carries the outcome.
///
/// A settled result is pressed into the app's wax seal with a check *icon* —
/// the bundled faces have no check glyph (J7C). Checking gets a quiet ring and
/// never a tick; failed and cancelled get a plain disc, not a red alarm.
class PaymentResultMark extends StatelessWidget {
  const PaymentResultMark({required this.kind, this.size = 64, super.key});

  final PaymentResultKind kind;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final reduceMotion = MediaQuery.maybeDisableAnimationsOf(context) ?? false;

    Widget disc({required Color fill, required Widget child}) => Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: fill, shape: BoxShape.circle),
      alignment: Alignment.center,
      child: child,
    );

    final mark = switch (kind) {
      PaymentResultKind.received || PaymentResultKind.alreadyComplete => Stack(
        alignment: Alignment.center,
        children: [
          WaxSeal(glyph: '', diameter: size),
          Icon(Icons.check_rounded, size: size * 0.48, color: c.surface),
        ],
      ),
      PaymentResultKind.checking => SizedBox(
        width: size,
        height: size,
        child: Stack(
          alignment: Alignment.center,
          children: [
            disc(
              fill: c.surfaceSunken,
              child: Icon(
                Icons.schedule_rounded,
                size: size * 0.4,
                color: c.textSecondary,
              ),
            ),
            SizedBox(
              width: size,
              height: size,
              child: CircularProgressIndicator(
                // A still arc when the system asks for less motion.
                value: reduceMotion ? 0.25 : null,
                strokeWidth: 2.5,
                valueColor: AlwaysStoppedAnimation(c.attentionVivid),
                backgroundColor: c.hairline,
              ),
            ),
          ],
        ),
      ),
      PaymentResultKind.stillChecking => disc(
        fill: c.surfaceSunken,
        child: Icon(
          Icons.schedule_rounded,
          size: size * 0.42,
          color: c.textSecondary,
        ),
      ),
      PaymentResultKind.failed => disc(
        fill: c.dangerSoft,
        child: Icon(
          Icons.credit_card_off_rounded,
          size: size * 0.42,
          color: c.danger,
        ),
      ),
      PaymentResultKind.cancelled => disc(
        fill: c.surfaceSunken,
        child: Icon(
          Icons.remove_rounded,
          size: size * 0.42,
          color: c.textSecondary,
        ),
      ),
    };
    return ExcludeSemantics(child: mark);
  }
}

// ---------------------------------------------------------------------------
// The view
// ---------------------------------------------------------------------------

/// One result, laid out. A column, so the host decides how it scrolls.
class PaymentResultView extends StatelessWidget {
  const PaymentResultView({
    required this.content,
    this.routeStops,
    this.primary,
    this.secondary,
    super.key,
  });

  final PaymentResultContent content;

  /// The request's own route, when the caller has it. Never assembled from
  /// guesses: absent means no route line at all.
  final List<InlineRouteStop>? routeStops;

  final PaymentResultAction? primary;
  final PaymentResultAction? secondary;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final isArabic = Directionality.of(context) == TextDirection.rtl;
    final item = content;
    final amount = item.amount;
    final hasLedger =
        item.outcome != null ||
        item.lines.isNotEmpty ||
        item.paidInFull ||
        item.ledgerNote != null;
    final l = L.of(context);

    // Landscape and small phones: a smaller mark and tighter rhythm, so the
    // heading and the button are not pushed off a 390-point-tall screen.
    final compact = MediaQuery.sizeOf(context).height < 560;

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(height: compact ? AppSpace.xs : AppSpace.lg),
            Center(
              child: PaymentResultMark(
                kind: item.kind,
                size: compact ? 48 : 64,
              ),
            ),
            SizedBox(height: compact ? AppSpace.md : AppSpace.lg),
            if (item.eyebrow != null) ...[
              ExcludeSemantics(
                child: Text(
                  isArabic ? item.eyebrow! : item.eyebrow!.toUpperCase(),
                  textAlign: TextAlign.center,
                  style: AppTypography.eyebrow(
                    context,
                    color: c.onAttentionSoft,
                  ),
                ),
              ),
              const SizedBox(height: AppSpace.xs),
            ],
            // The outcome is the one thing a screen reader must hear, and hear
            // again when a checking screen turns into a result.
            Semantics(
              header: true,
              liveRegion: true,
              child: Text(
                item.title,
                textAlign: TextAlign.center,
                style: text.headlineMedium,
              ),
            ),
            if (amount != null && amount.isPositive) ...[
              const SizedBox(height: AppSpace.sm),
              Semantics(
                // Its own node: the figure is read with what it paid for,
                // not run together with the heading above it.
                container: true,
                label: l.a11yPaymentResultAmount(
                  item.amountLabel ?? '',
                  amount.format(locale),
                  item.eyebrow ?? '',
                ),
                excludeSemantics: true,
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(
                    amount.format(locale),
                    // "30,00 €", never "€ 30,00", inside an Arabic page.
                    textDirection: TextDirection.ltr,
                    maxLines: 1,
                    style: AppTypography.heroMoney(
                      context,
                      color: c.textPrimary,
                    ),
                  ),
                ),
              ),
            ],
            if (routeStops != null && routeStops!.length >= 2) ...[
              const SizedBox(height: AppSpace.xs),
              Center(
                child: InlineRoute(
                  stops: routeStops!,
                  style: text.bodyMedium?.copyWith(
                    color: c.textSecondary,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            ],
            if (item.lead != null) ...[
              const SizedBox(height: AppSpace.sm),
              Text(
                item.lead!,
                textAlign: TextAlign.center,
                style: text.bodyMedium?.copyWith(color: c.textSecondary),
              ),
            ],
            if (hasLedger) ...[
              SizedBox(height: compact ? AppSpace.lg : AppSpace.xl),
              _Ledger(content: item),
            ],
            if (item.nextStep != null) ...[
              const SizedBox(height: AppSpace.lg),
              Semantics(
                container: true,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      isArabic
                          ? l.payResultNextTitle
                          : l.payResultNextTitle.toUpperCase(),
                      style: AppTypography.eyebrow(
                        context,
                        color: c.textTertiary,
                      ),
                    ),
                    const SizedBox(height: AppSpace.xs),
                    Text(
                      item.nextStep!,
                      style: text.bodyMedium?.copyWith(color: c.textSecondary),
                    ),
                  ],
                ),
              ),
            ],
            if (primary != null) ...[
              SizedBox(height: compact ? AppSpace.lg : AppSpace.xl),
              AppButton(
                label: primary!.label,
                icon: primary!.icon,
                onPressed: primary!.onPressed,
              ),
            ],
            if (secondary != null) ...[
              SizedBox(
                height: primary != null
                    ? AppSpace.sm
                    : (compact ? AppSpace.md : AppSpace.lg),
              ),
              AppButton(
                label: secondary!.label,
                icon: secondary!.icon,
                variant: AppButtonVariant.tertiary,
                onPressed: secondary!.onPressed,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// The sunken panel under the heading: the outcome, the figures, the stamp.
class _Ledger extends StatelessWidget {
  const _Ledger({required this.content});

  final PaymentResultContent content;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final l = L.of(context);

    return AppInsetGroup(
      padding: const EdgeInsets.all(AppSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (content.outcome != null)
            Row(
              children: [
                ExcludeSemantics(
                  child: Icon(
                    Icons.verified_outlined,
                    size: 20,
                    color: c.onAttentionSoft,
                  ),
                ),
                const SizedBox(width: AppSpace.sm),
                Expanded(child: Text(content.outcome!, style: text.titleSmall)),
              ],
            ),
          if (content.outcome != null && content.lines.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
              child: Divider(height: 1, color: c.hairline),
            )
          else if (content.outcome != null && content.paidInFull)
            const SizedBox(height: AppSpace.md),
          for (final line in content.lines)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpace.xxs),
              child: Semantics(
                container: true,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Expanded(
                      child: Text(
                        line.label,
                        style: line.isEmphasised
                            ? text.titleSmall
                            : text.bodyMedium?.copyWith(color: c.textSecondary),
                      ),
                    ),
                    const SizedBox(width: AppSpace.md),
                    Text(
                      line.isCredit
                          ? '−${line.amount.format(locale)}'
                          : line.amount.format(locale),
                      textDirection: TextDirection.ltr,
                      style: AppTypography.money(
                        context,
                        color: line.isCredit ? c.success : c.textPrimary,
                        weight: line.isEmphasised ? 700 : 600,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          if (content.paidInFull) ...[
            if (content.lines.isNotEmpty) const SizedBox(height: AppSpace.md),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: Semantics(
                container: true,
                label: l.payResultPaidInFull,
                excludeSemantics: true,
                child: StampChip(
                  label: l.payResultPaidInFull,
                  color: c.onAttentionSoft,
                  icon: Icons.check_rounded,
                ),
              ),
            ),
          ],
          if (content.ledgerNote != null) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              content.ledgerNote!,
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
          ],
        ],
      ),
    );
  }
}
