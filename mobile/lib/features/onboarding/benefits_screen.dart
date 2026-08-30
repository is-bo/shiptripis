/// The three chapters between the front page and sign-up.
///
/// Restored from the original ShipTrip onboarding: a bilingual poster in
/// three panels, each with a hand-painted hero on an airmail-bordered card
/// with a postage stamp tacked to its corner. Chapter I is the post, II is
/// the suitcase, III is the seal — send, earn, trust.
///
/// It is skippable from the first frame, and skipping is not a lesser path:
/// the story is charm, not instruction, and nothing downstream assumes the
/// user read it.
///
/// Every illustration is a [CustomPainter]. There is no image asset in this
/// app, which is why the heroes tint correctly in dark mode and cost nothing
/// to download. Each one animates once when its page becomes active and
/// renders a finished static frame when the platform asks for reduced motion.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../app/router.dart';
import '../../design/identity.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../l10n/app_localizations.dart';

enum _Hero { post, suitcase, seal }

class _Chapter {
  const _Chapter({
    required this.eyebrow,
    required this.title,
    required this.accent,
    required this.body,
    required this.stamp,
    required this.hero,
  });

  final String eyebrow;
  final String title;
  final String accent;
  final String body;
  final String stamp;
  final _Hero hero;
}

class BenefitsScreen extends StatefulWidget {
  const BenefitsScreen({super.key});

  @override
  State<BenefitsScreen> createState() => _BenefitsScreenState();
}

class _BenefitsScreenState extends State<BenefitsScreen> {
  final _controller = PageController();
  int _index = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _finish() => context.pushReplacementNamed(Routes.signUp);

