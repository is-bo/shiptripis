/// The ShipTrip identity kit.
///
/// Everything in this file is decoration in the strict sense — none of it
/// carries product state — but it is the decoration the product is recognised
/// by, and it is deliberately kept as first-class code rather than as ad-hoc
/// `Container`s inside screens.
///
/// The vocabulary is travel paperwork: parchment with a paper grain, passport
/// stamps, boarding passes with a perforated stub, postage marks, wax seals,
/// a dashed flight path with something moving along it. It was drawn entirely
/// with [CustomPainter] in the original build and stays that way here — there
/// is not a single raster asset in the app, so every mark is crisp at any
/// density, tintable per theme, and free.
///
/// Three rules every widget below obeys:
///
/// * **Tokens, never hex.** A stamp is `colors.danger`, a seal rim is
///   `colors.seal`. The kit therefore survives dark mode instead of turning
///   into a set of light-mode-only illustrations.
/// * **Reduced motion is honoured.** Every looping or entrance animation
///   checks [MediaQuery.disableAnimationsOf] and renders a correct, complete
///   static frame instead. Nothing here is load-bearing, so switching it off
///   costs no information.
/// * **Marks are not read aloud.** Seals, stamps, grain and route tracers are
///   wrapped in [ExcludeSemantics] unless they carry a word a screen reader
///   genuinely needs; the meaning always exists as real text nearby.
library;

import 'dart:math' as math;

import 'package:country_flags/country_flags.dart';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import 'tokens.dart';
import 'typography.dart';

// ---------------------------------------------------------------------------
// Entrance choreography
// ---------------------------------------------------------------------------

/// The staggered fade-and-rise that every ShipTrip screen opens with.
///
/// Wrapping it rather than calling `.animate()` inline is what makes "respect
/// reduce motion" true everywhere by construction: a screen cannot forget,
/// because there is no un-guarded spelling of the effect available to it.
class Entrance extends StatelessWidget {
  const Entrance({
    required this.child,
    this.delay = Duration.zero,
    this.rise = 10,
    this.slide = 0,
    super.key,
  });

  final Widget child;

  /// Position in the stagger. Roughly 80–120ms apart reads as one movement;
  /// much more and the screen assembles itself in front of the user.
  final Duration delay;

  /// Vertical travel, in logical pixels. Small on purpose — this is a settle,
  /// not an entrance from off-screen.
  final double rise;

  /// Horizontal travel as a fraction of the child's width. Sign is in
  /// *reading* order, so a positive value comes from the trailing edge in
  /// both English and Arabic.
  final double slide;

  @override
  Widget build(BuildContext context) {
    if (MediaQuery.disableAnimationsOf(context)) return child;

    final directedSlide = Directionality.of(context) == TextDirection.rtl
        ? -slide
        : slide;

    var animation = child.animate().fadeIn(
      delay: delay,
      duration: AppMotion.slow,
      curve: Curves.easeOut,
    );
    if (rise != 0) {
      animation = animation.moveY(
        begin: rise,
        end: 0,
        delay: delay,
        duration: AppMotion.expressive,
        curve: AppMotion.enter,
      );
    }
    if (directedSlide != 0) {
      animation = animation.slideX(
        begin: directedSlide,
        end: 0,
        delay: delay,
        duration: AppMotion.expressive,
        curve: AppMotion.enter,
      );
    }
    return animation;
  }
}

/// Convenience for a run of children that should enter one after another.
///
/// `step` is the gap between neighbours; `from` shifts the whole run later so
/// a section can follow the headline above it.
List<Widget> staggered(
  List<Widget> children, {
  Duration step = const Duration(milliseconds: 70),
  Duration from = Duration.zero,
  double rise = 10,
}) => [
  for (var i = 0; i < children.length; i++)
    Entrance(delay: from + step * i, rise: rise, child: children[i]),
];

// ---------------------------------------------------------------------------
// Paper
// ---------------------------------------------------------------------------

/// The paper grain drawn under every screen.
///
/// A few hundred sub-pixel dots at very low alpha. It is almost invisible in
/// a screenshot and completely obvious in its absence: it is the difference
/// between "warm off-white background" and "this is printed on something".
///
/// The seed is fixed so the speckle does not shimmer between rebuilds, and
/// the painter never repaints.
class PaperGrain extends StatelessWidget {
  const PaperGrain({this.density = 1, super.key});

