/// Shared test scaffolding.
///
/// Pumps a widget inside the real theme and the real localisations, because
/// most of what these tests check — directionality, tap-target sizes, whether
/// a label is a translated string at all — is only true inside them.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/app_settings.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';
import 'package:shiptrip/design/theme.dart';

import 'fake_api.dart';

/// Device sizes the layout has to survive.
///
/// These are the real problem cases, not a tidy grid: a small Android phone, a
/// mainstream one, a phone with a gesture pill, an iPhone with a home
/// indicator, and landscape — which is where a docked bar and a keyboard fight
/// hardest for room.
class DeviceProfile {
  const DeviceProfile({
    required this.name,
    required this.size,
    this.viewPadding = EdgeInsets.zero,
    this.textScale = 1.0,
  });

  final String name;
  final Size size;

  /// The system inset the bar must clear — a gesture pill or a home indicator.
  final EdgeInsets viewPadding;

  final double textScale;

  static const smallAndroid = DeviceProfile(
    name: 'small Android (320x640)',
    size: Size(320, 640),
  );

  static const android = DeviceProfile(
    name: 'Android (411x869)',
    size: Size(411, 869),
    viewPadding: EdgeInsets.only(top: 24),
  );

  static const androidGesture = DeviceProfile(
    name: 'Android gesture nav (411x869)',
    size: Size(411, 869),
    viewPadding: EdgeInsets.only(top: 24, bottom: 24),
  );

  static const iphone = DeviceProfile(
    name: 'iPhone home indicator (390x844)',
    size: Size(390, 844),
    viewPadding: EdgeInsets.only(top: 47, bottom: 34),
  );

  static const landscape = DeviceProfile(
    name: 'landscape (844x390)',
    size: Size(844, 390),
    viewPadding: EdgeInsets.only(left: 47, right: 34),
  );

  static const largeText = DeviceProfile(
    name: 'large text (390x844 @1.6)',
    size: Size(390, 844),
    viewPadding: EdgeInsets.only(top: 47, bottom: 34),
    textScale: 1.6,
  );

  static const all = [
    smallAndroid,
    android,
    androidGesture,
    iphone,
    landscape,
    largeText,
  ];
}

/// Pumps [child] inside the app's own theme, localisations and providers, on a
/// real router stack it can pop from.
///
/// For screens that finish by calling `context.pop()` — a form that closes on
/// save. Under a bare `MaterialApp` those throw `No GoRouter found in
/// context`, and swallowing that would mean the test never checks the thing
/// the user actually experiences.
///
/// The stack is two deep on purpose: a single route has nothing to pop to.
Future<void> pumpRouted(
  WidgetTester tester,
  Widget child, {
  DeviceProfile device = DeviceProfile.android,
  Locale locale = const Locale('en'),
  ProviderContainer? container,
  double? keyboardInset,
}) => pumpApp(
  tester,
  child,
  device: device,
  locale: locale,
  container: container,
  keyboardInset: keyboardInset,
  routed: true,
);

/// Pumps [child] inside the app's own theme, localisations and providers,
/// inside the member boundary as `main()` runs the app: an end of the
/// container's sign-in builds a new container ([nextContainerOf], or one with
/// only the same core) and pumps [child] again in it.
Future<void> pumpApp(
  WidgetTester tester,
  Widget child, {
  DeviceProfile device = DeviceProfile.android,
  Locale locale = const Locale('en'),
  ProviderContainer? container,
  double? keyboardInset,
  bool routed = false,
  List<RouteBase> extraRoutes = const [],
}) async {
  // A test that needs stubbed providers builds its own container and hands
  // it over.
  final scope =
      container ??
      ProviderContainer(
        overrides: [
          sessionCoreProvider.overrideWithValue(
            coreFor(FakeBackend(), signedIn: false),
          ),
        ],
      );
  addTearDown(scope.dispose);
  final session = _coreOf(scope);
  final next =
      nextContainerOf(scope) ??
      () => ProviderContainer(
        overrides: [sessionCoreProvider.overrideWithValue(session)],
      );
  var first = true;
  ProviderContainer build() {
    if (!first) return next();
    first = false;
    return scope;
  }

  // Order matters: the ratio has to be 1 before the physical size is set, or
  // the window ends up `size * originalRatio` logical pixels tall and every
  // geometric assertion below is measured against a viewport that does not
  // exist on any real phone.
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = device.size;
  addTearDown(tester.view.reset);

  Widget applyMedia(BuildContext context, Widget? inner) => MediaQuery(
    data: MediaQuery.of(context).copyWith(
      size: device.size,
      viewPadding: device.viewPadding,
      padding: device.viewPadding,
      viewInsets: keyboardInset == null
          ? EdgeInsets.zero
          : EdgeInsets.only(bottom: keyboardInset),
      textScaler: TextScaler.linear(device.textScale),
    ),
    child: inner ?? const SizedBox.shrink(),
  );

  final theme = buildAppTheme(brightness: Brightness.light, locale: locale);

  await tester.pumpWidget(
    MemberBoundary(
      session: session,
      container: build,
      child: routed
          ? _HostRouter(
              builder: (router) => MaterialApp.router(
                locale: locale,
                supportedLocales: supportedLocales,
                localizationsDelegates: appLocalizationsDelegates,
                theme: theme,
                builder: applyMedia,
                routerConfig: router,
              ),
              extraRoutes: extraRoutes,
              child: child,
            )
          : MaterialApp(
              locale: locale,
              supportedLocales: supportedLocales,
              localizationsDelegates: appLocalizationsDelegates,
              theme: theme,
              builder: applyMedia,
              home: child,
            ),
    ),
  );
  await tester.pump();
}

/// The session core [container] holds, or one of nobody for a container that
/// has none: a test whose screen never reads the session.
SessionCore _coreOf(ProviderContainer container) {
  try {
    return container.read(sessionCoreProvider);
  } on Object {
    return coreFor(FakeBackend(), signedIn: false);
  }
}

/// A router of its own for each tree the boundary builds, as the app's
/// router is one per container: no navigator is shared between two trees.
class _HostRouter extends StatefulWidget {
  const _HostRouter({
    required this.builder,
    required this.child,
    required this.extraRoutes,
  });

  final Widget Function(GoRouter router) builder;
  final Widget child;
  final List<RouteBase> extraRoutes;

  @override
  State<_HostRouter> createState() => _HostRouterState();
}

class _HostRouterState extends State<_HostRouter> {
  late final GoRouter _router = GoRouter(
    initialLocation: '/host/screen',
    routes: [
      GoRoute(
        path: '/host',
        builder: (_, _) => const Scaffold(body: SizedBox.shrink()),
        routes: [GoRoute(path: 'screen', builder: (_, _) => widget.child)],
      ),
      // Destinations a screen under test navigates to by name.
      ...widget.extraRoutes,
    ],
  );

  @override
  void dispose() {
    _router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(_router);
}
