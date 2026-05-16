import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
import 'trips_repository.dart';

final tripsRepositoryProvider = Provider<TripsRepository>((ref) {
  return TripsRepository(ref.read(dioProvider));
});

final airportsProvider =
    FutureProvider.family<List<Airport>, String?>((ref, country) async {
  final repo = ref.read(tripsRepositoryProvider);
  return repo.listAirports(country: country);
});

class MyTripsNotifier extends AsyncNotifier<List<Trip>> {
  @override
  Future<List<Trip>> build() async {
    final repo = ref.read(tripsRepositoryProvider);
    return repo.listTrips();
  }

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(
      () => ref.read(tripsRepositoryProvider).listTrips(),
    );
  }

  Future<Trip> create({
    required String originIata,
    required String destinationIata,
    required DateTime departureAt,
    required int capacityKg,
    String flightNumber = '',
    String notes = '',
  }) async {
    final repo = ref.read(tripsRepositoryProvider);
    final trip = await repo.createTrip(
      originIata: originIata,
      destinationIata: destinationIata,
      departureAt: departureAt,
      capacityKg: capacityKg,
      flightNumber: flightNumber,
      notes: notes,
    );
    final current = state.value ?? const <Trip>[];
    state = AsyncValue.data([trip, ...current]);
    return trip;
  }

  Future<void> cancel(int id) async {
    final repo = ref.read(tripsRepositoryProvider);
    final updated = await repo.cancelTrip(id);
    final current = state.value ?? const <Trip>[];
    state = AsyncValue.data([
      for (final t in current) t.id == id ? updated : t,
    ]);
  }
}

final myTripsProvider =
    AsyncNotifierProvider<MyTripsNotifier, List<Trip>>(MyTripsNotifier.new);

class TripSearchParams {
  const TripSearchParams({
    this.originIata,
    this.destinationIata,
    this.minCapacityKg,
  });
  final String? originIata;
  final String? destinationIata;
  final int? minCapacityKg;

  @override
  bool operator ==(Object other) =>
      other is TripSearchParams &&
      other.originIata == originIata &&
      other.destinationIata == destinationIata &&
      other.minCapacityKg == minCapacityKg;

  @override
  int get hashCode =>
      Object.hash(originIata, destinationIata, minCapacityKg);
}

final tripSearchProvider = FutureProvider.autoDispose
    .family<List<Trip>, TripSearchParams>((ref, p) async {
  return ref.read(tripsRepositoryProvider).searchTrips(
        originIata: p.originIata,
        destinationIata: p.destinationIata,
        minCapacityKg: p.minCapacityKg,
      );
});
