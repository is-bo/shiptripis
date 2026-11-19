/// The account moment: what a guest meets when they ask for something only a
/// member can do.
///
/// [ensureAccount] is the one entry point. For a member it answers at once;
/// for a guest it opens [AccountGateScreen] (`/auth/continue`), which says
/// why an account is needed and offers the ways in. Sign-in and sign-up
/// opened from it carry `continue=1` and are an *account flow*: the router
/// never redirects them when the session turns signed in. Every way in ends
/// in [finishSignIn], which has [completeAccountFlow] close every flow route
/// in one step, so the caller's `await ensureAccount(...)` resumes on the very
/// screen the guest was on and the action they asked for goes ahead.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/router.dart';
import '../../core/session/session.dart';
import '../../design/components/primitives.dart';
import '../../design/identity.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';
import 'account_name_screen.dart';
import 'auth_header.dart';
import 'social_sign_in_buttons.dart';

/// Why the account screen opened. It names the headline and the one line
/// under it, and travels in the route as [wire].
enum AccountReason {
  postRequest('post_request'),
  postTrip('post_trip'),
  carry('carry'),
  alert('alert'),
  report('report'),
  deliveries('deliveries'),
  chat('chat'),
  notifications('notifications'),
  generic('generic');

  const AccountReason(this.wire);

  final String wire;

  static AccountReason parse(String? raw) => values.firstWhere(
    (reason) => reason.wire == raw,
    orElse: () => AccountReason.generic,
  );

  String title(L l) => switch (this) {
    postRequest => l.accountReasonPostRequestTitle,
    postTrip => l.accountReasonPostTripTitle,
    carry => l.accountReasonCarryTitle,
    alert => l.accountReasonAlertTitle,
    report => l.accountReasonReportTitle,
    deliveries => l.accountReasonDeliveriesTitle,
    chat => l.accountReasonChatTitle,
    notifications => l.accountReasonNotificationsTitle,
    generic => l.accountReasonGenericTitle,
  };

  String body(L l) => switch (this) {
    postRequest => l.accountReasonPostRequestBody,
    postTrip => l.accountReasonPostTripBody,
    carry => l.accountReasonCarryBody,
    alert => l.accountReasonAlertBody,
    report => l.accountReasonReportBody,
    deliveries => l.accountReasonDeliveriesBody,
    chat => l.accountReasonChatBody,
    notifications => l.accountReasonNotificationsBody,
    generic => l.accountReasonGenericBody,
  };
}

/// How an auth screen was opened: on its own (a link, the router's own
/// redirect) or inside the account moment.
@immutable
class AccountFlow {
  const AccountFlow._({required this.active, this.next});

  /// An auth screen on its own: the router's redirect decides where a
  /// successful sign-in goes.
  static const none = AccountFlow._(active: false);

  /// Read from the route the screen was built for.
  factory AccountFlow.of(GoRouterState state) {
    final query = state.uri.queryParameters;
    return AccountFlow._(
      active: isAccountFlowLocation(state.uri),
      next: query[_nextParameter],
    );
  }

  /// True inside the account moment.
  final bool active;

  /// Where to go once signed in, when the flow was opened for a place
  /// rather than for an action.
  final String? next;

  /// The query parameters a screen passes on to the next auth screen it
  /// opens, so a switch between sign-in and sign-up stays the same flow.
  Map<String, String> get parameters => {
    if (active) _flowParameter: '1',
    _nextParameter: ?next,
  };
}

const _flowParameter = 'continue';
const _nextParameter = 'next';

/// Whether [uri] is one of the account flow's routes. Read by the router,
/// which never moves a newly signed-in person off one: the flow ends itself.
bool isAccountFlowLocation(Uri uri) =>
    uri.path == '/auth/continue' ||
    (uri.path.startsWith('/auth/') &&
        uri.queryParameters[_flowParameter] == '1');

