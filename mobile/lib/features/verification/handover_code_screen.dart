import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/verification/verification_providers.dart';
import '../../core/verification/verification_repository.dart';
import '../../core/ws/live_event_router.dart';
import '../../shared/util/safe_back.dart';
import '../../shared/widgets/primary_button.dart';

/// Read-only "show your pickup code" screen.
///
/// Unlike [HandoverIssueScreen], this screen never rotates the code. It
/// verifies an ACTIVE code exists on the server and renders the plaintext
/// from the WS-delivered cache in [LiveEventState.codesByMatch]. The user
/// can return to this screen as many times as they want and always see
/// the same digits.
///
/// Flow:
///   1. Sender pays → server auto-issues a PICKUP code and publishes
///      `handover.code_issued` over WS → mobile caches plaintext.
///   2. Sender lands here, taps "View pickup code" from My Requests, or
///      navigates from Match Detail — all paths show the same plaintext.
///   3. If plaintext isn't in the cache (cold reinstall, app killed before
///      the WS event arrived), the GET endpoint confirms a code exists
///      but we can't show the digits — surface a clear empty-state with
///      a one-tap "regenerate" escape hatch.
class HandoverCodeScreen extends ConsumerStatefulWidget {
  const HandoverCodeScreen({
    super.key,
    required this.matchId,
    required this.kind,
  });

  final int matchId;
  final HandoverKind kind;

  @override
  ConsumerState<HandoverCodeScreen> createState() =>
      _HandoverCodeScreenState();
}

class _HandoverCodeScreenState extends ConsumerState<HandoverCodeScreen> {
  ActiveCodeInfo? _info;
  String? _error;
  bool _loading = true;
  bool _rotating = false;

  String get _title => switch (widget.kind) {
        HandoverKind.pickup => 'Pickup code',
        HandoverKind.delivery => 'Delivery code',
      };

  String get _blurb => switch (widget.kind) {
        HandoverKind.pickup =>
          'Show this to the traveler when they pick up your parcel. You can come back here anytime — we won\'t change it.',
        HandoverKind.delivery =>
          'Read this to the traveler at drop-off. Verifying it releases payment from escrow.',
      };

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _refresh());
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final info = await ref
          .read(verificationRepositoryProvider)
          .getActiveCode(matchId: widget.matchId, kind: widget.kind);
      if (!mounted) return;
      setState(() => _info = info);
    } on VerificationFailure catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _rotate() async {
    setState(() {
      _rotating = true;
      _error = null;
    });
    try {
      await ref
          .read(verificationRepositoryProvider)
          .issue(matchId: widget.matchId, kind: widget.kind);
      // The WS event will populate codesByMatch; small delay for round-trip.
      await Future<void>.delayed(const Duration(milliseconds: 300));
      await _refresh();
    } on VerificationFailure catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _rotating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final live = liveCodeFor(ref, widget.matchId);
    final hasMatchingLive =
        live != null && live.kind == widget.kind.wire;

    return Scaffold(
      backgroundColor: AppColors.parchment,
      appBar: AppBar(
        backgroundColor: AppColors.parchment,
        foregroundColor: AppColors.ink,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () => safeBack(context, fallback: '/sender/requests'),
        ),
        title: Text(_title, style: AppType.display(18)),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(_blurb, style: AppType.body(14, color: AppColors.inkSoft)),
              const SizedBox(height: 24),
              Expanded(
                child: Center(child: _buildBody(hasMatchingLive, live)),
              ),
              const SizedBox(height: 16),
              if (_info != null && !hasMatchingLive)
                PrimaryButton(
                  label: _rotating ? 'Regenerating…' : 'Regenerate code',
                  expand: true,
                  color: AppColors.terracotta,
                  onTap: _rotating ? null : _rotate,
                )
              else
                PrimaryButton(
                  label: 'Done',
                  expand: true,
                  // Same contract as the AppBar back arrow: pop when there's a
                  // screen below, else fall back. Previously this did
                  // `context.go('/sender/requests')`, which replaced the stack
                  // and left the user on a top-level route with nothing to pop
                  // — the next back press quit the app.
                  onTap: () =>
                      safeBack(context, fallback: '/sender/requests'),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBody(bool hasLive, LiveHandoverCode? live) {
    if (_loading) {
      return const CircularProgressIndicator();
    }
    if (_error != null && _info == null) {
      return _ErrorState(message: _error!, onRetry: _refresh);
    }
    if (_info == null) {
      return _NoCodeYet(onIssue: _rotate, busy: _rotating);
    }
    if (hasLive && live != null) {
      return _CodeReveal(code: live.code, kind: widget.kind);
    }
    return _CodeLostState(info: _info!);
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.cloud_off, size: 48, color: AppColors.inkMute),
        const SizedBox(height: 12),
        Text(message,
            style: AppType.body(14, color: AppColors.danger),
            textAlign: TextAlign.center),
        const SizedBox(height: 12),
        TextButton(onPressed: onRetry, child: const Text('Try again')),
      ],
    );
  }
}

