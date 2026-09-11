/// The delivery handover, and the protection window that follows it.
///
/// ## The invariant this file is shaped around
///
/// **The traveller can never obtain the delivery code.** That is not enforced
/// here by remembering to check a boolean before calling a method — it is
/// enforced by construction. `HandoverRepository.revealDeliveryCode` is called
/// from exactly one place in this app, [_SenderCodePanel], a private widget
/// that is only ever instantiated inside the sender branch and whose state is
/// unreachable from the traveller's tree. The traveller's half of this screen
/// has no method that could call it, so no future edit can accidentally wire
/// one up.
///
/// The traveller is told this plainly rather than left to wonder: the server
/// publishes `traveler_can_view_delivery_code: false`, and this screen renders
/// that fact as reassurance instead of pretending the question does not exist.
///
/// ## The 30-minute buffer
///
/// The pause between pickup and code release is what stops a parcel and its
/// delivery code changing hands in the same moment. The client renders a
/// countdown to the server's `delivery_code_available_at` and, when it
/// reaches zero, **re-asks the server**. A local timer hitting zero unlocks
/// nothing; it only invalidates the cached deal so the next answer is the
/// server's.
///
/// ## Money
///
/// Nothing on this screen is computed. The protection deadline, the payout
/// status, the payout amount and whether a dispute has frozen it are all
/// server fields, rendered as given. The screen never promises an immediate
/// payout, because there is no such thing here.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../core/money/money.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/codes.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/deal.dart';
import '../../domain/handover.dart';
import '../../domain/payout.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';

/// Eight alphanumeric characters, per the server's contract.
const _deliveryCodeLength = 8;

class DeliveryScreen extends ConsumerStatefulWidget {
  const DeliveryScreen({required this.dealId, super.key});

  final int dealId;

  @override
  ConsumerState<DeliveryScreen> createState() => _DeliveryScreenState();
}

/// Holds only what the *traveller* needs plus the shared refusal state.
///
/// There is deliberately no `RevealedCode` field and no reveal method on this
/// class. Both live in [_SenderCodePanel].
class _DeliveryScreenState extends ConsumerState<DeliveryScreen> {
  final _code = TextEditingController();

  CodeAttemptOutcome? _attempt;
  String? _codeError;
  String? _blocking;

  /// A `delivery_code_available_at` the server attached to a refusal. Trusted
  /// over the cached deal, because it is newer.
  DateTime? _bufferUntil;

  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  bool get _isLockedOut {
    final until = _attempt?.lockedUntil;
    return until != null && until.isAfter(DateTime.now());
  }

  void _refetch() {
    _bufferUntil = null;
    ref.invalidate(dealDetailProvider(widget.dealId));
  }

  // -------------------------------------------------------------------------
  // Traveller action — the only handover call this class can make
  // -------------------------------------------------------------------------

