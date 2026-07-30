/// Identity verification — "passport control" for the account.
///
/// The app's whole visual language is travel documents (boarding cards,
/// stamps), so KYC is staged as a border checkpoint: a dossier of document
/// slots that get stamped as you fill them, then submitted for review. The
/// stamped slot row is the one loud element; everything around it stays quiet.
///
/// Steps: brief → document type → capture the shots → confirm → outcome.
/// The photos go straight to the Go kyc-service (never through Django); see
/// `core/kyc/kyc_repository.dart` for the wire contract.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/kyc/kyc_providers.dart';
import '../../core/kyc/kyc_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/util/safe_back.dart';
import '../../shared/widgets/primary_button.dart';

enum _Step { brief, document, capture, confirm, outcome }

class KycScreen extends ConsumerStatefulWidget {
  const KycScreen({super.key});

  @override
  ConsumerState<KycScreen> createState() => _KycScreenState();
}

class _KycScreenState extends ConsumerState<KycScreen> {
  _Step _step = _Step.brief;
  final _picker = ImagePicker();

  void _go(_Step s) {
    ref.read(kycDraftProvider.notifier).clearError();
    setState(() => _step = s);
  }

  /// Capture one slot. We ask the camera first (an ID photo is taken, not
  /// found), with a gallery fallback for people who already scanned theirs.
  Future<void> _capture(KycShot slot, {required bool fromGallery}) async {
    final XFile? picked;
    try {
      picked = await _picker.pickImage(
        source: fromGallery ? ImageSource.gallery : ImageSource.camera,
        // Downscale + recompress on the device: keeps a modern phone's 12MP
        // shot comfortably under the 8MB server cap while staying legible
        // enough for a reviewer to read the document.
        maxWidth: 2200,
        imageQuality: 88,
        preferredCameraDevice:
            slot == KycShot.selfie ? CameraDevice.front : CameraDevice.rear,
      );
    } catch (_) {
      if (!mounted) return;
      _toast('Couldn\'t open the camera. Check app permissions in Settings.');
      return;
    }
    if (picked == null || !mounted) return;

    final problem =
        ref.read(kycDraftProvider.notifier).attach(slot, File(picked.path));
    if (problem != null && mounted) _toast(problem);
  }

  void _toast(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        backgroundColor: AppColors.terracotta,
        content: Text(msg,
            style: AppType.body(13,
                color: AppColors.parchmentSoft, w: FontWeight.w600)),
      ),
    );
  }

  Future<void> _submit() async {
    final ok = await ref.read(kycDraftProvider.notifier).submit();
    if (!mounted) return;
    if (ok) {
      _go(_Step.outcome);
    } else {
      final err = ref.read(kycDraftProvider).error;
      if (err != null) _toast(err);
    }
  }

  void _back() {
    switch (_step) {
      case _Step.brief:
        safeBack(context, fallback: '/app');
      case _Step.document:
        _go(_Step.brief);
      case _Step.capture:
        _go(_Step.document);
      case _Step.confirm:
        _go(_Step.capture);
      case _Step.outcome:
        safeBack(context, fallback: '/app');
    }
  }

  @override
  Widget build(BuildContext context) {
    final draft = ref.watch(kycDraftProvider);

    return Scaffold(
      backgroundColor: AppColors.parchment,
      appBar: AppBar(
        backgroundColor: AppColors.parchment,
        foregroundColor: AppColors.ink,
        elevation: 0,
        leading: IconButton(
          icon: Icon(_step == _Step.outcome
              ? Icons.close_rounded
              : Icons.arrow_back_rounded),
          onPressed: draft.submitting ? null : _back,
        ),
        title: Text('Verify identity', style: AppType.display(18)),
      ),
      body: SafeArea(
        child: _StepTransition(
          child: switch (_step) {
            _Step.brief => _BriefStep(onStart: () => _go(_Step.document)),
            _Step.document => _DocumentStep(
                selected: draft.documentType,
                onPick: (t) {
                  ref.read(kycDraftProvider.notifier).pickDocumentType(t);
                  _go(_Step.capture);
                },
              ),
            _Step.capture => _CaptureStep(
                draft: draft,
                onShoot: (slot) => _capture(slot, fromGallery: false),
                onPickFile: (slot) => _capture(slot, fromGallery: true),
                onContinue: () => _go(_Step.confirm),
              ),
            _Step.confirm => _ConfirmStep(
                draft: draft,
                onEdit: () => _go(_Step.capture),
                onSubmit: _submit,
              ),
            _Step.outcome => _OutcomeStep(result: draft.result),
          },
        ),
      ),
    );
  }
}

