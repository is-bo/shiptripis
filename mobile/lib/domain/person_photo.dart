/// A member's profile photo, as the server publishes it (spec 21).
///
/// Two shapes, because two people read it. Everyone who sees a person by first
/// name gets [PersonPhoto]: a short-lived signed address and an opaque version.
/// Only the owner gets [OwnPhoto], which also says when Wassla removed the
/// photo and why.
///
/// The address expires in 30 minutes and the image does not: the app caches
/// the picture by [PersonPhoto.version], so a fresh address on a refreshed
/// payload never re-downloads a photo it already holds.
library;

import 'json.dart';

/// A photo anyone may see, on a card, a person page, a proposal or a chat row.
class PersonPhoto {
  const PersonPhoto({required this.url, required this.version});

  /// Null for no photo, and for a block missing either key, so one malformed
  /// block costs one picture and never a card.
  static PersonPhoto? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final url = readString(json['url']);
    final version = readString(json['version']);
    if (url == null || url.isEmpty || version == null || version.isEmpty) {
      return null;
    }
    return PersonPhoto(url: url, version: version);
  }

  /// Signed, and valid for 30 minutes.
  final String url;

  /// Changes with every upload. The image cache key.
  final String version;
}

enum OwnPhotoState {
  active,
  removed;

  static OwnPhotoState? maybe(Object? raw) => switch (readString(raw)) {
    'active' => active,
    'removed' => removed,
    _ => null,
  };
}

/// The member's own photo, from `GET /api/me` and `PUT /api/me/photo`.
class OwnPhoto {
  const OwnPhoto.active(PersonPhoto this.photo)
    : state = OwnPhotoState.active,
      removedAt = null,
      reason = null;

  const OwnPhoto.removed({this.removedAt, this.reason})
    : state = OwnPhotoState.removed,
      photo = null;

  /// Null for no photo, and for a state this build does not know.
  static OwnPhoto? maybe(Object? raw) {
    final json = readObject(raw);
    return switch (OwnPhotoState.maybe(json?['state'])) {
      OwnPhotoState.active => switch (PersonPhoto.maybe(json)) {
        final photo? => OwnPhoto.active(photo),
        null => null,
      },
      OwnPhotoState.removed => OwnPhoto.removed(
        removedAt: readDate(json?['removed_at']),
        // May be empty: render the generic notice then, never a blank line.
        reason: readString(json?['reason']),
      ),
      null => null,
    };
  }

  final OwnPhotoState state;

  /// Set while the photo is active.
  final PersonPhoto? photo;
  final DateTime? removedAt;

  /// What Wassla told the member when it removed the photo.
  final String? reason;

  bool get isRemoved => state == OwnPhotoState.removed;
}
