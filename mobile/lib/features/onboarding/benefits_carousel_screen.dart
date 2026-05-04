import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';

class BenefitsCarouselScreen extends StatefulWidget {
  const BenefitsCarouselScreen({super.key});

  @override
  State<BenefitsCarouselScreen> createState() => _BenefitsCarouselScreenState();
}

class _BenefitsCarouselScreenState extends State<BenefitsCarouselScreen> {
  final _controller = PageController();
  int _index = 0;

  static const _pages = <_BenefitPage>[
    _BenefitPage(
      indexLabel: '01 / 03',
      eyebrow: 'CHAPITRE I · LA POSTE',
      headlineEn: 'Send anywhere,\nfor a fraction.',
      subtitleFr: 'Envoyez vers la France, l\u2019Alg\u00e9rie, et plus loin.',
      bodyEn:
          'Travelers carry your parcel as part of their luggage. You pay a sliver of express shipping.',
      bodyFr:
          'Des voyageurs transportent vos colis. Vous payez une fraction du tarif express.',
      hero: _Hero.postcard,
      stampLabel: 'PAR AVION',
    ),
    _BenefitPage(
      indexLabel: '02 / 03',
      eyebrow: 'CHAPITRE II · LA VALISE',
      headlineEn: 'Earn while\nyou travel.',
      subtitleFr: 'Voyagez. Gagnez.',
      bodyEn:
          'Going to Algiers, Paris, or Oran already? Fill the unused kilos in your luggage.',
      bodyFr:
          'Vous partez \u00e0 Alger, Paris ou Oran\u00a0? Remplissez les kilos inutilis\u00e9s.',
      hero: _Hero.boardingPass,
      stampLabel: 'BOARDING',
    ),
    _BenefitPage(
      indexLabel: '03 / 03',
      eyebrow: 'CHAPITRE III · LE SCEAU',
      headlineEn: 'Built for\ntrust.',
      subtitleFr: 'Con\u00e7u pour la confiance.',
      bodyEn:
          'Verified IDs, escrow payments, four-digit pickup codes. Every handover proven.',
      bodyFr:
          'Identit\u00e9s v\u00e9rifi\u00e9es, paiement s\u00e9questre, codes de retrait \u00e0 quatre chiffres.',
      hero: _Hero.seal,
      stampLabel: 'VERIFIED',
    ),
  ];

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _advance() {
    if (_index >= _pages.length - 1) {
      context.go('/auth/sign-up');
      return;
    }
    _controller.nextPage(
      duration: AppDurations.med,
      curve: kAppCurve,
    );
  }

