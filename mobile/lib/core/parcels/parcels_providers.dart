import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
import 'parcels_repository.dart';

final parcelsRepositoryProvider = Provider<ParcelsRepository>((ref) {
  return ParcelsRepository(ref.read(dioProvider));
});

class DeliveryQuoteParams {
  const DeliveryQuoteParams({
    required this.weightKg,
    this.originIata,
    this.destinationIata,
  });
  final int weightKg;
  final String? originIata;
  final String? destinationIata;

  @override
  bool operator ==(Object other) =>
      other is DeliveryQuoteParams &&
      other.weightKg == weightKg &&
      other.originIata == originIata &&
      other.destinationIata == destinationIata;

  @override
  int get hashCode => Object.hash(weightKg, originIata, destinationIata);
}

final deliveryQuoteProvider = FutureProvider.autoDispose
    .family<DeliveryQuote, DeliveryQuoteParams>((ref, p) async {
  return ref.read(parcelsRepositoryProvider).quoteDelivery(
        weightKg: p.weightKg,
        originIata: p.originIata,
        destinationIata: p.destinationIata,
      );
});

class MyParcelsNotifier extends AsyncNotifier<List<Parcel>> {
  @override
  Future<List<Parcel>> build() async {
    return ref.read(parcelsRepositoryProvider).listMine();
  }

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(
      () => ref.read(parcelsRepositoryProvider).listMine(),
    );
  }

  Future<Parcel> createDelivery({
    required String originIata,
    required String destinationIata,
    required int weightKg,
    required String itemType,
    required int baseAmountDzd,
    String description = '',
    String pickupCity = '',
    String deliveryCity = '',
  }) async {
    final repo = ref.read(parcelsRepositoryProvider);
    final p = await repo.createDelivery(
      originIata: originIata,
      destinationIata: destinationIata,
      weightKg: weightKg,
      itemType: itemType,
      baseAmountDzd: baseAmountDzd,
      description: description,
      pickupCity: pickupCity,
      deliveryCity: deliveryCity,
    );
    state = AsyncValue.data([p, ...(state.value ?? const <Parcel>[])]);
    return p;
  }

  Future<Parcel> createProduct({
    required String originIata,
    required String destinationIata,
    required int weightKg,
    required String itemType,
    required int productPriceDzd,
    String productUrl = '',
    String storeName = '',
    String description = '',
    String pickupCity = '',
    String deliveryCity = '',
  }) async {
    final repo = ref.read(parcelsRepositoryProvider);
    final p = await repo.createProduct(
      originIata: originIata,
      destinationIata: destinationIata,
      weightKg: weightKg,
      itemType: itemType,
      productPriceDzd: productPriceDzd,
      productUrl: productUrl,
      storeName: storeName,
      description: description,
      pickupCity: pickupCity,
      deliveryCity: deliveryCity,
    );
    state = AsyncValue.data([p, ...(state.value ?? const <Parcel>[])]);
    return p;
  }

  Future<void> cancel(int id) async {
    final repo = ref.read(parcelsRepositoryProvider);
    final updated = await repo.cancel(id);
    final cur = state.value ?? const <Parcel>[];
    state = AsyncValue.data([
      for (final p in cur) p.id == id ? updated : p,
    ]);
  }
}

final myParcelsProvider =
    AsyncNotifierProvider<MyParcelsNotifier, List<Parcel>>(MyParcelsNotifier.new);
