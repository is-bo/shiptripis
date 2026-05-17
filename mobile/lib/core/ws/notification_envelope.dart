/// Wire format mirroring `backend/services/pkg/wsproto/Envelope`.
///
/// Server→client always carries `eventId` + `ts` (used for delivery
/// receipts on the Go side). `payload` is opaque JSON keyed off `type`.
library;

class NotificationEnvelope {
  const NotificationEnvelope({
    required this.type,
    this.eventId,
    this.ts,
    this.payload,
  });

  /// e.g. `offer.accepted`, `match.created`. Drives UI rendering.
  final String type;

  final String? eventId;
  final String? ts;
  final Map<String, dynamic>? payload;

  factory NotificationEnvelope.fromJson(Map<String, dynamic> json) {
    final p = json['payload'];
    return NotificationEnvelope(
      type: json['type'] as String,
      eventId: json['event_id'] as String?,
      ts: json['ts'] as String?,
      payload: p is Map<String, dynamic> ? p : null,
    );
  }
}
