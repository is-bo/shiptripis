/// Who a picked photo belongs to when the phone ends the app mid-pick.
///
/// On Android the camera or library runs in another activity, and the phone can
/// end this app while it is open. The picker keeps **one** "lost" result for
/// every kind of pick, so a photo recovered at the next launch could be the
/// identity-check selfie, a ticket, a cheque or a dispute photo, not the
/// profile photo the member was choosing. Offering that as a public photo would
/// publish a private image.
///
/// So every pick, wherever the app opens a picker, goes through [PickGuard]:
///
/// * **before** the picker opens, any earlier lost result is consumed and
///   thrown away, and a marker (the purpose, the account and a nonce) is
///   written to secure storage;
/// * **after** the picker answers, the pick that wrote the marker clears it,
///   and nobody else does;
/// * at the next launch, the profile photo accepts a lost result only when the
///   marker names the profile photo and the same signed-in account. A result
///   whose marker names anything else is consumed and discarded.
library;

import 'dart:math';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../session/session.dart';

/// Why a picker is being opened. The profile photo is the only purpose whose
/// lost result is ever used; the others are listed so that theirs is never
/// mistaken for it.
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

/// One pick in progress: the marker it wrote.
class PickTicket {
  const PickTicket(this.marker);

  final String marker;
}

class PickGuard {
  PickGuard(this._ref);

  final Ref _ref;

  static final _random = Random.secure();

  String get _account => '${_ref.read(accountProvider)?.id ?? 'none'}';

  /// Opens the way for a pick: throws away a lost result an earlier pick left
  /// (of any purpose), then writes this pick's marker.
  Future<PickTicket> begin(PickPurpose purpose) async {
    await _consumeLost();
    final marker =
        '${purpose.name}:$_account:${_random.nextInt(1 << 32).toRadixString(36)}';
    await _tryStorage(
      () => _ref.read(tokenStoreProvider).writePendingPick(marker),
    );
    return PickTicket(marker);
  }

  /// The pick answered (or failed): clears its marker, if it is still this
  /// pick's.
  Future<void> end(PickTicket ticket) => _clearIfStill(ticket.marker);

  /// Clears the marker only while it is still [marker]: a pick that began
  /// since owns the new one, and an earlier pick's cleanup must not take it.
  Future<void> _clearIfStill(String marker) async {
    final tokens = _ref.read(tokenStoreProvider);
    final current = await _tryStorage(tokens.readPendingPick);
    if (current == marker) {
      await _tryStorage(() => tokens.writePendingPick(null));
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

  /// The photo a previous run lost while choosing a **[purpose]** for the
  /// signed-in account, or null. The lost result is consumed either way, so it
  /// is never offered twice and never to another purpose or account.
  Future<XFile?> recoverLost(PickPurpose purpose) async {
    final tokens = _ref.read(tokenStoreProvider);
    final marker = await _tryStorage(tokens.readPendingPick);
    if (marker == null) return null;
    await _clearIfStill(marker);
    final lost = await _consumeLost();
    final parts = marker.split(':');
    final mine =
        parts.length >= 2 &&
        parts[0] == purpose.name &&
        parts[1] == _account &&
        _account != 'none';
    return mine ? lost : null;
  }

  /// Reads and so clears the picker's lost result.
  Future<XFile?> _consumeLost() async {
    try {
      final lost = await _ref.read(imagePickerProvider).retrieveLostData();
      if (lost.isEmpty) return null;
      return lost.file ?? lost.files?.firstOrNull;
    } on Object {
      // No plugin (iOS, a test) or a refusal: nothing was lost that can be read.
      return null;
    }
  }

  Future<T?> _tryStorage<T>(Future<T> Function() step) async {
    try {
      return await step();
    } on Object {
      // Secure storage failing must not stop a photo being picked.
      return null;
    }
  }
}
