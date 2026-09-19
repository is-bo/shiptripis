/// The shared read model.
///
/// Every provider here is a projection of server state. None of them decides
/// anything: "needs your attention" is assembled from booleans and party ids
/// the API already published (`allowed_actions`, `awaiting_user_id`,
/// `can_submit_*`, `can_rate`), never from a rule reimplemented in Dart.
///
/// They are `autoDispose` on purpose. Capacity, money and lifecycle state go
/// stale the moment the app is backgrounded, and a provider that outlives its
/// screen is how a user ends up funding a deal against a price that moved. The
/// shell's `IndexedStack` keeps the four tabs mounted, so this costs no
/// refetch when switching tabs — only when a surface is genuinely left.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show ProviderBase;

import '../core/live/live_updates.dart';
import '../core/session/session.dart';
import '../data/repositories.dart';
import '../domain/chat.dart';
import '../domain/deal.dart';
import '../domain/delivery_request.dart';
import '../domain/journey.dart';
import '../domain/offer.dart';
import '../domain/payment.dart';
import '../domain/payout.dart';
import '../domain/rating.dart';

Future<T> _liveRead<T>(
  Ref ref,
  int? expectedAccountId,
  LiveResource resource,
  Future<T> Function() read,
) async {
  final unsubscribe = ref
      .read(liveUpdatesProvider)
      .register(resource, ref.invalidateSelf);
  ref.onDispose(unsubscribe);
  final result = await read();
  if (ref.read(accountProvider)?.id != expectedAccountId) {
    throw const _StaleSessionRead();
  }
  return result;
}

typedef _AccountArgument<T> = ({int? accountId, T argument});

int? _watchAccountId(Ref ref) =>
    ref.watch(accountProvider.select((account) => account?.id));

AsyncValue<T> _projectLiveQuery<T>(Ref ref, ProviderBase<AsyncValue<T>> query) {
  // ignore: experimental_member_use
  ref.onManualInvalidation(() => ref.invalidate(query));
  return ref.watch(query);
}

class _StaleSessionRead implements Exception {
  const _StaleSessionRead();
}

// ---------------------------------------------------------------------------
// Sender-side
// ---------------------------------------------------------------------------

final _myRequestsQuery = FutureProvider.autoDispose
    .family<List<DeliveryRequest>, int?>((ref, accountId) async {
      final repo = ref.watch(requestRepositoryProvider);
      return _liveRead(
        ref,
        accountId,
        const LiveResource.requests(),
        repo.mine,
      );
    });
final myRequestsProvider =
    Provider.autoDispose<AsyncValue<List<DeliveryRequest>>>(
      (ref) => _projectLiveQuery(ref, _myRequestsQuery(_watchAccountId(ref))),
    );

final _requestDetailQuery = FutureProvider.autoDispose
    .family<DeliveryRequest, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(requestRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.request(key.argument),
        () => repo.byId(key.argument),
      );
    });
final requestDetailProvider = Provider.autoDispose
    .family<AsyncValue<DeliveryRequest>, int>((ref, id) {
      return _projectLiveQuery(
        ref,
        _requestDetailQuery((accountId: _watchAccountId(ref), argument: id)),
      );
    });

/// Which photo, on which request.
typedef ParcelPhotoRef = ({int requestId, int mediaId});

/// A short-lived signed URL for one parcel photo.
///
/// The bucket is private and its object keys never leave the server, so this
/// is the only route to the bytes. `autoDispose` matters more than usual: the
/// URL expires in minutes, so a provider that outlived its screen would hand
/// the next viewer a link that has already stopped working.
final _parcelPhotoUrlQuery = FutureProvider.autoDispose
    .family<String, ({AccountSession session, ParcelPhotoRef photo})>((
      ref,
      key,
    ) async {
      final repo = ref.watch(requestRepositoryProvider);
      final url = await repo.photoUrl(
        requestId: key.photo.requestId,
        mediaId: key.photo.mediaId,
      );
      if (ref.read(accountSessionProvider) != key.session) {
        throw const _StaleSessionRead();
      }
      return url;
    });
