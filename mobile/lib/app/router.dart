/// The route table.
///
/// ## Shape
///
/// Four tabs — Home, Deliveries, Chat, Profile — live inside a
/// [StatefulShellRoute.indexedStack], so each keeps its own navigation stack
/// and its own scroll position, and switching tabs costs no refetch.
///
/// **Notifications are not a tab.** They hang off the header bell, as a
/// full-screen route pushed above the shell. A notification inbox is something
/// a user visits occasionally and leaves; giving it a quarter of the
/// permanent navigation would cost the same space every screen, forever, to
/// serve a rare trip.
///
/// Everything that is a *task* rather than a *place* — creating a request,
/// paying, entering a handover code, opening a dispute — is pushed onto the
/// root navigator and therefore covers the bar. That is deliberate: a screen
/// with one job should not offer three ways to abandon it, and the task
/// screens are exactly the ones where a stray tab tap loses work.
///
/// ## Guarding
///
/// One redirect, driven by [SessionState]. It answers three questions and no
/// more: are we still restoring, is there a session, and is this route one of
/// the few that never needs one. Per-screen auth checks are not used — they
/// scatter the rule and always miss a case.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/session/session.dart';
import '../domain/canonical_place.dart';
import '../domain/location.dart';
import '../features/auth/forgot_password_screen.dart';
import '../features/auth/sign_in_screen.dart';
import '../features/auth/sign_up_screen.dart';
import '../features/auth/verify_email_screen.dart';
import '../features/chat/chat_list_screen.dart';
import '../features/chat/chat_thread_screen.dart';
import '../features/deals/cancel_screen.dart';
import '../features/deals/deal_screen.dart';
import '../features/deals/delivery_screen.dart';
import '../features/deals/payment_screen.dart';
import '../features/deals/pickup_screen.dart';
import '../features/deals/rate_screen.dart';
import '../features/deals/recipient_screen.dart';
import '../features/deliveries/deliveries_screen.dart';
import '../features/disputes/dispute_detail_screen.dart';
import '../features/disputes/dispute_open_screen.dart';
import '../features/guest/guest_pay_screen.dart';
import '../features/home/home_screen.dart';
import '../features/journeys/journey_create_screen.dart';
import '../features/journeys/journey_detail_screen.dart';
import '../features/journeys/journey_edit_screen.dart';
import '../features/journeys/leg_proof_screen.dart';
import '../features/kyc/kyc_screen.dart';
import '../features/location/canonical_place_picker_screen.dart';
import '../features/location/location_picker_screen.dart';
import '../features/notifications/notifications_screen.dart';
import '../features/offers/negotiation_screen.dart';
import '../features/onboarding/benefits_screen.dart';
import '../features/onboarding/onboarding_screen.dart';
import '../features/profile/appearance_screen.dart';
import '../features/profile/dzd_setup_screen.dart';
import '../features/profile/language_screen.dart';
import '../features/profile/notification_settings_screen.dart';
import '../features/profile/payout_detail_screen.dart';
import '../features/profile/payout_methods_screen.dart';
import '../features/profile/payouts_screen.dart';
import '../features/profile/profile_screen.dart';
import '../features/profile/ratings_screen.dart';
import '../features/requests/boost_screen.dart';
import '../features/requests/deposit_screen.dart';
import '../features/requests/discovery_screen.dart';
import '../features/requests/request_create_screen.dart';
import '../features/requests/request_detail_screen.dart';
import '../features/shell/app_shell.dart';
import '../features/splash/splash_screen.dart';

/// Route names. Screens navigate by name so a path change is a one-line edit
/// here rather than a search across thirty files.
abstract final class Routes {
  static const splash = 'splash';
  static const onboarding = 'onboarding';
  static const benefits = 'benefits';
  static const signIn = 'sign-in';
  static const signUp = 'sign-up';
  static const forgotPassword = 'forgot-password';
  static const verifyEmail = 'verify-email';

  static const home = 'home';
  static const deliveries = 'deliveries';
  static const chat = 'chat';
  static const profile = 'profile';

  static const notifications = 'notifications';

  static const requestCreate = 'request-create';
  static const requestDetail = 'request-detail';
  static const requestDeposit = 'request-deposit';
  static const requestDiscovery = 'request-discovery';
  static const requestBoost = 'request-boost';

