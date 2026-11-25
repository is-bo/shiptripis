/// The profile photo section of Profile (spec 21).
///
/// A member adds, changes and removes one optional photo. Everyone who sees
/// their first name sees it at once, guests included: there is no review step,
/// so there is no "waiting" state. Staff can remove a photo later, and then the
/// member sees that here, with the reason, until they dismiss it or add a new
/// one.
///
/// The server stores a centred square, so the preview crops to one: what the
/// member sees while uploading is what others will see.
///
/// What is picked, uploaded or refused lives in `profilePhotoProvider` and not
/// here: the Profile list is lazy, so this widget is disposed when it scrolls
/// away, and a pending upload, its outcome and its busy flag must survive that.
/// **A photo is uploaded once per press**; every retry is the member pressing a
/// button.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../app/profile_photo_state.dart';
import '../../design/components/feedback.dart';
import '../../design/components/images.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/account.dart';
import '../../domain/person_photo.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';

class ProfilePhotoSection extends ConsumerStatefulWidget {
  const ProfilePhotoSection({required this.account, super.key});

  final Account account;

  @override
  ConsumerState<ProfilePhotoSection> createState() =>
      _ProfilePhotoSectionState();
}

class _ProfilePhotoSectionState extends ConsumerState<ProfilePhotoSection> {
  @override
  void initState() {
    super.initState();
    // If the phone ended the app while the camera was open, the photo being
    // taken is offered here for the member to confirm. The controller does it
    // once, whatever number of times this scrolls into view.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        ref.read(profilePhotoProvider.notifier).recoverLostPick();
      }
    });
  }

  ProfilePhotoController get _controller =>
      ref.read(profilePhotoProvider.notifier);

  Future<void> _choose() async {
    final source = await showAppSheet<ImageSource>(
      context,
      builder: (sheetContext) {
        final l = L.of(sheetContext);
        return AppChoiceSheet<ImageSource>(
          title: l.profilePhotoTitle,
          selected: null,
          options: [
            AppSheetOption(
              value: ImageSource.camera,
              label: l.profilePhotoTake,
              icon: Icons.photo_camera_outlined,
            ),
            AppSheetOption(
              value: ImageSource.gallery,
              label: l.profilePhotoChoose,
              icon: Icons.photo_library_outlined,
            ),
          ],
        );
      },
    );
    if (source != null) await _pick(source);
  }

  Future<void> _pick(ImageSource source) async {
    final l = L.of(context);
    final saved = await _controller.pick(source);
    if (saved && mounted) AppSnack.success(context, l.profilePhotoUpdated);
  }

  Future<void> _upload() async {
    final l = L.of(context);
    final saved = await _controller.upload();
    if (saved && mounted) AppSnack.success(context, l.profilePhotoUpdated);
  }

  Future<void> _useRecovered() async {
    final l = L.of(context);
    final saved = await _controller.confirmRecovered();
    if (saved && mounted) AppSnack.success(context, l.profilePhotoUpdated);
  }

  Future<void> _remove({required bool confirm}) async {
    final l = L.of(context);
    if (ref.read(profilePhotoProvider).busy) return;
    if (confirm) {
      final ok = await confirmAction(
        context,
        title: l.profilePhotoRemoveTitle,
        body: l.profilePhotoRemoveBody,
        confirmLabel: l.profilePhotoRemove,
        isDestructive: true,
      );
      if (!ok || !mounted) return;
    }
    final error = await _controller.remove();
    if (!mounted) return;
    if (error != null) {
      AppSnack.failure(context, error);
    } else if (confirm) {
      AppSnack.success(context, l.profilePhotoRemoved);
    }
  }

  String _failureCopy(L l, ProfilePhotoFailure failure) => switch (failure) {
    ProfilePhotoFailure.tooLarge => l.profilePhotoTooLarge,
    ProfilePhotoFailure.unsupported => l.profilePhotoTypeNotAllowed,
    ProfilePhotoFailure.accountInactive => l.profilePhotoAccountInactive,
    ProfilePhotoFailure.storageUnavailable => l.profilePhotoStorageUnavailable,
    ProfilePhotoFailure.offline => l.profilePhotoOffline,
    ProfilePhotoFailure.general => l.profilePhotoFailed,
    ProfilePhotoFailure.unreadable => l.profilePhotoUnreadable,
    ProfilePhotoFailure.pickFailed => l.profilePhotoPickFailed,
  };

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final account = widget.account;
    final photo = ref.watch(profilePhotoProvider);
    final own = account.photo;
    final name = account.fullName.trim().isEmpty
        ? account.email
        : account.fullName;
    final removedByWassla = own != null && own.isRemoved;
    // An active photo the server could not sign is still the member's photo:
    // initials are drawn, and it can still be changed or removed.
    final hasPhoto = own != null && own.isActive;
    final failure = photo.phase == ProfilePhotoPhase.failed
        ? photo.failure
        : null;
    final confirming = photo.awaitingConfirmation && photo.picked != null;

    final help = hasPhoto ? l.profilePhotoHelpActive : l.profilePhotoHelpEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.profilePhotoTitle),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _PhotoFrame(
                    picked: photo.picked,
                    uploading: photo.uploading,
                    progress: photo.progress,
                    name: name,
                    initials: initialsFor(name),
                    photo: own?.photo,
                  ),
                  const SizedBox(width: AppSpace.lg),
                  Expanded(
                    child: photo.uploading
                        ? Semantics(
                            liveRegion: true,
                            child: Text(
                              l.profilePhotoUploading,
                              style: text.bodyMedium,
                            ),
                          )
                        : Text(
                            help,
                            style: text.bodySmall?.copyWith(
                              color: c.textSecondary,
                            ),
                          ),
                  ),
                ],
              ),
              if (removedByWassla) ...[
                const SizedBox(height: AppSpace.lg),
                InfoNotice(
                  title: l.profilePhotoWassla,
                  message: _removedMessage(l, own),
                  tone: StatusTone.bad,
                  icon: Icons.no_photography_outlined,
                  actionLabel: l.profilePhotoDismiss,
                  onAction: photo.busy ? null : () => _remove(confirm: false),
                ),
              ],
              if (confirming) ...[
                const SizedBox(height: AppSpace.lg),
                InfoNotice(
                  message: l.profilePhotoRecovered,
                  tone: StatusTone.waiting,
                  icon: Icons.restore_rounded,
                ),
              ],
              if (failure != null) ...[
                const SizedBox(height: AppSpace.lg),
                InfoNotice(
                  message: _failureCopy(l, failure),
                  tone: failure.canRetry ? StatusTone.waiting : StatusTone.bad,
                  icon: switch (failure) {
                    ProfilePhotoFailure.offline => Icons.wifi_off_rounded,
                    ProfilePhotoFailure.storageUnavailable ||
                    ProfilePhotoFailure.general => Icons.cloud_off_rounded,
                    _ => Icons.error_outline_rounded,
                  },
                  actionLabel: failure.canRetry ? l.actionRetry : null,
                  onAction: failure.canRetry && !photo.busy ? _upload : null,
                ),
              ],
              const SizedBox(height: AppSpace.lg),
              if (confirming) ...[
                AppButton(
                  label: l.profilePhotoUse,
                  icon: Icons.check_rounded,
                  onPressed: photo.busy ? null : _useRecovered,
                ),
              ] else if (hasPhoto) ...[
                AppButton(
                  label: l.profilePhotoChange,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_camera_outlined,
                  onPressed: photo.busy ? null : _choose,
                ),
                const SizedBox(height: AppSpace.sm),
                // Stays available beside a failed replacement: the photo
                // others see is the one on the server.
                AppButton(
                  label: l.profilePhotoRemove,
                  variant: AppButtonVariant.tertiary,
                  icon: Icons.delete_outline_rounded,
                  isLoading: photo.removing,
                  onPressed: photo.busy ? null : () => _remove(confirm: true),
                ),
              ] else ...[
                AppButton(
                  label: l.profilePhotoTake,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_camera_outlined,
                  onPressed: photo.busy
                      ? null
                      : () => _pick(ImageSource.camera),
                ),
                const SizedBox(height: AppSpace.sm),
                AppButton(
                  label: l.profilePhotoChoose,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_library_outlined,
                  onPressed: photo.busy
                      ? null
                      : () => _pick(ImageSource.gallery),
                ),
              ],
              if (photo.picked != null && !photo.uploading) ...[
                const SizedBox(height: AppSpace.sm),
                AppButton(
                  label: l.profilePhotoDiscard,
                  variant: AppButtonVariant.tertiary,
                  icon: Icons.close_rounded,
                  onPressed: photo.busy ? null : _controller.discard,
                ),
              ],
              const SizedBox(height: AppSpace.md),
              Text(
                l.profilePhotoFormatRule,
                style: text.bodySmall?.copyWith(color: c.textTertiary),
              ),
            ],
          ),
        ),
      ],
    );
  }

  /// What Wassla said, or the generic sentence when it gave no reason.
  static String _removedMessage(L l, OwnPhoto photo) {
    final reason = photo.reason?.trim() ?? '';
    return reason.isEmpty
        ? l.profilePhotoWasslaBody
        // The reason is staff's own words, in any language: isolated, so it
        // cannot reorder the label around it in a right-to-left sentence.
        : '${l.profilePhotoWasslaBody}\n'
              '${l.profilePhotoWasslaReason('\u2068$reason\u2069')}';
  }
}

