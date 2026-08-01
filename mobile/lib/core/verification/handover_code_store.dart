/// Local persistence for handover-code plaintext.
///
/// The server stores only an argon2id hash, so it can never hand the digits
/// back — the plaintext exists exactly once, in the `handover.code_issued` WS
/// event. Before this store that plaintext lived only in memory, so killing
/// the app lost it and the only way back to a visible code was to *rotate*
/// one, which silently invalidated the code the counterparty may already have
/// written down.
///
/// Codes are short-lived, single-purpose secrets for the holder's own eyes,
/// so they live in the same encrypted keystore as the auth tokens rather than
/// plain preferences. [clear] is wired into sign-out alongside the tokens.
library;

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

final handoverCodeStoreProvider =
    Provider<HandoverCodeStore>((ref) => HandoverCodeStore());

/// One stored code. [kind] is the wire value (`pickup` / `delivery`); a match
/// can hold one of each simultaneously.
class StoredHandoverCode {
  const StoredHandoverCode({
    required this.matchId,
    required this.kind,
    required this.code,
    required this.issuedAt,
  });

  final int matchId;
  final String kind;
  final String code;
  final DateTime issuedAt;

  Map<String, dynamic> toJson() => {
        'match_id': matchId,
        'kind': kind,
        'code': code,
        'issued_at': issuedAt.toIso8601String(),
      };

  static StoredHandoverCode? fromJson(Map<String, dynamic> j) {
    final mid = (j['match_id'] as num?)?.toInt();
    final kind = j['kind'] as String?;
    final code = j['code'] as String?;
    final at = DateTime.tryParse((j['issued_at'] as String?) ?? '');
    if (mid == null || kind == null || code == null || at == null) return null;
    return StoredHandoverCode(
      matchId: mid,
      kind: kind,
      code: code,
      issuedAt: at,
    );
  }
}

class HandoverCodeStore {
  HandoverCodeStore([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const _kCodes = 'handover.codes';

  /// Read every persisted code, keyed by `<matchId>:<kind>`.
  ///
  /// A corrupt or partially-written blob is treated as empty rather than
  /// thrown: losing the cache degrades to the old "regenerate" path, whereas
  /// throwing here would break the screen entirely.
  Future<Map<String, StoredHandoverCode>> readAll() async {
    final raw = await _storage.read(key: _kCodes);
    if (raw == null || raw.isEmpty) return {};
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return {};
      final out = <String, StoredHandoverCode>{};
      decoded.forEach((k, v) {
        if (v is Map<String, dynamic>) {
          final c = StoredHandoverCode.fromJson(v);
          if (c != null) out['$k'] = c;
        }
      });
      return out;
    } catch (_) {
      return {};
    }
  }

  /// Persist one code, replacing any previous code for the same match+kind
  /// (a rotation supersedes what came before).
  Future<void> save(StoredHandoverCode code) async {
    final all = await readAll();
    all[keyFor(code.matchId, code.kind)] = code;
    await _write(all);
  }

  /// Drop a single code — used once it has been consumed (the traveler
  /// verified it), so we don't keep a dead secret around.
  Future<void> remove(int matchId, String kind) async {
    final all = await readAll();
    if (all.remove(keyFor(matchId, kind)) == null) return;
    await _write(all);
  }

  /// Wipe everything. Called on sign-out — codes belong to the signed-in user.
  Future<void> clear() => _storage.delete(key: _kCodes);

  static String keyFor(int matchId, String kind) => '$matchId:$kind';

  Future<void> _write(Map<String, StoredHandoverCode> all) async {
    final encoded = <String, dynamic>{
      for (final e in all.entries) e.key: e.value.toJson(),
    };
    await _storage.write(key: _kCodes, value: jsonEncode(encoded));
  }
}
