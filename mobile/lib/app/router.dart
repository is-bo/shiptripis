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
/// more: are we still restoring, is there a session, and is this a place a
/// guest may look at ([isPublicLocation]). Per-screen auth checks are not
/// used — they scatter the rule and always miss a case. What a guest may look
/// at but not *do* is asked at the action, by `ensureAccount`.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/session/session.dart';
import '../domain/canonical_place.dart';
import '../domain/location.dart';
import '../domain/progress.dart';
import '../domain/public_discovery.dart';
import '../domain/reviews.dart';
import '../features/auth/account_gate.dart';
import '../features/auth/account_name_screen.dart';
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
import '../features/deals/schedule_change_answer_screen.dart';
import '../features/deliveries/deliveries_screen.dart';
import '../features/discovery/alerts_screen.dart';
import '../features/discovery/browse_screens.dart';
import '../features/discovery/person_screen.dart';
import '../features/discovery/public_profile_screen.dart';
import '../features/disputes/dispute_detail_screen.dart';
import '../features/disputes/dispute_open_screen.dart';
import '../features/guest/guest_pay_screen.dart';
import '../features/home/home_screen.dart';
import '../features/journeys/change_times_screen.dart';
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
import '../features/profile/appearance_screen.dart';
import '../features/profile/blocked_people_screen.dart';
import '../features/profile/delete_account_screen.dart';
import '../features/profile/dzd_setup_screen.dart';
import '../features/profile/language_screen.dart';
import '../features/profile/notification_settings_screen.dart';
import '../features/profile/payout_detail_screen.dart';
import '../features/profile/payout_methods_screen.dart';
import '../features/profile/payouts_screen.dart';
import '../features/profile/profile_screen.dart';
import '../features/profile/ratings_screen.dart';
import '../features/reviews/reviews_screen.dart';
import '../features/requests/boost_screen.dart';
import '../features/requests/deposit_screen.dart';
import '../features/requests/discovery_screen.dart';
import '../features/requests/request_create_screen.dart';
import '../features/requests/request_detail_screen.dart';
import '../features/shell/app_shell.dart';
import '../features/splash/splash_screen.dart';
import 'route_transition_tracker.dart';

/// Route names. Screens navigate by name so a path change is a one-line edit
/// here rather than a search across thirty files.
abstract final class Routes {
  static const splash = 'splash';
  static const howItWorks = 'how-it-works';
  static const accountGate = 'account-gate';
  static const signIn = 'sign-in';
  static const signUp = 'sign-up';
  static const forgotPassword = 'forgot-password';
  static const verifyEmail = 'verify-email';
  static const accountName = 'account-name';

  static const home = 'home';
  static const deliveries = 'deliveries';
  static const chat = 'chat';
  static const profile = 'profile';

  static const notifications = 'notifications';

  static const browseTrips = 'browse-trips';
  static const browseRequests = 'browse-requests';
  static const browsePeople = 'browse-people';
  static const person = 'person';
  static const reviewsPerson = 'reviews-person';
  static const reviewsTrip = 'reviews-trip';

  static const requestCreate = 'request-create';
  static const requestDetail = 'request-detail';
  static const requestDeposit = 'request-deposit';
  static const requestDiscovery = 'request-discovery';
  static const requestBoost = 'request-boost';

  static const journeyCreate = 'journey-create';
  static const journeyDetail = 'journey-detail';
  static const journeyEdit = 'journey-edit';
  static const legProof = 'leg-proof';
  static const journeyChangeTimes = 'journey-change-times';

  static const negotiation = 'negotiation';

  static const deal = 'deal';
  static const dealPayment = 'deal-payment';
  static const dealRecipient = 'deal-recipient';
  static const dealPickup = 'deal-pickup';
  static const dealDelivery = 'deal-delivery';
  static const dealCancel = 'deal-cancel';
  static const dealRate = 'deal-rate';
  static const dealScheduleChange = 'deal-schedule-change';

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
  static const profileBlocked = 'profile-blocked';
  static const profileDeleteAccount = 'profile-delete-account';
  static const profileRatings = 'profile-ratings';
  static const profilePublic = 'profile-public';
  static const profileAlerts = 'profile-alerts';
  static const profilePayouts = 'profile-payouts';
  static const profilePayoutMethods = 'profile-payout-methods';
  static const dzdProfileSetup = 'dzd-profile-setup';
  static const payoutDetail = 'payout-detail';
}

