/// Identity verification.
///
/// KYC is the one surface that does not talk to the main API. It posts
/// multipart to a separate Go service through the gateway, with its own
/// limits and its own `{"error": "..."}` envelope, which `ApiException`
/// already normalises.
///
/// Three consequences the screen handles explicitly:
///
/// * **The idempotency key is generated once and kept.** It is what makes a
///   retry a no-op rather than a second review sitting in a queue. Regenerating
///   it on every tap would defeat the mechanism entirely, so it lives in state
///   and survives a failure.
///
/// * **There is no status endpoint.** After a successful submission the app
///   re-reads the account, whose `is_kyc_verified` is the authoritative gate
///   and whose `kyc_status` is display-only.
///
/// * **`unverified` is ambiguous** — it covers "never submitted" and "expired,
///   resubmit". The copy therefore says what to do next instead of asserting
///   which of the two happened.
library;

import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/api/api_exception.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/account.dart';
import '../../domain/kyc.dart';
import '../../l10n/app_localizations.dart';

class KycScreen extends ConsumerStatefulWidget {
  const KycScreen({super.key});

  @override
  ConsumerState<KycScreen> createState() => _KycScreenState();
}

class _KycScreenState extends ConsumerState<KycScreen> {
  final _picker = ImagePicker();

  /// Generated once for the whole screen. Retrying a failed submission reuses
  /// it, which is exactly what the server's `ON CONFLICT DO NOTHING` expects.
  late final String _idempotencyKey = _newIdempotencyKey();

  KycDocumentType _documentType = KycDocumentType.idCard;
  XFile? _front;
  XFile? _back;
  XFile? _selfie;

  bool _busy = false;
  double _progress = 0;
  String? _fileError;

  static String _newIdempotencyKey() {
    // 32 lowercase hex characters, which is the format the Go service
    // validates. `Random.secure` because it is a de-duplication token that
    // must not collide across users.
    final random = Random.secure();
    final buffer = StringBuffer();
    for (var i = 0; i < 32; i++) {
      buffer.write(random.nextInt(16).toRadixString(16));
    }
    return buffer.toString();
  }

  Future<void> _pick(void Function(XFile) assign, {bool selfie = false}) async {
    final l = L.of(context);
    final file = await _picker.pickImage(
      source: selfie ? ImageSource.camera : ImageSource.gallery,
      preferredCameraDevice: CameraDevice.front,
      imageQuality: 92,
    );
    if (file == null || !mounted) return;

    // Checked locally so the user is not charged a 8 MB upload to be told no.
    // The server remains the authority; this only avoids the obvious waste.
    final length = await File(file.path).length();
    if (length > KycLimits.maxImageBytes) {
      if (!mounted) return;
      setState(() => _fileError = l.kycFileTooLarge);
      return;
    }
    final mime = file.mimeType ?? _mimeFromPath(file.path);
    if (!KycLimits.allowedContentTypes.contains(mime)) {
      if (!mounted) return;
      setState(() => _fileError = l.kycFileTypeNotAllowed);
      return;
    }

    setState(() {
      _fileError = null;
      assign(file);
    });
  }

  static String _mimeFromPath(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
    return '';
  }

  bool get _isComplete =>
      _front != null &&
      _selfie != null &&
      (!_documentType.requiresBackImage || _back != null);