  Future<void> _submit() async {
    if (_busy || _isLockedOut) return;
    final l = L.of(context);
    final code = _code.text.trim();
    if (code.isEmpty) {
      setState(() => _codeError = l.validationRequired);
      return;
    }

    setState(() {
      _busy = true;
      _codeError = null;
      _blocking = null;
    });
    try {
      await ref
          .read(handoverRepositoryProvider)
          .submitDeliveryCode(dealId: widget.dealId, code: code);
      if (!mounted) return;
      refreshVolatileState(ref);
      _code.clear();
      setState(() => _attempt = null);
      AppSnack.success(context, l.deliveryConfirmedTitle);
    } on ApiException catch (error) {
      if (!mounted) return;
      applyFailure(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // -------------------------------------------------------------------------
  // Failures. Shared, because both halves meet the same refusals.
  // -------------------------------------------------------------------------

  void applyFailure(ApiException error) {
    final l = L.of(context);

    if (error.code == ApiErrorCode.handoverCodeInvalid) {
      final outcome = CodeAttemptOutcome(
        attemptsRemaining: error.intExtra('attempts_remaining'),
        requiresNewCode: error.extras['requires_new_code'] == true,
      );
      setState(() {
        _attempt = outcome;
        _codeError = outcome.requiresNewCode
            ? l.codeRequiresNewCodeBody
            : l.codeIncorrect;
      });
      return;
    }

    if (error.code == ApiErrorCode.handoverCodeLocked) {
      setState(() {
        _attempt = CodeAttemptOutcome(
          lockedUntil: error.dateExtra('locked_until'),
        );
        _codeError = l.codeLockedTitle;
      });
      return;
    }

    if (error.code == ApiErrorCode.handoverRateLimited ||
        error.kind == ApiFailureKind.rateLimited) {
      final seconds = error.intExtra('retry_after_seconds');
      setState(() {
        _attempt = CodeAttemptOutcome(retryAfterSeconds: seconds);
        _codeError = seconds == null
            ? l.stateRateLimitedBody
            : l.codeRateLimitedBody(seconds);
      });
      return;
    }

    if (error.code == ApiErrorCode.deliveryCodeBufferOpen) {
      // The refusal carries a fresher deadline than anything cached, so the
      // countdown re-renders from it rather than from the stale deal.
      final until = error.dateExtra('delivery_code_available_at');
      refreshVolatileState(ref);
      setState(() {
        _bufferUntil = until;
        _blocking = l.deliveryCodeBufferOpenBody;
        _codeError = null;
      });
      return;
    }

    if (error.code == ApiErrorCode.deliveryAlreadyConfirmed) {
      // No notice needed: the refreshed screen shows the confirmed state,
      // which explains itself better than a banner would.
      refreshVolatileState(ref);
      setState(() {
        _blocking = null;
        _codeError = null;
      });
      AppSnack.info(context, l.deliveryConfirmedTitle);
      return;
    }

    final blocking = switch (error.code) {
      ApiErrorCode.codeNotAvailable => l.codeNotAvailableYet,
      ApiErrorCode.deliveryCodeNotArmed => l.codeNotAvailableYet,
      ApiErrorCode.dealNotInCarriage => l.deliveryNotInCarriageBody,
      ApiErrorCode.pickupNotConfirmed => l.deliveryAwaitingTravelerBody,
      ApiErrorCode.recipientNotSet => l.recipientRequiredTravelerBody,
      _ => error.kind == ApiFailureKind.forbidden ? l.stateForbiddenBody : null,
    };

    if (blocking != null) {
      if (error.isStale) refreshVolatileState(ref);
      setState(() {
        _blocking = blocking;
        _codeError = null;
      });
      return;
    }

    AppSnack.failure(context, error);
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final value = ref.watch(dealDetailProvider(widget.dealId));

    final deal = value.value;
    final viewerId = account?.id;
    final isSender =
        deal != null && viewerId != null && deal.isSender(viewerId);
    final handover = deal?.handover;

    final canSubmit =
        deal != null &&
        viewerId != null &&
        !isSender &&
        !(handover?.isDeliveryConfirmed ?? false) &&
        (handover?.canSubmitDeliveryCode ?? false);

    return DismissKeyboardOnTap(
      child: AppScaffold(
        topBar: AppTopBar(title: l.deliveryTitle, showBack: true),
        footer: canSubmit
            ? AppButton(
                label: l.deliveryConfirmAction,
                isLoading: _busy,
                onPressed: _isLockedOut ? null : _submit,
              )
            : null,
        body: AsyncView<Deal>(
          value: value,
          onRetry: _refetch,
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpace.gutter),
            child: SkeletonDetail(),
          ),
          data: (loaded) {
            if (viewerId == null) return const SkeletonDetail();
            return ListView(
              padding: canSubmit
                  ? AppScrollPadding.pageWithFooter(context)
                  : AppScrollPadding.page(context),
              children: _sections(
                loaded,
                isSender: loaded.isSender(viewerId),
                canSubmit: canSubmit,
              ),
            );
          },
        ),
      ),
    );
  }

  List<Widget> _sections(
    Deal deal, {
    required bool isSender,
    required bool canSubmit,
  }) {
    final l = L.of(context);
    final handover = deal.handover;
    final isConfirmed =
        (handover?.isDeliveryConfirmed ?? false) ||
        deal.deliveryConfirmedAt != null;

    return [
      if (_blocking != null) ...[
        InfoNotice(
          title: l.staleTitle,
          message: _blocking!,
          tone: StatusTone.waiting,
          icon: Icons.sync_problem_rounded,
        ),
        const SizedBox(height: AppSpace.xl),
      ],

      if (isConfirmed)
        ..._confirmedSections(deal, isSender: isSender)
      else if (isSender)
        ..._senderSections(deal)
      else
        ..._travelerSections(deal, canSubmit: canSubmit),
    ];
  }

  // -------------------------------------------------------------------------
  // Sender
  // -------------------------------------------------------------------------

  List<Widget> _senderSections(Deal deal) {
    final l = L.of(context);
    final handover = deal.handover;

    // A fresh server projection supersedes an earlier rejection's deadline.
    final availableAt =
        handover?.deliveryCodeAvailableAt ??
        deal.deliveryCodeAvailableAt ??
        _bufferUntil;
    // The device countdown is presentation only. A skewed device clock must
    // not hide availability that the server has now explicitly authorized.
    final inBuffer =
        !(handover?.canRevealDeliveryCode ?? false) &&
        ((handover?.inDeliveryCodeBuffer ?? false) ||
            (availableAt != null && availableAt.isAfter(DateTime.now())));

    final header = [
      AppInsetGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l.deliverySenderTitle,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: AppSpace.sm),
            Text(
              l.deliverySenderExplainer,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: AppSpace.xl),
    ];

    if (inBuffer && availableAt != null) {
      return [
        ...header,
        _BufferPanel(availableAt: availableAt, onAvailable: _refetch),
      ];
    }

    if (handover?.canRevealDeliveryCode ?? false) {
      final recipient = deal.recipient;
      return [
        ...header,
        _SenderCodePanel(
          dealId: deal.id,
          // Sender-only projection: the sender supplied these details, and the
          // traveller never receives them.
          recipientLabel: recipient?.email ?? recipient?.fullName,
          onFailure: applyFailure,
        ),
      ];
    }

    return [
      ...header,
      AppEmptyState(
        title: l.deliveryAwaitingTitle,
        body: l.deliveryAwaitingSenderBody,
        icon: Icons.lock_clock_rounded,
      ),
    ];
  }