  void _advance(int count) {
    if (_index >= count - 1) {
      _finish();
      return;
    }
    _controller.nextPage(
      duration: AppMotion.respecting(context, AppMotion.normal),
      curve: AppMotion.enter,
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final size = MediaQuery.sizeOf(context);
    final isShort = size.height < 720;

    final chapters = <_Chapter>[
      _Chapter(
        eyebrow: l.benefitsChapterOneEyebrow,
        title: l.benefitsChapterOneTitle,
        accent: l.benefitsChapterOneAccent,
        body: l.benefitsChapterOneBody,
        stamp: l.benefitsChapterOneStamp,
        hero: _Hero.post,
      ),
      _Chapter(
        eyebrow: l.benefitsChapterTwoEyebrow,
        title: l.benefitsChapterTwoTitle,
        accent: l.benefitsChapterTwoAccent,
        body: l.benefitsChapterTwoBody,
        stamp: l.benefitsChapterTwoStamp,
        hero: _Hero.suitcase,
      ),
      _Chapter(
        eyebrow: l.benefitsChapterThreeEyebrow,
        title: l.benefitsChapterThreeTitle,
        accent: l.benefitsChapterThreeAccent,
        body: l.benefitsChapterThreeBody,
        stamp: l.benefitsChapterThreeStamp,
        hero: _Hero.seal,
      ),
    ];

    final isLast = _index == chapters.length - 1;

    return AppScaffold(
      // The tint wash is this screen's own background; the scaffold's grain
      // still sits underneath it.
      body: Stack(
        children: [
          // A barely-there colour wash that shifts per chapter — warm for the
          // suitcase, emerald for the seal. It is the reason the three pages
          // feel like three places rather than one template.
          Positioned.fill(
            child: AnimatedContainer(
              duration: AppMotion.respecting(context, AppMotion.slow),
              color: switch (_index) {
                0 => const Color(0x00000000),
                1 => c.attentionVivid.withValues(alpha: 0.06),
                _ => c.brand.withValues(alpha: 0.04),
              },
            ),
          ),
          Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpace.xxl,
                  AppSpace.lg,
                  AppSpace.xxl,
                  0,
                ),
                child: Row(
                  children: [
                    Text(
                      l.benefitsIndex(_index + 1, chapters.length),
                      style: AppTypography.monoLabel(
                        context,
                        color: c.textTertiary,
                        tracking: 2,
                      ),
                    ),
                    const Spacer(),
                    // Hidden on the last page, where "Get started" is the
                    // same action and a skip beside it is just noise.
                    AnimatedOpacity(
                      opacity: isLast ? 0 : 1,
                      duration: AppMotion.respecting(context, AppMotion.fast),
                      child: IgnorePointer(
                        ignoring: isLast,
                        child: TextButton(
                          onPressed: _finish,
                          child: Text(l.benefitsSkip),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: Semantics(
                  label: l.onboardingPageOf(_index + 1, chapters.length),
                  child: PageView.builder(
                    controller: _controller,
                    itemCount: chapters.length,
                    onPageChanged: (i) => setState(() => _index = i),
                    itemBuilder: (context, i) => _ChapterPage(
                      key: ValueKey('chapter-$i'),
                      chapter: chapters[i],
                      isActive: i == _index,
                      titleSize: isShort ? 34 : 42,
                      heroHeight: (size.height * 0.32).clamp(200.0, 300.0),
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpace.xxl,
                  0,
                  AppSpace.xxl,
                  AppSpace.xxl,
                ),
                child: Row(
                  children: [
                    PassportDots(count: chapters.length, active: _index),
                    const Spacer(),
                    _AdvanceButton(
                      isLast: isLast,
                      label: l.onboardingGetStarted,
                      onPressed: () => _advance(chapters.length),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// One chapter
// ---------------------------------------------------------------------------

class _ChapterPage extends StatelessWidget {
  const _ChapterPage({
    required this.chapter,
    required this.isActive,
    required this.titleSize,
    required this.heroHeight,
    super.key,
  });

  final _Chapter chapter;
  final bool isActive;
  final double titleSize;
  final double heroHeight;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: AppSpace.xxl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: AppSpace.xxl),
          RepaintBoundary(
            child: SizedBox(
              height: heroHeight,
              child: _HeroCard(chapter: chapter, isActive: isActive),
            ),
          ),
          const SizedBox(height: AppSpace.x3l),
          Text(
            chapter.eyebrow.toUpperCase(),
            style: AppTypography.eyebrow(context, color: c.textTertiary),
          ),
          const SizedBox(height: AppSpace.md),
          Text(
            chapter.title,
            style: text.displayLarge?.copyWith(
              fontSize: titleSize,
              height: 1.02,
            ),
          ),
          const SizedBox(height: AppSpace.md),
          // The second voice: the same idea, said shorter, in italic serif
          // and terracotta. It is what stops the panel reading as a slide in
          // a deck.
          Text(
            chapter.accent,
            style: text.headlineSmall?.copyWith(
              fontSize: 18,
              height: 1.25,
              color: c.attention,
              fontStyle: FontStyle.italic,
            ),
          ),
          const SizedBox(height: AppSpace.lg),
          Text(
            chapter.body,
            style: text.bodyMedium?.copyWith(
              color: c.textSecondary,
              height: 1.55,
            ),
          ),
          const SizedBox(height: AppSpace.xxl),
        ],
      ),
    );
  }
}

/// The hero: an airmail-bordered card, tilted a degree off true, with a
/// postage stamp tacked over its top corner.
class _HeroCard extends StatelessWidget {
  const _HeroCard({required this.chapter, required this.isActive});

  final _Chapter chapter;
  final bool isActive;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned.fill(
          child: Transform.rotate(
            angle: -0.012,
            child: Container(
              decoration: BoxDecoration(
                color: c.surface,
                borderRadius: AppRadius.rLg,
                boxShadow: context.elevation.card,
                border: Border.all(color: c.hairline),
              ),
              child: ClipRRect(
                borderRadius: AppRadius.rLg,
                child: CustomPaint(
                  painter: _AirmailBorderPainter(
                    warm: c.attentionVivid,
                    cool: c.brand,
                    paper: c.surface,
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(AppSpace.lg),
                    child: switch (chapter.hero) {
                      _Hero.post => _PostHero(active: isActive),
                      _Hero.suitcase => _SuitcaseHero(active: isActive),
                      _Hero.seal => _SealHero(active: isActive),
                    },
                  ),
                ),
              ),
            ),
          ),
        ),
        PositionedDirectional(
          top: -10,
          end: 12,
          child: PostageStamp(label: chapter.stamp),
        ),
      ],
    );
  }
}

class _AirmailBorderPainter extends CustomPainter {
  const _AirmailBorderPainter({
    required this.warm,
    required this.cool,
    required this.paper,
  });

  final Color warm;
  final Color cool;
  final Color paper;

  @override
  void paint(Canvas canvas, Size size) {
    // The par-avion barber pole: warm, paper, cool, paper, repeating around
    // the inner edge.
    const inset = 8.0;
    final inner = Rect.fromLTRB(
      inset,
      inset,
      size.width - inset,
      size.height - inset,
    );
    if (inner.isEmpty) return;

    final stripe = Paint()
      ..strokeWidth = 6
      ..style = PaintingStyle.stroke;
    final colors = [warm, paper, cool, paper];
    final path = Path()
      ..moveTo(inner.left, inner.top)
      ..lineTo(inner.right, inner.top)
      ..lineTo(inner.right, inner.bottom)
      ..lineTo(inner.left, inner.bottom)
      ..close();

    for (final metric in path.computeMetrics()) {
      var distance = 0.0;
      var i = 0;
      while (distance < metric.length) {
        final next = math.min(distance + 8, metric.length);
        stripe.color = colors[i % colors.length];
        canvas.drawPath(metric.extractPath(distance, next), stripe);
        distance = next;
        i++;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _AirmailBorderPainter old) =>
      old.warm != warm || old.cool != cool || old.paper != paper;
}

// ---------------------------------------------------------------------------
// Chapter I — the post
// ---------------------------------------------------------------------------

/// A postcard: an addressee block, a parcel flying an arc across it, and a
/// wax seal in the corner.
class _PostHero extends StatefulWidget {
  const _PostHero({required this.active});

  final bool active;

  @override
  State<_PostHero> createState() => _PostHeroState();
}

class _PostHeroState extends State<_PostHero>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3600),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync();
  }

  @override
  void didUpdateWidget(covariant _PostHero old) {
    super.didUpdateWidget(old);
    _sync();
  }

  void _sync() {
    if (MediaQuery.disableAnimationsOf(context)) {
      _controller.stop();
      // Parked mid-flight, which is the frame that reads best as a still.
      _controller.value = 0.55;
      return;
    }
    if (widget.active && !_controller.isAnimating) {
      _controller.repeat();
    } else if (!widget.active && _controller.isAnimating) {
      _controller.stop();
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
    return Stack(
      children: [
        PositionedDirectional(
          // Below the postage stamp, not behind it. On a real postcard the
          // stamp takes the corner and the address block starts under it;
          // overlapping them just looks like a z-order mistake.
          top: 82,
          end: 8,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                'TO',
                style: AppTypography.monoLabel(
                  context,
                  color: c.textTertiary,
                  size: 9,
                  tracking: 1.4,
                ),
              ),
              const SizedBox(height: 4),
              for (final width in [86.0, 64.0, 72.0]) ...[
                Container(width: width, height: 1.4, color: c.hairline),
                const SizedBox(height: 6),
              ],
            ],
          ),
        ),
        AnimatedBuilder(
          animation: _controller,
          builder: (context, _) => CustomPaint(
            size: Size.infinite,
            painter: _ParcelFlightPainter(
              t: _controller.value,
              ink: c.textPrimary,
              paper: c.surface,
              trail: c.attentionVivid,
              parcel: c.seal,
              tag: c.accent,
            ),
          ),
        ),
        PositionedDirectional(
          bottom: 12,
          start: 12,
          child: WaxSeal(glyph: 'S', diameter: 38, color: c.attentionVivid),
        ),
      ],
    );
  }
}

class _ParcelFlightPainter extends CustomPainter {
  const _ParcelFlightPainter({
    required this.t,
    required this.ink,
    required this.paper,
    required this.trail,
    required this.parcel,
    required this.tag,
  });

  final double t;
  final Color ink;
  final Color paper;
  final Color trail;
  final Color parcel;
  final Color tag;

  Offset _at(Offset p0, Offset p1, Offset p2, double t) {
    final u = 1 - t;
    return Offset(
      u * u * p0.dx + 2 * u * t * p1.dx + t * t * p2.dx,
      u * u * p0.dy + 2 * u * t * p1.dy + t * t * p2.dy,
    );
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final start = Offset(size.width * 0.12, size.height * 0.78);
    final end = Offset(size.width * 0.88, size.height * 0.34);
    final control = Offset(size.width * 0.5, size.height * 0.05);

    final route = Path()
      ..moveTo(start.dx, start.dy)
      ..quadraticBezierTo(control.dx, control.dy, end.dx, end.dy);

    final dash = Paint()
      ..color = ink.withValues(alpha: 0.18)
      ..strokeWidth = 1.6
      ..style = PaintingStyle.stroke;
    for (final metric in route.computeMetrics()) {
      var distance = 0.0;
      while (distance < metric.length) {
        final next = math.min(distance + 5, metric.length);
        canvas.drawPath(metric.extractPath(distance, next), dash);
        distance = next + 4;
      }
    }

    final marker = Paint()
      ..color = ink
      ..strokeWidth = 1.6
      ..style = PaintingStyle.stroke;
    for (final point in [start, end]) {
      canvas
        ..drawCircle(point, 5, Paint()..color = paper)
        ..drawCircle(point, 5, marker);
    }

    // A short comet tail of recent positions — cheaper than motion blur and
    // it reads better at this size.
    for (var i = 1; i <= 6; i++) {
      final tt = t - i * 0.02;
      if (tt < 0) continue;
      canvas.drawCircle(
        _at(start, control, end, tt),
        2.4 - i * 0.2,
        Paint()..color = trail.withValues(alpha: (0.5 - i * 0.07).clamp(0, 1)),
      );
    }

    final position = _at(start, control, end, t);
    final tangent = Offset(
      2 * (1 - t) * (control.dx - start.dx) + 2 * t * (end.dx - control.dx),
      2 * (1 - t) * (control.dy - start.dy) + 2 * t * (end.dy - control.dy),
    );

    canvas
      ..save()
      ..translate(position.dx, position.dy)
      ..rotate(math.atan2(tangent.dy, tangent.dx));

    const w = 22.0;
    const h = 16.0;
    final body = RRect.fromRectAndRadius(
      Rect.fromCenter(center: Offset.zero, width: w, height: h),
      const Radius.circular(3),
    );
    final outline = Paint()
      ..color = ink
      ..strokeWidth = 1.4
      ..style = PaintingStyle.stroke;
    canvas
      ..drawRRect(body, Paint()..color = parcel)
      ..drawRRect(body, outline)
      ..drawLine(
        const Offset(0, -h / 2),
        const Offset(0, h / 2),
        Paint()
          ..color = ink
          ..strokeWidth = 1.4,
      )
      ..drawLine(
        const Offset(-w / 2, 0),
        const Offset(w / 2, 0),
        Paint()
          ..color = ink
          ..strokeWidth = 1.4,
      )
      ..drawCircle(
        const Offset(-w / 2 + 3, -h / 2 + 3),
        2.8,
        Paint()..color = tag,
      )
      ..restore();
  }

  @override
  bool shouldRepaint(covariant _ParcelFlightPainter old) =>
      old.t != t || old.ink != ink;
}

// ---------------------------------------------------------------------------
// Chapter II — the suitcase
// ---------------------------------------------------------------------------

/// A boarding pass with a torn-off stub, and coins dropping beside it.
class _SuitcaseHero extends StatelessWidget {
  const _SuitcaseHero({required this.active});

  final bool active;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final l = L.of(context);

    return LayoutBuilder(
      builder: (context, constraints) => Stack(
        children: [
          CustomPaint(
            size: Size(constraints.maxWidth, constraints.maxHeight),
            painter: _BoardingPassPainter(
              ink: c.textPrimary,
              mute: c.hairline,
              muteStrong: c.hairlineStrong,
              band: c.brand,
              onBand: c.onBrand,
              accent: c.accent,
              cancel: c.attention,
              stub: c.attentionSoft,
              // TextPainter cannot reach a BuildContext, so the two labels the
              // pass carries are resolved here and handed down already styled.
              fromLabel: _painted(
                context,
                'FROM',
                AppTypography.monoLabel(
                  context,
                  color: c.textTertiary,
                  size: 9,
                  tracking: 1.4,
                ),
              ),
              fromValue: _painted(
                context,
                'ALG',
                Theme.of(
                  context,
                ).textTheme.headlineMedium!.copyWith(fontSize: 22, height: 1),
              ),
              toLabel: _painted(
                context,
                'TO',
                AppTypography.monoLabel(
                  context,
                  color: c.textTertiary,
                  size: 9,
                  tracking: 1.4,
                ),
              ),
              toValue: _painted(
                context,
                'CDG',
                Theme.of(
                  context,
                ).textTheme.headlineMedium!.copyWith(fontSize: 22, height: 1),
              ),
              stubText: _painted(
                context,
                l.benefitsKilosFree,
                AppTypography.monoLabel(
                  context,
                  color: c.onAttentionSoft,
                  size: 11,
                  tracking: 1.4,
                ).copyWith(height: 1.1),
                align: TextAlign.center,
              ),
              currencyStamp: _painted(
                context,
                'EUR',
                AppTypography.monoLabel(
                  context,
                  color: c.attention,
                  size: 11,
                  tracking: 2,
                  weight: 700,
                ),
              ),
            ),
          ),
          PositionedDirectional(
            end: 24,
            bottom: 18,
            child: _CoinStack(active: active),
          ),
        ],
      ),
    );
  }
}

/// Lays a string out once so a painter can stamp it without a context.
TextPainter _painted(
  BuildContext context,
  String text,
  TextStyle style, {
  TextAlign align = TextAlign.start,
}) => TextPainter(
  text: TextSpan(text: text, style: style),
  textAlign: align,
  // Always LTR: these are IATA codes and unit labels printed on a ticket,
  // not sentences, and they read the same way in every locale.
  textDirection: TextDirection.ltr,
)..layout();

class _BoardingPassPainter extends CustomPainter {
  const _BoardingPassPainter({
    required this.ink,
    required this.mute,
    required this.muteStrong,
    required this.band,
    required this.onBand,
    required this.accent,
    required this.cancel,
    required this.stub,
    required this.fromLabel,
    required this.fromValue,
    required this.toLabel,
    required this.toValue,
    required this.stubText,
    required this.currencyStamp,
  });

  final Color ink;
  final Color mute;
  final Color muteStrong;
  final Color band;
  final Color onBand;
  final Color accent;
  final Color cancel;
  final Color stub;
  final TextPainter fromLabel;
  final TextPainter fromValue;
  final TextPainter toLabel;
  final TextPainter toValue;
  final TextPainter stubText;
  final TextPainter currencyStamp;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width < 120 || size.height < 120) return;

    final inkStroke = Paint()
      ..color = ink
      ..strokeWidth = 1.4
      ..style = PaintingStyle.stroke;
    final muteStroke = Paint()
      ..color = mute
      ..strokeWidth = 1
      ..style = PaintingStyle.stroke;

    final r = Rect.fromLTWH(8, 8, size.width - 16, size.height - 16);

    // Airline band along the top, with a sun dot where the logo would be.
    final header = Rect.fromLTWH(r.left, r.top, r.width, 28);
    canvas.drawRect(header, Paint()..color = band);
    for (var i = 0; i < 8; i++) {
      final x = r.left + 14 + i * 12.0;
      if (x + 6 > r.right - 26) break;
      canvas.drawLine(
        Offset(x, header.top + 14),
        Offset(x + 6, header.top + 14),
        Paint()
          ..color = onBand
          ..strokeWidth = 1.4,
      );
    }
    canvas.drawCircle(
      Offset(r.right - 16, header.center.dy),
      4.5,
      Paint()..color = accent,
    );

    // The perforation the stub tears along.
    final perfX = r.left + r.width * 0.65;
    final perf = Paint()..color = muteStrong;
    for (var y = r.top + 36; y < r.bottom - 6; y += 6) {
      canvas.drawCircle(Offset(perfX, y), 1.2, perf);
    }

    final leftPad = r.left + 14;
    fromLabel.paint(canvas, Offset(leftPad, r.top + 50));
    fromValue.paint(canvas, Offset(leftPad, r.top + 62));
    toLabel.paint(canvas, Offset(perfX - 50, r.top + 50));
    toValue.paint(canvas, Offset(perfX - 50, r.top + 62));

    // The leg arrow between them.
    final from = Offset(leftPad + 54, r.top + 76);
    final to = Offset(perfX - 58, r.top + 76);
    if (to.dx > from.dx) {
      canvas.drawLine(from, to, inkStroke);
      for (final sign in [-1, 1]) {
        canvas.drawLine(to, to + Offset(-6, 5.0 * sign), inkStroke);
      }
    }

    // Passenger / class / seat, as unfilled rules.
    for (var i = 0; i < 3; i++) {
      final y = r.top + 100 + i * 22;
      final width = perfX - leftPad - 20 - i * 40;
      if (y > r.bottom - 24 || width <= 0) break;
      canvas.drawLine(
        Offset(leftPad, y),
        Offset(leftPad + width, y),
        muteStroke,
      );
    }

    // The stub, cancelled with diagonal strokes.
    final stubRect = Rect.fromLTWH(
      perfX + 12,
      r.top + 38,
      r.right - perfX - 22,
      r.height - 50,
    );
    if (stubRect.width > 20 && stubRect.height > 20) {
      canvas
        ..drawRect(stubRect, Paint()..color = stub)
        ..drawRect(stubRect, muteStroke)
        ..save()
        ..clipRect(stubRect);
      final cancelPaint = Paint()
        ..color = cancel.withValues(alpha: 0.5)
        ..strokeWidth = 1.6;
      for (
        var x = stubRect.left - stubRect.height;
        x < stubRect.right;
        x += 6
      ) {
        canvas.drawLine(
          Offset(x, stubRect.top),
          Offset(x + stubRect.height, stubRect.bottom),
          cancelPaint,
        );
      }
      canvas.restore();
      stubText.paint(
        canvas,
        Offset(
          stubRect.center.dx - stubText.width / 2,
          stubRect.center.dy - stubText.height / 2,
        ),
      );
    }

    // The currency stamp, pressed on crooked.
    canvas
      ..save()
      ..translate(leftPad + 62, r.bottom - 28)
      ..rotate(-0.18);
    final stampBox = Rect.fromCenter(
      center: Offset.zero,
      width: 60,
      height: 26,
    );
    final stampStroke = Paint()
      ..color = cancel
      ..strokeWidth = 1.6
      ..style = PaintingStyle.stroke;
    canvas
      ..drawRect(stampBox, stampStroke)
      ..drawRect(stampBox.deflate(3), stampStroke..strokeWidth = 0.8);
    currencyStamp.paint(
      canvas,
      Offset(-currencyStamp.width / 2, -currencyStamp.height / 2),
    );
    canvas.restore();

    canvas.drawRRect(
      RRect.fromRectAndRadius(r, const Radius.circular(8)),
      Paint()
        ..color = mute
        ..strokeWidth = 1
        ..style = PaintingStyle.stroke,
    );
  }

  @override
  bool shouldRepaint(covariant _BoardingPassPainter old) => old.ink != ink;
}

/// Coins landing one after another — the earning, made literal.
class _CoinStack extends StatefulWidget {
  const _CoinStack({required this.active});