  Future<void> _submit() async {
    if (!_isComplete) return;
    final l = L.of(context);
    setState(() {
      _busy = true;
      _progress = 0;
    });

    try {
      await ref
          .read(kycRepositoryProvider)
          .submit(
            documentType: _documentType,
            idempotencyKey: _idempotencyKey,
            front: (path: _front!.path, name: _front!.name),
            selfie: (path: _selfie!.path, name: _selfie!.name),
            back: _documentType.requiresBackImage && _back != null
                ? (path: _back!.path, name: _back!.name)
                : null,
            onProgress: (sent, total) {
              if (mounted && total > 0) {
                setState(() => _progress = sent / total);
              }
            },
          );

      // No KYC status endpoint exists: the account is where status lives.
      await ref.read(sessionProvider.notifier).refreshAccount();
      if (!mounted) return;
      AppSnack.success(context, l.kycSubmitted);
    } on ApiException catch (error) {
      if (!mounted) return;
      AppSnack.failure(
        context,
        error,
        fallback: error.kind == ApiFailureKind.server ? l.kycUnavailable : null,
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final status = account?.kycStatus ?? KycStatus.unknown;

    // Verified or awaiting review: there is nothing for the user to do, so the
    // screen states the position rather than showing an inert form.
    final isTerminal =
        status == KycStatus.verified || status == KycStatus.pending;

    return AppScaffold(
      topBar: AppTopBar(title: l.kycTitle, showBack: true),
      body: ListView(
        padding: isTerminal
            ? AppScrollPadding.page(context)
            : AppScrollPadding.pageWithFooter(context),
        children: [
          _StatusBlock(status: status, reason: account?.kycRejectionReason),
          const SizedBox(height: AppSpace.xl),

          if (!isTerminal) ...[
            AppInsetGroup(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    l.kycWhyTitle,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: AppSpace.sm),
                  Text(
                    l.kycWhyBody,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: context.colors.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpace.xl),

            AppSegmentedChoice<KycDocumentType>(
              label: l.kycDocumentType,
              selected: _documentType,
              onSelect: (value) => setState(() {
                _documentType = value;
                if (!value.requiresBackImage) _back = null;
              }),
              options: [
                AppChoice(value: KycDocumentType.idCard, label: l.kycDocIdCard),
                AppChoice(
                  value: KycDocumentType.passport,
                  label: l.kycDocPassport,
                ),
                AppChoice(
                  value: KycDocumentType.drivingLicense,
                  label: l.kycDocDrivingLicense,
                ),
              ],
            ),
            const SizedBox(height: AppSpace.xl),

            if (_fileError != null) ...[
              InfoNotice(
                message: _fileError!,
                tone: StatusTone.bad,
                icon: Icons.error_outline_rounded,
              ),
              const SizedBox(height: AppSpace.lg),
            ],

            _PhotoSlot(
              label: l.kycFrontImage,
              file: _front,
              enabled: !_busy,
              onPick: () => _pick((f) => _front = f),
            ),
            const SizedBox(height: AppSpace.md),

            if (_documentType.requiresBackImage)
              _PhotoSlot(
                label: l.kycBackImage,
                file: _back,
                enabled: !_busy,
                onPick: () => _pick((f) => _back = f),
              )
            else
              InfoNotice(
                message: l.kycBackNotNeeded,
                icon: Icons.info_outline_rounded,
              ),
            const SizedBox(height: AppSpace.md),

            _PhotoSlot(
              label: l.kycSelfie,
              helper: l.kycSelfieHelp,
              file: _selfie,
              enabled: !_busy,
              onPick: () => _pick((f) => _selfie = f, selfie: true),
            ),

            if (_busy) ...[
              const SizedBox(height: AppSpace.xl),
              Semantics(
                liveRegion: true,
                label: l.kycUploading,
                child: LinearProgressIndicator(
                  value: _progress == 0 ? null : _progress,
                ),
              ),
            ],
          ],
        ],
      ),
      footer: isTerminal
          ? null
          : AppButton(
              label: l.kycSubmitAction,
              isLoading: _busy,
              onPressed: _isComplete ? _submit : null,
            ),
    );
  }
}

class _StatusBlock extends StatelessWidget {
  const _StatusBlock({required this.status, this.reason});

  final KycStatus status;
  final String? reason;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    final (label, body, tone, icon) = switch (status) {
      KycStatus.verified => (
        l.kycStatusApproved,
        l.kycApprovedBody,
        StatusTone.good,
        Icons.verified_rounded,
      ),
      KycStatus.pending => (
        l.kycStatusPending,
        l.kycPendingBody,
        StatusTone.waiting,
        Icons.hourglass_top_rounded,
      ),
      KycStatus.rejected => (
        l.kycStatusRejected,
        reason == null || reason!.isEmpty
            ? l.kycRejectedBody
            : '${l.kycRejectedBody}\n\n${l.proofRejectedReason}: $reason',
        StatusTone.bad,
        Icons.error_outline_rounded,
      ),
      // `unverified` covers both "never started" and "expired". The copy says
      // what to do rather than claiming to know which.
      KycStatus.unverified || KycStatus.unknown => (
        l.kycStatusNotStarted,
        l.kycWhyBody,
        StatusTone.neutral,
        Icons.badge_outlined,
      ),
    };

    return AppCard(
      accent: tone,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StatusPill(label: label, tone: tone, icon: icon),
          const SizedBox(height: AppSpace.md),
          Text(
            body,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.colors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _PhotoSlot extends StatelessWidget {
  const _PhotoSlot({
    required this.label,
    required this.file,
    required this.onPick,
    required this.enabled,
    this.helper,
  });

  final String label;
  final XFile? file;
  final VoidCallback onPick;
  final bool enabled;
  final String? helper;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final chosen = file != null;

    return AppSelectField(
      label: label,
      placeholder: l.kycAddPhoto,
      value: chosen ? file!.name : null,
      helper: helper,
      enabled: enabled,
      isRequired: true,
      icon: chosen ? Icons.check_circle_rounded : Icons.add_a_photo_outlined,
      trailingIcon: chosen
          ? Icons.refresh_rounded
          : Icons.chevron_right_rounded,
      onTap: onPick,
      secondary: chosen ? l.kycReplacePhoto : null,
    );
  }
}
