/// Loading, empty, error and offline states.
///
/// Three rules this file exists to enforce:
///
/// 1. **A failure is never rendered from server prose.** Copy is chosen from
///    the structured [ApiFailureKind] and [ApiErrorCode], never from the
///    server's `detail` string, which is English-only and written for
///    engineers. `serverDetail` is deliberately unreachable from here.
///
/// 2. **Loading has a shape.** A list loads as skeleton rows, a detail screen
///    as a skeleton of itself. A centred spinner over a blank screen tells the
///    user nothing about what is coming and makes every screen feel identical.
///    The spinner survives only where the wait is genuinely indeterminate and
///    brief — inside a button.
///
/// 3. **A failure states what the user can do next.** Every error view carries
///    an action or explicitly says none is needed. "Something went wrong" with
///    no way forward is a dead end.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../l10n/app_localizations.dart';
import '../tokens.dart';
import 'primitives.dart';
import 'status.dart';

// ---------------------------------------------------------------------------
// Failure copy
// ---------------------------------------------------------------------------

/// User-facing description of a failure.
@immutable
class FailureCopy {
  const FailureCopy({
    required this.title,
    required this.body,
    required this.icon,
    required this.tone,
    this.canRetry = true,
    this.isSessionExpired = false,
  });

  final String title;
  final String body;
  final IconData icon;
  final StatusTone tone;

  /// False where retrying the same call cannot succeed — a 403, a 404, a
  /// retired surface. Offering "Try again" there is a lie.
  final bool canRetry;

  /// The caller should route to sign-in rather than render this.
  final bool isSessionExpired;
}

/// Maps any thrown object to copy the user can act on.
///
/// Unknown objects fall through to the generic case rather than leaking a
/// `toString()`. That is deliberate: a Dart error message on a payment screen
/// is both unreadable and a small information disclosure.
FailureCopy describeFailure(BuildContext context, Object? error) {
  final l = L.of(context);

  if (error is! ApiException) {
    return FailureCopy(
      title: l.stateUnexpectedTitle,
      body: l.stateUnexpectedBody,
      icon: Icons.error_outline_rounded,
      tone: StatusTone.bad,
    );
  }

  // A stale-state failure is not really an error: the server is telling us the
  // screen is out of date. It gets its own calmer treatment.
  if (error.code.impliesStaleClientState) {
    return FailureCopy(
      title: l.staleTitle,
      body: staleMessage(context, error.code),
      icon: Icons.sync_problem_rounded,
      tone: StatusTone.waiting,
    );
  }

  if (error.code.isRetiredSurface) {
    return FailureCopy(
      title: l.stateAppOutdatedTitle,
      body: l.stateAppOutdatedBody,
      icon: Icons.system_update_rounded,
      tone: StatusTone.waiting,
      canRetry: false,
    );
  }

  if (error.code.isProviderUnavailable) {
    return FailureCopy(
      title: l.paymentProviderUnavailable,
      body: l.paymentNoProvidersBody,
      icon: Icons.credit_card_off_rounded,
      tone: StatusTone.waiting,
    );
  }

  return switch (error.kind) {
    ApiFailureKind.offline => FailureCopy(
      title: l.stateOfflineTitle,
      body: l.stateOfflineBody,
      icon: Icons.wifi_off_rounded,
      tone: StatusTone.waiting,
    ),
    ApiFailureKind.timeout => FailureCopy(
      title: l.stateTimeoutTitle,
      body: l.stateTimeoutBody,
      icon: Icons.schedule_rounded,
      tone: StatusTone.waiting,
    ),
    ApiFailureKind.unauthenticated => FailureCopy(
      title: l.stateSessionExpiredTitle,
      body: l.stateSessionExpiredBody,
      icon: Icons.lock_outline_rounded,
      tone: StatusTone.waiting,
      canRetry: false,
      isSessionExpired: true,
    ),
    ApiFailureKind.forbidden => FailureCopy(
      title: l.stateForbiddenTitle,
      body: l.stateForbiddenBody,
      icon: Icons.block_rounded,
      tone: StatusTone.bad,
      canRetry: false,
    ),
    ApiFailureKind.notFound || ApiFailureKind.gone => FailureCopy(
      title: l.stateNotFoundTitle,
      body: l.stateNotFoundBody,
      icon: Icons.search_off_rounded,
      tone: StatusTone.neutral,
      canRetry: false,
    ),
    ApiFailureKind.rateLimited => FailureCopy(
      title: l.stateRateLimitedTitle,
      // The backend's throttles are distributed, so when it sends a
      // `Retry-After` the number is real and shared across every instance.
      // Saying "wait a moment" when the server told us "wait ninety seconds"
      // is the difference between a user who waits and one who force-quits.
      body: switch (error.retryAfter) {
        final Duration d => l.stateRateLimitedWait(d.inSeconds),
        _ => l.stateRateLimitedBody,
      },
      icon: Icons.hourglass_top_rounded,
      tone: StatusTone.waiting,
    ),
    ApiFailureKind.validation || ApiFailureKind.conflict => FailureCopy(
      title: l.staleTitle,
      body: staleMessage(context, error.code),
      icon: Icons.info_outline_rounded,
      tone: StatusTone.waiting,
    ),
    ApiFailureKind.server ||
    ApiFailureKind.malformed ||
    ApiFailureKind.cancelled => FailureCopy(
      title: l.stateServerErrorTitle,
      body: l.stateServerErrorBody,
      icon: Icons.cloud_off_rounded,
      tone: StatusTone.bad,
    ),
  };
}

