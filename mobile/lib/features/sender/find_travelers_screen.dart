import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/trips/trips_providers.dart';
import '../../core/trips/trips_repository.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

/// Results page for `search_filter_screen`. The sender narrows by route +
/// capacity, sees matching trips, and taps one to start a request scoped to
/// that traveler's route.
class FindTravelersScreen extends ConsumerWidget {
  const FindTravelersScreen({
    super.key,
    required this.originIata,
    required this.destinationIata,
    required this.minCapacityKg,
  });

  final String originIata;
  final String destinationIata;
  final int minCapacityKg;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
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
                      separatorBuilder: (_, __) =>
                          const SizedBox(height: AppSpacing.x3),
                      itemBuilder: (_, i) => _TripTile(
                        trip: trips[i],
                        onTap: () => context.push(
                            '/sender/new?traveler=${trips[i].travelerId}'),
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
}

class _TripTile extends StatelessWidget {
  const _TripTile({required this.trip, required this.onTap});
  final Trip trip;
  final VoidCallback onTap;

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
                Text('Traveler #${trip.travelerId}',
                    style: AppType.mono(11, color: AppColors.inkMute)),
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
              child: Text('Tap to request →',
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
