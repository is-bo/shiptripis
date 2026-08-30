/// Sign in.
///
/// The one thing worth noting: the server answers a bad credential with
/// `400 {"detail": ["Incorrect email or password."]}` — deliberately the same
/// message whether the address exists or the password is wrong, so an attacker
/// cannot enumerate accounts. This screen preserves that: the failure is shown
/// once, above the form, and is **never** attached to the email field, because
/// a red ring around "email" would tell the attacker exactly what the server
/// refused to.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/session/session.dart';
import 'auth_header.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';

class SignInScreen extends ConsumerStatefulWidget {
  const SignInScreen({super.key});

  @override
  ConsumerState<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends ConsumerState<SignInScreen> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _passwordFocus = FocusNode();

  bool _busy = false;
  bool _obscure = true;
  String? _formError;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _passwordFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _formError = null;
    });

    final l = L.of(context);
    try {
      await ref
          .read(sessionProvider.notifier)
          .signIn(email: _email.text, password: _password.text);
      // The router's redirect takes over from here; no manual navigation.
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _formError = switch (error.kind) {
          ApiFailureKind.validation ||
          ApiFailureKind.unauthenticated => l.authInvalidCredentials,
          _ => describeFailure(context, error).body,
        };
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final validators = Validators.of(context);

    return DismissKeyboardOnTap(
      child: AppScaffold(
        body: Form(
          key: _formKey,
          child: ListView(
            padding: AppScrollPadding.pageWithFooter(context, top: AppSpace.md),
            children: [
              AuthHeader(
                stamp: l.authWelcomeBackStamp,
                headline: l.authSignInHeadline,
                subhead: l.authSignInSubhead,
              ),
              if (_formError != null) ...[
                InfoNotice(
                  message: _formError!,
                  tone: StatusTone.bad,
                  icon: Icons.error_outline_rounded,
                ),
                const SizedBox(height: AppSpace.lg),
              ],
              AppTextField(
                label: l.authEmail,
                controller: _email,
                isRequired: true,
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.username],
                validator: validators.email,
                prefixIcon: Icons.alternate_email_rounded,
                onSubmitted: (_) => _passwordFocus.requestFocus(),
              ),
              AppTextField(
                label: l.authPassword,
                controller: _password,
                focusNode: _passwordFocus,
                isRequired: true,
                obscureText: _obscure,
                textInputAction: TextInputAction.done,
                autofillHints: const [AutofillHints.password],
                validator: validators.required,
                prefixIcon: Icons.lock_outline_rounded,
                onSubmitted: (_) => _submit(),
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
                  onPressed: () => context.pushNamed(
                    Routes.forgotPassword,
                    queryParameters: {
                      if (_email.text.trim().isNotEmpty)
                        'email': _email.text.trim(),
                    },
                  ),
                  child: Text(l.authForgotPassword),
                ),
              ),
            ],
          ),
        ),
        footer: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AppButton(
              label: l.authSignIn,
              isLoading: _busy,
              onPressed: _submit,
            ),
            const SizedBox(height: AppSpace.sm),
            AppButton(
              label: l.authNoAccount,
              variant: AppButtonVariant.tertiary,
              onPressed: () => context.pushReplacementNamed(Routes.signUp),
            ),
          ],
        ),
      ),
    );
  }
}