/// Copy for a stale-state code — the server refused because the client's view
/// of the world has moved on.
///
/// Every branch is keyed on a machine code. No English server string is ever
/// parsed to reach one of these.
String staleMessage(BuildContext context, ApiErrorCode code) {
  final l = L.of(context);
  return switch (code.raw) {
    'request_not_open' => l.staleRequestNotOpen,
    'request_already_matched' => l.staleRequestAlreadyMatched,
    'journey_not_active' => l.staleJourneyNotActive,
    'offer_not_pending' => l.staleOfferNotPending,
    'match_not_pending' => l.staleMatchNotPending,
    'capacity_exceeded' => l.staleCapacityExceeded,
    'reward_below_minimum' => l.staleRewardBelowMinimum,
    'route_inputs_changed' || 'route_preflight_missing' => l.staleRouteChanged,
    'kyc_not_verified' || 'kyc_invalid' => l.staleKycInvalid,
    'flight_proof_not_approved' => l.staleFlightProofInvalid,
    'reservation_expired' ||
    'invalid_reservation_grace' => l.staleReservationExpired,
    'deal_closed' => l.staleDealClosed,
    'offer_expired' => l.staleOfferExpired,
    _ => l.staleRefreshAction,
  };
}

// ---------------------------------------------------------------------------
// Full-surface states
// ---------------------------------------------------------------------------

/// The empty state for a whole screen or a whole tab.
///
/// A soft disc behind a single glyph, not an illustration: three languages and
/// a dark theme make bespoke artwork expensive to keep honest, and an
/// illustration that has drifted from the copy is worse than no illustration.
class AppEmptyState extends StatelessWidget {
  const AppEmptyState({
    required this.title,
    required this.body,
    required this.icon,
    this.actionLabel,
    this.onAction,
    this.secondaryLabel,
    this.onSecondary,
    this.compact = false,
    super.key,
  });

  final String title;
  final String body;
  final IconData icon;
  final String? actionLabel;
  final VoidCallback? onAction;
  final String? secondaryLabel;
  final VoidCallback? onSecondary;

  /// Tighter, for a state inside a card or a section rather than a page.
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final content = Padding(
      padding: EdgeInsets.symmetric(
        horizontal: AppSpace.gutter,
        vertical: compact ? AppSpace.xxl : AppSpace.x5l,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: compact ? 48 : 64,
            height: compact ? 48 : 64,
            decoration: BoxDecoration(
              color: c.surfaceSunken,
              shape: BoxShape.circle,
            ),
            child: Icon(icon, size: compact ? 22 : 28, color: c.textTertiary),
          ),
          SizedBox(height: compact ? AppSpace.md : AppSpace.lg),
          Text(title, style: text.titleMedium, textAlign: TextAlign.center),
          const SizedBox(height: AppSpace.sm),
          Text(
            body,
            style: text.bodyMedium?.copyWith(color: c.textSecondary),
            textAlign: TextAlign.center,
          ),
          if (actionLabel != null && onAction != null) ...[
            SizedBox(height: compact ? AppSpace.lg : AppSpace.xxl),
            AppButton(label: actionLabel!, onPressed: onAction, expand: false),
          ],
          if (secondaryLabel != null && onSecondary != null) ...[
            const SizedBox(height: AppSpace.sm),
            AppButton(
              label: secondaryLabel!,
              onPressed: onSecondary,
              variant: AppButtonVariant.tertiary,
              expand: false,
            ),
          ],
        ],
      ),
    );

    // A compact state sits inside somebody else's layout and must not bring a
    // scroll view of its own.
    if (compact) return content;

    // A full-surface state is often the direct child of a RefreshIndicator,
    // and an error page you cannot pull to refresh is a dead end at exactly
    // the moment the user wants a way out. Scrollable, always-scrollable
    // physics, and tall enough to centre.
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(child: content),
        ),
      ),
    );
  }
}