  // -------------------------------------------------------------------------
  // Traveller — no reveal path exists here
  // -------------------------------------------------------------------------

  List<Widget> _travelerSections(Deal deal, {required bool canSubmit}) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final handover = deal.handover;
    final lockedUntil = _attempt?.lockedUntil;
    final availableAt =
        handover?.deliveryCodeAvailableAt ?? deal.deliveryCodeAvailableAt;
    final waitingForSafetyPeriod =
        !canSubmit && (handover?.inDeliveryCodeBuffer ?? false);

    return [
      AppInsetGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              waitingForSafetyPeriod
                  ? l.deliverySafetyWaitingTitle
                  : l.deliveryTravelerTitle,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: AppSpace.sm),
            Text(
              waitingForSafetyPeriod
                  ? l.pickupConfirmedTravelerNext
                  : l.deliveryTravelerExplainer,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: AppSpace.lg),

      // Rendered from the server's own flag rather than from a hard-coded
      // sentence, so the reassurance is the API's word and a test can assert
      // it. The flag is contractually false and there is no branch for true.
      if (!(handover?.travelerCanViewDeliveryCode ?? false))
        InfoNotice(
          message: l.deliveryCodeTravelerNever,
          tone: StatusTone.progress,
          icon: Icons.shield_outlined,
        ),

