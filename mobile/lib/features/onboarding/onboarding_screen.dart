/// The front page — the first thing anyone sees of ShipTrip.
///
/// This is the original ShipTrip welcome screen, restored: wordmark and an
/// "EST. 2026 · ALG ↔ FR" passport stamp across the top, the animated flight
/// path with the two corridor cities named underneath it, then the eyebrow,
/// the serif headline, the promise, and two doors — a sun-coloured "Get
/// started" and a ghost "Sign in".
///
/// Two things it is deliberately *not*: it is not a tutorial, and it is not a
/// gate. Both doors are visible from the first frame and nothing has to be
/// completed before they open. The three-chapter story behind "Get started"
/// is skippable from its own first page.
///
/// The composition is an [IntrinsicHeight] column inside a scroll view rather
/// than a plain [Column]: the hero and copy sit at the top, the actions are
/// pushed to the bottom by a [Spacer] on a tall phone, and on a short one the
/// whole thing scrolls instead of overflowing.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../app/router.dart';
import '../../design/components/primitives.dart';
import '../../design/identity.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../l10n/app_localizations.dart';

class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final size = MediaQuery.sizeOf(context);

    // The headline is the loudest thing on the screen and the first thing to
    // break on a small phone, so it steps down rather than wrapping into a
    // fourth line.
    final headlineSize = size.height < 720 ? 34.0 : 40.0;
    final heroHeight = (size.width * 0.42).clamp(140.0, 200.0);

    return AppScaffold(
      body: SingleChildScrollView(
        physics: const ClampingScrollPhysics(),
        padding: EdgeInsets.fromLTRB(
          AppSpace.xxl,
          AppSpace.lg,
          AppSpace.xxl,
          AppScrollPadding.bottomOf(context),
        ),
        child: ConstrainedBox(
          constraints: BoxConstraints(
            minHeight:
                size.height -
                MediaQuery.paddingOf(context).vertical -
                AppSpace.lg -
                AppScrollPadding.bottomOf(context),
          ),
          child: IntrinsicHeight(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Entrance(rise: 0, slide: -0.1, child: ShipTripMark()),
                    const SizedBox(width: AppSpace.md),
                    // Flexible, not a Spacer and a fixed chip: on a 320pt
                    // phone the wordmark and the stamp together are wider
                    // than the screen, and the stamp is the half that should
                    // give way.
                    Flexible(
                      child: Align(
                        alignment: AlignmentDirectional.centerEnd,
                        child: Entrance(
                          delay: const Duration(milliseconds: 500),
                          rise: -8,
                          child: StampChip(
                            label: l.onboardingStamp,
                            angle: 0.05,
                            color: c.danger,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpace.x3l),
                Entrance(
                  delay: const Duration(milliseconds: 150),
                  rise: 0,
                  child: RouteTrace(height: heroHeight),
                ),
                const SizedBox(height: AppSpace.md),
                Entrance(
                  delay: const Duration(milliseconds: 300),
                  child: _CorridorRow(
                    from: l.onboardingRouteFrom,
                    to: l.onboardingRouteTo,
                    meta: l.onboardingRouteMeta,
                  ),
                ),
                const SizedBox(height: AppSpace.x3l),
                Entrance(
                  delay: const Duration(milliseconds: 360),
                  child: Text(
                    l.onboardingEyebrow.toUpperCase(),
                    style: AppTypography.eyebrow(
                      context,
                      color: c.textTertiary,
                    ),
                  ),
                ),
                const SizedBox(height: AppSpace.md),
                Entrance(
                  delay: const Duration(milliseconds: 430),
                  rise: 12,
                  child: Text(
                    l.onboardingHeadline,
                    style: text.displayLarge?.copyWith(
                      fontSize: headlineSize,
                      height: 1.05,
                    ),
                  ),
                ),
                const SizedBox(height: AppSpace.lg),
                Entrance(
                  delay: const Duration(milliseconds: 560),
                  rise: 8,
                  child: Text(
                    l.onboardingBody,
                    style: text.bodyMedium?.copyWith(
                      color: c.textSecondary,
                      height: 1.55,
                    ),
                  ),
                ),
                const Spacer(),
                const SizedBox(height: AppSpace.xxl),
                Entrance(
                  delay: const Duration(milliseconds: 700),
                  rise: 8,
                  child: Row(
                    children: [
                      Expanded(
                        child: AppButton(
                          // The short label: this button shares its row with
                          // "Sign in", and "Create an account" wraps to two
                          // lines there on every phone narrower than a tablet.
                          label: l.onboardingGetStartedShort,
                          variant: AppButtonVariant.hero,
                          icon: Icons.arrow_forward_rounded,
                          onPressed: () => context.pushNamed(Routes.benefits),
                        ),
                      ),
                      const SizedBox(width: AppSpace.md),
                      AppButton(
                        label: l.authSignIn,
                        variant: AppButtonVariant.secondary,
                        expand: false,
                        onPressed: () => context.pushNamed(Routes.signIn),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpace.lg),
                Entrance(
                  delay: const Duration(milliseconds: 820),
                  rise: 0,
                  child: Row(
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          color: c.success,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: AppSpace.sm),
                      Flexible(
                        child: Text(
                          l.onboardingTrust,
                          style: text.bodySmall?.copyWith(
                            color: c.textTertiary,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The two ends of the corridor, named, with the leg between them.
///
/// It reads as a departure board, which is the point: the product is one
/// route, not a global marketplace, and saying so on the front page is
/// honest rather than limiting.
class _CorridorRow extends StatelessWidget {
  const _CorridorRow({
    required this.from,
    required this.to,
    required this.meta,
  });

  final String from;
  final String to;
  final String meta;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;

    Widget end(String city, String code, CrossAxisAlignment align) => Column(
      crossAxisAlignment: align,
      children: [
        Text(
          city,
          style: AppTypography.monoLabel(context, color: c.textTertiary),
        ),
        const SizedBox(height: 2),
        CountryPill(code: code, dense: true),
      ],
    );

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        end(from, 'DZ', CrossAxisAlignment.start),
        Flexible(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpace.sm),
            child: Text(
              meta,
              textAlign: TextAlign.center,
              overflow: TextOverflow.ellipsis,
              style: AppTypography.monoLabel(
                context,
                color: c.textTertiary,
                size: 10,
                tracking: 1.4,
              ),
            ),
          ),
        ),
        end(to, 'FR', CrossAxisAlignment.end),
      ],
    );
  }
}
