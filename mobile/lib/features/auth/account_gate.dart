/// The account moment: what a guest meets when they ask for something only a
/// member can do.
///
/// [ensureAccount] is the one entry point. For a member it answers at once;
/// for a guest it opens [AccountGateScreen] (`/auth/continue`), which says
/// why an account is needed and offers the ways in. Sign-in and sign-up
/// opened from it carry `continue=1` and are an *account flow*: the router
/// never redirects them when the session turns signed in, and on success
/// [completeAccountFlow] closes every flow route in one step, so the
/// caller's `await ensureAccount(...)` resumes on the very screen the guest
/// was on and the action they asked for goes ahead.
library;

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
import 'auth_header.dart';

/// Why the account screen opened. It names the headline and the one line
/// under it, and travels in the route as [wire].
enum AccountReason {
  postRequest('post_request'),
  postTrip('post_trip'),
  carry('carry'),
  alert('alert'),
  propose('propose'),
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
    propose => l.accountReasonProposeTitle,
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
    propose => l.accountReasonProposeBody,
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
/// which never moves a newly signed-in person off one.
bool isAccountFlowLocation(Uri uri) =>
    uri.path == '/auth/continue' ||
    (uri.path.startsWith('/auth/') &&
        uri.queryParameters[_flowParameter] == '1');

const _flowAuthRoutes = {
  Routes.signIn,
  Routes.signUp,
  Routes.forgotPassword,
  Routes.verifyEmail,
};

bool _isAccountFlowRoute(Route<dynamic> route) {
  final settings = route.settings;
  if (settings.name == Routes.accountGate) return true;
  final arguments = settings.arguments;
  return _flowAuthRoutes.contains(settings.name) &&
      arguments is Map &&
      arguments[_flowParameter] == '1';
}

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

  await router.pushNamed<void>(
    Routes.accountGate,
    queryParameters: {'reason': reason.wire},
  );
  return container.read(sessionProvider) is SessionSignedIn;
}

/// Opens sign-in as an account flow, from a guest's own "Sign in".
Future<void> openSignIn(BuildContext context) => context.pushNamed<void>(
  Routes.signIn,
  queryParameters: {_flowParameter: '1'},
);

/// Ends the account moment: closes the gate and every sign-in, sign-up,
/// password and verify screen opened from it, in one step.
///
/// The screen underneath is the one the guest asked from, and the future
/// that opened the gate completes there. When the flow is the whole stack (it
/// was opened by a link), Home is put under the person instead.
void completeAccountFlow(BuildContext context, AccountFlow flow) {
  final router = GoRouter.of(context);
  final next = isSafePostLoginLocation(flow.next) ? flow.next : null;
  if (isAccountFlowLocation(router.routerDelegate.currentConfiguration.uri)) {
    router.go(next ?? '/home');
    return;
  }
  Navigator.of(
    context,
    rootNavigator: true,
  ).popUntil((route) => !_isAccountFlowRoute(route));
  if (next != null) router.push(next);
}

/// The account screen.
class AccountGateScreen extends ConsumerStatefulWidget {
  const AccountGateScreen({required this.reason, super.key});

  final AccountReason reason;

  @override
  ConsumerState<AccountGateScreen> createState() => _AccountGateScreenState();
}

class _AccountGateScreenState extends ConsumerState<AccountGateScreen> {
  static const _flow = AccountFlow._(active: true);

  @override
  void initState() {
    super.initState();
    // Only a link can open this for someone already signed in: there is
    // nothing to ask them.
    if (ref.read(sessionProvider) is SessionSignedIn) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) completeAccountFlow(context, _flow);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

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
          const AccountProviderButtons(),
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

/// The place for "Continue with Apple" and "Continue with Google" on the
/// account screen, above "Continue with email".
///
/// It renders nothing until those sign-ins exist: the buttons go here, each
/// followed by `SizedBox(height: AppSpace.sm)`, and a successful one calls
/// [completeAccountFlow] like the email sign-in does.
class AccountProviderButtons extends StatelessWidget {
  const AccountProviderButtons({super.key});

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
