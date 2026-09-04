library;

import 'json.dart';

class PushPreferences {
  const PushPreferences({
    required this.essentialEnabled,
    required this.messagesEnabled,
    required this.marketplaceEnabled,
  });

  factory PushPreferences.fromJson(Map<String, dynamic> json) =>
      PushPreferences(
        essentialEnabled: readBool(json['essential_enabled'], fallback: true),
        messagesEnabled: readBool(json['messages_enabled'], fallback: true),
        marketplaceEnabled: readBool(
          json['marketplace_enabled'],
          fallback: true,
        ),
      );

  final bool essentialEnabled;
  final bool messagesEnabled;
  final bool marketplaceEnabled;
}
