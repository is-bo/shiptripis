/// "Someone else can pay" — the Sender's side of a guest payment.
///
/// One job: put a secure link to pay *this* obligation into the hands of
/// someone the Sender trusts, and say plainly what state that link is in.
///
/// ## What the sheet reads, and what it never does
///
/// Opening the sheet **reads** the link (`GET .../guest-link`); it never issues
/// one. The server can show the live link again, so the link a relative is
/// already holding keeps working however many times the Sender looks at it.
/// Only two things issue a link: the very first open, when there has never been
/// one (tapping the entry point *is* the request), and an explicit "Create a
/// new payment link" after one expired or was revoked.
///
/// Every figure is the server's. The amount is the order's outstanding
/// balance as the server last stated it; the sheet never subtracts anything.
///
/// ## No email here
///
/// ShipTrip does not email payment links, and the Sender is not asked for
/// anyone's address. Sharing goes through the phone's own share sheet — which
/// includes the Sender's mail app — so the request arrives from someone the
/// payer knows rather than from a platform they have never heard of. The only
/// email in the whole flow is the payer's own receipt address, asked on the
/// payment page and only when ShipTrip will actually send a receipt.
///
/// ## Staying current without polling forever
///
/// A guest paying is a websocket event first: `payment.*` invalidates this
/// order's resource and the sheet re-reads within a round trip of the webhook.
/// The fallback poll exists for a Sender whose socket is down; it runs only
/// while a link is live, backs off from 3 s to a 20 s ceiling, and stops after
/// ten minutes. Returning to the app — typically from the messaging app the
/// link was just shared in — re-reads straight away and restarts it.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../core/live/live_updates.dart';
import '../../core/money/money.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/identity.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';
import '../common/payment_result.dart';

class GuestPaymentSheet extends ConsumerStatefulWidget {
  const GuestPaymentSheet({required this.order, this.onSettled, super.key});

  final PaymentOrder order;

  /// Called once, when the server reports the obligation paid.
  final VoidCallback? onSettled;

  static Future<void> show(
    BuildContext context, {
    required PaymentOrder order,
    VoidCallback? onSettled,
  }) {
    return showAppSheet<void>(
      context,
      builder: (sheetContext) =>
          GuestPaymentSheet(order: order, onSettled: onSettled),
    );
  }

  @override
  ConsumerState<GuestPaymentSheet> createState() => _GuestPaymentSheetState();
}

enum _Load { loading, ready, failed }

