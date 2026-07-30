/// KYC identity verification — client for the Go kyc-service.
///
/// The bytes never touch Django: the Go service streams each image to
/// S3/MinIO and then records the row over gRPC. We talk to one endpoint:
///
///   POST /kyc/submit   (multipart/form-data, Bearer auth)
///     document_type    id_card | passport | driving_license
///     idempotency_key  32-char UUIDv4 hex — STABLE across retries of the
///                      same logical submission, so a retry overwrites the
///                      same S3 keys instead of orphaning objects and
///                      Django dedupes the row.
///     front            image file (always required)
///     back             image file (required unless passport)
///     selfie           image file (always required)
///
/// → 201 {submission_id, status, created:true}  first time
/// → 200 {submission_id, status, created:false} idempotent replay
/// → 4xx/5xx {error: "..."}
library;

import 'dart:io';
import 'dart:math';

import 'package:dio/dio.dart';

/// Server-side backstop is 8 MiB per image (kyc-service `MaxImageBytes`).
/// We enforce the same cap client-side so a doomed upload fails instantly
/// instead of after streaming megabytes over a mobile connection.
const int kMaxKycImageBytes = 8 << 20;

/// The service accepts JPEG and PNG only. HEIC is converted by the picker
/// before it reaches us (mobile rule, not server-enforced).
const Set<String> kAllowedKycExtensions = {'jpg', 'jpeg', 'png'};

class KycFailure implements Exception {
  KycFailure(this.message);
  final String message;

  @override
  String toString() => message;
}

enum KycDocumentType { idCard, passport, drivingLicense }

extension KycDocumentTypeX on KycDocumentType {
  /// Wire value — must stay in lockstep with kyc.proto DocumentType and
  /// Django `KycSubmission.DocumentType`.
  String get wire => switch (this) {
        KycDocumentType.idCard => 'id_card',
        KycDocumentType.passport => 'passport',
        KycDocumentType.drivingLicense => 'driving_license',
      };

  String get label => switch (this) {
        KycDocumentType.idCard => 'National ID card',
        KycDocumentType.passport => 'Passport',
        KycDocumentType.drivingLicense => 'Driving licence',
      };

  /// A passport is a single booklet page — no reverse side to photograph.
  bool get needsBack => this != KycDocumentType.passport;
}

enum KycStatus { pending, approved, rejected, expired, unknown }

KycStatus kycStatusFromWire(String? s) => switch (s) {
      'pending' => KycStatus.pending,
      'approved' => KycStatus.approved,
      'rejected' => KycStatus.rejected,
      'expired' => KycStatus.expired,
      _ => KycStatus.unknown,
    };

class KycSubmissionResult {
  const KycSubmissionResult({
    required this.submissionId,
    required this.status,
    required this.created,
  });

  factory KycSubmissionResult.fromJson(Map<String, dynamic> j) =>
      KycSubmissionResult(
        submissionId: (j['submission_id'] as num?)?.toInt() ?? 0,
        status: kycStatusFromWire(j['status'] as String?),
        created: (j['created'] as bool?) ?? false,
      );

  final int submissionId;
  final KycStatus status;

  /// False when the server recognized our `idempotency_key` and replayed an
  /// existing submission instead of creating one.
  final bool created;
}

/// Generates the stable 32-char hex key that makes a submission idempotent.
String newIdempotencyKey() {
  final rnd = Random.secure();
  final buf = StringBuffer();
  for (var i = 0; i < 32; i++) {
    buf.write(rnd.nextInt(16).toRadixString(16));
  }
  return buf.toString();
}

class KycRepository {
  KycRepository(this._dio);
  final Dio _dio;

