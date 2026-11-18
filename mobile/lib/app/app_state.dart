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
/// refetch when switching tabs — only when a surface is genuinely left. The
/// one exception is finished Deal history, kept a minute after its last viewer
/// for a filter round trip ([DealHistoryController.keptFor]): list
/// presentation, never a detail, an amount or an allowed action.
library;

import 'dart:async';

import 'package:dio/dio.dart' show CancelToken;
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
import '../domain/problems.dart';
import '../domain/progress.dart';
import '../domain/schedule_change.dart';
import '../domain/find_travelers.dart';
import '../domain/rating.dart';
import '../domain/sea_crossings.dart';

/// A token that cancels this provider's read once nothing wants its answer:
/// the provider is disposed (its screen left, its filter changed) or rebuilt
/// (a live event, a refresh or a new session superseded it). Riverpod has
/// already stopped listening to that read by then, so its cancellation is
/// never shown to anyone (K5).
///
/// For reads only. A write must finish whatever the UI does meanwhile, so it
/// is never handed one of these.
CancelToken cancelOnDispose(Ref ref) {
  final token = CancelToken();
  ref.onDispose(token.cancel);
  return token;
}

/// A private read, refreshed by live events for [resource].
///
/// A guest asks the server for nothing private. A list a guest's screens
/// show (their own requests behind a trip preview, say) reads as [guest];
/// anything else stays loading, for a session that is not there.
Future<T> _liveRead<T>(
  Ref ref,
  int? expectedAccountId,
  LiveResource resource,
  Future<T> Function(CancelToken cancel) read, {
  T? guest,
}) async {
  if (ref.watch(isGuestProvider)) {
    return guest ?? Completer<T>().future;
  }
  final unsubscribe = ref
      .read(liveUpdatesProvider)
      .register(resource, ref.invalidateSelf);
  ref.onDispose(unsubscribe);
  final result = await read(cancelOnDispose(ref));
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
        (cancel) => repo.mine(cancelToken: cancel),
        guest: const [],
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
        (cancel) => repo.byId(key.argument, cancelToken: cancel),
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
        cancelToken: cancelOnDispose(ref),
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
        (cancel) => repo.postingDeposit(key.argument, cancelToken: cancel),
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
    return _liveRead(
      ref,
      accountId,
      const LiveResource.journeys(),
      (cancel) => repo.mine(cancelToken: cancel),
      guest: const [],
    );
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
        (cancel) => repo.byId(key.argument, cancelToken: cancel),
      );
    });

/// The ferry lines and the "Sea legs" switch, for the route editor.
///
/// Its own provider so a failure stays local to Sea: editing flight and road
/// legs never waits on it and never fails with it.
final seaCrossingsProvider = FutureProvider.autoDispose<SeaCrossings>(
  (ref) => ref
      .watch(geographyRepositoryProvider)
      .seaCrossings(cancelToken: cancelOnDispose(ref)),
  // No silent retry loop: a failure shows the editor's own notice straight
  // away, with a button, instead of staying "loading" for a minute.
  retry: (_, _) => null,
);

/// Whether travellers may set a price, and the ceilings. Its own provider: a
/// failure leaves the route editable and hides only the price.
final travelerPricingPolicyProvider =
    FutureProvider.autoDispose<TravelerPricingPolicy>(
      (ref) => ref
          .watch(journeyRepositoryProvider)
          .pricingPolicy(cancelToken: cancelOnDispose(ref)),
      retry: (_, _) => null,
    );

final journeyDetailProvider = Provider.autoDispose
    .family<AsyncValue<Journey>, int>((ref, id) {
      return _projectLiveQuery(
        ref,
        _journeyDetailQuery((accountId: _watchAccountId(ref), argument: id)),
      );
    });

/// Each leg's progress reports and the buttons the server offers.
///
/// Refreshed with the journey itself: a reminder, a report from another
/// device or a journey the server moved all reconcile through
/// `LiveResource.journey`.
final _journeyProgressQuery = FutureProvider.autoDispose
    .family<JourneyProgress, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(journeyRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.journey(key.argument),
        (cancel) => repo.progress(key.argument, cancelToken: cancel),
      );
    });