/// The error state for a whole screen or a whole tab.
class AppErrorState extends StatelessWidget {
  const AppErrorState({
    required this.error,
    this.onRetry,
    this.onSignIn,
    this.compact = false,
    super.key,
  });

  final Object? error;
  final VoidCallback? onRetry;

  /// Called instead of [onRetry] when the session has expired.
  final VoidCallback? onSignIn;

  final bool compact;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final copy = describeFailure(context, error);
    final showSignIn = copy.isSessionExpired && onSignIn != null;

    return AppEmptyState(
      title: copy.title,
      body: copy.body,
      icon: copy.icon,
      compact: compact,
      actionLabel: showSignIn
          ? l.authSignIn
          : (copy.canRetry && onRetry != null ? l.actionRetry : null),
      onAction: showSignIn ? onSignIn : (copy.canRetry ? onRetry : null),
    );
  }
}

/// A compact failure strip for one section of an otherwise working screen.
///
/// Used where the rest of the page is still valid — a count that failed to
/// load, a secondary list. Replacing the whole screen there would throw away
/// good content because of a minor call.
class InlineFailure extends StatelessWidget {
  const InlineFailure({required this.error, this.onRetry, super.key});

  final Object? error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final copy = describeFailure(context, error);
    return InfoNotice(
      title: copy.title,
      message: copy.body,
      tone: copy.tone,
      icon: copy.icon,
      actionLabel: copy.canRetry && onRetry != null ? l.actionRetry : null,
      onAction: onRetry,
    );
  }
}

// ---------------------------------------------------------------------------
// Skeletons
// ---------------------------------------------------------------------------

/// A shimmering placeholder block.
///
/// The sheen stops entirely under Reduce Motion — a looping animation is one
/// of the exact things that setting exists to suppress — and degrades to a
/// flat tone, which still reads as "not content yet".
class SkeletonBox extends StatefulWidget {
  const SkeletonBox({
    this.width,
    this.height = 14,
    this.radius = AppRadius.rXs,
    super.key,
  });

  final double? width;
  final double height;
  final BorderRadius radius;

  @override
  State<SkeletonBox> createState() => _SkeletonBoxState();
}

class _SkeletonBoxState extends State<SkeletonBox>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1200),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _controller.stop();
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final reduced = MediaQuery.disableAnimationsOf(context);

    final box = Container(
      width: widget.width,
      height: widget.height,
      decoration: BoxDecoration(color: c.skeleton, borderRadius: widget.radius),
    );

    if (reduced) return ExcludeSemantics(child: box);

    return ExcludeSemantics(
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) => ShaderMask(
          blendMode: BlendMode.srcATop,
          shaderCallback: (bounds) {
            final t = _controller.value * 2 - 0.5;
            return LinearGradient(
              begin: Alignment(t - 0.6, 0),
              end: Alignment(t + 0.6, 0),
              colors: [c.skeleton, c.skeletonSheen, c.skeleton],
            ).createShader(bounds);
          },
          child: box,
        ),
      ),
    );
  }
}

/// A run of skeleton lines with a naturally ragged right edge.
class SkeletonLines extends StatelessWidget {
  const SkeletonLines({this.count = 3, this.spacing = AppSpace.sm, super.key});

  final int count;
  final double spacing;

  static const _widths = [1.0, 0.92, 0.66, 0.85, 0.74];

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final max = constraints.maxWidth.isFinite ? constraints.maxWidth : 280.0;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < count; i++) ...[
            if (i > 0) SizedBox(height: spacing),
            SkeletonBox(width: max * _widths[i % _widths.length], height: 12),
          ],
        ],
      );
    },
  );
}

/// The loading shape of a list of cards.
class SkeletonCardList extends StatelessWidget {
  const SkeletonCardList({this.count = 3, super.key});

  final int count;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return Semantics(
      label: l.a11yLoadingContent,
      liveRegion: true,
      child: Column(
        children: [
          for (var i = 0; i < count; i++) ...[
            if (i > 0) const SizedBox(height: AppSpace.md),
            const AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      SkeletonBox(
                        width: 36,
                        height: 36,
                        radius: AppRadius.rPill,
                      ),
                      SizedBox(width: AppSpace.md),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            SkeletonBox(width: 140, height: 13),
                            SizedBox(height: AppSpace.sm),
                            SkeletonBox(width: 84, height: 11),
                          ],
                        ),
                      ),
                    ],
                  ),
                  SizedBox(height: AppSpace.lg),
                  SkeletonLines(count: 2),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// The loading shape of a detail screen: a heading, a block, some rows.