  void _skip() => context.go('/auth/sign-up');

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final isShort = size.height < 720;
    final headlineSize = isShort ? 36.0 : 44.0;
    final isLast = _index == _pages.length - 1;

    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: Stack(
        children: [
          const Positioned.fill(child: _GrainLayer()),
          // Subtle vignette tint shifts per page (warmer on page 2, cool on page 3).
          Positioned.fill(
            child: AnimatedSwitcher(
              duration: AppDurations.slow,
              child: ColoredBox(
                key: ValueKey(_index),
                color: switch (_index) {
                  0 => const Color(0x00000000),
                  1 => const Color(0x0CE8763A), // warm wash
                  _ => const Color(0x0A0E5A4F), // emerald wash
                },
              ),
            ),
          ),
          SafeArea(
            child: Column(
              children: [
                // Header: index counter + skip.
                Padding(
                  padding: const EdgeInsets.fromLTRB(
                      AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, 0),
                  child: Row(
                    children: [
                      AnimatedSwitcher(
                        duration: AppDurations.fast,
                        transitionBuilder: (c, a) => FadeTransition(
                          opacity: a,
                          child: SlideTransition(
                            position: Tween<Offset>(
                              begin: const Offset(0, 0.3),
                              end: Offset.zero,
                            ).animate(a),
                            child: c,
                          ),
                        ),
                        child: Text(
                          _pages[_index].indexLabel,
                          key: ValueKey(_index),
                          style: AppType.mono(11,
                                  color: AppColors.inkMute,
                                  w: FontWeight.w600)
                              .copyWith(letterSpacing: 2),
                        ),
                      ),
                      const Spacer(),
                      _SkipButton(onTap: _skip, hidden: isLast),
                    ],
                  ),
                ),

                // Hero + copy carousel.
                Expanded(
                  child: PageView.builder(
                    controller: _controller,
                    onPageChanged: (i) => setState(() => _index = i),
                    itemCount: _pages.length,
                    itemBuilder: (context, i) => _BenefitPageView(
                      key: ValueKey('benefit-$i'),
                      page: _pages[i],
                      headlineSize: headlineSize,
                      heroHeight: (size.height * 0.34).clamp(220.0, 320.0),
                      isActive: i == _index,
                    ),
                  ),
                ),

                // Footer: indicator + CTA.
                Padding(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.x6, 0,
                      AppSpacing.x6, AppSpacing.x6),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      _PassportDots(count: _pages.length, active: _index),
                      const Spacer(),
                      _AdvanceCta(isLast: isLast, onTap: _advance),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// Page model
// =============================================================================

enum _Hero { postcard, boardingPass, seal }

class _BenefitPage {
  const _BenefitPage({
    required this.indexLabel,
    required this.eyebrow,
    required this.headlineEn,
    required this.subtitleFr,
    required this.bodyEn,
    required this.bodyFr,
    required this.hero,
    required this.stampLabel,
  });

  final String indexLabel;
  final String eyebrow;
  final String headlineEn;
  final String subtitleFr;
  final String bodyEn;
  final String bodyFr;
  final _Hero hero;
  final String stampLabel;
}

// =============================================================================
// Single page (hero + staggered text)
// =============================================================================

class _BenefitPageView extends StatelessWidget {
  const _BenefitPageView({
    super.key,
    required this.page,
    required this.headlineSize,
    required this.heroHeight,
    required this.isActive,
  });

  final _BenefitPage page;
  final double headlineSize;
  final double heroHeight;
  final bool isActive;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      physics: const NeverScrollableScrollPhysics(),
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: AppSpacing.x6),
          // Hero illustration — RepaintBoundary keeps the painter cached as the
          // PageView slides under it.
          RepaintBoundary(
            child: SizedBox(
              height: heroHeight,
              child: _HeroFrame(
                page: page,
                isActive: isActive,
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.x8),
          Text(page.eyebrow, style: AppType.eyebrow())
              .animate(target: isActive ? 1 : 0)
              .fadeIn(duration: 400.ms)
              .moveY(begin: 6, end: 0),
          const SizedBox(height: AppSpacing.x3),
          Text(
            page.headlineEn,
            style: AppType.display(headlineSize,
                w: FontWeight.w400, height: 1.02),
          )
              .animate(target: isActive ? 1 : 0)
              .fadeIn(delay: 80.ms, duration: 600.ms)
              .moveY(begin: 16, end: 0, curve: kAppCurve),
          const SizedBox(height: AppSpacing.x3),
          // FR subtitle — italicized Fraunces; small caps shadow line.
          Text(
            page.subtitleFr,
            style: AppType.display(18,
                color: AppColors.terracottaDeep,
                w: FontWeight.w400,
                height: 1.2).copyWith(fontStyle: FontStyle.italic),
          )
              .animate(target: isActive ? 1 : 0)
              .fadeIn(delay: 200.ms, duration: 600.ms)
              .moveY(begin: 10, end: 0, curve: kAppCurve),
          const SizedBox(height: AppSpacing.x4),
          // EN body — sans, ink soft.
          Text(
            page.bodyEn,
            style: AppType.body(14,
                color: AppColors.inkSoft, height: 1.55, w: FontWeight.w500),
          )
              .animate(target: isActive ? 1 : 0)
              .fadeIn(delay: 320.ms, duration: 600.ms)
              .moveY(begin: 8, end: 0),
          const SizedBox(height: AppSpacing.x2),
          // FR body — same line height, mute.
          Text(
            page.bodyFr,
            style: AppType.body(13,
                color: AppColors.inkMute, height: 1.55, w: FontWeight.w400),
          )
              .animate(target: isActive ? 1 : 0)
              .fadeIn(delay: 420.ms, duration: 600.ms)
              .moveY(begin: 8, end: 0),
        ],
      ),
    );
  }
}

// =============================================================================
// Hero "stamped page" frame — wraps each painter with a postcard border + label.
// =============================================================================

class _HeroFrame extends StatelessWidget {
  const _HeroFrame({required this.page, required this.isActive});

  final _BenefitPage page;
  final bool isActive;

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        // Card with airmail-style border.
        Positioned.fill(
          child: Transform.rotate(
            angle: -0.012,
            child: Container(
              decoration: BoxDecoration(
                color: AppColors.parchmentSoft,
                borderRadius: BorderRadius.circular(AppRadius.lg),
                boxShadow: AppShadows.card,
                border: Border.all(color: AppColors.hairlineSoft),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(AppRadius.lg),
                child: CustomPaint(
                  painter: const _AirmailBorderPainter(),
                  child: Padding(
                    padding: const EdgeInsets.all(AppSpacing.x4),
                    child: _HeroBody(hero: page.hero, isActive: isActive),
                  ),
                ),
              ),
            ),
          ),
        ),
        // Postage stamp — top-right, slight tilt.
        Positioned(
          top: -10,
          right: 12,
          child: _PostageStamp(label: page.stampLabel)
              .animate(target: isActive ? 1 : 0)
              .scale(
                begin: const Offset(0.7, 0.7),
                end: const Offset(1, 1),
                delay: 240.ms,
                duration: 500.ms,
                curve: kAppCurve,
              )
              .fadeIn(delay: 240.ms),
        ),
      ],
    );
  }
}