final journeyProgressProvider = Provider.autoDispose
    .family<AsyncValue<JourneyProgress>, int>((ref, id) {
      return _projectLiveQuery(
        ref,
        _journeyProgressQuery((accountId: _watchAccountId(ref), argument: id)),
      );
    });

final _pendingProgressQuery = FutureProvider.autoDispose
    .family<List<PendingProgressQuestion>, int?>((ref, accountId) async {
      final repo = ref.watch(journeyRepositoryProvider);
      return _liveRead(
        ref,
        accountId,
        const LiveResource.progress(),
        (cancel) => repo.pendingProgress(cancelToken: cancel),
      );
    });

/// "Did you depart from {city}?", for Home. Read only when the traveler has a
/// live journey, so a sender's Home makes no extra request. A failure is an
/// empty list: Home must never fail because a reminder could not load.
final pendingProgressProvider =
    Provider.autoDispose<List<PendingProgressQuestion>>((ref) {
      final accountId = _watchAccountId(ref);
      if (accountId == null || ref.watch(activeJourneysProvider).isEmpty) {
        return const [];
      }
      final dismissed = ref.watch(dismissedProgressQuestionsProvider);
      final pending = _projectLiveQuery(ref, _pendingProgressQuery(accountId));
      return [
        for (final question in pending.value ?? const [])
          if (!dismissed.contains((question.legId, question.kind))) question,
      ];
    });

/// Questions the traveler answered "Not yet" to, for this app session only.
/// The server keeps asking on its own schedule; this just stops Home nagging
/// with the answer already given.
final dismissedProgressQuestionsProvider =
    NotifierProvider<DismissedProgressQuestions, Set<(int, ProgressKind)>>(
      DismissedProgressQuestions.new,
    );

class DismissedProgressQuestions extends Notifier<Set<(int, ProgressKind)>> {
  @override
  Set<(int, ProgressKind)> build() => const {};

  void dismiss(int legId, ProgressKind kind) =>
      state = {...state, (legId, kind)};
}

/// The journeys a traveller can actually receive proposals on.
final activeJourneysProvider = Provider.autoDispose<List<Journey>>((ref) {
  final journeys = ref.watch(myJourneysProvider).value ?? const [];
  return journeys.where((j) => j.status.isLive).toList(growable: false);
});

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

final _currentDealsQuery = FutureProvider.autoDispose.family<List<Deal>, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(dealRepositoryProvider);
  return _liveRead(
    ref,
    accountId,
    const LiveResource.deals(),
    (cancel) => repo.current(cancelToken: cancel),
    guest: const [],
  );
});

/// Every live Deal, plus delivered ones whose review window may still be open.
///
/// The one Deal read Home and active Deliveries share. It is bounded by
/// construction — finished history is paged separately — and complete: every
/// page is read, so an account with more Deals than one page no longer loses
/// the older ones (K5). Each row carries the server's `attention` flags.
final currentDealsProvider = Provider.autoDispose<AsyncValue<List<Deal>>>(
  (ref) => _projectLiveQuery(ref, _currentDealsQuery(_watchAccountId(ref))),
);

/// Live shipments only.
///
/// Derived from [currentDealsProvider] by each row's server-owned
/// `activity_state` — the same rule the server's `?activity=active` filter
/// applies — so this is that set without a second request.
final activeDealsProvider = Provider.autoDispose<AsyncValue<List<Deal>>>((ref) {
  // ignore: experimental_member_use
  ref.onManualInvalidation(() => ref.invalidate(currentDealsProvider));
  return ref
      .watch(currentDealsProvider)
      .whenData(
        (deals) => deals
            .where((deal) => deal.activityState == ActivityState.active)
            .toList(growable: false),
      );
});

/// Finished Deals read so far, and whether the server has more.
@immutable
class DealHistory {
  const DealHistory({
    this.deals = const [],
    this.pagesLoaded = 0,
    this.hasMore = false,
    this.loadingMore = false,
    this.loadMoreError,
  });

