/// One dispute.
///
/// Three things this screen is careful about:
///
/// * **The settlement is the platform's arithmetic, not the client's.** When a
///   dispute resolves, the server publishes the refund, the payout and the fee.
///   They are rendered. Nothing here splits, subtracts or reconciles them —
///   `Money` has no operators, which makes that structural rather than a
///   convention.
///
/// * **Evidence links are fetched at the moment of viewing.** A signed URL
///   expires in about five minutes, so caching one produces a dead link later.
///   The URL is never stored, never logged and never put in a route.
///
/// * **The timeline reads from event kinds and allowlisted payload keys**, not
///   from prose. Staff notes are filtered out server-side for a party, and this
///   screen never tries to reconstruct them.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/dispute.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';

/// What the seeded policy accepts today. Local checks only save a doomed
/// upload; the server decides.
const _maxEvidenceBytes = 25 * 1024 * 1024;
const _maxEvidenceItems = 20;

final _disputeProvider = FutureProvider.autoDispose.family<Dispute, int>((
  ref,
  id,
) async {
  final repo = ref.watch(disputeRepositoryProvider);
  return repo.byId(id);
});

class DisputeDetailScreen extends ConsumerStatefulWidget {
  const DisputeDetailScreen({required this.disputeId, super.key});

  final int disputeId;

  @override
  ConsumerState<DisputeDetailScreen> createState() =>
      _DisputeDetailScreenState();
}

class _DisputeDetailScreenState extends ConsumerState<DisputeDetailScreen> {
  final _picker = ImagePicker();
  bool _busy = false;
  double _progress = 0;

  void _refresh() => ref.invalidate(_disputeProvider(widget.disputeId));

