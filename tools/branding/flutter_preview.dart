import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/theme.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/features/onboarding/onboarding_screen.dart';
import 'package:shiptrip/features/auth/sign_in_screen.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';
import 'package:shiptrip/features/splash/splash_screen.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import '../../mobile/test/support/fake_api.dart';

void main() {
  const width = int.fromEnvironment('WASSLA_PREVIEW_WIDTH', defaultValue: 390);
  const device = width >= 768 ? '-desktop' : '';
  const out = String.fromEnvironment(
    'WASSLA_SCREENSHOT_DIR',
    defaultValue: 'build/rebrand/screenshots',
  );
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    await Directory(out).create(recursive: true);
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
    for (final family in [
      'Fraunces',
      'DMSans',
      'NotoSansArabic',
      'JetBrainsMono',
    ]) {
      await (FontLoader(
        family,
      )..addFont(rootBundle.load('assets/fonts/$family-Variable.ttf'))).load();
    }
  });
  final account = Account(
    id: 42,
    email: 'amina@example.test',
    fullName: 'Amina Bouzid',
    phone: '',
    wilaya: '',
    role: AccountRole.both,
    preferredLanguage: CommunicationLanguage.french,
    isEmailVerified: true,
    isPhoneVerified: false,
    isKycVerified: true,
    kycStatus: KycStatus.verified,
    dateJoined: DateTime(2026, 1, 1),
  );
  for (final mode in Brightness.values) {
    for (final lang in ['en', 'fr', 'ar']) {
      for (final entry in <String, Widget>{
        'home': const HomeScreen(),
        'welcome': const OnboardingScreen(),
        'sign-in': const SignInScreen(),
        'profile': const ProfileScreen(),
        'splash': const SplashScreen(),
      }.entries) {
        testWidgets('${entry.key} ${mode.name} $lang', (tester) async {
          tester.view.devicePixelRatio = 1;
          tester.view.physicalSize = Size(
            width.toDouble(),
            width >= 768 ? 900 : 844,
          );
          addTearDown(tester.view.reset);
          final scope = ProviderContainer(
            overrides: [
              attentionProvider.overrideWith((ref) => const []),
              currentDealsProvider.overrideWith((ref) => const AsyncData([])),
              myRequestsProvider.overrideWith((ref) => const AsyncData([])),
              myJourneysProvider.overrideWith((ref) => const AsyncData([])),
              tokenStoreProvider.overrideWithValue(FakeTokenStore()),
              accountProvider.overrideWithValue(account),
              completedDealsCountProvider.overrideWith(
                (ref) => const AsyncData(12),
              ),
              receivedRatingsProvider.overrideWith(
                (ref) => const AsyncData([]),
              ),
              unreadNotificationsProvider.overrideWith(
                (ref) => const AsyncData(0),
              ),
            ],
          );
          addTearDown(scope.dispose);
          final key = GlobalKey();
          await tester.pumpWidget(
            UncontrolledProviderScope(
              container: scope,
              child: MaterialApp(
                locale: Locale(lang),
                supportedLocales: L.supportedLocales,
                localizationsDelegates: L.localizationsDelegates,
                theme: buildAppTheme(brightness: mode, locale: Locale(lang)),
                builder: (context, child) => MediaQuery(
                  data: MediaQuery.of(context)
                      .copyWith(disableAnimations: true),
                  child: child!,
                ),
                home: RepaintBoundary(key: key, child: entry.value),
              ),
            ),
          );
          await tester.pump(const Duration(milliseconds: 500));
          await tester.runAsync(() async {
            await Future<void>.delayed(const Duration(milliseconds: 200));
          });
          await tester.pump();
          expect(tester.takeException(), isNull);
          await tester.runAsync(() async {
            final boundary =
                key.currentContext!.findRenderObject() as RenderRepaintBoundary;
            final image = await boundary.toImage(pixelRatio: 2);
            final data = await image.toByteData(format: ui.ImageByteFormat.png);
            await File('$out/app-${entry.key}${device}-${mode.name}-$lang.png')
                .writeAsBytes(data!.buffer.asUint8List());
            image.dispose();
          });
          await tester.pumpWidget(const SizedBox.shrink());
        });
      }
    }
  }
}
