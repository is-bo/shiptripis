/// Deleting the account from inside the app (App Store 5.1.1(v), Google Play
/// User Data).
///
/// The server decides everything (`/api/me/deletion`): what still has to be
/// finished, whether the password is asked, and whether Apple has to confirm.
/// This screen shows that answer, collects the confirmation and, once the
/// server has deleted the account, clears the phone and lands on Profile as a
/// guest with a notice that says it is done.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/auth/social_sign_in.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/account.dart';
import '../../l10n/app_localizations.dart';
import '../common/contact_support.dart';

final accountDeletionCheckProvider =
    FutureProvider.autoDispose<AccountDeletionCheck>(
      (ref) => ref.watch(authRepositoryProvider).deletionCheck(),
    );

class DeleteAccountScreen extends ConsumerStatefulWidget {
  const DeleteAccountScreen({super.key});

  @override
  ConsumerState<DeleteAccountScreen> createState() =>
      _DeleteAccountScreenState();
}

class _DeleteAccountScreenState extends ConsumerState<DeleteAccountScreen> {
  final _password = TextEditingController();
  bool _obscure = true;
  bool _busy = false;
  String? _passwordError;

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  /// Apple can only be asked on an iPhone build that offers Sign in with
  /// Apple; anywhere else an Apple account is deleted from such a phone or
  /// by support.
  bool get _canAskApple => ref.read(socialSignInProvider).offersApple;

  Future<void> _delete(AccountDeletionCheck check) async {
    final l = L.of(context);
    if (check.passwordRequired && _password.text.isEmpty) {
      setState(() => _passwordError = l.deleteAccountPasswordMissing);
      return;
    }
    setState(() => _passwordError = null);
    final confirmed = await confirmAction(
      context,
      title: l.deleteAccountConfirmTitle,
      body: l.deleteAccountConfirmBody,
      confirmLabel: l.deleteAccountConfirm,
      isDestructive: true,
    );
    if (!mounted || !confirmed) return;

    setState(() => _busy = true);
    try {
      String? appleCode;
      if (check.appleAuthorizationRequired) {
        appleCode = await ref
            .read(socialSignInProvider)
            .appleAuthorizationCode();
        // The person closed Apple's sheet: nothing happens.
        if (appleCode == null) return;
      }
      await ref
          .read(authRepositoryProvider)
          .deleteAccount(
            password: check.passwordRequired ? _password.text : null,
            appleAuthorizationCode: appleCode,
          );
      if (!mounted) return;
      // The member's screens end with the account: the next ones open on
      // Home, which says the account was deleted.
      await ref.read(sessionProvider.notifier).accountDeleted();
    } on SocialSignInFailure {
      if (mounted) AppSnack.info(context, l.socialAppleFailed);
    } on ApiException catch (error) {
      if (mounted) _explain(error);
    } on Object catch (error) {
      if (mounted) AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _explain(ApiException error) {
    final l = L.of(context);
    final code = error.code;
    if (code == ApiErrorCode.passwordIncorrect) {
      setState(() => _passwordError = l.deleteAccountPasswordIncorrect);
    } else if (code == ApiErrorCode.accountDeletionBlocked ||
        code == ApiErrorCode.appleAuthorizationRequired) {
      // Something changed since the screen read it: read it again.
      ref.invalidate(accountDeletionCheckProvider);
      AppSnack.info(context, l.deleteAccountChanged);
    } else if (code == ApiErrorCode.appleAuthorizationRefused) {
      AppSnack.info(context, l.deleteAccountAppleRefused);
    } else if (code == ApiErrorCode.appleRevokeUnavailable) {
      AppSnack.info(context, l.deleteAccountAppleUnavailable);
    } else if (code == ApiErrorCode.staffAccount) {
      AppSnack.info(context, l.deleteAccountStaff);
    } else {
      AppSnack.failure(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final check = ref.watch(accountDeletionCheckProvider);
    final ready = check.value;
    final appleBlocked =
        ready != null && ready.appleAuthorizationRequired && !_canAskApple;
    final mayDelete = ready != null && ready.canDelete && !appleBlocked;

    return DismissKeyboardOnTap(
      child: AppScaffold(
        topBar: AppTopBar(title: l.deleteAccountTitle, showBack: true),
        body: AsyncView<AccountDeletionCheck>(
          value: check,
          onRetry: () => ref.invalidate(accountDeletionCheckProvider),
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpace.gutter),
            child: SkeletonDetail(),
          ),
          data: (value) => ListView(
            padding: AppScrollPadding.pageWithFooter(context),
            children: [
              _Explanation(),
              const SizedBox(height: AppSpace.xl),
              if (!value.canDelete)
                _Blockers(
                  blockers: value.blockers,
                  onRefresh: () => ref.invalidate(accountDeletionCheckProvider),
                )
              else if (appleBlocked)
                _AppleElsewhere()
              else ...[
                if (value.appleAuthorizationRequired) ...[
                  InfoNotice(
                    message: l.deleteAccountAppleNote,
                    icon: Icons.apple,
                  ),
                  const SizedBox(height: AppSpace.lg),
                ],
                if (value.passwordRequired)
                  AppTextField(
                    label: l.deleteAccountPasswordLabel,
                    helper: l.deleteAccountPasswordHelp,
                    controller: _password,
                    errorText: _passwordError,
                    isRequired: true,
                    enabled: !_busy,
                    obscureText: _obscure,
                    textInputAction: TextInputAction.done,
                    autofillHints: const [AutofillHints.password],
                    prefixIcon: Icons.lock_outline_rounded,
                    onChanged: (_) {
                      if (_passwordError != null) {
                        setState(() => _passwordError = null);
                      }
                    },
                    onSubmitted: (_) => _delete(value),
                    suffix: AppIconButton(
                      icon: _obscure
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                      label: _obscure ? l.authShowPassword : l.authHidePassword,
                      onPressed: () => setState(() => _obscure = !_obscure),
                    ),
                  ),
              ],
            ],
          ),
        ),
        footer: mayDelete
            ? AppButton(
                label: l.deleteAccountAction,
                variant: AppButtonVariant.destructive,
                icon: Icons.delete_forever_outlined,
                isLoading: _busy,
                onPressed: _busy ? null : () => _delete(ready),
              )
            : null,
      ),
    );
  }
}

/// What deleting does and what stays.
class _Explanation extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(l.deleteAccountIntro, style: text.bodyLarge),
        const SizedBox(height: AppSpace.xl),
        SectionHeader(title: l.deleteAccountKeptTitle),
        Text(
          l.deleteAccountKeptBody,
          style: text.bodyMedium?.copyWith(color: c.textSecondary),
        ),
      ],
    );
  }
}