  final List<Deal> deals;
  final int pagesLoaded;
  final bool hasMore;
  final bool loadingMore;

  /// Why the last next-page read failed, until the next attempt starts.
  final Object? loadMoreError;

  DealHistory _loading() => DealHistory(
    deals: deals,
    pagesLoaded: pagesLoaded,
    hasMore: hasMore,
    loadingMore: true,
  );

  DealHistory _failed(Object error) => DealHistory(
    deals: deals,
    pagesLoaded: pagesLoaded,
    hasMore: hasMore,
    loadMoreError: error,
  );
}

/// Completed and cancelled Deals, a page at a time.
///
/// History only grows, so it is never read whole: the first page when the
/// user opens it, the next as they scroll toward the end. A live Deal event
/// starts it again from the first page, like every other projection here.
class DealHistoryController extends AsyncNotifier<DealHistory> {
  DealHistoryController(this.accountId);

  /// How long history outlives its last viewer (K5). Switching Deliveries'
  /// filter away and back used to start again from page one and drop every
  /// page already scrolled through. History is list presentation only: each
  /// Deal it shows opens onto a fresh detail read, and a live Deal event still
  /// drops it at once.
  static const keptFor = Duration(minutes: 1);

  final int? accountId;
  int _generation = 0;
  CancelToken? _loadMore;

  @override
  Future<DealHistory> build() async {
    final generation = ++_generation;
    ref.onDispose(() {
      _generation++;
      _loadMore?.cancel();
    });
    _keepBriefly();
    final repo = ref.watch(dealRepositoryProvider);
    final page = await _liveRead(
      ref,
      accountId,
      const LiveResource.deals(),
      (cancel) => repo.historyPage(page: 1, cancelToken: cancel),
    );
    if (generation != _generation) throw const _StaleSessionRead();
    return DealHistory(
      deals: page.deals,
      pagesLoaded: 1,
      hasMore: page.hasNext,
    );
  }

  /// Keeps this history for [keptFor] after its last viewer leaves, and never
  /// past the sign-in that read it: the family is keyed by account id, so the
  /// same account signing in again must not find the old pages.
  void _keepBriefly() {
    final link = ref.keepAlive();
    Timer? release;
    ref
      ..onCancel(() => release = Timer(keptFor, link.close))
      ..onResume(() => release?.cancel())
      ..onDispose(() => release?.cancel());
    final session = ref.read(accountSessionProvider);
    ref.listen(accountSessionProvider, (_, next) {
      if (next != session) link.close();
    });
  }

  /// Reads the next page. A no-op while one is already in flight, when the
  /// server said there is nothing more, or before the first page landed.
  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || current.loadingMore) return;
    final generation = _generation;
    state = AsyncData(current._loading());
    final cancel = _loadMore = CancelToken();
    try {
      final page = await ref
          .read(dealRepositoryProvider)
          .historyPage(page: current.pagesLoaded + 1, cancelToken: cancel);
      if (generation != _generation ||
          ref.read(accountProvider)?.id != accountId) {
        return;
      }
      // Offset paging over a newest-first list: a Deal finishing meanwhile
      // pushes every row down one, so the next page can repeat the last row
      // of this one. It can never skip one.
      final seen = {for (final deal in current.deals) deal.id};
      state = AsyncData(
        DealHistory(
          deals: [
            ...current.deals,
            ...page.deals.where((deal) => seen.add(deal.id)),
          ],
          pagesLoaded: current.pagesLoaded + 1,
          hasMore: page.hasNext,
        ),
      );
    } on Object catch (error) {
      if (generation != _generation) return;
      state = AsyncData(current._failed(error));
    }
  }
}

final _dealHistoryQuery = AsyncNotifierProvider.autoDispose
    .family<DealHistoryController, DealHistory, int?>(
      DealHistoryController.new,
    );
final dealHistoryProvider = Provider.autoDispose<AsyncValue<DealHistory>>(
  (ref) => _projectLiveQuery(ref, _dealHistoryQuery(_watchAccountId(ref))),
);

