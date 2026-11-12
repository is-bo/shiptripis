/// Public discovery: listings, people, alerts and "I can carry this".
///
/// The contract is `docs/PHASE_L2A_DISCOVERY_CONTRACT.md`. Everything here is
/// a **server card**, rendered. A card is built on the server from an
/// allowlist, so this file only reads the keys the contract names: there is no
/// surname, phone, street, coordinate, recipient or internal user id to parse,
/// and none is invented. Matching, ordering, listing rules and the daily cap
/// live in Django; nothing in this file decides who is shown.
///
/// Two decoding rules, both learned from earlier contracts:
///
/// * **A closed vocabulary degrades, it does not throw.** An unknown tier
///   state, capacity band or leg mode parses to `unknown`, so one new server
///   value costs one badge rather than the whole section.
/// * **A tier that is switched off is a state, not an error.** The server
///   answers HTTP 200 with `state: "disabled"`; [DiscoveryTierState.disabled]
///   lets Home omit the section instead of showing a failure.
library;

import '../core/money/money.dart';
import 'canonical_place.dart';
import 'delivery_request.dart' show ItemCategory;
import 'discovery.dart';
import 'find_travelers.dart';
import 'journey.dart' show JourneyPrice;
import 'json.dart';
import 'transport_mode.dart';

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

/// What a whole tier is, before any row is read.
enum DiscoveryTierState {
  results,
  empty,

  /// Switched off by staff policy. The section is absent, not an error.
  disabled,
  unknown;

  static DiscoveryTierState parse(Object? raw) => readEnum(
    raw,
    DiscoveryTierState.values,
    fallback: DiscoveryTierState.unknown,
  );
}

/// One page of a discovery list.
///
/// [nextOffset] is the server's own cursor. The client never computes the next
/// offset from the number of rows it holds, so a page that came back short for
/// a server-side reason cannot make it skip or repeat rows.
class DiscoveryPage<T> {
  const DiscoveryPage({
    required this.state,
    required this.results,
    this.nextOffset,
  });

  factory DiscoveryPage.fromJson(
    Map<String, dynamic> json,
    T Function(Map<String, dynamic> row) parse,
  ) => DiscoveryPage(
    state: DiscoveryTierState.parse(json['state']),
    results: readObjectList(json['results']).map(parse).toList(growable: false),
    nextOffset: readInt(json['next_offset']),
  );

  final DiscoveryTierState state;
  final List<T> results;
  final int? nextOffset;

  bool get isDisabled => state == DiscoveryTierState.disabled;
  bool get hasMore => nextOffset != null;
}

// ---------------------------------------------------------------------------
// Places and people
// ---------------------------------------------------------------------------

/// A city as discovery publishes it: catalogue id, label and country. Never a
/// coordinate, a street or an airport's own name.
class PlaceRef {
  const PlaceRef({
    required this.placeId,
    required this.label,
    required this.countryCode,
  });

  static PlaceRef? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final id = readInt(json['place_id']);
    if (id == null) return null;
    return PlaceRef(
      placeId: id,
      label: readText(json['label']),
      countryCode: readText(json['country_code']).toUpperCase(),
    );
  }

  /// A city picked in the place picker. An airport stands for the city the
  /// catalogue says it serves, because discovery speaks in cities only.
  factory PlaceRef.fromCanonical(CanonicalPlace place) => PlaceRef(
    placeId: place.matchingLocalityId ?? place.id,
    label: place.isAirport
        ? (place.matchingLocalityName ?? place.name)
        : place.name,
    countryCode: place.countryCode.toUpperCase(),
  );

  final int placeId;
  final String label;
  final String countryCode;

  /// This city as the catalogue place a request form takes.
  ///
  /// Discovery publishes cities at locality level, and a locality is its own
  /// matching locality, so this is the same identity the form would get from
  /// picking the city by hand. Used to pre-fill the route of a trip.
  CanonicalPlace toLocality() => CanonicalPlace(
    id: placeId,
    countryCode: countryCode,
    type: CanonicalPlaceType.locality,
    name: label,
    displayLabel: label,
    parentName: '',
    parentAdminLevel: '',
    matchingLocalityId: placeId,
  );
}

/// The summary of a person on a card: first name, whether their identity is
/// verified, and the same trust summary Find Travelers shows.
///
/// [rating] is null for somebody with no revealed rating, and the UI must show
/// "New" rather than a number for it.
class PublicPerson {
  const PublicPerson({
    required this.displayName,
    this.identityVerified = false,
    this.rating,
    this.completedDeliveries = 0,
  });