class _GuestPaymentSheetState extends ConsumerState<GuestPaymentSheet>
    with WidgetsBindingObserver {
  static const _pollSteps = <Duration>[
    Duration(seconds: 3),
    Duration(seconds: 3),
    Duration(seconds: 5),
    Duration(seconds: 5),
    Duration(seconds: 10),
  ];
  static const _pollCeiling = Duration(seconds: 20);

  /// The fallback gives up after this. The live event and a return to the app
  /// both still refresh the sheet; only the timer stops.
  static const _pollBudget = Duration(minutes: 10);

  late PaymentOrder _order;
  GuestPaymentLink? _link;
  _Load _load = _Load.loading;

  bool _creating = false;
  bool _revoking = false;
  bool _copied = false;

  /// A failed action, in words, kept on the sheet until the next action.
  String? _notice;
  StatusTone _noticeTone = StatusTone.bad;

  Timer? _pollTimer;
  Timer? _copiedTimer;
  Duration _pollElapsed = Duration.zero;
  int _pollTick = 0;
  bool _settled = false;
  bool _readingOrder = false;
  bool _readingLink = false;
  LiveUnsubscribe? _liveUnsubscribe;

  PaymentRepository get _repo => ref.read(paymentRepositoryProvider);
  String get _reference => widget.order.publicReference;

  @override
  void initState() {
    super.initState();
    _order = widget.order;
    WidgetsBinding.instance.addObserver(this);
    if (_order.status.isSettled) {
      _settled = true;
      _load = _Load.ready;
      return;
    }
    _liveUnsubscribe = ref
        .read(liveUpdatesProvider)
        .register(_liveResource(), _onLiveEvent);
    unawaited(_open());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pollTimer?.cancel();
    _copiedTimer?.cancel();
    _liveUnsubscribe?.call();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Back from the messaging app the link was shared in: the likeliest moment
    // for something to have changed. Ask now, and give the fallback a fresh
    // budget since the Sender is evidently still waiting.
    if (state != AppLifecycleState.resumed || _settled) return;
    unawaited(_refreshOrder());
    unawaited(_readLink());
    _restartPolling();
  }

  /// The resource a `payment.*` event for this order lands on.
  LiveResource _liveResource() {
    final dealId = widget.order.dealId;
    if (dealId != null) return LiveResource.payment(dealId);
    final requestId = widget.order.deliveryRequestId;
    if (requestId != null) return LiveResource.deposit(requestId);
    return const LiveResource.deals();
  }

  void _onLiveEvent() {
    unawaited(_refreshOrder());
    unawaited(_readLink());
  }

  // -------------------------------------------------------------------------
  // Reading and writing the link
  // -------------------------------------------------------------------------

  Future<void> _open() async {
    setState(() {
      _load = _Load.loading;
      _notice = null;
    });
    try {
      final link = await _repo.guestLink(_reference);
      if (!mounted) return;
      if (link.state == GuestLinkState.none && link.canCreate) {
        // Never shared before: tapping "Someone else can pay" was the request.
        await _create();
        return;
      }
      _adopt(link);
    } on ApiException catch (error) {
      if (!mounted) return;
      if (_isClosedError(error)) {
        await _refreshOrder();
        if (!mounted) return;
      }
      setState(() => _load = _settled ? _Load.ready : _Load.failed);
    }
  }

  /// A quiet re-read, for a live event or a return to the app. Never shows a
  /// spinner and never replaces a failure notice the Sender is reading.
  Future<void> _readLink() async {
    if (_readingLink || _creating || _revoking || _settled || !mounted) return;
    if (_load == _Load.loading) return;
    _readingLink = true;
    try {
      final link = await _repo.guestLink(_reference);
      if (mounted) _adopt(link);
    } on ApiException {
      // A failed refresh is not news: the last known state still stands.
    } finally {
      _readingLink = false;
    }
  }

  Future<void> _create() async {
    setState(() {
      _creating = true;
      _notice = null;
    });
    try {
      final link = await _repo.createGuestLink(reference: _reference);
      if (!mounted) return;
      _adopt(link);
      // A link just handed out is the likeliest one to be paid soon.
      _restartPolling();
    } on ApiException catch (error) {
      if (!mounted) return;
      final l = L.of(context);
      if (error.code == ApiErrorCode.guestCheckoutInProgress) {
        _showNotice(l.guestErrorBusy, StatusTone.waiting);
      } else if (_isClosedError(error)) {
        await _refreshOrder();
      } else {
        _showNotice(
          error.isRetryable ? l.guestErrorLoad : l.guestPaymentLinkFailed,
          StatusTone.bad,
        );
      }
      if (!mounted) return;
      setState(() => _load = _Load.ready);
      _creating = false;
      await _readLink();
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  Future<void> _revoke() async {
    final l = L.of(context);
    final confirmed = await confirmAction(
      context,
      title: l.guestRevokeConfirmTitle,
      body: l.guestRevokeConfirmBody,
      confirmLabel: l.guestRevokeAction,
      cancelLabel: l.guestRevokeKeep,
      isDestructive: true,
    );
    if (!confirmed || !mounted) return;

    setState(() {
      _revoking = true;
      _notice = null;
    });
    try {
      final link = await _repo.revokeGuestLink(_reference);
      if (!mounted) return;
      _adopt(link);
      _announce(l.guestRevokedDone);
    } on ApiException catch (error) {
      if (!mounted) return;
      _showNotice(
        error.code == ApiErrorCode.guestCheckoutInProgress
            ? l.guestErrorRevokeBusy
            : l.guestErrorRevoke,
        error.code == ApiErrorCode.guestCheckoutInProgress
            ? StatusTone.waiting
            : StatusTone.bad,
      );
      _revoking = false;
      await _readLink();
    } finally {
      if (mounted) setState(() => _revoking = false);
    }
  }

  void _adopt(GuestPaymentLink link) {
    setState(() {
      _link = link;
      _load = _Load.ready;
    });
    if (link.state == GuestLinkState.paid) {
      unawaited(_refreshOrder());
      _markSettled();
      return;
    }
    _syncPolling();
  }

  bool _isClosedError(ApiException error) =>
      error.code == ApiErrorCode.nothingOutstanding ||
      error.code == ApiErrorCode.orderNotCollectable;

  // -------------------------------------------------------------------------
  // Settlement
  // -------------------------------------------------------------------------

  Future<void> _refreshOrder() async {
    if (_readingOrder || !mounted) return;
    _readingOrder = true;
    final before = _order.latestAttempt;
    try {
      final updated = await _repo.order(_reference);
      if (!mounted) return;
      setState(() => _order = updated);
      if (updated.status.isSettled) {
        _markSettled();
        return;
      }
      // A guest opening or abandoning a checkout shows up on the order as a
      // new or finished attempt. That is the moment the link's "someone is
      // paying" flag changes, so re-read the link then and only then.
      final after = updated.latestAttempt;
      if (after?.id != before?.id || after?.status != before?.status) {
        _readingOrder = false;
        await _readLink();
      }
    } on ApiException {
      // The next tick, event or resume asks again.
    } finally {
      _readingOrder = false;
    }
  }

  void _markSettled() {
    if (_settled) return;
    _settled = true;
    _pollTimer?.cancel();
    _pollTimer = null;
    _liveUnsubscribe?.call();
    _liveUnsubscribe = null;
    if (mounted) setState(() {});
    widget.onSettled?.call();
  }

  // -------------------------------------------------------------------------
  // Fallback polling
  // -------------------------------------------------------------------------

  /// Somebody could be paying only while a link is live.
  bool get _pollingApplies =>
      !_settled && _link?.state == GuestLinkState.active;

  void _syncPolling() {
    if (!_pollingApplies) {
      _pollTimer?.cancel();
      _pollTimer = null;
      return;
    }
    if (_pollTimer == null) _schedulePoll();
  }

  void _restartPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _pollTick = 0;
    _pollElapsed = Duration.zero;
    _syncPolling();
  }

  void _schedulePoll() {
    // `_settled` and the budget are what end the loop: cancelling a timer
    // inside its own callback would not, because that timer has already fired.
    if (!mounted || !_pollingApplies) return;
    // The budget is the sum of the waits actually scheduled, not a wall-clock
    // reading: exact, and immune to the device clock jumping.
    if (_pollElapsed >= _pollBudget) {
      _pollTimer = null;
      return;
    }
    final delay = _pollTick < _pollSteps.length
        ? _pollSteps[_pollTick]
        : _pollCeiling;
    _pollTick++;
    _pollElapsed += delay;
    _pollTimer = Timer(delay, () async {
      await _refreshOrder();
      _schedulePoll();
    });
  }

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  Future<void> _share(String url, String amount) async {
    final l = L.of(context);
    setState(() => _notice = null);
    try {
      await SharePlus.instance.share(
        ShareParams(
          text: l.guestShareMessage(amount, url),
          subject: l.guestShareSubject,
        ),
      );
    } catch (_) {
      if (mounted) _showNotice(l.guestErrorShare, StatusTone.neutral);
    }
  }

  Future<void> _copy(String url) async {
    final l = L.of(context);
    await Clipboard.setData(ClipboardData(text: url));
    if (!mounted) return;
    HapticFeedback.selectionClick();
    _copiedTimer?.cancel();
    setState(() {
      _copied = true;
      _notice = null;
    });
    _announce(l.guestLinkCopied);
    _copiedTimer = Timer(const Duration(seconds: 2), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  void _showNotice(String message, StatusTone tone) {
    setState(() {
      _notice = message;
      _noticeTone = tone;
    });
  }

  void _announce(String message) {
    final view = View.maybeOf(context);
    if (view == null) return;
    unawaited(
      SemanticsService.sendAnnouncement(
        view,
        message,
        Directionality.of(context),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    if (_settled || _link?.state == GuestLinkState.paid) {
      return AppSheet(
        title: l.guestPaymentTitle,
        // The one payment that settled it, not the running total (J7D).
        child: _PaidView(amount: lastPaymentOf(_order)),
      );
    }

    // The server's outstanding balance: from the link read when there is one,
    // from the order the sheet was opened on until then.
    final amount = _link?.amount ?? _order.outstanding ?? _order.amount;
    final amountText = amount?.format(locale) ?? '';

    return AppSheet(
      title: l.guestPaymentTitle,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (amount != null)
            _AmountHero(amount: amount, purpose: _purposeLabel(l, _order)),
          const SizedBox(height: AppSpace.lg),
          if (_notice != null) ...[
            InfoNotice(
              message: _notice!,
              tone: _noticeTone,
              icon: _noticeTone == StatusTone.waiting
                  ? Icons.hourglass_top_rounded
                  : Icons.error_outline_rounded,
            ),
            const SizedBox(height: AppSpace.lg),
          ],
          ..._body(context, l, amountText),
        ],
      ),
    );
  }

  List<Widget> _body(BuildContext context, L l, String amountText) {
    final link = _link;
    if (_load == _Load.loading || (_creating && link == null)) {
      return const [_LoadingBlock()];
    }
    if (_load == _Load.failed || link == null) {
      return [
        InfoNotice(
          message: l.guestErrorLoad,
          tone: StatusTone.bad,
          icon: Icons.wifi_off_rounded,
          actionLabel: l.actionRetry,
          onAction: _open,
        ),
      ];
    }

    final locale = Localizations.localeOf(context);
    final expires = link.expiresAt == null
        ? null
        : l.guestStatusExpiresOn(
            LocaleFormats.dateTime(locale, link.expiresAt!),
          );

    Widget createButton(String label, {bool primary = true}) => AppButton(
      label: label,
      icon: Icons.add_link_rounded,
      variant: primary ? AppButtonVariant.primary : AppButtonVariant.secondary,
      isLoading: _creating,
      onPressed: link.canCreate ? _create : null,
    );

    return switch (link.state) {
      GuestLinkState.active when link.checkoutInProgress => [
        _StatusPanel(
          icon: Icons.hourglass_top_rounded,
          tone: StatusTone.waiting,
          title: l.guestStatusPaying,
          body: l.guestStatusPayingBody,
        ),
      ],
      GuestLinkState.active when link.isShareable => [
        Text(
          l.guestShareLead,
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: context.colors.textSecondary),
        ),
        const SizedBox(height: AppSpace.xl),
        AppButton(
          label: l.guestShareAction,
          icon: Icons.share_rounded,
          onPressed: () => _share(link.paymentLink!, amountText),
        ),
        const SizedBox(height: AppSpace.sm),
        AppButton(
          label: _copied ? l.guestCopiedAction : l.guestCopyAction,
          icon: _copied ? Icons.check_rounded : Icons.copy_rounded,
          variant: AppButtonVariant.secondary,
          onPressed: () => _copy(link.paymentLink!),
        ),
        const SizedBox(height: AppSpace.xl),
        _StatusPanel(
          icon: Icons.link_rounded,
          tone: StatusTone.good,
          title: l.guestStatusReady,
          body: expires,
          trailing: link.canRevoke
              ? _MoreMenu(busy: _revoking, onRevoke: _revoke)
              : null,
          footer: _LinkPreview(url: link.paymentLink!),
        ),
      ],
      // Live, but issued before links could be shown again: say so, and let
      // the Sender replace it deliberately rather than doing it for them.
      GuestLinkState.active => [
        _StatusPanel(
          icon: Icons.info_outline_rounded,
          tone: StatusTone.neutral,
          title: l.guestStatusHidden,
          body: l.guestStatusHiddenBody,
        ),
        const SizedBox(height: AppSpace.lg),
        createButton(l.guestCreateNewAction, primary: false),
      ],
      GuestLinkState.expired => [
        _StatusPanel(
          icon: Icons.timer_off_outlined,
          tone: StatusTone.neutral,
          title: l.guestStatusExpired,
          body: link.canCreate ? l.guestStatusNewLinkBody : null,
        ),
        if (link.canCreate) ...[
          const SizedBox(height: AppSpace.lg),
          createButton(l.guestCreateNewAction),
        ],
      ],
      GuestLinkState.revoked => [
        _StatusPanel(
          icon: Icons.link_off_rounded,
          tone: StatusTone.neutral,
          title: l.guestStatusRevoked,
          body: link.canCreate ? l.guestStatusNewLinkBody : null,
        ),
        if (link.canCreate) ...[
          const SizedBox(height: AppSpace.lg),
          createButton(l.guestCreateNewAction),
        ],
      ],
      GuestLinkState.closed => [
        _StatusPanel(
          icon: Icons.block_rounded,
          tone: StatusTone.neutral,
          title: l.guestStatusClosed,
        ),
      ],
      // Never shared and the automatic first issue did not go through; the
      // notice above says why.
      GuestLinkState.none => [
        if (link.canCreate) createButton(l.guestCreateAction),
      ],
      GuestLinkState.paid || GuestLinkState.unknown => [
        InfoNotice(
          message: l.guestErrorLoad,
          tone: StatusTone.bad,
          icon: Icons.error_outline_rounded,
          actionLabel: l.actionRetry,
          onAction: _open,
        ),
      ],
    };
  }
}

/// What the payment is for, in words. Chosen from the server's purpose and its
/// own figures (a credited deposit or a part payment makes a balance the
/// *remaining* one); nothing is computed.
String _purposeLabel(L l, PaymentOrder order) => switch (order.purpose) {
  PaymentPurpose.postingDeposit => l.guestPurposeDeposit,
  PaymentPurpose.dealBalance =>
    order.hasCredit || (order.paid?.isPositive ?? false)
        ? l.guestPurposeRemaining
        : l.guestPurposeDelivery,
  PaymentPurpose.boost => l.guestPurposeBoost,
  PaymentPurpose.unknown => l.guestPurposeOther,
};

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

/// The amount is the point of the sheet: what it is for, then the figure.
class _AmountHero extends StatelessWidget {
  const _AmountHero({required this.amount, required this.purpose});

  final Money amount;
  final String purpose;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final formatted = amount.format(Localizations.localeOf(context));
    final isArabic = Directionality.of(context) == TextDirection.rtl;
    return Semantics(
      label: '$purpose, $formatted',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            isArabic ? purpose : purpose.toUpperCase(),
            style: AppTypography.eyebrow(context, color: c.onAttentionSoft),
          ),
          const SizedBox(height: AppSpace.xs),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: AlignmentDirectional.centerStart,
            child: Text(
              formatted,
              style: AppTypography.heroMoney(context, color: c.textPrimary),
              maxLines: 1,
            ),
          ),
        ],
      ),
    );
  }
}