  Future<void> _addNote() async {
    final text = await showAppSheet<String>(
      context,
      builder: (sheetContext) => const _NoteSheet(),
    );
    if (text == null || text.isEmpty || !mounted) return;

    setState(() => _busy = true);
    try {
      await ref
          .read(disputeRepositoryProvider)
          .addText(disputeId: widget.disputeId, text: text);
      if (!mounted) return;
      _refresh();
      AppSnack.success(context, L.of(context).disputeEvidenceAdded);
    } on ApiException catch (error) {
      if (!mounted) return;
      _explain(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addFile(EvidenceKind kind) async {
    final l = L.of(context);
    final picked = kind == EvidenceKind.video
        ? await _picker.pickVideo(source: ImageSource.gallery)
        : await _picker.pickImage(
            source: ImageSource.gallery,
            imageQuality: 92,
          );
    if (picked == null || !mounted) return;

    final bytes = await File(picked.path).length();
    if (!mounted) return;
    if (bytes > _maxEvidenceBytes) {
      AppSnack.info(context, l.disputeFileTooLarge('25 MB'));
      return;
    }

    setState(() {
      _busy = true;
      _progress = 0;
    });
    try {
      await ref
          .read(disputeRepositoryProvider)
          .addFile(
            disputeId: widget.disputeId,
            kind: kind,
            filePath: picked.path,
            fileName: picked.name,
            onProgress: (sent, total) {
              if (mounted && total > 0) {
                setState(() => _progress = sent / total);
              }
            },
          );
      if (!mounted) return;
      _refresh();
      AppSnack.success(context, l.disputeEvidenceAdded);
    } on ApiException catch (error) {
      if (!mounted) return;
      _explain(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _explain(ApiException error) {
    final l = L.of(context);
    final message = switch (error.code.raw) {
      'dispute_evidence_limit_reached' => l.disputeEvidenceLimitReached,
      'dispute_evidence_too_large' => l.disputeFileTooLarge(
        _formatBytes(error.intExtra('max_evidence_bytes')),
      ),
      'dispute_evidence_type_not_allowed' => l.disputeFileTypeNotAllowed,
      'dispute_evidence_type_mismatch' => l.disputeEvidenceTypeMismatchBody,
      'dispute_evidence_content_mismatch' =>
        l.disputeEvidenceContentMismatchBody,
      'dispute_not_active' => l.disputeEvidenceClosedBody,
      'dispute_evidence_text_required' => l.disputeEvidenceTextRequiredBody,
      'dispute_evidence_file_required' => l.disputeEvidenceFileRequiredBody,
      _ => null,
    };
    AppSnack.failure(context, error, fallback: message);
  }

  static String _formatBytes(int? bytes) =>
      bytes == null ? '25 MB' : '${(bytes / (1024 * 1024)).round()} MB';

  /// Fetches a fresh signed URL and opens it. Never cached — it expires in
  /// minutes and a stored one is a broken link waiting to happen.
  Future<void> _view(DisputeEvidence evidence) async {
    final l = L.of(context);
    try {
      final link = await ref
          .read(disputeRepositoryProvider)
          .evidenceUrl(disputeId: widget.disputeId, evidenceId: evidence.id);
      final uri = Uri.tryParse(link.url);
      if (!mounted) return;
      if (uri == null ||
          !await launchUrl(uri, mode: LaunchMode.externalApplication)) {
        if (!mounted) return;
        AppSnack.info(context, l.disputeEvidenceOpenFailed);
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      AppSnack.failure(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final dispute = ref.watch(_disputeProvider(widget.disputeId));

    return AppScaffold(
      topBar: AppTopBar(title: l.disputeDetailTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: AsyncView<Dispute>(
          value: dispute,
          onRetry: _refresh,
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonDetail()],
          ),
          data: (data) => ListView(
            padding: AppScrollPadding.page(context),
            children: [
              _Header(dispute: data),
              const SizedBox(height: AppSpace.xl),

              if (data.hasResolution) ...[
                _Settlement(dispute: data),
                const SizedBox(height: AppSpace.xl),
              ],

              _Evidence(
                dispute: data,
                busy: _busy,
                progress: _progress,
                onAddNote: _addNote,
                onAddPhoto: () => _addFile(EvidenceKind.photo),
                onAddVideo: () => _addFile(EvidenceKind.video),
                onView: _view,
              ),
              const SizedBox(height: AppSpace.xl),

              _Timeline(dispute: data),
            ],
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.dispute});

  final Dispute dispute;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);
    final copy = disputeStatusCopy(context, dispute.status);

    return AppCard(
      accent: copy.tone,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  disputeCategoryLabel(context, dispute.category),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              StatusPill(
                label: copy.label,
                tone: copy.tone,
                icon: copy.icon,
                compact: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.lg),

          if (dispute.reasonText.isNotEmpty) ...[
            Text(
              l.disputeReasonLabel,
              style: Theme.of(
                context,
              ).textTheme.labelSmall?.copyWith(color: c.textTertiary),
            ),
            const SizedBox(height: AppSpace.xs),
            Text(
              dispute.reasonText,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: AppSpace.lg),
          ],

          if (dispute.openedByRole != null)
            DetailRow(
              label: l.disputeOpenedByLabel,
              value: Text(
                dispute.openedByRole == 'sender'
                    ? l.disputeOpenedBySender
                    : l.disputeOpenedByTraveler,
              ),
            ),
          if (dispute.openedAt != null)
            DetailRow(
              label: l.disputeOpenedAtLabel,
              value: Text(LocaleFormats.dateTime(locale, dispute.openedAt!)),
            ),
          if (dispute.protectionEndsAt != null)
            DetailRow(
              label: l.disputeProtectionEndsLabel,
              value: Text(
                LocaleFormats.dateTime(locale, dispute.protectionEndsAt!),
              ),
            ),

          // The consequence for the other party, stated wherever it is true.
          if (dispute.payoutFrozen) ...[
            const SizedBox(height: AppSpace.md),
            InfoNotice(
              title: l.disputePayoutFrozenTitle,
              message: l.disputeFreezesPayoutBody,
              tone: StatusTone.waiting,
              icon: Icons.ac_unit_rounded,
            ),
          ] else if (dispute.payoutAlreadySettled) ...[
            const SizedBox(height: AppSpace.md),
            InfoNotice(message: l.disputePayoutSettledBody),
          ],
        ],
      ),
    );
  }
}

/// The amounts the platform decided. Rendered, never derived.
class _Settlement extends StatelessWidget {
  const _Settlement({required this.dispute});

  final Dispute dispute;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    final outcome = switch (dispute.resolution) {
      DisputeResolution.fullSenderRefund => l.disputeResolutionRefunded,
      DisputeResolution.fullTravelerPayout => l.disputeResolutionTravelerPaid,
      DisputeResolution.partialSplit => l.disputeResolutionPartial,
      DisputeResolution.unknown => l.disputeResolutionTitle,
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.disputeAmountsTitle, subtitle: outcome),
        MoneyBreakdown(
          explainer: l.disputeAmountsExplainer,
          lines: [
            if (dispute.collectedTotal != null)
              MoneyLine(
                label: l.disputeCollectedTotal,
                amount: dispute.collectedTotal!,
              ),
            if (dispute.travelerPayout != null)
              MoneyLine(
                label: l.moneyTravelerReceives,
                amount: dispute.travelerPayout!,
              ),
            if (dispute.platformFee != null)
              MoneyLine(
                label: l.moneyPlatformFee,
                amount: dispute.platformFee!,
              ),
            if (dispute.senderRefund != null)
              MoneyLine.total(
                label: l.moneyRefundToYou,
                amount: dispute.senderRefund!,
              ),
          ],
        ),
        if (dispute.resolutionNote != null &&
            dispute.resolutionNote!.isNotEmpty) ...[
          const SizedBox(height: AppSpace.lg),
          AppInsetGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l.disputeResolutionNoteLabel,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: context.colors.textTertiary,
                  ),
                ),
                const SizedBox(height: AppSpace.xs),
                Text(
                  dispute.resolutionNote!,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}

class _Evidence extends StatelessWidget {
  const _Evidence({
    required this.dispute,
    required this.busy,
    required this.progress,
    required this.onAddNote,
    required this.onAddPhoto,
    required this.onAddVideo,
    required this.onView,
  });

  final Dispute dispute;
  final bool busy;
  final double progress;
  final VoidCallback onAddNote;
  final VoidCallback onAddPhoto;
  final VoidCallback onAddVideo;
  final void Function(DisputeEvidence) onView;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final canAdd =
        dispute.canAddEvidence && dispute.evidence.length < _maxEvidenceItems;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(
          title: l.disputeEvidenceTitle,
          subtitle: l.disputeEvidenceExplainer,
        ),

        if (dispute.evidence.isEmpty)
          Text(
            l.disputeEvidenceNone,
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: c.textTertiary),
          )
        else
          for (final item in dispute.evidence) ...[
            _EvidenceRow(evidence: item, onView: () => onView(item)),
            const SizedBox(height: AppSpace.sm),
          ],

        const SizedBox(height: AppSpace.md),
        Text(
          l.disputeEvidenceCount(dispute.evidence.length, _maxEvidenceItems),
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
        ),

        if (busy) ...[
          const SizedBox(height: AppSpace.lg),
          Semantics(
            liveRegion: true,
            label: l.disputeUploading((progress * 100).round()),
            child: LinearProgressIndicator(
              value: progress == 0 ? null : progress,
            ),
          ),
        ],

        if (canAdd) ...[
          const SizedBox(height: AppSpace.lg),
          Wrap(
            spacing: AppSpace.sm,
            runSpacing: AppSpace.sm,
            children: [
              AppButton(
                label: l.disputeAddNote,
                variant: AppButtonVariant.secondary,
                icon: Icons.notes_rounded,
                expand: false,
                onPressed: busy ? null : onAddNote,
              ),
              AppButton(
                label: l.disputeAddPhoto,
                variant: AppButtonVariant.secondary,
                icon: Icons.photo_outlined,
                expand: false,
                onPressed: busy ? null : onAddPhoto,
              ),
              AppButton(
                label: l.disputeAddVideo,
                variant: AppButtonVariant.secondary,
                icon: Icons.videocam_outlined,
                expand: false,
                onPressed: busy ? null : onAddVideo,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.md),
          Text(
            l.disputeEvidenceLinkNote,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
          ),
        ] else if (!dispute.canAddEvidence) ...[
          const SizedBox(height: AppSpace.lg),
          InfoNotice(message: l.disputeEvidenceClosedBody),
        ] else ...[
          const SizedBox(height: AppSpace.lg),
          InfoNotice(
            message: l.disputeEvidenceLimitReached,
            tone: StatusTone.waiting,
            icon: Icons.info_outline_rounded,
          ),
        ],
      ],
    );
  }
}

class _EvidenceRow extends StatelessWidget {
  const _EvidenceRow({required this.evidence, required this.onView});

  final DisputeEvidence evidence;
  final VoidCallback onView;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);

    final (label, icon) = switch (evidence.kind) {
      EvidenceKind.photo => (l.disputeEvidenceKindPhoto, Icons.image_outlined),
      EvidenceKind.video => (
        l.disputeEvidenceKindVideo,
        Icons.videocam_outlined,
      ),
      EvidenceKind.text ||
      EvidenceKind.unknown => (l.disputeEvidenceKindText, Icons.notes_rounded),
    };

    return AppCard(
      // Only a file has somewhere to go; a note is already on screen.
      onTap: evidence.hasFile ? onView : null,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: c.textTertiary),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: Theme.of(
                    context,
                  ).textTheme.labelMedium?.copyWith(color: c.textSecondary),
                ),
                if (evidence.text != null && evidence.text!.isNotEmpty) ...[
                  const SizedBox(height: AppSpace.xs),
                  Text(
                    evidence.text!,
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ],
                if (evidence.createdAt != null) ...[
                  const SizedBox(height: AppSpace.xs),
                  Text(
                    LocaleFormats.dateTime(locale, evidence.createdAt!),
                    style: Theme.of(
                      context,
                    ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
                  ),
                ],
              ],
            ),
          ),
          if (evidence.hasFile)
            Text(
              l.disputeEvidenceView,
              style: Theme.of(
                context,
              ).textTheme.labelMedium?.copyWith(color: c.brand),
            ),
        ],
      ),
    );
  }
}

