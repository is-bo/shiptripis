/// Flight proof for one leg.
///
/// Proof is what lets a sender believe the flight is real, so the screen leads
/// with that rather than treating it as paperwork.
///
/// The server verifies the file's actual bytes against its declared type, so a
/// renamed `.jpg` is refused. Stating the rule up front is cheaper than an
/// upload that fails at the far end of a phone connection — and the local
/// checks here exist only to save that round trip. The server remains the
/// authority.
library;

import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/journey.dart';
import '../../l10n/app_localizations.dart';
import 'journey_labels.dart';

/// What the server accepts. Duplicated here only to avoid a doomed upload.
const _maxProofBytes = 10 * 1024 * 1024;
const _allowedProofTypes = ['image/jpeg', 'image/png', 'image/webp'];

enum _ProofKind {
  ticket,
  boardingPass,
  bookingConfirmation;

  String get wire => switch (this) {
    _ProofKind.ticket => 'ticket',
    _ProofKind.boardingPass => 'boarding_pass',
    _ProofKind.bookingConfirmation => 'booking_confirmation',
  };
}

/// Copy for every proof refusal the server can send.
///
/// Branching on the machine code, never on the server's English, and never on
/// a raw provider message: the deployed failure that started Phase 8F-A was a
/// storage `AccessDenied` surfacing as "this isn't your fault, try again in a
/// moment", which was both untrue and unactionable. Each of these says what
/// went wrong and what to do about it; the request id stays available to
/// support through the failure's own affordance rather than in the sentence.
String? proofFailureCopy(BuildContext context, ApiException error) {
  final l = L.of(context);
  return switch (error.code.raw) {
    'journey_proof_upload_closed' => l.proofErrorUploadClosed,
    'proof_only_for_flight' => l.proofDriveNotRequired,
    'journey_not_owned' => l.journeyErrorNotOwned,
    'proof_file_missing' => l.proofChooseImage,
    'proof_file_too_large' => l.proofFileTooLarge,
    'proof_media_type_unsupported' => l.proofFileTypeNotAllowed,
    'proof_kind_unknown' => l.proofKindLabel,
    'proof_storage_unavailable' => l.proofErrorStorageUnavailable,
    _ => switch (error.statusCode) {
      413 => l.proofFileTooLarge,
      415 => l.proofFileTypeNotAllowed,
      _ => null,
    },
  };
}

class LegProofScreen extends ConsumerStatefulWidget {
  const LegProofScreen({
    required this.journeyId,
    required this.legId,
    super.key,
  });

  final int journeyId;
  final int legId;

  @override
  ConsumerState<LegProofScreen> createState() => _LegProofScreenState();
}

class _LegProofScreenState extends ConsumerState<LegProofScreen> {
  final _picker = ImagePicker();

  _ProofKind _kind = _ProofKind.ticket;
  XFile? _file;
  String? _fileMime;

  /// Identifies the *file*, not the attempt, and is regenerated only when a
  /// different image is chosen. That is what makes Retry safe: the server
  /// recognises the second attempt as the same upload and returns the row the
  /// first one may already have created.
  String? _idempotencyKey;

  bool _busy = false;
  double _progress = 0;
  String? _fileError;

  /// The last failure, kept so the screen can offer Retry beside the file
  /// that is still selected rather than dropping the user back to the gallery.
  ApiException? _lastFailure;

  Future<void> _pick(ImageSource source) async {
    final l = L.of(context);
    final picked = await _picker.pickImage(source: source, imageQuality: 92);
    if (picked == null || !mounted) return;

    final bytes = await File(picked.path).length();
    if (!mounted) return;
    if (bytes > _maxProofBytes) {
      setState(() => _fileError = l.proofFileTooLarge);
      return;
    }
    final mime = picked.mimeType ?? _mimeFromPath(picked.path);
    if (!_allowedProofTypes.contains(mime)) {
      setState(() => _fileError = l.proofFileTypeNotAllowed);
      return;
    }

    setState(() {
      _fileError = null;
      _lastFailure = null;
      _file = picked;
      _fileMime = mime;
      _idempotencyKey = _newIdempotencyKey();
    });
  }

