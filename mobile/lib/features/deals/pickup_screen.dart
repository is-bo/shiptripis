/// The pickup handover.
///
/// One screen, two jobs, split by who is looking at it — because the two jobs
/// are opposites and putting them side by side is how a code ends up in the
/// wrong hands. The sender *reveals* a code; the traveller *types* one. There
/// is no state in which a party sees both affordances.
///
/// Three things this screen refuses to do:
///
/// * **Decide anything.** Whether a code can be shown, submitted, or is
///   already spent is read from `handover.can*` and `pickupConfirmedAt`. The
///   client never infers a permission from a deal status.
/// * **Keep the plaintext.** [RevealedCode] lives in this State object and
///   nowhere else — not in a provider, not in a route parameter, not in a
///   snackbar, not in a log. Leaving the screen destroys it.
/// * **Explain a refusal in the server's words.** Every failure branches on
///   [ApiErrorCode]; `attempts_remaining`, `locked_until` and
///   `requires_new_code` are read as structured extras into
///   [CodeAttemptOutcome] rather than parsed out of a sentence.
///
/// `recipient_not_set` gets its own copy on purpose. The traveller is standing
/// in front of the sender being told a code will not work, and the reason is
/// something only the sender can fix — so the message says that, rather than
/// implying the traveller mistyped.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/codes.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/deal.dart';
import '../../domain/handover.dart';
import '../../l10n/app_localizations.dart';

/// Handover codes are eight alphanumeric characters (`3F7KQP9M`). Declared
/// here so the entry field and the length check cannot drift apart.
const _pickupCodeLength = 8;

class PickupScreen extends ConsumerStatefulWidget {
  const PickupScreen({required this.dealId, super.key});

  final int dealId;

  @override
  ConsumerState<PickupScreen> createState() => _PickupScreenState();
}

class _PickupScreenState extends ConsumerState<PickupScreen> {
  final _code = TextEditingController();

  /// Sender-only plaintext, for as long as this screen is on screen.
  RevealedCode? _revealed;

  /// What the server said about the last rejected attempt.
  CodeAttemptOutcome? _attempt;

  String? _codeError;