/// What has to be finished first, each worded with where to finish it.
class _Blockers extends StatelessWidget {
  const _Blockers({required this.blockers, required this.onRefresh});

  final List<AccountDeletionBlocker> blockers;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InfoNotice(
          title: l.deleteAccountBlockedTitle,
          message: l.deleteAccountBlockedBody,
          tone: StatusTone.action,
          icon: Icons.pending_actions_rounded,
        ),
        const SizedBox(height: AppSpace.md),
        for (final blocker in blockers)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpace.sm),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.pending_outlined,
                  size: 20,
                  color: context.colors.textTertiary,
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Text(
                    _blockerLabel(l, blocker),
                    style: text.bodyMedium,
                  ),
                ),
              ],
            ),
          ),
        const SizedBox(height: AppSpace.md),
        AppButton(
          label: l.deleteAccountOpenDeliveries,
          variant: AppButtonVariant.secondary,
          icon: Icons.inventory_2_outlined,
          onPressed: () => context.goNamed(Routes.deliveries),
        ),
        const SizedBox(height: AppSpace.sm),
        AppButton(
          label: l.deleteAccountCheckAgain,
          variant: AppButtonVariant.tertiary,
          icon: Icons.refresh_rounded,
          onPressed: onRefresh,
        ),
      ],
    );
  }

  static String _blockerLabel(L l, AccountDeletionBlocker blocker) =>
      switch (blocker) {
        AccountDeletionBlocker.openDeliveries =>
          l.deleteAccountBlockerDeliveries,
        AccountDeletionBlocker.openDisputes => l.deleteAccountBlockerDisputes,
        AccountDeletionBlocker.pendingPayouts => l.deleteAccountBlockerPayouts,
        AccountDeletionBlocker.pendingRefunds => l.deleteAccountBlockerRefunds,
        AccountDeletionBlocker.openRequests => l.deleteAccountBlockerRequests,
        AccountDeletionBlocker.activeJourneys => l.deleteAccountBlockerJourneys,
        AccountDeletionBlocker.unknown => l.deleteAccountBlockerOther,
      };
}

/// An account that signs in with Apple, on a phone that cannot ask Apple.
class _AppleElsewhere extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final supportEmail = supportEmailOf(ref);
    return InfoNotice(
      title: l.deleteAccountAppleElsewhereTitle,
      message: l.deleteAccountAppleElsewhereBody,
      icon: Icons.apple,
      actionLabel: supportEmail == null ? null : l.actionContactSupport,
      onAction: supportEmail == null
          ? null
          : () => openSupportEmail(context, supportEmail),
    );
  }
}
