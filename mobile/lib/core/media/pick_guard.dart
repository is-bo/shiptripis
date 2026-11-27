/// Keeping one kind of pick from answering another.
///
/// On Android the camera or library runs in another activity, and the phone can
/// end this app while it is open. The picker keeps **one** "lost" result for
/// every kind of pick, and a copy of the chosen file that is still being made
/// when the app comes back can answer the callback of the **next** pick, of
/// whatever kind. A photo that answered the profile photo's pick could then be
/// the identity-check selfie, a ticket, a cheque or a dispute photo, and
/// offering it as a public photo would publish a private image, just as an
/// identity document answering a parcel photo would be staged as the item.
///
/// The plugin gives no way to bind a result to the pick that asked for it, so
/// the app never uses a lost result at all, and **every** picker of the app goes
/// through [PickGuard.pickImage] or [PickGuard.pickVideo] (the profile photo
/// through [PickGuard.run]), which refuse any result they cannot prove came from
/// their own launch:
///
/// * **one pick at a time, for every purpose.** The guard is reserved before its
///   first wait, so a second tap, of the same or another screen, finds the
///   picker taken and does nothing: it never touches the marker, and so can
///   never end the owner of the picker that is open;
/// * **before** a picker opens, the pick makes itself the pending pick in
///   durable storage (a marker: the purpose and a nonce), in one serialized step
///   that also answers the marker it replaced. If storage refuses, or the
///   sign-in moved meanwhile, the picker does not open ([PickBlockedException]):
///   a pick with no durable owner is not allowed;
/// * any earlier lost result is consumed and its file deleted, and if there was
///   one, or the replaced marker was not empty (an earlier pick never ended: the
///   phone ended the app, or a sign-out came between), the pick is **tainted**
///   and a result may still be on its way for a pick that is gone: the next
///   [suspectWindow] is suspect too;
/// * a result that arrives tainted or inside the window is deleted and refused
///   ([PickBlockedException.uncertain]) **before it is returned to anyone**, so
///   no screen can stage, show or send it;
/// * after the picker answers the pick clears its own marker, and nobody
///   else's, in the same serialized queue as the credentials and the sign-out.
library;

import 'dart:io' show Platform;
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../session/session.dart';
import 'photo_prepare.dart' show deleteQuietly;

/// Why a picker is being opened. Each purpose's results stay with its own
/// screen: none is ever recovered by another.
enum PickPurpose {
  profilePhoto,
  identityDocument,
  ticketProof,
  itemPhoto,
  payoutCheque,
  disputeEvidence,
}

/// The one `ImagePicker` of the app, as a provider: the seam a test replaces
/// (a test runner has no camera and no lost-result store).
final imagePickerProvider = Provider<ImagePicker>((ref) => ImagePicker());

final pickGuardProvider = Provider<PickGuard>(
  (ref) => PickGuard(ref, nativeLaunchGate: Platform.isAndroid),
);

/// A pick was not allowed to go on, and why.
///
/// * **Not [uncertain]:** the pick could not be given an owner in durable
///   storage, or the sign-in moved while it was being given one, so no picker
///   was opened.
/// * **[uncertain]:** the picker answered, but not provably for this pick (an
///   earlier pick may have been the one that answered). The file was deleted and
///   is not returned: the member picks again.
class PickBlockedException implements Exception {
  const PickBlockedException({this.uncertain = false});

  final bool uncertain;

  @override
  String toString() => 'PickBlockedException(uncertain: $uncertain)';
}

/// One pick in progress: the marker it wrote, and whether an earlier pick may
/// still answer it.
class _Ticket {
  const _Ticket(this.marker, {required this.tainted});

  final String marker;
  final bool tainted;
}

class PickGuard {
  PickGuard(
    this._ref, {
    DateTime Function()? now,
    bool nativeLaunchGate = false,
  }) : _now = now ?? DateTime.now,
       _nativeLaunchGate = nativeLaunchGate;

  final Ref _ref;
  final DateTime Function() _now;

  /// Whether the platform has the launch gate of `wassla/pick_launch` (Android:
  /// see [_announce]).
  final bool _nativeLaunchGate;

  static final _random = Random.secure();

  static const _launchChannel = MethodChannel('wassla/pick_launch');

  /// How long after a stale marker or a lost result was found a result is still
  /// not trusted. A copy that outlived its app finishes within seconds of the
  /// next launch; a member who chooses again after the refusal is let through
  /// when the window has passed.
  static const suspectWindow = Duration(seconds: 30);

  DateTime? _suspectUntil;

  /// True from the first line of a pick to the end of its marker's release: the
  /// one pick of the app that may have a picker open.
  bool _taken = false;

  /// Whether a pick is in progress.
  bool get busy => _taken;