      if (waitingForSafetyPeriod) ...[
        const SizedBox(height: AppSpace.xl),
        LockedCodePanel(
          title: l.deliverySafetyWaitingTitle,
          body: l.deliverySafetyWaitingTravelerBody,
          availableAt: availableAt,
          onAvailable: availableAt == null ? null : _refetch,
        ),
      ] else if (!canSubmit) ...[
        const SizedBox(height: AppSpace.xl),
        AppEmptyState(
          title: l.deliveryAwaitingTitle,
          body: l.deliveryAwaitingTravelerBody,
          icon: Icons.lock_clock_rounded,
        ),
      ] else ...[
        const SizedBox(height: AppSpace.xl),
        CodeEntryField(
          controller: _code,
          label: l.deliveryCodeLabel,
          length: _deliveryCodeLength,
          allowLetters: true,
          errorText: _codeError,
          attemptsRemaining: _attempt?.attemptsRemaining,
          enabled: !_busy && !_isLockedOut,
          onSubmitted: (_) => _submit(),
        ),
        if (lockedUntil != null && _isLockedOut) ...[
          const SizedBox(height: AppSpace.lg),
          InfoNotice(
            title: l.codeLockedTitle,
            message: l.codeLockedBody(LocaleFormats.time(locale, lockedUntil)),
            tone: StatusTone.bad,
            icon: Icons.lock_clock_rounded,
          ),
          const SizedBox(height: AppSpace.md),
          CodeCountdown(
            target: lockedUntil,
            onElapsed: () {
              if (mounted) setState(() {});
            },
          ),
        ],
      ],
    ];
  }

  // -------------------------------------------------------------------------
  // Confirmed
  // -------------------------------------------------------------------------

  List<Widget> _confirmedSections(Deal deal, {required bool isSender}) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final at = deal.handover?.deliveryConfirmedAt ?? deal.deliveryConfirmedAt;

    return [
      AppCard(
        accent: StatusTone.good,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            StatusPill(
              label: l.deliveryConfirmedTitle,
              tone: StatusTone.good,
              icon: Icons.check_circle_rounded,
            ),
            const SizedBox(height: AppSpace.md),
            Text(
              isSender
                  ? l.deliveryConfirmedSenderBody
                  : l.deliveryConfirmedTravelerBody,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
            if (at != null) ...[
              const SizedBox(height: AppSpace.md),
              DetailRow(
                label: l.timelineDone,
                value: Text(
                  LocaleFormats.dateTime(locale, at),
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ),
            ],
          ],
        ),
      ),

      if (!isSender) ...[
        const SizedBox(height: AppSpace.lg),
        InfoNotice(
          message: l.deliveryConfirmedTravelerNext,
          tone: StatusTone.waiting,
          icon: Icons.schedule_rounded,
        ),
      ],

      const SizedBox(height: AppSpace.xl),
      _ProtectionSection(deal: deal, isSender: isSender),
    ];
  }
}

// ---------------------------------------------------------------------------
// Sender-only code panel
// ---------------------------------------------------------------------------

/// The one place in this application that calls `revealDeliveryCode`.
///
/// Instantiated only from the sender branch of [DeliveryScreen], and only when
/// the server has said `can_reveal_delivery_code`. The plaintext lives in this
/// State object for as long as the sender is looking at it and is destroyed
/// with the widget — it is never lifted into a provider, a route, a snackbar
/// or a log.
class _SenderCodePanel extends ConsumerStatefulWidget {
  const _SenderCodePanel({
    required this.dealId,
    required this.onFailure,
    this.recipientLabel,
  });

  final int dealId;
  final String? recipientLabel;
  final void Function(ApiException error) onFailure;

  @override
  ConsumerState<_SenderCodePanel> createState() => _SenderCodePanelState();
}

