import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/verification/verification_providers.dart';
import '../../core/verification/verification_repository.dart';
import '../../shared/widgets/primary_button.dart';

/// Sender's screen for issuing a handover code.
///
/// Two phases:
///   PICKUP   -- when the match is `accepted`, sender asks the traveler to
///               present this code at parcel pickup.
///   DELIVERY -- when the match is `in_transit`, sender (or recipient)
///               reads this code to the traveler at drop-off; verifying it
///               pays out the traveler from escrow.
///
/// The plaintext code is shown ONCE -- we never persist it on device.
/// If the user re-opens the screen they must re-issue (rotates).
class HandoverIssueScreen extends ConsumerStatefulWidget {
  const HandoverIssueScreen({
    super.key,
    required this.matchId,
    required this.kind,
  });

  final int matchId;
  final HandoverKind kind;

  @override
  ConsumerState<HandoverIssueScreen> createState() =>
      _HandoverIssueScreenState();
}

class _HandoverIssueScreenState extends ConsumerState<HandoverIssueScreen> {
  IssuedCode? _issued;
  String? _error;
  bool _busy = false;

  String get _title => switch (widget.kind) {
        HandoverKind.pickup => 'Pickup code',
        HandoverKind.delivery => 'Delivery code',
      };

  String get _blurb => switch (widget.kind) {
        HandoverKind.pickup =>
          'Show this code to the traveler in person at pickup. They will enter it on their device to confirm they have your parcel.',
        HandoverKind.delivery =>
          'When the traveler arrives, read this code to them. Once they verify it, payment is released from escrow.',
      };

  Future<void> _issue() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final issued = await ref
          .read(verificationRepositoryProvider)
          .issue(matchId: widget.matchId, kind: widget.kind);
      if (!mounted) return;
      setState(() => _issued = issued);
    } on VerificationFailure catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      appBar: AppBar(
        backgroundColor: AppColors.parchment,
        foregroundColor: AppColors.ink,
        elevation: 0,
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
                child: Center(
                  child: _issued != null
                      ? _CodeReveal(code: _issued!.code, kind: widget.kind)
                      : _ReadyToIssue(error: _error),
                ),
              ),
              const SizedBox(height: 16),
              if (_issued == null)
                PrimaryButton(
                  label: _busy ? 'Generating…' : 'Generate code',
                  expand: true,
                  onTap: _busy ? null : _issue,
                )
              else
                PrimaryButton(
                  label: 'Regenerate (invalidates current)',
                  expand: true,
                  color: AppColors.terracotta,
                  onTap: _busy ? null : _issue,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ReadyToIssue extends StatelessWidget {
  const _ReadyToIssue({this.error});
  final String? error;

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
          child: Icon(Icons.qr_code_2,
              size: 44, color: AppColors.goldDeep),
        ),
        const SizedBox(height: 18),
        Text(
          'Generate a one-time code',
          style: AppType.display(18),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 6),
        Text(
          'You can regenerate at any time. Only the latest code is valid.',
          style: AppType.body(13, color: AppColors.inkMute),
          textAlign: TextAlign.center,
        ),
        if (error != null) ...[
          const SizedBox(height: 18),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: AppColors.danger.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(AppRadius.md),
              border: Border.all(color: AppColors.danger.withValues(alpha: 0.3)),
            ),
            child: Text(
              error!,
              style: AppType.body(13, color: AppColors.danger),
              textAlign: TextAlign.center,
            ),
          ),
        ],
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
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Text(
            'This code is shown only once. We never see it again after you close this screen — regenerate if you forget it.',
            style: AppType.body(12, color: AppColors.inkMute),
            textAlign: TextAlign.center,
          ),
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
      child: Text(d, style: AppType.mono(28, color: AppColors.emeraldDeep, w: FontWeight.w700)),
    );
  }
}
