import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';
import 'oauth_buttons.dart';

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key});
  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  final _email = TextEditingController();
  final _pw = TextEditingController();
  bool _showPw = false;

  @override
  void dispose() {
    _email.dispose();
    _pw.dispose();
    super.dispose();
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
              const StampChip(label: "WELCOME BACK"),
              const SizedBox(height: AppSpacing.x4),
              Text("Good to see\nyou again.",
                      style: AppType.display(40, w: FontWeight.w400, height: 1.02))
                  .animate()
                  .fadeIn(duration: 400.ms)
                  .moveY(begin: 8, end: 0),
              const SizedBox(height: AppSpacing.x3),
              Text(
                "Sign in to keep tracking your trips and offers.",
                style: AppType.body(14, color: AppColors.inkSoft),
              ).animate().fadeIn(delay: 100.ms),
              const SizedBox(height: AppSpacing.x8),
              AppInput(
                controller: _email,
                hint: "you@example.com",
                label: "Email",
                icon: Icons.alternate_email_rounded,
                keyboardType: TextInputType.emailAddress,
              ).animate().fadeIn(delay: 200.ms).moveY(begin: 6, end: 0),
              const SizedBox(height: AppSpacing.x4),
              AppInput(
                controller: _pw,
                hint: "Your password",
                label: "Password",
                icon: Icons.lock_outline_rounded,
                obscure: !_showPw,
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
              ).animate().fadeIn(delay: 280.ms).moveY(begin: 6, end: 0),
              const SizedBox(height: AppSpacing.x3),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: () => context.push('/auth/forgot'),
                  child: Text("Forgot password?",
                      style: AppType.body(13,
                          color: AppColors.ink, w: FontWeight.w600)),
                ),
              ),
              const SizedBox(height: AppSpacing.x3),
              Center(
                child: PrimaryButton(
                  label: "Sign in",
                  icon: Icons.arrow_forward_rounded,
                  onTap: () => context.go('/role'),
                ),
              ),
              const SizedBox(height: AppSpacing.x6),
              const _Divider(label: "or continue with"),
              const SizedBox(height: AppSpacing.x4),
              const OAuthButtons(),
              const SizedBox(height: AppSpacing.x8),
              Center(
                child: Wrap(
                  alignment: WrapAlignment.center,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text("New here? ",
                        style: AppType.body(13, color: AppColors.inkMute)),
                    GestureDetector(
                      onTap: () => context.go('/auth/sign-up'),
                      child: Text("Create an account",
                          style: AppType.body(13,
                              color: AppColors.ink, w: FontWeight.w700)),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Divider extends StatelessWidget {
  const _Divider({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: Container(height: 1, color: AppColors.hairline)),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Text(label.toUpperCase(),
              style: AppType.eyebrow().copyWith(letterSpacing: 1.6)),
        ),
        Expanded(child: Container(height: 1, color: AppColors.hairline)),
      ],
    );
  }
}
