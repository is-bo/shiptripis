/// Translates incoming WS envelopes into provider invalidations and
/// keeps a small live-event store the UI can read directly (most
/// importantly the just-issued handover code so the sender's screen
/// shows it the moment Django publishes it).
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
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

/// A toast-style notice the shell renders at the top of the app. Each one
/// carries optional deep-link metadata so taps land on the right screen.
class LiveBanner {
  const LiveBanner({
    required this.id,
    required this.title,
    required this.body,
    this.deepLink,
    this.tone = LiveBannerTone.info,
  });

  final int id;
  final String title;
  final String body;
  final String? deepLink;
  final LiveBannerTone tone;
}

enum LiveBannerTone { info, success, warning }

class LiveEventState {
  const LiveEventState({
    this.codesByMatch = const {},
    this.matchTick = 0,
    this.banners = const [],
    this.nextBannerId = 1,
  });

  final Map<int, LiveHandoverCode> codesByMatch;

  /// Bumps on any match-list-affecting event. UI list screens that
  /// watch `liveEventProvider.select((s) => s.matchTick)` re-fetch
  /// when this changes.
  final int matchTick;

  /// Active actionable notifications. Newest first. Shell pops them on tap
  /// or auto-dismiss.
  final List<LiveBanner> banners;

  final int nextBannerId;

  LiveEventState withCode(LiveHandoverCode c) {
    final next = Map<int, LiveHandoverCode>.from(codesByMatch);
    next[c.matchId] = c;
    return LiveEventState(
      codesByMatch: next,
      matchTick: matchTick,
      banners: banners,
      nextBannerId: nextBannerId,
    );
  }

  LiveEventState withMatchTick() {
    return LiveEventState(
      codesByMatch: codesByMatch,
      matchTick: matchTick + 1,
      banners: banners,
      nextBannerId: nextBannerId,
    );
  }

  LiveEventState withBanner({
    required String title,
    required String body,
    String? deepLink,
    LiveBannerTone tone = LiveBannerTone.info,
  }) {
    final banner = LiveBanner(
      id: nextBannerId,
      title: title,
      body: body,
      deepLink: deepLink,
      tone: tone,
    );
    return LiveEventState(
      codesByMatch: codesByMatch,
      matchTick: matchTick,
      banners: [banner, ...banners],
      nextBannerId: nextBannerId + 1,
    );
  }

  LiveEventState withoutBanner(int id) {
    return LiveEventState(
      codesByMatch: codesByMatch,
      matchTick: matchTick,
      banners: banners.where((b) => b.id != id).toList(growable: false),
      nextBannerId: nextBannerId,
    );
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

  int? _viewerId() {
    final auth = ref.read(authNotifierProvider);
    return auth is AuthSignedIn ? auth.user.id : null;
  }

  void _onEnvelope(NotificationEnvelope env) {
    final p = env.payload ?? const {};
    final viewerId = _viewerId();
    switch (env.type) {
      case 'handover.code_issued':
        final mid = (p['match_id'] as num?)?.toInt();
        final kind = p['kind'] as String?;
        final code = p['code'] as String?;
        final issuedTo = (p['issued_to_id'] as num?)?.toInt();
        if (mid != null && kind != null && code != null) {
          // Only cache the plaintext for the side it was issued to. The
          // server fans the event to both parties so the counterparty
          // can invalidate UI, but they must never see the digits.
          final isHolder = viewerId != null && issuedTo == viewerId;
          if (isHolder) {
            state = state.withCode(LiveHandoverCode(
              matchId: mid,
              kind: kind,
              code: code,
              issuedAt: DateTime.now(),
            ));
          }
          ref.invalidate(matchDetailProvider(mid));
          if (isHolder) {
            final label = kind == 'pickup' ? 'pickup' : 'delivery';
            state = state.withBanner(
              title: 'Your $label code is ready',
              body: 'Tap to view — we won\'t rotate it.',
              deepLink: '/handover/code/$mid?kind=$kind',
              tone: LiveBannerTone.success,
            );
          }
        }
        break;
      case 'offer.created':
      case 'offer.updated':
      case 'offer.accepted':
      case 'match.created':
        final mid = (p['match_id'] as num?)?.toInt();
        if (mid != null) {
          ref.invalidate(matchDetailProvider(mid));
          ref.invalidate(offerListProvider(mid));
        }
        state = state.withMatchTick();
        break;
      case 'match.in_transit':
        final mid = (p['match_id'] as num?)?.toInt();
        final senderId = (p['sender_id'] as num?)?.toInt();
        final travelerId = (p['traveler_id'] as num?)?.toInt();
        if (mid != null) {
          ref.invalidate(matchDetailProvider(mid));
          ref.invalidate(offerListProvider(mid));
        }
        state = state.withMatchTick();
        if (viewerId != null && mid != null) {
          if (viewerId == senderId) {
            state = state.withBanner(
              title: 'Your parcel is on its way',
              body: 'Follow it live.',
              deepLink: '/tracking/$mid',
              tone: LiveBannerTone.success,
            );
          } else if (viewerId == travelerId) {
            state = state.withBanner(
              title: 'Pickup confirmed',
              body: 'Tap when you arrive to enter the delivery code.',
              deepLink: '/handover/verify/$mid?kind=delivery',
              tone: LiveBannerTone.info,
            );
          }
        }
        break;
      case 'match.completed':
        final mid = (p['match_id'] as num?)?.toInt();
        final senderId = (p['sender_id'] as num?)?.toInt();
        final travelerId = (p['traveler_id'] as num?)?.toInt();
        if (mid != null) {
          ref.invalidate(matchDetailProvider(mid));
          ref.invalidate(offerListProvider(mid));
        }
        state = state.withMatchTick();
        if (viewerId != null) {
          final isTraveler = viewerId == travelerId;
          final isSender = viewerId == senderId;
          if (isTraveler) {
            state = state.withBanner(
              title: 'Payment released',
              body: 'Your earnings are now in your wallet.',
              tone: LiveBannerTone.success,
            );
          } else if (isSender) {
            state = state.withBanner(
              title: 'Delivered',
              body: 'Thanks for using ShipTrip.',
              tone: LiveBannerTone.success,
            );
          }
        }
        break;
      case 'payment.captured':
        final mid = (p['match_id'] as num?)?.toInt();
        final payerId = (p['payer_id'] as num?)?.toInt();
        if (mid != null) {
          ref.invalidate(matchDetailProvider(mid));
        }
        state = state.withMatchTick();
        // Traveler side: surface "you have a paid match — wait for the code"
        // (the sender just paid and is being shown the pickup code).
        if (viewerId != null && payerId != null && viewerId != payerId) {
          state = state.withBanner(
            title: 'Match locked in',
            body: 'The sender paid — wait for them to show you the pickup code.',
            tone: LiveBannerTone.info,
          );
        }
        break;
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

  void dismissBanner(int id) {
    state = state.withoutBanner(id);
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
