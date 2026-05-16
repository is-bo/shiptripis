import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/matching/matching_providers.dart';
import '../../core/matching/matching_repository.dart';
import '../../core/parcels/parcels_providers.dart';
import '../../core/parcels/parcels_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/trips/trips_providers.dart';
import '../../core/trips/trips_repository.dart';
import '../../shared/widgets/boarding_card.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/stamp_chip.dart';

class FindParcelsScreen extends ConsumerStatefulWidget {
  const FindParcelsScreen({super.key});

  @override
  ConsumerState<FindParcelsScreen> createState() => _FindParcelsScreenState();
}

class _FindParcelsScreenState extends ConsumerState<FindParcelsScreen> {
  Trip? _filterByTrip;
  String? _kindFilter; // 'delivery' | 'product' | null
  bool _bootstrapped = false;

  @override
  Widget build(BuildContext context) {
    final tripsAsync = ref.watch(myTripsProvider);

    if (!_bootstrapped && tripsAsync.hasValue) {
      _bootstrapped = true;
      final bookable = tripsAsync.value!
          .where((t) => t.status == 'active' || t.status == 'draft')
          .toList();
      if (bookable.isNotEmpty) _filterByTrip = bookable.first;
    }

    final params = OpenParcelSearchParams(
      originIata: _filterByTrip?.origin.iata,
      destinationIata: _filterByTrip?.destination.iata,
      kind: _kindFilter,
      maxWeightKg: _filterByTrip?.capacityKg,
    );
    final parcelsAsync = ref.watch(openParcelSearchProvider(params));

    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(openParcelSearchProvider(params)),
        child: CustomScrollView(
          slivers: [
            SliverToBoxAdapter(child: _Header()),
            SliverToBoxAdapter(
              child: _RouteFilter(
                trips: tripsAsync.value ?? const [],
                selected: _filterByTrip,
                onChanged: (t) => setState(() => _filterByTrip = t),
              ),
            ),
            SliverToBoxAdapter(
              child: _KindFilter(
                value: _kindFilter,
                onChanged: (v) => setState(() => _kindFilter = v),
              ),
            ),
            const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.x4)),
            parcelsAsync.when(
              loading: () => const SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(child: CircularProgressIndicator()),
                ),
              ),
              error: (e, _) => SliverPadding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
                sliver: SliverToBoxAdapter(
                  child: _ErrorTile(
                    onRetry: () =>
                        ref.invalidate(openParcelSearchProvider(params)),
                  ),
                ),
              ),
              data: (parcels) {
                if (parcels.isEmpty) {
                  return const SliverPadding(
                    padding: EdgeInsets.fromLTRB(
                        AppSpacing.x6, 0, AppSpacing.x6, 100),
                    sliver: SliverToBoxAdapter(child: _EmptyTile()),
                  );
                }
                return SliverList.separated(
                  itemCount: parcels.length,
                  separatorBuilder: (_, _) =>
                      const SizedBox(height: AppSpacing.x4),
                  itemBuilder: (_, i) => Padding(
                    padding: EdgeInsets.fromLTRB(AppSpacing.x6, 0, AppSpacing.x6,
                        i == parcels.length - 1 ? 100 : 0),
                    child: _OpenParcelCard(
                      parcel: parcels[i],
                      onTap: () => _openApplySheet(parcels[i]),
                    )
                        .animate()
                        .fadeIn(
                            delay: Duration(milliseconds: 50 * i),
                            duration: 320.ms)
                        .moveY(begin: 14, end: 0, curve: kAppCurve),
                  ),
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _openApplySheet(Parcel parcel) async {
    final allTrips = ref.read(myTripsProvider).value ?? const <Trip>[];
    final eligible = allTrips.where((t) {
      if (t.status != 'active' && t.status != 'draft') return false;
      if (t.origin.iata != parcel.origin.iata) return false;
      if (t.destination.iata != parcel.destination.iata) return false;
      if (t.capacityKg < parcel.weightKg) return false;
      return true;
    }).toList();

    if (eligible.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            "No trip of yours covers ${parcel.origin.iata} → ${parcel.destination.iata} with ${parcel.weightKg}kg+ capacity.",
            style: AppType.body(13, color: AppColors.parchment),
          ),
          backgroundColor: AppColors.ink,
        ),
      );
      return;
    }

    final result = await showModalBottomSheet<_ApplyResult>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _ApplySheet(parcel: parcel, eligibleTrips: eligible),
    );

    if (result == null || !mounted) return;

    final repo = ref.read(matchingRepositoryProvider);
    try {
      final match = await repo.apply(
        parcelId: parcel.id,
        tripId: result.tripId,
        baseAmountDzd: result.baseAmountDzd,
        note: result.note,
      );
      if (!mounted) return;
      // Invalidate caches that show this work.
      ref.invalidate(openParcelSearchProvider);
      ref.invalidate(matchListProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.emerald,
          content: Text(
            "Application sent. The sender will review your offer.",
            style: AppType.body(13,
                color: AppColors.parchment, w: FontWeight.w600),
          ),
        ),
      );
      context.push('/match/${match.id}');
    } on MatchingFailure catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.terracotta,
          content: Text(e.message,
              style: AppType.body(13,
                  color: AppColors.parchment, w: FontWeight.w600)),
        ),
      );
    }
  }
}

