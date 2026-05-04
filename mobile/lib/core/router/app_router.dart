import 'package:go_router/go_router.dart';

import '../../features/auth/forgot_password_screen.dart';
import '../../features/auth/sign_in_screen.dart';
import '../../features/auth/sign_up_screen.dart';
import '../../features/onboarding/benefits_carousel_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/onboarding/role_select_screen.dart';
import '../../features/sender/flight_tracking_screen.dart';
import '../../features/sender/make_request_screen.dart';
import '../../features/sender/offer_to_traveler_screen.dart';
import '../../features/sender/payment_screen.dart';
import '../../features/sender/pickup_code_screen.dart';
import '../../features/sender/search_filter_screen.dart';
import '../../features/shell/app_shell.dart';
import '../../features/traveler/create_trip_screen.dart';
import '../../features/traveler/offer_detail_screen.dart';
import '../../shared/mock/mock_data.dart';

final appRouter = GoRouter(
  initialLocation: '/',
  routes: [
    GoRoute(path: '/', builder: (_, __) => const OnboardingScreen()),
    GoRoute(
        path: '/benefits', builder: (_, __) => const BenefitsCarouselScreen()),
    GoRoute(path: '/auth/sign-in', builder: (_, __) => const SignInScreen()),
    GoRoute(path: '/auth/sign-up', builder: (_, __) => const SignUpScreen()),
    GoRoute(
        path: '/auth/forgot',
        builder: (_, __) => const ForgotPasswordScreen()),
    GoRoute(path: '/role', builder: (_, __) => const RoleSelectScreen()),
    GoRoute(path: '/app', builder: (_, __) => const AppShell()),
    GoRoute(
        path: '/sender/new', builder: (_, __) => const MakeRequestScreen()),
    GoRoute(
        path: '/sender/search',
        builder: (_, __) => const SearchFilterScreen()),
    GoRoute(
      path: '/sender/offer',
      builder: (_, state) {
        final t = state.extra as MockTraveler? ?? mockTravelers.first;
        return OfferToTravelerScreen(traveler: t);
      },
    ),
    GoRoute(
        path: '/traveler/new', builder: (_, __) => const CreateTripScreen()),
    GoRoute(
      path: '/offer',
      builder: (_, state) {
        final o = state.extra as MockOffer? ?? mockOffers.first;
        return OfferDetailScreen(offer: o);
      },
    ),
    GoRoute(
      path: '/payment/:id',
      builder: (_, state) =>
          PaymentScreen(offerId: state.pathParameters['id']!),
    ),
    GoRoute(
      path: '/code/:id',
      builder: (_, state) =>
          PickupCodeScreen(offerId: state.pathParameters['id']!),
    ),
    GoRoute(
      path: '/tracking/:id',
      builder: (_, state) =>
          FlightTrackingScreen(tripId: state.pathParameters['id']!),
    ),
  ],
);
