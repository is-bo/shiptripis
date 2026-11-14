/// Public discovery: Home's matches, Browse trips and requests, people, my own
/// profile, route alerts and "I can carry this".
///
/// Like every repository, thin: a path, a body, a parse. The contract is
/// `docs/PHASE_L2A_DISCOVERY_CONTRACT.md`. Every list is read at the server's
/// own `limit` and `next_offset`; nothing here ranks, filters or counts.
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_client.dart';
import '../core/session/session.dart';
import '../domain/json.dart';
import '../domain/public_discovery.dart';
import '../domain/reviews.dart';

/// Rows per Browse page. The server's default is 20 and its ceiling 50; 20
/// keeps each read small and the scroll lazy.
const browsePageSize = 20;

/// Reviews per page; the server's ceiling is 50.
const reviewsPageSize = 20;

class DiscoveryRepository {
  const DiscoveryRepository(this._api);

  final ApiClient _api;

  /// Home's "Matches for you". A sender gets one group per open request, a
  /// traveler one per discoverable journey; both are fan-ins over the existing
  /// matching engines, so a row here is a row on the screen it opens.
  Future<MatchesForYou<SenderMatchGroup>> senderMatches({
    CancelToken? cancelToken,
  }) async {
    final json = await _api.getObject(
      '/api/discovery/matches',
      query: {'role': 'sender'},
      cancelToken: cancelToken,
    );
    return MatchesForYou(
      state: MatchesState.parse(json['state']),
      groups: readObjectList(
        json['groups'],
      ).map(SenderMatchGroup.fromJson).toList(growable: false),
    );
  }

  Future<MatchesForYou<TravelerMatchGroup>> travelerMatches({
    CancelToken? cancelToken,
  }) async {
    final json = await _api.getObject(
      '/api/discovery/matches',
      query: {'role': 'traveler'},
      cancelToken: cancelToken,
    );
    return MatchesForYou(
      state: MatchesState.parse(json['state']),
      groups: readObjectList(
        json['groups'],
      ).map(TravelerMatchGroup.fromJson).toList(growable: false),
    );
  }

  /// Published trips, soonest departure first.
  Future<DiscoveryPage<TripCard>> trips({
    BrowseFilter filter = const BrowseFilter(),
    int limit = browsePageSize,
    int offset = 0,
    CancelToken? cancelToken,
  }) async => DiscoveryPage.fromJson(
    await _api.getObject(
      '/api/discovery/trips',
      query: _listQuery(filter, limit: limit, offset: offset),
      cancelToken: cancelToken,
    ),
    TripCard.fromJson,
  );

  /// Open requests, newest first.
  Future<DiscoveryPage<RequestCard>> requests({
    BrowseFilter filter = const BrowseFilter(),
    int limit = browsePageSize,
    int offset = 0,
    CancelToken? cancelToken,
  }) async => DiscoveryPage.fromJson(
    await _api.getObject(
      '/api/discovery/requests',
      query: _listQuery(filter, limit: limit, offset: offset),
      cancelToken: cancelToken,
    ),
    RequestCard.fromJson,
  );

  /// People who opted in. [viewerRole] is the **viewer's** role: a sender sees
  /// travelers and a traveler sees senders.
  Future<DiscoveryPage<ProfileCard>> people({
    required bool viewerIsSender,
    BrowseFilter filter = const BrowseFilter(),
    int limit = browsePageSize,
    int offset = 0,
    CancelToken? cancelToken,
  }) async => DiscoveryPage.fromJson(
    await _api.getObject(
      '/api/discovery/people',
      query: {
        'role': viewerIsSender ? 'sender' : 'traveler',
        'origin_place_id': ?filter.origin?.placeId,
        'destination_place_id': ?filter.destination?.placeId,
        'limit': limit,
        if (offset > 0) 'offset': offset,
      },
      cancelToken: cancelToken,
    ),
    ProfileCard.fromJson,
  );

  Future<PersonLookup> person(String id, {CancelToken? cancelToken}) async {
    final json = await _api.getObject(
      '/api/discovery/people/$id',
      cancelToken: cancelToken,
    );
    if (DiscoveryTierState.parse(json['state']) ==
        DiscoveryTierState.disabled) {
      return const PersonDisabled();
    }
    return PersonFound(PersonPage.fromJson(json));
  }

