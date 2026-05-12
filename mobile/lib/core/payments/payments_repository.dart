import 'package:dio/dio.dart';

class PaymentsFailure implements Exception {
  PaymentsFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

class PaymentIntent {
  const PaymentIntent({
    required this.id,
    required this.offerId,
    required this.payerId,
    required this.provider,
    required this.providerIntentId,
    required this.amountMinor,
    required this.currency,
    required this.status,
    this.succeededAt,
  });

  factory PaymentIntent.fromJson(Map<String, dynamic> j) => PaymentIntent(
        id: j['id'] as int,
        offerId: j['offer_id'] as int,
        payerId: j['payer_id'] as int,
        provider: j['provider'] as String,
        providerIntentId: (j['provider_intent_id'] as String?) ?? '',
        amountMinor: j['amount_minor'] as int,
        currency: j['currency'] as String,
        status: j['status'] as String,
        succeededAt: j['succeeded_at'] == null
            ? null
            : DateTime.tryParse(j['succeeded_at'] as String),
      );

  final int id;
  final int offerId;
  final int payerId;
  final String provider;
  final String providerIntentId;
  final int amountMinor;
  final String currency;
  final String status;
  final DateTime? succeededAt;

  bool get succeeded => status == 'succeeded';
}

class PaymentsRepository {
  PaymentsRepository(this._dio);
  final Dio _dio;

  /// Create a payment intent for the accepted offer.
  ///
  /// V1 always routes through the mock provider, which returns
  /// `status=succeeded` instantly. Sender UI shows a 1–2s processing
  /// animation regardless to feel realistic.
  Future<PaymentIntent> createIntent({
    required int offerId,
    String currency = 'DZD',
    String? idempotencyKey,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/api/payments/intents/create',
      data: {
        'offer_id': offerId,
        'currency': currency,
        if (idempotencyKey != null && idempotencyKey.isNotEmpty)
          'idempotency_key': idempotencyKey,
      },
    );
    if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
      return PaymentIntent.fromJson(r.data!);
    }
    throw PaymentsFailure(_extractMessage(r) ?? 'Payment could not be started.');
  }

  Future<PaymentIntent> getIntent(int id) async {
    final r = await _dio.get<Map<String, dynamic>>('/api/payments/intents/$id');
    if (r.statusCode == 200 && r.data != null) {
      return PaymentIntent.fromJson(r.data!);
    }
    throw PaymentsFailure(_extractMessage(r) ?? 'Could not load payment.');
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