class _HeroBody extends StatelessWidget {
  const _HeroBody({required this.hero, required this.isActive});

  final _Hero hero;
  final bool isActive;

  @override
  Widget build(BuildContext context) {
    return switch (hero) {
      _Hero.postcard => _FlyingParcelHero(active: isActive),
      _Hero.boardingPass => _BoardingPassHero(active: isActive),
      _Hero.seal => _PickupCodeSealHero(active: isActive),
    };
  }
}

// =============================================================================
// Page 1 hero — Flying parcel arc on a postcard.
// =============================================================================

class _FlyingParcelHero extends StatefulWidget {
  const _FlyingParcelHero({required this.active});
  final bool active;

  @override
  State<_FlyingParcelHero> createState() => _FlyingParcelHeroState();
}

class _FlyingParcelHeroState extends State<_FlyingParcelHero>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3600),
  );

  @override
  void initState() {
    super.initState();
    if (widget.active) _ctrl.repeat();
  }

  @override
  void didUpdateWidget(covariant _FlyingParcelHero oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !_ctrl.isAnimating) _ctrl.repeat();
    if (!widget.active && _ctrl.isAnimating) _ctrl.stop();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        // Address lines (top-right) like a postcard "to:" block.
        Positioned(
          top: 8,
          right: 8,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('TO',
                  style:
                      AppType.mono(9, color: AppColors.inkMute).copyWith(letterSpacing: 1.4)),
              const SizedBox(height: 4),
              Container(width: 86, height: 1.4, color: AppColors.hairline),
              const SizedBox(height: 6),
              Container(width: 64, height: 1.4, color: AppColors.hairline),
              const SizedBox(height: 6),
              Container(width: 72, height: 1.4, color: AppColors.hairline),
            ],
          ),
        ),
        // The flying parcel.
        AnimatedBuilder(
          animation: _ctrl,
          builder: (_, _) => CustomPaint(
            painter: _FlyingParcelPainter(_ctrl.value),
            size: Size.infinite,
          ),
        ),
        // Bottom-left wax seal.
        Positioned(
          bottom: 12,
          left: 12,
          child: _WaxSeal(diameter: 38, glyph: 'S'),
        ),
      ],
    );
  }
}

class _FlyingParcelPainter extends CustomPainter {
  _FlyingParcelPainter(this.t);
  final double t;

  @override
  void paint(Canvas canvas, Size size) {
    // Arc anchors.
    final start = Offset(size.width * 0.12, size.height * 0.78);
    final end = Offset(size.width * 0.88, size.height * 0.34);
    final ctrl = Offset(size.width * 0.5, size.height * 0.05);

    final pathFull = Path()
      ..moveTo(start.dx, start.dy)
      ..quadraticBezierTo(ctrl.dx, ctrl.dy, end.dx, end.dy);

    // Dashed full route.
    final dashPaint = Paint()
      ..color = AppColors.ink.withValues(alpha: 0.18)
      ..strokeWidth = 1.6
      ..style = PaintingStyle.stroke;
    _drawDashed(canvas, pathFull, dashPaint, dash: 5, gap: 4);

    // Origin/destination markers.
    final markerStroke = Paint()
      ..color = AppColors.ink
      ..strokeWidth = 1.6
      ..style = PaintingStyle.stroke;
    canvas.drawCircle(start, 5, Paint()..color = AppColors.parchment);
    canvas.drawCircle(start, 5, markerStroke);
    canvas.drawCircle(end, 5, Paint()..color = AppColors.parchment);
    canvas.drawCircle(end, 5, markerStroke);

    // Animated parcel position.
    final pos = _quad(start, ctrl, end, t);
    final tangent = _quadTangent(start, ctrl, end, t);
    final angle = math.atan2(tangent.dy, tangent.dx);

    // Trailing motion dots (recent positions).
    for (int i = 1; i <= 6; i++) {
      final tt = (t - i * 0.02);
      if (tt < 0) continue;
      final p = _quad(start, ctrl, end, tt);
      final paint = Paint()
        ..color = AppColors.terracotta.withValues(alpha: (0.5 - i * 0.07).clamp(0.0, 1.0))
        ..style = PaintingStyle.fill;
      canvas.drawCircle(p, 2.4 - i * 0.2, paint);
    }

    // Parcel — square with a strap.
    canvas.save();
    canvas.translate(pos.dx, pos.dy);
    canvas.rotate(angle);
    const w = 22.0;
    const h = 16.0;
    final body = RRect.fromRectAndRadius(
      Rect.fromCenter(center: Offset.zero, width: w, height: h),
      const Radius.circular(3),
    );
    canvas.drawRRect(
        body, Paint()..color = AppColors.gold);
    canvas.drawRRect(
        body,
        Paint()
          ..color = AppColors.ink
          ..strokeWidth = 1.4
          ..style = PaintingStyle.stroke);
    // Strap.
    canvas.drawLine(
      Offset(0, -h / 2),
      Offset(0, h / 2),
      Paint()
        ..color = AppColors.ink
        ..strokeWidth = 1.4,
    );
    canvas.drawLine(
      Offset(-w / 2, 0),
      Offset(w / 2, 0),
      Paint()
        ..color = AppColors.ink
        ..strokeWidth = 1.4,
    );
    // Sun-yellow tag.
    canvas.drawCircle(
      Offset(-w / 2 + 3, -h / 2 + 3),
      2.8,
      Paint()..color = AppColors.sun,
    );
    canvas.restore();
  }

