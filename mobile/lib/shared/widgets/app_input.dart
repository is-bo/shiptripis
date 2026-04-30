import 'package:flutter/material.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';

class AppInput extends StatelessWidget {
  const AppInput({
    super.key,
    required this.controller,
    required this.hint,
    this.label,
    this.icon,
    this.obscure = false,
    this.suffix,
    this.keyboardType,
    this.onChanged,
    this.autofocus = false,
  });

  final TextEditingController controller;
  final String hint;
  final String? label;
  final IconData? icon;
  final bool obscure;
  final Widget? suffix;
  final TextInputType? keyboardType;
  final ValueChanged<String>? onChanged;
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (label != null) ...[
          Text(label!.toUpperCase(), style: AppType.eyebrow()),
          const SizedBox(height: 8),
        ],
        TextField(
          controller: controller,
          obscureText: obscure,
          keyboardType: keyboardType,
          autofocus: autofocus,
          onChanged: onChanged,
          style: AppType.body(15, w: FontWeight.w500),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: AppType.body(14, color: AppColors.inkMute),
            prefixIcon: icon == null
                ? null
                : Padding(
                    padding: const EdgeInsets.only(left: 14, right: 8),
                    child: Icon(icon, size: 18, color: AppColors.inkMute),
                  ),
            prefixIconConstraints: const BoxConstraints(minWidth: 0),
            suffixIcon: suffix,
            filled: true,
            fillColor: AppColors.parchmentSoft,
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 14, vertical: 16),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(AppRadius.md),
              borderSide: const BorderSide(color: AppColors.hairline, width: 1.2),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(AppRadius.md),
              borderSide: const BorderSide(color: AppColors.ink, width: 1.4),
            ),
          ),
        ),
      ],
    );
  }
}

/// Big tappable + / - stepper used for weight, kg, count.
class NumberStepper extends StatelessWidget {
  const NumberStepper({
    super.key,
    required this.value,
    required this.onChanged,
    this.min = 1,
    this.max = 25,
    this.unit = "kg",
    this.step = 1,
  });

  final int value;
  final ValueChanged<int> onChanged;
  final int min;
  final int max;
  final String unit;
  final int step;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.pill),
        border: Border.all(color: AppColors.hairline, width: 1.2),
      ),
      child: Row(
        children: [
          _btn(
            icon: Icons.remove_rounded,
            onTap: value > min ? () => onChanged(value - step) : null,
          ),
          Expanded(
            child: Center(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic,
                children: [
                  Text("$value",
                      style: AppType.display(28, w: FontWeight.w500)),
                  const SizedBox(width: 6),
                  Text(unit,
                      style:
                          AppType.mono(13, color: AppColors.inkMute, w: FontWeight.w600)),
                ],
              ),
            ),
          ),
          _btn(
            icon: Icons.add_rounded,
            onTap: value < max ? () => onChanged(value + step) : null,
          ),
        ],
      ),
    );
  }

  Widget _btn({required IconData icon, VoidCallback? onTap}) {
    final disabled = onTap == null;
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: AppDurations.fast,
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: disabled ? AppColors.parchmentDeep : AppColors.ink,
          shape: BoxShape.circle,
        ),
        child: Icon(
          icon,
          color: disabled ? AppColors.inkMute : AppColors.parchment,
          size: 20,
        ),
      ),
    );
  }
}
