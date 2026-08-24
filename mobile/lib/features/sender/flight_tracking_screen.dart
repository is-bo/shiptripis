import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/stamp_chip.dart';

/// Live flight tracking — clean parchment route illustration, no map.
class FlightTrackingScreen extends StatefulWidget {
  const FlightTrackingScreen({
    super.key,
    required this.tripId,
    this.flightNo = "AH 1004",
    this.origin = "Algiers",
    this.dest = "Paris",
    this.originCode = "ALG",
    this.destCode = "CDG",
  });
  final String tripId;
  final String flightNo;
  final String origin;
  final String dest;
  final String originCode;
  final String destCode;

  @override
  State<FlightTrackingScreen> createState() => _FlightTrackingScreenState();
}

class _FlightTrackingScreenState extends State<FlightTrackingScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctl;

  @override
  void initState() {
    super.initState();
    _ctl = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 16),
    )..repeat();
  }

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Column(
          children: [
            _topBar(),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
                children: [
                  Text("Tracking", style: AppType.eyebrow()),
                  const SizedBox(height: 6),
                  Text("Your parcel\nis in the air.",
                      style: AppType.display(32,
                          w: FontWeight.w400, height: 1.05)),
                  const SizedBox(height: AppSpacing.x6),
                  AnimatedBuilder(
                    animation: _ctl,
                    builder: (_, _) => _routeCard(_ctl.value),
                  ),
                  const SizedBox(height: AppSpacing.x5),
                  AnimatedBuilder(
                    animation: _ctl,
                    builder: (_, _) => _statsRow(_ctl.value),
                  ),
                  const SizedBox(height: AppSpacing.x5),
                  _label("Flight"),
                  const SizedBox(height: 10),
                  _flightCard(),
                  const SizedBox(height: AppSpacing.x5),
                  _label("Timeline"),
                  const SizedBox(height: 10),
                  AnimatedBuilder(
                    animation: _ctl,
                    builder: (_, _) => _timeline(_ctl.value),
                  ),
                  const SizedBox(height: AppSpacing.x4),
                  _liveBadge(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _topBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x4, AppSpacing.x4, AppSpacing.x4, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => context.pop(),
            icon: const Icon(Icons.arrow_back_rounded),
            style: IconButton.styleFrom(
              backgroundColor: AppColors.parchmentSoft,
              shape: const CircleBorder(),
            ),
          ),
          const Spacer(),
          StampChip(label: "IN TRANSIT", color: AppColors.sun),
        ],
      ),
    );
  }

  Widget _routeCard(double progress) {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 24, 20, 22),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.xl),
        border: Border.all(color: AppColors.hairline),
        boxShadow: AppShadows.card,
      ),
      child: Column(
        children: [
          Row(
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(widget.originCode,
                      style: AppType.display(36,
                          w: FontWeight.w400, height: 1)),
                  const SizedBox(height: 4),
                  Text(widget.origin,
                      style: AppType.body(12.5,
                          color: AppColors.inkMute, w: FontWeight.w600)),
                  const SizedBox(height: 6),
                  const CountryPill(code: 'DZ', label: 'DZ', dense: true),
                ],
              ),
              const Spacer(),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(widget.destCode,
                      style: AppType.display(36,
                          w: FontWeight.w400, height: 1)),
                  const SizedBox(height: 4),
                  Text(widget.dest,
                      style: AppType.body(12.5,
                          color: AppColors.inkMute, w: FontWeight.w600)),
                  const SizedBox(height: 6),
                  const CountryPill(code: 'FR', label: 'FR', dense: true),
                ],
              ),
            ],
          ),
          const SizedBox(height: 22),
          SizedBox(
            height: 84,
            child: CustomPaint(
              painter: _ArcRoutePainter(progress: progress),
              size: Size.infinite,
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Text("Departed 09:42",
                  style: AppType.mono(11.5,
                      color: AppColors.emerald, w: FontWeight.w700)),
              const Spacer(),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.sun.withValues(alpha: 0.25),
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: Text("${(progress * 100).toInt()}% complete",
                    style: AppType.mono(11,
                        color: AppColors.ink, w: FontWeight.w700)),
              ),
              const Spacer(),
              Text("Arrives 12:07",
                  style: AppType.mono(11.5,
                      color: AppColors.terracotta, w: FontWeight.w700)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _statsRow(double p) {
    final altitude = 9800 + (math.sin(p * math.pi) * 600).round();
    final speed = 845 + (math.sin(p * math.pi * 2) * 12).round();
    final etaMin = ((1 - p) * 138).round();
    final h = etaMin ~/ 60;
    final m = etaMin % 60;
    return Row(
      children: [
        _stat("Altitude", "${_fmt(altitude)} m", Icons.arrow_upward_rounded),
        const SizedBox(width: 10),
        _stat("Speed", "$speed km/h", Icons.speed_rounded),
        const SizedBox(width: 10),
        _stat("ETA", "${h}h ${m.toString().padLeft(2, '0')}m",
            Icons.schedule_rounded),
      ],
    );
  }

  Widget _stat(String label, String value, IconData icon) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 10),
        decoration: BoxDecoration(
          color: AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: AppColors.hairline),
        ),
        child: Column(
          children: [
            Icon(icon, size: 16, color: AppColors.inkMute),
            const SizedBox(height: 8),
            Text(value,
                style: AppType.mono(13, w: FontWeight.w700),
                maxLines: 1,
                overflow: TextOverflow.ellipsis),
            const SizedBox(height: 2),
            Text(label.toUpperCase(),
                style: AppType.eyebrow().copyWith(letterSpacing: 1.4)),
          ],
        ),
      ),
    );
  }

  Widget _flightCard() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: AppColors.sun,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Transform.rotate(
              angle: -0.78,
              child: const Icon(Icons.airplanemode_active,
                  size: 22, color: AppColors.ink),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.flightNo,
                    style: AppType.mono(15,
                        color: AppColors.parchment, w: FontWeight.w700)),
                const SizedBox(height: 2),
                Text("Air Algérie · Airbus A330",
                    style: AppType.body(12,
                        color: AppColors.parchmentDeep, w: FontWeight.w500)),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.emerald,
              borderRadius: BorderRadius.circular(AppRadius.pill),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 6,
                  height: 6,
                  decoration: const BoxDecoration(
                      color: AppColors.parchment, shape: BoxShape.circle),
                ),
                const SizedBox(width: 6),
                Text("ON TIME",
                    style: AppType.mono(10,
                        color: AppColors.parchment, w: FontWeight.w700)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _timeline(double p) {
    final steps = [
      ("Picked up", "Algiers · Hydra", true),
      ("Departed ALG", "09:42 · Gate B12", true),
      ("In flight", "Cruising over Med.", p < 0.95),
      ("Arrived CDG", "Terminal 2E", p >= 0.95),
      ("Delivered", "Paris · 13e", false),
    ];
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        children: List.generate(steps.length, (i) {
          final s = steps[i];
          final done = s.$3;
          final isLast = i == steps.length - 1;
          return _timelineRow(
            label: s.$1,
            sub: s.$2,
            done: done,
            isLast: isLast,
            pulse: i == 2 && p < 0.95,
          );
        }),
      ),
    );
  }

  Widget _timelineRow({
    required String label,
    required String sub,
    required bool done,
    required bool isLast,
    required bool pulse,
  }) {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Column(
            children: [
              Container(
                width: 14,
                height: 14,
                margin: const EdgeInsets.only(top: 2),
                decoration: BoxDecoration(
                  color: done ? AppColors.sun : AppColors.parchment,
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: done ? AppColors.sunDeep : AppColors.hairline,
                    width: 1.5,
                  ),
                  boxShadow: pulse
                      ? [
                          BoxShadow(
                            color: AppColors.sun.withValues(alpha: 0.5),
                            blurRadius: 12,
                          ),
                        ]
                      : null,
                ),
                child: done
                    ? const Icon(Icons.check_rounded,
                        size: 10, color: AppColors.ink)
                    : null,
              ),
              if (!isLast)
                Expanded(
                  child: Container(
                    width: 1.4,
                    color: done ? AppColors.sun : AppColors.hairline,
                  ),
                ),
            ],
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: isLast ? 0 : 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label,
                      style: AppType.body(13.5,
                          w: FontWeight.w700,
                          color: done ? AppColors.ink : AppColors.inkMute)),
                  const SizedBox(height: 2),
                  Text(sub,
                      style: AppType.body(11.5,
                          color: AppColors.inkMute, w: FontWeight.w500)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _liveBadge() {
    return Row(
      children: [
        const Icon(Icons.info_outline_rounded,
            size: 14, color: AppColors.inkMute),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            "Live data · powered by OpenSky Network · refresh ~30s",
            style: AppType.body(11,
                color: AppColors.inkMute, w: FontWeight.w500),
          ),
        ),
      ],
    );
  }

  Widget _label(String t) =>
      Text(t.toUpperCase(), style: AppType.eyebrow());

  static String _fmt(int n) {
    final s = n.toString();
    return s.replaceAllMapped(
        RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => "${m[1]} ");
  }
}