  Offset _quad(Offset p0, Offset p1, Offset p2, double t) {
    final u = 1 - t;
    return Offset(
      u * u * p0.dx + 2 * u * t * p1.dx + t * t * p2.dx,
      u * u * p0.dy + 2 * u * t * p1.dy + t * t * p2.dy,
    );
  }

  Offset _quadTangent(Offset p0, Offset p1, Offset p2, double t) {
    return Offset(
      2 * (1 - t) * (p1.dx - p0.dx) + 2 * t * (p2.dx - p1.dx),
      2 * (1 - t) * (p1.dy - p0.dy) + 2 * t * (p2.dy - p1.dy),
    );
  }

  void _drawDashed(Canvas canvas, Path path, Paint paint,
      {required double dash, required double gap}) {
    for (final metric in path.computeMetrics()) {
      double distance = 0;
      while (distance < metric.length) {
        final next = math.min(distance + dash, metric.length);
        canvas.drawPath(metric.extractPath(distance, next), paint);
        distance = next + gap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _FlyingParcelPainter old) => old.t != t;
}

// =============================================================================
// Page 2 hero — Boarding pass with perforation, stamps, coin stack.
// =============================================================================

class _BoardingPassHero extends StatelessWidget {
  const _BoardingPassHero({required this.active});
  final bool active;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, c) {
        return Stack(
          children: [
            CustomPaint(
              size: Size(c.maxWidth, c.maxHeight),
              painter: const _BoardingPassPainter(),
            ),
            // Animated coin stack drop.
            Positioned(
              right: 24,
              bottom: 18,
              child: _CoinStack(active: active),
            ),
          ],
        );
      },
    );
  }
}

class _BoardingPassPainter extends CustomPainter {
  const _BoardingPassPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final ink = Paint()
      ..color = AppColors.ink
      ..strokeWidth = 1.4
      ..style = PaintingStyle.stroke;
    final mute = Paint()
      ..color = AppColors.hairline
      ..strokeWidth = 1.0
      ..style = PaintingStyle.stroke;

    // Pass body insets.
    final r = Rect.fromLTWH(8, 8, size.width - 16, size.height - 16);

    // Header band — emerald with airline-tag look.
    final header = Rect.fromLTWH(r.left, r.top, r.width, 28);
    canvas.drawRect(
      header,
      Paint()..color = AppColors.emerald,
    );
    // Header text approximation as ticks.
    for (int i = 0; i < 8; i++) {
      final x = r.left + 14 + i * 12.0;
      canvas.drawLine(
        Offset(x, header.top + 12),
        Offset(x + 6, header.top + 12),
        Paint()
          ..color = AppColors.parchmentSoft
          ..strokeWidth = 1.4,
      );
    }
    // Sun dot at right of header.
    canvas.drawCircle(
      Offset(r.right - 16, header.center.dy),
      4.5,
      Paint()..color = AppColors.sun,
    );

    // Vertical perforation line at 65% (separates main + stub).
    final perfX = r.left + r.width * 0.65;
    final perfPaint = Paint()
      ..color = AppColors.inkMute
      ..strokeWidth = 1.0;
    double y = r.top + 36;
    while (y < r.bottom - 6) {
      canvas.drawCircle(Offset(perfX, y), 1.2, perfPaint);
      y += 6;
    }

    // Left section: From / To + form lines.
    final leftPad = r.left + 14;
    // FROM block.
    _drawLabelAndValue(canvas,
        x: leftPad, y: r.top + 50, label: 'FROM', value: 'ALG', accent: ink);
    // Arrow.
    _drawArrow(canvas,
        from: Offset(leftPad + 50, r.top + 64),
        to: Offset(perfX - 60, r.top + 64),
        paint: ink);
    // TO block.
    _drawLabelAndValue(canvas,
        x: perfX - 50, y: r.top + 50, label: 'TO', value: 'CDG', accent: ink);

    // Form lines (passenger / class / seat placeholders).
    final formY = r.top + 96.0;
    _drawFormRow(canvas, x: leftPad, y: formY, w: perfX - leftPad - 20, mute: mute);
    _drawFormRow(canvas, x: leftPad, y: formY + 22, w: perfX - leftPad - 60, mute: mute);
    _drawFormRow(canvas, x: leftPad, y: formY + 44, w: perfX - leftPad - 100, mute: mute);

