/// Session-scoped invalidation for authoritative server state.
///
/// WebSocket and Firebase messages are hints that a resource changed. They
/// never patch financial or lifecycle state locally; registered providers
/// re-read their normal HTTP endpoint instead.
library;

import 'dart:async';
import 'dart:collection';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

enum LiveResourceKind {
  account,
  deal,
  deals,
  payment,
  match,
  matches,
  offers,
  request,
  requests,
  deposit,
  journey,
  journeys,
  dispute,
  chat,
  threads,
  notifications,
  unread,
  payouts,
}

@immutable
class LiveResource {
  const LiveResource(this.kind, [this.id]);

  const LiveResource.account() : this(LiveResourceKind.account);
  const LiveResource.deal(int id) : this(LiveResourceKind.deal, id);
  const LiveResource.deals() : this(LiveResourceKind.deals);
  const LiveResource.payment(int dealId)
    : this(LiveResourceKind.payment, dealId);
  const LiveResource.match(int id) : this(LiveResourceKind.match, id);
  const LiveResource.matches() : this(LiveResourceKind.matches);
  const LiveResource.offers(int matchId)
    : this(LiveResourceKind.offers, matchId);
  const LiveResource.request(int id) : this(LiveResourceKind.request, id);
  const LiveResource.requests() : this(LiveResourceKind.requests);
  const LiveResource.deposit(int requestId)
    : this(LiveResourceKind.deposit, requestId);
  const LiveResource.journey(int id) : this(LiveResourceKind.journey, id);
  const LiveResource.journeys() : this(LiveResourceKind.journeys);
  const LiveResource.dispute(int id) : this(LiveResourceKind.dispute, id);
  const LiveResource.chat(int matchId) : this(LiveResourceKind.chat, matchId);
  const LiveResource.threads() : this(LiveResourceKind.threads);
  const LiveResource.notifications() : this(LiveResourceKind.notifications);
  const LiveResource.unread() : this(LiveResourceKind.unread);
  const LiveResource.payouts() : this(LiveResourceKind.payouts);

  final LiveResourceKind kind;
  final int? id;

  bool get isCollection => id == null && kind != LiveResourceKind.account;

  @override
  bool operator ==(Object other) =>
      other is LiveResource && other.kind == kind && other.id == id;

  @override
  int get hashCode => Object.hash(kind, id);

  @override
  String toString() => id == null ? kind.name : '${kind.name}($id)';
}

enum LiveEventSource { websocket, firebase }

typedef LiveUnsubscribe = void Function();

final liveUpdatesProvider = Provider<LiveUpdates>((ref) {
  final updates = LiveUpdates();
  ref.onDispose(updates.dispose);
  return updates;
});

class LiveUpdates {
  LiveUpdates({
    Duration coalesceFor = const Duration(milliseconds: 75),
    Duration reconcileSettlesFor = const Duration(seconds: 5),
    DateTime Function()? now,
  }) : _coalesceFor = coalesceFor,
       _reconcileSettlesFor = reconcileSettlesFor,
       _now = now ?? DateTime.now;

  static const _dedupLimit = 128;

  final Duration _coalesceFor;

  /// How long one catch-up covers for.
  ///
  /// Three things ask for a catch-up at almost the same instant — the app
  /// resuming, the chat socket connecting, the notification socket connecting —
  /// and each of them re-fires *every mounted collection*. On the deployed TEST
  /// runtime that showed up as `/api/deals`, `/api/matches`, `/api/parcels`,
  /// `/api/chat/threads` and the bell each being fetched three times inside two
  /// seconds on every foreground, over a server running two workers. They are
  /// not three different questions; they are the same question asked by three
  /// callers who cannot see each other. The first one answers it.
  ///
  /// This bounds duplicate *catch-up* only. A real business event arriving over
  /// the socket still goes through [ingest] and is never suppressed.
  final Duration _reconcileSettlesFor;

