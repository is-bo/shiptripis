/// Tolerant JSON readers shared by every model.
///
/// Two rules, both non-negotiable for this client:
///
/// 1. **An unknown value never crashes a screen.** The backend can add a deal
///    status, a dispute category or a notification channel at any time. A
///    model that threw on an unrecognised string would take out the whole
///    Deliveries tab for a user whose one in-flight deal happens to be in the
///    new state. Every enum here parses to an explicit `unknown` member and
///    the UI renders it as a neutral, honest "we don't recognise this state"
///    rather than pretending it is something else.
///
/// 2. **A type surprise never crashes a screen either.** The API is not
///    uniform: some money is an int, some a decimal string; some timestamps
///    end in `Z`, some in `+00:00`. These readers accept what actually
///    arrives and return null when they genuinely cannot.
///
/// What they deliberately do *not* do is invent values. A missing amount reads
/// as null and the UI omits the row; it never reads as zero, which would be a
/// lie about money.
library;

/// Reads an int from an int, a whole-valued num, or a numeric string.
int? readInt(Object? raw) => switch (raw) {
  final int v => v,
  final num v when v == v.roundToDouble() => v.toInt(),
  final String v => int.tryParse(v.trim()),
  _ => null,
};

double? readDouble(Object? raw) => switch (raw) {
  final num v => v.toDouble(),
  final String v => double.tryParse(v.trim()),
  _ => null,
};

String? readString(Object? raw) {
  if (raw is String) return raw;
  if (raw == null) return null;
  // A number used as an identifier is common enough to accept; anything
  // structural (a map, a list) is not a string and pretending otherwise would
  // put `{a: 1}` on screen.
  if (raw is num || raw is bool) return '$raw';
  return null;
}

/// Non-null string, empty when absent. For labels that must render something.
String readText(Object? raw) => readString(raw) ?? '';

bool readBool(Object? raw, {bool fallback = false}) => switch (raw) {
  final bool v => v,
  'true' || 'True' || 1 => true,
  'false' || 'False' || 0 => false,
  _ => fallback,
};

/// Parses an ISO-8601 instant and returns it in **local** time.
///
/// The API emits both `2026-08-26T12:00:00Z` and `2026-08-26T12:00:00+00:00`
/// for the same field depending on whether it came through a serializer or
/// through an error envelope's `details()`. `DateTime.tryParse` handles both.
///
/// Converting to local here — once — is what keeps every countdown and
/// deadline in the app on the user's own clock without each screen
/// remembering to call `.toLocal()`.
DateTime? readDate(Object? raw) {
  final text = readString(raw);
  if (text == null || text.isEmpty) return null;
  return DateTime.tryParse(text)?.toLocal();
}

/// A list of objects, skipping any element that is not a JSON object.
///
/// One malformed row in a list of forty should cost the user that row, not
/// the screen.
List<Map<String, dynamic>> readObjectList(Object? raw) {
  if (raw is! List) return const [];
  return raw
      .whereType<Map>()
      .map(Map<String, dynamic>.from)
      .toList(growable: false);
}

List<String> readStringList(Object? raw) {
  if (raw is! List) return const [];
  return raw.map(readString).whereType<String>().toList(growable: false);
}

List<int> readIntList(Object? raw) {
  if (raw is! List) return const [];
  return raw.map(readInt).whereType<int>().toList(growable: false);
}

/// A nested object, or null when the key is absent or holds something else.
Map<String, dynamic>? readObject(Object? raw) {
  if (raw is Map<String, dynamic>) return raw;
  if (raw is Map) return Map<String, dynamic>.from(raw);
  return null;
}

/// Maps a wire string onto an enum by name, falling back to [fallback].
///
/// Used by every domain enum so the fallback behaviour is written once and
/// cannot be forgotten in a new model.
T readEnum<T extends Enum>(
  Object? raw,
  List<T> values, {
  required T fallback,
  Map<String, T> aliases = const {},
}) {
  final text = readString(raw)?.trim();
  if (text == null || text.isEmpty) return fallback;

  final alias = aliases[text];
  if (alias != null) return alias;

  // Wire values are snake_case; Dart members are lowerCamelCase.
  final normalised = text.toLowerCase().replaceAll(RegExp('[_-]'), '');
  for (final value in values) {
    if (value.name.toLowerCase() == normalised) return value;
  }
  return fallback;
}
