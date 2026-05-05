import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';

/// Passport-stamp style chip — slight rotation, dashed border, ink color.
class StampChip extends StatelessWidget {
  const StampChip({super.key, required this.label, this.color, this.angle = -0.04});
  final String label;
  final Color? color;
  final double angle;

  @override
  Widget build(BuildContext context) {
    final c = color ?? AppColors.stamp;
    return Transform.rotate(
      angle: angle,
      child: CustomPaint(
        painter: _DashedBorderPainter(color: c.withValues(alpha: 0.7)),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          child: Text(
            label.toUpperCase(),
            style: AppType.eyebrow(color: c).copyWith(letterSpacing: 1.8, fontWeight: FontWeight.w700),
          ),
        ),
      ),
    );
  }
}

class _DashedBorderPainter extends CustomPainter {
  _DashedBorderPainter({required this.color});
  final Color color;
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4;
    const dashW = 4.0, dashGap = 3.0;
    final rect = RRect.fromRectAndRadius(
      Rect.fromLTWH(0, 0, size.width, size.height),
      const Radius.circular(4),
    );
    final path = Path()..addRRect(rect);
    final metrics = path.computeMetrics();
    for (final m in metrics) {
      double dist = 0;
      while (dist < m.length) {
        final next = math.min(dist + dashW, m.length);
        canvas.drawPath(m.extractPath(dist, next), paint);
        dist = next + dashGap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DashedBorderPainter old) => old.color != color;
}
