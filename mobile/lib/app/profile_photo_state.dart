/// The member's profile photo: picking, preparing, uploading and removing.
///
/// This lives in a provider and not in the Profile screen's state because the
/// screen is a lazy list: scrolling the photo section away disposes it, and a
/// pending upload, its outcome and the busy flag must outlive that. The state
/// is scoped to the signed-in account and starts over when the account
/// changes.
///
/// **An upload is sent once per press.** Nothing here retries one: not on a
/// failure, not on a reconnect, and (see `ApiClient.upload`) not after a token
/// refresh. A retry is the member pressing a button, and each press is a new
/// upload.
library;

import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../core/api/api_exception.dart';
import '../core/api/error_codes.dart';
import '../core/media/photo_prepare.dart';
import '../core/media/pick_guard.dart';
import '../core/session/session.dart';
import 'discovery_state.dart';

/// The server's ceiling for a profile photo. The prepared JPEG is far below
/// it; the check is kept so an unexpected file is never sent.
const _maxPhotoBytes = 10 * 1024 * 1024;

/// Opens the device's camera or photo library and returns the original.
typedef ProfilePhotoPicker = Future<XFile?> Function(ImageSource source);

/// Downscales a picked file and returns the path of the JPEG it wrote.
typedef ProfilePhotoPreparer = Future<String> Function(String sourcePath);

/// The picker, behind a provider: the seam a widget test overrides, because a
/// test runner has no camera. It asks for the original: the native step that
/// follows downscales it without decoding all of it. (Who the pick belongs to
/// is [PickGuard]'s business, and the controller's, not this seam's.)
final profilePhotoPickerProvider = Provider<ProfilePhotoPicker>(
  (ref) =>
      (source) => ref.read(imagePickerProvider).pickImage(source: source),
);

/// The platform's one method for preparing a photo (`wassla/photo_prepare`).
final profilePhotoPreparerProvider = Provider<ProfilePhotoPreparer>(
  (ref) => prepareProfilePhoto,
);

/// Why a photo did not go up, as the member needs to hear it.
enum ProfilePhotoFailure {
  tooLarge,
  unsupported,
  accountInactive,
  storageUnavailable,
  offline,
  general,

  /// The picked file could not be read (the phone cleared it): pick again.
  unreadable,

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

enum ProfilePhotoPhase { idle, uploading, failed }

/// A prepared file waiting to go up, or that failed and can go up again.
@immutable
class PickedPhoto {
  const PickedPhoto({
    required this.path,
    required this.contentType,
    required this.fileName,
  });

  /// A JPEG (or whatever its bytes say it is) at a path used for this pick
  /// only.
  final String path;

  /// Read from the file's first bytes, never from its name.
  final String contentType;
  final String fileName;
}

@immutable
class ProfilePhotoState {
  const ProfilePhotoState({
    this.phase = ProfilePhotoPhase.idle,
    this.failure,
    this.picked,
    this.progress = 0,
    this.removing = false,
    this.awaitingConfirmation = false,
    this.picking = false,
  });

  final ProfilePhotoPhase phase;
  final ProfilePhotoFailure? failure;
  final PickedPhoto? picked;
  final double progress;
  final bool removing;

  /// A photo recovered after the phone ended the app: it is shown for the
  /// member to confirm and is never uploaded without that.
  final bool awaitingConfirmation;

  /// The camera or library is open, or about to be: reserved at the first tap,
  /// so a second tap cannot open it again.
  final bool picking;

  bool get uploading => phase == ProfilePhotoPhase.uploading;
  bool get busy => uploading || removing || picking;

  ProfilePhotoState copyWith({
    ProfilePhotoPhase? phase,
    ProfilePhotoFailure? failure,
    bool clearFailure = false,
    PickedPhoto? picked,
    bool clearPicked = false,
    double? progress,
    bool? removing,
    bool? awaitingConfirmation,
    bool? picking,
  }) => ProfilePhotoState(
    phase: phase ?? this.phase,
    failure: clearFailure ? null : failure ?? this.failure,
    picked: clearPicked ? null : picked ?? this.picked,
    progress: progress ?? this.progress,
    removing: removing ?? this.removing,
    awaitingConfirmation: awaitingConfirmation ?? this.awaitingConfirmation,
    picking: picking ?? this.picking,
  );
}

final profilePhotoProvider =
    NotifierProvider<ProfilePhotoController, ProfilePhotoState>(
      ProfilePhotoController.new,
    );

class ProfilePhotoController extends Notifier<ProfilePhotoState> {
  bool _recoveryTried = false;