/// The pages of the account-flow screens pushed on [stack], by the key the
/// router gives each pushed page (`Page.key` is the match's `pageKey`).
Set<LocalKey> _pushedFlowPages(RouteMatchList stack) {
  final keys = <LocalKey>{};
  void walk(List<RouteMatchBase> matches) {
    for (final match in matches) {
      if (match is ImperativeRouteMatch) {
        if (isAccountFlowLocation(match.matches.uri)) keys.add(match.pageKey);
      } else if (match is ShellRouteMatch) {
        walk(match.matches);
      }
    }
  }

  walk(stack.matches);
  return keys;
}

/// Completed when the account screen opened by the pending [ensureAccount]
/// goes away, however it goes: closed, completed, or swept off by a new
/// stack (a notification tapped while it was open).
Completer<void>? _gateClosed;

/// Answers whether the person has an account, asking a guest to make one.
///
/// A member gets `true` at once. A guest sees the account screen for
/// [reason]; the answer is whether they are signed in when it closes, so
/// closing it is a plain "no" and the caller does nothing. While the session
/// is still being restored nothing is asked and the answer is `false`.
Future<bool> ensureAccount(BuildContext context, AccountReason reason) async {
  final container = ProviderScope.containerOf(context, listen: false);
  final session = container.read(sessionProvider);
  if (session is SessionSignedIn) return true;
  if (session is! SessionSignedOut) return false;

  final router = GoRouter.of(context);
  // A second tap while the first one's account screen is opening.
  if (isAccountFlowLocation(router.state.uri)) return false;

  final closed = _gateClosed = Completer<void>();
  unawaited(
    router
        .pushNamed<void>(
          Routes.accountGate,
          queryParameters: {'reason': reason.wire},
        )
        .whenComplete(() {
          if (!closed.isCompleted) closed.complete();
        }),
  );
  // Held across the wait, so the answer is read only from a container that
  // is still alive: one disposed meanwhile (the app torn down with the
  // screen) closes the subscription, and nobody is waiting on the answer.
  // The caller's own widget may well be gone by then (guest Home becomes
  // member Home), which is no reason to drop the action it asked for.
  final answer = container.listen(sessionProvider, (_, _) {});
  try {
    await closed.future;
    return !answer.closed && answer.read() is SessionSignedIn;
  } finally {
    answer.close();
  }
}

/// Opens sign-in as an account flow, from a guest's own "Sign in".
Future<void> openSignIn(BuildContext context) => context.pushNamed<void>(
  Routes.signIn,
  queryParameters: {_flowParameter: '1'},
);

/// Ends the account moment: closes the gate and every sign-in, sign-up,
/// password, verify and name screen opened from it, in one step.
///
/// The screen underneath is the one the guest asked from, and the future
/// that opened the gate completes there. When the flow is the whole stack (it
/// was opened by a link), Home is put under the person instead. Called from a
/// screen the flow has already closed, it does nothing.
void completeAccountFlow(BuildContext context, AccountFlow flow) {
  if (ModalRoute.of(context)?.isActive == false) return;
  final router = GoRouter.of(context);
  final next = isSafePostLoginLocation(flow.next) ? flow.next : null;
  final stack = router.routerDelegate.currentConfiguration;
  if (isAccountFlowLocation(stack.uri)) {
    router.go(next ?? '/home');
    return;
  }
  final flowPages = _pushedFlowPages(stack);
  Navigator.of(context, rootNavigator: true).popUntil((route) {
    final page = route.settings;
    return page is! Page || !flowPages.contains(page.key);
  });
  if (next != null) router.push(next);
}

/// What happens once someone has signed in (or made their account) on an
/// auth screen opened as [flow]. The one place every way in ends: the email
/// sign-in, confirming the email after sign-up, and the account screen.
///
/// Inside the account flow it closes the flow, so the action or place it was
/// opened for goes ahead; an account without a name (a social sign-in that
/// gave none) is asked for one first, as the flow's last screen, which then
/// closes the flow itself. Outside one (the auth screen is the whole stack),
/// the router's redirect has already moved the member on, and Home asks for a
/// missing name ([AskForNameOnce]).
void finishSignIn(BuildContext context, AccountFlow flow) {
  if (!flow.active || ModalRoute.of(context)?.isActive == false) return;
  final container = ProviderScope.containerOf(context, listen: false);
  final account = container.read(accountProvider);
  if (account != null && account.fullName.trim().isEmpty) {
    container.read(accountNameAskedProvider.notifier).markAsked();
    context.pushNamed(Routes.accountName, queryParameters: flow.parameters);
    return;
  }
  completeAccountFlow(context, flow);
}

