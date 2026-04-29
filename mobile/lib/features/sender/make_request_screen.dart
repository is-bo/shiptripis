import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/boarding_card.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

enum _RequestType { delivery, product }

class MakeRequestScreen extends StatefulWidget {
  const MakeRequestScreen({super.key});
  @override
  State<MakeRequestScreen> createState() => _MakeRequestScreenState();
}

class _MakeRequestScreenState extends State<MakeRequestScreen> {
  _RequestType _type = _RequestType.delivery;
  String _itemType = "Documents";
  double _kg = 2;
  final _itemCtl = TextEditingController(text: "Argan oil");
  final _maxPriceCtl = TextEditingController(text: "12 000");

  @override
  void dispose() {
    _itemCtl.dispose();
    _maxPriceCtl.dispose();
    super.dispose();
  }

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
                  Text("New request", style: AppType.eyebrow()),
                  const SizedBox(height: 6),
                  Text(
                    _type == _RequestType.delivery
                        ? "Send something\nto a friend."
                        : "Buy from there,\nbring it here.",
                    style: AppType.display(34, w: FontWeight.w400, height: 1),
                  )
                      .animate(target: _type.index.toDouble())
                      .fadeIn(duration: 300.ms),
                  const SizedBox(height: AppSpacing.x6),
                  _typeToggle(),
                  const SizedBox(height: AppSpacing.x6),
                  if (_type == _RequestType.delivery) ..._deliveryFields()
                  else ..._productFields(),
                  const SizedBox(height: AppSpacing.x6),
                  _routeBlock(),
                  const SizedBox(height: AppSpacing.x6),
                  _photoUpload(),
                  const SizedBox(height: AppSpacing.x6),
                  _summary(),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
              child: PrimaryButton(
                label: "Post request",
                icon: Icons.send_rounded,
                expand: true,
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
          StampChip(label: "ESCROW PROTECTED", color: AppColors.emerald),
        ],
      ),
    );
  }

  Widget _typeToggle() {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.pill),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          _toggleSeg(_RequestType.delivery, "Send a parcel", Icons.inventory_2_outlined),
          _toggleSeg(_RequestType.product, "Buy a product", Icons.shopping_bag_outlined),
        ],
      ),
    );
  }

  Widget _toggleSeg(_RequestType t, String label, IconData icon) {
    final selected = _type == t;
    return Expanded(
      child: GestureDetector(
        onTap: () => setState(() => _type = t),
        child: AnimatedContainer(
          duration: AppDurations.fast,
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            color: selected ? AppColors.ink : Colors.transparent,
            borderRadius: BorderRadius.circular(AppRadius.pill),
          ),
          alignment: Alignment.center,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: selected ? AppColors.parchment : AppColors.ink),
              const SizedBox(width: 8),
              Text(label,
                  style: AppType.body(12.5,
                      w: FontWeight.w600,
                      color: selected ? AppColors.parchment : AppColors.ink)),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _deliveryFields() {
    final types = ["Documents", "Small box", "Electronics", "Clothing", "Food"];
    return [
      _label("Item type"),
      const SizedBox(height: 10),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: types
            .map((t) => _chip(t, _itemType == t, () => setState(() => _itemType = t)))
            .toList(),
      ),
      const SizedBox(height: AppSpacing.x5),
      _label("Weight"),
      Row(
        children: [
          Expanded(
            child: SliderTheme(
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
                max: 25,
                divisions: 24,
                onChanged: (v) => setState(() => _kg = v),
              ),
            ),
          ),
          Text("${_kg.toStringAsFixed(0)} kg",
              style: AppType.mono(14, w: FontWeight.w700)),
        ],
      ),
    ];
  }

  List<Widget> _productFields() {
    return [
      _label("Product"),
      const SizedBox(height: 10),
      _input(_itemCtl, "e.g. iPhone 15"),
      const SizedBox(height: AppSpacing.x4),
      _label("Max price (DZD)"),
      const SizedBox(height: 10),
      _input(_maxPriceCtl, "Maximum you'd pay"),
    ];
  }

  Widget _routeBlock() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _label("Route"),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(AppSpacing.x4),
          decoration: BoxDecoration(
            color: AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Column(
            children: [
              Row(
                children: [
                  const CountryPill(code: 'DZ', label: 'Algeria'),
                  const SizedBox(width: 8),
                  const Icon(Icons.arrow_forward_rounded, color: AppColors.inkMute, size: 18),
                  const SizedBox(width: 8),
                  const CountryPill(code: 'FR', label: 'France'),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: _miniInput(hint: "Pickup city", initial: "Algiers · Hydra"),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: _miniInput(hint: "Drop-off city", initial: "Paris · 13e"),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _photoUpload() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _label("Photo"),
        const SizedBox(height: 10),
        Container(
          height: 110,
          decoration: BoxDecoration(
            color: AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppColors.hairline, width: 1.4),
          ),
          child: CustomPaint(
            painter: _DashedRectPainter(),
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.add_a_photo_outlined, color: AppColors.inkMute),
                  const SizedBox(height: 8),
                  Text("Tap to add a photo",
                      style: AppType.body(13, color: AppColors.inkMute, w: FontWeight.w500)),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _summary() {
    final base = _type == _RequestType.delivery
        ? (_kg * 1800).toInt()
        : int.tryParse(_maxPriceCtl.text.replaceAll(' ', '')) ?? 0;
    final commission = (_type == _RequestType.delivery)
        ? (base * 0.25).round()
        : 2500 + _calcProductCommission(base);
    final total = base + commission;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        children: [
          _row("Base", "${_fmt(base)} DZD"),
          _row(
            _type == _RequestType.delivery ? "Commission · 25%" : "Base fee + commission",
            "${_fmt(commission)} DZD",
          ),
          const SizedBox(height: 4),
          DashedDivider(color: AppColors.parchment.withValues(alpha: 0.25)),
          const SizedBox(height: 8),
          _row("Total", "${_fmt(total)} DZD", strong: true),
        ],
      ),
    );
  }

  int _calcProductCommission(int price) {
    if (price < 30000) return 0;
    if (price < 55000) return (price * 0.07).round();
    if (price < 100000) return (price * 0.05).round();
    return (price * 0.03).round();
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

  Widget _chip(String l, bool selected, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: AppDurations.fast,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: selected ? AppColors.ink : AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.pill),
          border: Border.all(color: selected ? AppColors.ink : AppColors.hairline),
        ),
        child: Text(l,
            style: AppType.body(12.5,
                w: FontWeight.w600,
                color: selected ? AppColors.parchment : AppColors.ink)),
      ),
    );
  }

  Widget _input(TextEditingController c, String hint) {
    return TextField(
      controller: c,
      style: AppType.body(15, w: FontWeight.w500),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: AppType.body(14, color: AppColors.inkMute),
        filled: true,
        fillColor: AppColors.parchmentSoft,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.hairline),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.ink, width: 1.4),
        ),
      ),
    );
  }

  Widget _miniInput({required String hint, required String initial}) {
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

  static String _fmt(int n) {
    final s = n.toString();
    return s.replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => "${m[1]} ");
  }
}

class _DashedRectPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = AppColors.hairline
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    final rect = RRect.fromRectAndRadius(
        Rect.fromLTWH(6, 6, size.width - 12, size.height - 12),
        const Radius.circular(AppRadius.md));
    canvas.drawRRect(rect, p);
  }

  @override
  bool shouldRepaint(covariant _DashedRectPainter old) => false;
}