    // Right stub: stacked stamps box (decorative).
    final stub = Rect.fromLTWH(perfX + 12, r.top + 38, r.right - perfX - 22, r.height - 50);
    canvas.drawRect(stub, mute);

    // Decorative diagonal cancel-stamp lines on stub.
    canvas.save();
    canvas.clipRect(stub);
    final stampPaint = Paint()
      ..color = AppColors.terracotta.withValues(alpha: 0.6)
      ..strokeWidth = 1.6;
    for (double x = stub.left - stub.height; x < stub.right; x += 6) {
      canvas.drawLine(
        Offset(x, stub.top),
        Offset(x + stub.height, stub.bottom),
        stampPaint,
      );
    }
    canvas.restore();
    // Stub label.
    final tp = TextPainter(
      text: TextSpan(
        text: 'KG\nFREE',
        style: AppType.mono(11,
                color: AppColors.parchmentSoft, w: FontWeight.w700)
            .copyWith(letterSpacing: 1.4, height: 1.1),
      ),
      textAlign: TextAlign.center,
      textDirection: TextDirection.ltr,
    )..layout(maxWidth: stub.width);
    tp.paint(
      canvas,
      Offset(stub.center.dx - tp.width / 2,
          stub.center.dy - tp.height / 2 - 8),
    );

    // Bottom-left passport stamp.
    canvas.save();
    canvas.translate(leftPad + 60, r.bottom - 28);
    canvas.rotate(-0.18);
    _drawStampMark(canvas, label: 'DZD', accent: AppColors.terracottaDeep);
    canvas.restore();

    // Outer border.
    canvas.drawRRect(
        RRect.fromRectAndRadius(r, const Radius.circular(8)),
        Paint()
          ..color = AppColors.hairlineSoft
          ..strokeWidth = 1.0
          ..style = PaintingStyle.stroke);
  }

  void _drawLabelAndValue(Canvas canvas,
      {required double x,
      required double y,
      required String label,
      required String value,
      required Paint accent}) {
    final lp = TextPainter(
      text: TextSpan(
        text: label,
        style: AppType.mono(9, color: AppColors.inkMute, w: FontWeight.w600)
            .copyWith(letterSpacing: 1.4),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    lp.paint(canvas, Offset(x, y));

    final vp = TextPainter(
      text: TextSpan(
        text: value,
        style: AppType.display(22, w: FontWeight.w500, height: 1.0),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    vp.paint(canvas, Offset(x, y + 12));
  }

  void _drawArrow(Canvas canvas,
      {required Offset from, required Offset to, required Paint paint}) {
    canvas.drawLine(from, to, paint);
    final dir = (to - from);
    final ang = math.atan2(dir.dy, dir.dx);
    final p1 = to + Offset(math.cos(ang + math.pi - 0.5) * 6,
        math.sin(ang + math.pi - 0.5) * 6);
    final p2 = to + Offset(math.cos(ang + math.pi + 0.5) * 6,
        math.sin(ang + math.pi + 0.5) * 6);
    canvas.drawLine(to, p1, paint);
    canvas.drawLine(to, p2, paint);
  }

  void _drawFormRow(Canvas canvas,
      {required double x,
      required double y,
      required double w,
      required Paint mute}) {
    canvas.drawLine(Offset(x, y), Offset(x + w, y), mute);
  }

  void _drawStampMark(Canvas canvas,
      {required String label, required Color accent}) {
    final r = Rect.fromCenter(center: Offset.zero, width: 60, height: 26);
    final p = Paint()
      ..color = accent
      ..strokeWidth = 1.6
      ..style = PaintingStyle.stroke;
    canvas.drawRect(r, p);
    canvas.drawRect(r.deflate(3), p..strokeWidth = 0.8);
    final tp = TextPainter(
      text: TextSpan(
        text: label,
        style: AppType.mono(11, color: accent, w: FontWeight.w700)
            .copyWith(letterSpacing: 2),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, Offset(-tp.width / 2, -tp.height / 2));
  }

  @override
  bool shouldRepaint(covariant _BoardingPassPainter oldDelegate) => false;
}

class _CoinStack extends StatefulWidget {
  const _CoinStack({required this.active});
  final bool active;

  @override
  State<_CoinStack> createState() => _CoinStackState();
}

class _CoinStackState extends State<_CoinStack>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1400),
  );

  @override
  void initState() {
    super.initState();
    if (widget.active) _c.forward();
  }

  @override
  void didUpdateWidget(covariant _CoinStack old) {
    super.didUpdateWidget(old);
    if (widget.active && _c.value == 0) {
      _c.forward(from: 0);
    } else if (!widget.active) {
      _c.value = 0;
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (_, _) {
        return SizedBox(
          width: 56,
          height: 86,
          child: Stack(
            children: List.generate(4, (i) {
              final t = ((_c.value * 1.4) - i * 0.18).clamp(0.0, 1.0);
              final ease = Curves.easeOutBack.transform(t);
              return Positioned(
                left: 4 + i * 0.4,
                bottom: 6 + i * 9.0 - (1 - ease) * 22,
                child: Opacity(
                  opacity: ease,
                  child: _CoinDot(label: i == 3 ? 'DZD' : null),
                ),
              );
            }),
          ),
        );
      },
    );
  }
}

class _CoinDot extends StatelessWidget {
  const _CoinDot({this.label});
  final String? label;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 44,
      height: 12,
      decoration: BoxDecoration(
        color: AppColors.gold,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppColors.ink, width: 1.2),
      ),
      alignment: Alignment.center,
      child: label == null
          ? null
          : Text(
              label!,
              style: AppType.mono(8, color: AppColors.ink, w: FontWeight.w700)
                  .copyWith(letterSpacing: 1.2),
            ),
    );
  }
}