class _ApplyResult {
  const _ApplyResult(
      {required this.tripId, this.baseAmountDzd, this.note = ''});
  final int tripId;
  final int? baseAmountDzd;
  final String note;
}

class _ApplySheet extends StatefulWidget {
  const _ApplySheet({required this.parcel, required this.eligibleTrips});
  final Parcel parcel;
  final List<Trip> eligibleTrips;

  @override
  State<_ApplySheet> createState() => _ApplySheetState();
}

class _ApplySheetState extends State<_ApplySheet> {
  late Trip _trip;
  late final TextEditingController _amountController;
  final _noteController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _trip = widget.eligibleTrips.first;
    final defaultAmount = widget.parcel.kind == 'product'
        ? widget.parcel.productPriceDzd
        : widget.parcel.baseAmountDzd;
    _amountController = TextEditingController(
      text: defaultAmount?.toString() ?? '',
    );
  }

  @override
  void dispose() {
    _amountController.dispose();
    _noteController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final inset = MediaQuery.of(context).viewInsets.bottom;
    final isProduct = widget.parcel.kind == 'product';
    return Padding(
      padding: EdgeInsets.only(bottom: inset),
      child: Container(
        decoration: const BoxDecoration(
          color: AppColors.parchment,
          borderRadius:
              BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
        ),
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
        child: SafeArea(
          top: false,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 44,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.hairline,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.x4),
              Text("APPLY TO CARRY",
                  style: AppType.eyebrow().copyWith(letterSpacing: 1.4)),
              const SizedBox(height: 4),
              Text(
                "${widget.parcel.origin.iata} → ${widget.parcel.destination.iata}",
                style: AppType.display(26, w: FontWeight.w500),
              ),
              const SizedBox(height: 2),
              Text(
                "${widget.parcel.weightKg} kg · ${isProduct ? 'product' : 'delivery'}",
                style: AppType.body(13, color: AppColors.inkMute),
              ),
              const SizedBox(height: AppSpacing.x5),
              Text("WITH WHICH TRIP", style: AppType.eyebrow()),
              const SizedBox(height: 8),
              ...widget.eligibleTrips.map((t) => _TripRadioRow(
                    trip: t,
                    selected: t.id == _trip.id,
                    onTap: () => setState(() => _trip = t),
                  )),
              const SizedBox(height: AppSpacing.x5),
              Text(isProduct ? "PRODUCT PRICE (DZD)" : "YOUR PAYOUT (DZD)",
                  style: AppType.eyebrow()),
              const SizedBox(height: 6),
              TextField(
                controller: _amountController,
                keyboardType: TextInputType.number,
                style: AppType.mono(18, w: FontWeight.w700),
                decoration: InputDecoration(
                  filled: true,
                  fillColor: AppColors.parchmentSoft,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    borderSide: const BorderSide(color: AppColors.hairline),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    borderSide: const BorderSide(color: AppColors.hairline),
                  ),
                  hintText:
                      isProduct ? "What you'll pay at the store" : "Your asking price",
                  hintStyle:
                      AppType.body(13, color: AppColors.inkMute),
                ),
              ),
              const SizedBox(height: AppSpacing.x4),
              Text("NOTE (OPTIONAL)", style: AppType.eyebrow()),
              const SizedBox(height: 6),
              TextField(
                controller: _noteController,
                maxLines: 2,
                style: AppType.body(13.5),
                decoration: InputDecoration(
                  filled: true,
                  fillColor: AppColors.parchmentSoft,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    borderSide: const BorderSide(color: AppColors.hairline),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    borderSide: const BorderSide(color: AppColors.hairline),
                  ),
                  hintText: "Say hi or add pickup details",
                  hintStyle: AppType.body(13, color: AppColors.inkMute),
                ),
              ),
              const SizedBox(height: AppSpacing.x6),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.ink,
                    foregroundColor: AppColors.parchment,
                    padding:
                        const EdgeInsets.symmetric(vertical: AppSpacing.x4),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(AppRadius.pill),
                    ),
                  ),
                  onPressed: () {
                    final amt = int.tryParse(_amountController.text.trim());
                    Navigator.of(context).pop(_ApplyResult(
                      tripId: _trip.id,
                      baseAmountDzd: amt,
                      note: _noteController.text.trim(),
                    ));
                  },
                  child: Text("Send application",
                      style: AppType.body(14.5,
                          color: AppColors.parchment, w: FontWeight.w700)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TripRadioRow extends StatelessWidget {
  const _TripRadioRow(
      {required this.trip, required this.selected, required this.onTap});
  final Trip trip;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.x4, vertical: AppSpacing.x3),
        decoration: BoxDecoration(
          color: selected ? AppColors.ink : AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(
              color: selected ? AppColors.ink : AppColors.hairline),
        ),
        child: Row(
          children: [
            Icon(
              selected
                  ? Icons.radio_button_checked
                  : Icons.radio_button_unchecked,
              size: 18,
              color: selected ? AppColors.parchment : AppColors.inkMute,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    "Trip #${trip.id} · ${trip.flightNumber.isEmpty ? 'no flight#' : trip.flightNumber}",
                    style: AppType.body(13,
                        w: FontWeight.w700,
                        color: selected
                            ? AppColors.parchment
                            : AppColors.ink),
                  ),
                  Text(
                    "${_fmtDate(trip.departureAt)} · ${trip.capacityKg} kg free",
                    style: AppType.body(11.5,
                        color: selected
                            ? AppColors.parchmentDeep
                            : AppColors.inkMute),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  static String _fmtDate(DateTime d) {
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];
    final l = d.toLocal();
    return "${l.day.toString().padLeft(2, '0')} ${months[l.month - 1]}";
  }
}

class _Header extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return SafeArea(
      bottom: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x4),
        child: Row(
          children: [
            IconButton(
              onPressed: () => Navigator.of(context).maybePop(),
              icon: const Icon(Icons.arrow_back_rounded),
            ),
            const SizedBox(width: 4),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("OPEN PARCELS",
                      style: AppType.eyebrow().copyWith(letterSpacing: 1.4)),
                  const SizedBox(height: 2),
                  Text("Find a shipment\nfor your trip.",
                      style:
                          AppType.display(28, w: FontWeight.w400, height: 1.05)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RouteFilter extends StatelessWidget {
  const _RouteFilter(
      {required this.trips, required this.selected, required this.onChanged});
  final List<Trip> trips;
  final Trip? selected;
  final ValueChanged<Trip?> onChanged;

  @override
  Widget build(BuildContext context) {
    final bookable = trips
        .where((t) => t.status == 'active' || t.status == 'draft')
        .toList();
    if (bookable.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.x6, vertical: AppSpacing.x2),
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.x4),
          decoration: BoxDecoration(
            color: AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Row(
            children: [
              const Icon(Icons.flight_takeoff_rounded,
                  color: AppColors.inkMute),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  "List a trip first — open parcels are matched to your routes.",
                  style: AppType.body(12.5, color: AppColors.inkMute),
                ),
              ),
            ],
          ),
        ),
      );
    }
    return SizedBox(
      height: 56,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
        itemCount: bookable.length + 1,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          if (i == 0) {
            final isAll = selected == null;
            return _Chip(
              label: "All routes",
              selected: isAll,
              onTap: () => onChanged(null),
            );
          }
          final t = bookable[i - 1];
          final isSelected = selected?.id == t.id;
          return _Chip(
            label: "${t.origin.iata} → ${t.destination.iata}",
            selected: isSelected,
            onTap: () => onChanged(t),
          );
        },
      ),
    );
  }
}