class _Timeline extends StatelessWidget {
  const _Timeline({required this.dispute});

  final Dispute dispute;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);
    if (dispute.events.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.disputeTimelineTitle),
        for (final event in dispute.events)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpace.md),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Padding(
                  padding: EdgeInsets.only(top: 5),
                  child: StatusDot(tone: StatusTone.neutral),
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _describe(context, event),
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                      if (event.createdAt != null) ...[
                        const SizedBox(height: AppSpace.xxs),
                        Text(
                          LocaleFormats.dateTime(locale, event.createdAt!),
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(color: c.textTertiary),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  /// Built from the event's kind and its allowlisted payload — never from a
  /// server-authored sentence, which would neither translate nor be safe to
  /// show a party.
  String _describe(BuildContext context, DisputeEvent event) {
    final l = L.of(context);
    return switch (event.kind) {
      'opened' => l.disputeEventOpened,
      'status_changed' => l.disputeEventStatusChanged(
        _statusLabel(context, event.payload['status']),
      ),
      'evidence_added' => l.disputeEventEvidenceAdded,
      'resolved' => l.disputeEventResolved,
      'closed' => l.disputeEventClosed,
      'payout_frozen' => l.disputeEventPayoutFrozen,
      'note' => l.disputeEventNote,
      _ => l.disputeEventOther,
    };
  }

  String _statusLabel(BuildContext context, Object? raw) {
    final status = switch (raw) {
      'open' => DisputeStatus.open,
      'awaiting_evidence' => DisputeStatus.awaitingEvidence,
      'under_review' => DisputeStatus.underReview,
      'resolved' => DisputeStatus.resolved,
      'closed' => DisputeStatus.closed,
      _ => DisputeStatus.unknown,
    };
    return disputeStatusCopy(context, status).label;
  }
}

class _NoteSheet extends StatefulWidget {
  const _NoteSheet();

  @override
  State<_NoteSheet> createState() => _NoteSheetState();
}

class _NoteSheetState extends State<_NoteSheet> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return AppSheet(
      title: l.disputeAddNote,
      footer: AppButton(
        label: l.actionAdd,
        onPressed: () {
          final text = _controller.text.trim();
          if (text.isEmpty) return;
          Navigator.of(context).pop(text);
        },
      ),
      child: AppTextField(
        label: l.disputeAddNote,
        controller: _controller,
        hint: l.disputeEvidenceNoteHint,
        maxLines: 6,
        minLines: 4,
        maxLength: 2000,
        autofocus: true,
      ),
    );
  }
}