  /// A refusal that is about the deal rather than about the code typed.
  String? _blocking;

  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    _revealed = null;
    super.dispose();
  }

  bool get _isLockedOut {
    final until = _attempt?.lockedUntil;
    return until != null && until.isAfter(DateTime.now());
  }

  // -------------------------------------------------------------------------
  // Sender actions
  // -------------------------------------------------------------------------

  /// [allowed] is `viewer is the sender && handover.canRevealPickupCode`,
  /// computed at the call site. Re-checked here so the guard cannot be lost by
  /// a later edit that moves the button.
  Future<void> _reveal({required bool allowed}) async {
    if (!allowed || _busy) return;
    setState(() {
      _busy = true;
      _blocking = null;
    });
    try {
      final code = await ref
          .read(handoverRepositoryProvider)
          .revealPickupCode(widget.dealId);
      if (!mounted) return;
      setState(() => _revealed = code);
    } on ApiException catch (error) {
      if (!mounted) return;
      _applyFailure(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _rotate({required bool allowed}) async {
    if (!allowed || _busy) return;
    final l = L.of(context);

    final confirmed = await confirmAction(
      context,
      title: l.codeRotateConfirmTitle,
      body: l.codeRotateConfirmBody,
      confirmLabel: l.codeRotate,
      isDestructive: true,
    );
    if (!confirmed || !mounted) return;

    setState(() {
      _busy = true;
      _blocking = null;
    });
    try {
      final code = await ref
          .read(handoverRepositoryProvider)
          .rotatePickupCode(widget.dealId);
      if (!mounted) return;
      // Rotation supersedes the previous code server-side, so the rest of the
      // app must stop believing what it last read.
      refreshVolatileState(ref);
      setState(() => _revealed = code);
      AppSnack.success(context, l.codeRotated);
    } on ApiException catch (error) {
      if (!mounted) return;
      _applyFailure(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // -------------------------------------------------------------------------
  // Traveller action
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
          .submitPickupCode(dealId: widget.dealId, code: code);
      if (!mounted) return;
      refreshVolatileState(ref);
      _code.clear();
      setState(() => _attempt = null);
      AppSnack.success(context, l.pickupConfirmedTitle);
    } on ApiException catch (error) {
      if (!mounted) return;
      _applyFailure(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // -------------------------------------------------------------------------
  // Failures
  // -------------------------------------------------------------------------

  void _applyFailure(ApiException error) {
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

    final blocking = switch (error.code) {
      ApiErrorCode.pickupAlreadyConfirmed => l.pickupAlreadyConfirmedBody,
      ApiErrorCode.dealNotFunded => l.pickupNotFundedBody,
      ApiErrorCode.dealNotPickupReady => l.pickupNotReadyBody,
      ApiErrorCode.recipientNotSet => l.recipientRequiredTravelerBody,
      _ => error.kind == ApiFailureKind.forbidden ? l.stateForbiddenBody : null,
    };

    if (blocking != null) {
      // The screen is describing a world that moved. Re-read it rather than
      // leaving the user with a stale set of buttons.
      if (error.isStale) refreshVolatileState(ref);
      setState(() {
        _blocking = blocking;
        _codeError = null;
        _revealed = null;
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
    final isConfirmed = handover?.isPickupConfirmed ?? false;

    // The reveal is gated on both facts, and the same expression feeds the
    // button and the action it calls.
    final canReveal =
        isSender && !isConfirmed && (handover?.canRevealPickupCode ?? false);
    final canSubmit =
        deal != null &&
        viewerId != null &&
        !isSender &&
        !isConfirmed &&
        (handover?.canSubmitPickupCode ?? false);

    Widget? footer;
    if (canReveal && _revealed == null) {
      footer = AppButton(
        label: l.pickupSenderReveal,
        icon: Icons.visibility_rounded,
        isLoading: _busy,
        onPressed: () => _reveal(allowed: canReveal),
      );
    } else if (canSubmit) {
      footer = AppButton(
        label: l.pickupConfirmAction,
        isLoading: _busy,
        onPressed: _isLockedOut ? null : _submit,
      );
    }

    return DismissKeyboardOnTap(
      child: AppScaffold(
        topBar: AppTopBar(title: l.pickupTitle, showBack: true),
        footer: footer,
        body: AsyncView<Deal>(
          value: value,
          onRetry: () => ref.invalidate(dealDetailProvider(widget.dealId)),
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpace.gutter),
            child: SkeletonDetail(),
          ),
          data: (loaded) {
            if (viewerId == null) return const SkeletonDetail();
            return ListView(
              padding: footer == null
                  ? AppScrollPadding.page(context)
                  : AppScrollPadding.pageWithFooter(context),
              children: _sections(
                loaded,
                viewerId: viewerId,
                canReveal: canReveal,
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
    required int viewerId,
    required bool canReveal,
    required bool canSubmit,
  }) {
    final l = L.of(context);
    final isSender = deal.isSender(viewerId);
    final handover = deal.handover;

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

      if (handover?.isPickupConfirmed ?? false)
        ..._confirmed(deal, isSender: isSender)
      else if (isSender)
        ..._senderSections(canReveal: canReveal)
      else
        ..._travelerSections(canSubmit: canSubmit),
    ];
  }

  // -------------------------------------------------------------------------
  // Sender
  // -------------------------------------------------------------------------

  List<Widget> _senderSections({required bool canReveal}) {
    final l = L.of(context);
    final revealed = _revealed;

    return [
      AppInsetGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l.pickupSenderTitle,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: AppSpace.sm),
            Text(
              l.pickupSenderExplainer,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: AppSpace.lg),

      // The single most important sentence on this screen: a code sent by
      // message is a code that confirms a pickup that never happened.
      InfoNotice(
        message: l.pickupSenderWarning,
        tone: StatusTone.action,
        icon: Icons.record_voice_over_rounded,
      ),

      if (revealed != null) ...[
        const SizedBox(height: AppSpace.xl),
        CodeDisplay(
          // `code` is the plaintext that gets copied and spelled out;
          // `formatted` is the server's own grouping for reading aloud.
          code: revealed.code,
          formatted: revealed.formatted,
          label: l.pickupCodeLabel,
          caption: l.codeCopyForReading,
          onCopy: () => AppSnack.info(context, l.actionCopied),
        ),
      ],

      if (canReveal) ...[
        const SizedBox(height: AppSpace.lg),
        AppButton(
          label: l.codeRotate,
          icon: Icons.autorenew_rounded,
          variant: AppButtonVariant.tertiary,
          expand: false,
          onPressed: _busy ? null : () => _rotate(allowed: canReveal),
        ),
      ] else if (revealed == null) ...[
        const SizedBox(height: AppSpace.xl),
        AppEmptyState(
          title: l.pickupAwaitingTitle,
          body: l.pickupAwaitingSenderBody,
          icon: Icons.inventory_2_outlined,
          compact: true,
        ),
      ],
    ];
  }

  // -------------------------------------------------------------------------
  // Traveller
  // -------------------------------------------------------------------------

  List<Widget> _travelerSections({required bool canSubmit}) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final lockedUntil = _attempt?.lockedUntil;

    if (!canSubmit) {
      return [
        AppEmptyState(
          title: l.pickupAwaitingTitle,
          body: l.pickupAwaitingTravelerBody,
          icon: Icons.inventory_2_outlined,
        ),
      ];
    }

    return [
      AppInsetGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l.pickupTravelerTitle,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: AppSpace.sm),
            Text(
              l.pickupTravelerExplainer,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: AppSpace.xl),

      CodeEntryField(
        controller: _code,
        label: l.pickupCodeLabel,
        length: _pickupCodeLength,
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
          // The lockout expiring only re-enables the field. Whether the code
          // works remains entirely the server's answer.
          onElapsed: () {
            if (mounted) setState(() {});
          },
        ),
      ],
    ];
  }

  // -------------------------------------------------------------------------
  // Confirmed
  // -------------------------------------------------------------------------

  List<Widget> _confirmed(Deal deal, {required bool isSender}) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final handover = deal.handover;
    final at = handover?.pickupConfirmedAt ?? deal.pickupConfirmedAt;
    final availableAt =
        handover?.deliveryCodeAvailableAt ?? deal.deliveryCodeAvailableAt;
    final waiting = handover?.inDeliveryCodeBuffer ?? false;

    return [
      AppCard(
        accent: StatusTone.good,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            StatusPill(
              label: l.pickupConfirmedTitle,
              tone: StatusTone.good,
              icon: Icons.check_circle_rounded,
            ),
            const SizedBox(height: AppSpace.md),
            Text(
              l.pickupConfirmedBody,
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
      const SizedBox(height: AppSpace.xl),

      SectionHeader(title: l.pickupNextTitle),
      if (waiting)
        LockedCodePanel(
          title: l.deliverySafetyWaitingTitle,
          body: isSender
              ? l.deliverySafetyWaitingSenderBody
              : l.deliverySafetyWaitingTravelerBody,
          availableAt: availableAt,
          onAvailable: availableAt == null
              ? null
              : () => ref.invalidate(dealDetailProvider(deal.id)),
        )
      else
        InfoNotice(
          message: isSender
              ? l.pickupConfirmedSenderNext
              : l.pickupConfirmedTravelerNext,
          tone: StatusTone.progress,
          icon: Icons.schedule_rounded,
        ),
      const SizedBox(height: AppSpace.lg),

      AppButton(
        label: l.pickupGoToDeliveryAction,
        variant: AppButtonVariant.secondary,
        icon: Icons.arrow_forward_rounded,
        onPressed: () => context.openDelivery(deal.id),
      ),
    ];
  }
}