// =============================================================================
// Page 3 hero — Pickup-code seal: 4-digit ticker + wax seal + certification flourish.
// =============================================================================

class _PickupCodeSealHero extends StatefulWidget {
  const _PickupCodeSealHero({required this.active});
  final bool active;

  @override
  State<_PickupCodeSealHero> createState() => _PickupCodeSealHeroState();
}

class _PickupCodeSealHeroState extends State<_PickupCodeSealHero>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1800),
  );

  @override
  void initState() {
    super.initState();
    if (widget.active) _c.forward();
  }

  @override
  void didUpdateWidget(covariant _PickupCodeSealHero old) {
    super.didUpdateWidget(old);
    if (widget.active && _c.value == 0) {
      _c.forward(from: 0);
    } else if (!widget.active) {
      _c.value = 0;
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  static const _code = ['4', '7', '2', '9'];

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        // Certification radiating lines.
        Positioned.fill(
          child: AnimatedBuilder(
            animation: _c,
            builder: (_, _) => CustomPaint(
              painter: _CertFlourishPainter(t: _c.value),
            ),
          ),
        ),
        // Code reveal — 4 mono digits in vault frames.
        Center(
          child: Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: List.generate(_code.length, (i) {
                return Padding(
                  padding: EdgeInsets.symmetric(
                      horizontal: i == 1 ? 14 : 4, vertical: 4),
                  child: _CodeTile(
                    digit: _code[i],
                    delayMs: 200 + i * 120,
                    active: widget.active,
                  ),
                );
              }),
            ),
          ),
        ),
        // Wax seal bottom-right with checkmark.
        Positioned(
          bottom: 8,
          right: 12,
          child: _WaxSeal(diameter: 48, glyph: 'OK', accent: AppColors.emerald)
              .animate(target: widget.active ? 1 : 0)
              .scale(
                begin: const Offset(0.4, 0.4),
                end: const Offset(1, 1),
                delay: 700.ms,
                duration: 500.ms,
                curve: Curves.elasticOut,
              ),
        ),
        // "VERIFIED" caption strip top-left.
        Positioned(
          top: 8,
          left: 8,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.ink,
              borderRadius: BorderRadius.circular(2),
            ),
            child: Text(
              'HANDOVER · 4 DIGITS',
              style: AppType.mono(9,
                      color: AppColors.parchmentSoft, w: FontWeight.w700)
                  .copyWith(letterSpacing: 1.6),
            ),
          )
              .animate(target: widget.active ? 1 : 0)
              .fadeIn(delay: 100.ms)
              .moveY(begin: -6, end: 0),
        ),
      ],
    );
  }
}

class _CodeTile extends StatelessWidget {
  const _CodeTile(
      {required this.digit, required this.delayMs, required this.active});
  final String digit;
  final int delayMs;
  final bool active;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 48,
      height: 64,
      decoration: BoxDecoration(
        color: AppColors.parchment,
        border: Border.all(color: AppColors.ink, width: 1.4),
        borderRadius: BorderRadius.circular(4),
        boxShadow: AppShadows.stamped,
      ),
      alignment: Alignment.center,
      child: Stack(
        alignment: Alignment.center,
        children: [
          // Mid-line that suggests a split-flap.
          Positioned(
            left: 0,
            right: 0,
            top: 31,
            child: Container(height: 1, color: AppColors.hairline),
          ),
          Text(
            digit,
            style: AppType.display(34, w: FontWeight.w500),
          )
              .animate(target: active ? 1 : 0)
              .fadeIn(delay: delayMs.ms, duration: 300.ms)
              .slideY(
                begin: -0.4,
                end: 0,
                delay: delayMs.ms,
                duration: 400.ms,
                curve: kAppCurve,
              ),
        ],
      ),
    );
  }
}

class _CertFlourishPainter extends CustomPainter {
  _CertFlourishPainter({required this.t});
  final double t;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final maxR = size.shortestSide * 0.62;

