/// Password reset, both halves in one screen.
///
/// The server is deliberately uninformative here and the UI has to match it
/// rather than fight it:
///
/// * The request step **always** answers `202`, whether or not the address has
///   an account. So the confirmation says "if that address has an account" —
///   claiming an email was sent would leak account existence to anyone who
///   cared to ask.
///
/// * The confirm step answers every failure — unknown email, wrong code,
///   expired code, too many attempts — with the same generic message. There is
///   nothing more specific to say, so the screen does not invent it; it offers
///   a new code instead, which is the only useful next move.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/session/session.dart';
import '../../design/components/codes.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import 'auth_header.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';

class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({this.initialEmail, super.key});

  final String? initialEmail;

  @override
  ConsumerState<ForgotPasswordScreen> createState() =>
      _ForgotPasswordScreenState();
}

enum _Stage { request, confirm }

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  late final _email = TextEditingController(text: widget.initialEmail ?? '');
  final _code = TextEditingController();
  final _newPassword = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  _Stage _stage = _Stage.request;
  bool _busy = false;
  bool _obscure = true;
  String? _codeError;

  @override
  void dispose() {
    _email.dispose();
    _code.dispose();
    _newPassword.dispose();
    super.dispose();
  }

  Future<void> _requestCode() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);
    try {
      await ref
          .read(authRepositoryProvider)
          .requestPasswordReset(_email.text.trim());
      if (!mounted) return;
      setState(() => _stage = _Stage.confirm);
    } on ApiException catch (error) {
      if (!mounted) return;
      AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirm() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_code.text.length != 6) {
      setState(() => _codeError = L.of(context).validationRequired);
      return;
    }
    setState(() {
      _busy = true;
      _codeError = null;
    });

    final l = L.of(context);
    try {
      await ref
          .read(authRepositoryProvider)
          .confirmPasswordReset(
            email: _email.text.trim(),
            code: _code.text,
            newPassword: _newPassword.text,
          );
      if (!mounted) return;
      AppSnack.success(context, l.authResetDone);
      context.pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      // Every failure here is indistinguishable by design. Showing the same
      // line for all of them is honest; guessing which one it was is not.
      setState(
        () => _codeError = error.kind == ApiFailureKind.validation
            ? l.codeIncorrect
            : describeFailure(context, error).body,
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final validators = Validators.of(context);
    final isRequest = _stage == _Stage.request;

    return DismissKeyboardOnTap(
      child: AppScaffold(
        body: Form(
          key: _formKey,
          child: ListView(
            padding: AppScrollPadding.pageWithFooter(context, top: AppSpace.md),
            children: [
              AuthHeader(
                stamp: l.authForgotStamp,
                headline: l.authForgotHeadline,
                subhead: l.authForgotSubhead,
              ),
              if (!isRequest) ...[
                InfoNotice(
                  message: l.authResetCodeSent,
                  tone: StatusTone.progress,
                  icon: Icons.mark_email_read_outlined,
                ),
                const SizedBox(height: AppSpace.lg),
              ],
              AppTextField(
                label: l.authEmail,
                controller: _email,
                isRequired: true,
                enabled: isRequest,
                keyboardType: TextInputType.emailAddress,
                autofillHints: const [AutofillHints.email],
                validator: validators.email,
              ),
              if (!isRequest) ...[
                const SizedBox(height: AppSpace.md),
                CodeEntryField(
                  controller: _code,
                  label: l.authResetCodeLabel,
                  length: 6,
                  errorText: _codeError,
                  enabled: !_busy,
                ),
                const SizedBox(height: AppSpace.xl),
                AppTextField(
                  label: l.authNewPassword,
                  controller: _newPassword,
                  isRequired: true,
                  obscureText: _obscure,
                  autofillHints: const [AutofillHints.newPassword],
                  validator: validators.password,
                  helper: l.validationPasswordTooShort,
                  suffix: AppIconButton(
                    icon: _obscure
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                    label: _obscure ? l.authShowPassword : l.authHidePassword,
                    onPressed: () => setState(() => _obscure = !_obscure),
                  ),
                ),
                Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: TextButton(
                    onPressed: _busy ? null : _requestCode,
                    child: Text(l.authResendCode),
                  ),
                ),
              ],
            ],
          ),
        ),
        footer: AppButton(
          label: isRequest ? l.authSendCode : l.actionConfirm,
          isLoading: _busy,
          onPressed: isRequest ? _requestCode : _confirm,
        ),
      ),
    );
  }
}
