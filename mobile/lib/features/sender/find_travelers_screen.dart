import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/matching/matching_providers.dart';
import '../../core/matching/matching_repository.dart';
import '../../core/parcels/parcels_providers.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/trips/trips_providers.dart';
import '../../core/trips/trips_repository.dart';
import '../../shared/util/safe_back.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

/// Results page for `search_filter_screen`. The sender narrows by route +
/// capacity, sees matching trips, and taps one.
///
/// Two modes, decided by [parcelId]:
///   null — browsing before posting. Tapping opens the request form, scoped
///          to that traveler.
///   set  — the parcel already exists (they came from "find a traveler" on a
///          posted request). Tapping applies with it directly; making them
///          re-type everything they already submitted would be absurd.
class FindTravelersScreen extends ConsumerStatefulWidget {
  const FindTravelersScreen({
    super.key,
    required this.originIata,
    required this.destinationIata,
    required this.minCapacityKg,
    this.parcelId,
  });

  final String originIata;
  final String destinationIata;
  final int minCapacityKg;
  final int? parcelId;

  @override
  ConsumerState<FindTravelersScreen> createState() =>
      _FindTravelersScreenState();
}

class _FindTravelersScreenState extends ConsumerState<FindTravelersScreen> {
  @override
  Widget build(BuildContext context) {
    final originIata = widget.originIata;
    final destinationIata = widget.destinationIata;
    final minCapacityKg = widget.minCapacityKg;
    final params = TripSearchParams(
      originIata: originIata,
      destinationIata: destinationIata,
      minCapacityKg: minCapacityKg,
    );
    final async = ref.watch(tripSearchProvider(params));

    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Column(
          children: [
            _topBar(context),
            const SizedBox(height: AppSpacing.x4),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('TRAVELERS', style: AppType.eyebrow()),
                        const SizedBox(height: 4),
                        Text('$originIata → $destinationIata',
                            style: AppType.display(26, w: FontWeight.w500)),
                        Text('Min capacity ${minCapacityKg}kg',
                            style: AppType.body(12.5, color: AppColors.inkMute)),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.x4),
            Expanded(
              child: async.when(
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(AppSpacing.x6),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.cloud_off_rounded,
                            color: AppColors.terracotta, size: 32),
                        const SizedBox(height: 12),
                        Text("Couldn't load travelers.",
                            style: AppType.body(13, w: FontWeight.w600)),
                        const SizedBox(height: 8),
                        TextButton(
                          onPressed: () =>
                              ref.invalidate(tripSearchProvider(params)),
                          child: const Text('Retry'),
                        ),
                      ],
                    ),
                  ),
                ),
                data: (trips) {
                  if (trips.isEmpty) {
                    return _Empty(
                      onPostRequest: () =>
                          context.push('/sender/new'),
                    );
                  }
                  return RefreshIndicator(
                    onRefresh: () async =>
                        ref.invalidate(tripSearchProvider(params)),
                    child: ListView.separated(
                      padding: const EdgeInsets.fromLTRB(AppSpacing.x6,
                          AppSpacing.x2, AppSpacing.x6, AppSpacing.x6),
                      itemCount: trips.length,
                      separatorBuilder: (_, _) =>
                          const SizedBox(height: AppSpacing.x3),
                      itemBuilder: (_, i) => _TripTile(
                        trip: trips[i],
                        applyingWithParcel: widget.parcelId != null,
                        onTap: () {
                          final pid = widget.parcelId;
                          if (pid != null) {
                            _openApplySheet(pid, trips[i]);
                          } else {
                            context.push(
                                '/sender/new?traveler=${trips[i].travelerId}');
                          }
                        },
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

  Widget _topBar(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x4, AppSpacing.x4, AppSpacing.x4, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => safeBack(context),
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

  /// The parcel already exists, so this only asks for the one thing that is
  /// genuinely per-trip: the price the sender is willing to pay this traveler.
  Future<void> _openApplySheet(int parcelId, Trip trip) async {
    final result = await showModalBottomSheet<_ApplyResult>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _SenderApplySheet(trip: trip),
    );
    if (result == null || !mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      final match = await ref.read(matchingRepositoryProvider).applyToTrip(
            parcelId: parcelId,
            tripId: trip.id,
            baseAmountDzd: result.baseAmountDzd,
            note: result.note,
          );
      if (!mounted) return;
      ref.invalidate(matchListProvider);
      ref.invalidate(myParcelsProvider);
      messenger.showSnackBar(
        SnackBar(
          backgroundColor: AppColors.emerald,
          content: Text('Request sent to ${trip.travelerLabel}.',
              style: AppType.body(13,
                  color: AppColors.parchment, w: FontWeight.w600)),
        ),
      );
      context.push('/match/${match.id}');
    } on MatchingFailure catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
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
  const _ApplyResult({this.baseAmountDzd, this.note = ''});
  final int? baseAmountDzd;
  final String note;
}

/// Price-and-note sheet. Deliberately tiny: everything else about the parcel
/// was already submitted when it was posted.
class _SenderApplySheet extends StatefulWidget {
  const _SenderApplySheet({required this.trip});
  final Trip trip;

  @override
  State<_SenderApplySheet> createState() => _SenderApplySheetState();
}

class _SenderApplySheetState extends State<_SenderApplySheet> {
  final _amount = TextEditingController();
  final _note = TextEditingController();
  String? _amountError;

  @override
  void dispose() {
    _amount.dispose();
    _note.dispose();
    super.dispose();
  }

  void _submit() {
    final raw = _amount.text.trim();
    int? amount;
    if (raw.isNotEmpty) {
      amount = int.tryParse(raw);
      // Mirrors the server's `min_value=100` so the user sees the problem
      // here rather than as a 400 after the round trip.
      if (amount == null || amount < 100) {
        setState(() => _amountError = 'Enter an amount of at least 100 DZD.');
        return;
      }
    }
    Navigator.of(context).pop(
      _ApplyResult(baseAmountDzd: amount, note: _note.text.trim()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom),
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.x6),
        decoration: const BoxDecoration(
          color: AppColors.parchment,
          borderRadius: BorderRadius.vertical(
              top: Radius.circular(AppRadius.lg)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('SEND TO THIS TRAVELER', style: AppType.eyebrow()),
            const SizedBox(height: 6),
            Text(widget.trip.travelerLabel,
                style: AppType.display(22, w: FontWeight.w500)),
            const SizedBox(height: 4),
            Text(
              'Your request is already filled in — just confirm what you want to pay.',
              style: AppType.body(13, color: AppColors.inkMute),
            ),
            const SizedBox(height: AppSpacing.x5),
            Text('YOUR PRICE (DZD)', style: AppType.eyebrow()),
            const SizedBox(height: 8),
            TextField(
              controller: _amount,
              keyboardType: TextInputType.number,
              onChanged: (_) {
                if (_amountError != null) setState(() => _amountError = null);
              },
              decoration: InputDecoration(
                hintText: 'Leave empty to keep your posted price',
                hintStyle: AppType.body(13, color: AppColors.inkMute),
                filled: true,
                fillColor: AppColors.parchmentSoft,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide: const BorderSide(color: AppColors.hairline),
                ),
              ),
            ),
            if (_amountError != null) ...[
              const SizedBox(height: 6),
              Text(_amountError!,
                  style: AppType.body(12, color: AppColors.danger)),
            ],
            const SizedBox(height: AppSpacing.x4),
            Text('NOTE (OPTIONAL)', style: AppType.eyebrow()),
            const SizedBox(height: 8),
            TextField(
              controller: _note,
              maxLines: 2,
              decoration: InputDecoration(
                hintText: 'Anything the traveler should know',
                hintStyle: AppType.body(13, color: AppColors.inkMute),
                filled: true,
                fillColor: AppColors.parchmentSoft,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide: const BorderSide(color: AppColors.hairline),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.x5),
            Center(
              child: PrimaryButton(
                label: 'Send request',
                icon: Icons.send_rounded,
                onTap: _submit,
              ),
            ),
            const SizedBox(height: AppSpacing.x2),
          ],
        ),
      ),
    );
  }
}

class _TripTile extends StatelessWidget {
  const _TripTile({
    required this.trip,
    required this.onTap,
    this.applyingWithParcel = false,
  });
  final Trip trip;
  final VoidCallback onTap;
  final bool applyingWithParcel;

  @override
  Widget build(BuildContext context) {
    final dep = trip.departureAt.toLocal();
    final dateStr =
        '${_mon(dep.month)} ${dep.day} · ${dep.hour.toString().padLeft(2, '0')}:${dep.minute.toString().padLeft(2, '0')}';
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: Container(
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
                CountryPill(
                    code: trip.origin.country,
                    label: trip.origin.iata,
                    dense: true),
                const SizedBox(width: 6),
                const Icon(Icons.arrow_forward_rounded,
                    size: 16, color: AppColors.inkMute),
                const SizedBox(width: 6),
                CountryPill(
                    code: trip.destination.country,
                    label: trip.destination.iata,
                    dense: true),
                const Spacer(),
                Text(trip.travelerLabel,
                    style: AppType.body(11, color: AppColors.inkMute)),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                const Icon(Icons.calendar_today_rounded,
                    size: 14, color: AppColors.inkSoft),
                const SizedBox(width: 6),
                Text(dateStr,
                    style: AppType.body(13, w: FontWeight.w600)),
                const SizedBox(width: 14),
                const Icon(Icons.scale_rounded,
                    size: 14, color: AppColors.inkSoft),
                const SizedBox(width: 6),
                Text('${trip.capacityKg} kg free',
                    style: AppType.body(13, w: FontWeight.w600)),
                if (trip.flightNumber.isNotEmpty) ...[
                  const SizedBox(width: 14),
                  const Icon(Icons.flight_rounded,
                      size: 14, color: AppColors.inkSoft),
                  const SizedBox(width: 6),
                  Text(trip.flightNumber,
                      style: AppType.mono(12, w: FontWeight.w600)),
                ],
              ],
            ),
            if (trip.notes.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(trip.notes,
                  style: AppType.body(12.5, color: AppColors.inkSoft),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis),
            ],
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: Text(
                  applyingWithParcel
                      ? 'Send your request →'
                      : 'Tap to request →',
                  style: AppType.body(12,
                      color: AppColors.emerald, w: FontWeight.w700)),
            ),
          ],
        ),
      ),
    );
  }

  static String _mon(int m) => const [
        'Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'
      ][m - 1];
}

class _Empty extends StatelessWidget {
  const _Empty({required this.onPostRequest});
  final VoidCallback onPostRequest;
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.x6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: AppColors.parchmentSoft,
                borderRadius: BorderRadius.circular(AppRadius.pill),
                border: Border.all(color: AppColors.hairline),
              ),
              child: const Icon(Icons.travel_explore_rounded,
                  color: AppColors.inkMute, size: 28),
            ),
            const SizedBox(height: 14),
            Text('No travelers on this route yet.',
                style: AppType.display(18, w: FontWeight.w500)),
            const SizedBox(height: 6),
            Text(
              'Post your request anyway — travelers see new requests and can offer.',
              style: AppType.body(13, color: AppColors.inkMute),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            PrimaryButton(label: 'Post a request', onTap: onPostRequest),
          ],
        ),
      ),
    );
  }
}