class _NoCodeYet extends StatelessWidget {
  const _NoCodeYet({required this.onIssue, required this.busy});
  final VoidCallback onIssue;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 88,
          height: 88,
          decoration: BoxDecoration(
            color: AppColors.gold.withValues(alpha: 0.12),
            shape: BoxShape.circle,
            border: Border.all(color: AppColors.gold, width: 1.5),
          ),
          child: Icon(Icons.hourglass_empty,
              size: 44, color: AppColors.goldDeep),
        ),
        const SizedBox(height: 18),
        Text(
          'Code on the way',
          style: AppType.display(18),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 6),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Text(
            'We auto-issue your pickup code right after payment. If you don\'t see it in a moment, generate one manually.',
            style: AppType.body(13, color: AppColors.inkMute),
            textAlign: TextAlign.center,
          ),
        ),
        const SizedBox(height: 16),
        TextButton.icon(
          onPressed: busy ? null : onIssue,
          icon: const Icon(Icons.refresh, size: 16),
          label: Text(busy ? 'Generating…' : 'Generate now'),
        ),
      ],
    );
  }
}

/// Server says a code is active but mobile lost the plaintext (cold install,
/// missed WS event). Single, friendly path: regenerate.
class _CodeLostState extends StatelessWidget {
  const _CodeLostState({required this.info});
  final ActiveCodeInfo info;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.lock_outline, size: 48, color: AppColors.goldDeep),
        const SizedBox(height: 12),
        Text(
          'Your code is safe on the server',
          style: AppType.display(16),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Text(
            'For your security we only show pickup codes once. Tap below to issue a fresh one — the old one becomes invalid.',
            style: AppType.body(13, color: AppColors.inkMute),
            textAlign: TextAlign.center,
          ),
        ),
      ],
    );
  }
}

class _CodeReveal extends StatelessWidget {
  const _CodeReveal({required this.code, required this.kind});
  final String code;
  final HandoverKind kind;

  String get _kindLabel => switch (kind) {
        HandoverKind.pickup => 'PICKUP',
        HandoverKind.delivery => 'DELIVERY',
      };

  @override
  Widget build(BuildContext context) {
    final digits = code.split('');
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: AppColors.emerald,
            borderRadius: BorderRadius.circular(AppRadius.pill),
          ),
          child: Text(
            _kindLabel,
            style: AppType.eyebrow(color: AppColors.parchmentSoft),
          ),
        ),
        const SizedBox(height: 18),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            for (var i = 0; i < digits.length; i++) ...[
              _Digit(d: digits[i]),
              if (i < digits.length - 1) const SizedBox(width: 8),
            ],
          ],
        ),
        const SizedBox(height: 14),
        TextButton.icon(
          onPressed: () {
            Clipboard.setData(ClipboardData(text: code));
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Code copied')),
            );
          },
          icon: const Icon(Icons.copy, size: 16),
          label: const Text('Copy'),
        ),
      ],
    );
  }
}

class _Digit extends StatelessWidget {
  const _Digit({required this.d});
  final String d;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 44,
      height: 60,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.gold, width: 1.5),
      ),
      child: Text(d,
          style: AppType.mono(28,
              color: AppColors.emeraldDeep, w: FontWeight.w700)),
    );
  }
}