  /// Multiplier on the dot count. Raise it for a small hero card, leave it at
  /// 1 for a full screen.
  final double density;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: IgnorePointer(
      child: CustomPaint(
        painter: _GrainPainter(color: context.colors.grain, density: density),
        size: Size.infinite,
      ),
    ),
  );
}

class _GrainPainter extends CustomPainter {
  const _GrainPainter({required this.color, required this.density});

  final Color color;
  final double density;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    // Scaled to area rather than fixed, so a small card and a tall screen get
    // the same *texture* instead of the same number of dots.
    final count = (size.width * size.height / 620 * density).clamp(60, 2600);
    final random = math.Random(7);
    final paint = Paint()..color = color;
    for (var i = 0; i < count; i++) {
      canvas.drawCircle(
        Offset(
          random.nextDouble() * size.width,
          random.nextDouble() * size.height,
        ),
        0.55,
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _GrainPainter old) =>
      old.color != color || old.density != density;
}

/// A horizontal perforation line — the tear-off on a boarding pass.
class DashedDivider extends StatelessWidget {
  const DashedDivider({
    this.color,
    this.thickness = 1,
    this.dash = 4,
    this.gap = 4,
    super.key,
  });

  final Color? color;
  final double thickness;
  final double dash;
  final double gap;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: CustomPaint(
      size: Size(double.infinity, thickness),
      painter: _DashedLinePainter(
        color: color ?? context.colors.hairlineStrong,
        thickness: thickness,
        dash: dash,
        gap: gap,
      ),
    ),
  );
}

class _DashedLinePainter extends CustomPainter {
  const _DashedLinePainter({
    required this.color,
    required this.thickness,
    required this.dash,
    required this.gap,
  });

  final Color color;
  final double thickness;
  final double dash;
  final double gap;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = thickness
      ..strokeCap = StrokeCap.round;
    for (var x = 0.0; x < size.width; x += dash + gap) {
      canvas.drawLine(
        Offset(x, size.height / 2),
        Offset(math.min(x + dash, size.width), size.height / 2),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _DashedLinePainter old) =>
      old.color != color ||
      old.thickness != thickness ||
      old.dash != dash ||
      old.gap != gap;
}

// ---------------------------------------------------------------------------
// Stamps and seals
// ---------------------------------------------------------------------------

/// A passport stamp: dashed rectangle, wide-tracked caps, slightly askew.
///
/// The rotation is the whole trick — a straight one reads as a chip, a
/// crooked one reads as something a border officer pressed onto a page. It is
/// deliberately tiny (a few hundredths of a radian); more looks like a bug.
class StampChip extends StatelessWidget {
  const StampChip({
    required this.label,
    this.color,
    this.angle = -0.04,
    this.icon,
    super.key,
  });