    // Concentric arcs.
    for (int i = 0; i < 3; i++) {
      final r = maxR * (0.6 + i * 0.18);
      final paint = Paint()
        ..color = AppColors.gold.withValues(alpha: 0.18 - i * 0.04)
        ..strokeWidth = 1.0
        ..style = PaintingStyle.stroke;
      canvas.drawCircle(center, r * (0.6 + 0.4 * t), paint);
    }

    // Radiating ticks.
    final tickPaint = Paint()
      ..color = AppColors.emerald.withValues(alpha: 0.35)
      ..strokeWidth = 1.0;
    final activeTicks = (24 * t).floor();
    for (int i = 0; i < activeTicks; i++) {
      final ang = (i / 24) * math.pi * 2 - math.pi / 2;
      final r1 = maxR * 0.84;
      final r2 = maxR * 0.92;
      canvas.drawLine(
        Offset(center.dx + math.cos(ang) * r1, center.dy + math.sin(ang) * r1),
        Offset(center.dx + math.cos(ang) * r2, center.dy + math.sin(ang) * r2),
        tickPaint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _CertFlourishPainter old) => old.t != t;
}

// =============================================================================
// Shared bits — wax seal, postage stamp, dots, skip, advance CTA, grain layer.
// =============================================================================

class _WaxSeal extends StatelessWidget {
  const _WaxSeal({
    required this.diameter,
    required this.glyph,
    this.accent = AppColors.terracottaDeep,
  });
  final double diameter;
  final String glyph;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: diameter,
      height: diameter,
      child: CustomPaint(
        painter: _WaxSealPainter(accent: accent),
        child: Center(
          child: Text(
            glyph,
            style: AppType.display(diameter * 0.32,
                color: AppColors.parchmentSoft, w: FontWeight.w600),
          ),
        ),
      ),
    );
  }
}

class _WaxSealPainter extends CustomPainter {
  _WaxSealPainter({required this.accent});
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final r = size.shortestSide / 2;

    // Drip-edge shadow.
    canvas.drawCircle(
      center.translate(2, 2),
      r,
      Paint()..color = accent.withValues(alpha: 0.25),
    );
    // Body.
    canvas.drawCircle(center, r, Paint()..color = accent);
    // Inner darker ring.
    canvas.drawCircle(
      center,
      r - 2,
      Paint()
        ..color = AppColors.parchmentSoft.withValues(alpha: 0.25)
        ..strokeWidth = 1.4
        ..style = PaintingStyle.stroke,
    );
    // Subtle radial highlight.
    canvas.drawCircle(
      center.translate(-r * 0.25, -r * 0.25),
      r * 0.35,
      Paint()..color = AppColors.parchmentSoft.withValues(alpha: 0.18),
    );
  }

  @override
  bool shouldRepaint(covariant _WaxSealPainter oldDelegate) =>
      oldDelegate.accent != accent;
}