  /// Wall clock, injectable so the window can be exercised without waiting it
  /// out. Deliberately not a [Timer]: a pending timer would outlive the widget
  /// tree in every test that foregrounds the app, and a catch-up window has no
  /// work of its own to do when it expires.
  final DateTime Function() _now;
  DateTime? _reconciledAt;
  Set<LiveResource> _lastReconciled = const {};
  final Map<LiveResource, Set<VoidCallback>> _listeners = {};
  final LinkedHashMap<String, Set<LiveResource>> _seen = LinkedHashMap();
  final Set<LiveResource> _queued = {};
  Timer? _flushTimer;
  int? _accountId;
  int _generation = 0;
  bool _disposed = false;

  LiveUnsubscribe register(LiveResource resource, VoidCallback callback) {
    if (_disposed) return () {};
    final callbacks = _listeners.putIfAbsent(resource, () => {});
    callbacks.add(callback);
    var active = true;
    return () {
      if (!active) return;
      active = false;
      final current = _listeners[resource];
      current?.remove(callback);
      if (current?.isEmpty ?? false) _listeners.remove(resource);
    };
  }

  /// Changes the owner of every event, queued callback and dedup key.
  ///
  /// This is synchronous so logout cannot leave a callback from the previous
  /// account waiting behind a timer.
  void bindAccount(int? accountId) {
    if (_accountId == accountId) return;
    _accountId = accountId;
    _generation++;
    _flushTimer?.cancel();
    _flushTimer = null;
    _queued.clear();
    _seen.clear();
    _reconciledAt = null;
    _lastReconciled = const {};
  }

  /// Normalizes either a Go WS envelope or Firebase data and queues only the
  /// HTTP resources affected by its typed business event.
  void ingest(Map<String, dynamic> event, {required LiveEventSource source}) {
    if (_disposed || _accountId == null) return;
    final normalized = _NormalizedEvent.from(event);
    if (normalized.type.isEmpty) return;
    final resources = resourcesForLiveEvent(normalized.type, normalized.data);
    if (resources.isEmpty) return;

    final eventId = normalized.eventId;
    if (eventId == null || eventId.isEmpty) {
      _enqueue(resources);
      return;
    }

    final previouslySeen = _seen[eventId];
    if (previouslySeen == null) {
      _seen[eventId] = {...resources};
      while (_seen.length > _dedupLimit) {
        _seen.remove(_seen.keys.first);
      }
      _enqueue(resources);
      return;
    }

    // The WS copy can carry a match id that the FCM allowlist omitted. Keep
    // dedup per resource so that richer second copy still reaches the active
    // chat controller without refiring callbacks already covered by FCM.
    final richer = resources.difference(previouslySeen);
    if (richer.isEmpty) return;
    previouslySeen.addAll(richer);
    _enqueue(richer);
  }

  /// Reconciles the current route, every mounted collection and the bell.
  /// Detail providers elsewhere in an IndexedStack are intentionally skipped.
  void reconcileScope(Iterable<LiveResource> routeResources) {
    if (_disposed || _accountId == null) return;
    final resources = <LiveResource>{
      const LiveResource.unread(),
      ...routeResources,
      for (final resource in _listeners.keys)
        if (resource.isCollection) resource,
    };
    // Already covered: a catch-up for these same resources completed moments
    // ago, so re-reading them would return what the screen is already showing.
    // Anything *new* since — a detail route pushed after the last catch-up —
    // still goes through, and so does any reconcile after the window.
    final at = _now();
    final settled = _reconciledAt;
    if (settled != null && at.difference(settled) < _reconcileSettlesFor) {
      final fresh = resources.difference(_lastReconciled);
      if (fresh.isEmpty) return;
      _lastReconciled = {..._lastReconciled, ...fresh};
      _enqueue(fresh);
      return;
    }
    _reconciledAt = at;
    _lastReconciled = resources;
    _enqueue(resources);
  }