final parcelPhotoUrlProvider = Provider.autoDispose
    .family<AsyncValue<String>, ParcelPhotoRef>((ref, photo) {
      final session = ref.watch(accountSessionProvider);
      if (session == null) return const AsyncLoading<String>();
      return _projectLiveQuery(
        ref,
        _parcelPhotoUrlQuery((session: session, photo: photo)),
      );
    });

final _postingDepositQuery = FutureProvider.autoDispose
    .family<PostingDepositState, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(paymentRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.deposit(key.argument),
        () => repo.postingDeposit(key.argument),
      );
    });
final postingDepositProvider = Provider.autoDispose
    .family<AsyncValue<PostingDepositState>, int>((ref, requestId) {
      return _projectLiveQuery(
        ref,
        _postingDepositQuery((
          accountId: _watchAccountId(ref),
          argument: requestId,
        )),
      );
    });

// ---------------------------------------------------------------------------
// Traveller-side
// ---------------------------------------------------------------------------

final _myJourneysQuery = FutureProvider.autoDispose.family<List<Journey>, int?>(
  (ref, accountId) async {
    final repo = ref.watch(journeyRepositoryProvider);
    return _liveRead(ref, accountId, const LiveResource.journeys(), repo.mine);
  },
);
final myJourneysProvider = Provider.autoDispose<AsyncValue<List<Journey>>>(
  (ref) => _projectLiveQuery(ref, _myJourneysQuery(_watchAccountId(ref))),
);

final _journeyDetailQuery = FutureProvider.autoDispose
    .family<Journey, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(journeyRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.journey(key.argument),
        () => repo.byId(key.argument),
      );
    });
final journeyDetailProvider = Provider.autoDispose
    .family<AsyncValue<Journey>, int>((ref, id) {
      return _projectLiveQuery(
        ref,
        _journeyDetailQuery((accountId: _watchAccountId(ref), argument: id)),
      );
    });

/// The journeys a traveller can actually receive proposals on.
final activeJourneysProvider = Provider.autoDispose<List<Journey>>((ref) {
  final journeys = ref.watch(myJourneysProvider).value ?? const [];
  return journeys.where((j) => j.status.isLive).toList(growable: false);
});

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

final _dealsQuery = FutureProvider.autoDispose.family<List<Deal>, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(dealRepositoryProvider);
  return _liveRead(ref, accountId, const LiveResource.deals(), repo.list);
});
final dealsProvider = Provider.autoDispose<AsyncValue<List<Deal>>>(
  (ref) => _projectLiveQuery(ref, _dealsQuery(_watchAccountId(ref))),
);

final _activeDealsQuery = FutureProvider.autoDispose.family<List<Deal>, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(dealRepositoryProvider);
  return _liveRead(
    ref,
    accountId,
    const LiveResource.deals(),
    () => repo.list(activity: ActivityState.active),
  );
});
final activeDealsProvider = Provider.autoDispose<AsyncValue<List<Deal>>>(
  (ref) => _projectLiveQuery(ref, _activeDealsQuery(_watchAccountId(ref))),
);

final _historyDealsQuery = FutureProvider.autoDispose.family<List<Deal>, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(dealRepositoryProvider);
  return _liveRead(ref, accountId, const LiveResource.deals(), () async {
    // History is everything the server no longer counts as active, which is
    // two server buckets, not one. Asking only for `completed` left every
    // cancelled or refunded delivery fetched by no provider at all and so
    // invisible in every list on the client.
    final buckets = await Future.wait([
      repo.list(activity: ActivityState.completed),
      repo.list(activity: ActivityState.cancelled),
    ]);
    final byId = <int, Deal>{};
    for (final bucket in buckets) {
      for (final deal in bucket) {
        byId[deal.id] = deal;
      }
    }
    return byId.values.toList(growable: false)
      ..sort((a, b) => b.id.compareTo(a.id));
  });
});
final historyDealsProvider = Provider.autoDispose<AsyncValue<List<Deal>>>(
  (ref) => _projectLiveQuery(ref, _historyDealsQuery(_watchAccountId(ref))),
);