  /// One pick: reserves the guard, gives the pick its marker, calls [open] (the
  /// call that shows the picker) and clears the marker when it answers.
  ///
  /// Answers null when the member picked nothing, **and** when the pick did not
  /// go on without being a failure: another pick is in progress (it keeps the
  /// guard, and its marker is not touched), the sign-in changed while the pick
  /// was being prepared, or [proceed] said the caller no longer wants it. [open]
  /// is asked only after all of those are checked once more, so a picker never
  /// opens for a member who has gone.
  ///
  /// Throws [PickBlockedException] when the pick has no durable owner (no
  /// picker was opened) and when the answer cannot be proven to be this pick's
  /// ([PickBlockedException.uncertain]; the file is deleted first). Whatever
  /// [open] throws is rethrown after the marker is cleared.
  Future<XFile?> run(
    PickPurpose purpose,
    Future<XFile?> Function() open, {
    bool Function()? proceed,
  }) async {
    if (_taken) return null;
    _taken = true;
    try {
      final tokens = _ref.read(tokenStoreProvider);
      final identity = tokens.identityGeneration;
      final ticket = await _begin(purpose, identity);
      XFile? picked;
      bool trusted = false;
      try {
        if (tokens.identityGeneration != identity) return null;
        if (proceed != null && !proceed()) return null;
        await _announce('opened');
        try {
          // Asked again: the announcement is a platform round trip, and a
          // sign-out, an expiry or a newer press may have come while it was
          // out. The picker never opens for a member who has gone, and the
          // `finally` below ends the announced launch.
          if (tokens.identityGeneration != identity) return null;
          if (proceed != null && !proceed()) return null;
          picked = await open();
          // Judged the moment the picker answers: a long wait for the marker's
          // release must not carry the suspect window past its end.
          trusted = _trusts(ticket);
        } finally {
          await _announce('closed', strict: false);
        }
      } finally {
        await _end(ticket);
      }
      if (picked == null) return null;
      if (tokens.identityGeneration != identity) {
        await deleteQuietly(picked.path);
        return null;
      }
      if (!trusted) {
        // It may be another pick's file (an identity document, a ticket): it is
        // never kept, shown or sent.
        await deleteQuietly(picked.path);
        throw const PickBlockedException(uncertain: true);
      }
      return picked;
    } finally {
      _taken = false;
    }
  }

  /// A pick of an image for [purpose] (see [run]).
  Future<XFile?> pickImage(
    PickPurpose purpose, {
    required ImageSource source,
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
  }) => run(
    purpose,
    () => _ref
        .read(imagePickerProvider)
        .pickImage(
          source: source,
          maxWidth: maxWidth,
          maxHeight: maxHeight,
          imageQuality: imageQuality,
          preferredCameraDevice: preferredCameraDevice,
        ),
  );

  /// A pick of a video for [purpose] (see [run]).
  Future<XFile?> pickVideo(
    PickPurpose purpose, {
    required ImageSource source,
  }) => run(
    purpose,
    () => _ref.read(imagePickerProvider).pickVideo(source: source),
  );

  /// Makes the pick the pending pick (throwing [PickBlockedException] when
  /// storage cannot be changed, or the sign-in moved meanwhile), then throws
  /// away a lost result an earlier pick left.
  Future<_Ticket> _begin(PickPurpose purpose, int identity) async {
    final marker =
        '${purpose.name}:${_random.nextInt(1 << 32).toRadixString(36)}';
    final ({bool applied, String? previous}) exchange;
    try {
      exchange = await _ref
          .read(tokenStoreProvider)
          .exchangePendingPick(marker, expectedIdentityGeneration: identity);
    } on Object {
      throw const PickBlockedException();
    }
    if (!exchange.applied) throw const PickBlockedException();
    final lost = await _consumeLost();
    final lostPath = lost.path;
    if (lostPath != null) await deleteQuietly(lostPath);
    final tainted = exchange.previous != null || lost.found;
    if (tainted) _suspectUntil = _now().add(suspectWindow);
    return _Ticket(marker, tainted: tainted);
  }

  /// Tells the Android side that this pick has opened its picker (or that it
  /// has answered), so a result the picker restores after the phone ended the
  /// app, with no pick of this run waiting for it, is dropped before the plugin
  /// copies it: a copy still being made cannot then answer a later pick. Only
  /// Android has the gate (the picker's other platforms keep no lost result for
  /// another process to answer), so elsewhere there is nothing to tell. A refusal of the
  /// opening ([strict]) stops the pick, because a launch the native side does
  /// not know would have its own answer dropped.
  Future<void> _announce(String event, {bool strict = true}) async {
    if (!_nativeLaunchGate) return;
    try {
      await _launchChannel.invokeMethod<void>(event);
    } on Object {
      // Android always has the handler (a missing one means this build has no
      // gate, and a result it restored would reach the plugin), so a refusal
      // of any kind stops the pick, never the ending of one.
      if (strict) throw const PickBlockedException();
    }
  }

  /// Whether a result that arrives for [ticket] can be believed to answer this
  /// pick: no earlier pick may still answer it, and no stale pick was found
  /// within the last [suspectWindow].
  bool _trusts(_Ticket ticket) {
    if (ticket.tainted) return false;
    final until = _suspectUntil;
    return until == null || !_now().isBefore(until);
  }

  /// The pick answered (or failed): clears its marker, if it is still this
  /// pick's. A refusal of storage leaves the marker, which only makes the next
  /// pick careful.
  Future<void> _end(_Ticket ticket) async {
    try {
      await _ref.read(tokenStoreProvider).releasePendingPick(ticket.marker);
    } on Object {
      // The next pick finds the marker and treats itself as tainted.
    }
  }

  /// Reads and so clears the picker's lost result: whether there was one, and
  /// where its file is.
  Future<({bool found, String? path})> _consumeLost() async {
    try {
      final lost = await _ref.read(imagePickerProvider).retrieveLostData();
      if (lost.isEmpty) return (found: false, path: null);
      return (found: true, path: (lost.file ?? lost.files?.firstOrNull)?.path);
    } on Object {
      // No plugin (iOS, a test) or a refusal: nothing was lost that can be read.
      return (found: false, path: null);
    }
  }
}
