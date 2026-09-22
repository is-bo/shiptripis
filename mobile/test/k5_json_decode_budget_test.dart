// K5 13.11: what JSON parsing actually costs on the UI isolate.
//
// Dio 5.11's default transformer (`FusedTransformer`, isolate threshold
// 50 KiB) already decodes any body of 50 KiB or more in a background isolate;
// smaller bodies, and every model `fromJson`, run on the UI isolate. This
// times both halves for the largest realistic payloads the app reads, built
// in the current API shapes, so the "move parsing to an isolate?" question is
// answered with numbers instead of instinct.
//
// Host numbers are converted to a low-end phone estimate with the reference
// Dio and Flutter both use: 50 KB of JSON takes ~2.5 ms on a Moto G4. The
// same 50 KB is decoded here first, and its host time sets the scale.
//
// The assertions are deliberately loose — a 10x regression trips them, a busy
// CI runner does not. The printed table is the measurement.

// ignore_for_file: avoid_print

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/domain/chat.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/delivery_request.dart';
import 'package:shiptrip/domain/notification.dart';

/// Dio's own isolate threshold, from `FusedTransformer` in dio 5.11.0.
const _dioIsolateThreshold = 50 * 1024;

/// Moto G4 reference for 50 KB, per the Flutter/Dio source comment.
const _lowEndMicrosFor50Kb = 2500;

/// Pixel 4 reference for the same 50 KB, from the same comment.
const _midMicrosFor50Kb = 400;

/// Frame budget the plan uses as the bar for moving work off the UI thread.
const _uiBudgetMicros = 8000;

final _utf8Json = const Utf8Decoder().fuse(const JsonDecoder());

String _iso(int day, [int hour = 10]) =>
    '2026-08-${(day % 28 + 1).toString().padLeft(2, '0')}'
    'T${hour.toString().padLeft(2, '0')}:15:42.123456Z';

Map<String, dynamic> _dealRow(int id) => {
  'id': id,
  'accepted_offer_id': 5000 + id,
  'match_id': 1000 + id,
  'delivery_request_id': 2000 + id,
  'journey_id': 3000 + id,
  'sender_id': 42,
  'traveler_id': 99,
  'status': 'completed',
  'activity_state': 'completed',
  'is_legacy': false,
  'cancellation_reason': '',
  'funded_at': _iso(id),
  'agreed_pickup_at': _iso(id, 12),
  'pickup_confirmed_at': _iso(id, 13),
  'delivery_code_available_at': _iso(id, 14),
  'delivery_code_released_at': _iso(id, 15),
  'delivery_confirmed_at': _iso(id, 16),
  'protection_ends_at': _iso(id + 2, 16),
  'rating_window_ends_at': _iso(id + 7, 16),
  'completed_at': _iso(id + 2, 17),
  'cancelled_at': null,
  'funded_scheduled_arrival_floor_at': _iso(id, 11),
  'arrival_confirmed_at': _iso(id, 15),
  'terms': {
    'currency': 'EUR',
    'traveler_reward_minor': 2500,
    'commission_rate_bps': 1500,
    'platform_fee_minor': 375,
    'sender_total_minor': 2875,
    'boost_amount_minor': 500,
    'boost_traveler_bonus_minor': 350,
    'boost_platform_fee_minor': 150,
    'traveler_total_minor': 2850,
    'platform_total_minor': 525,
    'sender_total_with_boost_minor': 3375,
    'business_settings_version': 10,
    'pricing_version': 'v1-j2-boost-reward-1',
    'policy_snapshot': {
      'canonical_currency': 'EUR',
      'commission_rate_bps': 1500,
      'pricing_version': 'v1-j2-boost-reward-1',
      'business_settings_version': 10,
      'pricing': {
        'currency': 'EUR',
        'matched_distance_band': '1000_2500_km',
        'matched_distance_precision': 'route',
        'actual_weight_kg': '4.500',
        'volumetric_weight_kg': '3.200',
        'chargeable_weight_kg': '4.500',
        'minimum_reward_eur_cents': 1800,
        'weight_component_eur_cents': 900,
        'distance_component_eur_cents': 1100,
        'urgency_multiplier': '1.00',
        'category_multiplier': '1.10',
      },
      'compatibility': {
        'matching_version': 'v1-route-2',
        'compatible': true,
        'rejection_codes': <String>[],
        'start_leg_id': 7001,
        'end_leg_id': 7002,
        'covered_leg_ids': [7001, 7002],
        'covered_leg_positions': [0, 1],
        'covered_legs': [
          for (final leg in [7001, 7002])
            {
              'id': leg,
              'position': leg - 7001,
              'transport_mode': 'flight',
              'origin_label': 'Alger',
              'destination_label': 'Paris',
              'depart_at': _iso(id, 8),
              'arrive_at': _iso(id, 11),
            },
        ],
        'estimated_pickup_window': {'start': _iso(id, 6), 'end': _iso(id, 8)},
        'estimated_delivery_window': {
          'start': _iso(id, 11),
          'end': _iso(id, 20),
        },
      },
      'policy': {
        'reservation': {'funding_window_minutes': 30, 'ttl_minutes': 1440},
      },
      'reservation': {'funding_window_minutes': 30, 'ttl_minutes': 1440},
    },
    'is_legacy': false,
    'created_at': _iso(id, 9),
  },
  'leg_allocations': [
    for (final leg in [7001, 7002])
      {
        'id': 9000 + leg,
        'journey_leg_id': leg,
        'journey_leg_position': leg - 7001,
        'allocated_weight_kg': '4.500',
        'status': 'consumed',
        'reserved_at': _iso(id, 9),
        'expires_at': null,
        'released_at': null,
        'release_reason': '',
      },
  ],
  'created_at': _iso(id, 9),
  'updated_at': _iso(id + 2, 17),
  'attention': {
    'can_reveal_pickup_code': false,
    'can_submit_pickup_code': false,
    'can_reveal_delivery_code': false,
    'can_submit_delivery_code': false,
    'can_rate': id.isEven,
  },
};