/// Eases the height change between steps so the scaffold chrome stays put
/// while the body swaps. Deliberately the only transition here — the stamp
/// rail is where the motion budget is spent.
class _StepTransition extends StatelessWidget {
  const _StepTransition({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return AnimatedSize(
      duration: AppDurations.fast,
      curve: kAppCurve,
      alignment: Alignment.topCenter,
      child: child,
    );
  }
}

// ---------------------------------------------------------------- step 1

class _BriefStep extends StatelessWidget {
  const _BriefStep({required this.onStart});
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    return _StepScroll(
      children: [
        const _Eyebrow('Passport control'),
        const SizedBox(height: 6),
        Text('One check, then you\'re cleared',
            style: AppType.display(28, w: FontWeight.w400, height: 1.12)),
        const SizedBox(height: 12),
        Text(
          'Senders hand real parcels to travellers they\'ve never met. '
          'Verifying who you are is what makes that trade safe — for both '
          'sides of every handover.',
          style: AppType.body(14.5, color: AppColors.inkSoft, height: 1.5),
        ),
        const SizedBox(height: 26),
        const _ChecklistRow(
          icon: Icons.badge_outlined,
          title: 'A government document',
          body: 'National ID, passport, or driving licence.',
        ),
        const _ChecklistRow(
          icon: Icons.photo_camera_front_outlined,
          title: 'A photo of your face',
          body: 'So we can match it to the document.',
        ),
        const _ChecklistRow(
          icon: Icons.schedule_rounded,
          title: 'About two minutes',
          body: 'Review usually finishes within a day.',
          last: true,
        ),
        const SizedBox(height: 24),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: AppColors.emerald.withValues(alpha: 0.07),
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: AppColors.emerald.withValues(alpha: 0.2)),
          ),
          child: Row(
            children: [
              Icon(Icons.lock_outline_rounded,
                  size: 18, color: AppColors.emerald),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Your documents are stored encrypted and are only seen by '
                  'the reviewer. They\'re never shown to other users.',
                  style: AppType.body(12.5,
                      color: AppColors.emeraldDeep, height: 1.45),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 28),
        PrimaryButton(
          label: 'Start verification',
          expand: true,
          color: AppColors.emerald,
          onTap: onStart,
        ),
      ],
    );
  }
}

