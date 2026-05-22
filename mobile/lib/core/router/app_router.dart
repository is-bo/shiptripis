import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth_notifier.dart';
import '../../core/verification/verification_repository.dart';
import '../../features/auth/forgot_password_screen.dart';
import '../../features/auth/sign_in_screen.dart';
import '../../features/auth/sign_up_screen.dart';
import '../../features/matching/match_detail_screen.dart';
import '../../features/onboarding/benefits_carousel_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/onboarding/role_select_screen.dart';
import '../../features/sender/find_travelers_screen.dart';
import '../../features/sender/follow_package_screen.dart';
import '../../features/sender/make_request_screen.dart';
import '../../features/sender/my_requests_screen.dart';
import '../../features/sender/payment_screen.dart';
import '../../features/sender/search_filter_screen.dart';
import '../../features/shell/app_shell.dart';
import '../../features/traveler/create_trip_screen.dart';
import '../../features/traveler/find_parcels_screen.dart';
import '../../features/verification/handover_issue_screen.dart';
import '../../features/verification/handover_verify_screen.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/',
    redirect: (context, state) {
      final auth = ref.read(authNotifierProvider);
      if (auth is! AuthSignedIn) return null;

      final loc = state.matchedLocation;
      final serverRole = auth.user.role;

      // Pure-sender server role cannot enter traveler-only screens.
      if (serverRole == 'sender' &&
          (loc.startsWith('/traveler/'))) {
        return '/app';
      }
      // Pure-traveler server role cannot enter sender-only screens.
      if (serverRole == 'traveler' &&
          (loc.startsWith('/sender/'))) {
        return '/app';
      }
      return null;
    },
    routes: [
      GoRoute(path: '/', builder: (_, _) => const OnboardingScreen()),
      GoRoute(
          path: '/benefits', builder: (_, _) => const BenefitsCarouselScreen()),
      GoRoute(path: '/auth/sign-in', builder: (_, _) => const SignInScreen()),
      GoRoute(path: '/auth/sign-up', builder: (_, _) => const SignUpScreen()),
      GoRoute(
          path: '/auth/forgot', builder: (_, _) => const ForgotPasswordScreen()),
      GoRoute(path: '/role', builder: (_, _) => const RoleSelectScreen()),
      GoRoute(path: '/app', builder: (_, _) => const AppShell()),
      GoRoute(
          path: '/sender/new', builder: (_, _) => const MakeRequestScreen()),
      GoRoute(
          path: '/sender/requests',
          builder: (_, _) => const MyRequestsScreen()),
      GoRoute(
          path: '/sender/search',
          builder: (_, _) => const SearchFilterScreen()),
      GoRoute(
        path: '/sender/results',
        builder: (_, state) {
          final q = state.uri.queryParameters;
          return FindTravelersScreen(
            originIata: q['from'] ?? '',
            destinationIata: q['to'] ?? '',
            minCapacityKg: int.tryParse(q['kg'] ?? '') ?? 1,
          );
        },
      ),
      GoRoute(
          path: '/traveler/new', builder: (_, _) => const CreateTripScreen()),
      GoRoute(
          path: '/traveler/find',
          builder: (_, _) => const FindParcelsScreen()),
      GoRoute(
        path: '/match/:id',
        builder: (_, state) =>
            MatchDetailScreen(matchId: int.parse(state.pathParameters['id']!)),
      ),
      GoRoute(
        path: '/payment/:id',
        builder: (_, state) => PaymentScreen(
          offerId: state.pathParameters['id']!,
          matchId: int.tryParse(state.uri.queryParameters['match'] ?? ''),
        ),
      ),
      GoRoute(
        path: '/code/:id',
        redirect: (_, state) =>
            '/handover/issue/${state.pathParameters['id']}?kind=pickup',
      ),
      GoRoute(
        path: '/handover/issue/:id',
        builder: (_, state) => HandoverIssueScreen(
          matchId: int.parse(state.pathParameters['id']!),
          kind: (state.uri.queryParameters['kind'] == 'delivery')
              ? HandoverKind.delivery
              : HandoverKind.pickup,
        ),
      ),
      GoRoute(
        path: '/handover/verify/:id',
        builder: (_, state) => HandoverVerifyScreen(
          matchId: int.parse(state.pathParameters['id']!),
          kind: (state.uri.queryParameters['kind'] == 'delivery')
              ? HandoverKind.delivery
              : HandoverKind.pickup,
        ),
      ),
      GoRoute(
        path: '/tracking/:id',
        builder: (_, state) =>
            FollowPackageScreen(matchId: state.pathParameters['id']!),
      ),
    ],
  );
});

// Keep a deprecated top-level alias so any lingering imports don't break the
// build during this transition. New code should use appRouterProvider.
@Deprecated('use appRouterProvider')
GoRouter? appRouter;