  static const journeyCreate = 'journey-create';
  static const journeyDetail = 'journey-detail';
  static const journeyEdit = 'journey-edit';
  static const legProof = 'leg-proof';

  static const negotiation = 'negotiation';

  static const deal = 'deal';
  static const dealPayment = 'deal-payment';
  static const dealRecipient = 'deal-recipient';
  static const dealPickup = 'deal-pickup';
  static const dealDelivery = 'deal-delivery';
  static const dealCancel = 'deal-cancel';
  static const dealRate = 'deal-rate';

  static const disputeOpen = 'dispute-open';
  static const disputeDetail = 'dispute-detail';

  static const chatThread = 'chat-thread';

  static const kyc = 'kyc';
  static const locationPicker = 'location-picker';
  static const preferredLocationPicker = 'preferred-location-picker';
  static const guestPay = 'guest-pay';

  static const profileLanguage = 'profile-language';
  static const profileNotifications = 'profile-notifications';
  static const profileAppearance = 'profile-appearance';
  static const profileRatings = 'profile-ratings';
  static const profilePayouts = 'profile-payouts';
  static const profilePayoutMethods = 'profile-payout-methods';
  static const dzdProfileSetup = 'dzd-profile-setup';
  static const payoutDetail = 'payout-detail';
}

final _rootNavigatorKey = GlobalKey<NavigatorState>(debugLabel: 'root');

/// Routes that never require a session.
///
/// The guest payment link is the interesting one: somebody's relative in
/// Algiers opens it from a message, has no account, and must be able to pay.
const _publicPrefixes = <String>['/onboarding', '/auth', '/guest/pay'];

bool _isPublic(String location) =>
    _publicPrefixes.any((prefix) => location.startsWith(prefix));

bool _isSafePostLoginLocation(String? location) =>
    location != null &&
    location.startsWith('/') &&
    !location.startsWith('//') &&
    !_isPublic(location);

