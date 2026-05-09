import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});
  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> with TickerProviderStateMixin {
  late final AnimationController _route =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 3200))..repeat();

  @override
  void dispose() {
    _route.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final displaySize = size.height < 720 ? 34.0 : 40.0;
    final heroHeight = (size.width * 0.42).clamp(140.0, 200.0);
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: Stack(
        children: [
          Positioned.fill(child: CustomPaint(painter: _GrainPainter())),
          SafeArea(
            child: SingleChildScrollView(
              physics: const ClampingScrollPhysics(),
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  minHeight: size.height - MediaQuery.paddingOf(context).vertical,
                ),
                child: IntrinsicHeight(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SizedBox(height: AppSpacing.x4),
                      Row(
                        children: [
                          _Logo()
                              .animate()
                              .fadeIn(duration: 600.ms)
                              .slideX(begin: -0.1, end: 0),
                          const Spacer(),
                          const StampChip(
                                  label: "EST. 2026 · ALG ↔ FR", angle: 0.05)
                              .animate()
                              .fadeIn(delay: 600.ms, duration: 500.ms)
                              .moveY(begin: -8, end: 0),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.x8),
                      AnimatedBuilder(
                        animation: _route,
                        builder: (_, __) => CustomPaint(
                          painter: _RoutePainter(_route.value),
                          size: Size(double.infinity, heroHeight),
                        ),
                      ).animate().fadeIn(delay: 200.ms, duration: 800.ms),
                      const SizedBox(height: AppSpacing.x3),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text("ALGIERS",
                                  style: AppType.mono(11,
                                      color: AppColors.inkMute)),
                              const SizedBox(height: 2),
                              const CountryPill(
                                  code: 'DZ', label: 'DZ', dense: true),
                            ],
                          ),
                          Text("DIRECT · 2H 25M",
                              style: AppType.mono(10, color: AppColors.inkMute)
                                  .copyWith(letterSpacing: 1.4)),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              Text("PARIS",
                                  style: AppType.mono(11,
                                      color: AppColors.inkMute)),
                              const SizedBox(height: 2),
                              const CountryPill(
                                  code: 'FR', label: 'FR', dense: true),
                            ],
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.x8),
                      Text("Welcome", style: AppType.eyebrow())
                          .animate()
                          .fadeIn(delay: 400.ms),
                      const SizedBox(height: AppSpacing.x3),
                      Text(
                        "Send anything,\nthe travelers do\nthe rest.",
                        style: AppType.display(displaySize,
                            w: FontWeight.w400, height: 1.05),
                      )
                          .animate()
                          .fadeIn(delay: 500.ms, duration: 700.ms)
                          .moveY(begin: 12, end: 0, curve: kAppCurve),
                      const SizedBox(height: AppSpacing.x4),
                      Text(
                        "A peer-to-peer corridor between Algeria and France. Travelers carry, senders save. Verified, escrowed, in DZD.",
                        style: AppType.body(14,
                            color: AppColors.inkSoft, height: 1.55),
                      )
                          .animate()
                          .fadeIn(delay: 700.ms, duration: 700.ms)
                          .moveY(begin: 8, end: 0),
                      const Spacer(),
                      const SizedBox(height: AppSpacing.x6),
                      Row(
                        children: [
                          Expanded(
                            child: PrimaryButton(
                              label: "Get started",
                              icon: Icons.arrow_forward_rounded,
                              expand: true,
                              color: AppColors.sun,
                              fg: AppColors.ink,
                              onTap: () => context.push('/benefits'),
                            ),
                          ),
                          const SizedBox(width: AppSpacing.x3),
                          GhostButton(
                              label: "Sign in",
                              onTap: () => context.push('/auth/sign-in')),
                        ],
                      )
                          .animate()
                          .fadeIn(delay: 900.ms, duration: 600.ms)
                          .moveY(begin: 8, end: 0),
                      const SizedBox(height: AppSpacing.x4),
                      Row(
                        children: [
                          _Dot(),
                          const SizedBox(width: 8),
                          Flexible(
                            child: Text(
                              "KYC verified · Escrow · DZD pricing",
                              style: AppType.body(12,
                                  color: AppColors.inkMute,
                                  w: FontWeight.w500),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ).animate().fadeIn(delay: 1100.ms),
                      const SizedBox(height: AppSpacing.x4),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Logo extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 30,
          height: 30,
          decoration: BoxDecoration(
            color: AppColors.ink,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Center(
            child: Transform.rotate(
              angle: -0.78,
              child: const Icon(Icons.airplanemode_active, size: 16, color: AppColors.parchment),
            ),
          ),
        ),
        const SizedBox(width: 10),
        Text("ShipTrip", style: AppType.display(20, w: FontWeight.w500)),
      ],
    );
  }
}

class _Dot extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      width: 6,
      height: 6,
      decoration: const BoxDecoration(color: AppColors.success, shape: BoxShape.circle),
    );
  }
}