  factory PublicPerson.fromJson(Map<String, dynamic> json) => PublicPerson(
    displayName: readText(json['display_name']),
    identityVerified: readBool(json['identity_verified']),
    rating: readDouble(json['rating']),
    completedDeliveries: readInt(json['completed_deliveries']) ?? 0,
  );

  final String displayName;
  final bool identityVerified;
  final double? rating;
  final int completedDeliveries;

  bool get hasRating => rating != null;
}

/// A route a member chose to show on their profile, as a pair of cities.
class UsualRoute {
  const UsualRoute({required this.origin, required this.destination});

  static UsualRoute? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final origin = PlaceRef.maybe(json['origin']);
    final destination = PlaceRef.maybe(json['destination']);
    if (origin == null || destination == null) return null;
    return UsualRoute(origin: origin, destination: destination);
  }

  final PlaceRef origin;
  final PlaceRef destination;
}

List<UsualRoute> _usualRoutes(Object? raw) => raw is List
    ? raw.map(UsualRoute.maybe).whereType<UsualRoute>().toList(growable: false)
    : const [];

/// A public profile card — exactly what others see, and what the owner
/// previews of themselves.
class ProfileCard {
  const ProfileCard({
    required this.person,
    required this.usualRoutes,
    this.id,
    this.memberSince,
  });

  factory ProfileCard.fromJson(Map<String, dynamic> json) => ProfileCard(
    id: readString(json['id']),
    person: PublicPerson.fromJson(json),
    memberSince: _yearMonth(readString(json['member_since'])),
    usualRoutes: _usualRoutes(json['usual_routes']),
  );

  /// The opaque public id used to open the person page. Null on a card that
  /// has never been saved (the off-by-default answer for the owner).
  final String? id;
  final PublicPerson person;

  /// First of the month the member joined; only the month and year are shown.
  final DateTime? memberSince;
  final List<UsualRoute> usualRoutes;
}

DateTime? _yearMonth(String? raw) {
  if (raw == null) return null;
  final parts = raw.split('-');
  if (parts.length != 2) return null;
  final year = int.tryParse(parts[0]);
  final month = int.tryParse(parts[1]);
  if (year == null || month == null || month < 1 || month > 12) return null;
  return DateTime(year, month);
}

// ---------------------------------------------------------------------------
// Listings
// ---------------------------------------------------------------------------

/// The remaining weight capacity, as the server's public band.
enum CapacityBand {
  under5kg,
  fiveToTenKg,
  tenToTwentyKg,
  twentyKgPlus,
  unknown;

  static CapacityBand parse(Object? raw) => switch (readString(raw)) {
    'under_5kg' => under5kg,
    '5_to_10kg' => fiveToTenKg,
    '10_to_20kg' => tenToTwentyKg,
    '20kg_plus' => twentyKgPlus,
    _ => unknown,
  };
}

class TripLeg {
  const TripLeg({required this.mode, this.departAt, this.arriveAt});

  factory TripLeg.fromJson(Map<String, dynamic> json) => TripLeg(
    mode: TransportMode.parse(json['mode']),
    departAt: readDate(json['depart_at']),
    arriveAt: readDate(json['arrive_at']),
  );

  final TransportMode mode;
  final DateTime? departAt;
  final DateTime? arriveAt;
}

/// A published trip as a sender sees it in Browse trips.
class TripCard {
  const TripCard({
    required this.journeyId,
    required this.traveler,
    required this.stops,
    required this.legs,
    required this.capacityBand,
    this.departsAt,
    this.nextDepartureAt,
    this.arrivesAt,
    this.price,
  });

  factory TripCard.fromJson(Map<String, dynamic> json) => TripCard(
    journeyId: readInt(json['journey_id']) ?? 0,
    traveler: PublicPerson.fromJson(readObject(json['traveler']) ?? const {}),
    stops: readObjectList(
      json['stops'],
    ).map(PlaceRef.maybe).whereType<PlaceRef>().toList(growable: false),
    legs: readObjectList(
      json['legs'],
    ).map(TripLeg.fromJson).toList(growable: false),
    departsAt: readDate(json['departs_at']),
    nextDepartureAt: readDate(json['next_departure_at']),
    arrivesAt: readDate(json['arrives_at']),
    capacityBand: CapacityBand.parse(json['capacity_band']),
    price: JourneyPrice.maybe(json['price']),
  );

  final int journeyId;
  final PublicPerson traveler;

