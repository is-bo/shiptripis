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
  bool _busy = false;
  double _progress = 0;
  String? _fileError;

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
      _file = picked;
    });
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
      AppSnack.failure(
        context,
        error,
        fallback: switch (error.code.raw) {
          'journey_proof_upload_closed' => l.proofErrorUploadClosed,
          'proof_only_for_flight' => l.proofDriveNotRequired,
          'journey_not_owned' => l.journeyErrorNotOwned,
          _ => switch (error.statusCode) {
            413 => l.proofFileTooLarge,
            415 => l.proofFileTypeNotAllowed,
            _ => null,
          },
        },
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
                  leg.origin?.coarseLabel ?? '',
                  leg.destination?.coarseLabel ?? '',
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