/// An account-flow screen (the gate, sign-in, sign-up, forgot password)
/// reached by someone already signed in, by a link: there is nothing to ask,
/// so the flow ends as soon as it shows.
class AccountFlowScreen extends ConsumerStatefulWidget {
  const AccountFlowScreen({required this.flow, required this.child, super.key});

  final AccountFlow flow;
  final Widget child;

  @override
  ConsumerState<AccountFlowScreen> createState() => _AccountFlowScreenState();
}

class _AccountFlowScreenState extends ConsumerState<AccountFlowScreen> {
  @override
  void initState() {
    super.initState();
    if (widget.flow.active && ref.read(sessionProvider) is SessionSignedIn) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _endOnceShown());
    }
  }

  /// Once the screen has finished coming in: replacing the stack while the
  /// one it replaced is still leaving would build the shell twice.
  void _endOnceShown() {
    if (!mounted) return;
    final animation = ModalRoute.of(context)?.animation;
    if (animation == null || animation.isCompleted) {
      completeAccountFlow(context, widget.flow);
      return;
    }
    void shown(AnimationStatus status) {
      if (!status.isCompleted) return;
      animation.removeStatusListener(shown);
      if (mounted) completeAccountFlow(context, widget.flow);
    }

    animation.addStatusListener(shown);
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// The account screen.
class AccountGateScreen extends ConsumerStatefulWidget {
  const AccountGateScreen({required this.reason, super.key});

  final AccountReason reason;

  /// Runs [signIn], started from a widget on the account screen whose caller
  /// then calls [finishSignIn] itself, so the screen does not also finish it
  /// when the session turns signed in.
  static Future<T> finishingHere<T>(
    BuildContext context,
    Future<T> Function() signIn,
  ) async {
    final gate = context.findAncestorStateOfType<_AccountGateScreenState>();
    if (gate == null) return signIn();
    gate._finishedByCaller++;
    try {
      return await signIn();
    } finally {
      gate._finishedByCaller--;
    }
  }

  @override
  ConsumerState<AccountGateScreen> createState() => _AccountGateScreenState();
}

class _AccountGateScreenState extends ConsumerState<AccountGateScreen> {
  static const _flow = AccountFlow._(active: true);

  /// Sign-ins started on this screen whose caller calls [finishSignIn] itself.
  int _finishedByCaller = 0;

  @override
  void dispose() {
    final closed = _gateClosed;
    if (closed != null && !closed.isCompleted) closed.complete();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    // A sign-in that finished with this screen on top and nobody left to
    // finish it (a sign-in screen backed out of while it was answering) is
    // finished here, the one way every sign-in is.
    ref.listen(sessionProvider, (previous, next) {
      if (previous is! SessionSignedIn &&
          next is SessionSignedIn &&
          _finishedByCaller == 0 &&
          (ModalRoute.of(context)?.isCurrent ?? false)) {
        finishSignIn(context, _flow);
      }
    });

    return AppScaffold(
      body: ListView(
        padding: AppScrollPadding.page(context, top: AppSpace.md),
        children: [
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: PaperCloseButton(),
          ),
          const SizedBox(height: AppSpace.xxl),
          AuthHeader(
            stamp: l.accountGateStamp,
            headline: widget.reason.title(l),
            subhead: widget.reason.body(l),
            stampColor: c.brandInk,
            showBack: false,
          ),
          const SocialSignInButtons(flow: _flow),
          AppButton(
            label: l.accountGateEmail,
            icon: Icons.mail_outline_rounded,
            onPressed: () => context.pushNamed(
              Routes.signUp,
              queryParameters: _flow.parameters,
            ),
          ),
          const SizedBox(height: AppSpace.sm),
          AppButton(
            label: l.accountGateHaveAccount,
            variant: AppButtonVariant.tertiary,
            onPressed: () => context.pushNamed(
              Routes.signIn,
              queryParameters: _flow.parameters,
            ),
          ),
        ],
      ),
    );
  }
}