  /// Ordered cities, at locality level.
  final List<PlaceRef> stops;
  final List<TripLeg> legs;
  final DateTime? departsAt;

  /// The next leg that has not left yet. What a sender should read as "when".
  final DateTime? nextDepartureAt;
  final DateTime? arrivesAt;
  final CapacityBand capacityBand;

  /// What the traveller charges, or null. A card is about no parcel in
  /// particular, so this is the price itself and never a total for a parcel.
  final JourneyPrice? price;

  /// The distinct leg modes in travel order, unknown ones dropped.
  List<TransportMode> get modes => legs
      .map((leg) => leg.mode)
      .where((mode) => mode != TransportMode.unknown)
      .toSet()
      .toList(growable: false);
}

/// An open request as a traveler sees it in Browse requests.
class RequestCard {
  const RequestCard({
    required this.requestId,
    required this.sender,
    required this.title,
    required this.category,
    required this.fragile,
    required this.totalOfferedReward,
    this.pickup,
    this.delivery,
    this.weightKg,
    this.readyWindowStart,
    this.readyWindowEnd,
    this.deadlineAt,
    this.boost,
  });

  factory RequestCard.fromJson(Map<String, dynamic> json) => RequestCard(
    requestId: readInt(json['request_id']) ?? 0,
    sender: readText(readObject(json['sender'])?['display_name']),
    pickup: PlaceRef.maybe(json['pickup']),
    delivery: PlaceRef.maybe(json['delivery']),
    title: readText(json['title']),
    category: readEnum(
      json['category'],
      ItemCategory.values,
      fallback: ItemCategory.unknown,
    ),
    fragile: readBool(json['fragile']),
    weightKg: readDouble(json['weight_kg']),
    readyWindowStart: readDate(json['ready_window_start']),
    readyWindowEnd: readDate(json['ready_window_end']),
    deadlineAt: readDate(json['deadline_at']),
    boost: Money.eurCentsOrNull(json['boost_eur_cents']),
    totalOfferedReward: Money.eurCentsOrNull(
      json['total_offered_reward_eur_cents'],
    ),
  );

  final int requestId;
  final String sender;
  final PlaceRef? pickup;
  final PlaceRef? delivery;
  final String title;
  final ItemCategory category;
  final bool fragile;
  final double? weightKg;
  final DateTime? readyWindowStart;
  final DateTime? readyWindowEnd;
  final DateTime? deadlineAt;

  /// The Boost inside [totalOfferedReward], when there is one.
  final Money? boost;

  /// What the sender offers a traveler in total. The server states it; this
  /// class never adds reward and boost itself.
  final Money? totalOfferedReward;
}

// ---------------------------------------------------------------------------
// Matches for you
// ---------------------------------------------------------------------------

enum MatchesState {
  results,

  /// Active items exist but none has a compatible counterpart yet.
  none,

  /// Nothing to match: no open request, or no discoverable journey.
  noActiveItems,
  unknown;

  static MatchesState parse(Object? raw) => switch (readString(raw)) {
    'results' => results,
    'none' => none,
    'no_active_items' => noActiveItems,
    _ => unknown,
  };
}

/// One item of mine (a request or a journey) and the counterparts that fit it.
abstract interface class MatchGroup {
  bool get hasResults;
  bool get moreAvailable;
}

/// A sender's open request and the travelers who really fit it.
class SenderMatchGroup implements MatchGroup {
  const SenderMatchGroup({
    required this.requestId,
    required this.results,
    required this.moreAvailable,
    this.pickup,
    this.delivery,
    this.deadlineAt,
  });

  factory SenderMatchGroup.fromJson(Map<String, dynamic> json) {
    final request = readObject(json['request']) ?? const {};
    return SenderMatchGroup(
      requestId: readInt(request['id']) ?? 0,
      pickup: PlaceRef.maybe(request['pickup']),
      delivery: PlaceRef.maybe(request['delivery']),
      deadlineAt: readDate(request['deadline_at']),
      results: readObjectList(
        json['results'],
      ).map(TravelerCandidate.fromJson).toList(growable: false),
      moreAvailable: readBool(json['more_available']),
    );
  }

  final int requestId;
  final PlaceRef? pickup;
  final PlaceRef? delivery;
  final DateTime? deadlineAt;

  /// Exactly the first rows of Find Travelers for this request.
  final List<TravelerCandidate> results;
  @override
  final bool moreAvailable;

  @override
  bool get hasResults => results.isNotEmpty;
}

