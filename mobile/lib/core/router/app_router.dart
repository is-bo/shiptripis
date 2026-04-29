import 'package:go_router/go_router.dart';

import '../../features/onboarding/onboarding_screen.dart';
import '../../features/onboarding/role_select_screen.dart';
import '../../features/shell/app_shell.dart';
import '../../features/sender/make_request_screen.dart';
import '../../features/traveler/create_trip_screen.dart';
import '../../features/sender/search_filter_screen.dart';

final appRouter = GoRouter(
  initialLocation: '/',
  routes: [
    GoRoute(path: '/', builder: (_, __) => const OnboardingScreen()),
    GoRoute(path: '/role', builder: (_, __) => const RoleSelectScreen()),
    GoRoute(path: '/app', builder: (_, __) => const AppShell()),
    GoRoute(path: '/sender/new', builder: (_, __) => const MakeRequestScreen()),
    GoRoute(path: '/sender/search', builder: (_, __) => const SearchFilterScreen()),
    GoRoute(path: '/traveler/new', builder: (_, __) => const CreateTripScreen()),
  ],
);
