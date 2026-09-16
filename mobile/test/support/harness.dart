/// Shared test scaffolding.
///
/// Pumps a widget inside the real theme and the real localisations, because
/// most of what these tests check — directionality, tap-target sizes, whether
/// a label is a translated string at all — is only true inside them.
library;

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/design/theme.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

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

/// Pumps [child] inside the app's own theme, localisations and providers.
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
  // `Override` is not nameable from Riverpod 3's public API, so a test that
  // needs stubbed providers builds its own container and hands it over.
  final scope = container ?? ProviderContainer();
  addTearDown(scope.dispose);
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

  const supported = [Locale('en'), Locale('fr'), Locale('ar')];
  const delegates = [
    L.delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
  ];
  final theme = buildAppTheme(brightness: Brightness.light, locale: locale);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: scope,
      child: routed
          ? MaterialApp.router(
              locale: locale,
              supportedLocales: supported,
              localizationsDelegates: delegates,
              theme: theme,
              builder: applyMedia,
              routerConfig: GoRouter(
                initialLocation: '/host/screen',
                routes: [
                  GoRoute(
                    path: '/host',
                    builder: (_, _) => const Scaffold(body: SizedBox.shrink()),
                    routes: [GoRoute(path: 'screen', builder: (_, _) => child)],
                  ),
                  // Destinations a screen under test navigates to by name.
                  ...extraRoutes,
                ],
              ),
            )
          : MaterialApp(
              locale: locale,
              supportedLocales: supported,
              localizationsDelegates: delegates,
              theme: theme,
              builder: applyMedia,
              home: child,
            ),
    ),
  );
  await tester.pump();
}
