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
///
/// ## A ferry runs between cities, never airports
///
/// A sea segment joins two port *cities*, so it ignores the airport a stop was
/// reached by: Marseille —sea→ Algiers is sent as Marseille and Algiers even
/// when the same stops also carry airports for a flight on the other side.
library;

import 'package:flutter/widgets.dart';

import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/forms.dart' show parseDecimalInput;
import '../../domain/canonical_place.dart';
import '../../domain/delivery_request.dart' show ItemCategory;
import '../../domain/journey.dart';
import '../../domain/sea_crossings.dart';
import '../../domain/transport_mode.dart';
import '../../domain/transport_rules.dart';

/// The server's own ceiling, enforced here so nobody builds a 21st leg only
/// to have the whole journey refused.
const int maxJourneyLegs = 20;

/// The per-leg weight ceiling shared with the server. It is a typo guard, not
/// a commercial limit, so it is far above anything one person carries.
const double maxJourneyLegCapacityKg = 20000.0;

/// The optional per-leg limits, as the server bounds them.
const int maxJourneyLegVolumeLitres = 200000;
const int maxJourneyLegParcels = 10000;

/// The longest handover note the server stores.
const int maxStopNoteLength = 280;

/// The item categories a traveller can decline, in the order they are shown.
/// `unknown` is a parse fallback, never something to choose.
const List<ItemCategory> carryableCategories = [
  ItemCategory.documents,
  ItemCategory.smallBox,
  ItemCategory.electronics,
  ItemCategory.clothing,
  ItemCategory.other,
];

String _categoryWire(ItemCategory category) => switch (category) {
  ItemCategory.smallBox => 'small_box',
  _ => category.name,
};

/// How a draft mode reads as the parsed [TransportMode] the design system
/// knows how to draw.
extension LegModeTransport on LegMode {
  TransportMode get transport => switch (this) {
    LegMode.flight => TransportMode.flight,
    LegMode.drive => TransportMode.drive,
    LegMode.sea => TransportMode.sea,
  };
}

/// One stop on the route.
class RouteStopDraft {
  RouteStopDraft({
    required this.place,
    this.airport,
    this.acceptsPickup = true,
    this.acceptsDropoff = true,
    this.windowStart,
    this.windowEnd,
    String note = '',
  }) {
    this.note.text = note;
  }

  /// Handover options for this stop. The defaults — accept both, no window, no
  /// note — are what a stop that was never configured means, and are not sent.
  bool acceptsPickup;
  bool acceptsDropoff;
  DateTime? windowStart;
  DateTime? windowEnd;
  final note = TextEditingController();

  bool get hasWindow => windowStart != null && windowEnd != null;

  void dispose() => note.dispose();

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
    String volumeLitres = '',
    String parcels = '',
  }) {
    capacity.text = capacityKg;
    this.flightNumber.text = flightNumber;
    volume.text = volumeLitres;
    this.parcels.text = parcels;
  }

  /// The server's leg id when this segment came from a saved journey. Kept
  /// through edits so an unchanged flight leg keeps its reviewed proof.
  int? id;

  LegMode mode;
  DateTime? departAt;
  DateTime? arriveAt;

  final capacity = TextEditingController();
  final flightNumber = TextEditingController();

  /// Optional extra limits. Empty means "not limited".
  final volume = TextEditingController();
  final parcels = TextEditingController();

  TransportMode get displayMode => mode.transport;

  TransportModeDraft get wireMode => switch (mode) {
    LegMode.flight => TransportModeDraft.flight,
    LegMode.drive => TransportModeDraft.drive,
    LegMode.sea => TransportModeDraft.sea,
  };

  /// Whether the "More capacity options" disclosure has anything in it.
  bool get hasExtraCapacity =>
      volume.text.trim().isNotEmpty || parcels.text.trim().isNotEmpty;

  void dispose() {
    capacity.dispose();
    flightNumber.dispose();
    volume.dispose();
    parcels.dispose();
  }
}

