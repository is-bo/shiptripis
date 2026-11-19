/// Read models for public discovery.
///
/// Every provider here is a projection of what `/api/discovery/*` answered; none
/// decides who is listed, matched or hidden. Three properties matter:
///
/// * **Each section loads on its own.** Home watches these providers from
///   separate widgets, so one failing, or one switched off, never blanks the
///   page, and a section scrolled far below the fold does not read until it is
///   near the screen.
/// * **They are `autoDispose` and tied to who is looking.** A listing goes
///   stale the moment the app is backgrounded, and the previous account's
///   cards must never survive a sign-out. The public reads (listings, people,
///   a person, reviews) watch [discoveryAudienceProvider], a guest or one
///   member's sign-in; the personal ones (matches, the own profile, alerts)
///   watch [accountSessionProvider] and read nothing for a guest. A change
///   rebuilds each of them and cancels its read. A rebuild keeps the previous
///   value in Riverpod, even past a failed read, so every value and failure
///   is marked with whom it was read for and every reader goes through
///   [AccountScopedValue.ofCurrentAccount], which drops a value that is not
///   the current read's. A guest who signs
///   in is the one exception: their cards stay while each read is asked again
///   for the member, so the screen they signed in from stays as it was.
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
import '../domain/find_travelers.dart' show TravelerRating;
import '../domain/reviews.dart';
import 'app_state.dart';

/// A read that has nobody to ask for: a personal read for a guest, or any
/// read while the session is still being restored. Nothing is sent and
/// nothing ever answers.
Future<T> _signedOut<T>() => Completer<T>().future;

/// Who the public discovery reads are for, as their cache identity: a guest,
/// or one member's sign-in. Null while the session is being restored, when
/// nothing is read.
///
/// A member's sign-in ending, or another beginning, gives a new identity, so
/// nothing read for one viewer is shown to the next. A guest signing in keeps
/// the guest's identity: [_watchAudience] re-reads each listing for the new
/// member by refresh, so the cards and the screen under the account moment
/// stay mounted while it happens.
final discoveryAudienceProvider = NotifierProvider<DiscoveryAudience, Object?>(
  DiscoveryAudience.new,
);

class DiscoveryAudience extends Notifier<Object?> {
  Object? _audience;
  AccountSession? _member;

  @override
  Object? build() {
    final session = ref.watch(sessionProvider);
    final previous = _member;
    final member = _member = session is SessionSignedIn
        ? (accountId: session.account.id, generation: session.generation)
        : null;
    final fromGuest = previous == null && _audience is _Guest;
    return _audience = switch (session) {
      SessionRestoring() => null,
      SessionSignedOut() => fromGuest ? _audience : _Guest(),
      SessionSignedIn() =>
        fromGuest || (previous == member && _audience != null)
            ? _audience
            : member,
    };
  }
}

/// A guest's identity. Never const: each spell signed out is its own.
class _Guest {}

/// The audience of a public read, and a re-read when a guest signs in.
Object? _watchAudience(Ref ref) {
  ref.listen(accountSessionProvider, (previous, next) {
    if (previous == null && next != null) ref.invalidateSelf();
  });
  return ref.watch(discoveryAudienceProvider);
}

/// Whom each discovery value and failure was read for: the audience of a
/// public read, the account session of a personal one.
final _readFor = Expando<Object>('discovery reader');

/// [read], with its value or its failure marked as read for [reader].
Future<T> _readAs<T extends Object>(Object reader, Future<T> read) async {
  final T value;
  try {
    value = await read;
  } catch (error) {
    _mark(error, reader);
    rethrow;
  }
  return _mark(value, reader);
}

/// Marks [target] as read for [reader]; returns it.
T _mark<T>(T target, Object? reader) {
  if (_markable(target)) _readFor[target!] = reader;
  return target;
}

Object? _readerOf(Object? target) =>
    _markable(target) ? _readFor[target!] : null;

/// What an [Expando] can hold: no primitive, no record.
bool _markable(Object? target) =>
    target != null &&
    target is! num &&
    target is! String &&
    target is! bool &&
    target is! Record;

