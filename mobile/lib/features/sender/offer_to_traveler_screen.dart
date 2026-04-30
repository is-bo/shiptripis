import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/mock/mock_data.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

/// Offer flow when sender taps "Request" on a specific traveler.
/// No route block (route is the traveler's), no weight slider — uses NumberStepper.
class OfferToTravelerScreen extends StatefulWidget {
  const OfferToTravelerScreen({super.key, required this.traveler});
  final MockTraveler traveler;

  @override
  State<OfferToTravelerScreen> createState() => _OfferToTravelerScreenState();
}

class _OfferToTravelerScreenState extends State<OfferToTravelerScreen> {
  String _itemType = "Documents";
  int _kg = 2;
  final _itemDesc = TextEditingController(text: "Folder of contracts");
  final _priceCtl = TextEditingController(text: "4500");
  final _pickupCtl = TextEditingController();
  final _dropCtl = TextEditingController();

  @override
  void dispose() {
    _itemDesc.dispose();
    _priceCtl.dispose();
    _pickupCtl.dispose();
    _dropCtl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.traveler;
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
                  Text("Send to", style: AppType.eyebrow()),
                  const SizedBox(height: 6),
                  Text(t.name,
                      style: AppType.display(34, w: FontWeight.w400, height: 1)),
                  const SizedBox(height: AppSpacing.x4),
                  _travelerCard(t)
                      .animate()
                      .fadeIn(duration: 280.ms)
                      .slideY(begin: 0.05),
                  const SizedBox(height: AppSpacing.x6),
                  _label("Item type"),
                  const SizedBox(height: 10),
                  _itemTypes(),
                  const SizedBox(height: AppSpacing.x5),
                  _label("Weight"),
                  const SizedBox(height: 10),
                  NumberStepper(
                    value: _kg,
                    onChanged: (v) => setState(() => _kg = v),
                    min: 1,
                    max: t.kgFree,
                    unit: "kg",
                  ),
                  const SizedBox(height: 6),
                  Text("Traveler has ${t.kgFree} kg free",
                      style: AppType.body(11.5,
                          color: AppColors.inkMute, w: FontWeight.w500)),
                  const SizedBox(height: AppSpacing.x5),
                  AppInput(
                    controller: _itemDesc,
                    label: "Description",
                    hint: "What's inside?",
                    icon: Icons.inventory_2_outlined,
                  ),
                  const SizedBox(height: AppSpacing.x4),
                  AppInput(
                    controller: _pickupCtl,
                    label: "Pickup point (${t.origin})",
                    hint: "Neighborhood, landmark…",
                    icon: Icons.place_outlined,
                  ),
                  const SizedBox(height: AppSpacing.x4),
                  AppInput(
                    controller: _dropCtl,
                    label: "Drop-off point (${t.dest})",
                    hint: "Address or area",
                    icon: Icons.flag_outlined,
                  ),
                  const SizedBox(height: AppSpacing.x4),
                  AppInput(
                    controller: _priceCtl,
                    label: "Your offer (DZD)",
                    hint: "Amount",
                    icon: Icons.payments_outlined,
                    keyboardType: TextInputType.number,
                  ),
                  const SizedBox(height: AppSpacing.x6),
                  _summary(t),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
              child: PrimaryButton(
                label: "Send offer",
                icon: Icons.send_rounded,
                expand: true,
                color: AppColors.sun,
                fg: AppColors.ink,
                onTap: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      backgroundColor: AppColors.ink,
                      content: Text("Offer sent to ${t.name}",
                          style: AppType.body(13.5,
                              color: AppColors.parchment, w: FontWeight.w500)),
                    ),
                  );
                  context.pop();
                },
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
          StampChip(label: "DIRECT OFFER", color: AppColors.terracotta),
        ],
      ),
    );
  }

  Widget _travelerCard(MockTraveler t) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: AppColors.ink,
              borderRadius: BorderRadius.circular(14),
            ),
            alignment: Alignment.center,
            child: Text(t.avatar,
                style: AppType.display(16,
                    color: AppColors.parchment, w: FontWeight.w500)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(t.name,
                    style: AppType.body(15, w: FontWeight.w700)),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Text("${t.origin} → ${t.dest}",
                        style: AppType.mono(12,
                            color: AppColors.inkSoft, w: FontWeight.w600)),
                    const SizedBox(width: 8),
                    Container(
                        width: 3, height: 3, color: AppColors.inkMute),
                    const SizedBox(width: 8),
                    Text(t.date,
                        style: AppType.mono(12,
                            color: AppColors.inkMute, w: FontWeight.w500)),
                  ],
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text("${t.pricePerKg}",
                  style: AppType.mono(15, w: FontWeight.w700)),
              Text("DZD/kg",
                  style: AppType.body(10.5, color: AppColors.inkMute)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _itemTypes() {
    final types = ["Documents", "Small box", "Electronics", "Clothing"];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: types
          .map((t) => GestureDetector(
                onTap: () => setState(() => _itemType = t),
                child: AnimatedContainer(
                  duration: AppDurations.fast,
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: _itemType == t
                        ? AppColors.ink
                        : AppColors.parchmentSoft,
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                    border: Border.all(
                        color: _itemType == t
                            ? AppColors.ink
                            : AppColors.hairline),
                  ),
                  child: Text(t,
                      style: AppType.body(12.5,
                          w: FontWeight.w600,
                          color: _itemType == t
                              ? AppColors.parchment
                              : AppColors.ink)),
                ),
              ))
          .toList(),
    );
  }

  Widget _summary(MockTraveler t) {
    final base = int.tryParse(_priceCtl.text) ?? 0;
    final commission = (base * 0.25).round();
    final total = base + commission;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        children: [
          _row("Your offer", "${_fmt(base)} DZD"),
          _row("Commission · 25%", "${_fmt(commission)} DZD"),
          const SizedBox(height: 4),
          Container(height: 1, color: AppColors.parchment.withValues(alpha: 0.2)),
          const SizedBox(height: 8),
          _row("Total in escrow", "${_fmt(total)} DZD", strong: true),
        ],
      ),
    );
  }

  Widget _row(String l, String v, {bool strong = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Text(l, style: AppType.body(13, color: AppColors.parchmentDeep)),
          const Spacer(),
          Text(v,
              style: AppType.mono(strong ? 16 : 13,
                  color: AppColors.parchment,
                  w: strong ? FontWeight.w700 : FontWeight.w500)),
        ],
      ),
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