class _SenderCodePanelState extends ConsumerState<_SenderCodePanel> {
  RevealedCode? _revealed;
  bool _busy = false;

  @override
  void dispose() {
    _revealed = null;
    super.dispose();
  }

  Future<void> _reveal() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final code = await ref
          .read(handoverRepositoryProvider)
          .revealDeliveryCode(widget.dealId);
      if (!mounted) return;
      setState(() => _revealed = code);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _revealed = null);
      widget.onFailure(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _rotate() async {
    if (_busy) return;
    final l = L.of(context);

    final confirmed = await confirmAction(
      context,
      title: l.codeRotateConfirmTitle,
      body: l.codeRotateConfirmBody,
      confirmLabel: l.codeRotate,
      isDestructive: true,
    );
    if (!confirmed || !mounted) return;

    setState(() => _busy = true);
    try {
      final code = await ref
          .read(handoverRepositoryProvider)
          .rotateDeliveryCode(widget.dealId);
      if (!mounted) return;
      refreshVolatileState(ref);
      setState(() => _revealed = code);
      AppSnack.success(context, l.codeRotated);
    } on ApiException catch (error) {
      if (!mounted) return;
      widget.onFailure(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final revealed = _revealed;
    final recipient = widget.recipientLabel;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InfoNotice(
          title: l.deliveryCodeReadyTitle,
          message: recipient == null || recipient.isEmpty
              ? l.deliveryCodeSentToRecipientUnknown
              : l.deliveryCodeSentToRecipient(recipient),
          tone: StatusTone.progress,
          icon: Icons.mark_email_read_outlined,
        ),
        const SizedBox(height: AppSpace.lg),

        InfoNotice(
          message: l.deliveryCodeSenderWarning,
          tone: StatusTone.action,
          icon: Icons.record_voice_over_rounded,
        ),

        if (revealed != null) ...[
          const SizedBox(height: AppSpace.xl),
          CodeDisplay(
            // `code` is copied and spelled out by the screen reader;
            // `formatted` is the server's grouping, for reading aloud.
            code: revealed.code,
            formatted: revealed.formatted,
            label: l.deliveryCodeLabel,
            caption: l.codeCopyForReading,
            onCopy: () => AppSnack.info(context, l.actionCopied),
          ),
        ] else ...[
          const SizedBox(height: AppSpace.xl),
          AppButton(
            label: l.deliveryCodeReveal,
            icon: Icons.visibility_rounded,
            isLoading: _busy,
            onPressed: _reveal,
          ),
        ],

        const SizedBox(height: AppSpace.lg),
        AppButton(
          label: l.codeRotate,
          icon: Icons.autorenew_rounded,
          variant: AppButtonVariant.tertiary,
          expand: false,
          onPressed: _busy ? null : _rotate,
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// The 30-minute buffer
// ---------------------------------------------------------------------------

/// The locked panel, with a countdown that ticks in its own heading.
///
/// The countdown lives in the title rather than in [LockedCodePanel]'s own
/// `availableAt` row so the screen shows one clock instead of two. Reaching
/// zero fires [onAvailable] exactly once, and the only thing that callback is
/// allowed to do is ask the server again.
class _BufferPanel extends StatefulWidget {
  const _BufferPanel({required this.availableAt, required this.onAvailable});

  final DateTime availableAt;
  final VoidCallback onAvailable;

  @override
  State<_BufferPanel> createState() => _BufferPanelState();
}

class _BufferPanelState extends State<_BufferPanel> {
  Timer? _timer;
  late CountdownParts _parts;
  bool _notified = false;

  @override
  void initState() {
    super.initState();
    _parts = CountdownParts.until(widget.availableAt);
    _schedule();
  }

  @override
  void didUpdateWidget(_BufferPanel old) {
    super.didUpdateWidget(old);
    if (old.availableAt != widget.availableAt) {
      _notified = false;
      _parts = CountdownParts.until(widget.availableAt);
      _schedule();
    }
  }

  void _schedule() {
    _timer?.cancel();
    if (_parts.hasElapsed) {
      if (_notified) return;
      _notified = true;
      // Out of the build phase: the callback invalidates a provider.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.onAvailable();
      });
      return;
    }
    _timer = Timer(_parts.tickInterval, () {
      if (!mounted) return;
      setState(() => _parts = CountdownParts.until(widget.availableAt));
      _schedule();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return LockedCodePanel(
      title: l.deliveryCodeLockedTitle(formatCountdown(context, _parts)),
      body: l.deliveryCodeLockedBody,
      explainerTitle: l.deliveryCodeLockedWhy,
      explainerBody: l.deliveryCodeLockedWhyBody,
    );
  }
}

// ---------------------------------------------------------------------------
// Protection window and payout
// ---------------------------------------------------------------------------

/// What happens to the money after delivery.
///
/// Every value here is a server field. The window's end, the payout status,
/// the amount and the freeze are read, never derived, and the copy never
/// implies the traveller has been paid.
class _ProtectionSection extends StatelessWidget {
  const _ProtectionSection({required this.deal, required this.isSender});

  final Deal deal;
  final bool isSender;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final text = Theme.of(context).textTheme;

    final protection = deal.protection;
    final endsAt = protection?.protectionEndsAt ?? deal.protectionEndsAt;
    final isOpen = endsAt != null && endsAt.isAfter(DateTime.now());
    final payout = protection?.payout;
    final dispute = deal.dispute;
    final hasActiveDispute = dispute != null && dispute.isActive;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionHeader(title: l.protectionTitle),
        AppCard(
          accent: hasActiveDispute
              ? StatusTone.bad
              : (isOpen ? StatusTone.waiting : StatusTone.good),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              StatusPill(
                label: isOpen ? l.protectionTitle : l.protectionEnded,
                tone: isOpen ? StatusTone.waiting : StatusTone.good,
                icon: Icons.shield_rounded,
              ),
              if (isOpen) ...[
                const SizedBox(height: AppSpace.md),
                CodeCountdown(target: endsAt, label: l.protectionEndsInLabel),
              ],
              const SizedBox(height: AppSpace.md),
              Text(
                endsAt == null
                    ? l.protectionExplainerBody
                    : (isSender
                          ? l.protectionSenderBody(
                              LocaleFormats.preciseDateTime(locale, endsAt),
                            )
                          : l.protectionTravelerBody(
                              LocaleFormats.preciseDateTime(locale, endsAt),
                            )),
                style: text.bodyMedium?.copyWith(
                  color: context.colors.textSecondary,
                ),
              ),
            ],
          ),
        ),

        if (hasActiveDispute) ...[
          const SizedBox(height: AppSpace.lg),
          InfoNotice(
            title: l.disputePayoutFrozenTitle,
            message: l.payoutFrozenBody,
            tone: StatusTone.bad,
            icon: Icons.ac_unit_rounded,
            actionLabel: l.disputeViewAction,
            onAction: () => context.openDispute(dispute.id),
          ),
        ],

        // The payout belongs to the traveller and is only ever shown to them.
        if (!isSender && (deal.payoutSummary != null || payout != null)) ...[
          const SizedBox(height: AppSpace.xl),
          SectionHeader(title: l.payoutTitle),
          _PayoutBlock(
            payoutSummary: deal.payoutSummary,
            legacyPayout: payout,
            frozen: hasActiveDispute,
          ),
        ],

        const SizedBox(height: AppSpace.xl),
        InfoNotice(
          title: l.protectionExplainerTitle,
          message: l.protectionExplainerBody,
          icon: Icons.info_outline_rounded,
        ),
      ],
    );
  }
}

