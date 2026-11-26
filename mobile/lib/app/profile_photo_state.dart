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
///
/// **A photo belongs to the press that started it.** Every step of a pick, its
/// preparation and its upload checks, after each wait, that the account, the
/// credentials (`TokenStore.identityGeneration`, read at the press and carried
/// to the moment the upload is sent) and the operation are still the ones the
/// press began under; if not, the step stops and writes nothing. A prepared
/// photo keeps the account and credentials it was made under ([PickedPhoto]), so
/// pressing "try again" later is checked against **those**, never against
/// whoever is signed in by then: a file prepared for one member is not sent
/// with another's token, even in the moment between the new member's tokens
/// being saved and their account being published. Only the operation that owns
/// the state ever starts it over. And the photo that comes back from the picker
/// is used only when [PickGuard] can vouch for it: this flow never recovers a
/// photo the phone lost when it ended the app, and never receives one that may
/// have been meant for another pick.
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
  pickFailed,

  /// The pick could not be given an owner in secure storage, so no picker was
  /// opened.
  pickBlocked,

  /// The picker answered, but not provably for this press (an earlier pick may
  /// have been the one that answered): the photo was not used. Pick again.
  pickUncertain,

  /// The platform could not get the photo ready (memory, a write): not the
  /// picture's fault, so a different attempt may work.
  prepareFailed;

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
    required this.owner,
    required this.identity,
  });

  /// A JPEG (or whatever its bytes say it is) at a path used for this pick
  /// only.
  final String path;

  /// Read from the file's first bytes, never from its name.
  final String contentType;
  final String fileName;

  /// The account and the credential generation the photo was made for: an
  /// upload of it is sent only while both are still current.
  final int? owner;
  final int identity;
}

@immutable
class ProfilePhotoState {
  const ProfilePhotoState({
    this.phase = ProfilePhotoPhase.idle,
    this.failure,
    this.picked,
    this.progress = 0,
    this.removing = false,
    this.picking = false,
  });

  final ProfilePhotoPhase phase;
  final ProfilePhotoFailure? failure;
  final PickedPhoto? picked;
  final double progress;
  final bool removing;

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
    bool? picking,
  }) => ProfilePhotoState(
    phase: phase ?? this.phase,
    failure: clearFailure ? null : failure ?? this.failure,
    picked: clearPicked ? null : picked ?? this.picked,
    progress: progress ?? this.progress,
    removing: removing ?? this.removing,
    picking: picking ?? this.picking,
  );
}

final profilePhotoProvider =
    NotifierProvider<ProfilePhotoController, ProfilePhotoState>(
      ProfilePhotoController.new,
    );

/// What a press began under: the account, the credential generation and the
/// operation. A step that finds any of the three changed is not live and
/// writes nothing.
typedef _Launch = ({int? owner, int identity, int epoch});

class ProfilePhotoController extends Notifier<ProfilePhotoState> {
  /// Every prepared file this controller made and has not yet deleted.
  final _owned = <String>{};

  /// The file an upload is reading right now: not deleted until the upload
  /// has finished with it.
  String? _uploadingPath;