  /// One page of reviews, newest first. Only countable ratings come back, and
  /// no author, deal or tracking number; the server's `rating` summary is the
  /// number the card showed.
  Future<ReviewsPage> reviews(
    ReviewsSubject subject, {
    int limit = reviewsPageSize,
    int offset = 0,
    CancelToken? cancelToken,
  }) async {
    final (path, extra) = switch (subject) {
      PersonReviews(:final profileId) => (
        '/api/discovery/people/$profileId/reviews',
        const <String, dynamic>{},
      ),
      TripReviews(:final journeyId, :final requestId) => (
        '/api/discovery/trips/$journeyId/reviews',
        {'request': ?requestId},
      ),
    };
    return ReviewsPage.fromJson(
      await _api.getObject(
        path,
        query: {...extra, 'limit': limit, if (offset > 0) 'offset': offset},
        cancelToken: cancelToken,
      ),
    );
  }

  Future<OwnProfile> ownProfile({CancelToken? cancelToken}) async =>
      OwnProfile.fromJson(
        await _api.getObject(
          '/api/discovery/profile/me',
          cancelToken: cancelToken,
        ),
      );

  /// Changes only what is passed. [usualRoutes] replaces the list (at most
  /// three, order kept); `null` leaves it alone.
  Future<OwnProfile> updateOwnProfile({
    bool? isDiscoverable,
    List<({int originPlaceId, int destinationPlaceId})>? usualRoutes,
    bool? promptDismissed,
  }) async => OwnProfile.fromJson(
    await _api.putObject(
      '/api/discovery/profile/me',
      body: {
        'is_discoverable': ?isDiscoverable,
        if (usualRoutes != null)
          'usual_routes': [
            for (final route in usualRoutes)
              {
                'origin_place_id': route.originPlaceId,
                'destination_place_id': route.destinationPlaceId,
              },
          ],
        'prompt_dismissed': ?promptDismissed,
      },
    ),
  );

  Future<List<RouteAlert>> alerts({CancelToken? cancelToken}) async {
    final json = await _api.getObject(
      '/api/discovery/alerts',
      cancelToken: cancelToken,
    );
    return readObjectList(
      json['results'],
    ).map(RouteAlert.maybe).whereType<RouteAlert>().toList(growable: false);
  }

  /// Creates a route alert, or returns the identical active one. Following one
  /// person passes their profile id.
  Future<RouteAlert> createAlert({
    required AlertWatch watches,
    required int originPlaceId,
    required int destinationPlaceId,
    String? subjectProfileId,
  }) async {
    final json = await _api.postObject(
      '/api/discovery/alerts',
      body: {
        'watches': watches.wire,
        'origin_place_id': originPlaceId,
        'destination_place_id': destinationPlaceId,
        'subject_profile_id': ?subjectProfileId,
      },
    );
    final alert = RouteAlert.maybe(json);
    if (alert == null) {
      throw StateError('The alert answer carried no alert.');
    }
    return alert;
  }

  Future<void> deleteAlert(int id) =>
      _api.deleteVoid('/api/discovery/alerts/$id');

  /// "I can carry this". A signal, not an offer: no price, no match, no
  /// reservation. An incompatible pair is a `409 incompatible_candidate`.
  Future<InterestResult> sendInterest({
    required int requestId,
    required int journeyId,
  }) async => InterestResult.fromJson(
    await _api.postObject(
      '/api/discovery/requests/$requestId/interest',
      body: {'journey_id': journeyId},
    ),
  );

  static Map<String, dynamic> _listQuery(
    BrowseFilter filter, {
    required int limit,
    required int offset,
  }) => {
    'origin_country': ?filter.originCountry,
    'destination_country': ?filter.destinationCountry,
    'origin_place_id': ?filter.origin?.placeId,
    'destination_place_id': ?filter.destination?.placeId,
    if (filter.departingAfter != null)
      'departing_after': _startOfDay(filter.departingAfter!),
    'limit': limit,
    if (offset > 0) 'offset': offset,
  };

  /// A date filter means "from the start of that day". Sent as the UTC instant
  /// of the viewer's local midnight so the day the viewer picked is the day the
  /// server filters on, whatever their time zone.
  static String _startOfDay(DateTime day) =>
      DateTime(day.year, day.month, day.day).toUtc().toIso8601String();
}

final discoveryRepositoryProvider = Provider<DiscoveryRepository>(
  (ref) => DiscoveryRepository(ref.watch(apiClientProvider)),
);
