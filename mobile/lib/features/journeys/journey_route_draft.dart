/// A journey route while it is being built or edited, expressed as **stops**.
///
/// ## Why this exists
///
/// The first version of this screen asked people to think in *legs*. Picking
/// Jijel and Paris produced one leg, Jijel → Paris, and "Add a leg" appended
/// to the end of the chain. So a traveller who then wanted
/// Jijel → Algiers → Paris had no way in: adding a stop put it *after* Paris.
/// The only route to the answer was to delete Paris, add Algiers, and add
/// Paris again. Real-device QA found exactly that, and it is not a copy
/// problem — it is the wrong noun.
///
/// People think in stops. So this model holds stops, and derives the legs
/// between them. Inserting Algiers between Jijel and Paris splits one segment
/// into two; the destination never has to be taken apart to reach the middle.
///
/// ## The chain cannot come apart
///
/// A leg's endpoints are never typed. Segment *k* runs from stop *k* to stop
/// *k+1*, so three of the server's rules are structurally impossible to break
/// rather than merely validated: positions are contiguous from zero, the
/// first leg begins where the journey does, and each leg starts where the
/// last one ended.
///
/// ## A stop is a place, and sometimes an airport at that place
///
/// The catalogue resolves CDG to Paris and ALG to Algiers, so an airport is
/// not a separate stop from the city it serves — it is *how that stop is
/// reached by air*. Two consecutive stops must be different localities, which
/// is why "CDG then Paris" is not a leg and "Jijel then Algiers/ALG" is. A
/// stop therefore carries an optional [RouteStopDraft.airport], and the
/// endpoint actually sent is that airport when one is chosen.
///
/// This is what keeps the airport transition honest. A city never silently
/// becomes an airport: when a segment must fly, the editor asks which airport,
/// and the route then reads
///
///     Jijel  —drive→  Algiers (ALG)  —flight→  Paris (CDG)
library;

import 'package:flutter/widgets.dart';

import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/forms.dart' show parseDecimalInput;
import '../../domain/canonical_place.dart';
import '../../domain/journey.dart';
import '../../domain/transport_mode.dart';
import '../../domain/transport_rules.dart';

/// The server's own ceiling, enforced here so nobody builds a 21st leg only
/// to have the whole journey refused.
const int maxJourneyLegs = 20;

/// One stop on the route.
class RouteStopDraft {
  RouteStopDraft({required this.place, this.airport});

  /// What the traveller chose: usually a city, sometimes an airport directly.
  CanonicalPlace place;

  /// The airport this stop is reached by, when a touching segment flies and
  /// [place] is not itself an airport. Never inferred — always chosen.
  CanonicalPlace? airport;

  /// The place actually sent to the server for this stop's legs.
  CanonicalPlace get endpoint => airport ?? place;

  bool get resolvesToAirport => endpoint.isAirport;

  /// The canonical locality the server will match on. Backend-owned: a
  /// catalogue row that resolves to nothing is not quietly treated as
  /// matching itself.
  int? get matchingLocalityId => endpoint.matchingLocalityId;

  /// True once [airport] no longer belongs to [place] — after the stop's city
  /// was changed, for instance.
  bool get airportIsStale {
    final chosen = airport;
    if (chosen == null) return false;
    if (place.isAirport) return true;
    return chosen.matchingLocalityId != place.matchingLocalityId;
  }
}

/// One leg between two stops, while it is being filled in.
class RouteSegmentDraft {
  RouteSegmentDraft({
    required this.mode,
    this.id,
    this.departAt,
    this.arriveAt,
    String capacityKg = '',
    String flightNumber = '',
  }) {
    capacity.text = capacityKg;
    this.flightNumber.text = flightNumber;
  }

  /// The server's leg id when this segment came from a saved journey. Kept
  /// through edits so an unchanged flight leg keeps its reviewed proof.
  int? id;

  LegMode mode;
  DateTime? departAt;
  DateTime? arriveAt;

  final capacity = TextEditingController();
  final flightNumber = TextEditingController();