/// Delivery requests whose shipment the server no longer counts as active.
///
/// `ParcelRequest.status` is not a lifecycle signal for a matched shipment: the
/// backend advances it to `matched` when a Deal is created and never moves it
/// again, so `delivered` and `completed` are choices no row ever reaches. A
/// sender's own request therefore stays "live" forever by its own status, which
/// is why finished deliveries kept sitting in Home and never reached History.
///
/// The Deal is the authority. Every Deal row already carries the server-derived
/// `activity_state` and its `delivery_request_id`, so settlement is read from
/// there rather than re-derived locally. An unloaded or failed deal list yields
/// an empty set, which degrades to the previous behaviour rather than hiding a
/// shipment that may still be running.
final settledRequestIdsProvider = Provider.autoDispose<Set<int>>((ref) {
  final deals = ref.watch(dealsProvider).value;
  if (deals == null || deals.isEmpty) return const <int>{};
  final settled = <int>{};
  for (final deal in deals) {
    final requestId = deal.deliveryRequestId;
    if (requestId == null) continue;
    if (deal.activityState == ActivityState.completed ||
        deal.activityState == ActivityState.cancelled) {
      settled.add(requestId);
    }
  }
  return settled;
});

final _completedDealsCountQuery = FutureProvider.autoDispose.family<int, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(dealRepositoryProvider);
  return _liveRead(
    ref,
    accountId,
    const LiveResource.deals(),
    () => repo.count(status: DealStatus.completed),
  );
});
final completedDealsCountProvider = Provider.autoDispose<AsyncValue<int>>(
  (ref) =>
      _projectLiveQuery(ref, _completedDealsCountQuery(_watchAccountId(ref))),
);

final _dealDetailQuery = FutureProvider.autoDispose
    .family<Deal, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(dealRepositoryProvider);
      final deal = await _liveRead(
        ref,
        key.accountId,
        LiveResource.deal(key.argument),
        () => repo.byId(key.argument),
      );
      // One-shot refresh at a server deadline; this does not decide whether
      // an action is permitted and does not poll.
      final now = deal.serverTime ?? DateTime.now();
      final deadlines =
          [
              deal.protectionEndsAt,
              deal.ratings?.reviewWindowEndsAt,
            ].whereType<DateTime>().where((date) => date.isAfter(now)).toList()
            ..sort();
      if (deadlines.isNotEmpty) {
        final delay =
            deadlines.first.difference(now) + const Duration(seconds: 1);
        final elapsed = Stopwatch()..start();
        Timer? timer;
        void arm() {
          timer?.cancel();
          final remaining = delay - elapsed.elapsed;
          timer = Timer(
            remaining.isNegative ? Duration.zero : remaining,
            ref.invalidateSelf,
          );
        }

        arm();
        // Stop as soon as the screen stops listening, before auto-dispose's
        // grace period. Reattaching keeps the original deadline, not a new wait.
        ref.onCancel(() => timer?.cancel());
        ref.onResume(arm);
        ref.onDispose(() {
          timer?.cancel();
          elapsed.stop();
        });
      }
      return deal;
    });
final dealDetailProvider = Provider.autoDispose.family<AsyncValue<Deal>, int>((
  ref,
  id,
) {
  return _projectLiveQuery(
    ref,
    _dealDetailQuery((accountId: _watchAccountId(ref), argument: id)),
  );
});

final _matchesQuery = FutureProvider.autoDispose.family<List<Match>, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(matchingRepositoryProvider);
  return _liveRead(ref, accountId, const LiveResource.matches(), repo.matches);
});
final matchesProvider = Provider.autoDispose<AsyncValue<List<Match>>>(
  (ref) => _projectLiveQuery(ref, _matchesQuery(_watchAccountId(ref))),
);

final _matchDetailQuery = FutureProvider.autoDispose
    .family<Match, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(matchingRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.match(key.argument),
        () => repo.match(key.argument),
      );
    });