  /// Validate a picked image before we build the request. Returns null when
  /// the file is acceptable, else a message ready to show the user.
  static String? validationErrorFor(File file) {
    final ext = file.path.split('.').last.toLowerCase();
    if (!kAllowedKycExtensions.contains(ext)) {
      return 'Use a JPG or PNG photo.';
    }
    final bytes = file.lengthSync();
    if (bytes > kMaxKycImageBytes) {
      final mb = (bytes / (1 << 20)).toStringAsFixed(1);
      return 'That photo is ${mb}MB. Keep each one under 8MB.';
    }
    if (bytes == 0) {
      return 'That file is empty. Take the photo again.';
    }
    return null;
  }

  /// Submit the documents. `idempotencyKey` must be the SAME value on every
  /// retry of one logical submission (see the library docstring).
  Future<KycSubmissionResult> submit({
    required KycDocumentType documentType,
    required String idempotencyKey,
    required File front,
    File? back,
    required File selfie,
  }) async {
    if (documentType.needsBack && back == null) {
      throw KycFailure('Add a photo of the back of your document.');
    }

    final form = FormData();
    form.fields
      ..add(MapEntry('document_type', documentType.wire))
      ..add(MapEntry('idempotency_key', idempotencyKey));
    form.files.add(MapEntry('front', await _part(front, 'front')));
    if (back != null) {
      form.files.add(MapEntry('back', await _part(back, 'back')));
    }
    form.files.add(MapEntry('selfie', await _part(selfie, 'selfie')));

    try {
      final r = await _dio.post<Map<String, dynamic>>(
        '/kyc/submit',
        data: form,
        options: Options(
          // Dio's default JSON content-type would break the multipart
          // boundary; let FormData set it. Uploading three images over a
          // mobile connection also needs more than the global 15s budget.
          contentType: 'multipart/form-data',
          sendTimeout: const Duration(seconds: 90),
          receiveTimeout: const Duration(seconds: 90),
        ),
      );
      if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
        return KycSubmissionResult.fromJson(r.data!);
      }
      throw KycFailure(_message(r.statusCode, r.data));
    } on DioException catch (e) {
      if (e.type == DioExceptionType.sendTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.connectionTimeout) {
        throw KycFailure(
          'The upload timed out. Check your connection and try again — '
          'we won\'t create a duplicate.',
        );
      }
      if (e.response != null) {
        throw KycFailure(_message(e.response!.statusCode, e.response!.data));
      }
      throw KycFailure('No connection. Try again once you\'re back online.');
    }
  }

  /// The service reads each part's `Content-Type` to pick the stored
  /// extension, and accepts only image/jpeg + image/png. Dio derives that
  /// header from the filename, so we normalise the extension here (a `.jpeg`
  /// pick still has to land as a type the server allows).
  Future<MultipartFile> _part(File file, String field) async {
    final ext = file.path.split('.').last.toLowerCase();
    final filename = ext == 'png' ? '$field.png' : '$field.jpg';
    return MultipartFile.fromFile(file.path, filename: filename);
  }

  /// Turn a server error into something a person can act on. The service
  /// returns `{"error": "..."}`; those strings are terse and developer-facing,
  /// so we map the statuses we know and only fall back to the raw text.
  String _message(int? status, Object? data) {
    final raw = data is Map ? data['error'] as String? : null;
    switch (status) {
      case 400:
        if (raw != null && raw.contains('document_type')) {
          return 'Pick a document type and try again.';
        }
        if (raw != null && raw.contains('too large')) {
          return 'One of those photos is over 8MB. Retake it and try again.';
        }
        if (raw != null && raw.contains('content type')) {
          return 'Use a JPG or PNG photo.';
        }
        return raw ?? 'Something in the form was off. Check your photos.';
      case 401:
        return 'Your session expired. Sign in again to continue.';
      case 413:
        return 'Those photos are too large. Keep each one under 8MB.';
      case 503:
        return 'Verification is temporarily unavailable. Try again shortly.';
      case 502:
        return 'We couldn\'t reach verification. Try again shortly.';
      default:
        return raw ?? 'We couldn\'t submit your documents. Try again.';
    }
  }
}
