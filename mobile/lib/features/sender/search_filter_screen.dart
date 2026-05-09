import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/trips/trips_providers.dart';
import '../../core/trips/trips_repository.dart';
import '../../shared/widgets/airport_picker.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/inline_calendar.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class SearchFilterScreen extends ConsumerStatefulWidget {
  const SearchFilterScreen({super.key});
  @override
  ConsumerState<SearchFilterScreen> createState() => _SearchFilterScreenState();
}

class _SearchFilterScreenState extends ConsumerState<SearchFilterScreen> {
  Airport? _from;
  Airport? _to;
  DateTime _date = DateTime.now().add(const Duration(days: 3));
  bool _showCalendar = false;
  String _type = 'Documents';
  int _kg = 3;

  Future<void> _pickAirport(bool isOrigin, List<Airport> airports) async {
    final cur = isOrigin ? _from : _to;
    final country = cur?.country ?? (isOrigin ? 'DZ' : 'FR');
    final picked = await showAirportPicker(
      context,
      airports: airports,
      country: country,
      currentIata: cur?.iata ?? '',
      onCountryChanged: (_) {},
    );
    if (picked == null) return;
    setState(() {
      if (isOrigin) {
        _from = picked;
        if (_to?.country == picked.country) _to = null;
      } else {
        _to = picked;
        if (_from?.country == picked.country) _from = null;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final airportsAsync = ref.watch(airportsProvider(null));
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: airportsAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (_, _) => Center(
            child: TextButton(
              onPressed: () => ref.invalidate(airportsProvider(null)),
              child: const Text('Retry'),
            ),
          ),
          data: (airports) {
            _from ??= airports.firstWhere(
              (a) => a.country == 'DZ',
              orElse: () => airports.first,
            );
            _to ??= airports.firstWhere(
              (a) => a.country == 'FR',
              orElse: () => airports.last,
            );
            return Column(
              children: [
                _topBar(context),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(
                        AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
                    children: [
                      Text("Find a traveler", style: AppType.eyebrow()),
                      const SizedBox(height: 6),
                      Text("Where & when?",
                          style: AppType.display(34, w: FontWeight.w400, height: 1)),
                      const SizedBox(height: AppSpacing.x6),
                      _routeBlock(airports),
                      const SizedBox(height: AppSpacing.x6),
                      _dateBlock(),
                      const SizedBox(height: AppSpacing.x6),
                      _typeBlock(),
                      const SizedBox(height: AppSpacing.x6),
                      _weightBlock(),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(
                      AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
                  child: PrimaryButton(
                    label: "Find travelers",
                    icon: Icons.search_rounded,
                    onTap: () => context.pop(),
                    expand: true,
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _topBar(BuildContext context) {
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
          const StampChip(label: "DZ ⇆ FR ONLY", color: AppColors.emerald),
        ],
      ),
    );
  }

  Widget _routeBlock(List<Airport> airports) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text("ROUTE", style: AppType.eyebrow()),
          const SizedBox(height: 12),
          _AirportTile(
            label: "FROM",
            airport: _from!,
            onTap: () => _pickAirport(true, airports),
          ),
          const SizedBox(height: 8),
          Center(
            child: GestureDetector(
              onTap: () => setState(() {
                final tmp = _from;
                _from = _to;
                _to = tmp;
              }),
              child: Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: AppColors.ink,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: const Icon(Icons.swap_vert_rounded,
                    color: AppColors.parchment, size: 18),
              ),
            ),
          ),
          const SizedBox(height: 8),
          _AirportTile(
            label: "TO",
            airport: _to!,
            onTap: () => _pickAirport(false, airports),
          ),
        ],
      ),
    );
  }

  Widget _dateBlock() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("WHEN", style: AppType.eyebrow()),
        const SizedBox(height: 10),
        GestureDetector(
          onTap: () => setState(() => _showCalendar = !_showCalendar),
          child: Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
            decoration: BoxDecoration(
              color: AppColors.parchmentSoft,
              borderRadius: BorderRadius.circular(AppRadius.md),
              border: Border.all(color: AppColors.hairline, width: 1.2),
            ),
            child: Row(
              children: [
                const Icon(Icons.calendar_today_rounded,
                    size: 18, color: AppColors.ink),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(formatDate(_date),
                      style: AppType.mono(15, w: FontWeight.w700)),
                ),
                AnimatedRotation(
                  duration: AppDurations.fast,
                  turns: _showCalendar ? 0.5 : 0,
                  child: const Icon(Icons.expand_more_rounded,
                      color: AppColors.inkMute),
                ),
              ],
            ),
          ),
        ),
        AnimatedSize(
          duration: AppDurations.med,
          curve: kAppCurve,
          child: _showCalendar
              ? Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: InlineCalendar(
                    selected: _date,
                    onSelect: (d) => setState(() {
                      _date = d;
                      _showCalendar = false;
                    }),
                    minDate: DateTime.now(),
                    maxDate: DateTime.now().add(const Duration(days: 365)),
                  ),
                )
              : const SizedBox.shrink(),
        ),
      ],
    );
  }

  Widget _typeBlock() {
    final options = ["Documents", "Small box", "Electronics", "Clothing"];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("ITEM TYPE", style: AppType.eyebrow()),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: options
              .map((o) => _Choice(label: o, selected: _type == o, onTap: () => setState(() => _type = o)))
              .toList(),
        ),
      ],
    );
  }

  Widget _weightBlock() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("WEIGHT", style: AppType.eyebrow()),
        const SizedBox(height: 10),
        NumberStepper(
          value: _kg,
          onChanged: (v) => setState(() => _kg = v),
          min: 1,
          max: 25,
          unit: "kg",
        ),
      ],
    );
  }
}

class _AirportTile extends StatelessWidget {
  const _AirportTile({required this.label, required this.airport, required this.onTap});
  final String label;
  final Airport airport;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
        decoration: BoxDecoration(
          color: AppColors.parchment,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: AppColors.hairline, width: 1.2),
        ),
        child: Row(
          children: [
            CountryPill(code: airport.country, label: airport.country, dense: true),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(label, style: AppType.eyebrow()),
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                          color: AppColors.ink,
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(airport.iata,
                            style: AppType.mono(10,
                                color: AppColors.parchment, w: FontWeight.w700)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text("${airport.city} · ${airport.name}",
                      style: AppType.body(13, w: FontWeight.w600),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis),
                ],
              ),
            ),
            const Icon(Icons.unfold_more_rounded, color: AppColors.inkMute),
          ],
        ),
      ),
    );
  }
}

class _Choice extends StatelessWidget {
  const _Choice({required this.label, required this.selected, required this.onTap});
  final String label;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: AppDurations.fast,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: selected ? AppColors.ink : AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.pill),
          border: Border.all(
            color: selected ? AppColors.ink : AppColors.hairline,
          ),
        ),
        child: Text(label,
            style: AppType.body(12.5,
                color: selected ? AppColors.parchment : AppColors.ink,
                w: FontWeight.w600)),
      ),
    );
  }
}
