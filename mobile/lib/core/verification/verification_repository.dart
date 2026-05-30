import 'package:dio/dio.dart';

/// Repository for handover codes (apps.verification on the server).
///
/// Two endpoints in V1:
///   POST /api/matches/[id]/handover/issue     -- sender only
///   POST /api/matches/[id]/handover/verify    -- traveler only
///
/// The plaintext `code` is returned ONCE on issue; afterwards the server
/// only stores an argon2id hash. We never persist the plaintext on device.
class VerificationFailure implements Exception {
  VerificationFailure(this.message, {this.kind = 'error'});
  final String message;
  final String kind; // 'invalid' | 'locked' | 'state' | 'error'
  @override
  String toString() => message;
}

enum HandoverKind {
  pickup,
  delivery;

  String get wire => switch (this) {
        HandoverKind.pickup => 'pickup',
        HandoverKind.delivery => 'delivery',
      };
}

class IssuedCode {
  const IssuedCode({
    required this.handoverId,
    required this.code,
    required this.kind,
  });
  factory IssuedCode.fromJson(Map<String, dynamic> j) => IssuedCode(
        handoverId: j['handover_id'] as int,
        code: j['code'] as String,
        kind: j['kind'] as String,
      );
  final int handoverId;
  final String code; // 6-digit, only returned once
  final String kind;
}

class VerifiedCode {
  const VerifiedCode({required this.id, required this.kind, required this.status});
  factory VerifiedCode.fromJson(Map<String, dynamic> j) => VerifiedCode(
        id: j['id'] as int,
        kind: j['kind'] as String,
        status: j['status'] as String,
      );
  final int id;
  final String kind;
  final String status;
}

/// Metadata about an active handover code — plaintext NOT included.
/// Plaintext is delivered exactly once via the WS `handover.code_issued`
/// event and held in [LiveEventState.codesByMatch]. This object lets the
/// UI confirm a code exists (so it can render the cached plaintext) and
/// surface metadata like issued-at without rotating the code.
class ActiveCodeInfo {
  const ActiveCodeInfo({
    required this.id,
    required this.kind,
    required this.status,
    required this.createdAt,
  });
  factory ActiveCodeInfo.fromJson(Map<String, dynamic> j) => ActiveCodeInfo(
        id: j['id'] as int,
        kind: j['kind'] as String,
        status: j['status'] as String,
        createdAt: DateTime.parse(j['created_at'] as String),
      );
  final int id;
  final String kind;
  final String status;
  final DateTime createdAt;
}

class VerificationRepository {
  VerificationRepository(this._dio);
  final Dio _dio;

  Future<IssuedCode> issue({
    required int matchId,
    required HandoverKind kind,
  }) async {
    try {
      final r = await _dio.post<Map<String, dynamic>>(
        '/api/matches/$matchId/handover/issue',
        data: {'kind': kind.wire},
      );
      if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
        return IssuedCode.fromJson(r.data!);
      }
      throw VerificationFailure(_msg(r) ?? 'Could not issue code.');
    } on DioException catch (e) {
      throw VerificationFailure(_msg(e.response) ?? 'Could not issue code.');
    }
  }

  /// Fetches metadata about an existing ACTIVE code without rotating it.
  /// Returns null when no active code exists (server 404). Plaintext is
  /// never returned by this endpoint — only the WS issue event ever carries
  /// the plaintext. UI should read plaintext from LiveEventState.
  Future<ActiveCodeInfo?> getActiveCode({
    required int matchId,
    required HandoverKind kind,
  }) async {
    try {
      final r = await _dio.get<Map<String, dynamic>>(
        '/api/matches/$matchId/handover/code',
        queryParameters: {'kind': kind.wire},
      );
      if (r.statusCode == 200 && r.data != null) {
        return ActiveCodeInfo.fromJson(r.data!);
      }
      return null;
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      throw VerificationFailure(_msg(e.response) ?? 'Could not load code.');
    }
  }

  Future<VerifiedCode> verify({
    required int matchId,
    required HandoverKind kind,
    required String code,
  }) async {
    try {
      final r = await _dio.post<Map<String, dynamic>>(
        '/api/matches/$matchId/handover/verify',
        data: {'kind': kind.wire, 'code': code},
      );
      if (r.statusCode == 200 && r.data != null) {
        return VerifiedCode.fromJson(r.data!);
      }
      throw VerificationFailure(_msg(r) ?? 'Could not verify code.');
    } on DioException catch (e) {
      final code = e.response?.statusCode ?? 0;
      final kind = switch (code) {
        400 => 'invalid',
        409 => 'state',
        429 => 'locked',
        _ => 'error',
      };
      throw VerificationFailure(
        _msg(e.response) ?? 'Could not verify code.',
        kind: kind,
      );
    }
  }

  String? _msg(Response? r) {
    if (r == null) return null;
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