/// A traveler's journey and the requests that really fit it.
class TravelerMatchGroup implements MatchGroup {
  const TravelerMatchGroup({
    required this.journeyId,
    required this.results,
    required this.moreAvailable,
    this.origin,
    this.destination,
    this.nextDepartureAt,
  });

  factory TravelerMatchGroup.fromJson(Map<String, dynamic> json) {
    final journey = readObject(json['journey']) ?? const {};
    return TravelerMatchGroup(
      journeyId: readInt(journey['id']) ?? 0,
      origin: PlaceRef.maybe(journey['origin']),
      destination: PlaceRef.maybe(journey['destination']),
      nextDepartureAt: readDate(journey['next_departure_at']),
      results: readObjectList(
        json['results'],
      ).map(DiscoveryCandidate.fromJson).toList(growable: false),
      moreAvailable: readBool(json['more_available']),
    );
  }

  final int journeyId;
  final PlaceRef? origin;
  final PlaceRef? destination;
  final DateTime? nextDepartureAt;

  /// The first rows of the journey's compatible requests, in their public
  /// shape. There is no recommendation on them, by design.
  final List<DiscoveryCandidate> results;
  @override
  final bool moreAvailable;

  @override
  bool get hasResults => results.isNotEmpty;
}

class MatchesForYou<G extends MatchGroup> {
  const MatchesForYou({required this.state, required this.groups});

  final MatchesState state;
  final List<G> groups;

  /// Groups that have at least one result. Home shows only these; an item with
  /// nothing compatible yet is not padded out with filler.
  List<G> get withResults =>
      groups.where((group) => group.hasResults).toList(growable: false);
}

// ---------------------------------------------------------------------------
// Person page
// ---------------------------------------------------------------------------

class PersonPage {
  const PersonPage({
    required this.profile,
    required this.trips,
    required this.requests,
  });

  factory PersonPage.fromJson(Map<String, dynamic> json) => PersonPage(
    profile: ProfileCard.fromJson(readObject(json['profile']) ?? const {}),
    trips: readObjectList(
      json['trips'],
    ).map(TripCard.fromJson).toList(growable: false),
    requests: readObjectList(
      json['requests'],
    ).map(RequestCard.fromJson).toList(growable: false),
  );

  final ProfileCard profile;
  final List<TripCard> trips;
  final List<RequestCard> requests;
}

/// The person page answers `{"state": "disabled"}` while profiles are off.
sealed class PersonLookup {
  const PersonLookup();
}

class PersonFound extends PersonLookup {
  const PersonFound(this.page);
  final PersonPage page;
}

class PersonDisabled extends PersonLookup {
  const PersonDisabled();
}

// ---------------------------------------------------------------------------
// My own profile
// ---------------------------------------------------------------------------

enum OwnProfileState {
  visible,
  notVisible,

  /// Hidden by staff. The owner is told only that the profile is not
  /// currently visible; the reason is never sent.
  hidden,
  disabled,
  unknown;

  static OwnProfileState parse(Object? raw) => switch (readString(raw)) {
    'visible' => visible,
    'not_visible' => notVisible,
    'hidden' => hidden,
    'disabled' => disabled,
    _ => unknown,
  };
}

class OwnProfile {
  const OwnProfile({
    required this.state,
    required this.isDiscoverable,
    required this.showPrompt,
    required this.usualRoutes,
    required this.card,
  });

  factory OwnProfile.fromJson(Map<String, dynamic> json) => OwnProfile(
    state: OwnProfileState.parse(json['state']),
    isDiscoverable: readBool(json['is_discoverable']),
    showPrompt: readBool(json['show_prompt']),
    usualRoutes: _usualRoutes(json['usual_routes']),
    card: ProfileCard.fromJson(readObject(json['card']) ?? const {}),
  );

  final OwnProfileState state;
  final bool isDiscoverable;

  /// The one-time opt-in card on Home (spec 4.3). Server-decided.
  final bool showPrompt;
  final List<UsualRoute> usualRoutes;

  /// Exactly what others see.
  final ProfileCard card;
}

// ---------------------------------------------------------------------------
// Alerts and interest
// ---------------------------------------------------------------------------

enum AlertWatch {
  trips,
  requests;

  String get wire => name;

  static AlertWatch? maybe(Object? raw) => switch (readString(raw)) {
    'trips' => trips,
    'requests' => requests,
    _ => null,
  };
}