  /// Moves whenever the account changes or the member discards the photo, so a
  /// step that began before cannot be mistaken for one that began after.
  int _epoch = 0;

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
        _epoch++;
        _deleteOwned();
        state = const ProfilePhotoState();
      },
    );
    ref.onDispose(accountChanges.close);
    _epoch++;
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

  /// What a press that starts now begins under, read at the press itself, before
  /// any wait. The press takes a new epoch of its own, so that whatever an
  /// earlier press left waiting can no longer reset what this one is doing.
  _Launch _launch() => (
    owner: ref.read(accountProvider)?.id,
    identity: ref.read(tokenStoreProvider).identityGeneration,
    epoch: ++_epoch,
  );

  /// The launch of a retry: the account and credentials [photo] was prepared
  /// under, in an epoch of its own.
  _Launch _launchFor(PickedPhoto photo) =>
      (owner: photo.owner, identity: photo.identity, epoch: ++_epoch);

  /// Still what [launch] began under, asked of the session and the token store
  /// themselves at the moment of asking: a step that began for member A never
  /// writes anything for member B, however late its answer comes, and a
  /// sign-in whose tokens are saved before the account is published already
  /// ends the step.
  bool _live(_Launch launch) =>
      ref.mounted &&
      launch.epoch == _epoch &&
      ref.read(accountProvider)?.id == launch.owner &&
      ref.read(tokenStoreProvider).identityGeneration == launch.identity;

  /// A step found itself no longer live. If it is still the operation that owns
  /// the state and the account is still the one it began for (a credential
  /// change with the same member), nothing else will start over, so the flow
  /// does. Anything else already started over, or moved on to a newer press (a
  /// discard, a sign-out and back in as the same member): the state is that
  /// one's, and a late step leaves it alone.
  void _abandon(_Launch launch) {
    if (!ref.mounted || launch.epoch != _epoch) return;
    if (ref.read(accountProvider)?.id != launch.owner) return;
    _epoch++;
    _deleteOwned();
    state = const ProfilePhotoState();
  }

  /// Opens the camera or library, prepares what comes back, and uploads it.
  /// Returns true when the photo was saved.
  Future<bool> pick(ImageSource source) async {
    if (state.busy) return false;
    // Reserved before the first await: a second tap finds it taken, and only
    // this call writes and clears the pick's marker. What the press began
    // under is read here too.
    state = state.copyWith(picking: true);
    final launch = _launch();
    XFile? picked;
    try {
      picked = await ref
          .read(pickGuardProvider)
          .run(
            PickPurpose.profilePhoto,
            () => ref.read(profilePhotoPickerProvider)(source),
            // Asked last, just before the picker would open: a member who
            // signed out or pressed again while the marker was being written
            // never has a picker opened for them.
            proceed: () => _live(launch),
          );
    } on PickBlockedException catch (error) {
      if (_live(launch)) {
        _fail(
          error.uncertain
              ? ProfilePhotoFailure.pickUncertain
              : ProfilePhotoFailure.pickBlocked,
        );
      } else {
        _abandon(launch);
      }
      return false;
    } on PlatformException {
      if (_live(launch)) {
        _fail(ProfilePhotoFailure.pickFailed);
      } else {
        _abandon(launch);
      }
      return false;
    }
    if (!_live(launch)) {
      if (picked != null) await deleteQuietly(picked.path);
      _abandon(launch);
      return false;
    }
    state = state.copyWith(picking: false);
    if (picked == null) return false;
    final prepared = await _prepare(picked.path, launch);
    if (prepared == null) return false;
    return _upload(launch);
  }

  /// Sends the prepared photo again (it failed before). Returns true when the
  /// server saved it. It goes only for the account and credentials the photo was
  /// prepared under: if either has changed it is not sent at all.
  Future<bool> upload() {
    final photo = state.picked;
    if (photo == null || state.busy) return Future.value(false);
    return _upload(_launchFor(photo));
  }

  Future<bool> _upload(_Launch launch) async {
    final photo = state.picked;
    if (photo == null || state.busy) return false;
    if (!_live(launch)) {
      await _release(photo.path);
      _abandon(launch);
      return false;
    }
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
            expectedIdentity: launch.identity,
            onProgress: (sent, total) {
              if (_live(launch) && total > 0) {
                state = state.copyWith(progress: sent / total);
              }
            },
          );
    } on ApiException catch (error) {
      _uploadingPath = null;
      if (!_live(launch)) {
        await _release(photo.path);
        _abandon(launch);
        return false;
      }
      final failure = ProfilePhotoFailure.of(error);
      if (!failure.canRetry) {
        // A file the server will never accept is not kept, and neither is
        // one a banned account cannot send.
        await _drop(photo);
        if (_live(launch)) {
          _fail(failure);
        } else {
          _abandon(launch);
        }
      } else if (!await File(photo.path).exists()) {
        // The phone cleared the file between the pick and the stream: a
        // retry could only fail the same way.
        await _drop(photo);
        if (_live(launch)) {
          _fail(ProfilePhotoFailure.unreadable);
        } else {
          _abandon(launch);
        }
      } else if (_live(launch)) {
        state = state.copyWith(
          phase: ProfilePhotoPhase.failed,
          failure: failure,
        );
      } else {
        await _release(photo.path);
        _abandon(launch);
      }
      return false;
    } on FileSystemException {
      // The phone cleared the file between the pick and the upload.
      _uploadingPath = null;
      if (!_live(launch)) {
        await _release(photo.path);
        _abandon(launch);
        return false;
      }
      await _drop(photo);
      if (_live(launch)) {
        _fail(ProfilePhotoFailure.unreadable);
      } else {
        _abandon(launch);
      }
      return false;
    }
    _uploadingPath = null;
    if (!_live(launch)) {
      await _release(photo.path);
      _abandon(launch);
      return false;
    }
    await _drop(photo);
    if (!_live(launch)) {
      _abandon(launch);
      return false;
    }
    state = const ProfilePhotoState();
    _refreshOwnPhotoReads();
    return true;
  }

  /// The member gave up on the photo that is waiting.
  Future<void> discard() async {
    _epoch++;
    final photo = state.picked;
    if (!ref.mounted) return;
    // The photo is detached at once and its file goes on its own time: a press
    // made while it is being deleted starts from clean state and keeps it.
    state = const ProfilePhotoState();
    if (photo != null) await _release(photo.path);
  }

  /// Removes the photo, or dismisses the notice that Wassla removed it.
  /// Returns the server's refusal, or null when it worked.
  Future<ApiException?> remove() async {
    if (state.busy) return null;
    final launch = _launch();
    state = state.copyWith(removing: true);
    try {
      await ref.read(sessionProvider.notifier).removePhoto();
    } on ApiException catch (error) {
      if (_live(launch)) state = state.copyWith(removing: false);
      return error;
    }
    if (!_live(launch)) {
      _abandon(launch);
      return null;
    }
    // Whatever went wrong with an earlier replacement is obsolete now.
    final pending = state.picked;
    if (pending != null) await _drop(pending);
    if (!_live(launch)) {
      _abandon(launch);
      return null;
    }
    state = const ProfilePhotoState();
    _refreshOwnPhotoReads();
    return null;
  }

  /// Prepares [sourcePath] and keeps the result as the pending photo; a pick
  /// it replaces has its file deleted. Every wait on the file system is
  /// followed by a check that [launch] is still live, before anything is
  /// written.
  Future<PickedPhoto?> _prepare(String sourcePath, _Launch launch) async {
    state = state.copyWith(
      phase: ProfilePhotoPhase.uploading,
      clearFailure: true,
      progress: 0,
    );
    String? output;
    try {
      output = await ref.read(profilePhotoPreparerProvider)(sourcePath);
      _owned.add(output);
      if (!await _stillLive(launch, output)) return null;
      final type = sniffImageType(await readHead(output));
      if (!await _stillLive(launch, output)) return null;
      // The platform answered with something that is not an image: it did not
      // do its job, which is no verdict on the picture.
      if (type == null) throw const PhotoPrepareFailed();
      final length = await File(output).length();
      if (!await _stillLive(launch, output)) return null;
      if (length > _maxPhotoBytes) {
        await _release(output);
        if (_live(launch)) {
          _fail(ProfilePhotoFailure.tooLarge);
        } else {
          _abandon(launch);
        }
        return null;
      }
      final photo = PickedPhoto(
        path: output,
        contentType: type,
        fileName: 'photo.${extensionFor(type)}',
        owner: launch.owner,
        identity: launch.identity,
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
      _failPrepare(launch, ProfilePhotoFailure.unreadable);
    } on UnsupportedPhoto {
      if (output != null) await _release(output);
      _failPrepare(launch, ProfilePhotoFailure.unsupported);
    } on PhotoPrepareFailed {
      if (output != null) await _release(output);
      _failPrepare(launch, ProfilePhotoFailure.prepareFailed);
    }
    return null;
  }

  /// After a wait in [_prepare]: true while [launch] is live. Otherwise the
  /// prepared file at [output] goes, the flow starts over if nothing else will,
  /// and false is answered.
  Future<bool> _stillLive(_Launch launch, String output) async {
    if (_live(launch)) return true;
    await _release(output);
    _abandon(launch);
    return false;
  }

  void _failPrepare(_Launch launch, ProfilePhotoFailure failure) {
    if (_live(launch)) {
      _fail(failure);
    } else {
      _abandon(launch);
    }
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
