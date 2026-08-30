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
  String? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final l = L.of(context);
    if (_code.text.length != 6) {
      setState(() => _error = l.validationRequired);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      await ref
          .read(authRepositoryProvider)
          .verifyEmail(email: widget.email, code: _code.text);
      // The account row changed server-side; re-read it rather than assuming.
      await ref.read(sessionProvider.notifier).refreshAccount();
      if (!mounted) return;
      AppSnack.success(context, l.authVerifyDone);
      context.pop();
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
              stampColor: context.colors.brand,
            ),
            InfoNotice(
              message: l.authVerifyEmailBody(widget.email),
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
            // There is no resend endpoint in the V1 contract, so this screen
            // does not offer a button that would quietly do nothing. It says
            // what the user can actually try instead.
            Text(
              l.authVerifyNoCode,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
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