final routerProvider = Provider<GoRouter>((ref) {
  // go_router needs a Listenable, Riverpod speaks in providers. One notifier,
  // bumped whenever the session changes, bridges them without the router
  // itself being rebuilt from scratch on every auth event.
  final refresh = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: '/splash',
    refreshListenable: refresh,
    debugLogDiagnostics: false,

    redirect: (context, state) {
      final session = ref.read(sessionProvider);
      final location = state.matchedLocation;

      // Restoring: hold on the splash rather than flashing a sign-in screen at
      // a user who is already signed in. A cold start with no network stays
      // here too — being offline is not being signed out.
      if (session is SessionRestoring) {
        return location == '/splash' ? null : '/splash';
      }

      if (session is SessionSignedOut) {
        if (_isPublic(location)) return null;
        // Signed-out users land on onboarding, which offers both doors. It is
        // the product's front page, not a hurdle in front of sign-in.
        return session.becauseExpired ? '/auth/sign-in' : '/onboarding';
      }

      // Signed in. The auth screens and the splash are no longer valid places
      // to be — but the guest payment link stays reachable, because a signed-in
      // user can perfectly well be paying somebody else's obligation.
      if (location == '/splash' ||
          location.startsWith('/onboarding') ||
          location.startsWith('/auth')) {
        final next = state.uri.queryParameters['next'];
        if (_isSafePostLoginLocation(next)) return next;
        return '/home';
      }
      return null;
    },

    routes: [
      GoRoute(
        path: '/splash',
        name: Routes.splash,
        builder: (context, state) => const SplashScreen(),
      ),
      GoRoute(
        path: '/onboarding',
        name: Routes.onboarding,
        builder: (context, state) => const OnboardingScreen(),
        routes: [
          // The three-chapter story between the front page and sign-up. A
          // nested route so it inherits `/onboarding`'s public status, and
          // pushed rather than replaced so Back returns to the welcome screen
          // instead of leaving the app.
          GoRoute(
            path: 'benefits',
            name: Routes.benefits,
            builder: (context, state) => const BenefitsScreen(),
          ),
        ],
      ),

      // ---- Auth ----
      GoRoute(
        path: '/auth/sign-in',
        name: Routes.signIn,
        builder: (context, state) => const SignInScreen(),
      ),
      GoRoute(
        path: '/auth/sign-up',
        name: Routes.signUp,
        builder: (context, state) => const SignUpScreen(),
      ),
      GoRoute(
        path: '/auth/forgot',
        name: Routes.forgotPassword,
        builder: (context, state) => ForgotPasswordScreen(
          initialEmail: state.uri.queryParameters['email'],
        ),
      ),
      GoRoute(
        path: '/auth/verify-email',
        name: Routes.verifyEmail,
        builder: (context, state) =>
            VerifyEmailScreen(email: state.uri.queryParameters['email'] ?? ''),
      ),

      // ---- Guest payment: anonymous, outside the shell ----
      GoRoute(
        path: '/guest/pay/:token',
        name: Routes.guestPay,
        builder: (context, state) =>
            GuestPayScreen(token: state.pathParameters['token']!),
      ),

      // ---- The four tabs ----
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) =>
            AppShell(navigationShell: navigationShell),
        branches: [
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/home',
                name: Routes.home,
                builder: (context, state) => const HomeScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/deliveries',
                name: Routes.deliveries,
                builder: (context, state) => const DeliveriesScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/chat',
                name: Routes.chat,
                builder: (context, state) => const ChatListScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/profile',
                name: Routes.profile,
                builder: (context, state) => const ProfileScreen(),
              ),
            ],
          ),
        ],
      ),

      // ---- Above the shell ----
      GoRoute(
        path: '/notifications',
        name: Routes.notifications,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const NotificationsScreen(),
      ),

      GoRoute(
        path: '/requests/new',
        name: Routes.requestCreate,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const RequestCreateScreen(),
      ),
      GoRoute(
        path: '/requests/:id',
        name: Routes.requestDetail,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) =>
            RequestDetailScreen(requestId: _id(state, 'id')),
        routes: [
          GoRoute(
            path: 'deposit',
            name: Routes.requestDeposit,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                DepositScreen(requestId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'discovery',
            name: Routes.requestDiscovery,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                DiscoveryScreen(requestId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'boost',
            name: Routes.requestBoost,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                BoostScreen(requestId: _id(state, 'id')),
          ),
        ],
      ),

      GoRoute(
        path: '/journeys/new',
        name: Routes.journeyCreate,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const JourneyCreateScreen(),
      ),
      GoRoute(
        path: '/journeys/:id',
        name: Routes.journeyDetail,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) =>
            JourneyDetailScreen(journeyId: _id(state, 'id')),
        routes: [
          GoRoute(
            path: 'edit',
            name: Routes.journeyEdit,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                JourneyEditScreen(journeyId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'legs/:legId/proof',
            name: Routes.legProof,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) => LegProofScreen(
              journeyId: _id(state, 'id'),
              legId: _id(state, 'legId'),
            ),
          ),
        ],
      ),

      GoRoute(
        path: '/matches/:id',
        name: Routes.negotiation,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) =>
            NegotiationScreen(matchId: _id(state, 'id')),
      ),

      GoRoute(
        path: '/deals/:id',
        name: Routes.deal,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => DealScreen(dealId: _id(state, 'id')),
        routes: [
          GoRoute(
            path: 'payment',
            name: Routes.dealPayment,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                DealPaymentScreen(dealId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'recipient',
            name: Routes.dealRecipient,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                RecipientScreen(dealId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'pickup',
            name: Routes.dealPickup,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) => PickupScreen(dealId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'delivery',
            name: Routes.dealDelivery,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                DeliveryScreen(dealId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'cancel',
            name: Routes.dealCancel,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) => CancelScreen(dealId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'rate',
            name: Routes.dealRate,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) => RateScreen(dealId: _id(state, 'id')),
          ),
          GoRoute(
            path: 'dispute',
            name: Routes.disputeOpen,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                DisputeOpenScreen(dealId: _id(state, 'id')),
          ),
        ],
      ),

      GoRoute(
        path: '/disputes/:id',
        name: Routes.disputeDetail,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) =>
            DisputeDetailScreen(disputeId: _id(state, 'id')),
      ),

      // The conversation is full-screen. A chat composer plus a keyboard plus
      // a navigation bar is three fixed strips at the bottom of a small
      // phone, and the tab bar is the one that earns its place least while
      // somebody is typing.
      GoRoute(
        path: '/chat/thread/:matchId',
        name: Routes.chatThread,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => ChatThreadScreen(
          matchId: _id(state, 'matchId'),
          dealId: int.tryParse(state.uri.queryParameters['dealId'] ?? ''),
        ),
      ),

      GoRoute(
        path: '/kyc',
        name: Routes.kyc,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const KycScreen(),
      ),
      GoRoute(
        path: '/location/pick',
        name: Routes.locationPicker,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) {
          final current = state.extra;
          return CanonicalPlacePickerScreen(
            title: state.uri.queryParameters['title'],
            airportOnly: state.uri.queryParameters['airportOnly'] == 'true',
            current: current is CanonicalPlace ? current : null,
          );
        },
      ),
      GoRoute(
        path: '/location/preferred',
        name: Routes.preferredLocationPicker,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) {
          final place = state.extra;
          if (place is! CanonicalPlace) return const RouteNotFoundScreen();
          return LocationPickerScreen(
            canonicalPlace: place,
            title: state.uri.queryParameters['title'],
          );
        },
      ),

      GoRoute(
        path: '/profile/language',
        name: Routes.profileLanguage,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const LanguageScreen(),
      ),
      GoRoute(
        path: '/profile/notifications',
        name: Routes.profileNotifications,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const NotificationSettingsScreen(),
      ),
      GoRoute(
        path: '/profile/appearance',
        name: Routes.profileAppearance,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const AppearanceScreen(),
      ),
      GoRoute(
        path: '/profile/ratings',
        name: Routes.profileRatings,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const RatingsScreen(),
      ),
      GoRoute(
        path: '/profile/payouts',
        name: Routes.profilePayouts,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const PayoutsScreen(),
      ),
      GoRoute(
        path: '/profile/payout-methods',
        name: Routes.profilePayoutMethods,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const PayoutMethodsScreen(),
        routes: [
          GoRoute(
            path: 'dzd',
            name: Routes.dzdProfileSetup,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) => const DzdSetupScreen(),
          ),
        ],
      ),
      GoRoute(
        path: '/payouts/:reference',
        name: Routes.payoutDetail,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => PayoutDetailScreen(
          reference: state.pathParameters['reference'] ?? '',
        ),
      ),
    ],

    errorBuilder: (context, state) => const RouteNotFoundScreen(),
  );
});