class _KindFilter extends StatelessWidget {
  const _KindFilter({required this.value, required this.onChanged});
  final String? value;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x6, AppSpacing.x3, AppSpacing.x6, 0),
      child: Row(
        children: [
          _Chip(
            label: "All",
            selected: value == null,
            onTap: () => onChanged(null),
          ),
          const SizedBox(width: 8),
          _Chip(
            label: "Delivery",
            selected: value == 'delivery',
            onTap: () => onChanged('delivery'),
          ),
          const SizedBox(width: 8),
          _Chip(
            label: "Product",
            selected: value == 'product',
            onTap: () => onChanged('product'),
          ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip(
      {required this.label, required this.selected, required this.onTap});
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        alignment: Alignment.center,
        padding:
            const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? AppColors.ink : AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.pill),
          border: Border.all(
              color: selected ? AppColors.ink : AppColors.hairline),
        ),
        child: Text(label,
            style: AppType.body(12.5,
                w: FontWeight.w700,
                color: selected ? AppColors.parchment : AppColors.ink)),
      ),
    );
  }
}

class _OpenParcelCard extends StatelessWidget {
  const _OpenParcelCard({required this.parcel, required this.onTap});
  final Parcel parcel;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final isProduct = parcel.kind == 'product';
    final amount = isProduct ? parcel.productPriceDzd : parcel.baseAmountDzd;
    return BoardingCard(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StampChip(
                label: isProduct ? "PRODUCT" : "DELIVERY",
                color: isProduct ? AppColors.gold : AppColors.emerald,
              ),
              const Spacer(),
              Text("#${parcel.id}",
                  style:
                      AppType.mono(11, color: AppColors.inkMute)),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          Row(
            children: [
              CountryPill(
                  code: parcel.origin.country,
                  label: parcel.origin.iata,
                  dense: true),
              Expanded(
                child: Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8),
                  child: CustomPaint(
                    painter: _DashLinePainter(),
                    size: const Size.fromHeight(20),
                  ),
                ),
              ),
              CountryPill(
                  code: parcel.destination.country,
                  label: parcel.destination.iata,
                  dense: true),
            ],
          ),
          const SizedBox(height: AppSpacing.x4),
          const DashedDivider(),
          const SizedBox(height: AppSpacing.x4),
          Row(
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("WEIGHT", style: AppType.eyebrow()),
                  const SizedBox(height: 4),
                  Text("${parcel.weightKg} kg",
                      style: AppType.mono(14, w: FontWeight.w700)),
                ],
              ),
              const SizedBox(width: AppSpacing.x6),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(isProduct ? "PRODUCT PRICE" : "OFFERED",
                      style: AppType.eyebrow()),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Text(amount == null ? "—" : _fmt(amount),
                          style: AppType.mono(14, w: FontWeight.w700)),
                      const SizedBox(width: 4),
                      Text("DZD",
                          style: AppType.mono(10,
                              color: AppColors.inkMute)),
                    ],
                  ),
                ],
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 14, vertical: 8),
                decoration: BoxDecoration(
                  color: AppColors.ink,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: Row(
                  children: [
                    Text("Apply",
                        style: AppType.body(12.5,
                            color: AppColors.parchment,
                            w: FontWeight.w700)),
                    const SizedBox(width: 6),
                    const Icon(Icons.arrow_forward_rounded,
                        size: 14, color: AppColors.parchment),
                  ],
                ),
              ),
            ],
          ),
          if (parcel.itemType.isNotEmpty || parcel.description.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.x3),
            Text(
              [parcel.itemType, parcel.description]
                  .where((s) => s.isNotEmpty)
                  .join(" · "),
              style: AppType.body(12, color: AppColors.inkMute),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ],
      ),
    );
  }

  static String _fmt(int n) {
    final s = n.toString();
    return s.replaceAllMapped(
        RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => "${m[1]} ");
  }
}

