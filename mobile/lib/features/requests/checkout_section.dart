/// Paying one payment order.
///
/// Extracted rather than repeated because every paying surface in the product
/// — the posting deposit, a boost, the deal balance — is the same three
/// moments: choose a rail, leave for a hosted page, and then *wait to be told*
/// what happened. The screens around it differ; this part must not.
///
/// The one rule that shapes the whole file: **coming back from a provider is
/// not a payment.** The redirect carries no proof, the query string is not
/// consulted, and nothing here marks anything paid. After the browser opens,
/// this widget polls `GET /api/payments/orders/<ref>` until the server's own
/// `status` settles or the newest attempt dies. Two minutes of that is enough
/// for a webhook; past it the user is offered a manual check rather than a
/// spinner that never ends.
///
/// Two smaller decisions worth stating:
///
/// * No amount, currency or rate is ever sent to `checkout`. The server
///   rejects the entire request with `client_supplied_amount_rejected` if any
///   of them appear, and rightly so — the price is not the client's to state.
/// * An attempt that is still in flight is offered for *resumption*, not
///   replaced. Starting a second checkout while the first is open is how a
///   nervous user pays twice.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/money/money.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';
import '../guest/guest_payment_sheet.dart';

/// Where the user is in the payment, from this widget's point of view.
///
/// Note that only [_Phase.settled] is a claim about money, and it is only ever
/// reached by reading the order back from the server.
enum _Phase { choosing, confirming, settled, failed }

class CheckoutSection extends ConsumerStatefulWidget {
  const CheckoutSection({
    required this.orderReference,
    required this.order,
    required this.onSettled,
    super.key,
  });

  /// The order's public reference. The only identifier the payment endpoints
  /// take.
  final String orderReference;

  /// The order as the surrounding screen last read it. Null is legitimate:
  /// a boost purchase hands over a reference before anyone has fetched the
  /// order behind it.
  final PaymentOrder? order;

  /// Called once, when the server reports the order paid. The parent decides
  /// what that means — publish the request, activate the boost, fund the deal.
  final VoidCallback onSettled;

  @override
  ConsumerState<CheckoutSection> createState() => _CheckoutSectionState();
}

