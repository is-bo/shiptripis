/// Read models for public discovery.
///
/// Every provider here is a projection of what `/api/discovery/*` answered; none
/// decides who is listed, matched or hidden. Three properties matter:
///
/// * **Each section loads on its own.** Home watches these providers from
///   separate widgets, so one failing, or one switched off, never blanks the
///   page, and a section scrolled far below the fold does not read until it is
///   near the screen.
/// * **They are `autoDispose` and tied to the signed-in session.** A listing
///   goes stale the moment the app is backgrounded, and the previous account's
///   cards must never survive a sign-out. Watching [accountSessionProvider]
///   rebuilds each of them and cancels its read. A rebuild keeps the previous
///   value in Riverpod, so every reader goes through
///   [AccountScopedValue.ofCurrentAccount], which drops it; and signed out, no
///   read starts at all.
/// * **Lists page on the server's own cursor.** [FeedController] sends the
///   `next_offset` it was given and nothing else, and drops a row it already
///   holds, so an item that moved between two pages cannot show twice.
library;

import 'dart:async';

import 'package:dio/dio.dart' show CancelToken;
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/session/session.dart';
import '../data/discovery_repository.dart';
import '../domain/public_discovery.dart';
import 'app_state.dart';

/// A read that has nobody to ask for. Signed out there is no account to read
/// on behalf of, so nothing is sent and nothing ever answers; the screens that
/// showed these reads are gone by then.
Future<T> _signedOut<T>() => Completer<T>().future;

/// What a discovery read holds for the account that is signed in now.
extension AccountScopedValue<T> on AsyncValue<T> {
  /// Riverpod keeps the previous value while a provider rebuilds because a
  /// dependency changed, and the dependency here is the signed-in account. That
  /// value is the previous account's, so it is dropped: a card read for one
  /// member is never shown to the next. A refresh by `invalidate` is not a
  /// reload and keeps its value, which is what lets a failed pull to refresh
  /// say "showing what we loaded earlier".
  AsyncValue<T> get ofCurrentAccount => isReloading ? unwrapPrevious() : this;
}

/// How many cards a Home section shows before "See all".
const homeListingsPreviewCount = 5;
const homePeoplePreviewCount = 10;

// ---------------------------------------------------------------------------
// Home sections
// ---------------------------------------------------------------------------

final senderMatchesProvider =
    FutureProvider.autoDispose<MatchesForYou<SenderMatchGroup>>((ref) {
      if (ref.watch(accountSessionProvider) == null) return _signedOut();
      return ref
          .watch(discoveryRepositoryProvider)
          .senderMatches(cancelToken: cancelOnDispose(ref));
    });

final travelerMatchesProvider =
    FutureProvider.autoDispose<MatchesForYou<TravelerMatchGroup>>((ref) {
      if (ref.watch(accountSessionProvider) == null) return _signedOut();
      return ref
          .watch(discoveryRepositoryProvider)
          .travelerMatches(cancelToken: cancelOnDispose(ref));
    });

/// "Trips leaving soon", optionally narrowed to one corridor.
final previewTripsProvider = FutureProvider.autoDispose
    .family<DiscoveryPage<TripCard>, Corridor?>((ref, corridor) {
      if (ref.watch(accountSessionProvider) == null) return _signedOut();
      return ref
          .watch(discoveryRepositoryProvider)
          .trips(
            filter: corridor?.filter ?? const BrowseFilter(),
            limit: homeListingsPreviewCount,
            cancelToken: cancelOnDispose(ref),
          );
    });

/// "Parcels looking for a traveler", optionally narrowed to one corridor.
final previewRequestsProvider = FutureProvider.autoDispose
    .family<DiscoveryPage<RequestCard>, Corridor?>((ref, corridor) {
      if (ref.watch(accountSessionProvider) == null) return _signedOut();
      return ref
          .watch(discoveryRepositoryProvider)
          .requests(
            filter: corridor?.filter ?? const BrowseFilter(),
            limit: homeListingsPreviewCount,
            cancelToken: cancelOnDispose(ref),
          );
    });