class _PostageStamp extends StatelessWidget {
  const _PostageStamp({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    return Transform.rotate(
      angle: 0.07,
      child: Container(
        width: 76,
        height: 86,
        padding: const EdgeInsets.all(6),
        decoration: BoxDecoration(
          color: AppColors.parchmentSoft,
          boxShadow: AppShadows.card,
        ),
        child: CustomPaint(
          painter: const _StampPerforationPainter(),
          child: Container(
            decoration: BoxDecoration(
              color: AppColors.emeraldDeep,
              border: Border.all(color: AppColors.gold, width: 1.4),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  label,
                  style: AppType.mono(9,
                          color: AppColors.gold, w: FontWeight.w700)
                      .copyWith(letterSpacing: 1.6),
                ),
                const SizedBox(height: 4),
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    color: AppColors.sun,
                    shape: BoxShape.circle,
                    border: Border.all(color: AppColors.gold, width: 1.4),
                  ),
                  child: const Center(
                    child: Icon(Icons.airplanemode_active,
                        size: 14, color: AppColors.ink),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'DZD 1',
                  style: AppType.mono(8,
                          color: AppColors.gold, w: FontWeight.w600)
                      .copyWith(letterSpacing: 1.2),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _StampPerforationPainter extends CustomPainter {
  const _StampPerforationPainter();

  @override
  void paint(Canvas canvas, Size size) {
    // Cuts perforation notches by drawing parchment-colored circles around
    // the stamp edge. The container above paints over the rest.
    final paint = Paint()..color = AppColors.parchmentSoft;
    const step = 8.0;
    for (double x = 0; x <= size.width; x += step) {
      canvas.drawCircle(Offset(x, 0), 2.6, paint);
      canvas.drawCircle(Offset(x, size.height), 2.6, paint);
    }
    for (double y = 0; y <= size.height; y += step) {
      canvas.drawCircle(Offset(0, y), 2.6, paint);
      canvas.drawCircle(Offset(size.width, y), 2.6, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _StampPerforationPainter oldDelegate) => false;
}

class _AirmailBorderPainter extends CustomPainter {
  const _AirmailBorderPainter();

  @override
  void paint(Canvas canvas, Size size) {
    // Diagonal red/blue stripes along the inner edge — classic par-avion border.
    const inset = 8.0;
    const thickness = 6.0;
    final inner = Rect.fromLTRB(
        inset, inset, size.width - inset, size.height - inset);

    final stripePaint = Paint()
      ..strokeWidth = thickness
      ..style = PaintingStyle.stroke;

    void edge(Path edgePath) {
      // Diagonal pattern: alternate red / blue / parchment.
      final colors = [
        AppColors.terracotta,
        AppColors.parchment,
        AppColors.emerald,
        AppColors.parchment,
      ];
      double offset = 0;
      const step = 8.0;
      for (final m in edgePath.computeMetrics()) {
        double d = 0;
        int idx = 0;
        while (d < m.length) {
          final next = math.min(d + step, m.length);
          stripePaint.color = colors[idx % colors.length];
          canvas.drawPath(m.extractPath(d, next), stripePaint);
          d = next;
          idx++;
          offset += step;
        }
      }
      offset; // unused; satisfy lints if any
    }

    final p = Path()
      ..moveTo(inner.left, inner.top)
      ..lineTo(inner.right, inner.top)
      ..lineTo(inner.right, inner.bottom)
      ..lineTo(inner.left, inner.bottom)
      ..close();
    edge(p);
  }

  @override
  bool shouldRepaint(covariant _AirmailBorderPainter old) => false;
}

class _PassportDots extends StatelessWidget {
  const _PassportDots({required this.count, required this.active});
  final int count;
  final int active;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: List.generate(count, (i) {
        final isActive = i == active;
        return Padding(
          padding: const EdgeInsets.only(right: 8),
          child: AnimatedContainer(
            duration: AppDurations.med,
            curve: kAppCurve,
            width: isActive ? 28 : 8,
            height: 8,
            decoration: BoxDecoration(
              color: isActive ? AppColors.sun : AppColors.parchmentDeep,
              borderRadius: BorderRadius.circular(4),
              border: isActive
                  ? Border.all(color: AppColors.ink.withValues(alpha: 0.18))
                  : null,
              boxShadow: isActive
                  ? [
                      BoxShadow(
                        color: AppColors.sun.withValues(alpha: 0.45),
                        blurRadius: 12,
                        offset: const Offset(0, 4),
                      ),
                    ]
                  : null,
            ),
          ),
        );
      }),
    );
  }
}

class _SkipButton extends StatelessWidget {
  const _SkipButton({required this.onTap, required this.hidden});
  final VoidCallback onTap;
  final bool hidden;

  @override
  Widget build(BuildContext context) {
    return AnimatedOpacity(
      opacity: hidden ? 0 : 1,
      duration: AppDurations.fast,
      child: IgnorePointer(
        ignoring: hidden,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.x2, vertical: AppSpacing.x2),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Skip',
                  style: AppType.body(13,
                      color: AppColors.inkMute, w: FontWeight.w600),
                ),
                const SizedBox(width: 4),
                const Icon(Icons.arrow_forward_rounded,
                    size: 14, color: AppColors.inkMute),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AdvanceCta extends StatelessWidget {
  const _AdvanceCta({required this.isLast, required this.onTap});
  final bool isLast;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: AnimatedContainer(
        duration: AppDurations.med,
        curve: kAppCurve,
        height: 56,
        padding: EdgeInsets.symmetric(horizontal: isLast ? 26 : 20),
        decoration: BoxDecoration(
          color: AppColors.sun,
          borderRadius: BorderRadius.circular(AppRadius.pill),
          border: Border.all(color: AppColors.ink, width: 1.4),
          boxShadow: [
            BoxShadow(
              color: AppColors.sun.withValues(alpha: 0.45),
              blurRadius: 22,
              offset: const Offset(0, 10),
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            AnimatedSize(
              duration: AppDurations.med,
              curve: kAppCurve,
              child: isLast
                  ? Padding(
                      padding: const EdgeInsets.only(right: 10),
                      child: Text(
                        'Get started',
                        style: AppType.body(15,
                            color: AppColors.ink, w: FontWeight.w700),
                      ),
                    )
                  : const SizedBox(width: 4),
            ),
            Container(
              width: 32,
              height: 32,
              decoration: const BoxDecoration(
                color: AppColors.ink,
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.arrow_forward_rounded,
                  size: 18, color: AppColors.parchmentSoft),
            ),
          ],
        ),
      ),
    );
  }
}

class _GrainLayer extends StatelessWidget {
  const _GrainLayer();

  @override
  Widget build(BuildContext context) {
    return CustomPaint(painter: _GrainPainter());
  }
}

class _GrainPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final rnd = math.Random(7);
    final paint = Paint()..color = AppColors.ink.withValues(alpha: 0.025);
    for (int i = 0; i < 320; i++) {
      final dx = rnd.nextDouble() * size.width;
      final dy = rnd.nextDouble() * size.height;
      canvas.drawCircle(Offset(dx, dy), 0.6, paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
