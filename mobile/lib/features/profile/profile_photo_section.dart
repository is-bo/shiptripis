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
/// **A photo is uploaded once per tap.** The upload is never retried by the
/// app; every retry is the member pressing the button again, because each
/// upload stores a new photo on the server.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/session/session.dart';
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

/// The server's ceiling for a profile photo. Checked here as well, so an
/// oversized file is refused before it is pushed up a mobile uplink.
const _maxPhotoBytes = 10 * 1024 * 1024;

const _allowedPhotoTypes = {'image/jpeg', 'image/png', 'image/webp'};

/// The edge, in pixels, the picker scales a photo down to in native code. The
/// server keeps a 512 px square, so 1024 leaves room to crop without sending a
/// camera original.
const _photoMaxEdge = 1024.0;
const _photoQuality = 88;

/// Opens the device's camera or photo library.
typedef ProfilePhotoPicker = Future<XFile?> Function(ImageSource source);

/// The picker, behind a provider: one place for the resize policy, and the
/// seam a widget test overrides, because a test runner has no camera.
final profilePhotoPickerProvider = Provider<ProfilePhotoPicker>((ref) {
  final picker = ImagePicker();
  return (source) => picker.pickImage(
    source: source,
    maxWidth: _photoMaxEdge,
    maxHeight: _photoMaxEdge,
    imageQuality: _photoQuality,
  );
});

/// Why a photo did not go up, as the member needs to hear it.
enum ProfilePhotoFailure {
  tooLarge,
  unsupported,
  accountInactive,
  storageUnavailable,
  offline,
  general,

  /// The camera or library would not open: usually a refused permission.
  pickFailed;

  /// The same file may succeed if the member presses the button again.
  bool get canRetry =>
      this == storageUnavailable || this == offline || this == general;

  /// Reads the server's refusal. **Any 413 is "too large"**, whatever its
  /// body: the edge proxy refuses an oversized body with no JSON at all.
  static ProfilePhotoFailure of(ApiException error) {
    if (error.statusCode == 413 ||
        error.code == ApiErrorCode.profilePhotoTooLarge) {
      return tooLarge;
    }
    if (error.statusCode == 415 ||
        error.code == ApiErrorCode.profilePhotoMediaTypeUnsupported) {
      return unsupported;
    }
    if (error.code == ApiErrorCode.accountInactive) return accountInactive;
    if (error.code == ApiErrorCode.profilePhotoStorageUnavailable) {
      return storageUnavailable;
    }
    return switch (error.kind) {
      ApiFailureKind.offline || ApiFailureKind.timeout => offline,
      _ => general,
    };
  }
}

enum _Phase { idle, uploading, failed }

class ProfilePhotoSection extends ConsumerStatefulWidget {
  const ProfilePhotoSection({required this.account, super.key});

  final Account account;

  @override
  ConsumerState<ProfilePhotoSection> createState() =>
      _ProfilePhotoSectionState();
}

class _ProfilePhotoSectionState extends ConsumerState<ProfilePhotoSection> {
  _Phase _phase = _Phase.idle;
  ProfilePhotoFailure? _failure;

  /// The file being uploaded, or the one that failed and can be tried again.
  XFile? _picked;
  String _pickedType = '';
  double _progress = 0;
  bool _removing = false;

  bool get _busy => _phase == _Phase.uploading || _removing;

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
    XFile? picked;
    try {
      picked = await ref.read(profilePhotoPickerProvider)(source);
    } on PlatformException {
      if (!mounted) return;
      setState(() {
        _picked = null;
        _phase = _Phase.failed;
        _failure = ProfilePhotoFailure.pickFailed;
      });
      return;
    }
    if (picked == null || !mounted) return;

    final type = picked.mimeType ?? _typeFromPath(picked.path);
    final bytes = await picked.length();
    if (!mounted) return;
    final refusal = bytes > _maxPhotoBytes
        ? ProfilePhotoFailure.tooLarge
        : !_allowedPhotoTypes.contains(type)
        ? ProfilePhotoFailure.unsupported
        : null;
    if (refusal != null) {
      setState(() {
        _picked = null;
        _phase = _Phase.failed;
        _failure = refusal;
      });
      return;
    }