/// The photo, its initials, or the file going up. 96 dp square so it stays
/// well clear of a 360 dp screen's edges.
class _PhotoFrame extends StatelessWidget {
  const _PhotoFrame({
    required this.picked,
    required this.uploading,
    required this.progress,
    required this.name,
    required this.initials,
    required this.photo,
  });

  static const double _size = 96;

  final PickedPhoto? picked;
  final bool uploading;
  final double progress;
  final String name;
  final String initials;
  final PersonPhoto? photo;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final file = picked;

    if (file == null) {
      return AppAvatar(
        initials: initials,
        name: name,
        photo: photo,
        size: _size,
      );
    }

    // The centred square the server will keep, drawn from the local file: the
    // bytes are on the device already. Each pick has a path of its own, so a
    // new photo is never drawn as an earlier one cached under the same name.
    return Semantics(
      image: true,
      label: l.profilePhotoPreview,
      child: ExcludeSemantics(
        child: ClipRRect(
          borderRadius: AppRadius.rMd,
          child: SizedBox(
            width: _size,
            height: _size,
            child: Stack(
              fit: StackFit.expand,
              children: [
                Image.file(
                  File(file.path),
                  key: ValueKey(file.path),
                  fit: BoxFit.cover,
                  cacheWidth: decodeWidthFor(context, _size),
                  errorBuilder: (_, _, _) => ColoredBox(
                    color: c.surfaceSunken,
                    child: Icon(
                      Icons.image_not_supported_outlined,
                      color: c.textTertiary,
                    ),
                  ),
                ),
                if (uploading)
                  ColoredBox(
                    color: c.surface.withValues(alpha: 0.55),
                    child: Center(
                      child: SizedBox(
                        width: 36,
                        height: 36,
                        child: CircularProgressIndicator(
                          value: progress == 0 ? null : progress,
                          strokeWidth: 3,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