class RouteAlert {
  const RouteAlert({
    required this.id,
    required this.watches,
    required this.origin,
    required this.destination,
    this.subjectName,
    this.subjectProfileId,
    this.createdAt,
  });

  static RouteAlert? maybe(Map<String, dynamic> json) {
    final id = readInt(json['id']);
    final watches = AlertWatch.maybe(json['watches']);
    final origin = PlaceRef.maybe(json['origin']);
    final destination = PlaceRef.maybe(json['destination']);
    if (id == null ||
        watches == null ||
        origin == null ||
        destination == null) {
      return null;
    }
    final subject = readObject(json['subject']);
    return RouteAlert(
      id: id,
      watches: watches,
      origin: origin,
      destination: destination,
      subjectName: subject == null ? null : readString(subject['display_name']),
      subjectProfileId: subject == null ? null : readString(subject['id']),
      createdAt: readDate(json['created_at']),
    );
  }

  final int id;
  final AlertWatch watches;
  final PlaceRef origin;
  final PlaceRef destination;

  /// Set when the alert follows one person rather than a route.
  final String? subjectName;
  final String? subjectProfileId;
  final DateTime? createdAt;

  bool get followsPerson => subjectProfileId != null;
}

/// The answer to "I can carry this". The signal creates no match, no offer and
/// no reservation; [created] is false when the same signal already existed.
class InterestResult {
  const InterestResult({required this.created, this.sentAt});

  factory InterestResult.fromJson(Map<String, dynamic> json) => InterestResult(
    created: readBool(json['created']),
    sentAt: readDate(json['sent_at']),
  );

  final bool created;
  final DateTime? sentAt;
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

/// Route filters for Browse trips and Browse requests.
///
/// Value equality, because a filter is a Riverpod family key: two filters that
/// say the same thing must be the same provider.
class BrowseFilter {
  const BrowseFilter({
    this.originCountry,
    this.destinationCountry,
    this.origin,
    this.destination,
    this.departingAfter,
  });

  /// Corridor chips set the country pair; the pickers set a city.
  final String? originCountry;
  final String? destinationCountry;
  final PlaceRef? origin;
  final PlaceRef? destination;

  /// A calendar day, kept as a date so equal days are equal keys.
  final DateTime? departingAfter;

  bool get isEmpty =>
      originCountry == null &&
      destinationCountry == null &&
      origin == null &&
      destination == null &&
      departingAfter == null;

  BrowseFilter copyWith({
    PlaceRef? origin,
    PlaceRef? destination,
    DateTime? departingAfter,
    bool clearOrigin = false,
    bool clearDestination = false,
    bool clearDate = false,
    bool clearCountries = false,
  }) => BrowseFilter(
    originCountry: clearCountries ? null : originCountry,
    destinationCountry: clearCountries ? null : destinationCountry,
    origin: clearOrigin ? null : (origin ?? this.origin),
    destination: clearDestination ? null : (destination ?? this.destination),
    departingAfter: clearDate ? null : (departingAfter ?? this.departingAfter),
  );

  @override
  bool operator ==(Object other) =>
      other is BrowseFilter &&
      other.originCountry == originCountry &&
      other.destinationCountry == destinationCountry &&
      other.origin?.placeId == origin?.placeId &&
      other.destination?.placeId == destination?.placeId &&
      other.departingAfter == departingAfter;

  @override
  int get hashCode => Object.hash(
    originCountry,
    destinationCountry,
    origin?.placeId,
    destination?.placeId,
    departingAfter,
  );
}

/// A direction between the four launch countries, for the Home corridor chips.
///
/// Launch scope (spec 3) is Algeria, France, Spain and Germany, and the
/// product carries between Europe and Algeria, so a corridor is one European
/// country paired with Algeria, in either direction.
class Corridor {
  const Corridor(this.originCountry, this.destinationCountry);

  final String originCountry;
  final String destinationCountry;

  static const launchCorridors = <Corridor>[
    Corridor('FR', 'DZ'),
    Corridor('DZ', 'FR'),
    Corridor('ES', 'DZ'),
    Corridor('DZ', 'ES'),
    Corridor('DE', 'DZ'),
    Corridor('DZ', 'DE'),
  ];

  BrowseFilter get filter => BrowseFilter(
    originCountry: originCountry,
    destinationCountry: destinationCountry,
  );

  @override
  bool operator ==(Object other) =>
      other is Corridor &&
      other.originCountry == originCountry &&
      other.destinationCountry == destinationCountry;

  @override
  int get hashCode => Object.hash(originCountry, destinationCountry);
}