class _PayoutBlock extends StatelessWidget {
  const _PayoutBlock({
    this.payoutSummary,
    this.legacyPayout,
    required this.frozen,
  });

  final PayoutMobile? payoutSummary;
  final DealPayout? legacyPayout;
  final bool frozen;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    if (payoutSummary != null) {
      final summary = payoutSummary!;
      final stateCopy = payoutDisplayStateCopy(context, summary.displayState);
      final blockingCopy =
          payoutBlockingReasonLabel(context, summary.blockingReason);
      final dzdAmount = summary.dzdAmount;
      final isDzd = dzdAmount != null && dzdAmount > 0;
      final fxRate = summary.formattedFxRate;

      return AppInsetGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: StatusPill(
                    label: stateCopy.label,
                    tone: (frozen ||
                            summary.displayState ==
                                PayoutDisplayState.needsAttention)
                        ? StatusTone.bad
                        : (summary.displayState ==
                                PayoutDisplayState.protectionActive
                            ? StatusTone.waiting
                            : stateCopy.tone),
                    icon: frozen ? Icons.ac_unit_rounded : stateCopy.icon,
                  ),
                ),
                TextButton.icon(
                  onPressed: () =>
                      context.openPayoutDetail(summary.reference),
                  icon: const Icon(Icons.open_in_new_rounded, size: 16),
                  label: Text(l.payoutViewAction),
                ),
              ],
            ),
            const SizedBox(height: AppSpace.md),
            DetailRow(
              label: l.payoutAmountLabel,
              value: MoneyText(summary.canonicalEurAmount,
                  semanticPrefix: l.a11yMoneyAmount),
            ),
            if (isDzd) ...[
              const SizedBox(height: AppSpace.sm),
              DetailRow(
                label: l.payoutDzdTitle,
                value: MoneyText(Money.minor(dzdAmount, 'DZD', 0)),
              ),
              if (fxRate != null) ...[
                const SizedBox(height: AppSpace.xs),
                DetailRow(
                  label: l.payoutRateLabel(fxRate),
                  value: const SizedBox.shrink(),
                ),
              ],
            ],
            if (blockingCopy != null && blockingCopy.isNotEmpty) ...[
              const SizedBox(height: AppSpace.sm),
              Text(
                blockingCopy,
                style: text.bodySmall?.copyWith(color: c.danger),
              ),
            ],
            if (summary.availableActions
                .contains('configure_payout_method')) ...[
              const SizedBox(height: AppSpace.md),
              AppButton(
                label: l.payoutMethodsTitle,
                variant: AppButtonVariant.secondary,
                icon: Icons.account_balance_rounded,
                onPressed: () => context.openPayoutMethods(),
              ),
            ],
          ],
        ),
      );
    }

    if (legacyPayout != null) {
      final payout = legacyPayout!;
      final status = payoutStatusCopy(context, payout.status);
      final amount = payout.amount;
      final eligibleAt = payout.eligibleAt;
      final paidAt = payout.paidAt;

      return AppInsetGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            StatusPill(
              label: status.label,
              tone: frozen ? StatusTone.bad : status.tone,
              icon: frozen ? Icons.ac_unit_rounded : status.icon,
            ),
            if (amount != null) ...[
              const SizedBox(height: AppSpace.md),
              DetailRow(
                label: l.payoutAmountLabel,
                value: MoneyText(amount, semanticPrefix: l.a11yMoneyAmount),
              ),
            ],
            if (eligibleAt != null) ...[
              const SizedBox(height: AppSpace.sm),
              DetailRow(
                label: l.payoutEligibleLabel,
                value: Text(
                  LocaleFormats.dateTime(locale, eligibleAt),
                  style: text.bodyMedium,
                ),
              ),
            ],
            if (paidAt != null) ...[
              const SizedBox(height: AppSpace.sm),
              DetailRow(
                label: l.payoutStatusPaid,
                value: Text(
                  LocaleFormats.dateTime(locale, paidAt),
                  style: text.bodyMedium,
                ),
              ),
            ],
          ],
        ),
      );
    }

    return const SizedBox.shrink();
  }
}