/// The People row. Keyed by the **viewer's** side: a sender sees travelers.
final previewPeopleProvider = FutureProvider.autoDispose
    .family<DiscoveryPage<ProfileCard>, bool>((ref, viewerIsSender) {
      if (ref.watch(accountSessionProvider) == null) return _signedOut();
      return ref
          .watch(discoveryRepositoryProvider)
          .people(
            viewerIsSender: viewerIsSender,
            limit: homePeoplePreviewCount,
            cancelToken: cancelOnDispose(ref),
          );
    });

/// Drops every discovery read, so a pull to refresh re-reads each Home
/// section. The own profile is left alone: a refresh must not re-ask a member
/// who is half-way through editing it.
void refreshDiscovery(WidgetRef ref) {
  ref
    ..invalidate(senderMatchesProvider)
    ..invalidate(travelerMatchesProvider)
    ..invalidate(previewTripsProvider)
    ..invalidate(previewRequestsProvider)
    ..invalidate(previewPeopleProvider)
    ..invalidate(ownProfileProvider);
}

// ---------------------------------------------------------------------------
// My own profile and alerts
// ---------------------------------------------------------------------------

/// The member's own public profile: the opt-in card on Home, the Public
/// profile screen and its live preview all read this one object.
///
/// A write replaces the state with the server's answer. The preview is
/// therefore always the card the server would publish, never a local
/// reconstruction of it.
class OwnProfileController extends AsyncNotifier<OwnProfile> {
  @override
  Future<OwnProfile> build() {
    if (ref.watch(accountSessionProvider) == null) return _signedOut();
    return ref
        .watch(discoveryRepositoryProvider)
        .ownProfile(cancelToken: cancelOnDispose(ref));
  }

  /// Turns the profile on or off. Turning it on records consent on the server.
  Future<void> setDiscoverable(bool value) =>
      _apply((repo) => repo.updateOwnProfile(isDiscoverable: value));

  /// "Not now" on the Home card. Never blocks anything.
  Future<void> dismissPrompt() =>
      _apply((repo) => repo.updateOwnProfile(promptDismissed: true));

  Future<void> setUsualRoutes(
    List<({int originPlaceId, int destinationPlaceId})> routes,
  ) => _apply((repo) => repo.updateOwnProfile(usualRoutes: routes));

  Future<void> _apply(
    Future<OwnProfile> Function(DiscoveryRepository repo) write,
  ) async {
    final next = await write(ref.read(discoveryRepositoryProvider));
    state = AsyncData(next);
  }
}

final ownProfileProvider =
    AsyncNotifierProvider.autoDispose<OwnProfileController, OwnProfile>(
      OwnProfileController.new,
    );

final routeAlertsProvider = FutureProvider.autoDispose<List<RouteAlert>>((ref) {
  if (ref.watch(accountSessionProvider) == null) return _signedOut();
  return ref
      .watch(discoveryRepositoryProvider)
      .alerts(cancelToken: cancelOnDispose(ref));
});

/// One person's public page.
final personProvider = FutureProvider.autoDispose.family<PersonLookup, String>((
  ref,
  id,
) {
  if (ref.watch(accountSessionProvider) == null) return _signedOut();
  return ref
      .watch(discoveryRepositoryProvider)
      .person(id, cancelToken: cancelOnDispose(ref));
});

// ---------------------------------------------------------------------------
// Paged lists
// ---------------------------------------------------------------------------

/// The rows read so far, and where the server says the next page starts.
@immutable
class DiscoveryFeed<T> {
  const DiscoveryFeed({
    this.items = const [],
    this.nextOffset,
    this.disabled = false,
    this.loadingMore = false,
    this.loadMoreError,
  });

  final List<T> items;
  final int? nextOffset;

  /// The tier is switched off by staff: show "not available", not an error.
  final bool disabled;
  final bool loadingMore;

  /// Why the last next-page read failed, until the next attempt starts.
  final Object? loadMoreError;

  bool get hasMore => nextOffset != null;

  DiscoveryFeed<T> copyWith({
    List<T>? items,
    int? nextOffset,
    bool? loadingMore,
    Object? loadMoreError,
    bool clearNext = false,
    bool clearError = false,
  }) => DiscoveryFeed(
    items: items ?? this.items,
    nextOffset: clearNext ? null : (nextOffset ?? this.nextOffset),
    disabled: disabled,
    loadingMore: loadingMore ?? this.loadingMore,
    loadMoreError: clearError ? null : (loadMoreError ?? this.loadMoreError),
  );
}