class SkeletonDetail extends StatelessWidget {
  const SkeletonDetail({super.key});

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        const content = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SkeletonBox(width: 180, height: 22),
            SizedBox(height: AppSpace.lg),
            SkeletonBox(height: 96, radius: AppRadius.rLg),
            SizedBox(height: AppSpace.xl),
            SkeletonLines(count: 4),
            SizedBox(height: AppSpace.xl),
            SkeletonBox(height: 72, radius: AppRadius.rLg),
          ],
        );

        // Most loading states are children of a ListView and intentionally
        // receive an unbounded height. A few full-screen states (for example
        // the recipient form) hand us the viewport's finite height directly;
        // those must be scrollable because the detail skeleton is taller than
        // a short landscape viewport. Keeping the scroll root here makes the
        // fix apply to every screen without per-screen height arithmetic or
        // changing the Phase 5C skeleton proportions.
        final body = constraints.maxHeight.isFinite
            ? SingleChildScrollView(
                padding: const EdgeInsets.only(bottom: AppSpace.xl),
                child: content,
              )
            : content;

        return Semantics(
          label: l.a11yLoadingContent,
          liveRegion: true,
          child: body,
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// AsyncValue plumbing
// ---------------------------------------------------------------------------

/// Renders an [AsyncValue] with the right state for each case.
///
/// Keeps the previous data on screen during a refresh instead of flashing back
/// to a skeleton, which is what a naive `when` does and what makes a
/// pull-to-refresh feel like a full page reload.
class AsyncView<T> extends StatelessWidget {
  const AsyncView({
    required this.value,
    required this.data,
    this.loading,
    this.error,
    this.onRetry,
    this.onSignIn,
    super.key,
  });

  final AsyncValue<T> value;
  final Widget Function(T data) data;
  final Widget Function()? loading;
  final Widget Function(Object error)? error;
  final VoidCallback? onRetry;
  final VoidCallback? onSignIn;

  @override
  Widget build(BuildContext context) {
    final current = value;

    // Data we already have always wins, refresh or failure notwithstanding.
    if (current.hasValue) return data(current.requireValue);

    if (current.hasError) {
      final err = current.error;
      return error?.call(err!) ??
          AppErrorState(error: err, onRetry: onRetry, onSignIn: onSignIn);
    }

    return loading?.call() ?? const SkeletonCardList();
  }
}

// ---------------------------------------------------------------------------
// Offline
// ---------------------------------------------------------------------------

/// A persistent strip shown while the last call failed for want of a network.
///
/// Deliberately not a snackbar: the condition lasts, and a snackbar that has
/// already gone leaves the user staring at stale content with no explanation.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({required this.isOffline, this.onRetry, super.key});

  final bool isOffline;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return AnimatedSize(
      duration: AppMotion.respecting(context, AppMotion.fast),
      alignment: Alignment.topCenter,
      child: !isOffline
          ? const SizedBox(width: double.infinity)
          : Semantics(
              liveRegion: true,
              child: Material(
                color: c.waitingSoft,
                child: SafeArea(
                  bottom: false,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpace.gutter,
                      vertical: AppSpace.sm,
                    ),
                    child: Row(
                      children: [
                        Icon(
                          Icons.wifi_off_rounded,
                          size: 16,
                          color: c.onWaitingSoft,
                        ),
                        const SizedBox(width: AppSpace.sm),
                        Expanded(
                          child: Text(
                            l.stateOfflineTitle,
                            style: Theme.of(context).textTheme.labelMedium
                                ?.copyWith(color: c.onWaitingSoft),
                          ),
                        ),
                        if (onRetry != null)
                          TextButton(
                            onPressed: onRetry,
                            child: Text(l.actionRetry),
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
    );
  }
}

// ---------------------------------------------------------------------------
// Snackbars
// ---------------------------------------------------------------------------

/// Transient confirmations and failures.
///
/// Only for outcomes the user can afford to miss. Anything that changes what
/// they must do next belongs on the screen, not in a bar that disappears.
abstract final class AppSnack {
  static void success(BuildContext context, String message) =>
      _show(context, message, Icons.check_circle_outline_rounded, null);

  static void info(BuildContext context, String message) =>
      _show(context, message, Icons.info_outline_rounded, null);

  static void failure(BuildContext context, Object? error, {String? fallback}) {
    final copy = describeFailure(context, error);
    _show(context, fallback ?? copy.body, copy.icon, context.colors.danger);
  }

  static void _show(
    BuildContext context,
    String message,
    IconData icon,
    Color? accent,
  ) {
    final messenger = ScaffoldMessenger.maybeOf(context);
    if (messenger == null) return;
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Row(
            children: [
              Icon(
                icon,
                size: 18,
                color: accent ?? context.colors.textOnInverse,
              ),
              const SizedBox(width: AppSpace.md),
              Expanded(child: Text(message)),
            ],
          ),
          duration: const Duration(seconds: 4),
        ),
      );
  }
}