class _CheckoutSectionState extends ConsumerState<CheckoutSection>
    with WidgetsBindingObserver {
  /// Frequent enough to feel immediate, slow enough that two minutes of it is
  /// forty requests rather than four hundred.
  static const _pollInterval = Duration(seconds: 3);

  /// After this the poll stops on its own. A webhook that has not landed in
  /// two minutes is not going to land in the next three, and an endless
  /// spinner is worse than an honest "check again".
  static const _pollBudget = Duration(minutes: 2);

  Timer? _poll;
  DateTime? _confirmingSince;
  bool _pollExhausted = false;

  _Phase _phase = _Phase.choosing;
  PaymentOrder? _order;
  PaymentProviderId? _selected;
  PaymentProviderId? _busyProvider;
  bool _checkingManually = false;

  /// A failure that belongs on this section rather than in a snackbar: the
  /// user is mid-payment and needs the reason to stay on screen.
  _CheckoutNotice? _notice;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _order = widget.order;
    if (_order?.status.isSettled ?? false) _phase = _Phase.settled;
    if (_order == null) {
      // A surface that hands over a reference before anyone has read the
      // order behind it — a boost purchase. Read it once, so its rails arrive
      // with the amount each one would charge instead of falling back to the
      // amount-less catalogue. The payer of a boost is owed the same figure as
      // the payer of a deposit.
      unawaited(_readOrder());
    }
  }

  @override
  void didUpdateWidget(CheckoutSection oldWidget) {
    super.didUpdateWidget(oldWidget);
    // The parent re-read the order. Adopt it unless we are mid-poll, where our
    // own copy is the fresher of the two.
    if (widget.order != null && _phase != _Phase.confirming) {
      _order = widget.order;
    }
    if (widget.orderReference != oldWidget.orderReference) {
      _stopPolling();
      setState(() {
        _order = widget.order;
        _phase = _Phase.choosing;
        _notice = null;
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _poll?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Returning from the browser is the single most likely moment for the
    // answer to have arrived. Ask straight away rather than waiting out the
    // rest of the interval.
    if (state == AppLifecycleState.resumed && _phase == _Phase.confirming) {
      unawaited(_readOrder());
    }
  }

  // -------------------------------------------------------------------------
  // Polling
  // -------------------------------------------------------------------------

  void _startConfirming() {
    _poll?.cancel();
    setState(() {
      _phase = _Phase.confirming;
      _pollExhausted = false;
      _confirmingSince = DateTime.now();
      _notice = null;
    });
    _poll = Timer.periodic(_pollInterval, (_) {
      final since = _confirmingSince;
      if (since != null && DateTime.now().difference(since) >= _pollBudget) {
        _stopPolling();
        if (mounted) setState(() => _pollExhausted = true);
        return;
      }
      unawaited(_readOrder());
    });
  }

  void _stopPolling() {
    _poll?.cancel();
    _poll = null;
  }

  Future<void> _readOrder() async {
    try {
      final order = await ref
          .read(paymentRepositoryProvider)
          .order(widget.orderReference);
      if (!mounted) return;

      setState(() => _order = order);

      if (order.status.isSettled) {
        _stopPolling();
        setState(() => _phase = _Phase.settled);
        widget.onSettled();
        return;
      }
      if (order.lastAttemptFailed) {
        _stopPolling();
        setState(() => _phase = _Phase.failed);
      }
    } on ApiException {
      // A failed poll says nothing about the payment. Keep waiting; the
      // budget will end this if the network really is gone.
    }
  }

  Future<void> _checkNow() async {
    setState(() => _checkingManually = true);
    await _readOrder();
    if (!mounted) return;
    setState(() {
      _checkingManually = false;
      // Give the automatic poll another budget, since the user has told us
      // they are still waiting.
      if (_phase == _Phase.confirming) _startConfirming();
    });
  }

  // -------------------------------------------------------------------------
  // Checkout
  // -------------------------------------------------------------------------

  Future<void> _checkout(PaymentProviderId provider) async {
    setState(() {
      _busyProvider = provider;
      _notice = null;
    });
    try {
      // Deliberately no amount, no currency, no rate: the server owns all
      // three and refuses the request outright if the client states them.
      final attempt = await ref
          .read(paymentRepositoryProvider)
          .checkout(reference: widget.orderReference, provider: provider);
      if (!mounted) return;
      await _open(attempt.checkoutUrl);
    } on ApiException catch (error) {
      if (!mounted) return;
      _handleCheckoutFailure(error);
    } finally {
      if (mounted) setState(() => _busyProvider = null);
    }
  }

  Future<void> _resume(PaymentAttempt attempt) async {
    setState(() {
      _busyProvider = attempt.provider;
      _notice = null;
    });
    await _open(attempt.checkoutUrl);
    if (mounted) setState(() => _busyProvider = null);
  }

  Future<void> _open(String? checkoutUrl) async {
    final uri = checkoutUrl == null ? null : Uri.tryParse(checkoutUrl);
    if (uri == null) {
      setState(
        () => _notice = _CheckoutNotice(
          body: L.of(context).paymentCouldNotOpen,
          tone: StatusTone.bad,
        ),
      );
      return;
    }

    // External application only. An in-app webview around a card form is a
    // worse trust signal and drags us into PCI scope for nothing.
    final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!mounted) return;

    if (!opened) {
      setState(
        () => _notice = _CheckoutNotice(
          body: L.of(context).paymentCouldNotOpen,
          tone: StatusTone.bad,
        ),
      );
      return;
    }
    _startConfirming();
  }

  void _handleCheckoutFailure(ApiException error) {
    final l = L.of(context);

    final notice = switch (error.code) {
      ApiErrorCode.providerDisabled => _CheckoutNotice(
        title: l.paymentProviderDisabled,
        body: l.paymentProviderPickAnother,
        tone: StatusTone.waiting,
      ),
      ApiErrorCode.providerNewCheckoutsDisabled => _CheckoutNotice(
        title: l.paymentProviderNewCheckoutsDisabled,
        body: l.paymentProviderPickAnother,
        tone: StatusTone.waiting,
      ),
      ApiErrorCode.providerNotConfigured => _CheckoutNotice(
        title: l.paymentProviderNotConfigured,
        body: l.paymentProviderPickAnother,
        tone: StatusTone.waiting,
      ),
      // Credentials exist and the server will not transact against them. The
      // payer can do nothing about it, so the copy must not imply they can:
      // this is not "try again", it is "use the other method".
      ApiErrorCode.providerConfigurationInvalid => _CheckoutNotice(
        title: l.paymentProviderConfigurationInvalid,
        body: l.paymentProviderPickAnother,
        tone: StatusTone.waiting,
      ),
      // A definite refusal from the provider. Distinct from "unavailable",
      // which invites a retry that would fail the same way.
      ApiErrorCode.providerCheckoutFailed => _CheckoutNotice(
        title: l.paymentCheckoutFailedTitle,
        body: l.paymentCheckoutFailedBody,
        tone: StatusTone.bad,
      ),
      ApiErrorCode.providerUnavailable => _CheckoutNotice(
        title: l.paymentProviderUnavailable,
        body: l.paymentNoProvidersBody,
        tone: StatusTone.waiting,
      ),
      ApiErrorCode.orderNotCollectable => _CheckoutNotice(
        title: l.paymentOrderClosedTitle,
        body: l.paymentOrderClosedBody,
        tone: StatusTone.neutral,
      ),
      ApiErrorCode.nothingOutstanding => _CheckoutNotice(
        title: l.paymentNothingOutstandingTitle,
        body: l.paymentNothingOutstandingBody,
        tone: StatusTone.good,
      ),
      _ => null,
    };

    if (notice == null) {
      AppSnack.failure(context, error);
      return;
    }

    setState(() => _notice = notice);

    // "Nothing outstanding" and "not collectable" both mean this widget is
    // looking at an order that has moved. Re-read it so the surrounding screen
    // stops offering a payment that cannot happen.
    if (error.code == ApiErrorCode.nothingOutstanding ||
        error.code == ApiErrorCode.orderNotCollectable) {
      unawaited(_readOrder());
    }
    if (error.code.isProviderUnavailable) {
      ref.invalidate(paymentProvidersProvider);
    }
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final order = _order;

    return switch (_phase) {
      _Phase.settled => const _SettledBlock(),
      _Phase.confirming => _ConfirmingBlock(
        exhausted: _pollExhausted,
        isChecking: _checkingManually,
        onCheck: _checkNow,
      ),
      _Phase.failed => _FailedBlock(
        onRetry: () => setState(() {
          _phase = _Phase.choosing;
          _notice = null;
        }),
      ),
      _Phase.choosing => _buildChooser(context, order),
    };
  }

  Widget _buildChooser(BuildContext context, PaymentOrder? order) {
    final l = L.of(context);
    final providers = ref.watch(paymentProvidersProvider);

    final resumable = order?.latestAttempt;
    if (resumable != null && resumable.canResume) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_notice != null) ...[
            _notice!.build(context),
            const SizedBox(height: AppSpace.lg),
          ],
          InfoNotice(
            title: l.paymentContinueTitle,
            message: l.paymentContinueBody,
            tone: StatusTone.waiting,
            icon: Icons.open_in_new_rounded,
          ),
          const SizedBox(height: AppSpace.lg),
          AppButton(
            label: l.paymentContinueAction,
            icon: Icons.open_in_new_rounded,
            isLoading: _busyProvider != null,
            onPressed: () => _resume(resumable),
          ),
          const SizedBox(height: AppSpace.sm),
          AppButton(
            label: l.paymentCheckAgain,
            variant: AppButtonVariant.tertiary,
            isLoading: _checkingManually,
            onPressed: _checkNow,
          ),
        ],
      );
    }

    return AsyncView<ProvidersView>(
      value: providers,
      onRetry: () => ref.invalidate(paymentProvidersProvider),
      loading: () => const SkeletonLines(count: 4),
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(paymentProvidersProvider),
      ),
      data: (view) => _providerList(context, view, order),
    );
  }

  Widget _providerList(
    BuildContext context,
    ProvidersView view,
    PaymentOrder? order,
  ) {
    final l = L.of(context);

    // **The order's own rail list wins.** `GET /api/payments/providers` has no
    // obligation in hand, so its rows carry a settlement currency and no
    // amount; the order's rows carry what each rail would charge for *this*
    // obligation. Rendering the amount-less list would put the rails back to
    // being indistinguishable except by a subtitle, which is the whole defect
    // this screen is being repaired for. The standalone list remains the
    // fallback for a surface that has no order yet — a boost, before its
    // obligation has been read back.
    final source = (order?.providers.isNotEmpty ?? false)
        ? order!.providers
        : view.providers;

    // `mock` is already stripped by the model; `unknown` is a rail this build
    // does not know how to name, and an unnamed payment button is not one we
    // are willing to show.
    final options = source
        .where((p) => p.provider != PaymentProviderId.unknown)
        .toList(growable: false);

    if (options.where((p) => p.available).isEmpty) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_notice != null) ...[
            _notice!.build(context),
            const SizedBox(height: AppSpace.lg),
          ],
          AppEmptyState(
            title: l.paymentNoProvidersTitle,
            body: l.paymentNoProvidersBody,
            icon: Icons.credit_card_off_rounded,
            compact: true,
            actionLabel: l.actionRefresh,
            onAction: () => ref.invalidate(paymentProvidersProvider),
          ),
        ],
      );
    }

    final locale = Localizations.localeOf(context);
    // Selection is resolved against the rails that are usable *now*. A rail
    // chosen a moment ago can have become unavailable — a failed checkout
    // re-reads the list — and keeping that stale choice would put an amount on
    // the button for a rail the server has already refused, then fail at the
    // tap. There is at least one usable rail here: the empty state above
    // returns before this point when there is not.
    final usable = options.where((p) => p.available).toList(growable: false);
    final chosen = usable.firstWhere(
      (p) => p.provider == _selected,
      orElse: () => usable.first,
    );
    final selected = chosen.provider;

    // What *this* rail will take, in the currency it settles in. Never the
    // order's euro figure dressed up as the selected rail's charge: a "Pay
    // €37.50" button under a rail that debits dinars is exactly the confusion
    // this screen is being repaired for.
    final railCharge = chosen.settlementAmount;

    // The euro obligation next to a dinar charge, from the server's frozen
    // quote. Absent on a euro rail, where the two numbers are the same one.
    final quote = order?.chargilyQuote;
    final showsConversion =
        chosen.chargesForeignCurrency &&
        quote?.canonicalAmount != null &&
        quote?.paymentAmount != null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_notice != null) ...[
          _notice!.build(context),
          const SizedBox(height: AppSpace.lg),
        ],
        SectionHeader(title: l.paymentChooseProvider),
        for (final option in options) ...[
          _ProviderTile(
            option: option,
            isSelected: option.provider == selected,
            onSelect: option.available
                ? () => setState(() => _selected = option.provider)
                : null,
          ),
          const SizedBox(height: AppSpace.md),
        ],

        if (showsConversion) ...[
          const SizedBox(height: AppSpace.sm),
          ProviderConversion(
            canonical: quote!.canonicalAmount!,
            charged: quote.paymentAmount!,
            canonicalLabel: l.moneyYouPay,
            chargedLabel: l.moneyAmountCharged,
            // The rate is the server's own six-decimal string. Reformatting it
            // here would be inventing a number the server did not publish.
            rateLabel: l.moneyExchangeRate(quote.eurDzdRate),
            footnote: l.moneyChargedInDinars,
          ),
          const SizedBox(height: AppSpace.lg),
        ],

        const SizedBox(height: AppSpace.sm),
        AppButton(
          // The rail is named on the button, and so is the amount that rail
          // will actually charge. There is no currency for the payer to pick:
          // Stripe settles in euros and Chargily in dinars, the server decides
          // both, and the pairing is not the client's to invent.
          label: railCharge == null
              ? l.actionContinue
              : l.paymentPayWith(
                  railCharge.format(locale),
                  _providerName(l, chosen.provider),
                ),
          icon: Icons.lock_rounded,
          isLoading: _busyProvider != null,
          semanticHint: l.paymentOpeningProvider,
          onPressed: () => _checkout(selected),
        ),
        if (order != null &&
            order.status.isCollectable &&
            chosen.supportsGuestPayment) ...[
          const SizedBox(height: AppSpace.sm),
          Center(
            child: AppButton(
              label: l.guestPaymentTitle,
              icon: Icons.share_outlined,
              variant: AppButtonVariant.tertiary,
              onPressed: () => GuestPaymentSheet.show(
                context,
                order: order,
                onSettled: widget.onSettled,
              ),
            ),
          ),
        ],
        const SizedBox(height: AppSpace.md),
        Text(
          l.paymentRedirectNotProof,
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: context.colors.textTertiary),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

