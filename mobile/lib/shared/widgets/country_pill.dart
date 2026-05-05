import 'package:country_flags/country_flags.dart';
import 'package:flutter/material.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';

class CountryPill extends StatelessWidget {
  const CountryPill({super.key, required this.code, required this.label, this.dense = false});
  final String code; // 'DZ' or 'FR'
  final String label;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final flagH = dense ? 12.0 : 14.0;
    final flagW = dense ? 18.0 : 22.0;
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: dense ? 10 : 14,
        vertical: dense ? 6 : 9,
      ),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.pill),
        border: Border.all(color: AppColors.hairline, width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: SizedBox(
              height: flagH,
              width: flagW,
              child: CountryFlag.fromCountryCode(code),
            ),
          ),
          SizedBox(width: dense ? 6 : 8),
          Text(label,
              style: AppType.mono(dense ? 11 : 12.5, w: FontWeight.w600)
                  .copyWith(letterSpacing: 0.8)),
        ],
      ),
    );
  }
}
