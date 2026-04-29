import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class CreateTripScreen extends StatefulWidget {
  const CreateTripScreen({super.key});
  @override
  State<CreateTripScreen> createState() => _CreateTripScreenState();
}

class _CreateTripScreenState extends State<CreateTripScreen> {
  String _from = 'DZ';
  String _to = 'FR';
  double _kg = 8;
  final _accepted = <String>{"Documents", "Small box", "Clothing"};
  bool _ticketAdded = false;

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
                  Text("New trip", style: AppType.eyebrow()),
                  const SizedBox(height: 6),
                  Text("List your\nnext flight.",
                      style: AppType.display(34, w: FontWeight.w400, height: 1)),
                  const SizedBox(height: AppSpacing.x6),
                  _routeBlock(),
                  const SizedBox(height: AppSpacing.x6),
                  _datesRow(),
                  const SizedBox(height: AppSpacing.x6),
                  _capacity(),
                  const SizedBox(height: AppSpacing.x6),
                  _acceptedTypes(),
                  const SizedBox(height: AppSpacing.x6),
                  _ticketUpload(),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
              child: PrimaryButton(
                label: "Submit for review",
                icon: Icons.flight_takeoff_rounded,
                expand: true,
                color: AppColors.emerald,
                onTap: () => context.pop(),
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
          StampChip(label: "ADMIN APPROVAL · ~24H", color: AppColors.gold, angle: 0.04),
        ],
      ),
    );
  }

  Widget _routeBlock() {
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
          const SizedBox(height: 10),
          Row(
            children: [
              CountryPill(code: _from, label: _from == 'DZ' ? "Algeria" : "France"),
              const Spacer(),
              GestureDetector(
                onTap: () => setState(() {
                  final tmp = _from;
                  _from = _to;
                  _to = tmp;
                }),
                child: Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: AppColors.ink,
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                  ),
                  child: const Icon(Icons.swap_horiz_rounded,
                      color: AppColors.parchment, size: 18),
                ),
              ),
              const Spacer(),
              CountryPill(code: _to, label: _to == 'FR' ? "France" : "Algeria"),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _miniInput("Origin city", "Algiers · HOU")),
              const SizedBox(width: 10),
              Expanded(child: _miniInput("Destination city", "Paris · CDG")),
            ],
          ),
        ],
      ),
    );
  }

  Widget _datesRow() {
    return Row(
      children: [
        Expanded(
          child: _bigField(
            label: "DEPARTURE",
            value: "May 04, 2026",
            icon: Icons.calendar_today_rounded,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _bigField(
            label: "FLIGHT NO.",
            value: "AH 1004",
            icon: Icons.confirmation_num_outlined,
          ),
        ),
      ],
    );
  }

  Widget _capacity() {
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
          Row(
            children: [
              Text("AVAILABLE CAPACITY", style: AppType.eyebrow()),
              const Spacer(),
              Text("${_kg.toStringAsFixed(0)} kg",
                  style: AppType.mono(15, w: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 4),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: AppColors.emerald,
              inactiveTrackColor: AppColors.hairline,
              thumbColor: AppColors.terracotta,
              overlayColor: AppColors.terracotta.withValues(alpha: 0.15),
              trackHeight: 4,
              thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 9),
            ),
            child: Slider(
              value: _kg,
              min: 1,
              max: 25,
              divisions: 24,
              onChanged: (v) => setState(() => _kg = v),
            ),
          ),
        ],
      ),
    );
  }

  Widget _acceptedTypes() {
    final types = ["Documents", "Small box", "Electronics", "Clothing", "Food"];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("ACCEPTED ITEMS", style: AppType.eyebrow()),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: types.map((t) {
            final selected = _accepted.contains(t);
            return GestureDetector(
              onTap: () => setState(() {
                selected ? _accepted.remove(t) : _accepted.add(t);
              }),
              child: AnimatedContainer(
                duration: AppDurations.fast,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: selected ? AppColors.emerald : AppColors.parchmentSoft,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                  border: Border.all(
                    color: selected ? AppColors.emerald : AppColors.hairline,
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      selected ? Icons.check_rounded : Icons.add_rounded,
                      size: 14,
                      color: selected ? AppColors.parchment : AppColors.inkMute,
                    ),
                    const SizedBox(width: 6),
                    Text(t,
                        style: AppType.body(12.5,
                            color: selected ? AppColors.parchment : AppColors.ink,
                            w: FontWeight.w600)),
                  ],
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }

  Widget _ticketUpload() {
    return GestureDetector(
      onTap: () => setState(() => _ticketAdded = !_ticketAdded),
      child: AnimatedContainer(
        duration: AppDurations.med,
        padding: const EdgeInsets.all(AppSpacing.x4),
        decoration: BoxDecoration(
          color: _ticketAdded ? AppColors.emerald.withValues(alpha: 0.08) : AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(
            color: _ticketAdded ? AppColors.emerald : AppColors.hairline,
            width: 1.4,
          ),
        ),
        child: Row(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: _ticketAdded
                    ? AppColors.emerald
                    : AppColors.ink.withValues(alpha: 0.06),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                _ticketAdded ? Icons.check_rounded : Icons.upload_file_rounded,
                color: _ticketAdded ? AppColors.parchment : AppColors.ink,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _ticketAdded ? "Ticket attached" : "Upload your boarding pass",
                    style: AppType.body(14.5, w: FontWeight.w700),
                  ),
                  Text(
                    _ticketAdded
                        ? "boarding-AH1004.pdf · 412 KB"
                        : "Required · PDF or photo",
                    style: AppType.body(12, color: AppColors.inkMute),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _bigField({required String label, required String value, required IconData icon}) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(label, style: AppType.eyebrow()),
              const Spacer(),
              Icon(icon, size: 14, color: AppColors.inkMute),
            ],
          ),
          const SizedBox(height: 6),
          Text(value, style: AppType.mono(14, w: FontWeight.w700)),
        ],
      ),
    );
  }

  Widget _miniInput(String hint, String initial) {
    return TextFormField(
      initialValue: initial,
      style: AppType.body(13, w: FontWeight.w500),
      decoration: InputDecoration(
        hintText: hint,
        isDense: true,
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        filled: true,
        fillColor: AppColors.parchment,
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.hairline),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.ink),
        ),
      ),
    );
  }
}