/// What a discovery read holds for the account that is signed in now.
extension AccountScopedValue<T> on AsyncValue<T> {
  /// Riverpod keeps the previous value while a provider rebuilds because a
  /// dependency changed, and the dependency here is who is looking. That
  /// value is the previous viewer's, so it is dropped: a card read for one
  /// member is never shown to a guest or to the next member. It is dropped
  /// too when that rebuild fails, since the failure keeps it as well: a value
  /// read for someone else than the failed read was is never shown over the
  /// failure. A refresh by `invalidate` reads for the same viewer and keeps
  /// its value, which is what lets a failed pull to refresh say "showing what
  /// we loaded earlier".
  AsyncValue<T> get ofCurrentAccount {
    if (isReloading) return unwrapPrevious();
    if (hasError && hasValue && _readerOf(error) != _readerOf(value)) {
      return AsyncError<T>(error!, stackTrace!);
    }
    return this;
  }
}

/// How many cards a Home section shows before "See all".
const homeListingsPreviewCount = 5;
const homePeoplePreviewCount = 10;

// ---------------------------------------------------------------------------
// Home sections
// ---------------------------------------------------------------------------

final senderMatchesProvider =
    FutureProvider.autoDispose<MatchesForYou<SenderMatchGroup>>((ref) {
      final account = ref.watch(accountSessionProvider);
      if (account == null) return _signedOut();
      return _readAs(
        account,
        ref
            .watch(discoveryRepositoryProvider)
            .senderMatches(cancelToken: cancelOnDispose(ref)),
      );
    });

final travelerMatchesProvider =
    FutureProvider.autoDispose<MatchesForYou<TravelerMatchGroup>>((ref) {
      final account = ref.watch(accountSessionProvider);
      if (account == null) return _signedOut();
      return _readAs(
        account,
        ref
            .watch(discoveryRepositoryProvider)
            .travelerMatches(cancelToken: cancelOnDispose(ref)),
      );
    });

/// "Trips leaving soon", optionally narrowed to one corridor.
final previewTripsProvider = FutureProvider.autoDispose
    .family<DiscoveryPage<TripCard>, Corridor?>((ref, corridor) {
      final audience = _watchAudience(ref);
      if (audience == null) return _signedOut();
      return _readAs(
        audience,
        ref
            .watch(discoveryRepositoryProvider)
            .trips(
              filter: corridor?.filter ?? const BrowseFilter(),
              limit: homeListingsPreviewCount,
              cancelToken: cancelOnDispose(ref),
            ),
      );
    });

/// "Parcels looking for a traveler", optionally narrowed to one corridor.
final previewRequestsProvider = FutureProvider.autoDispose
    .family<DiscoveryPage<RequestCard>, Corridor?>((ref, corridor) {
      final audience = _watchAudience(ref);
      if (audience == null) return _signedOut();
      return _readAs(
        audience,
        ref
            .watch(discoveryRepositoryProvider)
            .requests(
              filter: corridor?.filter ?? const BrowseFilter(),
              limit: homeListingsPreviewCount,
              cancelToken: cancelOnDispose(ref),
            ),
      );
    });