final _rootNavigatorKey = GlobalKey<NavigatorState>(debugLabel: 'root');

/// The places a guest may be. An entry ending in `/` is that whole subtree;
/// any other entry is that one location.
///
/// The four tabs are here because each has a guest state (Deliveries and
/// Chat explain themselves, Profile offers the way in). The guest payment
/// link is the other interesting one: somebody's relative in Algiers opens
/// it from a message, has no account, and must be able to pay.
const _publicLocations = <String>[
  '/home',
  '/deliveries',
  '/chat',
  '/profile',
  '/profile/language',
  '/profile/appearance',
  '/profile/notifications',
  '/how-it-works',
  '/location/pick',
  '/discover/',
  '/reviews/',
  '/auth/',
  '/guest/pay/',
];

/// Whether a signed-out person may open [path], a location without its
/// query.
bool isPublicLocation(String path) => _publicLocations.any(
  (entry) => entry.endsWith('/') ? path.startsWith(entry) : path == entry,
);

/// Whether [location] is a place in this app to return to after signing in:
/// a path of its own, never another host, the auth screens or the splash.
bool isSafePostLoginLocation(String? location) {
  if (location == null ||
      !location.startsWith('/') ||
      location.startsWith('//') ||
      location.contains(r'\') ||
      location.startsWith('/auth/') ||
      location == '/splash') {
    return false;
  }
  final uri = Uri.tryParse(location);
  return uri != null && !uri.hasScheme && uri.host.isEmpty;
}

/// Sign-in, as an account flow, that returns to [next] once it succeeds: it
/// closes itself and opens [next] above the screen beneath it, or in its
/// place when it is the whole stack.
String _signInFor(String next) => Uri(
  path: '/auth/sign-in',
  queryParameters: {'continue': '1', 'next': next},
).toString();

/// Every location on the stack, the bottom one first: the base and each
/// pushed route.
List<Uri> _stackLocations(RouteMatchList configuration) {
  final locations = <Uri>[configuration.uri];
  void walk(List<RouteMatchBase> matches) {
    for (final match in matches) {
      if (match is ImperativeRouteMatch) {
        locations.add(match.matches.uri);
      } else if (match is ShellRouteMatch) {
        walk(match.matches);
      }
    }
  }

  walk(configuration.matches);
  return locations;
}

/// A session that ends while a member-only screen is open puts the person on
/// Home with sign-in above it, which brings them back to that screen. One
/// that ends on screens a guest may see leaves them there, as a guest.
void _leavePrivateScreens(GoRouter router) {
  final configuration = router.routerDelegate.currentConfiguration;
  if (configuration.matches.isEmpty) return;
  final private = _stackLocations(
    configuration,
  ).where((location) => !isPublicLocation(location.path));
  if (private.isEmpty) return;
  router.go('/home');
  router.push(_signInFor(private.last.toString()));
}

/// Where the router sends a person in [session] who asks for [uri], or null
/// to let them stay.
String? _redirectFor(SessionState session, Uri uri) {
  final location = uri.path;

  // Restoring: hold on the splash rather than flashing a sign-in screen at a
  // user who is already signed in. A cold start with no network stays here
  // too — being offline is not being signed out.
  if (session is SessionRestoring) {
    return location == '/splash' ? null : '/splash';
  }

  // Signed out is a guest. Home is the front page, and a place only a member
  // can see asks them to sign in, as an account flow, which then opens it:
  // above the screen they were on, or in place of the sign-in when a link
  // brought them straight there.
  if (session is SessionSignedOut) {
    if (location == '/splash') return '/home';
    if (isPublicLocation(location)) return null;
    return _signInFor(uri.toString());
  }

  // Signed in. The auth screens and the splash are no longer valid places to
  // be — but the guest payment link stays reachable, because a signed-in user
  // can perfectly well be paying somebody else's obligation. The one auth
  // screens a signed-in person needs: confirming their own email, from
  // sign-up, from Profile, or when posting is refused; and naming an account
  // a social sign-in left without a name. And the account flow closes itself
  // once it succeeds, so the action that opened it goes ahead on the screen
  // underneath; reached by a member, it closes as it opens
  // ([AccountFlowScreen]).
  if (location == '/auth/verify-email' || location == '/auth/name') {
    return null;
  }
  if (isAccountFlowLocation(uri)) return null;
  if (location == '/splash' || location.startsWith('/auth/')) {
    final next = uri.queryParameters['next'];
    if (isSafePostLoginLocation(next)) return next;
    return '/home';
  }
  return null;
}

final routerProvider = Provider<GoRouter>((ref) {
  // go_router needs a Listenable, Riverpod speaks in providers. One notifier,
  // bumped when a session change moves the person, bridges them without the
  // router itself being rebuilt from scratch on every auth event.
  final refresh = ValueNotifier<int>(0);
  ref.onDispose(refresh.dispose);

  late final GoRouter router;
  ref.listen(sessionProvider, (previous, next) {
    if (previous is SessionSignedIn && next is SessionSignedOut) {
      _leavePrivateScreens(router);
    }
    // Only when the redirect now answers differently. A refresh rebuilds the
    // stack from what the router last reported, and every screen pushed on it
    // comes back as a new route whose result nobody awaits: the account
    // moment, which signs a guest in under the screen they asked from, would
    // never hear that it closed.
    final base = router.routerDelegate.currentConfiguration;
    if (base.isEmpty || _redirectFor(next, base.uri) != null) {
      refresh.value++;
    }
  });

  return router = GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: '/splash',
    refreshListenable: refresh,
    observers: [ref.read(routeTransitionTrackerProvider)],
    debugLogDiagnostics: false,
    redirect: (context, state) =>
        _redirectFor(ref.read(sessionProvider), state.uri),

    routes: [
      GoRoute(
        path: '/splash',
        name: Routes.splash,
        builder: (context, state) => const SplashScreen(),
      ),
      // The three-chapter story, opened from guest Home and guest Profile.
      GoRoute(
        path: '/how-it-works',
        name: Routes.howItWorks,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const BenefitsScreen(),
      ),

      // ---- Auth ----
      // Each account-flow screen is wrapped in [AccountFlowScreen], which ends
      // the flow at once for someone who reaches it already signed in.
      GoRoute(
        path: '/auth/continue',
        name: Routes.accountGate,
        builder: (context, state) => AccountFlowScreen(
          flow: AccountFlow.of(state),
          child: AccountGateScreen(
            reason: AccountReason.parse(state.uri.queryParameters['reason']),
          ),
        ),
      ),
      GoRoute(
        path: '/auth/sign-in',
        name: Routes.signIn,
        builder: (context, state) {
          final flow = AccountFlow.of(state);
          return AccountFlowScreen(
            flow: flow,
            child: SignInScreen(flow: flow),
          );
        },
      ),
      GoRoute(
        path: '/auth/sign-up',
        name: Routes.signUp,
        builder: (context, state) {
          final flow = AccountFlow.of(state);
          return AccountFlowScreen(
            flow: flow,
            child: SignUpScreen(flow: flow),
          );
        },
      ),
      GoRoute(
        path: '/auth/forgot',
        name: Routes.forgotPassword,
        builder: (context, state) {
          final flow = AccountFlow.of(state);
          return AccountFlowScreen(
            flow: flow,
            child: ForgotPasswordScreen(
              initialEmail: state.uri.queryParameters['email'],
              flow: flow,
            ),
          );
        },
      ),
      GoRoute(
        path: '/auth/verify-email',
        name: Routes.verifyEmail,
        builder: (context, state) => VerifyEmailScreen(
          email: state.uri.queryParameters['email'] ?? '',
          flow: AccountFlow.of(state),
        ),
      ),
      GoRoute(
        path: '/auth/name',
        name: Routes.accountName,
        builder: (context, state) =>
            AccountNameScreen(flow: AccountFlow.of(state)),
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
                builder: (context, state) =>
                    const AccountScope(child: HomeScreen()),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/deliveries',
                name: Routes.deliveries,
                builder: (context, state) =>
                    const AccountScope(child: DeliveriesScreen()),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/chat',
                name: Routes.chat,
                builder: (context, state) =>
                    const AccountScope(child: ChatListScreen()),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/profile',
                name: Routes.profile,
                builder: (context, state) =>
                    const AccountScope(child: ProfileScreen()),
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

      // ---- Discovery ----
      GoRoute(
        path: '/discover/trips',
        name: Routes.browseTrips,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => BrowseTripsScreen(
          corridor: _corridor(state),
          alertId: int.tryParse(state.uri.queryParameters['alert'] ?? ''),
          focusJourneyId: int.tryParse(
            state.uri.queryParameters['focus'] ?? '',
          ),
        ),
      ),
      GoRoute(
        path: '/discover/requests',
        name: Routes.browseRequests,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => BrowseRequestsScreen(
          corridor: _corridor(state),
          alertId: int.tryParse(state.uri.queryParameters['alert'] ?? ''),
          focusRequestId: int.tryParse(
            state.uri.queryParameters['focus'] ?? '',
          ),
          carryJourneyId: int.tryParse(
            state.uri.queryParameters['journey'] ?? '',
          ),
        ),
      ),
      GoRoute(
        path: '/discover/people',
        name: Routes.browsePeople,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const BrowsePeopleScreen(),
        routes: [
          GoRoute(
            path: ':id',
            name: Routes.person,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                PersonScreen(profileId: state.pathParameters['id'] ?? ''),
          ),
        ],
      ),

      GoRoute(
        path: '/reviews/person/:id',
        name: Routes.reviewsPerson,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => ReviewsScreen(
          subject: PersonReviews(state.pathParameters['id'] ?? ''),
        ),
      ),
      GoRoute(
        path: '/reviews/trip/:id',
        name: Routes.reviewsTrip,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => ReviewsScreen(
          subject: TripReviews(
            _id(state, 'id'),
            // Only Find Travelers passes the sender's own open request.
            requestId: int.tryParse(state.uri.queryParameters['request'] ?? ''),
          ),
        ),
      ),

      GoRoute(
        path: '/requests/new',
        name: Routes.requestCreate,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) {
          final prefill = state.extra;
          return RequestCreateScreen(
            prefill: prefill is RequestRoutePrefill ? prefill : null,
          );
        },
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
            builder: (context, state) => DiscoveryScreen(
              requestId: _id(state, 'id'),
              // A trip chosen in Browse, or named by an "I can carry this"
              // notification. Opens that trip's card once the list has it.
              focusJourneyId: int.tryParse(
                state.uri.queryParameters['journey'] ?? '',
              ),
            ),
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
        builder: (context, state) => JourneyDetailScreen(
          journeyId: _id(state, 'id'),
          // A reminder names the step it asks about.
          askLegId: int.tryParse(state.uri.queryParameters['leg'] ?? ''),
          askKind: ProgressKind.parse(state.uri.queryParameters['ask']),
        ),
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
          GoRoute(
            path: 'change-times',
            name: Routes.journeyChangeTimes,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                ChangeTimesScreen(journeyId: _id(state, 'id')),
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
            path: 'schedule-change',
            name: Routes.dealScheduleChange,
            parentNavigatorKey: _rootNavigatorKey,
            builder: (context, state) =>
                ScheduleChangeAnswerScreen(dealId: _id(state, 'id')),
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
        path: '/profile/blocked',
        name: Routes.profileBlocked,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const BlockedPeopleScreen(),
      ),
      GoRoute(
        path: '/profile/delete-account',
        name: Routes.profileDeleteAccount,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const DeleteAccountScreen(),
      ),
      GoRoute(
        path: '/profile/public',
        name: Routes.profilePublic,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const PublicProfileScreen(),
      ),
      GoRoute(
        path: '/profile/alerts',
        name: Routes.profileAlerts,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) => const AlertsScreen(),
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

/// The corridor a Browse link names: an origin and a destination country.
Corridor? _corridor(GoRouterState state) {
  final origin = state.uri.queryParameters['from'];
  final destination = state.uri.queryParameters['to'];
  if (origin == null || destination == null) return null;
  final corridor = Corridor(origin.toUpperCase(), destination.toUpperCase());
  return Corridor.launchCorridors.contains(corridor) ? corridor : null;
}

// ---------------------------------------------------------------------------
// Navigation helpers
// ---------------------------------------------------------------------------

/// Typed navigation, so a caller cannot mistype a route name or forget a
/// parameter.
extension AppNavigation on BuildContext {
  void goHome() => goNamed(Routes.home);
  void goDeliveries() => goNamed(Routes.deliveries);

  void openHowItWorks() => pushNamed(Routes.howItWorks);

  /// Opens the request form, optionally with the route already chosen (a trip
  /// the sender found in Browse). A guest makes an account first, and the
  /// form then opens with the same route, on top of the same screen.
  Future<void> openRequestCreate({
    CanonicalPlace? pickup,
    CanonicalPlace? delivery,
  }) async {
    final router = GoRouter.of(this);
    if (!await ensureAccount(this, AccountReason.postRequest)) return;
    await router.pushNamed<void>(
      Routes.requestCreate,
      extra: pickup == null && delivery == null
          ? null
          : RequestRoutePrefill(pickup: pickup, delivery: delivery),
    );
  }

  void openRequest(int id) =>
      pushNamed(Routes.requestDetail, pathParameters: {'id': '$id'});

  void openDeposit(int requestId) =>
      pushNamed(Routes.requestDeposit, pathParameters: {'id': '$requestId'});

  /// Find Travelers for one request. [focusJourneyId] puts one trip in focus:
  /// its card opens as soon as the list has it, or the server's reason for
  /// not listing it is shown.
  void openDiscovery(int requestId, {int? focusJourneyId}) => pushNamed(
    Routes.requestDiscovery,
    pathParameters: {'id': '$requestId'},
    queryParameters: {if (focusJourneyId != null) 'journey': '$focusJourneyId'},
  );

  /// Browse trips. [alertId] and [focusJourneyId] come from a route-alert
  /// notification: the alert's own route becomes the filter and the trip that
  /// triggered it opens.
  void openBrowseTrips({
    Corridor? corridor,
    int? alertId,
    int? focusJourneyId,
  }) => pushNamed(
    Routes.browseTrips,
    queryParameters: {
      if (corridor != null) 'from': corridor.originCountry,
      if (corridor != null) 'to': corridor.destinationCountry,
      if (alertId != null) 'alert': '$alertId',
      if (focusJourneyId != null) 'focus': '$focusJourneyId',
    },
  );

  /// [carryJourneyId] is the traveler's own trip named by a "a parcel fits
  /// your trip" alert: the preview of [focusRequestId] offers to carry it on
  /// that trip.
  void openBrowseRequests({
    Corridor? corridor,
    int? alertId,
    int? focusRequestId,
    int? carryJourneyId,
  }) => pushNamed(
    Routes.browseRequests,
    queryParameters: {
      if (corridor != null) 'from': corridor.originCountry,
      if (corridor != null) 'to': corridor.destinationCountry,
      if (alertId != null) 'alert': '$alertId',
      if (focusRequestId != null) 'focus': '$focusRequestId',
      if (carryJourneyId != null) 'journey': '$carryJourneyId',
    },
  );

  void openBrowsePeople() => pushNamed(Routes.browsePeople);

  void openPerson(String profileId) =>
      pushNamed(Routes.person, pathParameters: {'id': profileId});

  void openPersonReviews(String profileId) =>
      pushNamed(Routes.reviewsPerson, pathParameters: {'id': profileId});

  void openTripReviews(int journeyId, {int? requestId}) => pushNamed(
    Routes.reviewsTrip,
    pathParameters: {'id': '$journeyId'},
    queryParameters: {if (requestId != null) 'request': '$requestId'},
  );

  void openPublicProfile() => pushNamed(Routes.profilePublic);

  void openRouteAlerts() => pushNamed(Routes.profileAlerts);

  void openBoost(int requestId) =>
      pushNamed(Routes.requestBoost, pathParameters: {'id': '$requestId'});

  /// Opens the trip form. A guest makes an account first.
  Future<void> openJourneyCreate() async {
    final router = GoRouter.of(this);
    if (!await ensureAccount(this, AccountReason.postTrip)) return;
    await router.pushNamed<void>(Routes.journeyCreate);
  }

  Future<void> openJourneyEdit(int id) =>
      pushNamed(Routes.journeyEdit, pathParameters: {'id': '$id'});

  void openJourney(int id) =>
      pushNamed(Routes.journeyDetail, pathParameters: {'id': '$id'});

  /// A reminder's destination: the journey, with the question as a sheet.
  void openJourneyQuestion(int id, int legId, ProgressKind kind) => pushNamed(
    Routes.journeyDetail,
    pathParameters: {'id': '$id'},
    queryParameters: {'leg': '$legId', 'ask': kind.wire},
  );

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

  /// A sender's answer to new times, or what they were told about them.
  void openScheduleChange(int dealId) =>
      pushNamed(Routes.dealScheduleChange, pathParameters: {'id': '$dealId'});

  void openChangeTimes(int journeyId) => pushNamed(
    Routes.journeyChangeTimes,
    pathParameters: {'id': '$journeyId'},
  );

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
              child: const Text('Wassla'),
            ),
          ],
        ),
      ),
    ),
  );
}
