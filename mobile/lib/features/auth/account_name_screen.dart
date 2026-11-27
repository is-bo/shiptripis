/// "What should we call you?": naming an account a social sign-in left
/// without a name.
///
/// Apple gives the person's name on the first authorization only, and lets
/// them withhold it; Google may carry none. The server never invents one from
/// the email address, so such an account starts with an empty name, and this
/// step asks for it once: right after the sign-in, as the last screen of the
/// account moment, and otherwise on Home, once per app launch while the name
/// is still empty ([AskForNameOnce]). Closing it is allowed; whatever the
/// person was doing goes ahead.
///
/// `PATCH /api/me` takes `full_name` only while the account has none; its
/// `name_already_set` means the name arrived another way, which is as good
/// as a success here (`SessionController.setFullName`).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/auth/social_sign_in.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/identity.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';
import 'account_gate.dart';
import 'auth_header.dart';

/// Whether the name step was offered to the signed-in account in this run
/// of the app. Held in memory only: the next launch asks again while the
/// name is still empty, and another account signing in starts over.
final accountNameAskedProvider = NotifierProvider<AccountNameAsked, bool>(
  AccountNameAsked.new,
);

class AccountNameAsked extends Notifier<bool> {
  @override
  bool build() {
    ref.watch(accountProvider.select((account) => account?.id));
    return false;
  }

  void markAsked() => state = true;
}

/// The name check, as a validator: not blank, and no longer than the server
/// takes, counted the way the server counts (code points, after trimming).
String? validateAccountName(L l, String? value) {
  final name = value?.trim() ?? '';
  if (name.isEmpty) return l.validationRequired;
  if (name.runes.length > maxFullNameLength) {
    return l.validationTooLong(maxFullNameLength);
  }
  return null;
}

class AccountNameScreen extends ConsumerStatefulWidget {
  const AccountNameScreen({this.flow = AccountFlow.none, super.key});

  /// Inside the account moment, finishing or closing this step ends the
  /// flow and lets the action that opened it go ahead.
  final AccountFlow flow;

  @override
  ConsumerState<AccountNameScreen> createState() => _AccountNameScreenState();
}

class _AccountNameScreenState extends ConsumerState<AccountNameScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    // Nobody to name (a link opened it signed out), or the name is already
    // there: nothing to ask.
    final account = ref.read(accountProvider);
    if (account == null || account.fullName.trim().isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _leave();
      });
    }
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _leave() {
    if (widget.flow.active) {
      completeAccountFlow(context, widget.flow);
    } else if (context.canPop()) {
      context.pop();
    } else {
      context.go('/home');
    }
  }

  Future<void> _submit() async {
    if (_busy) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final named = await ref
          .read(sessionProvider.notifier)
          .setFullName(_name.text);
      // Not named for this member: the form is not theirs to leave.
      if (mounted && named) _leave();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _error = describeFailure(context, error).body);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return PopScope(
      canPop: !widget.flow.active,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && widget.flow.active) {
          completeAccountFlow(context, widget.flow);
        }
      },
      child: DismissKeyboardOnTap(
        child: AppScaffold(
          body: Form(
            key: _formKey,
            child: ListView(
              padding: AppScrollPadding.pageWithFooter(
                context,
                top: AppSpace.md,
              ),
              children: [
                Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: PaperCloseButton(onPressed: _leave),
                ),
                const SizedBox(height: AppSpace.xl),
                AuthHeader(
                  stamp: l.accountNameStamp,
                  headline: l.accountNameTitle,
                  subhead: l.accountNameBody,
                  stampColor: c.brandInk,
                  showBack: false,
                ),
                if (_error != null) ...[
                  InfoNotice(
                    message: _error!,
                    tone: StatusTone.bad,
                    icon: Icons.error_outline_rounded,
                  ),
                  const SizedBox(height: AppSpace.lg),
                ],
                AppTextField(
                  label: l.accountNameLabel,
                  controller: _name,
                  isRequired: true,
                  autofocus: true,
                  textCapitalization: TextCapitalization.words,
                  textInputAction: TextInputAction.done,
                  autofillHints: const [AutofillHints.name],
                  validator: (value) => validateAccountName(l, value),
                  onSubmitted: (_) => _submit(),
                ),
              ],
            ),
          ),
          footer: AppButton(
            label: l.actionContinue,
            isLoading: _busy,
            onPressed: _submit,
          ),
        ),
      ),
    );
  }
}

/// Asks a member whose account has no name for one, once per app launch,
/// when [child] (Home) is the screen on top.
///
/// Home, and only Home, because it is the least intrusive place that is
/// still sure to be seen: a launch from a notification or a link opens the
/// screen the person came for, untouched, and the step waits until they are
/// back on the front page. The account moment asks on its own, and marks the
/// launch as asked, so nobody is asked twice in a row.
class AskForNameOnce extends ConsumerWidget {
  const AskForNameOnce({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unnamed = ref.watch(
      accountProvider.select(
        (account) => account != null && account.fullName.trim().isEmpty,
      ),
    );
    if (unnamed && !ref.watch(accountNameAskedProvider)) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!context.mounted || ref.read(accountNameAskedProvider)) return;
        final router = GoRouter.of(context);
        if (router.state.uri.path != '/home') return;
        ref.read(accountNameAskedProvider.notifier).markAsked();
        router.pushNamed(Routes.accountName);
      });
    }
    return child;
  }
}
