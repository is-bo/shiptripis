import 'package:flutter/material.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';

class OAuthButtons extends StatelessWidget {
  const OAuthButtons({super.key});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _OAuthBtn(
            label: "Google",
            iconBuilder: (s) => CustomPaint(painter: _GoogleG(), size: Size(s, s)),
            onTap: () {},
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _OAuthBtn(
            label: "Apple",
            iconBuilder: (s) => Icon(Icons.apple_rounded, size: s + 4, color: AppColors.ink),
            onTap: () {},
          ),
        ),
      ],
    );
  }
}

class _OAuthBtn extends StatelessWidget {
  const _OAuthBtn({required this.label, required this.iconBuilder, required this.onTap});
  final String label;
  final Widget Function(double size) iconBuilder;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14),
        decoration: BoxDecoration(
          color: AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.pill),
          border: Border.all(color: AppColors.hairline, width: 1.4),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            iconBuilder(18),
            const SizedBox(width: 10),
            Text(label,
                style: AppType.body(13.5, w: FontWeight.w600, color: AppColors.ink)),
          ],
        ),
      ),
    );
  }
}

/// Multi-color Google "G" mark, drawn from scratch (no external assets).
class _GoogleG extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final r = size.width / 2;
    final c = Offset(size.width / 2, size.height / 2);
    final stroke = r * 0.36;

    Paint arc(Color color) => Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.butt;

    final rect = Rect.fromCircle(center: c, radius: r - stroke / 2);
    // Blue top-right / right
    canvas.drawArc(rect, -1.05, 1.0, false, arc(const Color(0xFF4285F4)));
    // Green bottom-right
    canvas.drawArc(rect, -0.05, 1.4, false, arc(const Color(0xFF34A853)));
    // Yellow bottom-left
    canvas.drawArc(rect, 1.45, 1.0, false, arc(const Color(0xFFFBBC04)));
    // Red top-left
    canvas.drawArc(rect, 2.55, 1.6, false, arc(const Color(0xFFEA4335)));

    // horizontal bar of "G"
    final barY = c.dy + stroke * 0.05;
    final barRect = Rect.fromLTWH(c.dx - stroke * 0.15, barY - stroke * 0.18,
        r * 0.95, stroke * 0.65);
    canvas.drawRect(barRect, Paint()..color = const Color(0xFF4285F4));
  }

  @override
  bool shouldRepaint(covariant _GoogleG old) => false;
}
