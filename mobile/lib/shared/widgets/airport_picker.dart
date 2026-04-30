import 'package:flutter/material.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../mock/airports.dart';
import 'country_pill.dart';

Future<Airport?> showAirportPicker(
  BuildContext context, {
  required String country,
  required String currentIata,
  required ValueChanged<String> onCountryChanged,
}) {
  return showModalBottomSheet<Airport>(
    context: context,
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    builder: (_) => _AirportPickerSheet(
      country: country,
      currentIata: currentIata,
      onCountryChanged: onCountryChanged,
    ),
  );
}

class _AirportPickerSheet extends StatefulWidget {
  const _AirportPickerSheet({
    required this.country,
    required this.currentIata,
    required this.onCountryChanged,
  });
  final String country;
  final String currentIata;
  final ValueChanged<String> onCountryChanged;

  @override
  State<_AirportPickerSheet> createState() => _AirportPickerSheetState();
}

class _AirportPickerSheetState extends State<_AirportPickerSheet> {
  late String _country = widget.country;
  String _query = "";

  @override
  Widget build(BuildContext context) {
    final list = airportsByCountry(_country)
        .where((a) =>
            _query.isEmpty ||
            a.city.toLowerCase().contains(_query.toLowerCase()) ||
            a.name.toLowerCase().contains(_query.toLowerCase()) ||
            a.iata.toLowerCase().contains(_query.toLowerCase()))
        .toList();

    return DraggableScrollableSheet(
      initialChildSize: 0.85,
      minChildSize: 0.5,
      maxChildSize: 0.95,
      builder: (_, scroll) => Container(
        decoration: const BoxDecoration(
          color: AppColors.parchment,
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
        ),
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.hairline,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, 4, AppSpacing.x6, AppSpacing.x4),
              child: Row(
                children: [
                  Text("Choose airport",
                      style: AppType.display(22, w: FontWeight.w500)),
                  const Spacer(),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close_rounded),
                    style: IconButton.styleFrom(
                      backgroundColor: AppColors.parchmentSoft,
                      shape: const CircleBorder(),
                    ),
                  ),
                ],
              ),
            ),
            // country toggle
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
              child: Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: AppColors.parchmentSoft,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                  border: Border.all(color: AppColors.hairline),
                ),
                child: Row(
                  children: [
                    _seg('DZ', 'Algeria'),
                    _seg('FR', 'France'),
                  ],
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.x4),
            // search
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
              child: TextField(
                onChanged: (v) => setState(() => _query = v),
                style: AppType.body(14, w: FontWeight.w500),
                decoration: InputDecoration(
                  hintText: "Search city, airport or IATA",
                  hintStyle: AppType.body(13, color: AppColors.inkMute),
                  prefixIcon: const Icon(Icons.search_rounded,
                      color: AppColors.inkMute, size: 20),
                  filled: true,
                  fillColor: AppColors.parchmentSoft,
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    borderSide: const BorderSide(color: AppColors.hairline),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    borderSide: const BorderSide(color: AppColors.ink),
                  ),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.x3),
            Expanded(
              child: ListView.separated(
                controller: scroll,
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.x6, 4, AppSpacing.x6, AppSpacing.x6),
                itemCount: list.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (_, i) {
                  final a = list[i];
                  final selected = a.iata == widget.currentIata && _country == widget.country;
                  return GestureDetector(
                    onTap: () => Navigator.pop(context, a),
                    child: AnimatedContainer(
                      duration: AppDurations.fast,
                      padding: const EdgeInsets.all(AppSpacing.x4),
                      decoration: BoxDecoration(
                        color: selected ? AppColors.ink : AppColors.parchmentSoft,
                        borderRadius: BorderRadius.circular(AppRadius.md),
                        border: Border.all(
                          color: selected ? AppColors.ink : AppColors.hairline,
                        ),
                      ),
                      child: Row(
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: selected
                                  ? AppColors.sun
                                  : AppColors.parchment,
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(a.iata,
                                style: AppType.mono(13,
                                    w: FontWeight.w700,
                                    color: AppColors.ink)),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(a.city,
                                    style: AppType.body(15,
                                        w: FontWeight.w700,
                                        color: selected
                                            ? AppColors.parchment
                                            : AppColors.ink)),
                                Text(a.name,
                                    style: AppType.body(12,
                                        color: selected
                                            ? AppColors.parchmentDeep
                                            : AppColors.inkMute,
                                        w: FontWeight.w500)),
                              ],
                            ),
                          ),
                          if (selected)
                            const Icon(Icons.check_circle_rounded,
                                color: AppColors.sun, size: 22),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _seg(String code, String label) {
    final selected = _country == code;
    return Expanded(
      child: GestureDetector(
        onTap: () {
          setState(() => _country = code);
          widget.onCountryChanged(code);
        },
        child: AnimatedContainer(
          duration: AppDurations.fast,
          padding: const EdgeInsets.symmetric(vertical: 11),
          decoration: BoxDecoration(
            color: selected ? AppColors.ink : Colors.transparent,
            borderRadius: BorderRadius.circular(AppRadius.pill),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              CountryPill(code: code, label: label, dense: true),
            ],
          ),
        ),
      ),
    );
  }
}