final matchDetailProvider = Provider.autoDispose.family<AsyncValue<Match>, int>(
  (ref, id) {
    return _projectLiveQuery(
      ref,
      _matchDetailQuery((accountId: _watchAccountId(ref), argument: id)),
    );
  },
);

final _matchOffersQuery = FutureProvider.autoDispose
    .family<List<Offer>, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(matchingRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.offers(key.argument),
        () => repo.offers(key.argument),
      );
    });
final matchOffersProvider = Provider.autoDispose
    .family<AsyncValue<List<Offer>>, int>((ref, matchId) {
      return _projectLiveQuery(
        ref,
        _matchOffersQuery((accountId: _watchAccountId(ref), argument: matchId)),
      );
    });

final _chatThreadsQuery = FutureProvider.autoDispose
    .family<List<ChatThread>, int?>((ref, accountId) async {
      final repo = ref.watch(chatRepositoryProvider);
      return _liveRead(
        ref,
        accountId,
        const LiveResource.threads(),
        repo.threads,
      );
    });
final chatThreadsProvider = Provider.autoDispose<AsyncValue<List<ChatThread>>>(
  (ref) => _projectLiveQuery(ref, _chatThreadsQuery(_watchAccountId(ref))),
);

final _unreadNotificationsQuery = FutureProvider.autoDispose.family<int, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(notificationRepositoryProvider);
  return _liveRead(
    ref,
    accountId,
    const LiveResource.unread(),
    repo.activeCount,
  );
});

/// The bell count — notifications that still need attention, not unread ones.
final unreadNotificationsProvider = Provider.autoDispose<AsyncValue<int>>(
  (ref) =>
      _projectLiveQuery(ref, _unreadNotificationsQuery(_watchAccountId(ref))),
);

final _unreadActiveNotificationsQuery = FutureProvider.autoDispose
    .family<int, int?>((ref, accountId) async {
      final repo = ref.watch(notificationRepositoryProvider);
      return _liveRead(
        ref,
        accountId,
        const LiveResource.unread(),
        repo.unreadActiveCount,
      );
    });

/// Active notifications the user has not opened. Gates "Mark all read", which
/// the badge total must not: a fully-read inbox can still be full of live
/// actions, and offering to mark them read there does nothing the user can see.
final unreadActiveNotificationsProvider = Provider.autoDispose<AsyncValue<int>>(
  (ref) => _projectLiveQuery(
    ref,
    _unreadActiveNotificationsQuery(_watchAccountId(ref)),
  ),
);

final _payoutsQuery = FutureProvider.autoDispose.family<List<Payout>, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(paymentRepositoryProvider);
  return _liveRead(ref, accountId, const LiveResource.payouts(), repo.payouts);
});
final payoutsProvider = Provider.autoDispose<AsyncValue<List<Payout>>>(
  (ref) => _projectLiveQuery(ref, _payoutsQuery(_watchAccountId(ref))),
);

final _payoutMethodsQuery = FutureProvider.autoDispose
    .family<PayoutMethodsSummary, int?>((ref, accountId) async {
      final repo = ref.watch(paymentRepositoryProvider);
      return _liveRead(
        ref,
        accountId,
        const LiveResource.payouts(),
        repo.payoutMethods,
      );
    });
final payoutMethodsProvider =
    Provider.autoDispose<AsyncValue<PayoutMethodsSummary>>(
      (ref) =>
          _projectLiveQuery(ref, _payoutMethodsQuery(_watchAccountId(ref))),
    );

final _payoutHistoryQuery = FutureProvider.autoDispose
    .family<PayoutHistoryPage, int?>((ref, accountId) async {
      final repo = ref.watch(paymentRepositoryProvider);
      return _liveRead(
        ref,
        accountId,
        const LiveResource.payouts(),
        () => repo.payoutHistoryPaginated(page: 1, pageSize: 50),
      );
    });
final payoutHistoryProvider =
    Provider.autoDispose<AsyncValue<PayoutHistoryPage>>(
      (ref) =>
          _projectLiveQuery(ref, _payoutHistoryQuery(_watchAccountId(ref))),
    );

