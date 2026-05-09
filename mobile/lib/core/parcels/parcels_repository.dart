import 'package:dio/dio.dart';

import '../trips/trips_repository.dart' show Airport;

class ParcelsFailure implements Exception {
  ParcelsFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

class ParcelMedia {
  const ParcelMedia({
    required this.id,
    required this.bucket,
    required this.objectKey,
    required this.contentType,
    required this.bytes,
  });
  factory ParcelMedia.fromJson(Map<String, dynamic> j) => ParcelMedia(
        id: j['id'] as int,
        bucket: j['bucket'] as String,
        objectKey: j['object_key'] as String,
        contentType: j['content_type'] as String? ?? 'image/jpeg',
        bytes: j['bytes'] as int? ?? 0,
      );
  final int id;
  final String bucket;
  final String objectKey;
  final String contentType;
  final int bytes;
}

class Parcel {
  const Parcel({
    required this.id,
    required this.senderId,
    required this.kind,
    required this.origin,
    required this.destination,
    required this.pickupCity,
    required this.deliveryCity,
    required this.weightKg,
    required this.itemType,
    required this.description,
    required this.deadlineAt,
    required this.status,
    required this.media,
    required this.baseAmountDzd,
    required this.productUrl,
    required this.storeName,
    required this.productPriceDzd,
    required this.createdAt,
  });

  factory Parcel.fromJson(Map<String, dynamic> j) => Parcel(
        id: j['id'] as int,
        senderId: j['sender_id'] as int,
        kind: j['kind'] as String,
        origin: Airport.fromJson(Map<String, dynamic>.from(j['origin'] as Map)),
        destination:
            Airport.fromJson(Map<String, dynamic>.from(j['destination'] as Map)),
        pickupCity: (j['pickup_city'] as String?) ?? '',
        deliveryCity: (j['delivery_city'] as String?) ?? '',
        weightKg: j['weight_kg'] as int,
        itemType: j['item_type'] as String,
        description: (j['description'] as String?) ?? '',
        deadlineAt: j['deadline_at'] == null
            ? null
            : DateTime.parse(j['deadline_at'] as String),
        status: j['status'] as String,
        media: ((j['media'] as List?) ?? [])
            .map((e) => ParcelMedia.fromJson(Map<String, dynamic>.from(e as Map)))
            .toList(),
        baseAmountDzd: j['base_amount_dzd'] as int?,
        productUrl: j['product_url'] as String?,
        storeName: j['store_name'] as String?,
        productPriceDzd: j['product_price_dzd'] as int?,
        createdAt: DateTime.parse(j['created_at'] as String),
      );

  final int id;
  final int senderId;
  final String kind; // 'delivery' or 'product'
  final Airport origin;
  final Airport destination;
  final String pickupCity;
  final String deliveryCity;
  final int weightKg;
  final String itemType;
  final String description;
  final DateTime? deadlineAt;
  final String status;
  final List<ParcelMedia> media;
  final int? baseAmountDzd;
  final String? productUrl;
  final String? storeName;
  final int? productPriceDzd;
  final DateTime createdAt;
}

class ParcelsRepository {
  ParcelsRepository(this._dio);
  final Dio _dio;

  Future<List<Parcel>> listMine({String? status, String? kind}) async {
    final r = await _dio.get<dynamic>(
      '/api/parcels',
      queryParameters: {
        if (status != null) 'status': status,
        if (kind != null) 'kind': kind,
      },
    );
    if (r.statusCode == 200 && r.data is List) {
      return (r.data as List)
          .map((e) => Parcel.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    }
    throw ParcelsFailure(_extractMessage(r) ?? 'Could not load requests.');
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
    DateTime? deadlineAt,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/api/parcels/delivery',
      data: {
        'origin': originIata,
        'destination': destinationIata,
        'weight_kg': weightKg,
        'item_type': itemType,
        'description': description,
        'pickup_city': pickupCity,
        'delivery_city': deliveryCity,
        'base_amount_dzd': baseAmountDzd,
        if (deadlineAt != null)
          'deadline_at': deadlineAt.toUtc().toIso8601String(),
      },
    );
    if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
      return Parcel.fromJson(r.data!);
    }
    throw ParcelsFailure(_extractMessage(r) ?? 'Could not create request.');
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
    DateTime? deadlineAt,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/api/parcels/product',
      data: {
        'origin': originIata,
        'destination': destinationIata,
        'weight_kg': weightKg,
        'item_type': itemType,
        'product_price_dzd': productPriceDzd,
        'product_url': productUrl,
        'store_name': storeName,
        'description': description,
        'pickup_city': pickupCity,
        'delivery_city': deliveryCity,
        if (deadlineAt != null)
          'deadline_at': deadlineAt.toUtc().toIso8601String(),
      },
    );
    if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
      return Parcel.fromJson(r.data!);
    }
    throw ParcelsFailure(_extractMessage(r) ?? 'Could not create request.');
  }

  Future<Parcel> cancel(int id) async {
    final r = await _dio.post<Map<String, dynamic>>('/api/parcels/$id/cancel');
    if (r.statusCode == 200 && r.data != null) {
      return Parcel.fromJson(r.data!);
    }
    throw ParcelsFailure(_extractMessage(r) ?? 'Could not cancel request.');
  }

  String? _extractMessage(Response r) {
    final d = r.data;
    if (d is Map) {
      if (d['detail'] is String) return d['detail'] as String;
      for (final v in d.values) {
        if (v is List && v.isNotEmpty && v.first is String) {
          return v.first as String;
        }
        if (v is String) return v;
      }
    }
    return null;
  }
}
