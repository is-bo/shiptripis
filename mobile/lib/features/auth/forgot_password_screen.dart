import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth_notifier.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

enum _Step { email, code, done }

class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});
  @override
  ConsumerState<ForgotPasswordScreen> createState() =>
      _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final _email = TextEditingController();
  final _code = TextEditingController();
  final _newPw = TextEditingController();

  _Step _step = _Step.email;
  bool _busy = false;
  bool _showPw = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _code.dispose();
    _newPw.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    await ref
        .read(authNotifierProvider.notifier)
        .requestPasswordReset(_email.text.trim());
    if (!mounted) return;
    setState(() {
      _busy = false;
      _step = _Step.code;
    });
  }

  Future<void> _confirm() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    final ok = await ref.read(authNotifierProvider.notifier).confirmPasswordReset(
          email: _email.text.trim(),
          code: _code.text.trim(),
          newPassword: _newPw.text,
        );
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) {
      setState(() => _step = _Step.done);
    } else {
      final s = ref.read(authNotifierProvider);
      setState(() =>
          _error = s is AuthError ? s.message : 'Could not reset password.');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              IconButton(
                onPressed: () => context.pop(),
                icon: const Icon(Icons.arrow_back_rounded),
                style: IconButton.styleFrom(
                  backgroundColor: AppColors.parchmentSoft,
                  shape: const CircleBorder(),
                ),
              ),
              const SizedBox(height: AppSpacing.x6),
              StampChip(
                label: switch (_step) {
                  _Step.email => "PASSWORD RESET",
                  _Step.code => "CHECK YOUR INBOX",
                  _Step.done => "ALL SET",
                },
                color: _step == _Step.done
                    ? AppColors.emerald
                    : AppColors.terracotta,
              ),
              const SizedBox(height: AppSpacing.x4),
              AnimatedSwitcher(
                duration: AppDurations.med,
                child: switch (_step) {
                  _Step.email => _emailForm(),
                  _Step.code => _codeForm(),
                  _Step.done => _success(),
                },
              ),
              const SizedBox(height: AppSpacing.x6),
              if (_error != null)
                Container(
                  width: double.infinity,
                  margin: const EdgeInsets.only(bottom: AppSpacing.x4),
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 12),
                  decoration: BoxDecoration(
                    color: const Color(0x14B23A2E),
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    border: Border.all(color: AppColors.danger, width: 1),
                  ),
                  child: Text(_error!,
                      style: AppType.body(13,
                          color: AppColors.danger, w: FontWeight.w600)),
                ),
              Center(child: _primaryAction()),
              const SizedBox(height: AppSpacing.x4),
            ],
          ),
        ),
      ),
    );
  }

  Widget _primaryAction() {
    switch (_step) {
      case _Step.email:
        final ok = !_busy && _email.text.contains('@');
        return AnimatedOpacity(
          duration: AppDurations.med,
          opacity: ok ? 1 : 0.5,
          child: PrimaryButton(
            label: _busy ? "Sending..." : "Send code",
            icon: _busy ? null : Icons.mail_rounded,
            onTap: ok ? _sendCode : null,
          ),
        );
      case _Step.code:
        final ok = !_busy && _code.text.length == 6 && _newPw.text.length >= 8;
        return AnimatedOpacity(
          duration: AppDurations.med,
          opacity: ok ? 1 : 0.5,
          child: PrimaryButton(
            label: _busy ? "Resetting..." : "Reset password",
            icon: _busy ? null : Icons.arrow_forward_rounded,
            onTap: ok ? _confirm : null,
          ),
        );
      case _Step.done:
        return PrimaryButton(
          label: "Back to sign in",
          icon: Icons.arrow_forward_rounded,
          onTap: () => context.go('/auth/sign-in'),
        );
    }
  }

  Widget _emailForm() {
    return Column(
      key: const ValueKey('email'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Forgot your\npassword?",
                style: AppType.display(38, w: FontWeight.w400, height: 1.02))
            .animate()
            .fadeIn(duration: 350.ms)
            .moveY(begin: 6, end: 0),
        const SizedBox(height: AppSpacing.x3),
        Text(
            "Enter your email — we'll send a 6-digit code so you can pick a new password.",
            style: AppType.body(14, color: AppColors.inkSoft)),
        const SizedBox(height: AppSpacing.x6),
        AppInput(
          controller: _email,
          hint: "you@example.com",
          label: "Email",
          icon: Icons.alternate_email_rounded,
          keyboardType: TextInputType.emailAddress,
          autofocus: true,
          onChanged: (_) => setState(() {}),
        ),
      ],
    );
  }

  Widget _codeForm() {
    return Column(
      key: const ValueKey('code'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Enter the\ncode.",
                style: AppType.display(38, w: FontWeight.w400, height: 1.02))
            .animate()
            .fadeIn(duration: 350.ms)
            .moveY(begin: 6, end: 0),
        const SizedBox(height: AppSpacing.x3),
        Text(
          "We sent a 6-digit code to ${_email.text}. It expires in 15 minutes.",
          style: AppType.body(14, color: AppColors.inkSoft, height: 1.5),
        ),
        const SizedBox(height: AppSpacing.x6),
        AppInput(
          controller: _code,
          hint: "6-digit code",
          label: "Code",
          icon: Icons.password_rounded,
          keyboardType: TextInputType.number,
          autofocus: true,
          onChanged: (_) => setState(() {}),
        ),
        const SizedBox(height: AppSpacing.x4),
        AppInput(
          controller: _newPw,
          hint: "At least 8 characters",
          label: "New password",
          icon: Icons.lock_outline_rounded,
          obscure: !_showPw,
          onChanged: (_) => setState(() {}),
          suffix: IconButton(
            onPressed: () => setState(() => _showPw = !_showPw),
            icon: Icon(
              _showPw
                  ? Icons.visibility_off_rounded
                  : Icons.visibility_rounded,
              color: AppColors.inkMute,
              size: 18,
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.x3),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(
            onPressed: _busy
                ? null
                : () {
                    HapticFeedback.selectionClick();
                    setState(() => _step = _Step.email);
                  },
            child: Text("Use a different email",
                style: AppType.body(13,
                    color: AppColors.ink, w: FontWeight.w600)),
          ),
        ),
      ],
    );
  }

  Widget _success() {
    return Column(
      key: const ValueKey('done'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Password\nupdated.",
                style: AppType.display(38, w: FontWeight.w400, height: 1.02))
            .animate()
            .fadeIn(duration: 350.ms)
            .moveY(begin: 6, end: 0),
        const SizedBox(height: AppSpacing.x3),
        Text(
          "You can now sign in with your new password.",
          style: AppType.body(14, color: AppColors.inkSoft, height: 1.5),
        ),
      ],
    );
  }
}
