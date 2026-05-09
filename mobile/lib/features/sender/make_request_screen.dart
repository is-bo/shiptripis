import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/parcels/parcels_providers.dart';
import '../../core/parcels/parcels_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/trips/trips_providers.dart';
import '../../core/trips/trips_repository.dart';
import '../../shared/widgets/airport_picker.dart';
import '../../shared/widgets/boarding_card.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

enum _RequestType { delivery, product }

const _itemTypeOptions = [
  ("documents", "Documents"),
  ("small_box", "Small box"),
  ("electronics", "Electronics"),
  ("clothing", "Clothing"),
  ("other", "Other"),
];

class MakeRequestScreen extends ConsumerStatefulWidget {
  const MakeRequestScreen({super.key});
  @override
  ConsumerState<MakeRequestScreen> createState() => _MakeRequestScreenState();
}

class _MakeRequestScreenState extends ConsumerState<MakeRequestScreen> {
  _RequestType _type = _RequestType.delivery;
  String _itemType = "documents";
  int _kg = 2;

  Airport? _origin;
  Airport? _dest;

  final _amountCtl = TextEditingController(text: "5000");
  final _descCtl = TextEditingController();
  final _storeCtl = TextEditingController();
  final _urlCtl = TextEditingController();
  final _pickupCityCtl = TextEditingController();
  final _dropCityCtl = TextEditingController();

  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _amountCtl.dispose();
    _descCtl.dispose();
    _storeCtl.dispose();
    _urlCtl.dispose();
    _pickupCityCtl.dispose();
    _dropCityCtl.dispose();
    super.dispose();
  }

  int _amount() => int.tryParse(_amountCtl.text.replaceAll(' ', '').replaceAll(',', '')) ?? 0;

  int _commissionDelivery(int base) => (base * 0.25).round();

  int _commissionProduct(int price) {
    if (price < 30000) return 0;
    if (price < 55000) return (price * 0.07).round();
    if (price < 100000) return (price * 0.05).round();
    return (price * 0.03).round();
  }

  Future<void> _pickAirport(bool isOrigin, List<Airport> airports) async {
    final cur = isOrigin ? _origin : _dest;
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
        _origin = picked;
        if (_dest?.country == picked.country) _dest = null;
      } else {
        _dest = picked;
        if (_origin?.country == picked.country) _origin = null;
      }
    });
  }

  Future<void> _submit() async {
    if (_origin == null || _dest == null) {
      setState(() => _error = 'Choose origin and destination.');
      return;
    }
    final amount = _amount();
    if (amount < 100) {
      setState(() => _error = _type == _RequestType.delivery
          ? 'Enter a base amount of at least 100 DZD.'
          : 'Enter a product price of at least 100 DZD.');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final notifier = ref.read(myParcelsProvider.notifier);
      if (_type == _RequestType.delivery) {
        await notifier.createDelivery(
          originIata: _origin!.iata,
          destinationIata: _dest!.iata,
          weightKg: _kg,
          itemType: _itemType,
          baseAmountDzd: amount,
          description: _descCtl.text.trim(),
          pickupCity: _pickupCityCtl.text.trim(),
          deliveryCity: _dropCityCtl.text.trim(),
        );
      } else {
        await notifier.createProduct(
          originIata: _origin!.iata,
          destinationIata: _dest!.iata,
          weightKg: _kg,
          itemType: _itemType,
          productPriceDzd: amount,
          storeName: _storeCtl.text.trim(),
          productUrl: _urlCtl.text.trim(),
          description: _descCtl.text.trim(),
          pickupCity: _pickupCityCtl.text.trim(),
          deliveryCity: _dropCityCtl.text.trim(),
        );
      }
      if (!mounted) return;
      context.pop();
    } on ParcelsFailure catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Network error. Check your connection.');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
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
            _origin ??= airports.firstWhere(
              (a) => a.country == 'DZ',
              orElse: () => airports.first,
            );
            _dest ??= airports.firstWhere(
              (a) => a.country == 'FR',
              orElse: () => airports.last,
            );
            return Column(
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
                      ..._commonFields(),
                      const SizedBox(height: AppSpacing.x6),
                      if (_type == _RequestType.delivery)
                        ..._deliveryFields()
                      else
                        ..._productFields(),
                      const SizedBox(height: AppSpacing.x6),
                      _routeBlock(airports),
                      const SizedBox(height: AppSpacing.x6),
                      _summary(),
                      if (_error != null) ...[
                        const SizedBox(height: AppSpacing.x4),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: AppColors.terracotta.withValues(alpha: 0.08),
                            borderRadius: BorderRadius.circular(AppRadius.md),
                            border: Border.all(color: AppColors.terracotta),
                          ),
                          child: Row(
                            children: [
                              const Icon(Icons.error_outline_rounded,
                                  color: AppColors.terracotta, size: 18),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(_error!,
                                    style: AppType.body(13,
                                        color: AppColors.terracottaDeep,
                                        w: FontWeight.w600)),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(
                      AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
                  child: PrimaryButton(
                    label: _submitting ? "Posting…" : "Post request",
                    icon: Icons.send_rounded,
                    expand: true,
                    onTap: _submitting ? null : _submit,
                  ),
                ),
              ],
            );
          },
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
          const StampChip(label: "ESCROW PROTECTED", color: AppColors.emerald),
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
        onTap: () => setState(() {
          _type = t;
          _amountCtl.text = t == _RequestType.delivery ? "5000" : "20000";
        }),
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

  List<Widget> _commonFields() {
    return [
      _label("Item type"),
      const SizedBox(height: 10),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: _itemTypeOptions
            .map((t) => _chip(t.$2, _itemType == t.$1, () => setState(() => _itemType = t.$1)))
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
                value: _kg.toDouble(),
                min: 1,
                max: 25,
                divisions: 24,
                onChanged: (v) => setState(() => _kg = v.toInt()),
              ),
            ),
          ),
          Text("$_kg kg", style: AppType.mono(14, w: FontWeight.w700)),
        ],
      ),
    ];
  }

  List<Widget> _deliveryFields() {
    return [
      _label("Description (optional)"),
      const SizedBox(height: 10),
      _input(_descCtl, "e.g. wedding documents"),
      const SizedBox(height: AppSpacing.x4),
      _label("Base amount you'll pay (DZD)"),
      const SizedBox(height: 10),
      _input(_amountCtl, "5000",
          keyboard: TextInputType.number,
          onChanged: (_) => setState(() {})),
    ];
  }

  List<Widget> _productFields() {
    return [
      _label("Product / store"),
      const SizedBox(height: 10),
      _input(_storeCtl, "e.g. Fnac, Amazon FR"),
      const SizedBox(height: AppSpacing.x4),
      _label("Product URL (optional)"),
      const SizedBox(height: 10),
      _input(_urlCtl, "https://…",
          keyboard: TextInputType.url),
      const SizedBox(height: AppSpacing.x4),
      _label("Product price (DZD)"),
      const SizedBox(height: 10),
      _input(_amountCtl, "20000",
          keyboard: TextInputType.number,
          onChanged: (_) => setState(() {})),
    ];
  }

  Widget _routeBlock(List<Airport> airports) {
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
                  Expanded(
                    child: _AirportTile(
                      label: "FROM",
                      airport: _origin!,
                      onTap: () => _pickAirport(true, airports),
                    ),
                  ),
                  const SizedBox(width: 8),
                  const Icon(Icons.arrow_forward_rounded,
                      color: AppColors.inkMute, size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _AirportTile(
                      label: "TO",
                      airport: _dest!,
                      onTap: () => _pickAirport(false, airports),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: _miniInput(
                        controller: _pickupCityCtl, hint: "Pickup city"),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: _miniInput(
                        controller: _dropCityCtl, hint: "Drop-off city"),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _summary() {
    final amount = _amount();
    final commission = _type == _RequestType.delivery
        ? _commissionDelivery(amount)
        : 2500 + _commissionProduct(amount);
    final total = amount + commission;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        children: [
          _row(_type == _RequestType.delivery ? "Base amount" : "Product price",
              "${_fmt(amount)} DZD"),
          _row(
            _type == _RequestType.delivery
                ? "Commission · 25%"
                : "Base fee + commission",
            "${_fmt(commission)} DZD",
          ),
          const SizedBox(height: 4),
          DashedDivider(color: AppColors.parchment.withValues(alpha: 0.25)),
          const SizedBox(height: 8),
          _row("Total you pay", "${_fmt(total)} DZD", strong: true),
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

  Widget _label(String t) => Text(t.toUpperCase(), style: AppType.eyebrow());

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

  Widget _input(TextEditingController c, String hint,
      {TextInputType? keyboard, ValueChanged<String>? onChanged}) {
    return TextField(
      controller: c,
      keyboardType: keyboard,
      onChanged: onChanged,
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

  Widget _miniInput({required TextEditingController controller, required String hint}) {
    return TextField(
      controller: controller,
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
        padding: const EdgeInsets.fromLTRB(10, 8, 8, 8),
        decoration: BoxDecoration(
          color: AppColors.parchment,
          borderRadius: BorderRadius.circular(AppRadius.sm),
          border: Border.all(color: AppColors.hairline),
        ),
        child: Row(
          children: [
            CountryPill(code: airport.country, label: airport.country, dense: true),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: AppType.eyebrow()),
                  const SizedBox(height: 2),
                  Text("${airport.iata} · ${airport.city}",
                      style: AppType.body(12.5, w: FontWeight.w700),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis),
                ],
              ),
            ),
            const Icon(Icons.unfold_more_rounded,
                size: 16, color: AppColors.inkMute),
          ],
        ),
      ),
    );
  }
}