class _ChecklistRow extends StatelessWidget {
  const _ChecklistRow({
    required this.icon,
    required this.title,
    required this.body,
    this.last = false,
  });
  final IconData icon;
  final String title;
  final String body;
  final bool last;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: last ? 0 : 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: AppColors.parchmentSoft,
              borderRadius: BorderRadius.circular(AppRadius.sm),
              border: Border.all(color: AppColors.hairline),
            ),
            alignment: Alignment.center,
            child: Icon(icon, size: 18, color: AppColors.ink),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: AppType.body(14, w: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(body,
                    style: AppType.body(12.5,
                        color: AppColors.inkMute, height: 1.4)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- step 2

class _DocumentStep extends StatelessWidget {
  const _DocumentStep({required this.selected, required this.onPick});
  final KycDocumentType? selected;
  final ValueChanged<KycDocumentType> onPick;

  @override
  Widget build(BuildContext context) {
    return _StepScroll(
      children: [
        const _Eyebrow('Step 1 of 3'),
        const SizedBox(height: 6),
        Text('Which document?',
            style: AppType.display(28, w: FontWeight.w400, height: 1.12)),
        const SizedBox(height: 10),
        Text(
          'Pick whichever you have on hand. It must be valid and unexpired.',
          style: AppType.body(14, color: AppColors.inkSoft, height: 1.5),
        ),
        const SizedBox(height: 22),
        for (final t in KycDocumentType.values)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: _DocumentOption(
              type: t,
              selected: selected == t,
              onTap: () => onPick(t),
            ),
          ),
      ],
    );
  }
}

class _DocumentOption extends StatelessWidget {
  const _DocumentOption({
    required this.type,
    required this.selected,
    required this.onTap,
  });
  final KycDocumentType type;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final (icon, hint) = switch (type) {
      KycDocumentType.idCard => (
          Icons.badge_outlined,
          'Front and back',
        ),
      KycDocumentType.passport => (
          Icons.menu_book_outlined,
          'Photo page only',
        ),
      KycDocumentType.drivingLicense => (
          Icons.directions_car_outlined,
          'Front and back',
        ),
    };
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.md),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          decoration: BoxDecoration(
            color: selected
                ? AppColors.emerald.withValues(alpha: 0.07)
                : AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(
              color: selected ? AppColors.emerald : AppColors.hairline,
              width: selected ? 1.6 : 1,
            ),
          ),
          child: Row(
            children: [
              Icon(icon,
                  size: 22,
                  color: selected ? AppColors.emerald : AppColors.inkSoft),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(type.label,
                        style: AppType.body(14.5, w: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(hint,
                        style: AppType.body(12, color: AppColors.inkMute)),
                  ],
                ),
              ),
              Icon(Icons.chevron_right_rounded,
                  size: 20, color: AppColors.inkMute),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- step 3

class _CaptureStep extends StatelessWidget {
  const _CaptureStep({
    required this.draft,
    required this.onShoot,
    required this.onPickFile,
    required this.onContinue,
  });
  final KycDraft draft;
  final ValueChanged<KycShot> onShoot;
  final ValueChanged<KycShot> onPickFile;
  final VoidCallback onContinue;

  @override
  Widget build(BuildContext context) {
    final shots = draft.requiredShots;
    final done = draft.capturedCount;
    return _StepScroll(
      children: [
        const _Eyebrow('Step 2 of 3'),
        const SizedBox(height: 6),
        Text('Photograph your ${_docWord(draft.documentType)}',
            style: AppType.display(26, w: FontWeight.w400, height: 1.14)),
        const SizedBox(height: 10),
        Text(
          'Lay it flat in good light. Get all four corners in frame and make '
          'sure the text is readable.',
          style: AppType.body(14, color: AppColors.inkSoft, height: 1.5),
        ),
        const SizedBox(height: 18),
        // The signature element: a stamp rail that fills as each slot lands.
        _StampRail(shots: shots, draft: draft),
        const SizedBox(height: 20),
        for (final s in shots)
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: _ShotSlot(
              slot: s,
              file: draft.shot(s),
              onShoot: () => onShoot(s),
              onPickFile: () => onPickFile(s),
            ),
          ),
        const SizedBox(height: 10),
        PrimaryButton(
          label: draft.isComplete
              ? 'Review submission'
              : 'Add ${shots.length - done} more photo${shots.length - done == 1 ? '' : 's'}',
          expand: true,
          color: draft.isComplete ? AppColors.emerald : AppColors.inkMute,
          onTap: draft.isComplete ? onContinue : null,
        ),
      ],
    );
  }

  static String _docWord(KycDocumentType? t) => switch (t) {
        KycDocumentType.passport => 'passport',
        KycDocumentType.drivingLicense => 'licence',
        _ => 'ID card',
      };
}

/// Row of stamp slots — empty ones are dashed outlines, filled ones get an
/// emerald seal. Encodes real progress: one slot per required photo.
class _StampRail extends StatelessWidget {
  const _StampRail({required this.shots, required this.draft});
  final List<KycShot> shots;
  final KycDraft draft;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (var i = 0; i < shots.length; i++) ...[
          Expanded(
            child: _StampSlot(
              label: _shotLabel(shots[i]),
              filled: draft.has(shots[i]),
            ),
          ),
          if (i < shots.length - 1) const SizedBox(width: 8),
        ],
      ],
    );
  }
}

