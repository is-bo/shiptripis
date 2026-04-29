import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class SearchFilterScreen extends StatefulWidget {
  const SearchFilterScreen({super.key});
  @override
  State<SearchFilterScreen> createState() => _SearchFilterScreenState();
}

class _SearchFilterScreenState extends State<SearchFilterScreen> {
  String _from = 'DZ';
  String _to = 'FR';
  String _type = 'Documents';
  double _kg = 3;
  String _when = "This week";

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Column(
          children: [
            _topBar(context),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
                children: [
                  Text("Step 02 / 03", style: AppType.eyebrow()),
                  const SizedBox(height: 8),
                  Text("Where & when?",
                      style: AppType.display(34, w: FontWeight.w400, height: 1)),
                  const SizedBox(height: AppSpacing.x6),
                  _routeBlock(),
                  const SizedBox(height: AppSpacing.x6),
                  _whenBlock(),
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
              child: Row(
                children: [
                  Expanded(
                    child: PrimaryButton(
                      label: "Find travelers",
                      icon: Icons.search_rounded,
                      onTap: () => context.pop(),
                      expand: true,
                    ),
                  ),
                ],
              ),
            ),
          ],
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
          StampChip(label: "DZ ⇆ FR ONLY", color: AppColors.emerald),
        ],
      ),
    );
  }

  Widget _routeBlock() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Route", style: AppType.eyebrow()),
        const SizedBox(height: AppSpacing.x3),
        Container(
          padding: const EdgeInsets.all(AppSpacing.x4),
          decoration: BoxDecoration(
            color: AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Column(
            children: [
              _CountrySelectRow(
                label: "FROM",
                code: _from,
                onTap: () => setState(() {
                  final tmp = _from;
                  _from = _to;
                  _to = tmp;
                }),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(child: Container(height: 1, color: AppColors.hairline)),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: GestureDetector(
                      onTap: () => setState(() {
                        final tmp = _from;
                        _from = _to;
                        _to = tmp;
                      }),
                      child: Container(
                        width: 32,
                        height: 32,
                        decoration: BoxDecoration(
                          color: AppColors.ink,
                          borderRadius: BorderRadius.circular(AppRadius.pill),
                        ),
                        child: const Icon(Icons.swap_vert_rounded,
                            color: AppColors.parchment, size: 18),
                      ),
                    ),
                  ),
                  Expanded(child: Container(height: 1, color: AppColors.hairline)),
                ],
              ),
              const SizedBox(height: 8),
              _CountrySelectRow(
                label: "TO",
                code: _to,
                onTap: () => setState(() {
                  final tmp = _from;
                  _from = _to;
                  _to = tmp;
                }),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _whenBlock() {
    final options = ["Today", "This week", "Next week", "Custom"];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("When", style: AppType.eyebrow()),
        const SizedBox(height: AppSpacing.x3),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: options
              .map((o) => _Choice(label: o, selected: _when == o, onTap: () => setState(() => _when = o)))
              .toList(),
        ),
      ],
    );
  }

  Widget _typeBlock() {
    final options = ["Documents", "Small box", "Electronics", "Clothing", "Food"];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Item type", style: AppType.eyebrow()),
        const SizedBox(height: AppSpacing.x3),
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
        Row(
          children: [
            Text("Weight", style: AppType.eyebrow()),
            const Spacer(),
            Text("${_kg.toStringAsFixed(0)} kg",
                style: AppType.mono(13, w: FontWeight.w700)),
          ],
        ),
        const SizedBox(height: AppSpacing.x2),
        SliderTheme(
          data: SliderTheme.of(context).copyWith(
            activeTrackColor: AppColors.ink,
            inactiveTrackColor: AppColors.hairline,
            thumbColor: AppColors.terracotta,
            overlayColor: AppColors.terracotta.withValues(alpha: 0.15),
            trackHeight: 4,
            thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 9),
          ),
          child: Slider(
            value: _kg,
            min: 1,
            max: 20,
            divisions: 19,
            onChanged: (v) => setState(() => _kg = v),
          ),
        ),
      ],
    ).animate().fadeIn(delay: 100.ms);
  }
}

class _CountrySelectRow extends StatelessWidget {
  const _CountrySelectRow({required this.label, required this.code, required this.onTap});
  final String label;
  final String code;
  final VoidCallback onTap;

  String get _name => code == 'DZ' ? "Algeria" : "France";
  String get _city => code == 'DZ' ? "Algiers · Oran · Constantine" : "Paris · Lyon · Marseille";

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 60,
          child: Text(label,
              style: AppType.eyebrow().copyWith(letterSpacing: 1.6)),
        ),
        const SizedBox(width: 8),
        CountryPill(code: code, label: _name),
        const SizedBox(width: 10),
        Expanded(
          child: Text(_city,
              style: AppType.body(11.5, color: AppColors.inkMute, w: FontWeight.w500),
              overflow: TextOverflow.ellipsis),
        ),
      ],
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