  /// Random rather than derived from the file: two different boarding passes
  /// can be byte-identical after the picker re-encodes them, and collapsing
  /// those into one proof would be worse than an extra row.
  static String _newIdempotencyKey() {
    final random = Random.secure();
    return List.generate(
      4,
      (_) => random.nextInt(1 << 32).toRadixString(36),
    ).join();
  }

  static String _mimeFromPath(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.webp')) return 'image/webp';
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
    return '';
  }

  Future<void> _upload() async {
    final file = _file;
    if (file == null) return;

    setState(() {
      _busy = true;
      _progress = 0;
      _lastFailure = null;
    });
    final l = L.of(context);

    try {
      await ref
          .read(journeyRepositoryProvider)
          .uploadProof(
            journeyId: widget.journeyId,
            legId: widget.legId,
            filePath: file.path,
            fileName: file.name,
            kind: _kind.wire,
            contentType: _fileMime,
            idempotencyKey: _idempotencyKey,
            onProgress: (sent, total) {
              if (mounted && total > 0) {
                setState(() => _progress = sent / total);
              }
            },
          );
      if (!mounted) return;
      ref.invalidate(journeyDetailProvider(widget.journeyId));
      refreshVolatileState(ref);
      AppSnack.success(context, l.proofUploaded);
      context.pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      // The file stays selected. A storage hiccup or a dropped connection is
      // not a reason to make someone find their boarding pass again.
      setState(() => _lastFailure = error);
      AppSnack.failure(
        context,
        error,
        fallback: proofFailureCopy(context, error),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final journey = ref.watch(journeyDetailProvider(widget.journeyId));

    return AppScaffold(
      topBar: AppTopBar(title: l.proofTitle, showBack: true),
      body: AsyncView<Journey>(
        value: journey,
        onRetry: () => ref.invalidate(journeyDetailProvider(widget.journeyId)),
        loading: () => const Padding(
          padding: EdgeInsets.all(AppSpace.gutter),
          child: SkeletonDetail(),
        ),
        data: (data) {
          final leg = data.legs.where((x) => x.id == widget.legId).firstOrNull;

          if (leg == null) {
            return AppEmptyState(
              title: l.stateNotFoundTitle,
              body: l.stateNotFoundBody,
              icon: Icons.search_off_rounded,
            );
          }

          if (!leg.mode.requiresProof) {
            return AppEmptyState(
              title: l.proofTitle,
              body: l.proofDriveNotRequired,
              icon: Icons.directions_car_filled_rounded,
            );
          }

          // Proof is only accepted before publication. Once the journey is
          // live, the upload endpoint refuses — so the screen stops offering.
          final closed = !data.status.isEditable;

          return ListView(
            padding: closed
                ? AppScrollPadding.page(context)
                : AppScrollPadding.pageWithFooter(context),
            children: [
              Text(
                l.proofLegLabel(
                  leg.position + 1,
                  legOriginLabel(leg),
                  legDestinationLabel(leg),
                ),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: AppSpace.lg),

              InfoNotice(
                message: l.proofExplainer,
                tone: StatusTone.progress,
                icon: Icons.verified_user_outlined,
              ),
              const SizedBox(height: AppSpace.xl),

              if (leg.proofs.isNotEmpty) ...[
                SectionHeader(title: l.proofExistingTitle),
                for (final proof in leg.proofs) ...[
                  _ProofCard(proof: proof),
                  const SizedBox(height: AppSpace.md),
                ],
                const SizedBox(height: AppSpace.lg),
              ],

              if (closed)
                InfoNotice(
                  message: l.proofErrorUploadClosed,
                  tone: StatusTone.neutral,
                  icon: Icons.lock_outline_rounded,
                )
              else ...[
                AppSegmentedChoice<_ProofKind>(
                  label: l.proofKindLabel,
                  selected: _kind,
                  onSelect: (value) => setState(() => _kind = value),
                  options: [
                    AppChoice(
                      value: _ProofKind.ticket,
                      label: l.proofKindTicket,
                    ),
                    AppChoice(
                      value: _ProofKind.boardingPass,
                      label: l.proofKindBoardingPass,
                    ),
                    AppChoice(
                      value: _ProofKind.bookingConfirmation,
                      label: l.proofKindBookingConfirmation,
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

                // A failed attempt keeps the file. Retrying reuses the same
                // idempotency key, so a request that actually reached the
                // server before the connection died attaches to that proof
                // instead of creating a second one.
                if (_lastFailure != null && _file != null) ...[
                  InfoNotice(
                    title: l.proofRetryTitle,
                    message: [
                      proofFailureCopy(context, _lastFailure!) ??
                          l.proofErrorStorageUnavailable,
                      l.proofRetryFileKept,
                    ].join(' '),
                    tone: _lastFailure!.isRetryable
                        ? StatusTone.waiting
                        : StatusTone.bad,
                    icon: Icons.refresh_rounded,
                    actionLabel: _lastFailure!.isRetryable
                        ? l.proofRetry
                        : null,
                    onAction: _lastFailure!.isRetryable && !_busy
                        ? _upload
                        : null,
                  ),
                  const SizedBox(height: AppSpace.lg),
                ],

                AppSelectField(
                  label: l.proofUpload,
                  placeholder: l.proofChooseImage,
                  value: _file?.name,
                  secondary: _file == null ? null : l.proofSelectedFile,
                  helper: l.proofFormatRule,
                  isRequired: true,
                  enabled: !_busy,
                  icon: _file == null
                      ? Icons.image_outlined
                      : Icons.check_circle_rounded,
                  onTap: _busy ? () {} : () => _pick(ImageSource.gallery),
                ),
                const SizedBox(height: AppSpace.sm),
                Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: AppButton(
                    label: l.proofTakePhoto,
                    variant: AppButtonVariant.tertiary,
                    icon: Icons.photo_camera_outlined,
                    expand: false,
                    onPressed: _busy ? null : () => _pick(ImageSource.camera),
                  ),
                ),

                if (_busy) ...[
                  const SizedBox(height: AppSpace.xl),
                  Semantics(
                    liveRegion: true,
                    label: l.proofUploading,
                    child: LinearProgressIndicator(
                      value: _progress == 0 ? null : _progress,
                    ),
                  ),
                ],
              ],
            ],
          );
        },
      ),
      footer: (journey.value?.status.isEditable ?? false)
          ? AppButton(
              label: l.proofUpload,
              isLoading: _busy,
              onPressed: _file == null ? null : _upload,
            )
          : null,
    );
  }
}

class _ProofCard extends StatelessWidget {
  const _ProofCard({required this.proof});

  final JourneyLegProof proof;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    final (label, tone, icon) = switch (proof.status) {
      ProofStatus.approved => (
        l.proofStatusApproved,
        StatusTone.good,
        Icons.check_circle_rounded,
      ),
      ProofStatus.pending => (
        l.proofStatusPending,
        StatusTone.waiting,
        Icons.hourglass_top_rounded,
      ),
      ProofStatus.rejected => (
        l.proofStatusRejected,
        StatusTone.bad,
        Icons.error_outline_rounded,
      ),
      ProofStatus.unknown => (
        l.proofStatusMissing,
        StatusTone.neutral,
        Icons.help_outline_rounded,
      ),
    };

    return AppCard(
      accent: tone,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  proof.kind.replaceAll('_', ' '),
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              StatusPill(label: label, tone: tone, icon: icon, compact: true),
            ],
          ),
          if (proof.reviewedAt != null) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              LocaleFormats.dateTime(locale, proof.reviewedAt!),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: context.colors.textTertiary,
              ),
            ),
          ],
          // A rejection without its reason is an unfixable problem.
          if (proof.status == ProofStatus.rejected &&
              proof.rejectionReason != null &&
              proof.rejectionReason!.isNotEmpty) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              l.proofRejectedReason(proof.rejectionReason!),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
