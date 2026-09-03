/// Naming a route endpoint on screen.
///
/// A V1 journey's legs carry canonical catalogue places; the old
/// `Location`-shaped fields are null on every journey created since Phase 8C.
/// Screens that read only `leg.origin?.coarseLabel` therefore rendered an
/// empty string where a city belonged — which is a large part of why the
/// journey summary was hard to read on the device.
///
/// So endpoint naming goes through here: the canonical place first, the
/// coarse Location only as a fallback for a legacy row, and an em dash rather
/// than an empty label when there is genuinely nothing to say.
library;

import 'package:flutter/widgets.dart';

import '../../design/components/place.dart';
import '../../domain/canonical_place.dart';
import '../../domain/journey.dart';
import '../../domain/location.dart';

const String _unknown = '—';

/// The city (and IATA code, for an airport) for one end of a leg.
String endpointLabel(CanonicalPlace? place, AppLocation? location) {
  if (place != null) return placeLabel(place);
  final coarse = location?.coarseLabel;
  return (coarse == null || coarse.isEmpty) ? _unknown : coarse;
}

/// The supporting line under an endpoint: its wilaya, department, province.
String? endpointContext(
  BuildContext context,
  CanonicalPlace? place,
  AppLocation? location,
) {
  if (place != null) {
    final detail = placeContext(context, place);
    return detail.isEmpty ? null : detail;
  }
  return null;
}

String legOriginLabel(JourneyLeg leg) =>
    endpointLabel(leg.originPlace, leg.origin);

String legDestinationLabel(JourneyLeg leg) =>
    endpointLabel(leg.destinationPlace, leg.destination);

/// Where the journey starts, preferring what its first leg actually says.
String journeyStartLabel(Journey journey) {
  if (journey.startPlace != null || journey.startLocation != null) {
    return endpointLabel(journey.startPlace, journey.startLocation);
  }
  final first = journey.legs.isEmpty ? null : journey.legs.first;
  return first == null ? _unknown : legOriginLabel(first);
}

String journeyDestinationLabel(Journey journey) {
  if (journey.destinationPlace != null || journey.destinationLocation != null) {
    return endpointLabel(journey.destinationPlace, journey.destinationLocation);
  }
  final last = journey.legs.isEmpty ? null : journey.legs.last;
  return last == null ? _unknown : legDestinationLabel(last);
}