  void _enqueue(Iterable<LiveResource> resources) {
    _queued.addAll(resources);
    if (_flushTimer != null) return;
    final scheduledGeneration = _generation;
    _flushTimer = Timer(_coalesceFor, () {
      _flushTimer = null;
      if (_disposed || scheduledGeneration != _generation) {
        _queued.clear();
        return;
      }
      final ready = Set<LiveResource>.from(_queued);
      _queued.clear();
      for (final resource in ready) {
        final callbacks = List<VoidCallback>.from(
          _listeners[resource] ?? const <VoidCallback>{},
        );
        for (final callback in callbacks) {
          if (_disposed || scheduledGeneration != _generation) return;
          callback();
        }
      }
    });
  }

  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _generation++;
    _flushTimer?.cancel();
    _flushTimer = null;
    _reconciledAt = null;
    _queued.clear();
    _seen.clear();
    _listeners.clear();
  }
}

/// The one event-to-resource map used by WebSocket and Firebase delivery.
Set<LiveResource> resourcesForLiveEvent(
  String type,
  Map<String, dynamic> data,
) {
  // Ignore protocol frames and unknown names. A socket acknowledgement or
  // heartbeat is not a notification and must not cause an HTTP read.
  const knownEvents = {
    'trip.created',
    'trip.updated',
    'trip.cancelled',
    'parcel.created',
    'parcel.cancelled',
    'match.created',
    'match.in_transit',
    'match.completed',
    'offer.created',
    'offer.updated',
    'offer.accepted',
    'payment.captured',
    'payment.failed',
    'payment.refunded',
    'handover.confirmed',
    'handover.code_issued',
    'handover.delivery_code_available',
    'handover.delivery_confirmed',
    'kyc.status_changed',
    'flight_proof.status_changed',
    'deal.updated',
    'deal.cancelled',
    // I1A journey timing publishes three distinct arrival facts on three
    // channels (apps/core/channels.py). None of them was listed here, so every
    // arrival report, confirmation and decline was dropped before it could
    // refresh the deal or the bell — over the socket and over push alike.
    // They need no branch of their own: the `deal.` case below already
    // reconciles the deal, its match and its payment.
    'deal.arrival_reported',
    'deal.arrival_confirmed',
    'deal.arrival_declined',
    'dispute.opened',
    'dispute.resolved',
    'payout.status_changed',
    'chat.message.new',
  };
  if (!knownEvents.contains(type)) return const {};

  int? positive(String key) {
    final raw = data[key];
    final parsed = switch (raw) {
      final int value => value,
      final num value
          when value.isFinite && value == value.truncateToDouble() =>
        value.toInt(),
      final String value => int.tryParse(value),
      _ => null,
    };
    return parsed != null && parsed > 0 ? parsed : null;
  }

  final dealId = positive('deal_id');
  final matchId = positive('match_id');
  final requestId = positive('request_id') ?? positive('parcel_id');
  final journeyId = positive('journey_id') ?? positive('trip_id');
  final disputeId = positive('dispute_id');
  final resources = <LiveResource>{
    const LiveResource.notifications(),
    const LiveResource.unread(),
  };

  void addDeal() {
    resources.add(const LiveResource.deals());
    if (dealId != null) resources.add(LiveResource.deal(dealId));
  }

  void addMatch({bool offers = false}) {
    resources.add(const LiveResource.matches());
    if (matchId != null) {
      resources.add(LiveResource.match(matchId));
      if (offers) resources.add(LiveResource.offers(matchId));
    }
  }

  void addRequest({bool deposit = false}) {
    resources.add(const LiveResource.requests());
    if (requestId != null) {
      resources.add(LiveResource.request(requestId));
      if (deposit) resources.add(LiveResource.deposit(requestId));
    }
  }

  void addJourney() {
    resources.add(const LiveResource.journeys());
    if (journeyId != null) resources.add(LiveResource.journey(journeyId));
  }

  if (type.startsWith('parcel.')) {
    addRequest(deposit: true);
  } else if (type.startsWith('trip.') || type.startsWith('flight_proof.')) {
    addJourney();
    resources.add(const LiveResource.matches());
  } else if (type.startsWith('offer.')) {
    addMatch(offers: true);
    if (requestId != null) addRequest();
    if (journeyId != null) addJourney();
    if (dealId != null || type == 'offer.accepted') addDeal();
  } else if (type.startsWith('match.')) {
    addMatch(offers: true);
    resources.add(const LiveResource.threads());
    if (dealId != null) addDeal();
    if (requestId != null) addRequest();
    if (journeyId != null) addJourney();
  } else if (type.startsWith('payment.')) {
    addDeal();
    if (dealId != null) resources.add(LiveResource.payment(dealId));
    if (requestId != null) addRequest(deposit: true);
    resources
      ..add(const LiveResource.payouts())
      ..add(const LiveResource.threads());
  } else if (type.startsWith('payout.')) {
    addDeal();
    resources.add(const LiveResource.payouts());
  } else if (type.startsWith('deal.') || type.startsWith('handover.')) {
    addDeal();
    addMatch();
    if (dealId != null) resources.add(LiveResource.payment(dealId));
    if (requestId != null) addRequest();
    if (journeyId != null) addJourney();
    resources.add(const LiveResource.threads());
  } else if (type.startsWith('dispute.')) {
    addDeal();
    if (dealId != null) resources.add(LiveResource.payment(dealId));
    if (disputeId != null) resources.add(LiveResource.dispute(disputeId));
    resources
      ..add(const LiveResource.payouts())
      ..add(const LiveResource.threads());
  } else if (type.startsWith('chat.')) {
    resources.add(const LiveResource.threads());
    if (matchId != null) resources.add(LiveResource.chat(matchId));
  } else if (type.startsWith('kyc.')) {
    resources.add(const LiveResource.account());
  }

  if (matchId != null &&
      (type.startsWith('match.') ||
          type.startsWith('deal.') ||
          type.startsWith('payment.') ||
          type.startsWith('handover.') ||
          type.startsWith('dispute.'))) {
    resources.add(LiveResource.chat(matchId));
  }

  return resources;
}