/// The finished Deals read so far, for surfaces that only need the rows.
final historyDealsProvider = Provider.autoDispose<AsyncValue<List<Deal>>>((
  ref,
) {
  // ignore: experimental_member_use
  ref.onManualInvalidation(() => ref.invalidate(dealHistoryProvider));
  return ref.watch(dealHistoryProvider).whenData((history) => history.deals);
});

/// Asks the current account's history for its next page.
void loadMoreDealHistory(WidgetRef ref) {
  final accountId = ref.read(accountProvider)?.id;
  unawaited(ref.read(_dealHistoryQuery(accountId).notifier).loadMore());
}

final _completedDealsCountQuery = FutureProvider.autoDispose.family<int, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(dealRepositoryProvider);
  return _liveRead(
    ref,
    accountId,
    const LiveResource.deals(),
    (cancel) => repo.count(status: DealStatus.completed, cancelToken: cancel),
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
        (cancel) => repo.byId(key.argument, cancelToken: cancel),
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

/// A delivery's problem reports and which ones the server lets this person
/// make now. Refreshed with the deal itself: a report from the other person,
/// a staff decision or a pickup that closes the no-show window all arrive as a
/// deal event.
final _dealProblemsQuery = FutureProvider.autoDispose
    .family<DealProblems, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(problemRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.deal(key.argument),
        (cancel) => repo.forDeal(key.argument, cancelToken: cancel),
      );
    }, retry: (_, _) => null);
final dealProblemsProvider = Provider.autoDispose
    .family<AsyncValue<DealProblems>, int>((ref, dealId) {
      return _projectLiveQuery(
        ref,
        _dealProblemsQuery((accountId: _watchAccountId(ref), argument: dealId)),
      );
    });

/// The newest new times that touched a parcel, for its sender. A failure here
/// must never fail the delivery screen, so the screen reads `.value` only.
final _dealScheduleChangeQuery = FutureProvider.autoDispose
    .family<SenderScheduleChange?, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(dealRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.deal(key.argument),
        (cancel) => repo.scheduleChange(key.argument, cancelToken: cancel),
      );
    }, retry: (_, _) => null);
final dealScheduleChangeProvider = Provider.autoDispose
    .family<AsyncValue<SenderScheduleChange?>, int>((ref, dealId) {
      return _projectLiveQuery(
        ref,
        _dealScheduleChangeQuery((
          accountId: _watchAccountId(ref),
          argument: dealId,
        )),
      );
    });

/// The traveler's own changes on a journey, newest first.
final _journeyScheduleChangesQuery = FutureProvider.autoDispose
    .family<List<ScheduleChange>, _AccountArgument<int>>((ref, key) async {
      final repo = ref.watch(journeyRepositoryProvider);
      return _liveRead(
        ref,
        key.accountId,
        LiveResource.journey(key.argument),
        (cancel) => repo.scheduleChanges(key.argument, cancelToken: cancel),
      );
    }, retry: (_, _) => null);
final journeyScheduleChangesProvider = Provider.autoDispose
    .family<AsyncValue<List<ScheduleChange>>, int>((ref, journeyId) {
      return _projectLiveQuery(
        ref,
        _journeyScheduleChangesQuery((
          accountId: _watchAccountId(ref),
          argument: journeyId,
        )),
      );
    });

final _matchesQuery = FutureProvider.autoDispose.family<List<Match>, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(matchingRepositoryProvider);
  return _liveRead(
    ref,
    accountId,
    const LiveResource.matches(),
    (cancel) => repo.matches(cancelToken: cancel),
  );
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
        (cancel) => repo.match(key.argument, cancelToken: cancel),
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
        (cancel) => repo.offers(key.argument, cancelToken: cancel),
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
        (cancel) => repo.threads(cancelToken: cancel),
        guest: const [],
      );
    });
final chatThreadsProvider = Provider.autoDispose<AsyncValue<List<ChatThread>>>(
  (ref) => _projectLiveQuery(ref, _chatThreadsQuery(_watchAccountId(ref))),
);

