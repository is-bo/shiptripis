/// KYC wizard state.
///
/// One [KycDraft] holds the whole in-progress submission: document type, the
/// three photos, and the idempotency key. The key is minted ONCE when the
/// draft starts and reused for every retry, so a failed upload retried over a
/// flaky connection overwrites the same S3 objects instead of orphaning them
/// (and Django dedupes the row on it). It's only re-minted when the user
/// starts a genuinely new submission.
library;

import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
import 'kyc_repository.dart';

final kycRepositoryProvider = Provider<KycRepository>((ref) {
  return KycRepository(ref.read(dioProvider));
});

/// Which photo a capture step is for.
enum KycShot { front, back, selfie }

class KycDraft {
  const KycDraft({
    required this.idempotencyKey,
    this.documentType,
    this.front,
    this.back,
    this.selfie,
    this.submitting = false,
    this.error,
    this.result,
  });

  final String idempotencyKey;
  final KycDocumentType? documentType;
  final File? front;
  final File? back;
  final File? selfie;
  final bool submitting;
  final String? error;
  final KycSubmissionResult? result;

  static KycDraft fresh() => KycDraft(idempotencyKey: newIdempotencyKey());

  File? shot(KycShot s) => switch (s) {
        KycShot.front => front,
        KycShot.back => back,
        KycShot.selfie => selfie,
      };

  /// Back is skipped entirely for a passport.
  bool get needsBack => documentType?.needsBack ?? true;

  /// The shots this document type actually requires, in capture order.
  List<KycShot> get requiredShots => [
        KycShot.front,
        if (needsBack) KycShot.back,
        KycShot.selfie,
      ];

  bool has(KycShot s) => shot(s) != null;

  int get capturedCount => requiredShots.where(has).length;

  bool get isComplete =>
      documentType != null && requiredShots.every(has);

  KycDraft copy({
    KycDocumentType? documentType,
    File? front,
    File? back,
    File? selfie,
    bool? submitting,
    Object? error = _sentinel,
    KycSubmissionResult? result,
    bool clearBack = false,
  }) {
    return KycDraft(
      idempotencyKey: idempotencyKey,
      documentType: documentType ?? this.documentType,
      front: front ?? this.front,
      back: clearBack ? null : (back ?? this.back),
      selfie: selfie ?? this.selfie,
      submitting: submitting ?? this.submitting,
      error: identical(error, _sentinel) ? this.error : error as String?,
      result: result ?? this.result,
    );
  }
}

const _sentinel = Object();

class KycDraftNotifier extends Notifier<KycDraft> {
  @override
  KycDraft build() => KycDraft.fresh();

  void pickDocumentType(KycDocumentType type) {
    // Switching to a passport drops any back photo already taken — it isn't
    // part of that submission and would be an unused upload.
    final dropBack = !type.needsBack;
    state = state.copy(
      documentType: type,
      clearBack: dropBack,
      error: null,
    );
  }

  /// Attach a captured photo. Returns an error message when the file is
  /// rejected client-side (wrong format / too big / empty), else null.
  String? attach(KycShot slot, File file) {
    final problem = KycRepository.validationErrorFor(file);
    if (problem != null) {
      state = state.copy(error: problem);
      return problem;
    }
    state = switch (slot) {
      KycShot.front => state.copy(front: file, error: null),
      KycShot.back => state.copy(back: file, error: null),
      KycShot.selfie => state.copy(selfie: file, error: null),
    };
    return null;
  }

  void clearError() {
    if (state.error != null) state = state.copy(error: null);
  }

  /// Start over with a new idempotency key — a genuinely different submission.
  void reset() => state = KycDraft.fresh();

  Future<bool> submit() async {
    final d = state;
    if (!d.isComplete || d.submitting) return false;
    state = d.copy(submitting: true, error: null);
    try {
      final result = await ref.read(kycRepositoryProvider).submit(
            documentType: d.documentType!,
            idempotencyKey: d.idempotencyKey,
            front: d.front!,
            back: d.needsBack ? d.back : null,
            selfie: d.selfie!,
          );
      state = state.copy(submitting: false, result: result, error: null);
      // The profile badge reads `is_kyc_verified` off /me; refresh so an
      // instantly-approved submission shows up without a restart.
      await ref.read(authNotifierProvider.notifier).refreshUser();
      return true;
    } on KycFailure catch (e) {
      state = state.copy(submitting: false, error: e.message);
      return false;
    } catch (_) {
      state = state.copy(
        submitting: false,
        error: 'We couldn\'t submit your documents. Try again.',
      );
      return false;
    }
  }
}

final kycDraftProvider =
    NotifierProvider<KycDraftNotifier, KycDraft>(KycDraftNotifier.new);