@immutable
class _CheckoutNotice {
  const _CheckoutNotice({required this.body, required this.tone, this.title});

  final String? title;
  final String body;
  final StatusTone tone;

  Widget build(BuildContext context) => InfoNotice(
    title: title,
    message: body,
    tone: tone,
    icon: tone == StatusTone.good
        ? Icons.check_circle_outline_rounded
        : Icons.error_outline_rounded,
  );
}

/// The display name of a rail.
///
/// Providers are named, not described by payment type. Two rows reading "Card"
/// and "Chargily" invite exactly one misreading — that the first is a method
/// and the second a currency — and that misreading is what put a dinar figure
/// on a screen whose selected rail settles in euros.
String _providerName(L l, PaymentProviderId provider) => switch (provider) {
  PaymentProviderId.stripe => l.paymentProviderStripe,
  PaymentProviderId.chargily => l.paymentProviderChargily,
  PaymentProviderId.mock || PaymentProviderId.unknown => l.stateUnexpectedTitle,
};

/// One payment rail, showing what that rail will charge.
///
/// The amount is the point. A rail with no figure of its own reads as a way of
/// paying one screen-level price, so a payer has no way to see that choosing
/// the other row changes the currency leaving their account. Every figure here
/// is the server's; nothing on this tile is derived, converted or rounded.
class _ProviderTile extends StatelessWidget {
  const _ProviderTile({
    required this.option,
    required this.isSelected,
    required this.onSelect,
  });