class _ArcRoutePainter extends CustomPainter {
  _ArcRoutePainter({required this.progress});
  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final start = Offset(12, size.height - 12);
    final end = Offset(size.width - 12, size.height - 12);
    final ctrl = Offset(size.width / 2, -8);

    final path = Path()
      ..moveTo(start.dx, start.dy)
      ..quadraticBezierTo(ctrl.dx, ctrl.dy, end.dx, end.dy);

    // dashed full route
    final dashPaint = Paint()
      ..color = AppColors.hairline
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6;
    _drawDashed(canvas, path, dashPaint, dash: 6, gap: 5);

    // traveled portion solid
    final metric = path.computeMetrics().first;
    final traveled = metric.extractPath(0, metric.length * progress);
    final solid = Paint()
      ..color = AppColors.ink
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.4
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(traveled, solid);

    // origin / dest dots
    final dot = Paint()..color = AppColors.ink;
    canvas.drawCircle(start, 5, dot);
    canvas.drawCircle(end, 5, Paint()..color = AppColors.terracotta);

    // soft halo on dots
    canvas.drawCircle(start, 11,
        Paint()..color = AppColors.ink.withValues(alpha: 0.08));
    canvas.drawCircle(end, 11,
        Paint()..color = AppColors.terracotta.withValues(alpha: 0.15));

    // moving plane
    final t = metric.getTangentForOffset(metric.length * progress);
    if (t != null) {
      final glow = Paint()
        ..color = AppColors.sun.withValues(alpha: 0.55)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 10);
      canvas.drawCircle(t.position, 14, glow);

      canvas.save();
      canvas.translate(t.position.dx, t.position.dy);
      canvas.rotate(math.atan2(t.vector.dy, t.vector.dx));
      final fill = Paint()..color = AppColors.ink;
      final p = Path()
        ..moveTo(11, 0)
        ..lineTo(-6, -6)
        ..lineTo(-3, 0)
        ..lineTo(-6, 6)
        ..close();
      canvas.drawPath(p, fill);
      canvas.restore();
    }
  }

  void _drawDashed(Canvas c, Path path, Paint paint,
      {double dash = 6, double gap = 4}) {
    for (final m in path.computeMetrics()) {
      var d = 0.0;
      while (d < m.length) {
        c.drawPath(m.extractPath(d, d + dash), paint);
        d += dash + gap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _ArcRoutePainter old) =>
      old.progress != progress;
}
