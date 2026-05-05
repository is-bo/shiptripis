import 'package:flutter/material.dart';
import '../../core/theme/tokens.dart';

/// A boarding-pass shaped card with a perforated notch on each side.
class BoardingCard extends StatelessWidget {
  const BoardingCard({
    super.key,
    required this.child,
    this.color,
    this.onTap,
    this.padding = const EdgeInsets.all(AppSpacing.x5),
    this.notchPosition = 0.62,
    this.elevation = AppShadows.card,
  });

  final Widget child;
  final Color? color;
  final VoidCallback? onTap;
  final EdgeInsetsGeometry padding;
  final double notchPosition;
  final List<BoxShadow> elevation;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: PhysicalShape(
        clipper: _BoardingClipper(notch: notchPosition),
        color: color ?? AppColors.parchmentSoft,
        elevation: 0,
        child: Container(
          decoration: BoxDecoration(boxShadow: elevation),
          child: ClipPath(
            clipper: _BoardingClipper(notch: notchPosition),
            child: Padding(padding: padding, child: child),
          ),
        ),
      ),
    );
  }
}

class _BoardingClipper extends CustomClipper<Path> {
  _BoardingClipper({required this.notch});
  final double notch;

  @override
  Path getClip(Size size) {
    const r = AppRadius.lg;
    const notchR = 10.0;
    final ny = size.height * notch;
    final p = Path();
    p.moveTo(r, 0);
    p.lineTo(size.width - r, 0);
    p.quadraticBezierTo(size.width, 0, size.width, r);
    p.lineTo(size.width, ny - notchR);
    p.arcToPoint(Offset(size.width, ny + notchR),
        radius: const Radius.circular(notchR), clockwise: false);
    p.lineTo(size.width, size.height - r);
    p.quadraticBezierTo(size.width, size.height, size.width - r, size.height);
    p.lineTo(r, size.height);
    p.quadraticBezierTo(0, size.height, 0, size.height - r);
    p.lineTo(0, ny + notchR);
    p.arcToPoint(Offset(0, ny - notchR),
        radius: const Radius.circular(notchR), clockwise: false);
    p.lineTo(0, r);
    p.quadraticBezierTo(0, 0, r, 0);
    p.close();
    return p;
  }

  @override
  bool shouldReclip(covariant _BoardingClipper old) => old.notch != notch;
}

/// A horizontal dashed divider — for boarding pass perforation lines.
class DashedDivider extends StatelessWidget {
  const DashedDivider({super.key, this.color, this.height = 1, this.dash = 4, this.gap = 4});
  final Color? color;
  final double height;
  final double dash;
  final double gap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      child: LayoutBuilder(builder: (ctx, c) {
        final count = (c.maxWidth / (dash + gap)).floor();
        return Row(
          children: List.generate(
            count,
            (_) => Padding(
              padding: EdgeInsets.only(right: gap),
              child: Container(
                width: dash,
                height: height,
                color: color ?? AppColors.hairline,
              ),
            ),
          ),
        );
      }),
    );
  }
}