  final ProviderOption option;
  final bool isSelected;

  /// Null for a rail that cannot be used right now. The tile still renders,
  /// with the reason — a payment method that silently vanishes reads as a bug.
  final VoidCallback? onSelect;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final enabled = onSelect != null;

    final name = _providerName(l, option.provider);
    final charge = enabled ? option.settlementAmount : null;

    final subtitle = enabled
        ? switch (option.provider) {
            PaymentProviderId.stripe => l.paymentProviderStripeSubtitle,
            PaymentProviderId.chargily => l.paymentProviderChargilySubtitle,
            PaymentProviderId.mock ||
            PaymentProviderId.unknown => l.stateUnexpectedBody,
          }
        : _reasonCopy(l, option.unavailableReason);

    // A dinar rail states the euro obligation it stands for and the rate that
    // produced it. A euro rail says nothing extra: its charge and the
    // obligation are one number, and repeating it would imply they might not
    // be.
    final rate = option.eurDzdRate;
    final equivalence = <String>[
      if (option.showsCanonicalEquivalent)
        l.paymentRailEquivalent(option.canonicalAmount!.format(locale)),
      if (rate != null && rate.isNotEmpty) l.paymentRailRate(rate),
    ].join(' · ');

    return Semantics(
      button: true,
      enabled: enabled,
      selected: isSelected,
      label: charge == null
          ? name
          : l.a11yPaymentRailCharge(name, charge.format(locale)),
      hint: equivalence.isEmpty ? subtitle : '$subtitle. $equivalence',
      onTap: enabled ? onSelect : null,
      child: ExcludeSemantics(
        child: AppCard(
          onTap: onSelect,
          accent: isSelected && enabled ? StatusTone.progress : null,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Icon(
                  option.provider == PaymentProviderId.chargily
                      ? Icons.account_balance_rounded
                      : Icons.credit_card_rounded,
                  size: 22,
                  color: enabled ? c.textSecondary : c.textTertiary,
                ),
              ),
              const SizedBox(width: AppSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.baseline,
                      textBaseline: TextBaseline.alphabetic,
                      children: [
                        Expanded(
                          child: Text(
                            name,
                            style: text.titleSmall?.copyWith(
                              color: enabled ? c.textPrimary : c.textTertiary,
                            ),
                          ),
                        ),
                        if (charge != null) ...[
                          const SizedBox(width: AppSpace.sm),
                          MoneyText(
                            charge,
                            style: text.titleSmall?.copyWith(
                              color: c.textPrimary,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: AppSpace.xxs),
                    Text(
                      subtitle,
                      style: text.bodySmall?.copyWith(
                        color: enabled ? c.textSecondary : c.textTertiary,
                      ),
                    ),
                    if (enabled && equivalence.isNotEmpty) ...[
                      const SizedBox(height: AppSpace.xxs),
                      Text(
                        equivalence,
                        style: text.bodySmall?.copyWith(color: c.textTertiary),
                      ),
                    ],
                    if (enabled && option.rateIsIndicative) ...[
                      const SizedBox(height: AppSpace.xxs),
                      Text(
                        l.paymentRailRateLocked,
                        style: text.labelSmall?.copyWith(color: c.textTertiary),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: AppSpace.md),
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: enabled
                    ? Icon(
                        isSelected
                            ? Icons.radio_button_checked_rounded
                            : Icons.radio_button_unchecked_rounded,
                        size: 21,
                        color: isSelected ? c.brand : c.hairlineStrong,
                      )
                    : Icon(
                        Icons.block_rounded,
                        size: 19,
                        color: c.textTertiary,
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// `unavailable_reason` is a machine token, not a sentence. It is mapped,
  /// never rendered.
  static String _reasonCopy(L l, String reason) => switch (reason) {
    'provider_not_configured' => l.paymentProviderNotConfigured,
    'disabled_by_policy' => l.paymentProviderDisabled,
    'new_checkouts_disabled' => l.paymentProviderNewCheckoutsDisabled,
    // A rail the operator switched on whose configuration the server will not
    // transact against. Deliberately not "switched off": nobody switched it
    // off, and saying so would send anyone chasing it to the wrong control.
    'provider_configuration_invalid' => l.paymentProviderConfigurationInvalid,
    'amount_below_provider_minimum' => l.paymentProviderAmountTooSmall,
    _ => l.paymentProviderUnavailable,
  };
}

class _ConfirmingBlock extends StatelessWidget {
  const _ConfirmingBlock({
    required this.exhausted,
    required this.isChecking,
    required this.onCheck,
  });

  final bool exhausted;
  final bool isChecking;
  final VoidCallback onCheck;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InfoNotice(
          title: exhausted
              ? l.paymentStillConfirmingTitle
              : l.paymentConfirmingTitle,
          message: exhausted
              ? l.paymentStillConfirmingBody
              : l.paymentConfirmingBody,
          tone: StatusTone.waiting,
          icon: Icons.hourglass_top_rounded,
        ),
        const SizedBox(height: AppSpace.lg),
        if (!exhausted)
          Row(
            children: [
              SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2.2,
                  valueColor: AlwaysStoppedAnimation(c.brand),
                ),
              ),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: Text(
                  l.paymentRedirectNotProof,
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: c.textSecondary),
                ),
              ),
            ],
          )
        else
          AppButton(
            label: l.paymentCheckAgain,
            icon: Icons.refresh_rounded,
            variant: AppButtonVariant.secondary,
            isLoading: isChecking,
            onPressed: onCheck,
          ),
      ],
    );
  }
}

class _SettledBlock extends StatelessWidget {
  const _SettledBlock();

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return InfoNotice(
      title: l.paymentSucceededTitle,
      message: l.paymentSucceededBody,
      tone: StatusTone.good,
      icon: Icons.check_circle_outline_rounded,
    );
  }
}

class _FailedBlock extends StatelessWidget {
  const _FailedBlock({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InfoNotice(
          title: l.paymentFailedTitle,
          message: l.paymentFailedBody,
          tone: StatusTone.bad,
          icon: Icons.credit_card_off_rounded,
        ),
        const SizedBox(height: AppSpace.lg),
        AppButton(
          label: l.actionRetry,
          icon: Icons.refresh_rounded,
          variant: AppButtonVariant.secondary,
          onPressed: onRetry,
        ),
      ],
    );
  }
}

/// The euro amount as plain digits for an [AppAmountField].
///
/// Not [Money.format]: that inserts a currency symbol and locale grouping
/// separators, and a grouped `1,234.50` is unparseable by the same field's
/// own reader. This is a unit conversion on an integer, the exact inverse of
/// `AppAmountField.centsOf`, and it is not arithmetic on a price.
String amountFieldText(Money amount) {
  if (amount.exponent != 2) return '${amount.minorUnits}';
  final units = amount.minorUnits ~/ 100;
  final cents = (amount.minorUnits % 100).toString().padLeft(2, '0');
  return '$units.$cents';
}