  TransportMode get displayMode =>
      mode.isFlight ? TransportMode.flight : TransportMode.drive;

  TransportModeDraft get wireMode =>
      mode.isFlight ? TransportModeDraft.flight : TransportModeDraft.drive;

  void dispose() {
    capacity.dispose();
    flightNumber.dispose();
  }
}

/// Everything wrong with one segment, per field, so each message lands on the
/// input that caused it.
typedef SegmentIssues = ({
  String? depart,
  String? arrive,
  String? capacity,
  String? flightNumber,

  /// The segment must fly but one or both of its stops is not an airport.
  bool needsAirports,

  /// The two stops resolve to the same city, so there is no leg between them.
  bool stopsAreTheSamePlace,
});

/// The stops, the segments derived from them, and the edits people make.
///
/// A [ChangeNotifier] rather than immutable state: the segments own text
/// controllers whose lifetime has to follow the segment, and rebuilding the
/// whole route on every keystroke would drop the cursor.
class JourneyRouteDraft extends ChangeNotifier {
  JourneyRouteDraft();

  /// Rebuilds the editable route from a saved journey.
  ///
  /// The journey's own endpoints are what the traveller chose; a leg endpoint
  /// that is an airport becomes that stop's airport rather than replacing the
  /// city, so re-opening the editor shows "Paris (CDG)" and not "CDG".
  factory JourneyRouteDraft.fromJourney(Journey journey) {
    final draft = JourneyRouteDraft();
    final legs = journey.legs;
    if (legs.isEmpty) {
      final start = journey.startPlace;
      final end = journey.destinationPlace;
      if (start != null) draft._stops.add(RouteStopDraft(place: start));
      if (start != null && end != null) {
        draft._stops.add(RouteStopDraft(place: end));
        draft._segments.add(
          RouteSegmentDraft(mode: defaultModeFor(start, end)),
        );
      }
      return draft;
    }

    RouteStopDraft stopFor(
      CanonicalPlace? legEndpoint,
      CanonicalPlace? chosen,
    ) {
      final endpoint = legEndpoint ?? chosen;
      if (endpoint == null) {
        return RouteStopDraft(place: chosen ?? legEndpoint!);
      }
      if (!endpoint.isAirport) return RouteStopDraft(place: endpoint);
      // The city the traveller named, when the journey recorded one that this
      // airport serves; otherwise the airport stands for itself.
      final city =
          chosen != null &&
              !chosen.isAirport &&
              chosen.matchingLocalityId == endpoint.matchingLocalityId
          ? chosen
          : null;
      return city == null
          ? RouteStopDraft(place: endpoint)
          : RouteStopDraft(place: city, airport: endpoint);
    }

    draft._stops.add(stopFor(legs.first.originPlace, journey.startPlace));
    for (var i = 0; i < legs.length; i++) {
      final leg = legs[i];
      final isLast = i == legs.length - 1;
      draft._stops.add(
        stopFor(
          leg.destinationPlace,
          isLast ? journey.destinationPlace : leg.destinationPlace,
        ),
      );
      draft._segments.add(
        RouteSegmentDraft(
          id: leg.id,
          mode: leg.mode == TransportMode.flight
              ? LegMode.flight
              : LegMode.drive,
          departAt: leg.departAt,
          arriveAt: leg.arriveAt,
          capacityKg: leg.capacityKg == null
              ? ''
              : leg.capacityKg!.toStringAsFixed(2),
          flightNumber: leg.flightNumber,
        ),
      );
    }
    return draft;
  }

  final List<RouteStopDraft> _stops = [];
  final List<RouteSegmentDraft> _segments = [];

  List<RouteStopDraft> get stops => List.unmodifiable(_stops);
  List<RouteSegmentDraft> get segments => List.unmodifiable(_segments);

  bool get hasBothEnds => _stops.length >= 2;
  bool get canAddStop => _segments.length < maxJourneyLegs;

  RouteStopDraft? get origin => _stops.isEmpty ? null : _stops.first;
  RouteStopDraft? get destination => _stops.length < 2 ? null : _stops.last;

