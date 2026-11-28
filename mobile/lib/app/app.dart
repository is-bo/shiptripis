import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_exception.dart';
import '../core/session/session_core.dart';
import '../design/theme.dart';
import '../core/push/push_coordinator.dart';
import 'app_state.dart';
import 'app_settings.dart';
import 'router.dart';

/// How a failed read is retried, for the whole app: `main` sets it on the
/// scope the app runs in. A failure that waiting cannot mend (a throttle, a
/// tier switched off, a refusal) is shown at once and asked again only when
/// the person does; a network or server failure, and a read cancelled
/// before it answered (the server refused nothing), are retried the way
/// Riverpod does by default. A provider that sets its own retry keeps it.
Duration? appRetry(int retryCount, Object error) {
  if (error is ApiException &&
      !error.isRetryable &&
      error.kind != ApiFailureKind.cancelled) {
    return null;
  }
  return ProviderContainer.defaultRetry(retryCount, error);
}

/// The member's screens, and the provider container they run in, end with
/// the member's sign-in (rule S-4).
///
/// When the sign-in the boundary has seen ends, the boundary builds a new
/// container from [container] and the app again under a new key: no route,
/// dialog, sheet, draft or gesture of the old tree is in the new one. The old
/// container is not told of the end (its session keeps showing the member
/// who left, whose client sends nothing more) and is disposed once the frame
/// that removed its screens is done. A guest who signs in keeps the tree.
///
/// What outlives a member is created outside and passed in through
/// [container]: the session core, the push messaging handle and the device
/// settings.
class MemberBoundary extends StatefulWidget {
  const MemberBoundary({
    required this.session,
    required this.container,
    required this.child,
    super.key,
  });

  final SessionCore session;

  /// Builds a member's container: the first one, and one after every end.
  final ProviderContainer Function() container;

  final Widget child;

  @override
  State<MemberBoundary> createState() => _MemberBoundaryState();
}

class _MemberBoundaryState extends State<MemberBoundary> {
  late ProviderContainer _container = widget.container();
  String? _sid;

  @override
  void initState() {
    super.initState();
    _sid = widget.session.current?.sid;
    widget.session.addListener(_changed);
  }

  void _changed() {
    final sid = widget.session.current?.sid;
    if (_sid != null && sid != _sid) {
      final ended = _container;
      _container = widget.container();
      setState(() {});
      WidgetsBinding.instance.addPostFrameCallback((_) => ended.dispose());
    }
    _sid = sid;
  }

  @override
  void dispose() {
    widget.session.removeListener(_changed);
    _container.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => UncontrolledProviderScope(
    key: ObjectKey(_container),
    container: _container,
    child: widget.child,
  );
}

class ShipTripApp extends ConsumerWidget {
  const ShipTripApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final locale = ref.watch(localeProvider);
    final themeMode = ref.watch(themeModeProvider);
    final router = ref.watch(routerProvider);
    // Listened to, not watched: the coordinator has to exist for the whole
    // app run, but its state — permission, registration — changes on every
    // resume, and watching it rebuilt MaterialApp.router each time (K5).
    ref.listen(pushCoordinatorProvider, (_, _) {});

    // The theme is locale-dependent: Arabic swaps the whole type stack rather
    // than falling back glyph-by-glyph, so it has to be rebuilt when the
    // language changes.
    final Locale resolved = locale ?? ref.watch(effectiveLocaleProvider);

    return MaterialApp.router(
      title: 'Wassla',
      debugShowCheckedModeBanner: false,
      routerConfig: router,

      locale: locale,
      supportedLocales: supportedLocales,
      localizationsDelegates: appLocalizationsDelegates,

      theme: buildAppTheme(brightness: Brightness.light, locale: resolved),
      darkTheme: buildAppTheme(brightness: Brightness.dark, locale: resolved),
      themeMode: themeMode,

      builder: (context, child) {
        // Text scale is honoured, but capped. Above ~1.6 a lifecycle timeline
        // or a money breakdown stops fitting on a small phone at all; below
        // that everything in the design system is built to reflow. The cap is
        // generous enough to satisfy the accessibility requirement while
        // keeping payment screens legible.
        final media = MediaQuery.of(context);
        return MediaQuery(
          data: media.copyWith(
            textScaler: media.textScaler.clamp(
              minScaleFactor: 0.85,
              maxScaleFactor: 1.6,
            ),
          ),
          child: ResumeRefresher(child: child ?? const SizedBox.shrink()),
        );
      },
    );
  }
}