/// The People row. Keyed by the **viewer's** side: a sender sees travelers.
final previewPeopleProvider = FutureProvider.autoDispose
    .family<DiscoveryPage<ProfileCard>, bool>((ref, viewerIsSender) {
      final audience = _watchAudience(ref);
      if (audience == null) return _signedOut();
      return _readAs(
        audience,
        ref
            .watch(discoveryRepositoryProvider)
            .people(
              viewerIsSender: viewerIsSender,
              limit: homePeoplePreviewCount,
              cancelToken: cancelOnDispose(ref),
            ),
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
    final account = ref.watch(accountSessionProvider);
    if (account == null) return _signedOut();
    return _readAs(
      account,
      ref
          .watch(discoveryRepositoryProvider)
          .ownProfile(cancelToken: cancelOnDispose(ref)),
    );
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
    state = AsyncData(_mark(next, _readerOf(state.value)));
  }
}

final ownProfileProvider =
    AsyncNotifierProvider.autoDispose<OwnProfileController, OwnProfile>(
      OwnProfileController.new,
    );

/// The member's route alerts. A guest has none, and asks for none: their
/// switch on a person's page reads "off" and turning it on asks for an
/// account first.
final routeAlertsProvider = FutureProvider.autoDispose<List<RouteAlert>>((ref) {
  if (ref.watch(isGuestProvider)) return Future.value(const []);
  final account = ref.watch(accountSessionProvider);
  if (account == null) return _signedOut();
  return _readAs(
    account,
    ref
        .watch(discoveryRepositoryProvider)
        .alerts(cancelToken: cancelOnDispose(ref)),
  );
});

/// One person's public page.
final personProvider = FutureProvider.autoDispose.family<PersonLookup, String>((
  ref,
  id,
) {
  final audience = _watchAudience(ref);
  if (audience == null) return _signedOut();
  return _readAs(
    audience,
    ref
        .watch(discoveryRepositoryProvider)
        .person(id, cancelToken: cancelOnDispose(ref)),
  );
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
    final audience = _watchAudience(ref);
    ref.onDispose(() {
      _generation++;
      _more?.cancel();
    });
    if (audience == null) return _signedOut();
    return _readAs(
      audience,
      _firstPage(ref.watch(discoveryRepositoryProvider), generation),
    );
  }

  Future<DiscoveryFeed<T>> _firstPage(
    DiscoveryRepository repo,
    int generation,
  ) async {
    final page = await fetch(repo, 0, cancelOnDispose(ref));
    if (generation != _generation) throw _SupersededRead();
    return DiscoveryFeed(
      items: page.results,
      nextOffset: page.nextOffset,
      disabled: page.isDisabled,
    );
  }

  /// [next] in place of [current], read for the same viewer.
  void _replace(DiscoveryFeed<T> current, DiscoveryFeed<T> next) =>
      state = AsyncData(_mark(next, _readerOf(current)));

  /// Reads the next page. A no-op while one is in flight, when the server said
  /// there is nothing more, or before the first page landed.
  Future<void> loadMore() async {
    final current = state.value;
    final offset = current?.nextOffset;
    if (current == null || offset == null || current.loadingMore) return;
    final generation = _generation;
    _more?.cancel();
    final cancel = _more = CancelToken();
    _replace(current, current.copyWith(loadingMore: true, clearError: true));
    try {
      final page = await fetch(
        ref.read(discoveryRepositoryProvider),
        offset,
        cancel,
      );
      if (generation != _generation) return;
      final seen = {for (final item in current.items) keyOf(item)};
      _replace(
        current,
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
      _replace(
        current,
        current.copyWith(loadingMore: false, loadMoreError: error),
      );
    }
  }
}

/// Not const: each is marked with whom its read was for.
class _SupersededRead implements Exception {
  _SupersededRead();
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

/// The reviews of one person or trip, paged on the server's cursor.
///
/// The summary above the list is the `rating` the server sent with the first
/// page (the same number the card showed); it is never averaged here.
class ReviewsFeedController extends FeedController<PublicReview> {
  ReviewsFeedController(this.subject);

  final ReviewsSubject subject;

  /// The summary of the first page, or null while the tier is off.
  TravelerRating? rating;

  @override
  Future<DiscoveryPage<PublicReview>> fetch(
    DiscoveryRepository repo,
    int offset,
    CancelToken cancel,
  ) async {
    final page = await repo.reviews(
      subject,
      offset: offset,
      cancelToken: cancel,
    );
    if (offset == 0) rating = page.rating;
    return page;
  }

  @override
  Object keyOf(PublicReview item) => item.id;

  /// Marks one review as reported by this viewer, without a re-read.
  void markReported(int ratingId, MyReport report) {
    final current = state.value;
    if (current == null) return;
    _replace(
      current,
      current.copyWith(
        items: [
          for (final review in current.items)
            review.id == ratingId ? review.withReport(report) : review,
        ],
      ),
    );
  }
}

final reviewsFeedProvider = AsyncNotifierProvider.autoDispose
    .family<ReviewsFeedController, DiscoveryFeed<PublicReview>, ReviewsSubject>(
      ReviewsFeedController.new,
    );
