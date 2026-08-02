import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth_notifier.dart';
import '../../core/constants/wilayas.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';
import '../../shared/widgets/wilaya_picker.dart';
import 'oauth_buttons.dart';

class SignUpScreen extends ConsumerStatefulWidget {
  const SignUpScreen({super.key});
  @override
  ConsumerState<SignUpScreen> createState() => _SignUpScreenState();
}

class _SignUpScreenState extends ConsumerState<SignUpScreen> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _pw = TextEditingController();
  final _pw2 = TextEditingController();
  bool _showPw = false;
  bool _agree = false;
  Wilaya? _wilaya;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _pw.dispose();
    _pw2.dispose();
    super.dispose();
  }

  /// Only a mismatch once the confirm field has content — an empty second box
  /// is "not finished yet", not an error.
  bool get _pwMismatch => _pw2.text.isNotEmpty && _pw2.text != _pw.text;

  bool get _canSubmit =>
      _agree &&
      !_busy &&
      _name.text.trim().length >= 2 &&
      _email.text.contains('@') &&
      _phone.text.trim().length >= 6 &&
      _pw.text.length >= 8 &&
      _pw2.text == _pw.text &&
      _wilaya != null;

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    final ok = await ref.read(authNotifierProvider.notifier).signUp(
          fullName: _name.text.trim(),
          email: _email.text.trim(),
          password: _pw.text,
          phone: _phone.text.trim(),
          wilaya: _wilaya!.code,
        );
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) {
      context.go('/role');
    } else {
      final s = ref.read(authNotifierProvider);
      setState(() => _error = s is AuthError ? s.message : 'Sign-up failed.');
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
              const StampChip(label: "JOIN THE CORRIDOR", color: AppColors.terracotta),
              const SizedBox(height: AppSpacing.x4),
              Text("Create your\npassport.",
                      style: AppType.display(40, w: FontWeight.w400, height: 1.02))
                  .animate()
                  .fadeIn(duration: 400.ms)
                  .moveY(begin: 8, end: 0),
              const SizedBox(height: AppSpacing.x3),
              Text("Two minutes — then you can send or travel.",
                  style: AppType.body(14, color: AppColors.inkSoft)),
              const SizedBox(height: AppSpacing.x8),
              AppInput(
                controller: _name,
                hint: "Your full name",
                label: "Name",
                icon: Icons.person_outline_rounded,
                onChanged: (_) => setState(() {}),
              ).animate().fadeIn(delay: 100.ms).moveY(begin: 6, end: 0),
              const SizedBox(height: AppSpacing.x4),
              AppInput(
                controller: _email,
                hint: "you@example.com",
                label: "Email",
                icon: Icons.alternate_email_rounded,
                keyboardType: TextInputType.emailAddress,
                onChanged: (_) => setState(() {}),
              ).animate().fadeIn(delay: 180.ms).moveY(begin: 6, end: 0),
              const SizedBox(height: AppSpacing.x4),
              AppInput(
                controller: _phone,
                hint: "+213 / +33 ...",
                label: "Phone",
                icon: Icons.phone_outlined,
                keyboardType: TextInputType.phone,
                onChanged: (_) => setState(() {}),
              ).animate().fadeIn(delay: 260.ms).moveY(begin: 6, end: 0),
              const SizedBox(height: AppSpacing.x4),
              _WilayaField(
                wilaya: _wilaya,
                onTap: () async {
                  final picked =
                      await showWilayaPicker(context, selected: _wilaya);
                  if (picked != null) setState(() => _wilaya = picked);
                },
              ).animate().fadeIn(delay: 310.ms).moveY(begin: 6, end: 0),
              const SizedBox(height: AppSpacing.x4),
              AppInput(
                controller: _pw,
                hint: "At least 8 characters",
                label: "Password",
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
              ).animate().fadeIn(delay: 340.ms).moveY(begin: 6, end: 0),
              const SizedBox(height: AppSpacing.x4),
              AppInput(
                controller: _pw2,
                hint: "Type it once more",
                label: "Confirm password",
                icon: Icons.lock_outline_rounded,
                // Follows the same show/hide toggle as the field above —
                // revealing one and masking the other defeats the check.
                obscure: !_showPw,
                onChanged: (_) => setState(() {}),
              ).animate().fadeIn(delay: 355.ms).moveY(begin: 6, end: 0),
              // Only complain once they've actually started the second field —
              // flagging a mismatch against an empty box is just noise.
              if (_pwMismatch) ...[
                const SizedBox(height: 6),
                Text("Passwords don't match",
                    style: AppType.body(12, color: AppColors.danger)),
              ],
              const SizedBox(height: AppSpacing.x4),
              GestureDetector(
                onTap: () => setState(() => _agree = !_agree),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    AnimatedContainer(
                      duration: AppDurations.fast,
                      width: 22,
                      height: 22,
                      margin: const EdgeInsets.only(top: 2),
                      decoration: BoxDecoration(
                        color: _agree ? AppColors.ink : Colors.transparent,
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(
                          color: _agree ? AppColors.ink : AppColors.hairline,
                          width: 1.4,
                        ),
                      ),
                      child: _agree
                          ? const Icon(Icons.check_rounded,
                              size: 16, color: AppColors.parchment)
                          : null,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        "I agree to the Terms of Service and the Privacy Policy.",
                        style: AppType.body(12.5,
                            color: AppColors.inkSoft, w: FontWeight.w500),
                      ),
                    ),
                  ],
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: AppSpacing.x4),
                Container(
                  width: double.infinity,
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
              ],
              const SizedBox(height: AppSpacing.x6),
              Center(
                child: AnimatedOpacity(
                  duration: AppDurations.med,
                  opacity: _canSubmit ? 1 : 0.5,
                  child: PrimaryButton(
                    label: _busy ? "Creating..." : "Create account",
                    icon: _busy ? null : Icons.arrow_forward_rounded,
                    onTap: _canSubmit ? _submit : null,
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.x6),
              const _Divider(label: "or sign up with"),
              const SizedBox(height: AppSpacing.x4),
              const OAuthButtons(),
              const SizedBox(height: AppSpacing.x6),
              Center(
                child: Wrap(
                  alignment: WrapAlignment.center,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text("Already a member? ",
                        style: AppType.body(13, color: AppColors.inkMute)),
                    GestureDetector(
                      onTap: () => context.go('/auth/sign-in'),
                      child: Text("Sign in",
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

class _WilayaField extends StatelessWidget {
  const _WilayaField({required this.wilaya, required this.onTap});
  final Wilaya? wilaya;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("WILAYA", style: AppType.eyebrow()),
        const SizedBox(height: 8),
        InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(AppRadius.md),
          child: Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 14, vertical: 16),
            decoration: BoxDecoration(
              color: AppColors.parchmentSoft,
              borderRadius: BorderRadius.circular(AppRadius.md),
              border:
                  Border.all(color: AppColors.hairline, width: 1.2),
            ),
            child: Row(
              children: [
                const Icon(Icons.location_on_outlined,
                    size: 18, color: AppColors.inkMute),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    wilaya == null
                        ? 'Choose your wilaya'
                        : '${wilaya!.code} — ${wilaya!.name}',
                    style: AppType.body(15,
                        w: FontWeight.w500,
                        color: wilaya == null
                            ? AppColors.inkMute
                            : AppColors.ink),
                  ),
                ),
                const Icon(Icons.expand_more_rounded,
                    size: 18, color: AppColors.inkMute),
              ],
            ),
          ),
        ),
      ],
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