  final String label;
  final Color? color;
  final double angle;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final tint = color ?? context.colors.danger;
    return Transform.rotate(
      angle: angle,
      child: CustomPaint(
        painter: _DashedBorderPainter(color: tint.withValues(alpha: 0.75)),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null) ...[
                Icon(icon, size: 12, color: tint),
                const SizedBox(width: 5),
              ],
              // Shrinks rather than clips. A stamp is a graphic, so scaling
              // it down a few percent on a narrow phone costs nothing —
              // whereas an ellipsis mid-way through "EST. 2026 · ALG ↔ FR"
              // reads as a bug, and letting it overflow is one.
              Flexible(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: AlignmentDirectional.centerStart,
                  child: Text(
                    label.toUpperCase(),
                    maxLines: 1,
                    style: AppTypography.stamp(context, color: tint),
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

class _DashedBorderPainter extends CustomPainter {
  const _DashedBorderPainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4;
    final path = Path()
      ..addRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(0, 0, size.width, size.height),
          const Radius.circular(4),
        ),
      );
    const dash = 4.0;
    const gap = 3.0;
    for (final metric in path.computeMetrics()) {
      var distance = 0.0;
      while (distance < metric.length) {
        final next = math.min(distance + dash, metric.length);
        canvas.drawPath(metric.extractPath(distance, next), paint);
        distance = next + gap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DashedBorderPainter old) => old.color != color;
}

/// A blob of sealing wax with a letter pressed into it.
///
/// Used where the product wants to say "this is settled and witnessed" —
/// a completed handover, a verified identity, the trust panel in onboarding.
class WaxSeal extends StatelessWidget {
  const WaxSeal({
    required this.glyph,
    this.diameter = 44,
    this.color,
    super.key,
  });

  final String glyph;
  final double diameter;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    // Vivid, not the text terracotta: a seal is a shape, and the deeper
    // print colour reads as brown wax rather than as sealing wax.
    final tint = color ?? c.attentionVivid;
    return ExcludeSemantics(
      child: SizedBox(
        width: diameter,
        height: diameter,
        child: CustomPaint(
          painter: _WaxSealPainter(color: tint, highlight: c.surface),
          child: Center(
            child: Text(
              glyph,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                color: c.surface,
                fontSize: diameter * 0.32,
                height: 1,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _WaxSealPainter extends CustomPainter {
  const _WaxSealPainter({required this.color, required this.highlight});

  final Color color;
  final Color highlight;

  @override
  void paint(Canvas canvas, Size size) {
    final centre = Offset(size.width / 2, size.height / 2);
    final radius = size.shortestSide / 2;

    // Offset shadow first — wax sits *on* the paper, it does not float.
    canvas.drawCircle(
      centre.translate(2, 2),
      radius,
      Paint()..color = color.withValues(alpha: 0.28),
    );
    canvas.drawCircle(centre, radius, Paint()..color = color);
    canvas.drawCircle(
      centre,
      radius - 2,
      Paint()
        ..color = highlight.withValues(alpha: 0.28)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.4,
    );
    canvas.drawCircle(
      centre.translate(-radius * 0.25, -radius * 0.25),
      radius * 0.34,
      Paint()..color = highlight.withValues(alpha: 0.18),
    );
  }

  @override
  bool shouldRepaint(covariant _WaxSealPainter old) =>
      old.color != color || old.highlight != highlight;
}

/// A postage stamp — perforated edge, gold rule, a plane in a sun disc.
class PostageStamp extends StatelessWidget {
  const PostageStamp({
    required this.label,
    this.denomination = 'ALG · FR',
    this.width = 76,
    super.key,
  });

  final String label;
  final String denomination;
  final double width;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return ExcludeSemantics(
      child: Transform.rotate(
        angle: 0.07,
        child: Container(
          width: width,
          height: width * 1.13,
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(
            color: c.surface,
            boxShadow: context.elevation.card,
          ),
          child: CustomPaint(
            painter: _PerforationPainter(color: c.surface),
            child: Container(
              decoration: BoxDecoration(
                color: c.brandStrong,
                border: Border.all(color: c.seal, width: 1.4),
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    label.toUpperCase(),
                    style: AppTypography.monoLabel(
                      context,
                      color: c.sealSoft,
                      size: 9,
                      tracking: 1.6,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Container(
                    width: width * 0.37,
                    height: width * 0.37,
                    decoration: BoxDecoration(
                      color: c.accent,
                      shape: BoxShape.circle,
                      border: Border.all(color: c.seal, width: 1.4),
                    ),
                    child: Center(
                      child: Icon(
                        Icons.airplanemode_active,
                        size: width * 0.18,
                        color: c.onAccent,
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    denomination,
                    style: AppTypography.monoLabel(
                      context,
                      color: c.sealSoft,
                      size: 8,
                      tracking: 1.2,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _PerforationPainter extends CustomPainter {
  const _PerforationPainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    // Notches are punched by drawing the *paper* colour over the edge; the
    // stamp body painted above fills everything the notches leave behind.
    final paint = Paint()..color = color;
    const step = 8.0;
    for (var x = 0.0; x <= size.width; x += step) {
      canvas.drawCircle(Offset(x, 0), 2.6, paint);
      canvas.drawCircle(Offset(x, size.height), 2.6, paint);
    }
    for (var y = 0.0; y <= size.height; y += step) {
      canvas.drawCircle(Offset(0, y), 2.6, paint);
      canvas.drawCircle(Offset(size.width, y), 2.6, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _PerforationPainter old) => old.color != color;
}

// ---------------------------------------------------------------------------
// Boarding pass
// ---------------------------------------------------------------------------

/// A card clipped to a boarding-pass silhouette: rounded, with a semicircular
/// notch bitten out of each side where the stub would tear off.
///
/// Reach for it when a card *is* one journey or one delivery. A list of
/// settings rows is not a boarding pass and should stay an `AppCard`.
class BoardingCard extends StatelessWidget {
  const BoardingCard({
    required this.child,
    this.onTap,
    this.color,
    this.notchAt = 0.62,
    this.padding = const EdgeInsetsDirectional.all(AppSpace.xl),
    this.semanticLabel,
    this.accent,
    super.key,
  });

  final Widget child;
  final VoidCallback? onTap;
  final Color? color;

  /// Where the notch sits, as a fraction of the card's height.
  final double notchAt;

  final EdgeInsetsGeometry padding;
  final String? semanticLabel;

  /// A coloured strip down the leading edge, for a card whose deal is waiting
  /// on this user. Null means nothing is owed — the strip is a claim about
  /// server state and must never be decorative.
  final Color? accent;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final clipper = _BoardingPassClipper(notch: notchAt);

    Widget card = DecoratedBox(
      // The shadow has to be cast by the *clipped* silhouette, so it is drawn
      // by a shape-matched decoration underneath rather than by a BoxDecoration
      // on the content, which would square off the notches.
      decoration: ShapeDecoration(
        color: color ?? c.surface,
        shape: _BoardingPassBorder(notch: notchAt),
        shadows: context.elevation.card,
      ),
      child: ClipPath(
        clipper: clipper,
        child: Stack(
          children: [
            if (accent != null)
              PositionedDirectional(
                start: 0,
                top: 0,
                bottom: 0,
                width: 4,
                child: ColoredBox(color: accent!),
              ),
            Padding(
              padding: accent == null
                  ? padding
                  : padding.add(
                      const EdgeInsetsDirectional.only(start: AppSpace.sm),
                    ),
              child: child,
            ),
          ],
        ),
      ),
    );

    if (onTap != null) {
      card = Stack(
        children: [
          card,
          Positioned.fill(
            child: ClipPath(
              clipper: clipper,
              child: Material(
                color: Colors.transparent,
                child: InkWell(onTap: onTap, child: const SizedBox.expand()),
              ),
            ),
          ),
        ],
      );
    }

    if (semanticLabel != null) {
      card = Semantics(
        label: semanticLabel,
        button: onTap != null,
        container: true,
        child: card,
      );
    }
    return card;
  }
}

Path _boardingPassPath(Size size, double notch) {
  const r = AppRadius.lg;
  const notchR = 10.0;
  final ny = size.height * notch;
  return Path()
    ..moveTo(r, 0)
    ..lineTo(size.width - r, 0)
    ..quadraticBezierTo(size.width, 0, size.width, r)
    ..lineTo(size.width, ny - notchR)
    ..arcToPoint(
      Offset(size.width, ny + notchR),
      radius: const Radius.circular(notchR),
      clockwise: false,
    )
    ..lineTo(size.width, size.height - r)
    ..quadraticBezierTo(size.width, size.height, size.width - r, size.height)
    ..lineTo(r, size.height)
    ..quadraticBezierTo(0, size.height, 0, size.height - r)
    ..lineTo(0, ny + notchR)
    ..arcToPoint(
      Offset(0, ny - notchR),
      radius: const Radius.circular(notchR),
      clockwise: false,
    )
    ..lineTo(0, r)
    ..quadraticBezierTo(0, 0, r, 0)
    ..close();
}

class _BoardingPassClipper extends CustomClipper<Path> {
  const _BoardingPassClipper({required this.notch});

  final double notch;

  @override
  Path getClip(Size size) => _boardingPassPath(size, notch);

  @override
  bool shouldReclip(covariant _BoardingPassClipper old) => old.notch != notch;
}

class _BoardingPassBorder extends ShapeBorder {
  const _BoardingPassBorder({required this.notch});

  final double notch;

  @override
  EdgeInsetsGeometry get dimensions => EdgeInsets.zero;

  @override
  Path getInnerPath(Rect rect, {TextDirection? textDirection}) =>
      getOuterPath(rect, textDirection: textDirection);

  @override
  Path getOuterPath(Rect rect, {TextDirection? textDirection}) =>
      _boardingPassPath(rect.size, notch).shift(rect.topLeft);

  @override
  void paint(Canvas canvas, Rect rect, {TextDirection? textDirection}) {}

  @override
  ShapeBorder scale(double t) => _BoardingPassBorder(notch: notch);

  @override
  bool operator ==(Object other) =>
      other is _BoardingPassBorder && other.notch == notch;

  @override
  int get hashCode => notch.hashCode;
}

// ---------------------------------------------------------------------------
// Corridor marks
// ---------------------------------------------------------------------------

/// A country flag with its code beside it — the DZ ↔ FR corridor made
/// concrete. Numerals and codes stay LTR inside an Arabic layout.
class CountryPill extends StatelessWidget {
  const CountryPill({
    required this.code,
    this.label,
    this.dense = false,
    super.key,
  });

  /// ISO 3166-1 alpha-2, e.g. `DZ`.
  final String code;

  /// Defaults to [code]. Pass a name when the pill stands alone.
  final String? label;

  final bool dense;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = (label ?? code).toUpperCase();
    return Semantics(
      label: text,
      excludeSemantics: true,
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: dense ? 10 : 14,
          vertical: dense ? 6 : 9,
        ),
        decoration: BoxDecoration(
          color: c.surface,
          borderRadius: AppRadius.rPill,
          border: Border.all(color: c.hairline),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(2),
              child: SizedBox(
                height: dense ? 12 : 14,
                width: dense ? 18 : 22,
                child: CountryFlag.fromCountryCode(code),
              ),
            ),
            SizedBox(width: dense ? 6 : 8),
            Text(
              text,
              style: AppTypography.monoLabel(
                context,
                color: c.textPrimary,
                size: dense ? 11 : 12.5,
                tracking: 0.8,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The wordmark: a tilted plane in an ink tile, then "ShipTrip" in the
/// display serif.
class ShipTripMark extends StatelessWidget {
  const ShipTripMark({this.size = 30, this.showWordmark = true, super.key});

  final double size;
  final bool showWordmark;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Semantics(
      label: 'ShipTrip',
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
              color: c.surfaceInverse,
              borderRadius: BorderRadius.circular(size * 0.27),
            ),
            child: Center(
              child: Transform.rotate(
                angle: -0.78,
                child: Icon(
                  Icons.airplanemode_active,
                  size: size * 0.53,
                  color: c.textOnInverse,
                ),
              ),
            ),
          ),
          if (showWordmark) ...[
            SizedBox(width: size * 0.33),
            Text(
              'ShipTrip',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                fontSize: size * 0.67,
                color: c.textPrimary,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// The circular back affordance the original ShipTrip auth screens used
/// instead of an app bar: a disc of lighter paper on the parchment, with a
/// hairline so it has an edge.
///
/// Uses `maybePop`, which is the same resolution the top bar and the platform
/// gestures use — so a screen reached by a deep link cannot be backed out of
/// the app entirely.
class PaperBackButton extends StatelessWidget {
  const PaperBackButton({this.onPressed, super.key});

  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Semantics(
      button: true,
      label: MaterialLocalizations.of(context).backButtonTooltip,
      excludeSemantics: true,
      child: Material(
        color: c.surfaceRaised,
        shape: CircleBorder(side: BorderSide(color: c.hairline)),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onPressed ?? () => Navigator.of(context).maybePop(),
          child: SizedBox(
            width: AppSpace.minTapTarget,
            height: AppSpace.minTapTarget,
            child: Icon(
              // Directional: "back" is the other way round in Arabic.
              Icons.arrow_back_rounded,
              size: 20,
              color: c.textPrimary,
              textDirection: Directionality.of(context),
            ),
          ),
        ),
      ),
    );
  }
}

/// The page indicator from the onboarding carousel: the active dot stretches
/// into a sun-coloured lozenge with a glow under it.
class PassportDots extends StatelessWidget {
  const PassportDots({required this.count, required this.active, super.key});

  final int count;
  final int active;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return ExcludeSemantics(
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < count; i++)
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 8),
              child: AnimatedContainer(
                duration: AppMotion.respecting(context, AppMotion.normal),
                curve: AppMotion.enter,
                width: i == active ? 28 : 8,
                height: 8,
                decoration: BoxDecoration(
                  color: i == active ? c.accent : c.surfaceSunken,
                  borderRadius: AppRadius.rPill,
                  border: i == active
                      ? Border.all(color: c.hairlineStrong)
                      : null,
                  boxShadow: i == active
                      ? [
                          BoxShadow(
                            color: c.accent.withValues(alpha: 0.45),
                            blurRadius: 12,
                            offset: const Offset(0, 4),
                          ),
                        ]
                      : null,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

/// The animated flight path: a dashed arc between two city dots with a small
/// plane travelling along it, trailing a warm halo.
///
/// This is the single most recognisable thing in the app, so it earns a
/// three-second loop. With reduced motion on, the plane parks at the top of
/// the arc — a complete, composed frame rather than an empty route.
class RouteTrace extends StatefulWidget {
  const RouteTrace({this.height = 170, super.key});

  final double height;

  @override
  State<RouteTrace> createState() => _RouteTraceState();
}

class _RouteTraceState extends State<RouteTrace>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3200),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Read here rather than in initState: MediaQuery is not available yet at
    // initState time, and the setting can change while the screen is open.
    if (MediaQuery.disableAnimationsOf(context)) {
      _controller.stop();
      _controller.value = 0.5;
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return ExcludeSemantics(
      child: RepaintBoundary(
        child: SizedBox(
          height: widget.height,
          width: double.infinity,
          child: AnimatedBuilder(
            animation: _controller,
            builder: (context, _) => CustomPaint(
              painter: _RoutePainter(
                t: _controller.value,
                ink: c.textPrimary,
                halo: c.attentionVivid,
                accent: c.brand,
                // Mirrored in Arabic so the plane still flies in the
                // direction the page reads.
                mirrored: Directionality.of(context) == TextDirection.rtl,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _RoutePainter extends CustomPainter {
  const _RoutePainter({
    required this.t,
    required this.ink,
    required this.halo,
    required this.accent,
    required this.mirrored,
  });

  final double t;
  final Color ink;
  final Color halo;
  final Color accent;
  final bool mirrored;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    if (mirrored) {
      canvas.translate(size.width, 0);
      canvas.scale(-1, 1);
    }

    final start = Offset(20, size.height * 0.78);
    final end = Offset(size.width - 20, size.height * 0.32);
    final path = Path()
      ..moveTo(start.dx, start.dy)
      ..cubicTo(
        size.width * 0.30,
        size.height * 0.05,
        size.width * 0.70,
        size.height * 0.85,
        end.dx,
        end.dy,
      );

    final dashPaint = Paint()
      ..color = ink.withValues(alpha: 0.25)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    for (final metric in path.computeMetrics()) {
      var distance = 0.0;
      while (distance < metric.length) {
        final next = math.min(distance + 6, metric.length);
        canvas.drawPath(metric.extractPath(distance, next), dashPaint);
        distance = next + 4;
      }
    }

    for (final metric in path.computeMetrics()) {
      final tangent = metric.getTangentForOffset(metric.length * t);
      if (tangent == null) continue;
      final p = tangent.position;
      canvas
        ..drawCircle(p, 14, Paint()..color = halo.withValues(alpha: 0.18))
        ..drawCircle(p, 8, Paint()..color = halo.withValues(alpha: 0.35))
        ..save()
        ..translate(p.dx, p.dy)
        ..rotate(tangent.angle)
        ..drawPath(
          Path()
            ..moveTo(8, 0)
            ..lineTo(-6, -4)
            ..lineTo(-3, 0)
            ..lineTo(-6, 4)
            ..close(),
          Paint()..color = ink,
        )
        ..restore();
    }

    final dot = Paint()..color = ink;
    final soft = Paint()..color = ink.withValues(alpha: 0.08);
    for (final city in [start, end]) {
      canvas
        ..drawCircle(city, 5, dot)
        ..drawCircle(city, 12, soft);
    }

    final underline = Paint()
      ..color = accent
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    for (final city in [start, end]) {
      canvas.drawLine(
        city + const Offset(-12, 18),
        city + const Offset(12, 18),
        underline,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _RoutePainter old) =>
      old.t != t || old.ink != ink || old.mirrored != mirrored;
}
