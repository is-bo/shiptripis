/// Create an account.
///
/// Collects exactly what the server requires and nothing more. A wilaya is a
/// legacy optional profile hint, not an account prerequisite: actual V1
/// locations are collected on delivery requests and Journeys.
///
/// Server field errors land on the field that caused them: the API returns a
/// DRF field-error dict (`{"email": ["An account with this email already
/// exists."]}`), and [FieldErrorMap] routes each key to its input. Anything
/// unclaimed is shown above the form instead of being swallowed.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_settings.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/session/session.dart';
import '../../domain/communication_language.dart';
import 'auth_header.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';

class SignUpScreen extends ConsumerStatefulWidget {
  const SignUpScreen({super.key});

  @override
  ConsumerState<SignUpScreen> createState() => _SignUpScreenState();
}

class _SignUpScreenState extends ConsumerState<SignUpScreen> {
  static const _claimedFields = {'full_name', 'email', 'password', 'phone'};

  final _formKey = GlobalKey<FormState>();
  final _fullName = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _phone = TextEditingController();

  bool _busy = false;
  bool _obscure = true;
  FieldErrorMap _errors = const FieldErrorMap.empty();

  @override
  void dispose() {
    _fullName.dispose();
    _email.dispose();
    _password.dispose();
    _phone.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final formOk = _formKey.currentState?.validate() ?? false;
    if (!formOk) return;

    setState(() {
      _busy = true;
      _errors = const FieldErrorMap.empty();
    });

    try {
      await ref
          .read(sessionProvider.notifier)
          .signUp(
            fullName: _fullName.text,
            email: _email.text,
            password: _password.text,
            phone: _phone.text,
            // The account has no stored preference yet, so the language this
            // form was filled in is the only honest answer for the first
            // email. It is a starting point, changeable in
            // Profile -> Language, and nothing after this ever overwrites it
            // from the interface setting.
            preferredLanguage: CommunicationLanguage.forLanguageCode(
              ref.read(effectiveLocaleProvider).languageCode,
            ),
          );
      if (!mounted) return;
      // The account exists but is unverified, and the server has already sent
      // a code. Taking the user straight there is the difference between an
      // email they act on and one they find a week later.
      context.pushNamed(
        Routes.verifyEmail,
        queryParameters: {'email': _email.text.trim()},
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _errors = FieldErrorMap.from(error));
      if (_errors.isEmpty) AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final validators = Validators.of(context);
    final unclaimed = _errors.unclaimed(_claimedFields);

    return DismissKeyboardOnTap(
      child: AppScaffold(
        body: Form(
          key: _formKey,
          child: ListView(
            padding: AppScrollPadding.pageWithFooter(context, top: AppSpace.md),
            children: [
              AuthHeader(
                stamp: l.authJoinStamp,
                headline: l.authSignUpHeadline,
                subhead: l.authSignUpSubhead,
                stampColor: c.attention,
              ),
              if (unclaimed.isNotEmpty) ...[
                InfoNotice(
                  message: unclaimed.join('\n'),
                  tone: StatusTone.bad,
                  icon: Icons.error_outline_rounded,
                ),
                const SizedBox(height: AppSpace.lg),
              ],
              AppTextField(
                label: l.authFullName,
                controller: _fullName,
                isRequired: true,
                errorText: _errors['full_name'],
                textCapitalization: TextCapitalization.words,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.name],
                validator: validators.required,
              ),
              AppTextField(
                label: l.authEmail,
                controller: _email,
                isRequired: true,
                errorText: _errors['email'],
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.email],
                validator: validators.email,
              ),
              AppTextField(
                label: l.authPassword,
                controller: _password,
                isRequired: true,
                errorText: _errors['password'],
                obscureText: _obscure,
                textInputAction: TextInputAction.next,
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
              AppTextField(
                label: l.authPhone,
                controller: _phone,
                isRequired: true,
                errorText: _errors['phone'],
                keyboardType: TextInputType.phone,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.telephoneNumber],
                validator: validators.required,
              ),
              const SizedBox(height: AppSpace.sm),
              Text(
                l.authTermsNotice,
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
              ),
            ],
          ),
        ),
        footer: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AppButton(
              label: l.authSignUp,
              isLoading: _busy,
              onPressed: _submit,
            ),
            const SizedBox(height: AppSpace.sm),
            AppButton(
              label: l.authHaveAccount,
              variant: AppButtonVariant.tertiary,
              onPressed: () => context.pushReplacementNamed(Routes.signIn),
            ),
          ],
        ),
      ),
    );
  }
}