  bool isIntermediate(int index) => index > 0 && index < _stops.length - 1;

  @override
  void dispose() {
    for (final segment in _segments) {
      segment.dispose();
    }
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // Stops
  // -------------------------------------------------------------------------

  /// Sets the first stop, creating it when the route is empty.
  void setOrigin(CanonicalPlace place) {
    if (_stops.isEmpty) {
      _stops.add(RouteStopDraft(place: place));
    } else {
      _replacePlace(0, place);
    }
    _reconcile();
  }

  /// Sets the last stop, creating the first segment when it is the second
  /// place chosen.
  void setDestination(CanonicalPlace place) {
    if (_stops.isEmpty) return;
    if (_stops.length == 1) {
      _stops.add(RouteStopDraft(place: place));
      _segments.add(
        RouteSegmentDraft(
          mode: defaultModeFor(_stops[0].endpoint, _stops[1].endpoint),
        ),
      );
    } else {
      _replacePlace(_stops.length - 1, place);
    }
    _reconcile();
  }

  /// Changes any stop, including one in the middle.
  void setStop(int index, CanonicalPlace place) {
    if (index < 0 || index >= _stops.length) return;
    _replacePlace(index, place);
    _reconcile();
  }

  /// Chooses the airport a stop is reached by, for a segment that must fly.
  ///
  /// The city is left alone: a stop stays "Algiers", now reached via ALG.
  void setStopAirport(int index, CanonicalPlace airport) {
    if (index < 0 || index >= _stops.length) return;
    if (!airport.isAirport) return;
    final stop = _stops[index];
    if (stop.place.isAirport) {
      stop.place = airport;
      stop.airport = null;
    } else {
      stop.airport = airport;
    }
    _reconcile();
  }

  /// Inserts a stop **after** [afterIndex], splitting the segment that used to
  /// run past it.
  ///
  /// This is the operation the old screen had no way to express. The
  /// destination is untouched; the segment that spanned the gap becomes two,
  /// and the half that is still a flight keeps the flight number rather than
  /// making the traveller retype it.
  void insertStopAfter(int afterIndex, CanonicalPlace place) {
    if (!canAddStop) return;
    if (afterIndex < 0 || afterIndex >= _stops.length - 1) return;

    final original = _segments[afterIndex];
    final inserted = RouteStopDraft(place: place);
    _stops.insert(afterIndex + 1, inserted);

    final firstMode = defaultModeFor(
      _stops[afterIndex].endpoint,
      inserted.endpoint,
    );
    final secondMode = defaultModeFor(
      inserted.endpoint,
      _stops[afterIndex + 2].endpoint,
    );

    // The original segment becomes the first half: it keeps the departure the
    // traveller already entered, because that is still when they set off.
    final wasFlight = original.mode.isFlight;
    final carriedFlightNumber = original.flightNumber.text;
    original.mode = firstMode;
    original.arriveAt = null;
    // A leg's identity belongs to the pair of places it joins, so splitting
    // the span means *neither* half is the leg the server stored. Both are new
    // rows, and any proof on the old leg goes with it — a boarding pass for
    // Jijel → Paris does not evidence Jijel → Algiers.
    original.id = null;
    if (!firstMode.isFlight) original.flightNumber.clear();

    final second = RouteSegmentDraft(
      mode: secondMode,
      capacityKg: original.capacity.text,
      flightNumber: wasFlight && secondMode.isFlight && !firstMode.isFlight
          ? carriedFlightNumber
          : '',
    );
    _segments.insert(afterIndex + 1, second);
    _reconcile();
  }

  /// Removes an intermediate stop and rejoins the two segments it separated.
  void removeStop(int index) {
    if (!isIntermediate(index)) return;
    _stops.removeAt(index);
    // Keep the segment that arrives at this stop and let it run on to the
    // next one; the traveller's departure time for it is still correct.
    final surviving = _segments[index - 1];
    final removed = _segments.removeAt(index);
    surviving.arriveAt = removed.arriveAt;
    // The endpoints changed, so the id no longer identifies this leg to the
    // server; and a merged segment is not the flight the number described.
    surviving.id = null;
    surviving.mode = defaultModeFor(
      _stops[index - 1].endpoint,
      _stops[index].endpoint,
    );
    if (!surviving.mode.isFlight) surviving.flightNumber.clear();
    removed.dispose();
    _reconcile();
  }

  /// Moves an intermediate stop one position earlier or later.
  ///
  /// Only intermediate stops move: reordering an endpoint is a different
  /// journey, not a reorder.
  void moveStop(int index, {required bool earlier}) {
    if (!isIntermediate(index)) return;
    final target = earlier ? index - 1 : index + 1;
    if (!isIntermediate(target)) return;
    final stop = _stops.removeAt(index);
    _stops.insert(target, stop);
    // Every segment that touched either position now joins different places.
    final touched = {index - 1, index, target - 1, target};
    for (final position in touched) {
      if (position < 0 || position >= _segments.length) continue;
      final segment = _segments[position];
      segment.id = null;
      segment.mode = defaultModeFor(
        _stops[position].endpoint,
        _stops[position + 1].endpoint,
      );
      if (!segment.mode.isFlight) segment.flightNumber.clear();
    }
    _reconcile();
  }

  void _replacePlace(int index, CanonicalPlace place) {
    final stop = _stops[index];
    stop.place = place;
    // An airport chosen for the old city does not serve the new one.
    if (stop.airportIsStale) stop.airport = null;
    if (place.isAirport) stop.airport = null;
    for (final position in [index - 1, index]) {
      if (position < 0 || position >= _segments.length) continue;
      // The leg is no longer between the places the server stored.
      _segments[position].id = null;
    }
  }

  // -------------------------------------------------------------------------
  // Segments
  // -------------------------------------------------------------------------

  void setSegmentMode(int index, LegMode mode) {
    if (index < 0 || index >= _segments.length) return;
    if (!modesFor(index).contains(mode)) return;
    _segments[index].mode = mode;
    // A drive leg must arrive with an empty flight number, so the field is
    // cleared rather than merely hidden.
    if (!mode.isFlight) _segments[index].flightNumber.clear();
    _reconcile();
  }

  void setSegmentDeparture(int index, DateTime value) {
    if (index < 0 || index >= _segments.length) return;
    _segments[index].departAt = value;
    notifyListeners();
  }

  void setSegmentArrival(int index, DateTime? value) {
    if (index < 0 || index >= _segments.length) return;
    _segments[index].arriveAt = value;
    notifyListeners();
  }

  /// The modes segment [index] may legally declare.
  Set<LegMode> modesFor(int index) {
    if (index < 0 || index >= _segments.length) return {LegMode.drive};
    return availableModes(_stops[index].endpoint, _stops[index + 1].endpoint);
  }

  /// True when this segment can only be a flight — Algeria to anywhere
  /// outside it, and back.
  bool segmentMustFly(int index) => modesFor(index).length == 1;

  /// Re-derives everything that follows from the stops, and tells listeners.
  ///
  /// Called after every structural change so a mode can never survive a stop
  /// edit that made it impossible.
  void _reconcile() {
    for (var i = 0; i < _segments.length; i++) {
      final allowed = modesFor(i);
      if (!allowed.contains(_segments[i].mode)) {
        _segments[i].mode = allowed.first;
        if (!_segments[i].mode.isFlight) _segments[i].flightNumber.clear();
        _segments[i].id = null;
      }
    }
    notifyListeners();
  }

  /// Fired by the editor when a text field changes, so previews and the
  /// submit button track what has been typed.
  void touch() => notifyListeners();

  // -------------------------------------------------------------------------
  // Validation
  // -------------------------------------------------------------------------

  SegmentIssues issuesFor(int index, RouteCopy copy) {
    final segment = _segments[index];
    final previous = index == 0 ? null : _segments[index - 1];

    String? depart;
    final departAt = segment.departAt;
    if (departAt == null) {
      depart = copy.departRequired;
    } else if (previous != null) {
      final previousDepart = previous.departAt;
      final previousArrive = previous.arriveAt;
      if (previousDepart != null && !departAt.isAfter(previousDepart)) {
        depart = copy.departNotAfterPrevious;
      } else if (previousArrive != null && departAt.isBefore(previousArrive)) {
        depart = copy.departBeforePreviousArrival;
      }
    }

    final arriveAt = segment.arriveAt;
    final arrive =
        (arriveAt != null && departAt != null && !arriveAt.isAfter(departAt))
        ? copy.arriveBeforeDepart
        : null;

    // The wire format is two decimal places, so the check is on what will
    // actually be sent — 0.004 kg rounds to 0.00 and would be refused.
    final capacityValue = parseDecimalInput(segment.capacity.text);
    final capacity =
        (capacityValue == null || (capacityValue * 100).round() < 1)
        ? copy.capacityInvalid
        : null;

    final flightNumber =
        segment.mode.isFlight && segment.flightNumber.text.trim().isEmpty
        ? copy.required
        : null;

    final needsAirports =
        segment.mode.isFlight &&
        (!_stops[index].resolvesToAirport ||
            !_stops[index + 1].resolvesToAirport);

    final from = _stops[index].matchingLocalityId;
    final to = _stops[index + 1].matchingLocalityId;
    // A stop the catalogue cannot resolve is not silently treated as its own
    // match, so an unresolvable pair reads as "not a leg" rather than as one.
    final sameStop = from == null || to == null || from == to;

    return (
      depart: depart,
      arrive: arrive,
      capacity: capacity,
      flightNumber: flightNumber,
      needsAirports: needsAirports,
      stopsAreTheSamePlace: sameStop,
    );
  }

  bool isValid(RouteCopy copy) {
    if (!hasBothEnds) return false;
    if (_segments.isEmpty || _segments.length > maxJourneyLegs) return false;
    for (var i = 0; i < _segments.length; i++) {
      final issues = issuesFor(i, copy);
      if (issues.depart != null ||
          issues.arrive != null ||
          issues.capacity != null ||
          issues.flightNumber != null ||
          issues.needsAirports ||
          issues.stopsAreTheSamePlace) {
        return false;
      }
    }
    return true;
  }

  // -------------------------------------------------------------------------
  // The wire
  // -------------------------------------------------------------------------

  List<JourneyLegDraft> toLegDrafts() => [
    for (var i = 0; i < _segments.length; i++)
      JourneyLegDraft(
        id: _segments[i].id,
        position: i,
        mode: _segments[i].wireMode,
        originPlaceId: _stops[i].endpoint.id,
        destinationPlaceId: _stops[i + 1].endpoint.id,
        departAt: _segments[i].departAt!,
        arriveAt: _segments[i].arriveAt,
        capacityKg: parseDecimalInput(_segments[i].capacity.text)!,
        flightNumber: _segments[i].mode.isFlight
            ? _segments[i].flightNumber.text.trim()
            : '',
      ),
  ];

  /// The journey's own endpoints: what the traveller named, not the airport
  /// they happen to fly from.
  int get startPlaceId => _stops.first.place.id;
  int get destinationPlaceId => _stops.last.place.id;
}

/// The localised strings validation needs, passed in so the model stays
/// widget-free and directly testable.
typedef RouteCopy = ({
  String departRequired,
  String departNotAfterPrevious,
  String departBeforePreviousArrival,
  String arriveBeforeDepart,
  String capacityInvalid,
  String required,
});

/// Formats a segment's supporting detail for the route preview.
String? segmentDetailLabel(
  Locale locale,
  RouteSegmentDraft segment, {
  required String departsLabel,
}) {
  final parts = <String>[
    if (segment.mode.isFlight && segment.flightNumber.text.trim().isNotEmpty)
      segment.flightNumber.text.trim(),
    if (segment.departAt != null)
      '$departsLabel ${LocaleFormats.dateTime(locale, segment.departAt!)}',
  ];
  return parts.isEmpty ? null : parts.join(' · ');
}