class _StampSlot extends StatelessWidget {
  const _StampSlot({required this.label, required this.filled});
  final String label;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: AppDurations.med,
      curve: kAppCurve,
      padding: const EdgeInsets.symmetric(vertical: 9),
      decoration: BoxDecoration(
        color: filled
            ? AppColors.emerald.withValues(alpha: 0.10)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(
          color: filled
              ? AppColors.emerald.withValues(alpha: 0.55)
              : AppColors.hairline,
          width: filled ? 1.4 : 1,
        ),
      ),
      child: Column(
        children: [
          Icon(
            filled ? Icons.verified_rounded : Icons.circle_outlined,
            size: 15,
            color: filled ? AppColors.emerald : AppColors.inkMute,
          ),
          const SizedBox(height: 4),
          Text(
            label.toUpperCase(),
            style: AppType.mono(9.5,
                color: filled ? AppColors.emeraldDeep : AppColors.inkMute,
                w: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

String _shotLabel(KycShot s) => switch (s) {
      KycShot.front => 'Front',
      KycShot.back => 'Back',
      KycShot.selfie => 'Selfie',
    };

String _shotTitle(KycShot s) => switch (s) {
      KycShot.front => 'Front of document',
      KycShot.back => 'Back of document',
      KycShot.selfie => 'Photo of your face',
    };

String _shotHint(KycShot s) => switch (s) {
      KycShot.front => 'The side with your photo and name.',
      KycShot.back => 'The side with the machine-readable strip.',
      KycShot.selfie => 'Look straight at the camera, no hat or sunglasses.',
    };

/// One document slot. Empty it reads as an unfilled document window (dashed
/// frame); filled it shows the photo with a Retake affordance.
class _ShotSlot extends StatelessWidget {
  const _ShotSlot({
    required this.slot,
    required this.file,
    required this.onShoot,
    required this.onPickFile,
  });
  final KycShot slot;
  final File? file;
  final VoidCallback onShoot;
  final VoidCallback onPickFile;

  @override
  Widget build(BuildContext context) {
    final filled = file != null;
    return Container(
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
          color: filled ? AppColors.emerald.withValues(alpha: 0.4) : AppColors.hairline,
        ),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_shotTitle(slot),
                        style: AppType.body(14, w: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(_shotHint(slot),
                        style: AppType.body(12,
                            color: AppColors.inkMute, height: 1.4)),
                  ],
                ),
              ),
              if (filled)
                Icon(Icons.check_circle_rounded,
                    size: 20, color: AppColors.emerald),
            ],
          ),
          const SizedBox(height: 12),
          if (filled)
            ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.sm),
              child: Image.file(
                file!,
                height: 150,
                width: double.infinity,
                fit: BoxFit.cover,
                // A file we just wrote can still fail to decode (corrupt
                // capture); show a readable fallback instead of a red box.
                errorBuilder: (_, _, _) => Container(
                  height: 150,
                  color: AppColors.parchmentDeep,
                  alignment: Alignment.center,
                  child: Text('Preview unavailable — retake this photo.',
                      style: AppType.body(12, color: AppColors.inkMute)),
                ),
              ),
            ).animate().fadeIn(duration: 240.ms)
          else
            _EmptyFrame(slot: slot),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _GhostButton(
                  icon: Icons.photo_camera_rounded,
                  label: filled ? 'Retake' : 'Take photo',
                  onTap: onShoot,
                  emphasis: !filled,
                ),
              ),
              const SizedBox(width: 10),
              _GhostButton(
                icon: Icons.image_outlined,
                label: 'Upload',
                onTap: onPickFile,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Dashed document window for an empty slot.
class _EmptyFrame extends StatelessWidget {
  const _EmptyFrame({required this.slot});
  final KycShot slot;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _DashedBorderPainter(),
      child: SizedBox(
        height: 118,
        width: double.infinity,
        child: Center(
          child: Icon(
            slot == KycShot.selfie
                ? Icons.person_outline_rounded
                : Icons.crop_free_rounded,
            size: 34,
            color: AppColors.inkMute.withValues(alpha: 0.5),
          ),
        ),
      ),
    );
  }
}

