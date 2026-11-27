/// A stand-in for the one `ImagePicker` of the app.
///
/// A test runner has no camera and no Android "lost result" store. This keeps
/// the part of that store that matters here: **one** lost result for every kind
/// of pick, which stays until something reads it (as the real picker's does),
/// and survives a "restart" because a test hands the same fake to the next
/// container.
library;

import 'package:image_picker/image_picker.dart';

class FakeImagePicker extends ImagePicker {
  FakeImagePicker({this.onPick, this.lost});

  /// What a pick answers (null: the member closed the picker).
  Future<XFile?> Function(ImageSource source)? onPick;

  /// The result the phone kept when it ended the app: read once, then gone.
  XFile? lost;

  /// Every source a picker was opened for, in order.
  final picks = <ImageSource>[];

  /// How many times the lost result was read.
  int lostReads = 0;

  @override
  Future<XFile?> pickImage({
    required ImageSource source,
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
    bool requestFullMetadata = true,
  }) async {
    picks.add(source);
    return onPick?.call(source);
  }

  @override
  Future<XFile?> pickVideo({
    required ImageSource source,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
    Duration? maxDuration,
  }) async {
    picks.add(source);
    return onPick?.call(source);
  }

  @override
  Future<LostDataResponse> retrieveLostData() async {
    lostReads++;
    final result = lost;
    lost = null;
    return result == null
        ? LostDataResponse.empty()
        : LostDataResponse(file: result);
  }
}