    setState(() {
      _picked = picked;
      _pickedType = type;
    });
    await _upload();
  }

  Future<void> _upload() async {
    final file = _picked;
    if (file == null || _busy) return;
    final l = L.of(context);
    setState(() {
      _phase = _Phase.uploading;
      _failure = null;
      _progress = 0;
    });
    try {
      await ref
          .read(sessionProvider.notifier)
          .uploadPhoto(
            filePath: file.path,
            fileName: file.name,
            contentType: _pickedType,
            onProgress: (sent, total) {
              if (mounted && total > 0) {
                setState(() => _progress = sent / total);
              }
            },
          );
      if (!mounted) return;
      setState(() {
        _picked = null;
        _phase = _Phase.idle;
      });
      AppSnack.success(context, l.profilePhotoUpdated);
    } on ApiException catch (error) {
      if (!mounted) return;
      final failure = ProfilePhotoFailure.of(error);
      setState(() {
        _phase = _Phase.failed;
        _failure = failure;
        // A file the server will never accept is not kept, and neither is
        // one a banned account cannot send; the rest stay selected so the
        // member can press the button again.
        if (!failure.canRetry) _picked = null;
      });
    }
  }

  Future<void> _remove({required bool confirm}) async {
    if (_busy) return;
    final l = L.of(context);
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
    setState(() => _removing = true);
    try {
      await ref.read(sessionProvider.notifier).removePhoto();
      if (!mounted) return;
      setState(() => _removing = false);
      if (confirm) AppSnack.success(context, l.profilePhotoRemoved);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _removing = false);
      AppSnack.failure(context, error);
    }
  }

  static String _typeFromPath(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.webp')) return 'image/webp';
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
    return '';
  }

  String _failureCopy(L l, ProfilePhotoFailure failure) => switch (failure) {
    ProfilePhotoFailure.tooLarge => l.profilePhotoTooLarge,
    ProfilePhotoFailure.unsupported => l.profilePhotoTypeNotAllowed,
    ProfilePhotoFailure.accountInactive => l.profilePhotoAccountInactive,
    ProfilePhotoFailure.storageUnavailable => l.profilePhotoStorageUnavailable,
    ProfilePhotoFailure.offline => l.profilePhotoOffline,
    ProfilePhotoFailure.general => l.profilePhotoFailed,
    ProfilePhotoFailure.pickFailed => l.profilePhotoPickFailed,
  };

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final account = widget.account;
    final own = account.photo;
    final name = account.fullName.trim().isEmpty
        ? account.email
        : account.fullName;
    final uploading = _phase == _Phase.uploading;
    final removedByWassla = own != null && own.isRemoved;
    final hasPhoto = own != null && !own.isRemoved;
    final failure = _phase == _Phase.failed ? _failure : null;

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
                    picked: _picked,
                    uploading: uploading,
                    progress: _progress,
                    name: name,
                    initials: initialsFor(name),
                    account: account,
                  ),
                  const SizedBox(width: AppSpace.lg),
                  Expanded(
                    child: uploading
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
                  onAction: _busy ? null : () => _remove(confirm: false),
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
                  onAction: failure.canRetry && !_busy ? _upload : null,
                ),
              ],
              const SizedBox(height: AppSpace.lg),
              if (hasPhoto && _picked == null) ...[
                AppButton(
                  label: l.profilePhotoChange,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_camera_outlined,
                  onPressed: _busy ? null : _choose,
                ),
                const SizedBox(height: AppSpace.sm),
                AppButton(
                  label: l.profilePhotoRemove,
                  variant: AppButtonVariant.tertiary,
                  icon: Icons.delete_outline_rounded,
                  isLoading: _removing,
                  onPressed: _busy ? null : () => _remove(confirm: true),
                ),
              ] else ...[
                AppButton(
                  label: l.profilePhotoTake,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_camera_outlined,
                  onPressed: _busy ? null : () => _pick(ImageSource.camera),
                ),
                const SizedBox(height: AppSpace.sm),
                AppButton(
                  label: l.profilePhotoChoose,
                  variant: AppButtonVariant.secondary,
                  icon: Icons.photo_library_outlined,
                  onPressed: _busy ? null : () => _pick(ImageSource.gallery),
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
        : '${l.profilePhotoWasslaBody}\n${l.profilePhotoWasslaReason(reason)}';
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
    required this.account,
  });

  static const double _size = 96;

  final XFile? picked;
  final bool uploading;
  final double progress;
  final String name;
  final String initials;
  final Account account;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final file = picked;

    if (file == null) {
      return AppAvatar(
        initials: initials,
        name: name,
        photo: account.photo?.photo,
        size: _size,
      );
    }

    // The centred square the server will keep, drawn from the local file: the
    // bytes are on the device already.
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