/// Both badge numbers come from one endpoint, so they come from one read. Two
/// queries used to read it once each, side by side, every time the inbox was
/// open and on every catch-up (K5).
final _badgeCountsQuery = FutureProvider.autoDispose.family<BadgeCounts, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(notificationRepositoryProvider);
  return _liveRead(
    ref,
    accountId,
    const LiveResource.unread(),
    (cancel) => repo.badgeCounts(cancelToken: cancel),
  );
});

AsyncValue<int> _projectBadge(Ref ref, int Function(BadgeCounts) count) =>
    _projectLiveQuery(
      ref,
      _badgeCountsQuery(_watchAccountId(ref)),
    ).whenData(count);

/// The bell count — notifications that still need attention, not unread ones.
final unreadNotificationsProvider = Provider.autoDispose<AsyncValue<int>>(
  (ref) => _projectBadge(ref, (counts) => counts.active),
);

/// Active notifications the user has not opened. Gates "Mark all read", which
/// the badge total must not: a fully-read inbox can still be full of live
/// actions, and offering to mark them read there does nothing the user can see.
final unreadActiveNotificationsProvider = Provider.autoDispose<AsyncValue<int>>(
  (ref) => _projectBadge(ref, (counts) => counts.unreadActive),
);

final _payoutsQuery = FutureProvider.autoDispose.family<List<Payout>, int?>((
  ref,
  accountId,
) async {
  final repo = ref.watch(paymentRepositoryProvider);
  return _liveRead(
    ref,
    accountId,
    const LiveResource.payouts(),
    (cancel) => repo.payouts(cancelToken: cancel),
  );
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
        (cancel) => repo.payoutMethods(cancelToken: cancel),
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
        (cancel) => repo.payoutHistoryPaginated(
          page: 1,
          pageSize: 50,
          cancelToken: cancel,
        ),
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
      final payout = await repo.payoutDetail(
        key.reference,
        cancelToken: cancelOnDispose(ref),
      );
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
      final ratings = await repo.received(cancelToken: cancelOnDispose(ref));
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

final _ownRatingSummaryQuery = FutureProvider.autoDispose
    .family<TravelerRating, AccountSession>((ref, session) async {
      final repo = ref.watch(ratingRepositoryProvider);
      final summary = await repo.ownSummary(cancelToken: cancelOnDispose(ref));
      if (ref.read(accountSessionProvider) != session) {
        throw const _StaleSessionRead();
      }
      return summary;
    });

/// My own rating as the server states it (the figure on my public card).
/// Nothing on the phone averages anything.
final ownRatingSummaryProvider =
    Provider.autoDispose<AsyncValue<TravelerRating>>((ref) {
      final session = ref.watch(accountSessionProvider);
      if (session == null) {
        return const AsyncData<TravelerRating>(
          TravelerRating(state: TravelerRatingState.unrated, count: 0),
        );
      }
      return _projectLiveQuery(ref, _ownRatingSummaryQuery(session));
    });

/// The support address, or null while the server has none. No sign-in is
/// needed to read it. Every support action hides on null; a failed read hides
/// them too, rather than showing a button that goes nowhere.
final supportEmailProvider = FutureProvider.autoDispose<String?>((ref) {
  return ref
      .watch(supportRepositoryProvider)
      .email(cancelToken: cancelOnDispose(ref));
});

/// Re-reads both the list of ratings I received and the figure that sums them.
void refreshOwnRatings(WidgetRef ref) {
  ref
    ..invalidate(receivedRatingsProvider)
    ..invalidate(ownRatingSummaryProvider);
}

final paymentProvidersProvider = FutureProvider.autoDispose<ProvidersView>((
  ref,
) async {
  final repo = ref.watch(paymentRepositoryProvider);
  return repo.providers(cancelToken: cancelOnDispose(ref));
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
/// Reads the current Deal list, whose rows carry the server's `attention`
/// flags — the same answers the detail's `handover` and `ratings` blocks give.
/// It used to watch every Deal's *detail* to read them, which fetched one
/// detail per Deal on every Home load (K5); nothing here decides anything the
/// server did not state.
final attentionProvider = Provider.autoDispose<List<AttentionItem>>((ref) {
  // The id is all this reads, so a profile refresh — every resume — does not
  // rebuild the list and everything that shows it (K5).
  final accountId = _watchAccountId(ref);
  if (accountId == null) return const [];

  final items = <AttentionItem>[];

  for (final match in ref.watch(matchesProvider).value ?? const []) {
    if (match.awaitsViewer(accountId)) {
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

  for (final deal in ref.watch(currentDealsProvider).value ?? const []) {
    final isSender = deal.isSender(accountId);

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

    final flags = deal.attention;
    if (flags == null) continue;
    final handoverReason = flags.canRevealDeliveryCode
        ? AttentionReason.revealDeliveryCode
        : flags.canSubmitDeliveryCode
        ? AttentionReason.submitDeliveryCode
        : flags.canSubmitPickupCode
        ? AttentionReason.submitPickupCode
        : flags.canRevealPickupCode
        ? AttentionReason.revealPickupCode
        : null;
    if (handoverReason != null) {
      items.add(AttentionItem(reason: handoverReason, dealId: deal.id));
    }
    if (flags.canRate) {
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

  /// How recent a profile read must be for the first `resumed` after a launch
  /// in an unknown state to skip its own.
  static const _launchReadCovers = Duration(seconds: 30);

  DateTime? _leftAt;

  /// Built before the platform reported any on-screen state. An iOS
  /// background launch reports none, so the first `resumed` may be the first
  /// real open, long after the launch read the profile.
  bool _launchStateUnknown = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Built while off screen (a launch in the background): the first
    // `resumed` is then a real return, not the launch.
    switch (WidgetsBinding.instance.lifecycleState) {
      case AppLifecycleState.hidden:
      case AppLifecycleState.paused:
      case AppLifecycleState.detached:
        _leftAt = DateTime.now();
      case null:
        _launchStateUnknown = true;
      case AppLifecycleState.resumed:
      case AppLifecycleState.inactive:
        break;
    }
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
        // The first departure, not the latest: a device returns through
        // `paused → hidden → inactive → resumed`, and restamping on that
        // `hidden` made every real absence look a few milliseconds long, so
        // the profile was never re-read on a phone.
        _leftAt ??= DateTime.now();
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
    final firstAfterUnknownLaunch = _launchStateUnknown;
    _launchStateUnknown = false;

    if (away == null) {
      // No `hidden`/`paused` before this `resumed`: an `inactive` flicker (the
      // notification shade, the app switcher) or the launch itself, where the
      // session restore is already reading the profile. Neither is a
      // departure — unless the launch was in the background and this is the
      // first open, which only the age of the last profile read can tell.
      if (!firstAfterUnknownLaunch ||
          ref
              .read(sessionProvider.notifier)
              .accountReadWithin(_launchReadCovers)) {
        return;
      }
    } else if (DateTime.now().difference(away) < _ignoreShorterThan) {
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
    ..invalidate(currentDealsProvider)
    ..invalidate(dealHistoryProvider)
    ..invalidate(completedDealsCountProvider)
    ..invalidate(dealDetailProvider)
    ..invalidate(dealProblemsProvider)
    ..invalidate(dealScheduleChangeProvider)
    ..invalidate(journeyScheduleChangesProvider)
    ..invalidate(matchesProvider)
    ..invalidate(matchDetailProvider)
    ..invalidate(matchOffersProvider)
    ..invalidate(myRequestsProvider)
    ..invalidate(requestDetailProvider)
    ..invalidate(myJourneysProvider)
    ..invalidate(journeyDetailProvider)
    ..invalidate(journeyProgressProvider)
    ..invalidate(pendingProgressProvider)
    ..invalidate(chatThreadsProvider)
    ..invalidate(unreadNotificationsProvider)
    ..invalidate(postingDepositProvider)
    ..invalidate(payoutsProvider)
    ..invalidate(payoutHistoryProvider)
    ..invalidate(payoutMethodsProvider);
}