/// A discovery list that pages forward on the server's cursor.
abstract class FeedController<T> extends AsyncNotifier<DiscoveryFeed<T>> {
  int _generation = 0;
  CancelToken? _more;

  Future<DiscoveryPage<T>> fetch(
    DiscoveryRepository repo,
    int offset,
    CancelToken cancel,
  );

  /// Identity of a row, so a row that moved between pages is shown once.
  Object keyOf(T item);

  @override
  Future<DiscoveryFeed<T>> build() async {
    final generation = ++_generation;
    final signedIn = ref.watch(accountSessionProvider) != null;
    ref.onDispose(() {
      _generation++;
      _more?.cancel();
    });
    if (!signedIn) return _signedOut();
    final page = await fetch(
      ref.watch(discoveryRepositoryProvider),
      0,
      cancelOnDispose(ref),
    );
    if (generation != _generation) throw const _SupersededRead();
    return DiscoveryFeed(
      items: page.results,
      nextOffset: page.nextOffset,
      disabled: page.isDisabled,
    );
  }

  /// Reads the next page. A no-op while one is in flight, when the server said
  /// there is nothing more, or before the first page landed.
  Future<void> loadMore() async {
    final current = state.value;
    final offset = current?.nextOffset;
    if (current == null || offset == null || current.loadingMore) return;
    final generation = _generation;
    _more?.cancel();
    final cancel = _more = CancelToken();
    state = AsyncData(current.copyWith(loadingMore: true, clearError: true));
    try {
      final page = await fetch(
        ref.read(discoveryRepositoryProvider),
        offset,
        cancel,
      );
      if (generation != _generation) return;
      final seen = {for (final item in current.items) keyOf(item)};
      state = AsyncData(
        current.copyWith(
          items: [
            ...current.items,
            ...page.results.where((item) => seen.add(keyOf(item))),
          ],
          nextOffset: page.nextOffset,
          clearNext: page.nextOffset == null,
          loadingMore: false,
          clearError: true,
        ),
      );
    } on Object catch (error) {
      if (generation != _generation) return;
      state = AsyncData(
        current.copyWith(loadingMore: false, loadMoreError: error),
      );
    }
  }
}

class _SupersededRead implements Exception {
  const _SupersededRead();
}

class TripFeedController extends FeedController<TripCard> {
  TripFeedController(this.filter);

  final BrowseFilter filter;

  @override
  Future<DiscoveryPage<TripCard>> fetch(
    DiscoveryRepository repo,
    int offset,
    CancelToken cancel,
  ) => repo.trips(filter: filter, offset: offset, cancelToken: cancel);

  @override
  Object keyOf(TripCard item) => item.journeyId;
}

class RequestFeedController extends FeedController<RequestCard> {
  RequestFeedController(this.filter);

  final BrowseFilter filter;

  @override
  Future<DiscoveryPage<RequestCard>> fetch(
    DiscoveryRepository repo,
    int offset,
    CancelToken cancel,
  ) => repo.requests(filter: filter, offset: offset, cancelToken: cancel);

  @override
  Object keyOf(RequestCard item) => item.requestId;
}

class PeopleFeedController extends FeedController<ProfileCard> {
  PeopleFeedController(this.viewerIsSender);

  final bool viewerIsSender;

  @override
  Future<DiscoveryPage<ProfileCard>> fetch(
    DiscoveryRepository repo,
    int offset,
    CancelToken cancel,
  ) => repo.people(
    viewerIsSender: viewerIsSender,
    offset: offset,
    cancelToken: cancel,
  );

  @override
  Object keyOf(ProfileCard item) => item.id ?? item.person.displayName;
}

final tripFeedProvider = AsyncNotifierProvider.autoDispose
    .family<TripFeedController, DiscoveryFeed<TripCard>, BrowseFilter>(
      TripFeedController.new,
    );

final requestFeedProvider = AsyncNotifierProvider.autoDispose
    .family<RequestFeedController, DiscoveryFeed<RequestCard>, BrowseFilter>(
      RequestFeedController.new,
    );

final peopleFeedProvider = AsyncNotifierProvider.autoDispose
    .family<PeopleFeedController, DiscoveryFeed<ProfileCard>, bool>(
      PeopleFeedController.new,
    );