int _id(GoRouterState state, String key) =>
    int.tryParse(state.pathParameters[key] ?? '') ?? 0;

// ---------------------------------------------------------------------------
// Navigation helpers
// ---------------------------------------------------------------------------

/// Typed navigation, so a caller cannot mistype a route name or forget a
/// parameter.
extension AppNavigation on BuildContext {
  void goHome() => goNamed(Routes.home);
  void goDeliveries() => goNamed(Routes.deliveries);
  void goChat() => goNamed(Routes.chat);
  void goProfile() => goNamed(Routes.profile);

  void openNotifications() => pushNamed(Routes.notifications);

  Future<void> openRequestCreate() => pushNamed(Routes.requestCreate);

  void openRequest(int id) =>
      pushNamed(Routes.requestDetail, pathParameters: {'id': '$id'});

  void openDeposit(int requestId) =>
      pushNamed(Routes.requestDeposit, pathParameters: {'id': '$requestId'});

  void openDiscovery(int requestId) =>
      pushNamed(Routes.requestDiscovery, pathParameters: {'id': '$requestId'});

  void openBoost(int requestId) =>
      pushNamed(Routes.requestBoost, pathParameters: {'id': '$requestId'});

  Future<void> openJourneyCreate() => pushNamed(Routes.journeyCreate);

  Future<void> openJourneyEdit(int id) =>
      pushNamed(Routes.journeyEdit, pathParameters: {'id': '$id'});

  void openJourney(int id) =>
      pushNamed(Routes.journeyDetail, pathParameters: {'id': '$id'});

  void openLegProof(int journeyId, int legId) => pushNamed(
    Routes.legProof,
    pathParameters: {'id': '$journeyId', 'legId': '$legId'},
  );

