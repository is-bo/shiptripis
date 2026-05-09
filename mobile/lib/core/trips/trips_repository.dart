import 'package:dio/dio.dart';

class TripsFailure implements Exception {
  TripsFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

class Airport {
  const Airport({
    required this.iata,
    required this.city,
    required this.name,
    required this.country,
  });

  factory Airport.fromJson(Map<String, dynamic> j) => Airport(
        iata: j['iata'] as String,
        city: j['city'] as String,
        name: j['name'] as String,
        country: j['country'] as String,
      );

  final String iata;
  final String city;
  final String name;
  final String country;
}

class Trip {
  const Trip({
    required this.id,
    required this.travelerId,
    required this.origin,
    required this.destination,
    required this.departureAt,
    required this.capacityKg,
    required this.flightNumber,
    required this.notes,
    required this.status,
  });

  factory Trip.fromJson(Map<String, dynamic> j) => Trip(
        id: j['id'] as int,
        travelerId: j['traveler_id'] as int,
        origin: Airport.fromJson(Map<String, dynamic>.from(j['origin'] as Map)),
        destination:
            Airport.fromJson(Map<String, dynamic>.from(j['destination'] as Map)),
        departureAt: DateTime.parse(j['departure_at'] as String),
        capacityKg: j['capacity_kg'] as int,
        flightNumber: (j['flight_number'] as String?) ?? '',
        notes: (j['notes'] as String?) ?? '',
        status: j['status'] as String,
      );

  final int id;
  final int travelerId;
  final Airport origin;
  final Airport destination;
  final DateTime departureAt;
  final int capacityKg;
  final String flightNumber;
  final String notes;
  final String status;
}

class TripsRepository {
  TripsRepository(this._dio);
  final Dio _dio;

  Future<List<Airport>> listAirports({String? country}) async {
    final r = await _dio.get<dynamic>(
      '/api/airports',
      queryParameters: country == null ? null : {'country': country},
    );
    if (r.statusCode == 200 && r.data is List) {
      return (r.data as List)
          .map((e) => Airport.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    }
    throw TripsFailure(_extractMessage(r) ?? 'Could not load airports.');
  }

  Future<List<Trip>> listTrips({String? status}) async {
    final r = await _dio.get<dynamic>(
      '/api/trips',
      queryParameters: status == null ? null : {'status': status},
    );
    if (r.statusCode == 200 && r.data is List) {
      return (r.data as List)
          .map((e) => Trip.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    }
    throw TripsFailure(_extractMessage(r) ?? 'Could not load trips.');
  }

  Future<Trip> createTrip({
    required String originIata,
    required String destinationIata,
    required DateTime departureAt,
    required int capacityKg,
    String flightNumber = '',
    String notes = '',
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/api/trips',
      data: {
        'origin': originIata,
        'destination': destinationIata,
        'departure_at': departureAt.toUtc().toIso8601String(),
        'capacity_kg': capacityKg,
        'flight_number': flightNumber,
        'notes': notes,
      },
    );
    if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
      return Trip.fromJson(r.data!);
    }
    throw TripsFailure(_extractMessage(r) ?? 'Could not create trip.');
  }

  Future<Trip> cancelTrip(int id) async {
    final r = await _dio.post<Map<String, dynamic>>('/api/trips/$id/cancel');
    if (r.statusCode == 200 && r.data != null) {
      return Trip.fromJson(r.data!);
    }
    throw TripsFailure(_extractMessage(r) ?? 'Could not cancel trip.');
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
