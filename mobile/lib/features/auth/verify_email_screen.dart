/// Confirm the email address on a new account.
///
/// The server treats an already-verified address as a success rather than an
/// error, so a user who taps an old link and then types the code is not told
/// off for it. Every other failure is the same generic refusal, so the screen
/// offers a fresh code rather than pretending to know which one it was.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/session/session.dart';
import '../../design/components/codes.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';
import 'auth_header.dart';

class VerifyEmailScreen extends ConsumerStatefulWidget {
  const VerifyEmailScreen({required this.email, super.key});

  final String email;

  @override
  ConsumerState<VerifyEmailScreen> createState() => _VerifyEmailScreenState();
}

class _VerifyEmailScreenState extends ConsumerState<VerifyEmailScreen> {
  final _code = TextEditingController();
  bool _busy = false;
  bool _resending = false;
  String? _error;

  /// The address on the account when the route carries none (Profile and the
  /// refused-posting flow open this screen for the signed-in person).
  String get _email {
    if (widget.email.isNotEmpty) return widget.email;
    return ref.read(accountProvider)?.email ?? '';
  }

  Future<void> _resend() async {
    if (_resending || _busy) return;
    final l = L.of(context);
    setState(() => _resending = true);
    try {
      await ref.read(authRepositoryProvider).resendVerifyEmail();
      if (!mounted) return;
      _code.clear();
      setState(() => _error = null);
      AppSnack.success(context, l.authVerifyResent);
    } on ApiException catch (error) {
      if (!mounted) return;
      AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _resending = false);
    }
  }

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final l = L.of(context);
    final codeError = Validators.of(context).sixDigitCode(_code.text);
    if (codeError != null) {
      setState(() => _error = codeError);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      await ref
          .read(authRepositoryProvider)
          .verifyEmail(email: _email, code: _code.text);
      // The account row changed server-side; re-read it rather than assuming.
      await ref.read(sessionProvider.notifier).refreshAccount();
      if (!mounted) return;
      AppSnack.success(context, l.authVerifyDone);
      // `true` tells whoever sent the person here that the email is confirmed.
      context.pop(true);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(
        () => _error = error.kind == ApiFailureKind.validation
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
    final c = context.colors;

    return DismissKeyboardOnTap(
      child: AppScaffold(
        body: ListView(
          padding: AppScrollPadding.pageWithFooter(context, top: AppSpace.md),
          children: [
            AuthHeader(
              stamp: l.authVerifyStamp,
              headline: l.authVerifyEmailTitle,
              subhead: l.authVerifySubhead,
              stampColor: context.colors.brandInk,
            ),
            InfoNotice(
              message: l.authVerifyEmailBody(_email),
              tone: StatusTone.progress,
              icon: Icons.mark_email_read_outlined,
            ),
            const SizedBox(height: AppSpace.xl),
            CodeEntryField(
              controller: _code,
              label: l.authResetCodeLabel,
              length: 6,
              errorText: _error,
              enabled: !_busy,
              onSubmitted: (_) => _submit(),
            ),
            const SizedBox(height: AppSpace.md),
            Text(
              l.authVerifyNoCode,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
            ),
            const SizedBox(height: AppSpace.md),
            AppButton(
              label: l.authVerifyResend,
              icon: Icons.refresh_rounded,
              variant: AppButtonVariant.tertiary,
              isLoading: _resending,
              onPressed: _busy ? null : _resend,
            ),
          ],
        ),
        footer: AppButton(
          label: l.actionConfirm,
          isLoading: _busy,
          onPressed: _submit,
        ),
      ),
    );
  }
}
