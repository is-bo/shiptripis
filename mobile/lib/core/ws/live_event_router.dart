/// Translates incoming WS envelopes into provider invalidations and
/// keeps a small live-event store the UI can read directly (most
/// importantly the just-issued handover code so the sender's screen
/// shows it the moment Django publishes it).
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../matching/matching_providers.dart';
import '../parcels/parcels_providers.dart';
import '../trips/trips_providers.dart';
import 'notification_envelope.dart';
import 'notifications_providers.dart';

class LiveHandoverCode {
  const LiveHandoverCode({
    required this.matchId,
    required this.kind,
    required this.code,
    required this.issuedAt,
  });

  final int matchId;
  final String kind;
  final String code;
  final DateTime issuedAt;
}

class LiveEventState {
  const LiveEventState({
    this.codesByMatch = const {},
    this.matchTick = 0,
  });

  final Map<int, LiveHandoverCode> codesByMatch;

  /// Bumps on any match-list-affecting event. UI list screens that
  /// watch `liveEventProvider.select((s) => s.matchTick)` re-fetch
  /// when this changes.
  final int matchTick;

  LiveEventState withCode(LiveHandoverCode c) {
    final next = Map<int, LiveHandoverCode>.from(codesByMatch);
    next[c.matchId] = c;
    return LiveEventState(codesByMatch: next, matchTick: matchTick);
  }

  LiveEventState withMatchTick() {
    return LiveEventState(codesByMatch: codesByMatch, matchTick: matchTick + 1);
  }
}

class LiveEventNotifier extends Notifier<LiveEventState> {
  StreamSubscription<NotificationEnvelope>? _sub;

  @override
  LiveEventState build() {
    final client = ref.watch(notificationWsClientProvider);
    _sub?.cancel();
    _sub = client.events.listen(_onEnvelope);
    ref.onDispose(() {
      _sub?.cancel();
    });
    return const LiveEventState();
  }

  void _onEnvelope(NotificationEnvelope env) {
    final p = env.payload ?? const {};
    switch (env.type) {
      case 'handover.code_issued':
        final mid = (p['match_id'] as num?)?.toInt();
        final kind = p['kind'] as String?;
        final code = p['code'] as String?;
        if (mid != null && kind != null && code != null) {
          state = state.withCode(LiveHandoverCode(
            matchId: mid,
            kind: kind,
            code: code,
            issuedAt: DateTime.now(),
          ));
          ref.invalidate(matchDetailProvider(mid));
        }
        break;
      case 'offer.created':
      case 'offer.updated':
      case 'offer.accepted':
      case 'match.created':
      case 'match.in_transit':
      case 'match.completed':
        final mid = (p['match_id'] as num?)?.toInt();
        if (mid != null) {
          ref.invalidate(matchDetailProvider(mid));
          ref.invalidate(offerListProvider(mid));
        }
        state = state.withMatchTick();
        break;
      case 'payment.captured':
      case 'payment.refunded':
        final mid = (p['match_id'] as num?)?.toInt();
        if (mid != null) {
          ref.invalidate(matchDetailProvider(mid));
        }
        state = state.withMatchTick();
        break;
      case 'parcel.created':
      case 'parcel.cancelled':
        ref.invalidate(myParcelsProvider);
        break;
      case 'trip.created':
      case 'trip.cancelled':
        ref.invalidate(myTripsProvider);
        break;
    }
  }
}

final liveEventProvider =
    NotifierProvider<LiveEventNotifier, LiveEventState>(LiveEventNotifier.new);

/// Convenience: latest live code for a given match (PICKUP > DELIVERY
/// is the natural order since DELIVERY arrives later and overwrites in
/// the map).
LiveHandoverCode? liveCodeFor(WidgetRef ref, int matchId) {
  return ref.watch(liveEventProvider).codesByMatch[matchId];
}