class _DashedBorderPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.inkMute.withValues(alpha: 0.35)
      ..strokeWidth = 1.2
      ..style = PaintingStyle.stroke;
    final rrect = RRect.fromRectAndRadius(
      Offset.zero & size,
      const Radius.circular(AppRadius.sm),
    );
    final path = Path()..addRRect(rrect);
    // Walk the outline emitting 6px dashes with 5px gaps.
    for (final metric in path.computeMetrics()) {
      var d = 0.0;
      while (d < metric.length) {
        final end = (d + 6).clamp(0.0, metric.length);
        canvas.drawPath(metric.extractPath(d, end), paint);
        d += 11;
      }
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _GhostButton extends StatelessWidget {
  const _GhostButton({
    required this.icon,
    required this.label,
    required this.onTap,
    this.emphasis = false,
  });
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool emphasis;

  @override
  Widget build(BuildContext context) {
    final color = emphasis ? AppColors.emerald : AppColors.inkSoft;
    return Material(
      color: emphasis ? AppColors.emerald.withValues(alpha: 0.08) : Colors.transparent,
      borderRadius: BorderRadius.circular(AppRadius.sm),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        onTap: onTap,
        child: Container(
          height: 42,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.sm),
            border: Border.all(
                color: emphasis
                    ? AppColors.emerald.withValues(alpha: 0.5)
                    : AppColors.hairline),
          ),
          alignment: Alignment.center,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: color),
              const SizedBox(width: 7),
              Text(label,
                  style: AppType.body(12.5, color: color, w: FontWeight.w700)),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- step 4

class _ConfirmStep extends StatelessWidget {
  const _ConfirmStep({
    required this.draft,
    required this.onEdit,
    required this.onSubmit,
  });
  final KycDraft draft;
  final VoidCallback onEdit;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    return _StepScroll(
      children: [
        const _Eyebrow('Step 3 of 3'),
        const SizedBox(height: 6),
        Text('Ready to submit',
            style: AppType.display(28, w: FontWeight.w400, height: 1.12)),
        const SizedBox(height: 10),
        Text(
          'Check the photos are sharp and the whole document is visible. '
          'You can still go back and retake any of them.',
          style: AppType.body(14, color: AppColors.inkSoft, height: 1.5),
        ),
        const SizedBox(height: 22),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text('Document',
                      style: AppType.body(12, color: AppColors.inkMute)),
                  const Spacer(),
                  Text(draft.documentType?.label ?? '—',
                      style: AppType.body(13, w: FontWeight.w700)),
                ],
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  for (final s in draft.requiredShots) ...[
                    Expanded(child: _Thumb(label: _shotLabel(s), file: draft.shot(s))),
                    if (s != draft.requiredShots.last)
                      const SizedBox(width: 10),
                  ],
                ],
              ),
              const SizedBox(height: 14),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: draft.submitting ? null : onEdit,
                  icon: const Icon(Icons.edit_outlined, size: 15),
                  label: const Text('Retake a photo'),
                  style: TextButton.styleFrom(
                    foregroundColor: AppColors.ink,
                    padding: EdgeInsets.zero,
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 18),
        Text(
          'By submitting you confirm this document is yours and the details '
          'match your ShipTrip account.',
          style: AppType.body(12, color: AppColors.inkMute, height: 1.45),
        ),
        const SizedBox(height: 20),
        PrimaryButton(
          label: draft.submitting ? 'Uploading…' : 'Submit for review',
          expand: true,
          color: AppColors.emerald,
          onTap: draft.submitting ? null : onSubmit,
        ),
        if (draft.submitting) ...[
          const SizedBox(height: 14),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const SizedBox(
                width: 13,
                height: 13,
                child: CircularProgressIndicator(
                    strokeWidth: 1.8, color: AppColors.emerald),
              ),
              const SizedBox(width: 9),
              Text('Sending your documents securely…',
                  style: AppType.body(12, color: AppColors.inkMute)),
            ],
          ),
        ],
      ],
    );
  }
}

