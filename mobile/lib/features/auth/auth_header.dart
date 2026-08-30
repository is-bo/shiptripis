/// The masthead every pre-auth screen opens with.
///
/// Restored from the original ShipTrip auth screens, which had no app bar at
/// all. Instead: a circular back button floating on the parchment, a passport
/// stamp naming what you are about to do, a two-line serif headline set large
/// enough to be the only thing on the page that matters, and one plain
/// sentence under it.
///
/// It replaces `AppTopBar` on these four screens specifically. A title bar is
/// the right call for a screen you navigated *into*; it is the wrong call for
/// the front door, where the headline **is** the title and repeating it in a
/// 19pt bar above itself just makes the page look like a form.
///
/// The back affordance keeps `maybePop`, which is what the top bar used — so
/// the iOS edge swipe, the Android system back and this button all resolve
/// the same way, and none of them can drop the user out of the app from a
/// screen that was pushed.
library;

import 'package:flutter/material.dart';

import '../../design/identity.dart';
import '../../design/tokens.dart';

class AuthHeader extends StatelessWidget {
  const AuthHeader({
    required this.stamp,
    required this.headline,
    required this.subhead,
    this.stampColor,
    this.showBack = true,
    super.key,
  });

  /// The passport stamp — "WELCOME BACK", "JOIN THE CORRIDOR".
  final String stamp;

  /// Two or three short lines. Explicit `\n` in the catalogue, because where
  /// this breaks is a typographic decision and each language breaks it
  /// somewhere different.
  final String headline;

  final String subhead;
  final Color? stampColor;
  final bool showBack;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    // The headline steps down on a short phone rather than wrapping into a
    // fourth line and pushing the first field below the fold.
    final headlineSize = MediaQuery.sizeOf(context).height < 720 ? 32.0 : 38.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (showBack) ...[
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: PaperBackButton(),
          ),
          const SizedBox(height: AppSpace.xxl),
        ],
        Entrance(
          rise: -6,
          child: StampChip(label: stamp, color: stampColor ?? c.danger),
        ),
        const SizedBox(height: AppSpace.lg),
        Entrance(
          delay: const Duration(milliseconds: 60),
          rise: 8,
          child: Text(
            headline,
            style: text.displayLarge?.copyWith(
              fontSize: headlineSize,
              height: 1.02,
            ),
          ),
        ),
        const SizedBox(height: AppSpace.md),
        Entrance(
          delay: const Duration(milliseconds: 140),
          rise: 6,
          child: Text(
            subhead,
            style: text.bodyMedium?.copyWith(color: c.textSecondary),
          ),
        ),
        const SizedBox(height: AppSpace.x3l),
      ],
    );
  }
}
