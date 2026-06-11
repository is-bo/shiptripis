import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
import 'verification_repository.dart';

final verificationRepositoryProvider = Provider<VerificationRepository>((ref) {
  return VerificationRepository(ref.read(dioProvider));
});

class ActiveCodeParams {
  const ActiveCodeParams({required this.matchId, required this.kind});
  final int matchId;
  final HandoverKind kind;

  @override
  bool operator ==(Object other) =>
      other is ActiveCodeParams &&
      other.matchId == matchId &&
      other.kind == kind;

  @override
  int get hashCode => Object.hash(matchId, kind);
}

/// Existence check for an ACTIVE handover code without rotating it. Returns
/// null when no active code exists. Plaintext is delivered exactly once via
/// the WS `handover.code_issued` event; the UI reads plaintext from
/// `LiveEventState.codesByMatch`.
final activeCodeProvider = FutureProvider.autoDispose
    .family<ActiveCodeInfo?, ActiveCodeParams>((ref, p) async {
  return ref
      .read(verificationRepositoryProvider)
      .getActiveCode(matchId: p.matchId, kind: p.kind);
});