/// Everything wrong with one segment, per field, so each message lands on the
/// input that caused it.
typedef SegmentIssues = ({
  String? depart,
  String? arrive,
  String? capacity,
  String? flightNumber,

  /// The optional per-leg limits, when what was typed is not allowed.
  String? volume,
  String? parcels,

  /// The segment is a sea leg the server would refuse right now, and why.
  SeaRefusal? sea,

  /// The segment must fly but one or both of its stops is not an airport.
  bool needsAirports,

  /// The two stops resolve to the same city, so there is no leg between them.
  bool stopsAreTheSamePlace,
});

/// What is wrong with one stop's handover options.
typedef StopIssues = ({String? window});

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
          mode: switch (leg.mode) {
            TransportMode.flight => LegMode.flight,
            TransportMode.sea => LegMode.sea,
            _ => LegMode.drive,
          },
          departAt: leg.departAt,
          arriveAt: leg.arriveAt,
          capacityKg: leg.capacityKg == null
              ? ''
              : leg.capacityKg!.toStringAsFixed(2),
          flightNumber: leg.flightNumber,
          volumeLitres: leg.capacityVolumeLitres?.toString() ?? '',
          parcels: leg.capacityParcels?.toString() ?? '',
        ),
      );
    }

    // What each stop accepts, as the owner set it. A stop the payload does not
    // list was never configured and keeps the defaults.
    for (final detail in journey.stops) {
      if (detail.position < 0 || detail.position >= draft._stops.length) {
        continue;
      }
      final stop = draft._stops[detail.position];
      stop.acceptsPickup = detail.acceptsPickup;
      stop.acceptsDropoff = detail.acceptsDropoff;
      stop.windowStart = detail.windowStart;
      stop.windowEnd = detail.windowEnd;
      stop.note.text = detail.handoverNote;
    }

    draft.refusedCategories.addAll([
      for (final category in carryableCategories)
        if (journey.refusedCategories.contains(_categoryWire(category)))
          category,
    ]);
    draft.acceptsFragile = journey.acceptsFragile;
    return draft;
  }

  final List<RouteStopDraft> _stops = [];
  final List<RouteSegmentDraft> _segments = [];

  /// What this traveller will not take. Empty — the default — takes
  /// everything. Declining every category is not a journey, so the editor
  /// never lets the last one be switched off.
  final Set<ItemCategory> refusedCategories = {};
  bool acceptsFragile = true;

  /// The ferry lines, or null while they are loading or could not be loaded.
  /// Null never blocks flight and road editing and never demotes a sea leg the
  /// traveller already has; it only means Sea is not offered for a new one.
  SeaCrossings? _crossings;
  SeaCrossings? get seaCrossings => _crossings;

  /// The server's own refusal of a sea leg, by segment, until the traveller
  /// changes something. Shown on the leg it belongs to.
  final Map<int, SeaRefusal> _serverRefusals = {};

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
    for (final stop in _stops) {
      stop.dispose();
    }
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // Sea
  // -------------------------------------------------------------------------

  /// Gives the draft the server's ferry lines (or null when they cannot be
  /// had). Notifies without reconciling: a list that arrives late or changes
  /// must not silently rewrite a leg the traveller has already chosen.
  void setSeaCrossings(SeaCrossings? crossings) {
    if (identical(crossings, _crossings)) return;
    _crossings = crossings;
    notifyListeners();
  }

  /// Records the server's refusal of the sea leg at [position], so it shows on
  /// that leg. A reason this build does not know is ignored: the generic
  /// message already covers it.
  void markSeaRefused(int position, String? reason) {
    final refusal = SeaRefusal.fromServer(reason);
    if (refusal == null || position < 0 || position >= _segments.length) {
      return;
    }
    _serverRefusals[position] = refusal;
    notifyListeners();
  }

  /// Why a sea leg on segment [index] is a problem now: what the server told
  /// us on the last attempt, else what the ferry lines say.
  SeaRefusal? seaProblemFor(int index) {
    if (index < 0 ||
        index >= _segments.length ||
        !_segments[index].mode.isSea) {
      return null;
    }
    return _serverRefusals[index] ??
        seaRefusal(_stops[index].place, _stops[index + 1].place, _crossings);
  }

  /// True when Sea is missing from segment [index] only because the owner's
  /// switch is off, which is the one absence worth a line of explanation.
  bool seaSwitchedOffFor(int index) {
    if (index < 0 || index >= _segments.length) return false;
    return seaIsSwitchedOff(
      _stops[index].place,
      _stops[index + 1].place,
      _crossings,
    );
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
    // Whatever the old span was, each half starts from a derived mode; a sea
    // leg is never carried onto a half it may not fit.

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
      volumeLitres: original.volume.text,
      parcels: original.parcels.text,
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
    _stops.removeAt(index).dispose();
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
    // A road or sea leg must arrive with an empty flight number, so the field
    // is cleared rather than merely hidden.
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
  ///
  /// A sea leg the traveller already has stays in the set even if the ferry
  /// lines no longer offer it, so the chooser keeps showing what is selected
  /// and the reason is shown on the leg ([seaProblemFor]) rather than the leg
  /// quietly turning into something else.
  Set<LegMode> modesFor(int index) {
    if (index < 0 || index >= _segments.length) return {LegMode.drive};
    final modes = availableModes(
      _stops[index].place,
      _stops[index + 1].place,
      crossings: _crossings,
    );
    if (_segments[index].mode.isSea) modes.add(LegMode.sea);
    return modes;
  }

  /// True when this segment can only be a flight — Algeria to anywhere
  /// outside it, and back, with no ferry line on offer.
  bool segmentMustFly(int index) => modesFor(index).length == 1;

  /// Re-derives everything that follows from the stops, and tells listeners.
  ///
  /// Called after every structural change so a mode can never survive a stop
  /// edit that made it impossible.
  void _reconcile() {
    _serverRefusals.clear();
    for (var i = 0; i < _segments.length; i++) {
      final segment = _segments[i];
      final allowed = segment.mode.isSea ? _modesWithoutSwitch(i) : modesFor(i);
      if (!allowed.contains(segment.mode)) {
        segment.mode = allowed.first;
        if (!segment.mode.isFlight) segment.flightNumber.clear();
        segment.id = null;
      }
    }
    notifyListeners();
  }

  /// For a segment that is already a sea leg: the modes it may keep after a
  /// structural edit. Sea survives unless the edit made it structurally
  /// impossible (an airport stop, or a pair no line has ever joined). A switch
  /// that is merely off does not demote it; that is shown on the leg instead.
  Set<LegMode> _modesWithoutSwitch(int index) {
    final modes = availableModes(
      _stops[index].place,
      _stops[index + 1].place,
      crossings: _crossings,
    );
    final from = _stops[index].place;
    final to = _stops[index + 1].place;
    final possible =
        !from.isAirport &&
        !to.isAirport &&
        (_crossings == null ||
            _crossings!.hasLine(
              from.matchingLocalityId,
              to.matchingLocalityId,
            ));
    if (possible) modes.add(LegMode.sea);
    return modes;
  }

  /// Fired by the editor when a text field changes, so previews and the
  /// submit button track what has been typed.
  void touch() => notifyListeners();

  // -------------------------------------------------------------------------
  // Validation
  // -------------------------------------------------------------------------

  SegmentIssues issuesFor(
    int index,
    RouteCopy copy, {
    DateTime? now,
    String? pastDepartureError,
  }) {
    final segment = _segments[index];
    final previous = index == 0 ? null : _segments[index - 1];

    String? depart;
    final departAt = segment.departAt;
    if (departAt == null) {
      depart = copy.departRequired;
    } else if (now != null && !departAt.isAfter(now)) {
      depart = pastDepartureError ?? copy.departRequired;
    } else if (previous != null) {
      final previousDepart = previous.departAt;
      final previousArrive = previous.arriveAt;
      if (previousDepart != null && !departAt.isAfter(previousDepart)) {
        depart = copy.departNotAfterPrevious;
      } else if (previousArrive != null && departAt.isBefore(previousArrive)) {
        depart = copy.departBeforePreviousArrival;
      }
    }

    // Required since J7B. Matching delivers a parcel at the end of a leg only
    // if it knows when that leg arrives — the arrival is what the sender's
    // deadline is checked against — so a leg without one published a trip no
    // request could ever match. The server refuses it too.
    final arriveAt = segment.arriveAt;
    final String? arrive;
    if (arriveAt == null) {
      arrive = copy.arriveRequired;
    } else if (departAt != null && !arriveAt.isAfter(departAt)) {
      arrive = copy.arriveBeforeDepart;
    } else {
      arrive = null;
    }

    // The server accepts 0.01–20,000.00 kg with at most two decimal places.
    // Check the typed precision too: rounding 0.005 on-device would make a
    // value appear valid that the authoritative DecimalField rejects.
    final capacityText = segment.capacity.text.trim();
    final capacityValue = parseDecimalInput(capacityText);
    final capacity =
        (capacityValue == null ||
            !RegExp(r'^\d+(?:[.,]\d{1,2})?$').hasMatch(capacityText) ||
            !capacityValue.isFinite ||
            capacityValue < 0.01 ||
            capacityValue > maxJourneyLegCapacityKg)
        ? copy.capacityInvalid
        : null;

    final flightNumber =
        segment.mode.isFlight && segment.flightNumber.text.trim().isEmpty
        ? copy.required
        : null;

    final volume = _optionalWholeNumber(
      segment.volume.text,
      max: maxJourneyLegVolumeLitres,
      message: copy.volumeInvalid,
    );
    final parcels = _optionalWholeNumber(
      segment.parcels.text,
      max: maxJourneyLegParcels,
      message: copy.parcelsInvalid,
    );

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
      volume: volume,
      parcels: parcels,
      sea: seaProblemFor(index),
      needsAirports: needsAirports,
      stopsAreTheSamePlace: sameStop,
    );
  }

  bool isValid(RouteCopy copy, {DateTime? now}) {
    if (!hasBothEnds) return false;
    if (_segments.isEmpty || _segments.length > maxJourneyLegs) return false;
    for (var i = 0; i < _segments.length; i++) {
      final issues = issuesFor(i, copy, now: now);
      if (issues.depart != null ||
          issues.arrive != null ||
          issues.capacity != null ||
          issues.flightNumber != null ||
          issues.volume != null ||
          issues.parcels != null ||
          issues.sea != null ||
          issues.needsAirports ||
          issues.stopsAreTheSamePlace) {
        return false;
      }
    }
    for (var i = 0; i < _stops.length; i++) {
      if (stopIssuesFor(i, copy).window != null) return false;
    }
    return true;
  }

  /// Null for empty (not limited) or a whole number in `1..max`.
  static String? _optionalWholeNumber(
    String raw, {
    required int max,
    required String message,
  }) {
    final text = raw.trim();
    if (text.isEmpty) return null;
    final value = RegExp(r'^\d{1,9}$').hasMatch(text) ? int.parse(text) : null;
    return value == null || value < 1 || value > max ? message : null;
  }

  /// The handover options of stop [index], checked the way the server does: a
  /// window needs both ends, ends after it starts, and sits between arriving
  /// at this stop and leaving it.
  StopIssues stopIssuesFor(int index, RouteCopy copy) {
    final stop = _stops[index];
    final start = stop.windowStart;
    final end = stop.windowEnd;
    if (start == null && end == null) return (window: null);
    if (start == null || end == null) return (window: copy.windowIncomplete);
    if (!end.isAfter(start)) return (window: copy.windowOrder);
    final arrives = index > 0 ? _segments[index - 1].arriveAt : null;
    final leaves = index < _segments.length ? _segments[index].departAt : null;
    if ((arrives != null && start.isBefore(arrives)) ||
        (leaves != null && end.isAfter(leaves))) {
      return (window: copy.windowOutside);
    }
    return (window: null);
  }

  // -------------------------------------------------------------------------
  // Stop options
  // -------------------------------------------------------------------------

  /// What stop [index] really accepts: nothing is dropped off where the trip
  /// starts, and nothing is picked up where it ends, whatever was set.
  bool stopAcceptsPickup(int index) =>
      index < _stops.length - 1 && _stops[index].acceptsPickup;
  bool stopAcceptsDropoff(int index) =>
      index > 0 && _stops[index].acceptsDropoff;

  void setStopOptions(
    int index, {
    bool? acceptsPickup,
    bool? acceptsDropoff,
    DateTime? windowStart,
    DateTime? windowEnd,
    bool clearWindow = false,
  }) {
    if (index < 0 || index >= _stops.length) return;
    final stop = _stops[index];
    if (acceptsPickup != null) stop.acceptsPickup = acceptsPickup;
    if (acceptsDropoff != null) stop.acceptsDropoff = acceptsDropoff;
    if (clearWindow) {
      stop.windowStart = null;
      stop.windowEnd = null;
    } else {
      if (windowStart != null) stop.windowStart = windowStart;
      if (windowEnd != null) stop.windowEnd = windowEnd;
    }
    notifyListeners();
  }

  void setCarries(ItemCategory category, {required bool carries}) {
    if (carries) {
      refusedCategories.remove(category);
    } else {
      // Declining everything is not a journey: the last one stays on.
      if (refusedCategories.length >= carryableCategories.length - 1) return;
      refusedCategories.add(category);
    }
    notifyListeners();
  }

  void setAcceptsFragile(bool value) {
    acceptsFragile = value;
    notifyListeners();
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
        // A ferry joins cities, so it never takes the airport a stop was
        // reached by on its other side.
        originPlaceId: _segments[i].mode.isSea
            ? _stops[i].place.id
            : _stops[i].endpoint.id,
        destinationPlaceId: _segments[i].mode.isSea
            ? _stops[i + 1].place.id
            : _stops[i + 1].endpoint.id,
        departAt: _segments[i].departAt!,
        arriveAt: _segments[i].arriveAt,
        capacityKg: parseDecimalInput(_segments[i].capacity.text)!,
        capacityVolumeLitres: int.tryParse(_segments[i].volume.text.trim()),
        capacityParcels: int.tryParse(_segments[i].parcels.text.trim()),
        flightNumber: _segments[i].mode.isFlight
            ? _segments[i].flightNumber.text.trim()
            : '',
      ),
  ];

  /// The stops that differ from "accepts both, no window, no note". The first
  /// stop never takes a drop-off and the last never a pickup, so those sides
  /// follow the one that matters rather than being sent as a contradiction.
  List<JourneyStopDraft> toStopDrafts() {
    final last = _stops.length - 1;
    final drafts = <JourneyStopDraft>[];
    for (var i = 0; i < _stops.length; i++) {
      final stop = _stops[i];
      final bool pickup;
      final bool dropoff;
      if (i == 0) {
        pickup = dropoff = stop.acceptsPickup;
      } else if (i == last) {
        pickup = dropoff = stop.acceptsDropoff;
      } else {
        pickup = stop.acceptsPickup;
        dropoff = stop.acceptsDropoff;
      }
      final note = stop.note.text.trim();
      if (pickup && dropoff && !stop.hasWindow && note.isEmpty) continue;
      drafts.add(
        JourneyStopDraft(
          position: i,
          acceptsPickup: pickup,
          acceptsDropoff: dropoff,
          handoverNote: note,
          windowStart: stop.hasWindow ? stop.windowStart : null,
          windowEnd: stop.hasWindow ? stop.windowEnd : null,
        ),
      );
    }
    return drafts;
  }

  /// Wire values of the categories this traveller will not take.
  List<String> get refusedCategoryWire => [
    for (final category in carryableCategories)
      if (refusedCategories.contains(category)) _categoryWire(category),
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
  String arriveRequired,
  String arriveBeforeDepart,
  String capacityInvalid,
  String volumeInvalid,
  String parcelsInvalid,
  String windowIncomplete,
  String windowOrder,
  String windowOutside,
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
