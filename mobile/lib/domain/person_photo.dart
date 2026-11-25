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
///
/// An active photo is kept whether or not the server could sign its address:
/// the member still has a photo, and may change or remove it, even when no
/// picture can be drawn for the moment ([photo] is then null).
class OwnPhoto {
  const OwnPhoto.active({required String this.version, this.url})
    : state = OwnPhotoState.active,
      removedAt = null,
      reason = null;

  const OwnPhoto.removed({this.removedAt, this.reason})
    : state = OwnPhotoState.removed,
      version = null,
      url = null;

  /// Null for no photo, and for a state this build does not know.
  static OwnPhoto? maybe(Object? raw) {
    final json = readObject(raw);
    return switch (OwnPhotoState.maybe(json?['state'])) {
      OwnPhotoState.active => switch (readString(json?['version'])) {
        final version? when version.isNotEmpty => OwnPhoto.active(
          version: version,
          url: readString(json?['url']),
        ),
        _ => null,
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

  /// The active photo's version, whether or not it has an address.
  final String? version;

  /// Null while the photo is active but the server could not sign it.
  final String? url;
  final DateTime? removedAt;

  /// What Wassla told the member when it removed the photo.
  final String? reason;

  bool get isRemoved => state == OwnPhotoState.removed;
  bool get isActive => state == OwnPhotoState.active;

  /// What the avatar can draw: null when there is no address to draw from.
  PersonPhoto? get photo {
    final address = url;
    final key = version;
    if (!isActive || address == null || address.isEmpty || key == null) {
      return null;
    }
    return PersonPhoto(url: address, version: key);
  }
}
