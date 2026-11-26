/// Keeping one kind of pick from answering another.
///
/// On Android the camera or library runs in another activity, and the phone can
/// end this app while it is open. The picker keeps **one** "lost" result for
/// every kind of pick, and a copy of the chosen file that is still being made
/// when the app comes back can answer the callback of the **next** pick, of
/// whatever kind. A photo that answered the profile photo's pick could then be
/// the identity-check selfie, a ticket, a cheque or a dispute photo, and
/// offering it as a public photo would publish a private image.
///
/// The plugin gives no way to bind a result to the pick that asked for it, so
/// the app never uses a lost result at all, and the profile photo refuses any
/// result it cannot prove came from its own launch:
///
/// * **before** a picker opens, the pick makes itself the pending pick in
///   secure storage (a marker: the purpose and a nonce), in one serialized step
///   that also answers the marker it replaced. If storage refuses, the picker
///   does not open ([PickBlockedException]): a pick with no durable owner is
///   not allowed;
/// * any earlier lost result is consumed and its file deleted, and if there was
///   one, or the replaced marker was not empty (an earlier pick never ended: the
///   phone ended the app, or a sign-out came between), the pick is **tainted**
///   and a result may still be on its way for a pick that is gone: the next
///   [suspectWindow] is suspect too;
/// * the profile photo asks [PickGuard.trusts] when its picker answers, and a
///   result that arrives tainted or inside the window is deleted and refused;
/// * after the picker answers the pick clears its own marker, and nobody
///   else's, in the same serialized queue as the credentials and the sign-out.
library;

import 'dart:math';

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

final pickGuardProvider = Provider<PickGuard>((ref) => PickGuard(ref));

/// The pick could not be given an owner in secure storage, so no picker was
/// opened.
class PickBlockedException implements Exception {
  const PickBlockedException();

  @override
  String toString() => 'PickBlockedException';
}

/// One pick in progress: the marker it wrote, and whether an earlier pick may
/// still answer it.
class PickTicket {
  const PickTicket(this.marker, {this.tainted = false});

  final String marker;
  final bool tainted;
}

class PickGuard {
  PickGuard(this._ref, {DateTime Function()? now}) : _now = now ?? DateTime.now;

  final Ref _ref;
  final DateTime Function() _now;

  static final _random = Random.secure();

  /// How long after a stale marker or a lost result was found a result is still
  /// not trusted for the profile photo. A copy that outlived its app finishes
  /// within seconds of the next launch; a member who chooses again after the
  /// refusal is let through when the window has passed.
  static const suspectWindow = Duration(seconds: 30);

  DateTime? _suspectUntil;

  /// Opens the way for a pick: makes it the pending pick (throwing
  /// [PickBlockedException] when storage cannot be changed, or the sign-in
  /// moved meanwhile), then throws away a lost result an earlier pick left.
  Future<PickTicket> begin(PickPurpose purpose) async {
    final tokens = _ref.read(tokenStoreProvider);
    final marker =
        '${purpose.name}:${_random.nextInt(1 << 32).toRadixString(36)}';
    final ({bool applied, String? previous}) exchange;
    try {
      exchange = await tokens.exchangePendingPick(
        marker,
        expectedIdentityGeneration: tokens.identityGeneration,
      );
    } on Object {
      throw const PickBlockedException();
    }
    if (!exchange.applied) throw const PickBlockedException();
    final lost = await _consumeLost();
    final lostPath = lost.path;
    if (lostPath != null) await deleteQuietly(lostPath);
    final tainted = exchange.previous != null || lost.found;
    if (tainted) _suspectUntil = _now().add(suspectWindow);
    return PickTicket(marker, tainted: tainted);
  }

  /// Whether a result that arrives for [ticket] can be believed to answer this
  /// pick: no earlier pick may still answer it, and no stale pick was found
  /// within the last [suspectWindow].
  bool trusts(PickTicket ticket) {
    if (ticket.tainted) return false;
    final until = _suspectUntil;
    return until == null || !_now().isBefore(until);
  }

  /// The pick answered (or failed): clears its marker, if it is still this
  /// pick's. A refusal of storage leaves the marker, which only makes the next
  /// pick careful.
  Future<void> end(PickTicket ticket) async {
    try {
      await _ref.read(tokenStoreProvider).releasePendingPick(ticket.marker);
    } on Object {
      // The next pick finds the marker and treats itself as tainted.
    }
  }

  /// A pick for [purpose]: [begin], the picker, [end].
  Future<XFile?> pickImage(
    PickPurpose purpose, {
    required ImageSource source,
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
  }) async {
    final ticket = await begin(purpose);
    try {
      return await _ref
          .read(imagePickerProvider)
          .pickImage(
            source: source,
            maxWidth: maxWidth,
            maxHeight: maxHeight,
            imageQuality: imageQuality,
            preferredCameraDevice: preferredCameraDevice,
          );
    } finally {
      await end(ticket);
    }
  }

  Future<XFile?> pickVideo(
    PickPurpose purpose, {
    required ImageSource source,
  }) async {
    final ticket = await begin(purpose);
    try {
      return await _ref.read(imagePickerProvider).pickVideo(source: source);
    } finally {
      await end(ticket);
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
