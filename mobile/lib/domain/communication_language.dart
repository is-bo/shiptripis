/// The language ShipTrip writes to somebody in.
///
/// This is **not** the app's interface language. It is the durable preference
/// the backend snapshots onto every transactional message it owes — security
/// and account mail, payment and refund receipts, KYC and flight-proof
/// decisions, dispute and cancellation notices, payout notices, and the
/// recipient's delivery-code email.
///
/// Two rules from the server contract, mirrored here so the client cannot
/// disagree with it:
///
/// * the enum is exactly `en`, `fr`, `ar` — the server's serializers reject
///   anything else, so the app must never offer a fourth value or send a
///   region-tagged code such as `fr-DZ`; and
/// * a blank or unrecognised stored value resolves to **English**, matching
///   `apps.core.languages.normalize_communication_language`. Historical rows
///   predate the preference and carry no user intent; inventing one on the
///   client would be worse than the server's own deterministic fallback.
///
/// Nothing here is ever inferred from a name, an email address, a domain, a
/// nationality, or a city. The only inputs are what the server stored and what
/// the user explicitly chose.
library;

/// A language the platform can write in.
enum CommunicationLanguage {
  english('en'),
  french('fr'),
  arabic('ar');

  const CommunicationLanguage(this.wire);

  /// The exact value the API accepts and returns.
  final String wire;

  /// The server's fallback for a blank or unknown value.
  static const fallback = CommunicationLanguage.english;

  /// Parses a wire value the way the backend normalises it.
  ///
  /// Accepts a missing key, an empty string, whitespace, mixed case, and a
  /// region tag (`ar-DZ`), because a legacy row or a proxy that lower-cases
  /// nothing must not leave the selector in an impossible state. Anything it
  /// cannot recognise reads as [fallback], never as null.
  static CommunicationLanguage parse(Object? raw) {
    if (raw is! String) return fallback;
    final normalised = raw.trim().toLowerCase().split(RegExp('[-_]')).first;
    for (final value in values) {
      if (value.wire == normalised) return value;
    }
    return fallback;
  }

  /// Parses only when the server actually said something.
  ///
  /// Returns null when the key is absent — which on the recipient projection
  /// means "this viewer was not given the field", not "English". A caller that
  /// wants a value regardless uses [parse].
  static CommunicationLanguage? maybe(Object? raw) {
    if (raw == null) return null;
    if (raw is String && raw.trim().isEmpty) return fallback;
    return parse(raw);
  }

  /// Matches the app's locale to a communication language.
  ///
  /// Used once, at account creation, so a new account's first email is not in
  /// a language the person did not pick. It is never used to overwrite a
  /// stored preference afterwards.
  static CommunicationLanguage forLanguageCode(String code) => parse(code);

  /// The option's name in its own language.
  ///
  /// Deliberately not translated. Somebody choosing which language to be
  /// written in has to be able to recognise their own on the list, and
  /// "Arabic" rendered in French helps nobody who reads only Arabic.
  String get nativeLabel => switch (this) {
    CommunicationLanguage.english => 'English',
    CommunicationLanguage.french => 'Français',
    CommunicationLanguage.arabic => 'العربية',
  };

  /// True when the label itself has to be laid out right-to-left.
  ///
  /// Scoped to the label. Choosing Arabic mail does **not** turn the app
  /// right-to-left; only the app-language setting does that.
  bool get isRtlLabel => this == CommunicationLanguage.arabic;
}