final _payoutDetailQuery = FutureProvider.autoDispose
    .family<PayoutMobile, ({AccountSession session, String reference})>((
      ref,
      key,
    ) async {
      final repo = ref.watch(paymentRepositoryProvider);
      final payout = await repo.payoutDetail(key.reference);
      if (ref.read(accountSessionProvider) != key.session) {
        throw const _StaleSessionRead();
      }
      return payout;
    });
final payoutDetailProvider = Provider.autoDispose
    .family<AsyncValue<PayoutMobile>, String>((ref, reference) {
      final session = ref.watch(accountSessionProvider);
      if (session == null) return const AsyncLoading<PayoutMobile>();
      return _projectLiveQuery(
        ref,
        _payoutDetailQuery((session: session, reference: reference)),
      );
    });

final _receivedRatingsQuery = FutureProvider.autoDispose
    .family<List<Rating>, AccountSession>((ref, session) async {
      final repo = ref.watch(ratingRepositoryProvider);
      final ratings = await repo.received();
      if (ref.read(accountSessionProvider) != session) {
        throw const _StaleSessionRead();
      }
      return ratings;
    });
final receivedRatingsProvider = Provider.autoDispose<AsyncValue<List<Rating>>>((
  ref,
) {
  final session = ref.watch(accountSessionProvider);
  if (session == null) return const AsyncData<List<Rating>>([]);
  return _projectLiveQuery(ref, _receivedRatingsQuery(session));
});

final paymentProvidersProvider = FutureProvider.autoDispose<ProvidersView>((
  ref,
) async {
  final repo = ref.watch(paymentRepositoryProvider);
  return repo.providers();
});

// ---------------------------------------------------------------------------
// Derived: unread badges
// ---------------------------------------------------------------------------

final unreadChatCountProvider = Provider.autoDispose<int>((ref) {
  final threads = ref.watch(chatThreadsProvider).value ?? const [];
  var total = 0;
  for (final thread in threads) {
    total += thread.unreadCount;
  }
  return total;
});

// ---------------------------------------------------------------------------
// Derived: what needs this user
// ---------------------------------------------------------------------------

/// Why a delivery is sitting on this user's desk.
///
/// Each member maps to a server-published fact, named here so a screen can
/// order and explain them rather than showing an undifferentiated pile.
enum AttentionReason {
  /// An offer is waiting on this user's reply.
  offerAwaitingYou,

  /// A deal is accepted but unfunded, and this user is the sender.
  fundingRequired,

  /// The sender still has to record who receives the parcel.
  recipientRequired,

  /// The sender may reveal a code for the traveller to be given.
  revealPickupCode,

  /// The traveller may enter the pickup code.
  submitPickupCode,

  /// The delivery code is out of its buffer and the sender may reveal it.
  revealDeliveryCode,

  /// The traveller may enter the delivery code the recipient read to them.
  submitDeliveryCode,

  /// The rating window is open and this user has not rated.
  ratingOpen,
}

@immutable
class AttentionItem {
  const AttentionItem({
    required this.reason,
    required this.dealId,
    this.matchId,
    this.requestId,
  });

  final AttentionReason reason;
  final int? dealId;
  final int? matchId;
  final int? requestId;
}