Set<LiveResource> liveResourcesForLocation(String location) {
  final uri = Uri.tryParse(location);
  final segments = uri?.pathSegments ?? const <String>[];
  if (segments.isEmpty) return const {};

  int? idAt(int index) {
    if (segments.length <= index) return null;
    final id = int.tryParse(segments[index]);
    return id != null && id > 0 ? id : null;
  }

  final id = idAt(1);
  final chatMatchId = idAt(2);
  return switch (segments) {
    ['notifications'] => {
      const LiveResource.notifications(),
      const LiveResource.unread(),
    },
    ['deals', _, 'payment'] when id != null => {
      LiveResource.deal(id),
      LiveResource.payment(id),
    },
    ['deals', _, ...] when id != null => {LiveResource.deal(id)},
    ['disputes', _, ...] when id != null => {LiveResource.dispute(id)},
    ['matches', _, ...] when id != null => {
      LiveResource.match(id),
      LiveResource.offers(id),
    },
    ['requests', _, 'deposit'] when id != null => {
      LiveResource.request(id),
      LiveResource.deposit(id),
    },
    ['requests', _, ...] when id != null => {LiveResource.request(id)},
    ['journeys', _, ...] when id != null => {LiveResource.journey(id)},
    ['chat', 'thread', _] when chatMatchId != null => {
      const LiveResource.threads(),
      LiveResource.chat(chatMatchId),
    },
    ['profile', 'payouts'] => {const LiveResource.payouts()},
    _ => const <LiveResource>{},
  };
}

class _NormalizedEvent {
  const _NormalizedEvent({
    required this.type,
    required this.eventId,
    required this.data,
  });

  factory _NormalizedEvent.from(Map<String, dynamic> raw) {
    final data = <String, dynamic>{...raw};
    final payload = raw['payload'];
    if (payload is Map) data.addAll(Map<String, dynamic>.from(payload));
    final nested = data['payload'];
    if (nested is Map) data.addAll(Map<String, dynamic>.from(nested));
    final type =
        raw['type'] ?? raw['channel'] ?? data['type'] ?? data['channel'];
    final eventId = raw['event_id'] ?? data['event_id'];
    return _NormalizedEvent(
      type: type is String ? type : '',
      eventId: eventId is String ? eventId : null,
      data: data,
    );
  }

  final String type;
  final String? eventId;
  final Map<String, dynamic> data;
}