/// A quiet, sunken block that says where the link stands.
///
/// A live region, so a screen reader hears the change when a guest starts
/// paying or the link is revoked without having to go looking for it.
class _StatusPanel extends StatelessWidget {
  const _StatusPanel({
    required this.icon,
    required this.tone,
    required this.title,
    this.body,
    this.trailing,
    this.footer,
  });

  final IconData icon;
  final StatusTone tone;
  final String title;
  final String? body;
  final Widget? trailing;
  final Widget? footer;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final accent = StatusStyle.of(context, tone).accent;

    return AppInsetGroup(
      padding: EdgeInsetsDirectional.fromSTEB(
        AppSpace.lg,
        AppSpace.md,
        trailing == null ? AppSpace.lg : AppSpace.xs,
        AppSpace.md,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              ExcludeSemantics(child: Icon(icon, size: 20, color: accent)),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: Semantics(
                  liveRegion: true,
                  container: true,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: AppSpace.xs),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(title, style: text.titleSmall),
                        if (body != null) ...[
                          const SizedBox(height: AppSpace.xxs),
                          Text(
                            body!,
                            style: text.bodySmall?.copyWith(
                              color: c.textSecondary,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
              ?trailing,
            ],
          ),
          if (footer != null) ...[
            const SizedBox(height: AppSpace.sm),
            Padding(
              padding: EdgeInsetsDirectional.only(
                end: trailing == null ? 0 : AppSpace.md,
              ),
              child: footer!,
            ),
          ],
        ],
      ),
    );
  }
}