Map<String, dynamic> _location(int id, String city) => {
  'id': id,
  'kind': 'city',
  'public_label': '$city, Centre',
  'city': city,
  'region': '$city Region',
  'country_code': 'DZ',
  'precision': 'city',
  'coordinates_trusted': true,
  'canonical_place_id': id + 1,
};

Map<String, dynamic> _requestRow(int id) => {
  'id': id,
  'sender_id': 42,
  'target_traveler_id': null,
  'status': id.isEven ? 'completed' : 'open',
  'schema_version': 2,
  'pickup_location': _location(10 * id, 'Alger'),
  'delivery_location': _location(10 * id + 1, 'Paris'),
  'pickup_place': {
    'id': 8000 + id,
    'kind': 'city',
    'name': 'Alger',
    'country_code': 'DZ',
    'display_name': 'Alger, Algérie',
  },
  'delivery_place': {
    'id': 8100 + id,
    'kind': 'city',
    'name': 'Paris',
    'country_code': 'FR',
    'display_name': 'Paris, France',
  },
  'ready_window_start': _iso(id),
  'ready_window_end': _iso(id + 1),
  'deadline_at': _iso(id + 5),
  'actual_weight_kg': '4.500',
  'length_cm': '40.0',
  'width_cm': '30.0',
  'height_cm': '20.0',
  'declared_value_eur_cents': 12000,
  'sender_proposed_reward_eur_cents': 2500,
  'boost_eur_cents': 500,
  'total_offered_reward_eur_cents': 3000,
  'title': 'Coffret de gâteaux traditionnels $id',
  'description':
      'Boîte scellée de makrout et de baklawa, bien emballée. '
      'علبة حلويات تقليدية مغلفة بإحكام.',
  'handling_notes': 'Garder à plat, ne pas empiler.',
  'category': 'food',
  'fragile': true,
  'media': [
    {
      'id': 6000 + id,
      'purpose': 'item_photo',
      'content_type': 'image/jpeg',
      'size_bytes': 812345,
      'created_at': _iso(id),
    },
  ],
  'no_prohibited_items': true,
  'accurate_description': true,
  'customs_responsibility': true,
  'item_photo_media_id': 6000 + id,
  'created_at': _iso(id),
  'updated_at': _iso(id + 1),
};

Map<String, dynamic> _notificationRow(int id) => {
  'id': id,
  'channel': const [
    'deal.updated',
    'chat.message',
    'offer.created',
    'payout.status_changed',
  ][id % 4],
  'event_id': '3f1c9a2e-7b4d-4e8a-9c21-${id.toString().padLeft(12, '0')}',
  'payload': {
    'event': 'deal.updated',
    'deal_id': 100 + id,
    'match_id': 1000 + id,
    'parcel_id': 2000 + id,
    'status': 'in_transit',
    'actor_id': 99,
    'occurred_at': _iso(id),
  },
  'read_at': id.isEven ? _iso(id, 11) : null,
  'resolved': id % 3 == 0,
  'created_at': _iso(id),
};

Map<String, dynamic> _chatRow(int id) => {
  'id': id,
  'match_id': 1001,
  'sender_id': id.isEven ? 42 : 99,
  'body': id.isEven
      ? 'Bonjour, je serai à l’aéroport vers 14h, terminal 1. Ça vous va ?'
      : 'مرحبا، نعم هذا مناسب. سأكون هناك قبل الموعد بعشر دقائق.',
  'created_at': _iso(id),
  'read_at': _iso(id, 11),
  'client_message_id': 'c-${id.toString().padLeft(8, '0')}-a1b2',
};

Uint8List _bytes(Object body) =>
    Uint8List.fromList(utf8.encode(jsonEncode(body)));

