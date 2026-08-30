/// The wire contract, as this client understands it.
///
/// These are the parsing rules that would otherwise only be discovered against
/// a running server: the four error envelopes, the one uppercase enum, the
/// swapped distance keys, the per-viewer offer permissions, and the chat 402
/// whose field is `reason` rather than `code`.
///
/// Every fixture here is shaped from the real backend responses recorded in
/// the Phase 5 contract extraction, not invented.
library;

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/domain/chat.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/delivery_request.dart';
import 'package:shiptrip/domain/discovery.dart';
import 'package:shiptrip/domain/journey.dart';
import 'package:shiptrip/domain/location.dart';
import 'package:shiptrip/domain/offer.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/domain/transport_mode.dart';

/// Builds the failure the client would see for a given response.
///
/// `ApiException.fromResponse` takes a Dio [Response] because that is what the
/// client actually hands it; the tests go through the same door rather than a
/// convenience constructor that could drift from it.
ApiException _failure({
  required int statusCode,
  required Object? data,
  String path = '/api/x',
}) => ApiException.fromResponse(
  Response<dynamic>(
    requestOptions: RequestOptions(path: path),
    statusCode: statusCode,
    data: data,
  ),
);

void main() {
  group('transport mode', () {
    test('parses the API\'s uppercase values', () {
      // The one enum in the whole V1 contract that is not lowercase.
      expect(TransportMode.parse('FLIGHT'), TransportMode.flight);
      expect(TransportMode.parse('DRIVE'), TransportMode.drive);
    });

    test('parses the lowercase form used inside covered_legs', () {
      // The compatibility payload sends `"drive"`, the leg sends `"DRIVE"`.
      expect(TransportMode.parse('drive'), TransportMode.drive);
      expect(TransportMode.parse('flight'), TransportMode.flight);
    });

    test('an unknown mode degrades instead of throwing', () {
      expect(TransportMode.parse('TELEPORT'), TransportMode.unknown);
      expect(TransportMode.parse(null), TransportMode.unknown);
    });

    test('only a flight needs proof', () {
      expect(TransportMode.flight.requiresProof, isTrue);
      expect(TransportMode.drive.requiresProof, isFalse);
    });
  });

  group('journey legs', () {
    test('the owner sees exact metres', () {
      final leg = JourneyLeg.fromJson(const {
        'id': 101,
        'position': 0,
        'mode': 'FLIGHT',
        'depart_at': '2026-09-01T10:00:00Z',
        'capacity_kg': '20.00',
        'distance_meters': 1500000,
        'flight_number': 'AH1098',
        'has_approved_proof': true,
        'proofs': <Object>[],
      });

      expect(leg.isOwnerView, isTrue);
      expect(leg.distanceMeters, 1500000);
      expect(leg.distanceBand, isNull);
    });

    test('a counterparty sees a band in its place, not a null', () {
      // The key is swapped, not nulled — a client that assumed both exist
      // would render an empty distance for every non-owner.
      final leg = JourneyLeg.fromJson(const {
        'id': 101,
        'position': 0,
        'mode': 'DRIVE',
        'depart_at': '2026-09-01T10:00:00Z',
        'capacity_kg': '20.00',
        'distance_band': {
          'label': 'under_100km',
          'min_meters': 0,
          'max_meters': 100000,
        },
        'flight_number': '',
        'has_approved_proof': false,
      });

      expect(leg.isOwnerView, isFalse);
      expect(leg.distanceMeters, isNull);
      expect(leg.distanceBand?.label, 'under_100km');
    });

    test('a flight without approved proof blocks publication', () {
      final blocked = JourneyLeg.fromJson(const {
        'id': 1,
        'position': 0,
        'mode': 'FLIGHT',
        'depart_at': '2026-09-01T10:00:00Z',
        'capacity_kg': '10.00',
        'flight_number': 'AH1',
        'has_approved_proof': false,
        'proofs': <Object>[],
      });
      expect(blocked.needsProof, isTrue);

      final drive = JourneyLeg.fromJson(const {
        'id': 2,
        'position': 1,
        'mode': 'DRIVE',
        'depart_at': '2026-09-01T15:00:00Z',
        'capacity_kg': '10.00',
        'flight_number': '',
        'has_approved_proof': false,
      });
      expect(drive.needsProof, isFalse);
    });
  });

  group('locations', () {
    test('a coarse location is never treated as exact', () {
      final coarse = AppLocation.fromJson(const {
        'id': 12,
        'kind': 'city',
        'public_label': 'Paris, FR',
        'city': 'Paris',
        'country_code': 'FR',
        'coarse_latitude': '48.900000',
        'coarse_longitude': '2.400000',
        'precision': 'city',
      });

      expect(coarse.isExact, isFalse);
      expect(coarse.point?.lat, closeTo(48.9, 0.0001));
      expect(coarse.coarseLabel, 'Paris, FR');
    });

    test('an owner location exposes exact coordinates', () {
      final exact = AppLocation.fromJson(const {
        'id': 12,
        'kind': 'exact_address',
        'public_label': 'Paris, FR',
        'private_label': '12 rue de la Paix',
        'city': 'Paris',
        'country_code': 'FR',
        'latitude': '48.868200',
        'longitude': '2.329500',
        'coarse_latitude': '48.900000',
        'coarse_longitude': '2.300000',
        'precision': 'rooftop',
      });

      expect(exact.isExact, isTrue);
      expect(exact.displayLabel, '12 rue de la Paix');
      // Even for an owner, the coarse label stays available for the places
      // that must not show a street.
      expect(exact.coarseLabel, 'Paris, FR');
    });

    test('the legacy airport shape under the same key still parses', () {
      final airport = AppLocation.maybe(const {
        'iata': 'ALG',
        'city': 'Algiers',
        'name': 'Houari Boumediene',
        'country': 'DZ',
      })!;
      expect(airport.kind, LocationKind.airport);
      expect(airport.airportIata, 'ALG');
      expect(airport.isExact, isFalse);
    });
  });

  group('offers', () {
    Offer offerWith(List<String> actions, {String awaiting = 'traveler'}) =>
        Offer.fromJson({
          'id': 501,
          'match': 1,
          'proposed_by': 'sender',
          'proposer_id': 20,
          'economics_version': 'v1_eur',
          'currency': 'EUR',
          'traveler_reward_minor': 2500,
          'commission_rate_bps': 1000,
          'platform_fee_minor': 250,
          'sender_total_minor': 2750,
          'status': 'pending',
          'note': '',
          'awaiting_party': awaiting,
          'awaiting_user_id': 30,
          'allowed_actions': actions,
        });

    test('permissions come only from allowed_actions', () {
      final counterparty = offerWith(['accept', 'counter', 'decline']);
      expect(counterparty.canAccept, isTrue);
      expect(counterparty.canCounter, isTrue);
      expect(counterparty.canDecline, isTrue);
      expect(counterparty.canWithdraw, isFalse);

      final proposer = offerWith(['withdraw']);
      expect(proposer.canWithdraw, isTrue);
      expect(proposer.canAccept, isFalse);
      expect(proposer.canCounter, isFalse);
    });

    test('a closed offer offers nothing', () {
      final closed = offerWith(const []);
      expect(closed.hasAnyAction, isFalse);
    });

    test('an unrecognised action is dropped, not guessed at', () {
      final offer = offerWith(['accept', 'teleport']);
      expect(offer.allowedActions, {OfferAction.accept});
    });

    test('the fee is added on top, never taken out', () {
      final offer = offerWith(['accept']);
      // Reward + fee = total, all three from the server. The client renders
      // them; the identity is the API's to guarantee.
      expect(offer.travelerReward!.minorUnits, 2500);
      expect(offer.platformFee!.minorUnits, 250);
      expect(offer.senderTotal!.minorUnits, 2750);
    });

    test('awaiting is answered by user id, not by role guesswork', () {
      final offer = offerWith(['accept']);
      expect(offer.isAwaiting(30), isTrue);
      expect(offer.isAwaiting(20), isFalse);
    });
  });

  group('deals', () {
    test('every lifecycle instant is optional and never invented', () {
      final deal = Deal.fromJson(const {
        'id': 4,
        'sender_id': 20,
        'traveler_id': 30,
        'status': 'payment_required',
        'is_legacy': false,
      });

      expect(deal.isFunded, isFalse);
      expect(deal.fundedAt, isNull);
      expect(deal.protectionEndsAt, isNull);
      expect(deal.deliveryCodeAvailableAt, isNull);
      expect(deal.status.needsFunding, isTrue);
    });

    test('an unrecognised status degrades rather than crashing the tab', () {
      final deal = Deal.fromJson(const {
        'id': 4,
        'sender_id': 20,
        'traveler_id': 30,
        'status': 'awaiting_moon_phase',
        'is_legacy': false,
      });
      expect(deal.status, DealStatus.unknown);
    });

    test('a dispute keeps chat open; a closed deal does not', () {
      // Deliberate on the server side: parties in a dispute still need to talk.
      expect(DealStatus.disputed.closesChat, isFalse);
      expect(DealStatus.completed.closesChat, isTrue);
      expect(DealStatus.cancelled.closesChat, isTrue);
      expect(DealStatus.refunded.closesChat, isTrue);
    });

    test('the funding deadline comes from the reservation, not a guess', () {
      final deal = Deal.fromJson(const {
        'id': 4,
        'sender_id': 20,
        'traveler_id': 30,
        'status': 'payment_required',
        'is_legacy': false,
        'leg_allocations': [
          {
            'id': 900,
            'journey_leg_id': 10,
            'journey_leg_position': 0,
            'status': 'pending_payment',
            'expires_at': '2026-09-01T10:15:00Z',
          },
          {
            'id': 901,
            'journey_leg_id': 11,
            'journey_leg_position': 1,
            'status': 'pending_payment',
            'expires_at': '2026-09-01T10:05:00Z',
          },
        ],
      });

      // The earliest expiry is the real deadline.
      expect(deal.fundingDeadline, isNotNull);
      expect(deal.fundingDeadline!.toUtc().minute, 5);
    });

    test('the recipient projection differs by viewer', () {
      final travelerView = RecipientView.maybe(const {'recorded': true})!;
      expect(travelerView.recorded, isTrue);
      expect(travelerView.email, isNull);
      expect(travelerView.isFullRecord, isFalse);

      final senderView = RecipientView.maybe(const {
        'full_name': 'Amina',
        'email': 'amina@example.com',
        'phone': '+213555111222',
        'revision': 2,
      })!;
      expect(senderView.isFullRecord, isTrue);
      // And the traveller's copy never renders itself into a log line.
      expect(travelerView.toString(), isNot(contains('amina')));
      expect(senderView.toString(), isNot(contains('amina@example.com')));
    });
  });

  group('payments', () {
    test('an order has no processing state; the attempt carries it', () {
      // The server has no `processing` order status. "In flight" is a property
      // of the newest attempt, which is what a confirming screen must read.
      final order = PaymentOrder.fromJson(const {
        'public_reference': 'ref-1',
        'purpose': 'deal_balance',
        'status': 'pending',
        'currency': 'EUR',
        'amount_eur_cents': 3200,
        'outstanding_eur_cents': 2700,
        'deposit_credit_eur_cents': 500,
        'attempts': [
          {
            'id': 91,
            'provider': 'chargily',
            'status': 'checkout_pending',
            'amount_eur_cents': 2700,
            'checkout_url': 'https://pay.example/abc',
          },
        ],
      });

      expect(order.status, PaymentOrderStatus.pending);
      expect(order.isSettling, isTrue);
      expect(order.lastAttemptFailed, isFalse);
      expect(order.latestAttempt!.status.isInFlight, isTrue);
    });

    test('a dead attempt lets the sender start another', () {
      final order = PaymentOrder.fromJson(const {
        'public_reference': 'ref-1',
        'purpose': 'deal_balance',
        'status': 'pending',
        'currency': 'EUR',
        'outstanding_eur_cents': 2700,
        'attempts': [
          {'id': 92, 'provider': 'stripe', 'status': 'failed'},
        ],
      });

      expect(order.isSettling, isFalse);
      expect(order.lastAttemptFailed, isTrue);
    });

    test('the deposit credit is a subtraction, and is flagged as one', () {
      final order = PaymentOrder.fromJson(const {
        'public_reference': 'ref-1',
        'purpose': 'deal_balance',
        'status': 'partially_paid',
        'currency': 'EUR',
        'amount_eur_cents': 3200,
        'deposit_credit_eur_cents': 500,
        'outstanding_eur_cents': 2700,
      });

      expect(order.hasCredit, isTrue);
      // The outstanding figure is the server's, not amount minus credit here.
      expect(order.outstanding!.minorUnits, 2700);
    });

    test('the Chargily quote is whole dinars at the server\'s frozen rate', () {
      final quote = ChargilyQuote.maybe(const {
        'canonical_amount_eur_cents': 2700,
        'payment_amount_dzd': 40500,
        'eur_dzd_rate': '150.000000',
        'eur_dzd_rate_micros': 150000000,
        'rate_settings_version': 3,
      })!;

      expect(quote.paymentAmount!.exponent, 0);
      expect(quote.paymentAmount!.minorUnits, 40500);
      // The pre-formatted string is displayed verbatim, never re-derived.
      expect(quote.eurDzdRate, '150.000000');
    });

    test('the mock rail is never offered as a choice', () {
      final providers = ProvidersView.fromJson(const {
        'timing_mode': 'posting_deposit',
        'canonical_currency': 'EUR',
        'providers': [
          {'provider': 'stripe', 'available': true, 'payment_currency': 'EUR'},
          {'provider': 'mock', 'available': true, 'payment_currency': 'EUR'},
        ],
      });

      expect(
        providers.providers.map((p) => p.provider),
        isNot(contains(PaymentProviderId.mock)),
      );
    });

    test('a frozen payout is not a failed one', () {
      expect(PayoutStatus.frozen.isBlocked, isTrue);
      expect(PayoutStatus.frozen.isPending, isFalse);
      expect(PayoutStatus.notEligible.isPending, isTrue);
    });
  });

  group('chat', () {
    test('the 402 body uses `reason`, not `code`', () {
      final error = _failure(
        statusCode: 402,
        data: const {'reason': 'payment_pending', 'match_id': 55},
        path: '/api/matches/55/chat/messages',
      );

      // The reason lives in extras because it is not the `code` field the rest
      // of the API uses.
      final reason = ChatBlockReason.parse(error.extras['reason']);
      expect(reason, ChatBlockReason.paymentPending);
      expect(reason.isFixableByFunding, isTrue);
    });

    test('other block reasons are not presented as fixable', () {
      expect(ChatBlockReason.parse('match_closed').isFixableByFunding, isFalse);
      expect(ChatBlockReason.parse('not_a_party').isFixableByFunding, isFalse);
    });

    test('a thread stays readable after it stops being writable', () {
      final thread = ChatThread.fromJson(const {
        'match_id': 55,
        'deal_id': 123,
        'counterparty_id': 9,
        'counterparty_name': 'Amina K.',
        'route': 'Algiers → Paris',
        'status': 'completed',
        'can_send': false,
        'unread_count': 0,
      });

      // Listed and readable; the composer is gated on `can_send` alone.
      expect(thread.canSend, isFalse);
      expect(thread.route, 'Algiers → Paris');
    });
  });

  group('error envelopes', () {
    test('the structured domain envelope', () {
      final error = _failure(
        statusCode: 409,
        data: const {
          'code': 'reward_below_minimum',
          'detail': 'Offer at least 8 EUR.',
          'minimum_reward_eur_cents': 800,
        },
        path: '/api/matches/propose',
      );

      expect(error.code.raw, 'reward_below_minimum');
      expect(error.intExtra('minimum_reward_eur_cents'), 800);
      expect(error.kind, ApiFailureKind.conflict);
    });

    test('a DRF field-error dict', () {
      final error = _failure(
        statusCode: 400,
        data: const {
          'email': ['An account with this email already exists.'],
          'wilaya': ['Invalid wilaya code.'],
        },
        path: '/api/auth/sign-up',
      );

      expect(error.kind, ApiFailureKind.validation);
      expect(error.fieldErrors['email'], isNotEmpty);
      expect(error.fieldErrors['wilaya'], isNotEmpty);
    });

    test('a bare detail string with no code', () {
      final error = _failure(
        statusCode: 403,
        data: const {'detail': 'Not a party to this match.'},
        path: '/api/matches/1',
      );

      expect(error.kind, ApiFailureKind.forbidden);
      expect(error.code.isKnownToServer, isFalse);
    });

    test('the Go KYC service\'s own envelope', () {
      final error = _failure(
        statusCode: 415,
        data: const {'error': 'front: unsupported content type'},
        path: '/kyc/submit',
      );

      // Normalised into the same failure model as everything else, so screens
      // do not need a second error path for one service.
      expect(error.statusCode, 415);
      expect(error.serverDetail, isNotNull);
    });

    test('stale-state codes are recognised as such', () {
      for (final code in [
        'request_not_open',
        'request_already_matched',
        'offer_not_pending',
        'capacity_exceeded',
        'journey_not_active',
      ]) {
        final error = _failure(
          statusCode: 409,
          data: {'code': code, 'detail': 'x'},
          path: '/api/x',
        );
        expect(
          error.code.impliesStaleClientState,
          isTrue,
          reason: '$code should tell the client to refresh',
        );
      }
    });

    test('retired surfaces are recognised as such', () {
      final error = _failure(
        statusCode: 410,
        data: const {'code': 'legacy_matching_flow_retired', 'detail': 'x'},
        path: '/api/matches/apply',
      );
      expect(error.code.isRetiredSurface, isTrue);
    });
  });

  group('discovery', () {
    test('a traveller candidate carries no recommendation', () {
      // The server withholds it from compatible-requests on purpose. A client
      // that showed one would be inventing a number.
      final pricing = PricingQuote.maybe(const {
        'currency': 'EUR',
        'minimum_reward_eur_cents': 800,
        'minimum_economics': {
          'traveler_reward_minor': 800,
          'commission_rate_bps': 1000,
          'platform_fee_minor': 80,
          'sender_total_minor': 880,
        },
        'commission_rate_bps': 1000,
      })!;

      expect(pricing.minimumReward!.minorUnits, 800);
      expect(pricing.hasRecommendation, isFalse);
      expect(pricing.recommendedReward, isNull);
    });

    test('a sender candidate carries one', () {
      final pricing = PricingQuote.maybe(const {
        'currency': 'EUR',
        'minimum_reward_eur_cents': 800,
        'recommended_reward_eur_cents': 1200,
        'commission_rate_bps': 1000,
      })!;
      expect(pricing.hasRecommendation, isTrue);
      expect(pricing.recommendedReward!.minorUnits, 1200);
    });

    test('a proposal target requires a server-resolved leg range', () {
      final withRange = DiscoveryCandidate.fromJson(const {
        'delivery_request': {'id': 55, 'sender_id': 20},
        'journey': {
          'id': 77,
          'traveler_id': 30,
          'start_leg_id': 10,
          'end_leg_id': 12,
        },
      });
      expect(withRange.proposalTarget, isNotNull);
      expect(withRange.proposalTarget!.startLegId, 10);

      final withoutRange = DiscoveryCandidate.fromJson(const {
        'delivery_request': {'id': 55, 'sender_id': 20},
        'journey': {'id': 77, 'traveler_id': 30},
      });
      // No range means proposing is impossible, and the UI must not offer it.
      expect(withoutRange.proposalTarget, isNull);
    });
  });

  group('delivery requests', () {
    test('the proposed reward is intent, kept separate from a price', () {
      final request = DeliveryRequest.fromJson(const {
        'id': 55,
        'sender_id': 20,
        'status': 'open',
        'schema_version': 2,
        'sender_proposed_reward_eur_cents': 3000,
        'title': 'Laptop',
        'description': 'Boxed',
        'category': 'electronics',
      });

      expect(request.senderProposedReward!.minorUnits, 3000);
      expect(request.isV1, isTrue);
      expect(request.category, ItemCategory.electronics);
    });

    test('all five safety declarations are tracked separately', () {
      const none = SafetyAcknowledgements.none();
      expect(none.allConfirmed, isFalse);

      final all = SafetyAcknowledgements.fromJson(const {
        'description_is_accurate': true,
        'item_is_legal': true,
        'no_prohibited_goods': true,
        'declared_value_is_accurate': true,
        'customs_responsibilities_understood': true,
      });
      expect(all.allConfirmed, isTrue);
      expect(all.toJson().length, 5);
    });
  });
}
