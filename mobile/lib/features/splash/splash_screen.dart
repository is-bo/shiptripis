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
/// * **Never long.** A stored sign-in is shown from its snapshot without
///   waiting for the network, and a store that cannot be read with the app on
///   screen signs the member out (`SessionCore.load`), so nothing holds a
///   person here.
///
/// * **It is a ShipTrip screen, not a loading screen.** The original build had
///   no splash to copy — it bootstrapped straight into the welcome page — so
///   this one is written in the original's language rather than recovered from
///   it: parchment, grain, the wordmark, and the route tracer already flying.
///   The first frame of the app should already look like the app.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../../design/identity.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../l10n/app_localizations.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  static const _showProgressAfter = Duration(milliseconds: 600);

  Timer? _progressTimer;
  bool _showProgress = false;

  @override
  void initState() {
    super.initState();
    _progressTimer = Timer(_showProgressAfter, () {
      if (mounted) setState(() => _showProgress = true);
    });
  }

  @override
  void dispose() {
    _progressTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

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
                  opacity: _showProgress ? 1 : 0,
                  duration: AppMotion.respecting(context, AppMotion.normal),
                  child: SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.2,
                      color: c.brandInk,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