  /// Every prepared file this controller made and has not yet deleted.
  final _owned = <String>{};

  /// The file an upload is reading right now: not deleted until the upload
  /// has finished with it.
  String? _uploadingPath;

  @override
  ProfilePhotoState build() {
    // Watched for its id only: a new account starts from nothing.
    ref.watch(accountProvider.select((a) => a?.id));
    // And listened to from the container, because a rebuild waits for the next
    // read and a provider nobody watches pauses its own listeners: the moment
    // the account changes (sign-out, another member signing in) any step still
    // running for the old one stops being live, and the prepared files go,
    // except one an upload is still reading (that upload deletes it when it
    // lets go).
    final accountChanges = ref.container.listen(
      accountProvider.select((a) => a?.id),
      (previous, next) {
        if (previous == next) return;
        _deleteOwned();
        _recoveryTried = false;
        state = const ProfilePhotoState();
      },
    );
    ref.onDispose(accountChanges.close);
    _recoveryTried = false;
    ref.onDispose(_deleteOwned);
    return const ProfilePhotoState();
  }

  void _deleteOwned() {
    for (final path in _owned.toList()) {
      if (path == _uploadingPath) continue;
      _owned.remove(path);
      try {
        File(path).deleteSync();
      } on FileSystemException {
        // Already gone.
      }
    }
  }

  /// Whose photo a step is working on: the signed-in account when it began.
  int? get _owner => ref.read(accountProvider)?.id;

  /// Still the same account, asked of the session itself at the moment of
  /// asking: a step that began for member A never writes anything for member B,
  /// however late its answer comes.
  bool _live(int? owner) =>
      ref.mounted && ref.read(accountProvider)?.id == owner;

  /// Opens the camera or library, prepares what comes back, and uploads it.
  /// Returns true when the photo was saved.
  Future<bool> pick(ImageSource source) async {
    if (state.busy) return false;
    // Reserved before the first await: a second tap finds it taken, and only
    // this call writes and clears the pick's marker.
    state = state.copyWith(picking: true);
    final epoch = _owner;
    final guard = ref.read(pickGuardProvider);
    final ticket = await guard.begin(PickPurpose.profilePhoto);
    XFile? picked;
    try {
      picked = await ref.read(profilePhotoPickerProvider)(source);
    } on PlatformException {
      await guard.end(ticket);
      if (_live(epoch)) _fail(ProfilePhotoFailure.pickFailed);
      return false;
    }
    await guard.end(ticket);
    if (!_live(epoch)) return false;
    state = state.copyWith(picking: false);
    if (picked == null) return false;
    final prepared = await _prepare(picked.path, epoch);
    if (prepared == null) return false;
    return upload();
  }

  /// After the phone ended the app while the camera or library was open:
  /// offers the photo that was being picked, for the member to confirm. It is
  /// offered only when the lost pick was a profile photo for this account,
  /// and only once.
  Future<void> recoverLostPick() async {
    if (_recoveryTried || state.busy || state.picked != null) return;
    _recoveryTried = true;
    final epoch = _owner;
    final lost = await ref
        .read(pickGuardProvider)
        .recoverLost(PickPurpose.profilePhoto);
    if (lost == null || !_live(epoch)) return;
    final prepared = await _prepare(lost.path, epoch);
    if (prepared == null || !_live(epoch)) return;
    state = state.copyWith(awaitingConfirmation: true);
  }

  /// The member accepted the recovered photo.
  Future<bool> confirmRecovered() {
    state = state.copyWith(awaitingConfirmation: false);
    return upload();
  }

