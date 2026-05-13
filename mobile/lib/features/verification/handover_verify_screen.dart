import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/verification/verification_providers.dart';
import '../../core/verification/verification_repository.dart';
import '../../shared/widgets/primary_button.dart';

/// Traveler's screen for entering a handover code.
///
///   PICKUP   -- entered when collecting the parcel from the sender.
///   DELIVERY -- entered when handing the parcel to the recipient.
///                Successful DELIVERY verification releases escrow to
///                the traveler (server-side, via the wallet signal).
class HandoverVerifyScreen extends ConsumerStatefulWidget {
  const HandoverVerifyScreen({
    super.key,
    required this.matchId,
    required this.kind,
  });

  final int matchId;
  final HandoverKind kind;

  @override
  ConsumerState<HandoverVerifyScreen> createState() =>
      _HandoverVerifyScreenState();
}

class _HandoverVerifyScreenState extends ConsumerState<HandoverVerifyScreen> {
  final _ctl = TextEditingController();
  final _focus = FocusNode();
  bool _busy = false;
  String? _error;
  bool _success = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _focus.requestFocus());
  }

  @override
  void dispose() {
    _ctl.dispose();
    _focus.dispose();
    super.dispose();
  }

  String get _title => switch (widget.kind) {
        HandoverKind.pickup => 'Enter pickup code',
        HandoverKind.delivery => 'Enter delivery code',
      };

  String get _blurb => switch (widget.kind) {
        HandoverKind.pickup =>
          'Ask the sender for the 6-digit code shown on their screen. Entering it here confirms you have collected the parcel.',
        HandoverKind.delivery =>
          'Ask the recipient for the 6-digit code shown on the sender\'s screen. Once verified, your payment is released from escrow.',
      };

  Future<void> _verify() async {
    final code = _ctl.text.trim();
    if (code.length != 6 || int.tryParse(code) == null) {
      setState(() => _error = 'Enter the 6-digit code.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(verificationRepositoryProvider).verify(
            matchId: widget.matchId,
            kind: widget.kind,
            code: code,
          );
      if (!mounted) return;
      setState(() => _success = true);
    } on VerificationFailure catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _ctl.clear();
      });
      _focus.requestFocus();
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
          child: _success ? _SuccessView(kind: widget.kind) : _EntryView(
            blurb: _blurb,
            ctl: _ctl,
            focus: _focus,
            error: _error,
            busy: _busy,
            onSubmit: _verify,
          ),
        ),
      ),
    );
  }
}

class _EntryView extends StatelessWidget {
  const _EntryView({
    required this.blurb,
    required this.ctl,
    required this.focus,
    required this.error,
    required this.busy,
    required this.onSubmit,
  });

  final String blurb;
  final TextEditingController ctl;
  final FocusNode focus;
  final String? error;
  final bool busy;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(blurb, style: AppType.body(14, color: AppColors.inkSoft)),
        const SizedBox(height: 24),
        Center(
          child: SizedBox(
            width: 280,
            child: TextField(
              controller: ctl,
              focusNode: focus,
              autofocus: true,
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.done,
              maxLength: 6,
              textAlign: TextAlign.center,
              style: AppType.mono(28, color: AppColors.emeraldDeep, w: FontWeight.w700),
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: InputDecoration(
                counterText: '',
                hintText: '••••••',
                hintStyle: AppType.mono(28, color: AppColors.inkMute.withValues(alpha: 0.4)),
                filled: true,
                fillColor: Colors.white,
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide: BorderSide(color: AppColors.gold, width: 1.5),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide: BorderSide(color: AppColors.emerald, width: 2),
                ),
              ),
              onSubmitted: (_) => onSubmit(),
            ),
          ),
        ),
        if (error != null) ...[
          const SizedBox(height: 14),
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
        const Spacer(),
        PrimaryButton(
          label: busy ? 'Verifying…' : 'Verify',
          expand: true,
          onTap: busy ? null : onSubmit,
        ),
        const SizedBox(height: 8),
        Text(
          'After 5 wrong attempts the code locks. The sender can issue a new one.',
          style: AppType.body(12, color: AppColors.inkMute),
          textAlign: TextAlign.center,
        ),
      ],
    );
  }
}

class _SuccessView extends StatelessWidget {
  const _SuccessView({required this.kind});
  final HandoverKind kind;

  @override
  Widget build(BuildContext context) {
    final headline = switch (kind) {
      HandoverKind.pickup => 'Pickup confirmed',
      HandoverKind.delivery => 'Delivery confirmed',
    };
    final detail = switch (kind) {
      HandoverKind.pickup =>
        'You\'re officially carrying this parcel. Safe travels.',
      HandoverKind.delivery =>
        'Your payment has been released from escrow. Thank you for delivering.',
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Spacer(),
        Center(
          child: Container(
            width: 96,
            height: 96,
            decoration: BoxDecoration(
              color: AppColors.emerald.withValues(alpha: 0.1),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.check_circle_rounded,
                size: 64, color: AppColors.emerald),
          ),
        ),
        const SizedBox(height: 20),
        Text(headline,
            style: AppType.display(24, color: AppColors.emeraldDeep),
            textAlign: TextAlign.center),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Text(
            detail,
            style: AppType.body(14, color: AppColors.inkSoft),
            textAlign: TextAlign.center,
          ),
        ),
        const Spacer(),
        PrimaryButton(
          label: 'Done',
          expand: true,
          onTap: () => Navigator.of(context).pop(true),
        ),
      ],
    );
  }
}