/// Animated dashed flight path between two cities.
class _RoutePainter extends CustomPainter {
  _RoutePainter(this.t);
  final double t;

  @override
  void paint(Canvas canvas, Size size) {
    final start = Offset(20, size.height * 0.78);
    final end = Offset(size.width - 20, size.height * 0.32);
    final ctrl1 = Offset(size.width * 0.30, size.height * 0.05);
    final ctrl2 = Offset(size.width * 0.70, size.height * 0.85);
    final path = Path()
      ..moveTo(start.dx, start.dy)
      ..cubicTo(ctrl1.dx, ctrl1.dy, ctrl2.dx, ctrl2.dy, end.dx, end.dy);

    // dashed path drawing
    final dashPaint = Paint()
      ..color = AppColors.ink.withValues(alpha: 0.25)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    const dashW = 6.0, gap = 4.0;
    final metrics = path.computeMetrics().toList();
    for (final m in metrics) {
      double dist = 0;
      while (dist < m.length) {
        final next = math.min(dist + dashW, m.length);
        canvas.drawPath(m.extractPath(dist, next), dashPaint);
        dist = next + gap;
      }
    }

    // moving glow tracer
    for (final m in metrics) {
      final tracePos = m.getTangentForOffset(m.length * t);
      if (tracePos != null) {
        final p = tracePos.position;
        // glow halo
        canvas.drawCircle(p, 14, Paint()..color = AppColors.terracotta.withValues(alpha: 0.18));
        canvas.drawCircle(p, 8, Paint()..color = AppColors.terracotta.withValues(alpha: 0.35));
        // plane core
        canvas.save();
        canvas.translate(p.dx, p.dy);
        canvas.rotate(tracePos.angle);
        final planePaint = Paint()..color = AppColors.ink;
        final plane = Path()
          ..moveTo(8, 0)
          ..lineTo(-6, -4)
          ..lineTo(-3, 0)
          ..lineTo(-6, 4)
          ..close();
        canvas.drawPath(plane, planePaint);
        canvas.restore();
      }
    }

    // city dots
    final dot = Paint()..color = AppColors.ink;
    canvas.drawCircle(start, 5, dot);
    canvas.drawCircle(start, 12, Paint()..color = AppColors.ink.withValues(alpha: 0.08));
    canvas.drawCircle(end, 5, dot);
    canvas.drawCircle(end, 12, Paint()..color = AppColors.ink.withValues(alpha: 0.08));

    // emerald accent line under cities
    final accent = Paint()
      ..color = AppColors.emerald
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(start + const Offset(-12, 18), start + const Offset(12, 18), accent);
    canvas.drawLine(end + const Offset(-12, 18), end + const Offset(12, 18), accent);
  }

  @override
  bool shouldRepaint(covariant _RoutePainter old) => old.t != t;
}

/// Subtle paper-grain noise.
class _GrainPainter extends CustomPainter {
  final _rand = math.Random(7);
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = AppColors.ink.withValues(alpha: 0.025);
    for (int i = 0; i < 1400; i++) {
      final x = _rand.nextDouble() * size.width;
      final y = _rand.nextDouble() * size.height;
      canvas.drawCircle(Offset(x, y), 0.5, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _GrainPainter old) => false;
}
