/// The launch screen.
///
/// Held only while the session is being restored, which normally takes a few
/// hundred milliseconds. Three decisions worth stating:
///
/// * **No spinner for the first moment.** On a warm start the restore finishes
///   before a progress indicator would have finished fading in, and a flash of
///   loading reads as a stutter. The indicator appears only if the wait turns
///   out to be real.
///
/// * **A long wait gets an exit.** A cold start with no network legitimately
///   sits here, because being offline is not being signed out and the router
///   deliberately refuses to bounce the user to a sign-in screen for it. That
///   is the right call, and it makes an escape hatch mandatory: after a while
///   this screen says what is happening and offers to try again.
///
/// * **It is a ShipTrip screen, not a loading screen.** The original build had
///   no splash to copy — it bootstrapped straight into the welcome page — so
///   this one is written in the original's language rather than recovered from
///   it: parchment, grain, the wordmark, and the route tracer already flying.
///   The first frame of the app should already look like the app.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session/session.dart';
import '../../design/identity.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../l10n/app_localizations.dart';

class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  static const _showProgressAfter = Duration(milliseconds: 600);
  static const _offerRetryAfter = Duration(seconds: 8);

  Timer? _progressTimer;
  Timer? _retryTimer;
  bool _showProgress = false;
  bool _offerRetry = false;

  @override
  void initState() {
    super.initState();
    _progressTimer = Timer(_showProgressAfter, () {
      if (mounted) setState(() => _showProgress = true);
    });
    _retryTimer = Timer(_offerRetryAfter, () {
      if (mounted) setState(() => _offerRetry = true);
    });
  }

  @override
  void dispose() {
    _progressTimer?.cancel();
    _retryTimer?.cancel();
    super.dispose();
  }

  Future<void> _retry() async {
    setState(() {
      _offerRetry = false;
      _showProgress = true;
    });
    _retryTimer?.cancel();
    _retryTimer = Timer(_offerRetryAfter, () {
      if (mounted) setState(() => _offerRetry = true);
    });
    await ref.read(sessionProvider.notifier).restore();
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppScaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpace.x3l),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Entrance(rise: 0, child: RouteTrace(height: 120)),
              const SizedBox(height: AppSpace.xxl),
              Entrance(
                delay: const Duration(milliseconds: 120),
                child: Semantics(
                  header: true,
                  label: l.appName,
                  excludeSemantics: true,
                  child: const ShipTripMark(size: 40),
                ),
              ),
              const SizedBox(height: AppSpace.md),
              Entrance(
                delay: const Duration(milliseconds: 240),
                rise: 6,
                child: Text(
                  l.onboardingStamp,
                  style: AppTypography.eyebrow(context, color: c.textTertiary),
                ),
              ),
              const SizedBox(height: AppSpace.x3l),
              SizedBox(
                height: 24,
                child: AnimatedOpacity(
                  opacity: _showProgress && !_offerRetry ? 1 : 0,
                  duration: AppMotion.respecting(context, AppMotion.normal),
                  child: SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.2,
                      color: c.brand,
                    ),
                  ),
                ),
              ),
              if (_offerRetry) ...[
                const SizedBox(height: AppSpace.lg),
                Semantics(
                  liveRegion: true,
                  child: Text(
                    l.stateOfflineBody,
                    style: text.bodyMedium?.copyWith(color: c.textSecondary),
                    textAlign: TextAlign.center,
                  ),
                ),
                const SizedBox(height: AppSpace.lg),
                TextButton(onPressed: _retry, child: Text(l.actionRetry)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