  void openNegotiation(int matchId) =>
      pushNamed(Routes.negotiation, pathParameters: {'id': '$matchId'});

  void openDeal(int id) =>
      pushNamed(Routes.deal, pathParameters: {'id': '$id'});

  void openDealPayment(int id) =>
      pushNamed(Routes.dealPayment, pathParameters: {'id': '$id'});

  /// Leave a finished payment for its request (J7D).
  ///
  /// A payment screen is usually pushed *from* the request, so "View request"
  /// pops back onto it; pushing another copy would leave the settled payment
  /// underneath, one Back away. Anywhere else — the payment was reached
  /// straight from request creation — the payment screen is replaced, so Back
  /// never returns to a payable form. The whole app is never reset to Home.
  void leavePaymentForRequest(int requestId) => _leavePaymentFor(
    Routes.requestDetail,
    '/requests/$requestId',
    {'id': '$requestId'},
  );

  /// Leave a finished payment for its delivery. See [leavePaymentForRequest].
  void leavePaymentForDeal(int dealId) =>
      _leavePaymentFor(Routes.deal, '/deals/$dealId', {'id': '$dealId'});

  void _leavePaymentFor(
    String name,
    String location,
    Map<String, String> pathParameters,
  ) {
    final router = GoRouter.maybeOf(this);
    if (router == null) return;
    final matches = router.routerDelegate.currentConfiguration.matches;
    final below = matches.length >= 2 ? matches[matches.length - 2] : null;
    if (below?.matchedLocation == location && canPop()) {
      pop();
      return;
    }
    pushReplacementNamed(name, pathParameters: pathParameters);
  }

  void openRecipient(int dealId) =>
      pushNamed(Routes.dealRecipient, pathParameters: {'id': '$dealId'});

  void openPickup(int dealId) =>
      pushNamed(Routes.dealPickup, pathParameters: {'id': '$dealId'});

  void openDelivery(int dealId) =>
      pushNamed(Routes.dealDelivery, pathParameters: {'id': '$dealId'});

  void openCancel(int dealId) =>
      pushNamed(Routes.dealCancel, pathParameters: {'id': '$dealId'});

  void openRate(int dealId) =>
      pushNamed(Routes.dealRate, pathParameters: {'id': '$dealId'});

  void openDisputeForm(int dealId) =>
      pushNamed(Routes.disputeOpen, pathParameters: {'id': '$dealId'});

  void openDispute(int disputeId) =>
      pushNamed(Routes.disputeDetail, pathParameters: {'id': '$disputeId'});

  void openChatThread(int matchId, {int? dealId}) => pushNamed(
    Routes.chatThread,
    pathParameters: {'matchId': '$matchId'},
    queryParameters: {if (dealId != null) 'dealId': '$dealId'},
  );

  void openKyc() => pushNamed(Routes.kyc);

  void openPayoutMethods() => pushNamed(Routes.profilePayoutMethods);
  void openDzdProfileSetup() => pushNamed(Routes.dzdProfileSetup);
  void openPayoutDetail(String reference) =>
      pushNamed(Routes.payoutDetail, pathParameters: {'reference': reference});

  /// Opens the country → place picker.
  ///
  /// [current] is what the caller already holds, if anything. Passing it is
  /// what makes "change the pickup city" resume from the right country with
  /// the current choice marked, instead of restarting from a blank screen.
  Future<CanonicalPlace?> pickCanonicalPlace({
    String? title,
    bool airportOnly = false,
    CanonicalPlace? current,
  }) => pushNamed<CanonicalPlace>(
    Routes.locationPicker,
    queryParameters: {'title': ?title, if (airportOnly) 'airportOnly': 'true'},
    extra: current,
  );

  Future<AppLocation?> pickPreferredLocation(
    CanonicalPlace place, {
    String? title,
  }) => pushNamed<AppLocation>(
    Routes.preferredLocationPicker,
    queryParameters: {'title': ?title},
    extra: place,
  );
}

/// Shown when a deep link points somewhere that no longer exists.
class RouteNotFoundScreen extends StatelessWidget {
  const RouteNotFoundScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.explore_off_rounded, size: 40),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () => context.goHome(),
              child: const Text('ShipTrip'),
            ),
          ],
        ),
      ),
    ),
  );
}