/// Everything currently waiting on this user, assembled from server booleans.
///
/// Reads the deal **list**, which carries no `handover` block, plus whatever
/// detail is already in cache. It therefore surfaces the reasons it can see
/// and never invents the rest; a deal screen shows the full picture.
final attentionProvider = Provider.autoDispose<List<AttentionItem>>((ref) {
  final account = ref.watch(accountProvider);
  if (account == null) return const [];

  final items = <AttentionItem>[];

  for (final match in ref.watch(matchesProvider).value ?? const []) {
    if (match.awaitsViewer(account.id)) {
      items.add(
        AttentionItem(
          reason: AttentionReason.offerAwaitingYou,
          dealId: match.dealId,
          matchId: match.id,
          requestId: match.parcelId,
        ),
      );
    }
  }

  for (final deal in ref.watch(dealsProvider).value ?? const []) {
    final isSender = deal.isSender(account.id);

    if (deal.status.needsFunding && isSender) {
      items.add(
        AttentionItem(
          reason: AttentionReason.fundingRequired,
          dealId: deal.id,
          matchId: deal.matchId,
          requestId: deal.deliveryRequestId,
        ),
      );
      continue;
    }

    // The detail projection is richer; use it when this deal happens to be
    // loaded. Nothing here fabricates a permission the server did not send.
    final detail = ref.watch(dealDetailProvider(deal.id)).value;
    final handover = detail?.handover;
    if (handover != null) {
      if (handover.canRevealDeliveryCode) {
        items.add(
          AttentionItem(
            reason: AttentionReason.revealDeliveryCode,
            dealId: deal.id,
          ),
        );
      } else if (handover.canSubmitDeliveryCode) {
        items.add(
          AttentionItem(
            reason: AttentionReason.submitDeliveryCode,
            dealId: deal.id,
          ),
        );
      } else if (handover.canSubmitPickupCode) {
        items.add(
          AttentionItem(
            reason: AttentionReason.submitPickupCode,
            dealId: deal.id,
          ),
        );
      } else if (handover.canRevealPickupCode) {
        items.add(
          AttentionItem(
            reason: AttentionReason.revealPickupCode,
            dealId: deal.id,
          ),
        );
      }
    }

    final ratings = detail?.ratings;
    if (ratings != null && ratings.canRate && !ratings.submitted) {
      items.add(
        AttentionItem(reason: AttentionReason.ratingOpen, dealId: deal.id),
      );
    }
  }

  return items;
});

// ---------------------------------------------------------------------------
// Refresh on resume
// ---------------------------------------------------------------------------

/// Refreshes the account when the app returns to the foreground.
///
/// [PushCoordinator] separately reconciles the current route and mounted
/// collections through [LiveUpdates], avoiding unrelated detail reads.
class ResumeRefresher extends ConsumerStatefulWidget {
  const ResumeRefresher({required this.child, super.key});

  final Widget child;

  @override
  ConsumerState<ResumeRefresher> createState() => _ResumeRefresherState();
}

class _ResumeRefresherState extends ConsumerState<ResumeRefresher>
    with WidgetsBindingObserver {
  /// A provider redirect leaves and returns within seconds and still needs
  /// fresh state, so the only absence worth ignoring is one with no gap at
  /// all — a transient `inactive` flicker rather than a real departure.
  static const _ignoreShorterThan = Duration(seconds: 1);

  DateTime? _leftAt;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
        _leftAt = DateTime.now();
      case AppLifecycleState.resumed:
        _onResumed();
      case AppLifecycleState.inactive:
      case AppLifecycleState.detached:
        break;
    }
  }

  void _onResumed() {
    final away = _leftAt;
    _leftAt = null;

    if (away != null && DateTime.now().difference(away) < _ignoreShorterThan) {
      return;
    }

    unawaited(ref.read(sessionProvider.notifier).refreshAccount());
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// Drops every cached projection of server state.
///
/// Also called after any mutation that can move a deal — funding, a handover
/// submission, a cancellation — so the next read is authoritative rather than
/// optimistic.
void refreshVolatileState(WidgetRef ref) {
  ref
    ..invalidate(dealsProvider)
    ..invalidate(activeDealsProvider)
    ..invalidate(historyDealsProvider)
    ..invalidate(completedDealsCountProvider)
    ..invalidate(dealDetailProvider)
    ..invalidate(matchesProvider)
    ..invalidate(matchDetailProvider)
    ..invalidate(matchOffersProvider)
    ..invalidate(myRequestsProvider)
    ..invalidate(requestDetailProvider)
    ..invalidate(myJourneysProvider)
    ..invalidate(journeyDetailProvider)
    ..invalidate(chatThreadsProvider)
    ..invalidate(unreadNotificationsProvider)
    ..invalidate(postingDepositProvider)
    ..invalidate(payoutsProvider)
    ..invalidate(payoutHistoryProvider)
    ..invalidate(payoutMethodsProvider);
}