/// Median wall time of [body], in microseconds, after a JIT warm-up.
int _medianMicros(void Function() body, {int warmup = 40, int runs = 80}) {
  for (var i = 0; i < warmup; i++) {
    body();
  }
  final samples = <int>[];
  final watch = Stopwatch();
  for (var i = 0; i < runs; i++) {
    watch
      ..reset()
      ..start();
    body();
    watch.stop();
    samples.add(watch.elapsedMicroseconds);
  }
  samples.sort();
  return samples[samples.length ~/ 2];
}

List<dynamic> _results(Object? decoded) =>
    (decoded! as Map<String, dynamic>)['results'] as List<dynamic>;

/// Exactly what the repositories do with a list body, copy included.
List<T> _mapRows<T>(
  List<dynamic> rows,
  T Function(Map<String, dynamic>) fromJson,
) => rows
    .whereType<Map>()
    .map((r) => fromJson(Map<String, dynamic>.from(r)))
    .toList(growable: false);

class _Case {
  _Case(this.name, this.body, this.parse);
  final String name;
  final Uint8List body;
  final void Function(Object? decoded) parse;
}

void main() {
  test('JSON decode + fromJson cost for the largest realistic payloads', () {
    // Calibration: 50 KB of the same kind of JSON, decoded on this host.
    final calibrationRows = <Object>[];
    var calibration = _bytes(calibrationRows);
    while (calibration.length < 50 * 1000) {
      calibrationRows.add(_dealRow(calibrationRows.length));
      calibration = _bytes(calibrationRows);
    }
    final hostMicrosFor50Kb = _medianMicros(
      () => _utf8Json.convert(calibration),
    );
    final scale = _lowEndMicrosFor50Kb / hostMicrosFor50Kb;

    final cases = [
      _Case(
        'Deals, 100 rows (page_size max)',
        _bytes({
          'count': 100,
          'next': null,
          'previous': null,
          'results': [for (var i = 0; i < 100; i++) _dealRow(i)],
        }),
        (decoded) => _mapRows(_results(decoded), Deal.fromJson),
      ),
      _Case(
        'Deals, 20 rows (default page)',
        _bytes({
          'count': 20,
          'next': null,
          'previous': null,
          'results': [for (var i = 0; i < 20; i++) _dealRow(i)],
        }),
        (decoded) => _mapRows(_results(decoded), Deal.fromJson),
      ),
      _Case(
        'Own requests, 100 rows (bare array)',
        _bytes([for (var i = 0; i < 100; i++) _requestRow(i)]),
        (decoded) => _mapRows(decoded! as List, DeliveryRequest.fromJson),
      ),
      _Case(
        'Notifications, 100 rows (page_size max)',
        _bytes({
          'count': 100,
          'next': null,
          'previous': null,
          'results': [for (var i = 0; i < 100; i++) _notificationRow(i)],
        }),
        (decoded) =>
            NotificationPage.fromJson(decoded! as Map<String, dynamic>),
      ),
      _Case(
        'Chat history, 200 messages (page_size max)',
        _bytes({
          'count': 200,
          'has_more': true,
          'oldest_id': 1,
          'latest_id': 200,
          'results': [for (var i = 1; i <= 200; i++) _chatRow(i)],
        }),
        (decoded) => ChatMessagePage.fromJson(decoded! as Map<String, dynamic>),
      ),
    ];

    print(
      'K5 JSON budget — host 50 KB decode ${hostMicrosFor50Kb}us; '
      'low-end scale x${scale.toStringAsFixed(1)} (Moto G4 ~2.5 ms / 50 KB)',
    );
    print(
      '| Payload | Bytes | Decode on | decode host us | fromJson host us '
      '| UI-thread host us | Pixel 4 est. ms | Moto G4 est. ms |',
    );
    for (final c in cases) {
      final decodeMicros = _medianMicros(() => _utf8Json.convert(c.body));
      final decoded = _utf8Json.convert(c.body);
      final parseMicros = _medianMicros(() => c.parse(decoded));
      final inIsolate = c.body.length >= _dioIsolateThreshold;
      // What the UI isolate actually pays: the model mapping always, the
      // decode only when Dio keeps it on the calling isolate.
      final uiMicros = parseMicros + (inIsolate ? 0 : decodeMicros);
      final lowEndMillis = uiMicros * scale / 1000;
      final midMillis = uiMicros * _midMicrosFor50Kb / hostMicrosFor50Kb / 1000;
      print(
        '| ${c.name} | ${c.body.length} | '
        '${inIsolate ? 'isolate' : 'UI'} | $decodeMicros | $parseMicros | '
        '$uiMicros | ${midMillis.toStringAsFixed(2)} | '
        '${lowEndMillis.toStringAsFixed(2)} |',
      );

      // A generous guard: the host is several times a low-end phone, so a
      // UI-thread cost past a whole frame budget here is a real regression.
      expect(
        uiMicros,
        lessThan(_uiBudgetMicros),
        reason: '${c.name} blocks the UI isolate for ${uiMicros}us on host',
      );
    }
  });
}