  /// Sends the prepared photo. Returns true when the server saved it.
  Future<bool> upload() async {
    final photo = state.picked;
    if (photo == null || state.busy || state.awaitingConfirmation) return false;
    final epoch = _owner;
    _uploadingPath = photo.path;
    state = state.copyWith(
      phase: ProfilePhotoPhase.uploading,
      clearFailure: true,
      progress: 0,
    );
    try {
      await ref
          .read(sessionProvider.notifier)
          .uploadPhoto(
            filePath: photo.path,
            fileName: photo.fileName,
            contentType: photo.contentType,
            onProgress: (sent, total) {
              if (_live(epoch) && total > 0) {
                state = state.copyWith(progress: sent / total);
              }
            },
          );
    } on ApiException catch (error) {
      _uploadingPath = null;
      if (!_live(epoch)) {
        await _release(photo.path);
        return false;
      }
      final failure = ProfilePhotoFailure.of(error);
      if (!failure.canRetry) {
        // A file the server will never accept is not kept, and neither is
        // one a banned account cannot send.
        await _drop(photo);
        _fail(failure);
      } else if (!await File(photo.path).exists()) {
        // The phone cleared the file between the pick and the stream: a
        // retry could only fail the same way.
        await _drop(photo);
        if (_live(epoch)) _fail(ProfilePhotoFailure.unreadable);
      } else {
        state = state.copyWith(
          phase: ProfilePhotoPhase.failed,
          failure: failure,
        );
      }
      return false;
    } on FileSystemException {
      // The phone cleared the file between the pick and the upload.
      _uploadingPath = null;
      if (!_live(epoch)) {
        await _release(photo.path);
        return false;
      }
      await _drop(photo);
      _fail(ProfilePhotoFailure.unreadable);
      return false;
    }
    _uploadingPath = null;
    if (!_live(epoch)) {
      await _release(photo.path);
      return false;
    }
    await _drop(photo);
    state = const ProfilePhotoState();
    _refreshOwnPhotoReads();
    return true;
  }

  /// The member gave up on the photo that is waiting.
  Future<void> discard() async {
    final photo = state.picked;
    if (photo != null) await _drop(photo);
    if (ref.mounted) state = const ProfilePhotoState();
  }

  /// Removes the photo, or dismisses the notice that Wassla removed it.
  /// Returns the server's refusal, or null when it worked.
  Future<ApiException?> remove() async {
    if (state.busy) return null;
    final epoch = _owner;
    state = state.copyWith(removing: true);
    try {
      await ref.read(sessionProvider.notifier).removePhoto();
    } on ApiException catch (error) {
      if (_live(epoch)) state = state.copyWith(removing: false);
      return error;
    }
    if (!_live(epoch)) return null;
    // Whatever went wrong with an earlier replacement is obsolete now.
    final pending = state.picked;
    if (pending != null) await _drop(pending);
    state = const ProfilePhotoState();
    _refreshOwnPhotoReads();
    return null;
  }

  /// Prepares [sourcePath] and keeps the result as the pending photo; a pick
  /// it replaces has its file deleted.
  Future<PickedPhoto?> _prepare(String sourcePath, int? epoch) async {
    state = state.copyWith(
      phase: ProfilePhotoPhase.uploading,
      clearFailure: true,
      progress: 0,
    );
    String? output;
    try {
      output = await ref.read(profilePhotoPreparerProvider)(sourcePath);
      _owned.add(output);
      final type = sniffImageType(await readHead(output));
      if (type == null) throw const UnsupportedPhoto();
      if (await File(output).length() > _maxPhotoBytes) {
        await _release(output);
        if (_live(epoch)) _fail(ProfilePhotoFailure.tooLarge);
        return null;
      }
      if (!_live(epoch)) {
        await _release(output);
        return null;
      }
      final photo = PickedPhoto(
        path: output,
        contentType: type,
        fileName: 'photo.${extensionFor(type)}',
      );
      final replaced = state.picked;
      state = state.copyWith(
        phase: ProfilePhotoPhase.idle,
        picked: photo,
        clearFailure: true,
      );
      if (replaced != null && replaced.path != photo.path) {
        await _release(replaced.path);
      }
      return photo;
    } on FileSystemException {
      if (output != null) await _release(output);
      if (_live(epoch)) _fail(ProfilePhotoFailure.unreadable);
    } on UnsupportedPhoto {
      if (output != null) await _release(output);
      if (_live(epoch)) _fail(ProfilePhotoFailure.unsupported);
    }
    return null;
  }

  void _fail(ProfilePhotoFailure failure) {
    state = ProfilePhotoState(
      phase: ProfilePhotoPhase.failed,
      failure: failure,
      picked: state.picked,
    );
  }

  /// Deletes [photo]'s file and forgets it as the pending photo.
  Future<void> _drop(PickedPhoto photo) async {
    await _release(photo.path);
    if (ref.mounted && identical(state.picked, photo)) {
      state = state.copyWith(clearPicked: true);
    }
  }

  /// Deletes a prepared file this controller made.
  Future<void> _release(String path) async {
    _owned.remove(path);
    await deleteQuietly(path);
  }

  /// Every retained read that holds the member's own photo, so none keeps
  /// showing the old one: the own public profile (and its preview) and any
  /// person page, which may be the member's own.
  void _refreshOwnPhotoReads() {
    ref
      ..invalidate(ownProfileProvider)
      ..invalidate(personProvider);
  }
}