  final bool active;

  @override
  State<_CoinStack> createState() => _CoinStackState();
}

class _CoinStackState extends State<_CoinStack>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1400),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync();
  }

  @override
  void didUpdateWidget(covariant _CoinStack old) {
    super.didUpdateWidget(old);
    _sync();
  }

  void _sync() {
    if (MediaQuery.disableAnimationsOf(context)) {
      _controller.value = 1;
      return;
    }
    if (widget.active && _controller.value == 0) {
      _controller.forward(from: 0);
    } else if (!widget.active) {
      _controller.value = 0;
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
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) => SizedBox(
          width: 56,
          height: 86,
          child: Stack(
            children: [
              for (var i = 0; i < 4; i++)
                Positioned(
                  left: 4 + i * 0.4,
                  bottom:
                      6 +
                      i * 9.0 -
                      (1 -
                              Curves.easeOutBack.transform(
                                ((_controller.value * 1.4) - i * 0.18).clamp(
                                  0.0,
                                  1.0,
                                ),
                              )) *
                          22,
                  child: Opacity(
                    opacity: Curves.easeOutBack
                        .transform(
                          ((_controller.value * 1.4) - i * 0.18).clamp(
                            0.0,
                            1.0,
                          ),
                        )
                        .clamp(0.0, 1.0),
                    child: Container(
                      width: 44,
                      height: 12,
                      decoration: BoxDecoration(
                        color: c.seal,
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(color: c.textPrimary, width: 1.2),
                      ),
                      alignment: Alignment.center,
                      child: i == 3
                          ? Text(
                              'EUR',
                              style: AppTypography.monoLabel(
                                context,
                                color: c.textPrimary,
                                size: 8,
                                weight: 700,
                                tracking: 1.2,
                              ),
                            )
                          : null,
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

// ---------------------------------------------------------------------------
// Chapter III — the seal
// ---------------------------------------------------------------------------

/// A handover code landing tile by tile, under a certification flourish,
/// with a wax seal to close it.
///
/// Six characters, letters and digits — which is what the server actually
/// issues. The old four-digit version of this screen was charming and no
/// longer true.
class _SealHero extends StatefulWidget {
  const _SealHero({required this.active});

  final bool active;

  @override
  State<_SealHero> createState() => _SealHeroState();
}

class _SealHeroState extends State<_SealHero>
    with SingleTickerProviderStateMixin {
  static const _sample = ['K', '7', 'M', '4', '9', 'X'];

  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1800),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync();
  }

  @override
  void didUpdateWidget(covariant _SealHero old) {
    super.didUpdateWidget(old);
    _sync();
  }

  void _sync() {
    if (MediaQuery.disableAnimationsOf(context)) {
      _controller.value = 1;
      return;
    }
    if (widget.active && _controller.value == 0) {
      _controller.forward(from: 0);
    } else if (!widget.active) {
      _controller.value = 0;
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
    final l = L.of(context);

    return Stack(
      children: [
        Positioned.fill(
          child: AnimatedBuilder(
            animation: _controller,
            builder: (context, _) => CustomPaint(
              painter: _FlourishPainter(
                t: _controller.value,
                ring: c.seal,
                tick: c.brand,
              ),
            ),
          ),
        ),
        Center(
          child: Padding(
            padding: const EdgeInsets.only(top: 10),
            child: FittedBox(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                // A code is a machine token; it does not mirror in Arabic.
                textDirection: TextDirection.ltr,
                children: [
                  for (var i = 0; i < _sample.length; i++)
                    Padding(
                      padding: EdgeInsets.symmetric(
                        horizontal: i == 2 ? 8 : 3,
                        vertical: 4,
                      ),
                      child: _CodeTile(
                        glyph: _sample[i],
                        progress: _controller,
                        order: i,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
        PositionedDirectional(
          bottom: 8,
          end: 12,
          child: WaxSeal(glyph: '✓', diameter: 48, color: c.brand),
        ),
        PositionedDirectional(
          top: 8,
          start: 8,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: c.surfaceInverse,
              borderRadius: BorderRadius.circular(2),
            ),
            child: Text(
              l.benefitsHandoverCaption,
              style: AppTypography.monoLabel(
                context,
                color: c.textOnInverse,
                size: 9,
                weight: 700,
                tracking: 1.6,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// One character in a split-flap frame.
class _CodeTile extends StatelessWidget {
  const _CodeTile({
    required this.glyph,
    required this.progress,
    required this.order,
  });

  final String glyph;
  final Animation<double> progress;
  final int order;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return AnimatedBuilder(
      animation: progress,
      builder: (context, _) {
        // Each tile occupies its own slice of the timeline, so they land in
        // sequence the way a departure board flips.
        final t = ((progress.value - 0.12 - order * 0.07) / 0.3).clamp(
          0.0,
          1.0,
        );
        return Container(
          width: 44,
          height: 60,
          decoration: BoxDecoration(
            color: c.canvas,
            border: Border.all(color: c.textPrimary, width: 1.4),
            borderRadius: BorderRadius.circular(4),
            boxShadow: context.elevation.stamped,
          ),
          alignment: Alignment.center,
          child: Stack(
            alignment: Alignment.center,
            children: [
              Positioned(
                left: 0,
                right: 0,
                top: 29,
                child: Container(height: 1, color: c.hairline),
              ),
              Opacity(
                opacity: t,
                child: Transform.translate(
                  offset: Offset(0, -22 * (1 - AppMotion.enter.transform(t))),
                  child: Text(
                    glyph,
                    style: AppTypography.code(color: c.textPrimary, size: 28),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _FlourishPainter extends CustomPainter {
  const _FlourishPainter({
    required this.t,
    required this.ring,
    required this.tick,
  });

  final double t;
  final Color ring;
  final Color tick;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final centre = Offset(size.width / 2, size.height / 2);
    final maxR = size.shortestSide * 0.62;

    for (var i = 0; i < 3; i++) {
      canvas.drawCircle(
        centre,
        maxR * (0.6 + i * 0.18) * (0.6 + 0.4 * t),
        Paint()
          ..color = ring.withValues(alpha: 0.2 - i * 0.05)
          ..strokeWidth = 1
          ..style = PaintingStyle.stroke,
      );
    }

    final tickPaint = Paint()
      ..color = tick.withValues(alpha: 0.35)
      ..strokeWidth = 1;
    for (var i = 0; i < (24 * t).floor(); i++) {
      final angle = (i / 24) * math.pi * 2 - math.pi / 2;
      canvas.drawLine(
        centre + Offset(math.cos(angle), math.sin(angle)) * (maxR * 0.84),
        centre + Offset(math.cos(angle), math.sin(angle)) * (maxR * 0.92),
        tickPaint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _FlourishPainter old) => old.t != t;
}

// ---------------------------------------------------------------------------
// Advance
// ---------------------------------------------------------------------------

/// The sun pill that grows a label on the last chapter.
class _AdvanceButton extends StatelessWidget {
  const _AdvanceButton({
    required this.isLast,
    required this.label,
    required this.onPressed,
  });

  final bool isLast;
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final l = L.of(context);
    return Semantics(
      button: true,
      label: isLast ? label : l.actionNext,
      excludeSemantics: true,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onPressed,
        child: AnimatedContainer(
          duration: AppMotion.respecting(context, AppMotion.normal),
          curve: AppMotion.enter,
          height: 56,
          padding: EdgeInsets.symmetric(horizontal: isLast ? 12 : 12),
          decoration: BoxDecoration(
            color: c.accent,
            borderRadius: AppRadius.rPill,
            border: Border.all(color: c.textPrimary, width: 1.4),
            boxShadow: [
              BoxShadow(
                color: c.accent.withValues(alpha: 0.45),
                blurRadius: 22,
                offset: const Offset(0, 10),
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              AnimatedSize(
                duration: AppMotion.respecting(context, AppMotion.normal),
                curve: AppMotion.enter,
                child: isLast
                    ? Padding(
                        padding: const EdgeInsetsDirectional.only(
                          start: 12,
                          end: 10,
                        ),
                        child: Text(
                          label,
                          style: Theme.of(
                            context,
                          ).textTheme.labelLarge?.copyWith(color: c.onAccent),
                        ),
                      )
                    : const SizedBox(width: 2),
              ),
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: c.surfaceInverse,
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  Icons.arrow_forward_rounded,
                  size: 18,
                  color: c.textOnInverse,
                  // Points the way the page turns, which is leftward in
                  // Arabic.
                  textDirection: Directionality.of(context),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