class _Thumb extends StatelessWidget {
  const _Thumb({required this.label, required this.file});
  final String label;
  final File? file;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.xs),
          child: file == null
              ? Container(height: 78, color: AppColors.parchmentDeep)
              : Image.file(
                  file!,
                  height: 78,
                  width: double.infinity,
                  fit: BoxFit.cover,
                  errorBuilder: (_, _, _) =>
                      Container(height: 78, color: AppColors.parchmentDeep),
                ),
        ),
        const SizedBox(height: 5),
        Text(label.toUpperCase(),
            style: AppType.mono(9.5,
                color: AppColors.inkMute, w: FontWeight.w700)),
      ],
    );
  }
}

// ---------------------------------------------------------------- step 5

class _OutcomeStep extends ConsumerWidget {
  const _OutcomeStep({required this.result});
  final KycSubmissionResult? result;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final approved = result?.status == KycStatus.approved;
    return _StepScroll(
      children: [
        const SizedBox(height: 12),
        Center(
          child: Container(
            width: 92,
            height: 92,
            decoration: BoxDecoration(
              color: (approved ? AppColors.emerald : AppColors.gold)
                  .withValues(alpha: 0.12),
              shape: BoxShape.circle,
              border: Border.all(
                  color: approved ? AppColors.emerald : AppColors.gold,
                  width: 1.6),
            ),
            alignment: Alignment.center,
            child: Icon(
              approved ? Icons.verified_rounded : Icons.hourglass_top_rounded,
              size: 44,
              color: approved ? AppColors.emerald : AppColors.goldDeep,
            ),
          )
              .animate()
              .scale(
                  begin: const Offset(0.86, 0.86),
                  end: const Offset(1, 1),
                  duration: 420.ms,
                  curve: Curves.easeOutBack)
              .fadeIn(duration: 300.ms),
        ),
        const SizedBox(height: 22),
        Center(
          child: Text(
            approved ? 'You\'re verified' : 'Documents received',
            style: AppType.display(26, w: FontWeight.w400),
            textAlign: TextAlign.center,
          ),
        ),
        const SizedBox(height: 10),
        Text(
          approved
              ? 'Your identity is confirmed. Nothing else to do — you\'re '
                  'cleared to send and carry parcels.'
              : 'A reviewer will check them, usually within a day. We\'ll '
                  'notify you the moment there\'s a decision — you can keep '
                  'using ShipTrip in the meantime.',
          style: AppType.body(14, color: AppColors.inkSoft, height: 1.5),
          textAlign: TextAlign.center,
        ),
        if (result != null && !result!.created) ...[
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              color: AppColors.parchmentSoft,
              borderRadius: BorderRadius.circular(AppRadius.sm),
              border: Border.all(color: AppColors.hairline),
            ),
            child: Text(
              'We already had this submission on file, so we kept the '
              'original instead of creating a duplicate.',
              style: AppType.body(12, color: AppColors.inkMute, height: 1.45),
            ),
          ),
        ],
        const SizedBox(height: 28),
        PrimaryButton(
          label: 'Done',
          expand: true,
          color: AppColors.emerald,
          onTap: () {
            // Clear the draft so a later resubmission starts a genuinely new
            // one (fresh idempotency key) rather than replaying this.
            ref.read(kycDraftProvider.notifier).reset();
            safeBack(context, fallback: '/app');
          },
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------- shared

class _StepScroll extends StatelessWidget {
  const _StepScroll({required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 6, 20, 32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    );
  }
}

class _Eyebrow extends StatelessWidget {
  const _Eyebrow(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Text(text, style: AppType.eyebrow());
}
