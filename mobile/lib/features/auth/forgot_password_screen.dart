import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key});
  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final _email = TextEditingController();
  bool _sent = false;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Padding(
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
                label: _sent ? "EMAIL ON THE WAY" : "PASSWORD RESET",
                color: _sent ? AppColors.emerald : AppColors.terracotta,
              ),
              const SizedBox(height: AppSpacing.x4),
              AnimatedSwitcher(
                duration: AppDurations.med,
                child: _sent ? _success() : _form(),
              ),
              const Spacer(),
              if (_sent)
                Center(
                  child: PrimaryButton(
                    label: "Back to sign in",
                    icon: Icons.arrow_forward_rounded,
                    onTap: () => context.go('/auth/sign-in'),
                  ),
                )
              else
                Center(
                  child: PrimaryButton(
                    label: "Send reset link",
                    icon: Icons.mail_rounded,
                    onTap: _email.text.isNotEmpty
                        ? () => setState(() => _sent = true)
                        : null,
                  ),
                ),
              const SizedBox(height: AppSpacing.x4),
            ],
          ),
        ),
      ),
    );
  }

  Widget _form() {
    return Column(
      key: const ValueKey('form'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Forgot your\npassword?",
                style: AppType.display(38, w: FontWeight.w400, height: 1.02))
            .animate()
            .fadeIn(duration: 350.ms)
            .moveY(begin: 6, end: 0),
        const SizedBox(height: AppSpacing.x3),
        Text("Enter your email — we'll send a one-time link to reset it.",
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

  Widget _success() {
    return Column(
      key: const ValueKey('success'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Check your\ninbox.",
                style: AppType.display(38, w: FontWeight.w400, height: 1.02))
            .animate()
            .fadeIn(duration: 350.ms)
            .moveY(begin: 6, end: 0),
        const SizedBox(height: AppSpacing.x3),
        Text(
          "We sent a reset link to ${_email.text}. The link expires in 30 minutes.",
          style: AppType.body(14, color: AppColors.inkSoft, height: 1.5),
        ),
        const SizedBox(height: AppSpacing.x4),
        Container(
          padding: const EdgeInsets.all(AppSpacing.x4),
          decoration: BoxDecoration(
            color: AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Row(
            children: [
              const Icon(Icons.info_outline_rounded,
                  size: 18, color: AppColors.inkMute),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  "Didn't get it? Check spam, or wait 60 seconds and try again.",
                  style: AppType.body(12.5, color: AppColors.inkSoft),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