/// The link itself, small and quiet: enough to recognise, not to read aloud.
class _LinkPreview extends StatelessWidget {
  const _LinkPreview({required this.url});

  final String url;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final shown = url.replaceFirst(RegExp(r'^https?://'), '');
    return Semantics(
      label: L.of(context).guestLinkLabel,
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DashedDivider(color: c.hairlineStrong),
          const SizedBox(height: AppSpace.sm),
          // A URL is a machine token: always left-to-right, even in Arabic.
          Directionality(
            textDirection: TextDirection.ltr,
            child: Text(
              shown,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.left,
              style: AppTypography.monoLabel(
                context,
                color: c.textTertiary,
                size: 11.5,
                weight: 500,
                tracking: 0.2,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

enum _MoreAction { revoke }

/// Revoking lives one step away from Share, never beside it.
class _MoreMenu extends StatelessWidget {
  const _MoreMenu({required this.busy, required this.onRevoke});

  final bool busy;
  final VoidCallback onRevoke;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    if (busy) {
      return const SizedBox(
        width: AppSpace.minTapTarget,
        height: AppSpace.minTapTarget,
        child: Center(
          child: SizedBox.square(
            dimension: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      );
    }
    return PopupMenuButton<_MoreAction>(
      tooltip: l.guestMoreActions,
      icon: Icon(Icons.more_horiz_rounded, color: c.textSecondary),
      color: c.surfaceRaised,
      elevation: 3,
      shape: RoundedRectangleBorder(
        borderRadius: AppRadius.rMd,
        side: BorderSide(color: c.hairline),
      ),
      position: PopupMenuPosition.under,
      onSelected: (action) => switch (action) {
        _MoreAction.revoke => onRevoke(),
      },
      itemBuilder: (context) => [
        PopupMenuItem(
          value: _MoreAction.revoke,
          child: Row(
            children: [
              Icon(Icons.link_off_rounded, size: 20, color: c.danger),
              const SizedBox(width: AppSpace.md),
              Text(l.guestRevokeAction, style: TextStyle(color: c.danger)),
            ],
          ),
        ),
      ],
    );
  }
}

class _LoadingBlock extends StatelessWidget {
  const _LoadingBlock();

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const SkeletonLines(count: 2),
      const SizedBox(height: AppSpace.xl),
      SkeletonBox(width: double.infinity, height: AppSpace.minTapTarget + 6),
      const SizedBox(height: AppSpace.sm),
      SkeletonBox(width: double.infinity, height: AppSpace.minTapTarget + 6),
    ],
  );
}

/// The whole sheet once the obligation is paid: nothing left to share, copy
/// or revoke — a result, and the way on.
class _PaidView extends StatelessWidget {
  const _PaidView({required this.amount});

  /// What the server says was paid on this obligation. Null only if the order
  /// could not be re-read, in which case the sentence carries no figure.
  final Money? amount;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final paid = amount;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: AppSpace.sm),
        // The same mark as every payment result (J7D): an icon pressed into
        // the seal, never a "✓" glyph the app's own faces do not carry.
        const Center(
          child: PaymentResultMark(kind: PaymentResultKind.received, size: 56),
        ),
        const SizedBox(height: AppSpace.lg),
        Semantics(
          liveRegion: true,
          header: true,
          child: Text(
            l.guestPaidTitle,
            textAlign: TextAlign.center,
            style: text.headlineSmall,
          ),
        ),
        const SizedBox(height: AppSpace.sm),
        Text(
          paid != null && paid.isPositive
              ? l.guestPaidBody(paid.format(locale))
              : l.guestPaidBodyPlain,
          textAlign: TextAlign.center,
          style: text.bodyMedium?.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: AppSpace.xl),
        AppButton(
          label: l.actionContinue,
          icon: Icons.arrow_forward_rounded,
          onPressed: () => Navigator.of(context).maybePop(),
        ),
      ],
    );
  }
}