class _DashLinePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = AppColors.inkMute.withValues(alpha: 0.5)
      ..strokeWidth = 1.2;
    const dashW = 4.0, gap = 3.0;
    double x = 0;
    while (x < size.width) {
      canvas.drawLine(Offset(x, size.height / 2),
          Offset(x + dashW, size.height / 2), p);
      x += dashW + gap;
    }
  }

  @override
  bool shouldRepaint(covariant _DashLinePainter old) => false;
}

class _EmptyTile extends StatelessWidget {
  const _EmptyTile();
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x6),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: AppColors.parchment,
              borderRadius: BorderRadius.circular(AppRadius.pill),
              border: Border.all(color: AppColors.hairline),
            ),
            child: const Icon(Icons.search_off_rounded,
                color: AppColors.inkMute, size: 24),
          ),
          const SizedBox(height: 12),
          Text("No open parcels",
              style: AppType.display(18, w: FontWeight.w500)),
          const SizedBox(height: 4),
          Text(
              "Try removing filters or check back later — new requests appear every day.",
              style: AppType.body(13, color: AppColors.inkMute),
              textAlign: TextAlign.center),
        ],
      ),
    );
  }
}

class _ErrorTile extends StatelessWidget {
  const _ErrorTile({required this.onRetry});
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.terracotta.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
            color: AppColors.terracotta.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          const Icon(Icons.cloud_off_rounded,
              color: AppColors.terracotta),
          const SizedBox(width: 12),
          Expanded(
            child: Text("Couldn't load open parcels.",
                style: AppType.body(13, w: FontWeight.w600)),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
