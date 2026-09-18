/// Naming a delivery request's route on screen.
///
/// A published V1 request's route **is** its two canonical catalogue places,
/// `pickup_place` and `delivery_place`. The `Location` fields beside them are
/// the sender's *optional* preferred meeting points, and since Phase 8F-B the
/// map is optional during creation — so on most requests they are null.
///
/// Three screens read only those optional points and drew the route from
/// them: the request detail showed an empty route card, and the Deliveries and
/// Home rows showed a bare arrow (J7B). Journeys had the identical defect and
/// J1.2 fixed it with [endpointLabel]; requests now go through the same
/// function — the canonical place first, the coarse Location only for a
/// legacy row that has no place, and nothing invented.
///
/// An airport endpoint reads as the spec's locked route stop, `Algiers · ALG`:
/// the city the catalogue says it serves, with the code the sender actually
/// chose. The airport's own name is long enough that a 320-point route line
/// cut it to "Houari Bou…" and lost the code, which is the part that matters.
/// A locality never gains a code it was not given.
library;

import '../../domain/canonical_place.dart';
import '../../domain/delivery_request.dart';
import '../../domain/location.dart';
import '../../l10n/app_localizations.dart';
import '../journeys/journey_labels.dart';

/// Where the parcel is collected: the catalogue place (with its IATA code when
/// the sender chose an airport), or an em dash when nothing was recorded.
String requestPickupLabel(L l, DeliveryRequest request) =>
    _endpoint(l, request.pickupPlace, request.pickupLocation);

/// Where the parcel is delivered. See [requestPickupLabel].
String requestDeliveryLabel(L l, DeliveryRequest request) =>
    _endpoint(l, request.deliveryPlace, request.deliveryLocation);

String _endpoint(L l, CanonicalPlace? place, AppLocation? location) {
  final iata = place?.iataCode ?? '';
  final city = place?.matchingLocalityName ?? '';
  if (place != null && place.isAirport && iata.isNotEmpty && city.isNotEmpty) {
    return l.findTravelersStop(city, iata);
  }
  return endpointLabel(place, location);
}

/// Whether both ends of the route are known.
///
/// False only for a historical row that genuinely carries no route. Such a
/// request says "Route not recorded" rather than drawing an arrow between two
/// dashes, and a route is never reconstructed for it.
bool requestHasRoute(DeliveryRequest request) =>
    _endpointKnown(request.pickupPlace, request.pickupLocation) &&
    _endpointKnown(request.deliveryPlace, request.deliveryLocation);

bool _endpointKnown(CanonicalPlace? place, AppLocation? location) =>
    place != null || (location?.coarseLabel.isNotEmpty ?? false);
