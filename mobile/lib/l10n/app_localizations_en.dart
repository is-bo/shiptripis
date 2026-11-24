// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class LEn extends L {
  LEn([String locale = 'en']) : super(locale);

  @override
  String get payoutLegalCountryTitle => 'Payout account country';

  @override
  String get payoutLegalCountryLabel => 'Country';

  @override
  String get payoutLegalCountryBody =>
      'Select your legal Stripe account country to consent to payout setup. If your country is not listed, use DZD payouts.';

  @override
  String get appName => 'Wassla';

  @override
  String get actionContinue => 'Continue';

  @override
  String get actionCancel => 'Cancel';

  @override
  String get actionSave => 'Save';

  @override
  String get actionRetry => 'Try again';

  @override
  String get actionDone => 'Done';

  @override
  String get actionBack => 'Back';

  @override
  String get actionNext => 'Next';

  @override
  String get actionConfirm => 'Confirm';

  @override
  String get actionEdit => 'Edit';

  @override
  String get actionCopy => 'Copy';

  @override
  String get actionCopied => 'Copied';

  @override
  String get actionRefresh => 'Refresh';

  @override
  String get actionSeeAll => 'See all';

  @override
  String get actionGoBack => 'Go back';

  @override
  String get actionNotNow => 'Not now';

  @override
  String get actionOpen => 'Open';

  @override
  String get actionAdd => 'Add';

  @override
  String get actionSelect => 'Select';

  @override
  String get actionClear => 'Clear';

  @override
  String get actionContactSupport => 'Contact support';

  @override
  String get navHome => 'Home';

  @override
  String get navDeliveries => 'Deliveries';

  @override
  String get navChat => 'Chat';

  @override
  String get navProfile => 'Profile';

  @override
  String get navNotifications => 'Notifications';

  @override
  String navNotificationsWithCount(int count) {
    return 'Notifications, $count unread';
  }

  @override
  String get roleSender => 'Sending';

  @override
  String get roleTraveler => 'Traveling';

  @override
  String get roleSwitchLabel => 'Switch role';

  @override
  String get authSignIn => 'Sign in';

  @override
  String get authSignUp => 'Create account';

  @override
  String get authSignOut => 'Sign out';

  @override
  String get authEmail => 'Email';

  @override
  String get authPassword => 'Password';

  @override
  String get authFullName => 'Full name';

  @override
  String get authForgotPassword => 'Forgot your password?';

  @override
  String get authNoAccount => 'New to Wassla?';

  @override
  String get authHaveAccount => 'Already have an account?';

  @override
  String get authVerifyEmailTitle => 'Confirm your email';

  @override
  String authVerifyEmailBody(String email) {
    return 'We sent a link to $email. Confirm it to keep your account secure.';
  }

  @override
  String get authSignOutConfirmTitle => 'Sign out?';

  @override
  String get authSignOutConfirmBody =>
      'You\'ll need to sign in again to see your deliveries.';

  @override
  String get validationRequired => 'This is required';

  @override
  String get validationCodeSixDigits => 'Code must be 6 digits';

  @override
  String get validationCcpNumberDigits =>
      'CCP account number must contain 1 to 20 digits';

  @override
  String get validationCcpKeyDigits => 'CCP key must be exactly 2 digits';

  @override
  String get validationRipDigits => 'RIP must be exactly 20 digits';

  @override
  String get validationEmailInvalid => 'Enter a valid email address';

  @override
  String get validationPasswordTooShort => 'Use at least 8 characters';

  @override
  String get validationNumberInvalid => 'Enter a number';

  @override
  String get validationMoneyPrecision => 'Use no more than 2 decimal places';

  @override
  String get validationMustBePositive => 'Enter a number greater than zero';

  @override
  String validationTooLong(int max) {
    return 'Use at most $max characters';
  }

  @override
  String get validationSelectOne => 'Choose one';

  @override
  String get validationDateInPast => 'Choose a date in the future';

  @override
  String get validationDeadlineBeforeReady =>
      'The deadline has to be after the parcel is ready';

  @override
  String get stateOfflineTitle => 'You\'re offline';

  @override
  String get stateOfflineBody =>
      'Check your connection. We\'ll load this as soon as you\'re back.';

  @override
  String get stateTimeoutTitle => 'That took too long';

  @override
  String get stateTimeoutBody =>
      'The server didn’t answer in time. Nothing was lost — try again.';

  @override
  String get stateServerErrorTitle => 'Something went wrong on our side';

  @override
  String get stateServerErrorBody =>
      'This isn\'t your fault. Try again in a moment.';

  @override
  String get stateNotFoundTitle => 'Not found';

  @override
  String get stateNotFoundBody =>
      'This may have been removed, or it was never yours to see.';

  @override
  String get stateForbiddenTitle => 'You can\'t do that here';

  @override
  String get stateForbiddenBody => 'Your account doesn\'t have access to this.';

  @override
  String get stateSessionExpiredTitle => 'Please sign in again';

  @override
  String get stateSessionExpiredBody =>
      'Your session ended. Sign in to pick up where you left off.';

  @override
  String get stateRateLimitedTitle => 'Too many attempts';

  @override
  String get stateRateLimitedBody => 'Wait a moment before trying again.';

  @override
  String get stateUnexpectedTitle => 'Something unexpected happened';

  @override
  String get stateUnexpectedBody =>
      'We couldn\'t complete that. Try again, and tell us if it keeps happening.';

  @override
  String get stateAppOutdatedTitle => 'This version is out of date';

  @override
  String get stateAppOutdatedBody =>
      'Update Wassla to continue. This part of the app no longer works on this version.';

  @override
  String get staleTitle => 'This has changed';

  @override
  String get staleRefreshAction => 'Refresh';

  @override
  String get staleRequestNotOpen => 'This request isn\'t open any more.';

  @override
  String get staleRequestAlreadyMatched =>
      'This request has already been matched with a traveler.';

  @override
  String get staleJourneyNotActive => 'This journey isn\'t active any more.';

  @override
  String get staleOfferNotPending => 'This offer has already been answered.';

  @override
  String get staleMatchNotPending =>
      'This match isn\'t waiting on anyone any more.';

  @override
  String get staleCapacityExceeded =>
      'There isn\'t enough space left on this journey.';

  @override
  String get staleRewardBelowMinimum => 'The minimum reward has changed.';

  @override
  String get staleRouteChanged =>
      'The route details changed. We\'ve refreshed the price.';

  @override
  String get staleKycInvalid =>
      'Your identity check needs attention before you can do this.';

  @override
  String get staleTicketInvalid =>
      'A ticket on this journey needs attention before it can match.';

  @override
  String get staleReservationExpired => 'Your reserved space expired.';

  @override
  String get staleDealClosed => 'This delivery is closed.';

  @override
  String get stalePayoutProfileInvalid =>
      'Your payout details changed while you were on this page. Pull down to refresh, then try again.';

  @override
  String get stalePayoutCountryUnsupported =>
      'EUR payouts are not available in that country yet. Choose another country, or use DZD payouts.';

  @override
  String get staleStripeConnectUnavailable =>
      'EUR payout setup is temporarily unavailable. Your details are unchanged — please try again shortly.';

  @override
  String get staleStripeConnectProviderError =>
      'Stripe could not complete the request. Nothing was changed; please try again shortly.';

  @override
  String get stalePayoutSetupInvalid =>
      'That payout setup could not be completed. Check the details and try again.';

  @override
  String get stalePayoutEvidenceUnavailable =>
      'The uploaded document is no longer available. Please upload the crossed cheque again.';

  @override
  String get staleOfferExpired => 'This offer is no longer available.';

  @override
  String get moneyYouPay => 'You pay';

  @override
  String get moneyYouReceive => 'You receive';

  @override
  String get moneyYourEarnings => 'Your earnings';

  @override
  String get moneyTotalYouReceive => 'Total you receive';

  @override
  String get moneyTravelerReceives => 'Traveler receives';

  @override
  String get moneyPlatformFee => 'Wassla fee';

  @override
  String get moneyMinimumReward => 'Minimum reward';

  @override
  String get moneyTotal => 'Total';

  @override
  String get moneyDepositPaid => 'Deposit already paid';

  @override
  String get moneyRemainingToPay => 'Remaining to pay';

  @override
  String get moneyRefundToYou => 'Refund to you';

  @override
  String get moneyTravelerCompensation => 'Traveler compensation';

  @override
  String get moneyBreakdownTitle => 'How this adds up';

  @override
  String get moneyRewardNotReduced =>
      'The traveler receives this full amount. The Wassla fee is added on top, not taken out of it.';

  @override
  String get moneyDepositNotExtra =>
      'This is credited towards your final payment. It isn\'t an extra fee.';

  @override
  String get moneyAmountCharged => 'You\'ll be charged';

  @override
  String moneyExchangeRate(String rate) {
    return 'Rate: €1 = $rate DA';
  }

  @override
  String get moneyChargedInDinars =>
      'Chargily charges in Algerian dinars. The delivery price stays in euros.';

  @override
  String get homeSenderGreeting => 'Send something home';

  @override
  String get homeTravelerGreeting => 'Earn on a trip you\'re already taking';

  @override
  String get homeCreateRequest => 'Send a parcel';

  @override
  String get homeCreateJourney => 'Add a journey';

  @override
  String get homeNeedsYourAction => 'Needs you';

  @override
  String get homeInProgress => 'In progress';

  @override
  String get homeNothingNeedsYou => 'Nothing needs you right now';

  @override
  String get homeEmptySenderTitle => 'Nothing on the way yet';

  @override
  String get homeEmptySenderBody =>
      'Post what you want to send and travelers heading that way will see it.';

  @override
  String get homeEmptyTravelerTitle => 'No journeys yet';

  @override
  String get homeEmptyTravelerBody =>
      'Add the trip you\'re taking and we\'ll show you parcels along your route.';

  @override
  String get deliveriesTitle => 'Deliveries';

  @override
  String get dealUnavailableTitle => 'Delivery unavailable';

  @override
  String get dealUnavailableBody =>
      'This delivery is not available for this account. It may have changed, or the link may be out of date.';

  @override
  String get deliveriesFilterActive => 'Active';

  @override
  String get deliveriesFilterAwaitingYou => 'Needs you';

  @override
  String get deliveriesFilterHistory => 'History';

  @override
  String get deliveriesSenderSection => 'Sending';

  @override
  String get deliveriesJourneysSection => 'My journeys';

  @override
  String get deliveriesEmptyActiveTitle => 'Nothing active';

  @override
  String get deliveriesEmptyActiveBody =>
      'Deliveries you\'re sending or carrying will appear here.';

  @override
  String get deliveriesEmptyHistoryTitle => 'No history yet';

  @override
  String get deliveriesEmptyHistoryBody =>
      'Completed and cancelled deliveries stay here.';

  @override
  String get deliveriesEmptyAwaitingTitle => 'You\'re all caught up';

  @override
  String get deliveriesEmptyAwaitingBody => 'Nothing is waiting on you.';

  @override
  String get requestStatusAwaitingDeposit => 'Deposit needed';

  @override
  String get requestStatusOpen => 'Finding a traveler';

  @override
  String get requestStatusMatched => 'Matched';

  @override
  String get requestStatusInTransit => 'On the way';

  @override
  String get requestStatusDelivered => 'Delivered';

  @override
  String get requestStatusCompleted => 'Completed';

  @override
  String get requestStatusCancelled => 'Cancelled';

  @override
  String get requestStatusExpired => 'Expired';

  @override
  String get dealStatusOfferAccepted => 'Offer accepted';

  @override
  String get dealStatusPaymentRequired => 'Payment needed';

  @override
  String get dealStatusFunded => 'Paid and protected';

  @override
  String get dealStatusPickupReady => 'Ready for pickup';

  @override
  String get dealStatusPickedUp => 'Picked up';

  @override
  String get dealStatusInTransit => 'On the way';

  @override
  String get dealStatusDeliveryReady => 'Ready to deliver';

  @override
  String get dealStatusDeliveryConfirmed => 'Delivered';

  @override
  String get dealStatusProtection => 'Payment protected';

  @override
  String get dealStatusCompleted => 'Completed';

  @override
  String get dealStatusCancelled => 'Cancelled';

  @override
  String get dealStatusDisputed => 'Under dispute';

  @override
  String get dealStatusRefunded => 'Refunded';

  @override
  String get dealStatusPartiallyRefunded => 'Partly refunded';

  @override
  String get dealStatusPaymentFailed => 'Payment failed';

  @override
  String get dealStatusExpired => 'Expired';

  @override
  String get requestCreateTitle => 'Send a parcel';

  @override
  String get requestStepRoute => 'Route';

  @override
  String get requestStepParcel => 'Parcel';

  @override
  String get requestStepTiming => 'Timing';

  @override
  String get requestStepReview => 'Review';

  @override
  String get requestPickupLocation => 'Pickup from';

  @override
  String get requestDeliveryLocation => 'Deliver to';

  @override
  String get requestPickupHint => 'Where the traveler collects the parcel';

  @override
  String get requestDeliveryHint =>
      'Where the parcel is handed to the recipient';

  @override
  String get requestReadyFrom => 'Ready from';

  @override
  String get requestDeadline => 'Must arrive by';

  @override
  String get requestTitle => 'What are you sending?';

  @override
  String get requestTitleHint => 'Documents, medicine, clothes…';

  @override
  String get requestDescription => 'Description';

  @override
  String get requestDescriptionHint =>
      'Describe it accurately. This is what the traveler agrees to carry.';

  @override
  String get requestCategory => 'Category';

  @override
  String get requestWeight => 'Weight';

  @override
  String get requestWeightUnit => 'kg';

  @override
  String get requestDimensions => 'Size';

  @override
  String get requestLength => 'Length';

  @override
  String get requestWidth => 'Width';

  @override
  String get requestHeight => 'Height';

  @override
  String get requestDimensionUnit => 'cm';

  @override
  String get requestDeclaredValue => 'Declared value';

  @override
  String get requestDeclaredValueHelp =>
      'What it would cost to replace. Used if something goes wrong.';

  @override
  String get requestPhotos => 'Photos';

  @override
  String get requestHandlingNotes => 'Handling notes';

  @override
  String get requestHandlingNotesHint => 'Anything the traveler should know';

  @override
  String get requestFragile => 'Fragile';

  @override
  String get requestAcknowledgementsTitle => 'Before you post this';

  @override
  String get requestAckDescriptionAccurate =>
      'My description of this parcel is accurate';

  @override
  String get requestAckItemLegal => 'This item is legal to send and to receive';

  @override
  String get requestAckNoProhibited => 'It contains no prohibited goods';

  @override
  String get requestAckValueAccurate => 'The declared value is accurate';

  @override
  String get requestAckCustoms =>
      'I understand I\'m responsible for any customs or import rules that apply';

  @override
  String get requestProhibitedItemsLink => 'See what can\'t be sent';

  @override
  String get requestSizeExplainer =>
      'Size matters as much as weight. We charge on whichever is greater.';

  @override
  String get requestCreated => 'Posted';

  @override
  String get depositTitle => 'Publish your request';

  @override
  String get depositExplainer =>
      'Paid now to list your request. 100% credited toward your final delivery payment.';

  @override
  String get depositAmount => 'Deposit';

  @override
  String get depositCreditedNote =>
      'It\'s credited towards your final payment when a traveler accepts.';

  @override
  String get depositRefundNote =>
      'If nobody takes it, or you cancel before accepting an offer, you get it back in full.';

  @override
  String get depositGuidanceTitle => 'Deposit guidance';

  @override
  String get depositSuggestedTotal => 'Wassla suggested total';

  @override
  String get depositWholeAmount => 'Your total for this delivery';

  @override
  String get pricingUpdating => 'Updating the price';

  @override
  String get depositRecommended => 'Recommended deposit';

  @override
  String get depositMinimumAllowed => 'Minimum deposit';

  @override
  String get depositGuidanceNote =>
      'Wassla calculates the deposit from the suggested total and applies the current minimum and maximum. This is credit toward the final payment, not an extra fee.';

  @override
  String get depositPayAction => 'Pay deposit and publish';

  @override
  String get journeyTitle => 'Journey';

  @override
  String get journeyCreateTitle => 'Add a journey';

  @override
  String get journeyFrom => 'From';

  @override
  String get journeyTo => 'To';

  @override
  String get journeyLegs => 'Legs';

  @override
  String get journeyModeFlight => 'Flight';

  @override
  String get journeyModeDrive => 'Drive';

  @override
  String get journeyDeparts => 'Departs';

  @override
  String get journeyArrives => 'Arrives';

  @override
  String get journeyCapacity => 'Space you can carry';

  @override
  String get journeyFlightNumber => 'Flight number';

  @override
  String get journeyFlightNumberHint => 'e.g. AH1006';

  @override
  String get journeyPublish => 'Publish journey';

  @override
  String get journeyCancel => 'Cancel journey';

  @override
  String get journeyStatusDraft => 'Draft';

  @override
  String get journeyStatusPendingVerification => 'Being checked';

  @override
  String get journeyStatusActive => 'Live';

  @override
  String get journeyStatusInProgress => 'Under way';

  @override
  String get journeyStatusCompleted => 'Completed';

  @override
  String get journeyStatusCancelled => 'Cancelled';

  @override
  String get journeyStatusExpired => 'Expired';

  @override
  String get journeyEmptyLegsTitle => 'Add your first leg';

  @override
  String get journeyEmptyLegsBody =>
      'A journey is made of legs. Paris to Algiers by plane, then Algiers to Jijel by road.';

  @override
  String get journeyRouteShape => 'Your route';

  @override
  String get journeyModeLabel => 'How you\'re traveling';

  @override
  String get journeyChooseDateTime => 'Choose date and time';

  @override
  String get journeyArriveHelp =>
      'Needed to match you with senders: their deadline is checked against this time.';

  @override
  String get journeyMaxLegsReached => 'A journey can hold at most 20 legs.';

  @override
  String get journeyCapacityInvalid =>
      'Enter between 0.01 and 200 kg, to two decimal places.';

  @override
  String get journeyLegDepartRequired => 'Say when this leg departs.';

  @override
  String get journeyLegDepartNotAfterPrevious =>
      'This leg has to depart after the leg before it.';

  @override
  String get journeyLegDepartBeforePreviousArrival =>
      'This leg departs before the previous one lands.';

  @override
  String get journeyLegArriveRequired => 'Add when this leg arrives.';

  @override
  String get journeyLegArriveBeforeDepart =>
      'Arrival has to be after departure.';

  @override
  String get journeyNotesLabel => 'Anything senders should know';

  @override
  String get journeyNotesHint =>
      'No liquids, small parcels only, meeting near the terminal…';

  @override
  String get journeySaveDraft => 'Save journey';

  @override
  String get journeyCreatedDraft =>
      'Saved as a draft. Add flight proof, then publish it.';

  @override
  String get journeyDraftNextSteps =>
      'Nothing is visible to senders yet. Publish it when your flight proof is approved.';

  @override
  String get journeyLegsNeedProofTitle => 'Tickets to check';

  @override
  String get journeyPublishBlockedProof =>
      'Every flight and ferry leg needs an approved ticket before this can go live.';

  @override
  String get journeyPublished =>
      'Your journey is live. Senders heading your way can see it.';

  @override
  String get journeyErrorNotPublishable =>
      'This journey can\'t be published from where it is now.';

  @override
  String get journeyErrorNoLegs =>
      'This journey has no legs, so there is nothing to publish.';

  @override
  String get journeyErrorLegPositions =>
      'The legs are numbered wrongly. Cancel this journey and create it again.';

  @override
  String get journeyErrorEndpointsMismatch =>
      'The first and last legs don\'t match the journey\'s start and destination.';

  @override
  String get journeyErrorLegEndpoints =>
      'One leg starts or ends somewhere the route doesn\'t pass through.';

  @override
  String get journeyErrorLegTime => 'One leg arrives before it departs.';

  @override
  String get journeyErrorLegArrivalRequired =>
      'Every leg needs an arrival time before you publish. Without it, no sender can be matched with this trip.';

  @override
  String get journeyErrorLegsDisconnected =>
      'The legs don\'t join up into one route.';

  @override
  String get journeyErrorLegTimeOrder => 'The legs aren\'t in time order.';

  @override
  String get journeyErrorNotOwned => 'This journey belongs to someone else.';

  @override
  String get journeyCancelConfirmTitle => 'Cancel this journey?';

  @override
  String get journeyCancelConfirmBody =>
      'Senders stop seeing it and any space they were holding is released. This can\'t be undone.';

  @override
  String get journeyCancelled => 'Journey cancelled.';

  @override
  String journeyReleasedAllocations(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count reserved spaces were released.',
      one: '1 reserved space was released.',
      zero: 'No reserved space was being held.',
    );
    return '$_temp0';
  }

  @override
  String get journeyErrorNotCancellable =>
      'This journey can\'t be cancelled from where it is now.';

  @override
  String get journeyErrorHasFundedDeal =>
      'A paid delivery is riding on this journey. Sort that delivery out first.';

  @override
  String get journeyMatchesInfoTitle => 'Senders make the first move';

  @override
  String get journeyMatchesInfoBody =>
      'You can\'t offer on these. If one of these senders picks you, their offer arrives in Deliveries.';

  @override
  String get routeStopsTitle => 'Your stops';

  @override
  String get routeStopsHelp =>
      'Add where you start, where you end, and anywhere you stop on the way. We work out the legs between them.';

  @override
  String get routeStopLabel => 'Stop';

  @override
  String get routeAddStopHere => 'Add a stop here';

  @override
  String get routeAddStopTitle => 'Where do you stop?';

  @override
  String get routeChangeStopTitle => 'Change this stop';

  @override
  String get routeRemoveStop => 'Remove this stop';

  @override
  String get routeMoveStopEarlier => 'Move this stop earlier';

  @override
  String get routeMoveStopLater => 'Move this stop later';

  @override
  String get routeStopSameAsPrevious =>
      'This is the same city as the stop before it. Choose somewhere else, or remove one of them.';

  @override
  String routeSegmentBetween(String from, String to) {
    return '$from to $to';
  }

  @override
  String get routeFlightOnlyExplainer =>
      'There\'s no road between these two countries, so this part has to be a flight.';

  @override
  String get routeFlightAirportsRequired =>
      'A flight starts and ends at an airport. Choose the airport for each end of this part.';

  @override
  String get routeAirportNeededTitle => 'Which airport?';

  @override
  String routeAirportNeededBody(String stop) {
    return 'You\'re flying from $stop, so we need the airport. The stop stays $stop — we just need to know how you leave it.';
  }

  @override
  String get routeChooseAirport => 'Choose airport';

  @override
  String get routeChooseAirportTitle => 'Which airport?';

  @override
  String get routeChangeAirport => 'Change';

  @override
  String routeAirportChosen(String airport) {
    return 'Flying via $airport';
  }

  @override
  String get routeErrorModeUnavailable =>
      'That part of the route can\'t be driven. There\'s no road between those two countries, so it has to be a flight.';

  @override
  String get journeyEditTitle => 'Edit journey';

  @override
  String get journeyEditAction => 'Edit';

  @override
  String get journeySaveChanges => 'Save changes';

  @override
  String get journeyEditSaved => 'Journey updated.';

  @override
  String journeyEditSavedProofReset(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other:
          'Journey updated. $count flight proofs went back for review because those flights changed.',
      one:
          'Journey updated. One flight proof went back for review because that flight changed.',
    );
    return '$_temp0';
  }

  @override
  String get journeyEditBlockedTitle => 'This journey can\'t be edited';

  @override
  String get journeyEditBlockedStatus =>
      'This journey can no longer be edited because it is already published. Cancel it and create a new one if the route has changed.';

  @override
  String get journeyEditBlockedDependent =>
      'This journey can no longer be edited because a sender is already counting on this route.';

  @override
  String get journeyEditStaleRoute =>
      'This route changed while you were editing it. Reopen it and try again.';

  @override
  String get journeyEditProofNotice =>
      'Changing a flight or ferry leg\'s places, number or times means its ticket no longer shows that trip, so we\'ll check it again.';

  @override
  String get journeyEditProofWarningTitle =>
      'Your ticket will be checked again';

  @override
  String get journeyEditProofWarningBody =>
      'You\'ve changed a leg that already has a ticket. That ticket no longer shows this trip, so it goes back for review and the journey can\'t go live until it\'s approved again.';

  @override
  String get proofErrorStorageUnavailable =>
      'We couldn\'t store your file just now.';

  @override
  String get proofRetryTitle => 'Upload didn\'t finish';

  @override
  String get proofRetryFileKept => 'Your image is still selected.';

  @override
  String get proofRetry => 'Try again';

  @override
  String get proofTitle => 'Ticket proof';

  @override
  String get proofExplainerFlight =>
      'Upload your boarding pass or booking confirmation. We check it before your journey can match parcels.';

  @override
  String get proofDriveNotRequired => 'Driving legs don\'t need any proof.';

  @override
  String get proofUpload => 'Upload proof';

  @override
  String get proofStatusMissing => 'Not uploaded';

  @override
  String get proofStatusPending => 'Being reviewed';

  @override
  String get proofStatusApproved => 'Approved';

  @override
  String get proofStatusRejected => 'Not accepted';

  @override
  String proofRejectedReason(String reason) {
    return 'Reason: $reason';
  }

  @override
  String get proofKindLabel => 'What are you uploading?';

  @override
  String get proofKindTicket => 'Ticket';

  @override
  String get proofKindBoardingPass => 'Boarding pass';

  @override
  String get proofKindBookingConfirmation => 'Booking';

  @override
  String get proofFormatRule =>
      'JPEG, PNG or WebP, up to 10 MB. We check the file itself, so renaming one won\'t get it through.';

  @override
  String get proofFileTooLarge =>
      'That image is over 10 MB. Pick a smaller one.';

  @override
  String get proofFileTypeNotAllowed =>
      'Only JPEG, PNG and WebP images are accepted.';

  @override
  String get proofChooseImage => 'Choose an image';

  @override
  String get proofTakePhoto => 'Take a photo';

  @override
  String get proofSelectedFile => 'Ready to upload';

  @override
  String get proofUploading => 'Uploading your proof…';

  @override
  String get proofUploaded => 'Proof received. We\'ll review it shortly.';

  @override
  String get proofExistingTitle => 'What you\'ve already sent';

  @override
  String get proofErrorUploadClosed =>
      'This journey is past the point where proof can be added.';

  @override
  String proofLegLabel(int position, String from, String to) {
    return 'Leg $position: $from to $to';
  }

  @override
  String get kycTitle => 'Identity check';

  @override
  String get kycWhyTitle => 'Why we ask';

  @override
  String get kycWhyBody =>
      'Senders are handing a stranger something that matters to them. Verifying travelers is what makes that reasonable.';

  @override
  String get kycStatusNotStarted => 'Not started';

  @override
  String get kycStatusPending => 'Being reviewed';

  @override
  String get kycStatusApproved => 'Verified';

  @override
  String get kycStatusRejected => 'Not approved';

  @override
  String get kycStartAction => 'Start identity check';

  @override
  String get kycRetryAction => 'Try again';

  @override
  String get kycPendingBody =>
      'We\'re reviewing your documents. This usually takes less than a day.';

  @override
  String get kycApprovedBody =>
      'You\'re verified. You can publish journeys and carry parcels.';

  @override
  String get kycRejectedBody =>
      'We couldn\'t verify your documents. You can submit again.';

  @override
  String get kycRequiredForJourney =>
      'You need to be verified before you can publish a journey.';

  @override
  String get kycDocumentType => 'Document type';

  @override
  String get kycFrontImage => 'Front of document';

  @override
  String get kycBackImage => 'Back of document';

  @override
  String get kycSelfie => 'Selfie';

  @override
  String get discoveryTravelersTitle => 'Travelers for this parcel';

  @override
  String get discoveryRequestsTitle => 'Parcels along your route';

  @override
  String get discoveryEmptyTravelersBody =>
      'Nobody is going your way right now. We\'ll notify you when someone is.';

  @override
  String get discoveryEmptyRequestsTitle => 'No parcels yet';

  @override
  String get discoveryEmptyRequestsBody =>
      'Nothing matches your journey right now. We\'ll notify you when something does.';

  @override
  String get findTravelersRouteFitExcellent => 'Excellent route match';

  @override
  String get findTravelersRouteFitGood => 'Good route match';

  @override
  String get findTravelersRouteFitCompatible => 'Compatible route';

  @override
  String get findTravelersTimingComfortable => 'Arrives with time to spare';

  @override
  String get findTravelersTimingFits => 'Fits your delivery window';

  @override
  String get findTravelersNewTraveller => 'New';

  @override
  String get findTravelersViewTrip => 'View trip';

  @override
  String get findTravelersWhyThisFits => 'Why this trip fits';

  @override
  String get findTravelersEmptyTitle => 'No travelers going your way yet';

  @override
  String get findTravelersEmptyBody =>
      'Your request stays active. We’ll tell you as soon as somebody posts a trip along your route.';

  @override
  String get findTravelersIneligibleAwaitingDeposit =>
      'Pay the posting deposit to publish this request.';

  @override
  String get findTravelersIneligibleAlreadyMatched =>
      'This parcel already has a traveler.';

  @override
  String get findTravelersIneligibleClosed => 'This request is closed.';

  @override
  String get findTravelersIneligibleInProgress =>
      'This parcel is already on its way.';

  @override
  String get findTravelersDirectLeg => 'Carried in one leg';

  @override
  String get findTravelersWholeTripMatches => 'This whole trip is your route';

  @override
  String get findTravelersIdentityVerified => 'Identity verified';

  @override
  String get findTravelersFlightProofApproved => 'Flight ticket verified';

  @override
  String get findTravelersSortBestMatch => 'Best match';

  @override
  String get findTravelersSortSoonest => 'Soonest trip';

  @override
  String get findTravelersShowMore => 'Show more travelers';

  @override
  String findTravelersStop(String city, String iata) {
    return '$city · $iata';
  }

  @override
  String findTravelersTransfers(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count transfers',
      one: '1 transfer',
    );
    return '$_temp0';
  }

  @override
  String findTravelersPicksUpIn(String place) {
    return 'Picks up in $place';
  }

  @override
  String findTravelersArrivesIn(String place) {
    return 'Arrives in $place';
  }

  @override
  String findTravelersArrivesBeforeDeadline(String arrival, String deadline) {
    return 'Arrives $arrival, before your $deadline deadline';
  }

  @override
  String findTravelersHasRoomFor(String weight) {
    return 'Has room for $weight kg';
  }

  @override
  String findTravelersDeliveries(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count deliveries',
      one: '1 delivery',
      zero: 'No deliveries yet',
    );
    return '$_temp0';
  }

  @override
  String get discoveryDetourSmall => 'Barely a detour';

  @override
  String get discoveryDetourModerate => 'Small detour';

  @override
  String get discoveryDetourLarge => 'Noticeable detour';

  @override
  String discoveryRatingCount(String rating, int count) {
    return '$rating ($count)';
  }

  @override
  String get discoveryNoRatingsYet => 'No ratings yet';

  @override
  String get offerProposeTitle => 'Make an offer';

  @override
  String get offerProposeExplainer =>
      'You choose what the traveler earns. They can accept, decline, or come back with a different amount.';

  @override
  String get offerRewardLabel => 'Traveler\'s reward';

  @override
  String get offerUseRecommended => 'Use suggested';

  @override
  String get offerSend => 'Send offer';

  @override
  String get offerSendCounter => 'Send counter-offer';

  @override
  String get offerCounter => 'Counter';

  @override
  String get offerAccept => 'Accept';

  @override
  String get offerDecline => 'Decline';

  @override
  String get offerWithdraw => 'Withdraw';

  @override
  String get offerAwaitingTraveler => 'Waiting for the traveler';

  @override
  String get offerAwaitingSender => 'Waiting for the sender';

  @override
  String get offerAwaitingYou => 'Your move';

  @override
  String offerYouProposed(String amount) {
    return 'You offered $amount';
  }

  @override
  String get offerHistoryTitle => 'Offer history';

  @override
  String get offerStatusPending => 'Waiting';

  @override
  String get offerStatusAccepted => 'Accepted';

  @override
  String get offerStatusDeclined => 'Declined';

  @override
  String get offerStatusWithdrawn => 'Withdrawn';

  @override
  String get offerStatusExpired => 'Expired';

  @override
  String get offerDeclineConfirmTitle => 'Decline this offer?';

  @override
  String get offerDeclineConfirmBody =>
      'The other side will be told. You can still negotiate afterwards.';

  @override
  String get offerAcceptTravelerBody =>
      'Space on your journey is reserved as soon as you accept. The sender then has to pay.';

  @override
  String get offerAcceptSenderBody =>
      'Once you accept, you\'ll be asked to pay so the delivery can start.';

  @override
  String offerAcceptSenderConfirmTitle(String amount) {
    return 'Pay $amount for this delivery?';
  }

  @override
  String offerAcceptTravelerConfirmTitle(String amount) {
    return 'Receive $amount for this delivery?';
  }

  @override
  String get offerCounterTravelerExplainer =>
      'Choose how much you receive for this delivery. The sender can accept, decline, or counter again.';

  @override
  String get offerYourOfferTitle => 'Your offer';

  @override
  String get offerTravelerCounterTitle => 'Traveler\'s counter-offer';

  @override
  String get offerYourCounterTitle => 'Your counter-offer';

  @override
  String get offerSenderOfferTitle => 'Sender\'s offer';

  @override
  String offerYouWouldPay(String amount) {
    return 'You would pay $amount';
  }

  @override
  String offerTravelerAsks(String amount) {
    return 'Traveler asks $amount';
  }

  @override
  String offerYouWouldReceive(String amount) {
    return 'You would receive $amount';
  }

  @override
  String offerSenderOffers(String amount) {
    return 'Sender offers $amount';
  }

  @override
  String offerBelowMinimum(String amount) {
    return 'Offer at least $amount';
  }

  @override
  String get offerEmptyTitle => 'No offers yet';

  @override
  String get offerEmptyBody => 'When someone makes an offer, it shows up here.';

  @override
  String get paymentTitle => 'Payment';

  @override
  String get paymentChooseProvider => 'How would you like to pay?';

  @override
  String get paymentProviderStripe => 'Stripe';

  @override
  String get paymentProviderStripeSubtitle =>
      'Visa, Mastercard and other cards';

  @override
  String get paymentProviderChargily => 'Chargily';

  @override
  String get paymentProviderChargilySubtitle =>
      'Algerian cards — CIB and Edahabia';

  @override
  String get paymentProviderUnavailable => 'Unavailable right now';

  @override
  String get paymentProviderNotConfigured => 'Not available yet';

  @override
  String get paymentProviderDisabled => 'Temporarily switched off';

  @override
  String get paymentProviderConfigurationInvalid => 'Not ready yet';

  @override
  String get paymentProviderAmountTooSmall => 'Below this method\'s minimum';

  @override
  String get paymentCheckoutFailedTitle => 'We could not start this payment';

  @override
  String get paymentCheckoutFailedBody =>
      'The payment provider refused to open a checkout. Nothing has been charged. Try the other method, or come back shortly.';

  @override
  String paymentRailEquivalent(String amount) {
    return 'Equivalent to $amount';
  }

  @override
  String paymentRailRate(String rate) {
    return '€1 = $rate DA';
  }

  @override
  String get paymentRailRateLocked =>
      'The rate is locked when you start the payment. The delivery price stays in euros.';

  @override
  String paymentPayWith(String amount, String provider) {
    return 'Pay $amount with $provider';
  }

  @override
  String a11yPaymentRailCharge(String provider, String amount) {
    return '$provider, charges $amount';
  }

  @override
  String get paymentNoProvidersTitle => 'No payment method available';

  @override
  String get paymentNoProvidersBody =>
      'Payment is temporarily unavailable. Nothing has been charged and your delivery is unaffected.';

  @override
  String paymentPayAction(String amount) {
    return 'Pay $amount';
  }

  @override
  String get paymentOpeningProvider => 'Opening secure checkout…';

  @override
  String get paymentFailedTitle => 'Payment didn\'t go through';

  @override
  String get paymentFailedBody =>
      'Nothing was charged. You can try again or use a different method.';

  @override
  String get paymentStatusRequired => 'Payment needed';

  @override
  String get paymentStatusPaid => 'Paid';

  @override
  String get paymentStatusRefundPending => 'Refund on the way';

  @override
  String get paymentStatusPartiallyRefunded => 'Partly refunded';

  @override
  String get paymentStatusRefunded => 'Refunded';

  @override
  String get paymentRedirectNotProof =>
      'We confirm every payment with the provider before marking it paid.';

  @override
  String get guestPayTitle => 'Payment request';

  @override
  String get guestPayExplainer =>
      'The person who sent you this link is asking you to pay this for their Wassla delivery. You don’t need an account.';

  @override
  String guestPayExpiresAt(String when) {
    return 'Expires $when';
  }

  @override
  String get guestPayWarning =>
      'This link only lets you pay this amount. It gives no access to the delivery or to anyone’s details.';

  @override
  String get guestPayPayerEmail => 'Email for your receipt';

  @override
  String get guestPayPayerEmailHelp =>
      'We’ll send your receipt here, and tell you if a refund is ever due. It doesn’t create an account.';

  @override
  String get guestPayInvalidTitle => 'This link isn\'t valid';

  @override
  String get guestPayInvalidBody =>
      'It may have expired, been cancelled, or already been paid.';

  @override
  String get recipientTitle => 'Who\'s receiving this?';

  @override
  String get recipientExplainer =>
      'We email the delivery code to the recipient. The traveler can only complete the delivery if the recipient gives them that code.';

  @override
  String get recipientName => 'Recipient\'s name';

  @override
  String get recipientEmail => 'Recipient\'s email';

  @override
  String get recipientEmailHelp =>
      'The delivery code is sent here. Make sure it\'s right.';

  @override
  String get recipientLanguage => 'Recipient\'s language';

  @override
  String get recipientLanguageHelp =>
      'This is the language we\'ll use for the recipient\'s delivery email.';

  @override
  String get recipientPhone => 'Phone (optional)';

  @override
  String get recipientNote => 'Note for the recipient (optional)';

  @override
  String get recipientSave => 'Save recipient';

  @override
  String get recipientSaved => 'Recipient saved';

  @override
  String get recipientRequiredBody =>
      'Add the recipient before pickup so we can send them the delivery code.';

  @override
  String get recipientRecordedForTraveler =>
      'The sender has provided the recipient\'s details.';

  @override
  String get pickupSenderTitle => 'Pickup code';

  @override
  String get pickupSenderExplainer =>
      'Give this code to the traveler only when you\'re physically handing over the parcel. It\'s how they confirm they have it.';

  @override
  String get pickupSenderReveal => 'Show pickup code';

  @override
  String get pickupSenderWarning =>
      'Don\'t send this code in a message. Say it in person, at handover.';

  @override
  String get pickupTravelerTitle => 'Confirm pickup';

  @override
  String get pickupTravelerExplainer =>
      'Ask the sender for their pickup code when they hand you the parcel.';

  @override
  String get pickupCodeLabel => 'Pickup code';

  @override
  String get pickupConfirmAction => 'Confirm pickup';

  @override
  String get pickupConfirmedTitle => 'Pickup confirmed';

  @override
  String get pickupConfirmedBody => 'You\'re carrying this parcel now.';

  @override
  String get pickupAwaitingTitle => 'Waiting for pickup';

  @override
  String get pickupAwaitingSenderBody =>
      'The traveler will ask for your pickup code when you meet.';

  @override
  String get pickupAwaitingTravelerBody =>
      'Meet the sender and ask for their pickup code.';

  @override
  String get deliveryTravelerTitle => 'Confirm delivery';

  @override
  String get deliveryTravelerExplainer =>
      'Ask the recipient for the code that was emailed to them.';

  @override
  String get deliveryCodeLabel => 'Delivery code';

  @override
  String get deliveryConfirmAction => 'Confirm delivery';

  @override
  String get deliveryConfirmedTitle => 'Delivery confirmed';

  @override
  String get deliveryConfirmedTravelerBody =>
      'Thank you. Your payout is being prepared.';

  @override
  String get deliveryConfirmedSenderBody =>
      'Your parcel arrived. Your payment stays protected for a little longer.';

  @override
  String get deliverySenderTitle => 'Delivery code';

  @override
  String deliveryCodeLockedTitle(String countdown) {
    return 'Available in $countdown';
  }

  @override
  String get deliveryCodeLockedBody =>
      'For safety, the delivery code stays locked for 30 minutes after pickup. The recipient hasn\'t been emailed yet either.';

  @override
  String get deliveryCodeLockedWhy => 'Why the wait?';

  @override
  String get deliveryCodeLockedWhyBody =>
      'The pause means a code can\'t be handed over at the same moment as the parcel. It\'s what stops a delivery being marked complete before it happens.';

  @override
  String get deliveryCodeReadyTitle => 'Delivery code ready';

  @override
  String deliveryCodeSentToRecipient(String recipient) {
    return 'We\'ve emailed the code to $recipient.';
  }

  @override
  String get deliveryCodeReveal => 'Show delivery code';

  @override
  String get deliveryCodeSenderWarning =>
      'The recipient gives this to the traveler at the door. Only share it with the recipient.';

  @override
  String get deliveryCodeTravelerNever =>
      'Only the recipient has this code. Ask them for it when you arrive.';

  @override
  String codeAttemptsRemaining(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count attempts left',
      one: '1 attempt left',
    );
    return '$_temp0';
  }

  @override
  String get codeIncorrect => 'That code isn\'t right';

  @override
  String get codeLockedTitle => 'Too many wrong attempts';

  @override
  String codeLockedBody(String when) {
    return 'Try again $when. If you\'re stuck, ask for a new code.';
  }

  @override
  String get codeRotate => 'Get a new code';

  @override
  String get codeRotated => 'New code issued. The old one no longer works.';

  @override
  String get codeRotateConfirmTitle => 'Issue a new code?';

  @override
  String get codeRotateConfirmBody =>
      'The code you already shared will stop working immediately.';

  @override
  String get codeNotAvailableYet => 'This code isn\'t available yet';

  @override
  String get codeCopyForReading =>
      'Read the code out loud rather than sending it.';

  @override
  String get protectionTitle => 'Payment protected';

  @override
  String protectionSenderBody(String when) {
    return 'Your payment is held until $when. If something\'s wrong with the delivery, open a dispute before then.';
  }

  @override
  String protectionTravelerBody(String when) {
    return 'Delivered. Your payout is released after $when, once the protection window closes.';
  }

  @override
  String get protectionEnded => 'Protection window closed';

  @override
  String get protectionExplainerTitle => 'What this means';

  @override
  String get protectionExplainerBody =>
      'Funds are held pending delivery confirmation and the 48-hour protection period. Wassla releases them only after that period ends and no dispute is open.';

  @override
  String get payoutTitle => 'Payout';

  @override
  String get payoutStatusNotEligible => 'Not yet';

  @override
  String get payoutStatusEligible => 'Ready';

  @override
  String get payoutStatusScheduled => 'Scheduled';

  @override
  String get payoutStatusProcessing => 'On the way';

  @override
  String get payoutStatusPaid => 'Paid';

  @override
  String get payoutStatusFailed => 'Failed';

  @override
  String get payoutStatusCancelled => 'Cancelled';

  @override
  String get payoutStatusFrozen => 'On hold';

  @override
  String get payoutFrozenBody =>
      'A dispute is open on this delivery, so the payout is on hold until it\'s resolved.';

  @override
  String get payoutEmptyTitle => 'No payouts yet';

  @override
  String get payoutEmptyBody =>
      'Complete a delivery and your earnings appear here.';

  @override
  String get disputeOpenTitle => 'Open a dispute';

  @override
  String get disputeOpenExplainer =>
      'Tell us what went wrong. Opening a dispute puts the traveler\'s payout on hold while we look into it.';

  @override
  String get disputeCategory => 'What happened?';

  @override
  String get disputeDescription => 'Describe the problem';

  @override
  String get disputeDescriptionHint =>
      'What you expected, and what actually happened';

  @override
  String get disputeSubmit => 'Open dispute';

  @override
  String get disputeStatusOpen => 'Open';

  @override
  String get disputeStatusAwaitingEvidence => 'Waiting for evidence';

  @override
  String get disputeStatusUnderReview => 'Being reviewed';

  @override
  String get disputeStatusResolved => 'Resolved';

  @override
  String get disputeStatusClosed => 'Closed';

  @override
  String get disputeEvidenceTitle => 'Evidence';

  @override
  String get disputeEvidenceExplainer =>
      'Photos and video help us understand what happened.';

  @override
  String get disputeAddPhoto => 'Add photo';

  @override
  String get disputeAddVideo => 'Add video';

  @override
  String get disputeAddNote => 'Add a note';

  @override
  String disputeUploading(int percent) {
    return 'Uploading… $percent%';
  }

  @override
  String disputeFileTooLarge(String limit) {
    return 'That file is too large. The limit is $limit.';
  }

  @override
  String get disputeFileTypeNotAllowed =>
      'That file type isn\'t supported. Use a JPEG, PNG, WebP, MP4 or MOV.';

  @override
  String get disputeEvidenceLimitReached =>
      'You\'ve added the maximum number of items.';

  @override
  String get disputeResolutionTitle => 'Outcome';

  @override
  String get disputeResolutionRefunded => 'Refunded to the sender';

  @override
  String get disputeResolutionTravelerPaid => 'Paid to the traveler';

  @override
  String get disputeResolutionPartial => 'Split between both sides';

  @override
  String get disputeWindowClosedTitle => 'The dispute window has closed';

  @override
  String get disputeWindowClosedBody =>
      'Disputes can be opened for 48 hours after delivery.';

  @override
  String get cancelTitle => 'Cancel this delivery';

  @override
  String get cancelConfirmAction => 'Cancel delivery';

  @override
  String get cancelKeepAction => 'Keep it';

  @override
  String get cancelFullRefund => 'You\'ll be refunded in full.';

  @override
  String get cancelWithCompensation =>
      'Because it\'s close to pickup, the traveler is compensated for holding the space.';

  @override
  String get cancelNotAllowedTitle => 'This can\'t be cancelled here';

  @override
  String get cancelAfterPickupBody =>
      'The parcel has already been picked up. If something\'s wrong, open a dispute instead.';

  @override
  String get cancelOutcomeTitle => 'What happens';

  @override
  String get cancelCancelledTitle => 'Cancelled';

  @override
  String get cancelRefundOnWay => 'Your refund is on the way.';

  @override
  String get ratingTitle => 'How did it go?';

  @override
  String get ratingSenderPrompt => 'Rate the traveler';

  @override
  String get ratingTravelerPrompt => 'Rate the sender';

  @override
  String ratingScoreLabel(int score) {
    return '$score out of 5';
  }

  @override
  String get ratingTagsLabel => 'What stood out?';

  @override
  String get ratingCommentLabel => 'Anything else? (optional)';

  @override
  String get ratingSubmit => 'Submit rating';

  @override
  String get ratingSubmitted => 'Thanks for the rating';

  @override
  String get ratingWaitingForOther =>
      'Your rating is saved. You\'ll see theirs once they\'ve rated you too.';

  @override
  String get ratingHiddenUntilBoth => 'Hidden until you both rate';

  @override
  String get ratingWindowClosed => 'The rating window has closed.';

  @override
  String get ratingEmptyTitle => 'No ratings yet';

  @override
  String get ratingEmptyBody => 'Ratings appear after a delivery is completed.';

  @override
  String get boostTitle => 'Boost this request';

  @override
  String get boostExplainer =>
      'Travelers receive 100% of the Boost bonus. Boosted requests appear higher in traveler search.';

  @override
  String boostDurationDays(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days days',
      one: '1 day',
    );
    return '$_temp0';
  }

  @override
  String get chatTitle => 'Chat';

  @override
  String get chatEmptyTitle => 'No conversations';

  @override
  String get chatEmptyBody => 'Chat opens once a delivery is paid for.';

  @override
  String get chatThreadEmptyTitle => 'Say hello';

  @override
  String get chatThreadEmptyBody => 'Arrange where and when to meet.';

  @override
  String get chatComposerHint => 'Write a message';

  @override
  String get chatSend => 'Send';

  @override
  String get chatRetrySend => 'Tap to retry';

  @override
  String get chatSending => 'Sending…';

  @override
  String get chatClosedTitle => 'This conversation is closed';

  @override
  String get chatClosedBody =>
      'You can still read it, but new messages aren\'t possible.';

  @override
  String get chatUnavailableTitle => 'Chat isn\'t available yet';

  @override
  String get chatUnavailableBody =>
      'Chat opens for this delivery once payment is confirmed.';

  @override
  String get chatNeverShareCodes =>
      'Never send a pickup or delivery code in chat.';

  @override
  String get notificationsTitle => 'Notifications';

  @override
  String get notificationsMarkAllRead => 'Mark all as read';

  @override
  String get notificationsEmptyTitle => 'Nothing new';

  @override
  String get notificationsEmptyBody =>
      'Offers, payments and delivery updates show up here.';

  @override
  String get profileTitle => 'Profile';

  @override
  String get profileAccount => 'Account';

  @override
  String get profilePassportStamp => 'Wassla · MEMBER';

  @override
  String get profileCompletedDeliveries => 'Completed';

  @override
  String get profileRoles => 'What you do';

  @override
  String get profileVerification => 'Verification';

  @override
  String get profileRatings => 'Ratings';

  @override
  String get profilePayments => 'Payments and payouts';

  @override
  String get profileNotificationSettings => 'Notifications';

  @override
  String get profileLanguage => 'Language';

  @override
  String get profileLanguageSystem => 'Device language';

  @override
  String get profileAppLanguage => 'App language';

  @override
  String get profileAppLanguageHelp =>
      'What you read inside Wassla. Stored on this phone.';

  @override
  String get profileEmailLanguage => 'Email language';

  @override
  String get profileEmailLanguageHelp =>
      'What we write to you in — payments, verification, deliveries, disputes and account security. Saved to your account.';

  @override
  String get profileEmailLanguageSaved => 'Email language updated';

  @override
  String get profileSupport => 'Help and support';

  @override
  String get profileTerms => 'Terms of service';

  @override
  String get profilePrivacy => 'Privacy policy';

  @override
  String get profileLinkOpenFailed =>
      'We couldn\'t open that page. Check that you have a browser installed.';

  @override
  String get profileAppearance => 'Appearance';

  @override
  String get profileAppearanceSystem => 'Match device';

  @override
  String get profileAppearanceLight => 'Light';

  @override
  String get profileAppearanceDark => 'Dark';

  @override
  String get profileEmailVerified => 'Email verified';

  @override
  String get profileEmailUnverified => 'Email not verified';

  @override
  String profileMemberSince(String date) {
    return 'With Wassla since $date';
  }

  @override
  String profileVersion(String version) {
    return 'Version $version';
  }

  @override
  String get locationSearchTitle => 'Choose a place';

  @override
  String get locationSearchHint => 'Search localities and airports';

  @override
  String get locationSearchStart =>
      'Type a locality, municipality, commune, or airport';

  @override
  String placeTierWilaya(String name) {
    return '$name Wilaya';
  }

  @override
  String placeTierDepartment(String name) {
    return '$name department';
  }

  @override
  String placeTierRegion(String name) {
    return '$name region';
  }

  @override
  String placeTierProvince(String name) {
    return '$name province';
  }

  @override
  String placeTierAutonomousCommunity(String name) {
    return '$name autonomous community';
  }

  @override
  String placeTierState(String name) {
    return '$name state';
  }

  @override
  String placeTierDistrict(String name) {
    return '$name district';
  }

  @override
  String get locationTypeAirport => 'Airport';

  @override
  String locationAirportServesPlace(String place) {
    return 'Serves $place';
  }

  @override
  String locationAirportNearPlace(String place) {
    return 'Near $place';
  }

  @override
  String locationAirportNearbyDistance(String distance) {
    return 'Nearby airport · $distance km';
  }

  @override
  String get locationUseMap => 'Choose on map';

  @override
  String get locationConfirmPoint => 'Use this point';

  @override
  String get locationSaved => 'Saved places';

  @override
  String get locationPrivacyBeforeFunding =>
      'Only the city is shared until the delivery is paid for.';

  @override
  String get locationHiddenUntilFunded =>
      'Exact address available after payment';

  @override
  String get locationSearchEmptyTitle => 'No results';

  @override
  String get countryNameAlgeria => 'Algeria';

  @override
  String get countryNameFrance => 'France';

  @override
  String get countryNameSpain => 'Spain';

  @override
  String get countryNameGermany => 'Germany';

  @override
  String get locationCountryQuestion => 'Which country?';

  @override
  String get locationChangeCountry => 'Change';

  @override
  String get locationCountriesUnavailable =>
      'No countries are available right now.';

  @override
  String get locationSelectCountryBody =>
      'Pick a country above, then search for the town, commune or airport.';

  @override
  String get locationSearchReadyTitle => 'Ready when you are';

  @override
  String get locationSearchHintAirports => 'Search airports';

  @override
  String get locationSearchStartAirports =>
      'Type an airport name or its three-letter code.';

  @override
  String get locationAirportsOnly =>
      'This leg flies, so only airports are offered.';

  @override
  String get locationCurrentSelection => 'Currently selected';

  @override
  String locationSearchNoMatch(String query) {
    return 'Nothing here matches “$query”. Check the spelling, or try the nearest larger town.';
  }

  @override
  String locationSearchNoMatchAirports(String query) {
    return 'No airport here matches “$query”. Try the city name, or the three-letter code.';
  }

  @override
  String locationPreferredExplainer(String place) {
    return 'Travelers are matched on $place. A preferred point only says where you would rather meet inside it.';
  }

  @override
  String get locationPreferredFlexibleHint => 'No exact point needed';

  @override
  String get locationAddPreferredPoint => 'Add a preferred point';

  @override
  String get locationChangePreferredPoint => 'Change point';

  @override
  String get locationRemovePreferredPoint => 'Remove preferred point';

  @override
  String get locationPreferredRemoved => 'Preferred point removed.';

  @override
  String get locationPreferredClearedByPlace =>
      'Preferred point removed — it belonged to the place you just changed.';

  @override
  String get locationDecideLater => 'Decide later';

  @override
  String get locationPointInside => 'Point inside';

  @override
  String locationDropPinHelpIn(String place) {
    return 'Move the map until the crosshair sits where you mean inside $place, then confirm.';
  }

  @override
  String locationNoCentre(String place) {
    return 'We have no centre on file for $place, so the map starts wide. Move it to the right area before you confirm.';
  }

  @override
  String mapAttribution(String attribution) {
    return 'Map data $attribution';
  }

  @override
  String get locationYourPlaces => 'Your places';

  @override
  String get locationEmptyTitle => 'No saved places yet';

  @override
  String get locationEmptyBody =>
      'Drop a pin on the map to save your first address.';

  @override
  String get locationNamePlaceTitle => 'Name this place';

  @override
  String get locationNamePlaceBody =>
      'Only you see the label. Other people see the city until a delivery is paid for.';

  @override
  String get locationLabelField => 'Label';

  @override
  String get locationLabelHint => 'Home, Mum\'s place, the office';

  @override
  String get locationSavePlace => 'Save this place';

  @override
  String get locationPlaceSaved => 'Place saved.';

  @override
  String get locationPreferredMeetingPoint => 'Preferred meeting point';

  @override
  String get locationPreferredOptional => 'Optional';

  @override
  String locationFlexibleWithin(String place) {
    return 'Flexible within $place';
  }

  @override
  String locationPreferredValidation(String place) {
    return 'The map provider will verify that this point belongs to $place.';
  }

  @override
  String get mapZoomIn => 'Zoom in';

  @override
  String get mapZoomOut => 'Zoom out';

  @override
  String get timelineTitle => 'Progress';

  @override
  String get timelineDone => 'Done';

  @override
  String get a11yStatusPrefix => 'Status';

  @override
  String get a11yMoneyAmount => 'Amount';

  @override
  String get a11yRequiredField => 'Required';

  @override
  String get a11yCloseSheet => 'Close';

  @override
  String get a11yLoadingContent => 'Loading content';

  @override
  String get a11ySelected => 'Selected';

  @override
  String get a11yNotSelected => 'Not selected';

  @override
  String get a11yExpandSection => 'Expand';

  @override
  String get a11yCollapseSection => 'Collapse';

  @override
  String get disputeCategoryNotDelivered => 'Never arrived';

  @override
  String get disputeCategoryDamaged => 'Arrived damaged';

  @override
  String get disputeCategoryWrongItem => 'Wrong item';

  @override
  String get disputeCategoryLate => 'Arrived too late';

  @override
  String get disputeCategoryNoShow => 'The other person didn\'t show up';

  @override
  String get disputeCategoryPayment => 'Something is wrong with the money';

  @override
  String get disputeCategoryOther => 'Something else';

  @override
  String unitWeightKg(String value) {
    return '$value kg';
  }

  @override
  String unitDimensions(String length, String width, String height) {
    return '$length × $width × $height cm';
  }

  @override
  String unitCapacityKg(String value) {
    return '$value kg free';
  }

  @override
  String unitDurationHm(int hours, int minutes) {
    return '${hours}h ${minutes}m';
  }

  @override
  String unitDurationM(int minutes) {
    return '${minutes}m';
  }

  @override
  String distanceUnder(String max) {
    return 'Under $max km';
  }

  @override
  String distanceBetween(String min, String max) {
    return '$min–$max km';
  }

  @override
  String distanceOver(String min) {
    return 'Over $min km';
  }

  @override
  String get homeVerifyIdentityTitle => 'Verify your identity';

  @override
  String get homeVerifyIdentityBody =>
      'Travelers must be verified before a journey can go live.';

  @override
  String get homeAttentionOfferAwaiting =>
      'An offer is waiting for your answer';

  @override
  String get homeAttentionFunding => 'Pay to confirm this delivery';

  @override
  String get homeAttentionRecipient => 'Add who receives the parcel';

  @override
  String get homeAttentionRevealPickup =>
      'Show the pickup code to your traveler';

  @override
  String get homeAttentionSubmitPickup => 'Enter the pickup code';

  @override
  String get homeAttentionRevealDelivery => 'The delivery code is ready';

  @override
  String get homeAttentionSubmitDelivery => 'Enter the delivery code';

  @override
  String get homeAttentionRating => 'Rate this delivery';

  @override
  String get deliveryCardSending => 'Sending';

  @override
  String get deliveryCardCarrying => 'Carrying';

  @override
  String deliveryCardWith(String name) {
    return 'with $name';
  }

  @override
  String journeyLegCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count legs',
      one: '1 leg',
    );
    return '$_temp0';
  }

  @override
  String journeyProofNeeded(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count tickets need checking',
      one: '1 ticket needs checking',
    );
    return '$_temp0';
  }

  @override
  String get onboardingGetStarted => 'Create an account';

  @override
  String onboardingPageOf(int current, int total) {
    return 'Page $current of $total';
  }

  @override
  String get authInvalidCredentials => 'Email or password is incorrect';

  @override
  String get authShowPassword => 'Show password';

  @override
  String get authHidePassword => 'Hide password';

  @override
  String get authPhone => 'Phone number';

  @override
  String get authResetCodeSent =>
      'If that address has an account, we\'ve sent it a six-digit code.';

  @override
  String get authResetCodeLabel => 'Six-digit code';

  @override
  String get authNewPassword => 'New password';

  @override
  String get authResetDone =>
      'Password changed. You were signed out everywhere. Sign in with the new password.';

  @override
  String get authSendCode => 'Send code';

  @override
  String get authResendCode => 'Send a new code';

  @override
  String get authVerifyDone => 'Email verified';

  @override
  String get authTermsNotice =>
      'By creating an account you accept the Terms and the Privacy Policy.';

  @override
  String get authVerifyNoCode =>
      'Nothing arrived? Check your spam folder, then ask for a new code. Only the code in the newest email works.';

  @override
  String get kycDocIdCard => 'National ID card';

  @override
  String get kycDocPassport => 'Passport';

  @override
  String get kycDocDrivingLicense => 'Driving licence';

  @override
  String get kycAddPhoto => 'Add photo';

  @override
  String get kycReplacePhoto => 'Replace';

  @override
  String get kycFileTooLarge =>
      'That image is too large. Each photo must be under 8 MB.';

  @override
  String get kycFileTypeNotAllowed => 'Only JPEG and PNG photos are accepted.';

  @override
  String get kycUploading => 'Sending your documents…';

  @override
  String get kycSubmitAction => 'Submit for review';

  @override
  String get kycSubmitted => 'Documents received. We\'ll review them shortly.';

  @override
  String get kycBackNotNeeded => 'A passport only needs its photo page.';

  @override
  String get kycSelfieHelp =>
      'A clear photo of your face, taken now — it\'s checked against your document.';

  @override
  String get kycUnavailable =>
      'Verification is temporarily unavailable. Please try again shortly.';

  @override
  String get notificationOffer => 'Offer update';

  @override
  String get notificationPayment => 'Payment update';

  @override
  String get notificationChat => 'New message';

  @override
  String get notificationRequest => 'Request update';

  @override
  String get notificationDelivery => 'Delivery update';

  @override
  String get notificationOther => 'Update';

  @override
  String get chatBlockedPayAction => 'Go to payment';

  @override
  String get paymentProviderNewCheckoutsDisabled =>
      'Not taking new payments right now';

  @override
  String get paymentProviderPickAnother => 'Try a different payment method.';

  @override
  String get paymentContinueTitle => 'A checkout is already open';

  @override
  String get paymentContinueBody =>
      'Finish the payment you started instead of opening a second one.';

  @override
  String get paymentContinueAction => 'Continue your payment';

  @override
  String get paymentCouldNotOpen =>
      'We couldn\'t open the checkout page. Check that you have a browser installed.';

  @override
  String get paymentCheckAgain => 'Check again';

  @override
  String get paymentNothingOutstandingTitle => 'Nothing left to pay';

  @override
  String get paymentNothingOutstandingBody => 'This has already been settled.';

  @override
  String get paymentOrderClosedTitle => 'This can\'t be paid now';

  @override
  String get paymentOrderClosedBody =>
      'This payment was closed or refunded, so no new checkout can be opened.';

  @override
  String get requestReadyUntil => 'Ready until';

  @override
  String get requestReadyWindow => 'Ready window';

  @override
  String get requestReadyWindowHelp =>
      'The stretch of time a traveler could collect it. Give a window, not a minute.';

  @override
  String get requestDeadlineHelp =>
      'The latest it can arrive. This has to be after your ready window closes.';

  @override
  String get requestWeightHelp => 'Between 0.01 and 100 kg.';

  @override
  String get requestCategoryDocuments => 'Documents';

  @override
  String get requestCategorySmallBox => 'Small box';

  @override
  String get requestCategoryElectronics => 'Electronics';

  @override
  String get requestCategoryClothing => 'Clothing';

  @override
  String get requestCategoryOther => 'Something else';

  @override
  String get requestProposedReward => 'What you propose to pay';

  @override
  String get requestProposedRewardHelp =>
      'A starting point, not a price. Travelers can accept it or come back with a different amount.';

  @override
  String get requestRewardIsIntent =>
      'This is what you proposed. The price is settled when a traveler accepts an offer.';

  @override
  String get requestReviewTitle => 'Check this over';

  @override
  String get requestAckAllRequired => 'Confirm all five before you post.';

  @override
  String get requestPostAction => 'Post this request';

  @override
  String get requestDetailTitle => 'Your request';

  @override
  String get requestParcelSection => 'The parcel';

  @override
  String get requestTimingSection => 'Timing';

  @override
  String get requestRouteSection => 'Route';

  @override
  String get requestRouteNotRecorded => 'Route not recorded';

  @override
  String get requestMatchesSection => 'Travelers you\'ve approached';

  @override
  String get requestNoMatchesYet => 'You haven\'t proposed to anyone yet.';

  @override
  String get requestAwaitingDepositNotice =>
      'Travelers can\'t see this yet. Pay the deposit to publish it.';

  @override
  String get requestFindTravelers => 'Find travelers';

  @override
  String get requestPayDepositAction => 'Pay deposit';

  @override
  String get requestCancelAction => 'Cancel request';

  @override
  String get requestCancelConfirmTitle => 'Cancel this request?';

  @override
  String get requestCancelConfirmBody =>
      'It stops being visible to travelers. Any deposit you paid comes back to you.';

  @override
  String get requestCancelled => 'Request cancelled';

  @override
  String get requestCancelNotCancellableBody =>
      'A traveler is already matched with this request, so it can\'t be cancelled here.';

  @override
  String get requestCancelViaDealBody =>
      'This request has become a delivery. Cancel it from the delivery instead.';

  @override
  String requestPhotoCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count photos',
      one: '1 photo',
      zero: 'No photos',
    );
    return '$_temp0';
  }

  @override
  String get requestNotFragile => 'Standard handling';

  @override
  String get requestFragileYes => 'Handle with care';

  @override
  String get requestTargetedNotice =>
      'You addressed this request to one traveler. Nobody else can see it.';

  @override
  String get depositNotRequiredTitle => 'No deposit needed';

  @override
  String get depositNotRequiredBody =>
      'This request publishes without one. There is nothing to pay here.';

  @override
  String get depositClampedMin => 'This is the smallest deposit we take.';

  @override
  String get depositClampedMax =>
      'This is the largest deposit we take, whatever the parcel is worth.';

  @override
  String get discoveryProposeBlocked =>
      'We can\'t work out which part of this journey fits your parcel. Refresh and try again.';

  @override
  String get discoveryBreakdownNote =>
      'This is how the suggested amount adds up. Offer something different and the total moves with it.';

  @override
  String get discoveryProposalSent => 'Offer sent';

  @override
  String get discoveryLegRangeMoved =>
      'This traveler\'s route changed while you were looking. We\'ve refreshed it.';

  @override
  String discoveryIncompatibleCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'This traveler no longer fits your parcel, for $count reasons.',
      one: 'This traveler no longer fits your parcel, for 1 reason.',
    );
    return '$_temp0';
  }

  @override
  String get boostCompatibilityNote =>
      'Only travelers who already match your parcel ever see it. A boost doesn\'t change who those travelers are.';

  @override
  String get moneyBaseReward => 'Base delivery reward';

  @override
  String get moneyBoostBonus => 'Boost bonus';

  @override
  String get moneyBoostFee => 'Boost fee';

  @override
  String get validationReadyWindowOrder =>
      'The ready window has to end after it starts';

  @override
  String validationWeightRange(String min, String max) {
    return 'Enter a weight between $min and $max kg';
  }

  @override
  String get dealStepAgreed => 'Terms agreed';

  @override
  String get dealStepPaid => 'Payment held';

  @override
  String get dealStepRecipient => 'Recipient added';

  @override
  String get dealStepPickedUp => 'Parcel collected';

  @override
  String get dealStepDelivered => 'Delivered';

  @override
  String get dealStepProtection => 'Protected payment';

  @override
  String get dealStepCompleted => 'Completed';

  @override
  String get dealOpenChat => 'Message';

  @override
  String get dealMoneySection => 'The money';

  @override
  String get dealActionPay => 'Pay now';

  @override
  String get dealActionRecipient => 'Add recipient';

  @override
  String get dealActionPickup => 'Pickup';

  @override
  String get dealActionDelivery => 'Delivery';

  @override
  String get dealActionDispute => 'Open a dispute';

  @override
  String get dealActionCancel => 'Cancel this delivery';

  @override
  String get dealActionRate => 'Leave a rating';

  @override
  String dealFundingDeadline(String time) {
    return 'Pay before $time or the space is released';
  }

  @override
  String get dealTravelerAwaitingPayment => 'Waiting for the sender to pay.';

  @override
  String get dealTravelerPaymentFunded =>
      'The sender\'s payment is confirmed and protected.';

  @override
  String get ratingBlindNote =>
      'Neither of you sees the other\'s rating until you\'ve both left one, or the window closes.';

  @override
  String get ratingSubmittedTitle => 'Rating saved';

  @override
  String get ratingClosedTitle => 'Rating closed';

  @override
  String get ratingTheirsTitle => 'Their rating';

  @override
  String get ratingRevealedNote =>
      'You have both rated, so your ratings are now visible to each other.';

  @override
  String get pickupTitle => 'Pickup';

  @override
  String get pickupNextTitle => 'What happens next';

  @override
  String get pickupConfirmedSenderNext =>
      'The delivery code is now available to your recipient. Only they can pass it to the traveler.';

  @override
  String get pickupConfirmedTravelerNext =>
      'Carry the parcel to the recipient. They read you the delivery code at the door — you are never shown it yourself.';

  @override
  String get deliverySafetyWaitingTitle => 'Waiting for the safety period';

  @override
  String get deliverySafetyWaitingSenderBody =>
      'Pickup is confirmed. Delivery confirmation becomes available after the safety period; then Wassla emails the delivery code to your recipient.';

  @override
  String get deliverySafetyWaitingTravelerBody =>
      'Pickup is confirmed. Continue to the recipient. After the safety period, ask them for the delivery code — Wassla never shows it to you.';

  @override
  String get pickupGoToDeliveryAction => 'Go to delivery';

  @override
  String get pickupNotFundedBody =>
      'This delivery isn\'t funded yet, so there\'s no pickup code to show.';

  @override
  String get pickupNotReadyBody => 'This delivery isn\'t ready for pickup yet.';

  @override
  String get pickupAlreadyConfirmedBody =>
      'Pickup is already confirmed on this delivery.';

  @override
  String get recipientRequiredTravelerBody =>
      'The sender hasn\'t added the recipient yet. Ask them to do that, then try the code again.';

  @override
  String get codeRequiresNewCodeBody =>
      'This code can\'t be used again. A new one has to be issued before you can confirm.';

  @override
  String codeRateLimitedBody(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Too many tries. Wait $count seconds and try again.',
      one: 'Too many tries. Wait a second and try again.',
    );
    return '$_temp0';
  }

  @override
  String get deliveryTitle => 'Delivery';

  @override
  String get deliverySenderExplainer =>
      'The recipient receives this code by email. They read it to the traveler at the door, and that is what confirms the delivery.';

  @override
  String get deliveryCodeSentToRecipientUnknown =>
      'We\'ve emailed the code to your recipient.';

  @override
  String get deliveryCodeBufferOpenBody =>
      'The delivery code is still locked. It unlocks 30 minutes after pickup.';

  @override
  String get deliveryNotInCarriageBody =>
      'This delivery isn\'t in transit, so a new code can\'t be issued.';

  @override
  String get deliveryConfirmedTravelerNext =>
      'The protection window has started. Your payout is released once it closes — nothing is paid out before then.';

  @override
  String get deliveryAwaitingTitle => 'Not yet';

  @override
  String get deliveryAwaitingSenderBody =>
      'The delivery code appears here once the parcel has been picked up.';

  @override
  String get deliveryAwaitingTravelerBody =>
      'Confirm the pickup first. The delivery code can only be used after that.';

  @override
  String get protectionEndsInLabel => 'Ends in';

  @override
  String get payoutAmountLabel => 'Amount';

  @override
  String get payoutEligibleLabel => 'Expected';

  @override
  String get disputeViewAction => 'View the dispute';

  @override
  String get disputeOpened => 'Dispute opened';

  @override
  String get disputeExistingOpenedBody =>
      'You already have a dispute open on this delivery. We\'ve taken you to it.';

  @override
  String get disputeFreezesPayoutTitle => 'The traveler\'s payout goes on hold';

  @override
  String get disputeFreezesPayoutBody =>
      'Nothing is paid out while we look into this. Both sides can add evidence.';

  @override
  String get disputeNotAvailableTitle => 'You can\'t open a dispute yet';

  @override
  String get disputeNotAvailableBody =>
      'A dispute can be opened once the parcel has been picked up. Before that, cancel the delivery instead.';

  @override
  String get disputeAlreadyResolvedBody =>
      'There\'s already a resolved dispute on this delivery.';

  @override
  String get disputeDetailTitle => 'Dispute';

  @override
  String get disputeReasonLabel => 'What was reported';

  @override
  String get disputeOpenedByLabel => 'Opened by';

  @override
  String get disputeOpenedBySender => 'The sender';

  @override
  String get disputeOpenedByTraveler => 'The traveler';

  @override
  String get disputeOpenedAtLabel => 'Opened';

  @override
  String get disputeProtectionEndsLabel => 'Protection window ends';

  @override
  String get disputePayoutFrozenTitle => 'Payout on hold';

  @override
  String get disputePayoutSettledBody =>
      'The payout had already gone out before this dispute was opened.';

  @override
  String get disputeAmountsTitle => 'How this was settled';

  @override
  String get disputeAmountsExplainer =>
      'These amounts are Wassla\'s decision. Nothing here is worked out on your phone.';

  @override
  String get disputeCollectedTotal => 'Collected from the sender';

  @override
  String get disputeResolutionNoteLabel => 'Note from Wassla';

  @override
  String get disputeTimelineTitle => 'What\'s happened';

  @override
  String get disputeEventOpened => 'Dispute opened';

  @override
  String disputeEventStatusChanged(String status) {
    return 'Status changed to $status';
  }

  @override
  String get disputeEventEvidenceAdded => 'Evidence added';

  @override
  String get disputeEventResolved => 'Decision made';

  @override
  String get disputeEventClosed => 'Dispute closed';

  @override
  String get disputeEventPayoutFrozen => 'Payout put on hold';

  @override
  String get disputeEventNote => 'Note added';

  @override
  String get disputeEventOther => 'Update';

  @override
  String get disputeEvidenceNone => 'Nothing added yet';

  @override
  String get disputeEvidenceView => 'View';

  @override
  String get disputeEvidenceOpenFailed => 'We couldn\'t open that. Try again.';

  @override
  String get disputeEvidenceKindText => 'Note';

  @override
  String get disputeEvidenceKindPhoto => 'Photo';

  @override
  String get disputeEvidenceKindVideo => 'Video';

  @override
  String disputeEvidenceCount(int count, int max) {
    return '$count of $max added';
  }

  @override
  String get disputeEvidenceNoteHint => 'What you want us to know';

  @override
  String get disputeEvidenceAdded => 'Evidence added';

  @override
  String get disputeEvidenceClosedBody =>
      'This dispute is closed, so nothing more can be added.';

  @override
  String get disputeEvidenceTypeMismatchBody =>
      'That file doesn\'t match the type you chose.';

  @override
  String get disputeEvidenceContentMismatchBody =>
      'That file isn\'t what it claims to be. Try a different one.';

  @override
  String get disputeEvidenceLinkNote =>
      'Evidence links expire after a few minutes, so we fetch a fresh one each time you open something.';

  @override
  String get disputeEvidenceTextRequiredBody =>
      'Write something before adding a note.';

  @override
  String get disputeEvidenceFileRequiredBody => 'Choose a file first.';

  @override
  String get onboardingStamp => 'EST. 2026 · ALG ↔ FR';

  @override
  String benefitsIndex(int current, int total) {
    return '$current / $total';
  }

  @override
  String get benefitsChapterOneEyebrow => 'Chapter I · The post';

  @override
  String get benefitsChapterOneTitle => 'Send anywhere,\nfor a fraction.';

  @override
  String get benefitsChapterOneAccent =>
      'Envoyez vers la France, l’Algérie, et plus loin.';

  @override
  String get benefitsChapterOneBody =>
      'Travelers carry your parcel as part of their luggage. You pay a sliver of express shipping.';

  @override
  String get benefitsChapterOneStamp => 'Par avion';

  @override
  String get benefitsChapterTwoEyebrow => 'Chapter II · The suitcase';

  @override
  String get benefitsChapterTwoTitle => 'Earn while\nyou travel.';

  @override
  String get benefitsChapterTwoAccent => 'Voyagez. Gagnez.';

  @override
  String get benefitsChapterTwoBody =>
      'Going to Algiers, Paris or Oran already? Fill the unused kilos in your luggage.';

  @override
  String get benefitsChapterTwoStamp => 'Boarding';

  @override
  String get benefitsChapterThreeEyebrow => 'Chapter III · The seal';

  @override
  String get benefitsChapterThreeTitle => 'Built for\ntrust.';

  @override
  String get benefitsChapterThreeAccent => 'Conçu pour la confiance.';

  @override
  String get benefitsChapterThreeBody =>
      'Verified identities, payment held until delivery, a code at every handover. Nothing moves on trust alone.';

  @override
  String get benefitsChapterThreeStamp => 'Verified';

  @override
  String get benefitsHandoverCaption => 'HANDOVER CODE';

  @override
  String get benefitsKilosFree => 'KG\nFREE';

  @override
  String get authWelcomeBackStamp => 'Welcome back';

  @override
  String get authSignInHeadline => 'Good to see\nyou again.';

  @override
  String get authSignInSubhead =>
      'Sign in to pick up where your deliveries left off.';

  @override
  String get authJoinStamp => 'Join the corridor';

  @override
  String get authSignUpHeadline => 'Create your\npassport.';

  @override
  String get authSignUpSubhead => 'Two minutes — then you can send or travel.';

  @override
  String get authForgotStamp => 'Locked out';

  @override
  String get authForgotHeadline => 'Let\'s get you\nback in.';

  @override
  String get authVerifyStamp => 'One more stamp';

  @override
  String stateRateLimitedWait(int seconds) {
    return 'Wait about $seconds seconds before trying again.';
  }

  @override
  String get authForgotSubhead =>
      'Tell us the address on your account and we\'ll send a six-digit code to it.';

  @override
  String get authVerifySubhead =>
      'Enter the six-digit code we emailed you. It\'s the last step.';

  @override
  String get requestItemPhoto => 'Photo of the item';

  @override
  String get requestItemPhotoHelp =>
      'Add a clear photo of what you\'re sending. Travelers decide from this.';

  @override
  String get requestItemPhotoChoose => 'Choose a photo';

  @override
  String get requestItemPhotoFromGallery => 'From gallery';

  @override
  String get requestItemPhotoTakePhoto => 'Take a photo';

  @override
  String get requestItemPhotoReplace => 'Replace';

  @override
  String get requestItemPhotoRemove => 'Remove photo';

  @override
  String get requestItemPhotoUploading => 'Uploading your photo…';

  @override
  String get requestItemPhotoReady => 'Photo added';

  @override
  String get requestItemPhotoRequired => 'A photo of the item is required.';

  @override
  String get requestItemPhotoFormatRule => 'JPEG, PNG or WebP, up to 10 MB.';

  @override
  String get requestItemPhotoTooLarge =>
      'That image is too large. Choose one under 10 MB.';

  @override
  String get requestItemPhotoTypeNotAllowed =>
      'That file type isn\'t accepted. Use a JPEG, PNG or WebP image.';

  @override
  String get requestItemPhotoUploadFailed =>
      'The photo didn\'t upload. It\'s still selected — try again.';

  @override
  String get requestItemPhotoStorageUnavailable =>
      'Photo storage is unavailable right now. Try again in a moment.';

  @override
  String get requestItemPhotoPrivacy =>
      'Only travelers who can see this request can see the photo.';

  @override
  String get fieldOptional => 'Optional';

  @override
  String get requestDimensionsOptionalHelp =>
      'Optional. Leave empty if you haven\'t measured it — or enter all three.';

  @override
  String get requestDimensionsPartialFix =>
      'Enter length, width and height together, or clear all three.';

  @override
  String get formFixBeforeContinuing =>
      'Fix the highlighted field before continuing.';

  @override
  String formFixCountBeforeContinuing(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Fix $count fields before continuing.',
      one: 'Fix 1 field before continuing.',
    );
    return '$_temp0';
  }

  @override
  String get formServerRefusedOnStep =>
      'The server refused this request. The problem is on this step, marked below.';

  @override
  String get pushPermissionHeading => 'On this phone';

  @override
  String get pushPermissionBody =>
      'Get timely updates about offers, payments, delivery, messages and verification. Wassla asks only when you choose Enable.';

  @override
  String get pushPermissionEnabled => 'Notifications are enabled.';

  @override
  String get pushPermissionDeniedRequestable =>
      'Notifications are still off. Choose Enable notifications to ask Android again. Your in-app inbox keeps working either way.';

  @override
  String get pushPermissionDenied =>
      'Notifications are off at system level. You can enable them in Settings.';

  @override
  String get pushPermissionUnavailable =>
      'Push is not configured in this build. In-app notifications still work.';

  @override
  String get pushPermissionInitializationFailed =>
      'Push could not start on this phone. Your in-app notifications still work; reopen Wassla to try again.';

  @override
  String get pushEnableAction => 'Enable notifications';

  @override
  String get pushOpenSettingsAction => 'Open notification settings';

  @override
  String get pushRegistrationPending =>
      'System notification permission is on. Wassla is finishing notification setup for this phone.';

  @override
  String get pushRegistrationFailed =>
      'System notification permission is on, but Wassla could not finish registering this phone. Check your connection and try again.';

  @override
  String get pushRetryRegistrationAction => 'Retry notification setup';

  @override
  String get pushPreferencesHeading => 'Notification types';

  @override
  String get pushPreferencesBody =>
      'These choices control messages and marketplace activity. They do not change this phone\'s system permission, and essential delivery and account updates stay available.';

  @override
  String get pushEssentialTitle => 'Essential updates';

  @override
  String get pushEssentialBody =>
      'Payment, delivery, dispute, verification and account-security updates stay on.';

  @override
  String get pushMessagesTitle => 'Messages';

  @override
  String get pushMessagesBody => 'New chat activity.';

  @override
  String get pushMarketplaceTitle => 'Marketplace activity';

  @override
  String get pushMarketplaceBody => 'Offers, matches, journeys and requests.';

  @override
  String get notificationAccount => 'Verification update';

  @override
  String get notificationDispute => 'Dispute update';

  @override
  String get notificationPayout => 'Payout update';

  @override
  String get payoutMethodsTitle => 'Payout methods';

  @override
  String get profilePayoutMethods => 'Payout methods';

  @override
  String get payoutPreferenceTitle => 'Payout preference';

  @override
  String get payoutPreferenceEurOnly => 'EUR only';

  @override
  String get payoutPreferenceDzdOnly => 'DZD only';

  @override
  String get payoutPreferenceBoth => 'Both';

  @override
  String get payoutPreferenceBothExplainer =>
      'Stripe-funded deliveries are paid in EUR; Chargily-funded deliveries are paid in DZD.';

  @override
  String get payoutPreferenceScopeNote =>
      'Preferences apply to future payouts only.';

  @override
  String get payoutEurTitle => 'EUR payouts (Stripe)';

  @override
  String get payoutEurNotConfiguredBody =>
      'Connect your European bank account to receive payouts in EUR.';

  @override
  String get payoutEurSetupRequiredBody =>
      'Complete your account setup with Stripe to enable EUR payouts.';

  @override
  String get payoutEurPendingVerificationBody =>
      'Stripe is verifying your account details. You\'ll be notified once approved.';

  @override
  String get payoutEurReadyBody =>
      'Your EUR account is verified and ready to receive payouts.';

  @override
  String get payoutEurNeedsAttentionBody =>
      'Your Stripe account requires attention before payouts can proceed.';

  @override
  String get payoutActionSetupEur => 'Set up EUR payouts';

  @override
  String get payoutActionResumeEur => 'Resume setup';

  @override
  String get payoutActionManageEur => 'Manage with Stripe';

  @override
  String get payoutActionRefresh => 'Refresh status';

  @override
  String get payoutDzdTitle => 'DZD payouts (CCP / BaridiMob)';

  @override
  String get payoutDzdNotConfiguredBody =>
      'Add your CCP account and crossed cheque to receive payouts in Algeria.';

  @override
  String get payoutDzdSetupRequiredBody =>
      'Submit your CCP information and crossed cheque to proceed.';

  @override
  String get payoutDzdPendingReviewBody =>
      'Your CCP details and crossed cheque are being reviewed by our team.';

  @override
  String get payoutDzdReadyBody =>
      'Your CCP account is verified and ready for DZD payouts.';

  @override
  String get payoutDzdNeedsAttentionBody =>
      'Your payout profile requires verification or an update.';

  @override
  String get payoutDzdRejectedBody =>
      'This CCP account was not accepted for payouts. Submit a different account in your own name.';

  @override
  String get payoutDzdCorrectionBody =>
      'Your payout details need a correction. Submit them again with a clear photo of the whole crossed cheque.';

  @override
  String get payoutDzdInactiveBody =>
      'DZD payouts are currently inactive for your account.';

  @override
  String get payoutActionSetupDzd => 'Set up DZD payouts';

  @override
  String get payoutActionReplaceDzd => 'Update payout information';

  @override
  String get payoutDzdCcpLabel => 'CCP account';

  @override
  String get payoutDzdRipLabel => 'RIP';

  @override
  String get dzdFormTitle => 'Set up DZD payouts';

  @override
  String get dzdFormScopeExplainer =>
      'This information applies to future eligible payouts. Already-funded payouts keep their historical payout destination.';

  @override
  String get dzdFirstNameLabel => 'First name';

  @override
  String get dzdLastNameLabel => 'Last name';

  @override
  String get dzdCcpNumberLabel => 'CCP account number';

  @override
  String get dzdCcpNumberHint => '1 to 20 digits';

  @override
  String get dzdCcpKeyLabel => 'CCP key';

  @override
  String get dzdCcpKeyHint => '2 digits';

  @override
  String get dzdRipLabel => 'RIP';

  @override
  String get dzdRipHint => '20 digits';

  @override
  String get dzdChequeProofLabel => 'Photo of the full crossed cheque';

  @override
  String get dzdChequeProofHelper =>
      'Upload a clear photo of the full crossed cheque.';

  @override
  String get dzdChequeAddPhoto => 'Upload photo';

  @override
  String get dzdChequeReplacePhoto => 'Replace photo';

  @override
  String get dzdSubmitAction => 'Submit payout information';

  @override
  String get dzdSubmitSuccess => 'Payout information submitted successfully.';

  @override
  String get payoutReasonSetupRequired => 'Payout setup required';

  @override
  String get payoutReasonUnderReview => 'Profile under review';

  @override
  String get payoutReasonNeedsAttention => 'Profile needs attention';

  @override
  String get payoutReasonOnHold => 'Payout on hold';

  @override
  String get payoutReasonDisputeActive => 'Dispute open on this delivery';

  @override
  String get payoutReasonFailed => 'Payout attempt failed';

  @override
  String get payoutReasonReturned => 'Bank payout was returned';

  @override
  String get payoutReasonCountryUnsupported =>
      'Country not supported for Stripe EUR payouts';

  @override
  String payoutRateLabel(String rate) {
    return 'Frozen rate: 1 EUR = $rate DZD';
  }

  @override
  String get payoutHistoryTitle => 'Payout history';

  @override
  String get payoutDetailTitle => 'Payout detail';

  @override
  String get payoutRailLabel => 'Payout rail';

  @override
  String get payoutRailStripeEur => 'Stripe EUR';

  @override
  String get payoutRailManualDzd => 'CCP Transfer (DZD)';

  @override
  String get payoutRailUnavailable => 'Unavailable';

  @override
  String get payoutReferenceLabel => 'Payout reference';

  @override
  String get payoutDeliveryLabel => 'Associated delivery';

  @override
  String get payoutEligibleAtLabel => 'Eligible at';

  @override
  String get payoutSentAtLabel => 'Sent at';

  @override
  String get payoutPaidAtLabel => 'Paid at';

  @override
  String get payoutProtectionEndsAtLabel => 'Protection ends at';

  @override
  String get payoutViewAction => 'View payout';

  @override
  String get payoutViewHistoryAction => 'View payout history';

  @override
  String get payoutOpenStripeError =>
      'Could not open Stripe setup link. Please try again.';

  @override
  String get payoutStatusAwaitingDelivery => 'Awaiting delivery';

  @override
  String get payoutStatusProtectionActive => 'Protection period';

  @override
  String get payoutStatusReleasePending => 'Awaiting release';

  @override
  String get payoutStatusReady => 'Payout ready';

  @override
  String get payoutStatusSent => 'Payout sent';

  @override
  String get payoutStatusNeedsAttention => 'Needs attention';

  @override
  String get payoutProfileReady => 'Payout method ready';

  @override
  String get payoutProfileNeedsAttention => 'Method needs attention';

  @override
  String get earlyArrivalAction => 'I arrived early';

  @override
  String get earlyArrivalConfirmSheetTitle => 'Report early arrival';

  @override
  String get earlyArrivalConfirmSheetBody =>
      'This notifies the sender that you arrived before the scheduled arrival. It does not confirm delivery of the parcel. The sender must confirm your arrival, and payout timing still follows Wassla protection rules.';

  @override
  String get earlyArrivalWaitingSenderTitle =>
      'Waiting for Sender confirmation';

  @override
  String get earlyArrivalWaitingSenderBody =>
      'You reported your early arrival. The sender has been notified to confirm it. Handover and delivery remain separate.';

  @override
  String get earlyArrivalSenderNoticeTitle =>
      'Traveler says they arrived early';

  @override
  String get earlyArrivalSenderNoticeBody =>
      'The traveler reported early arrival for this delivery. Confirming arrival acknowledges their presence; parcel delivery and payout protection remain separate.';

  @override
  String get earlyArrivalConfirmAction => 'Confirm arrival';

  @override
  String get earlyArrivalDeclineAction => 'Decline';

  @override
  String get earlyArrivalConfirmedTitle => 'Arrival confirmed';

  @override
  String get earlyArrivalConfirmedBody =>
      'Early arrival is confirmed. Parcel delivery and 48-hour protection will begin only after the delivery code is verified.';

  @override
  String get earlyArrivalDeclinedTitle => 'Early arrival not confirmed';

  @override
  String get earlyArrivalDeclinedBody =>
      'The early arrival report was not confirmed. Delivery will proceed according to the scheduled route.';

  @override
  String get earlyArrivalScheduledArrivalLabel =>
      'Scheduled arrival for this delivery';

  @override
  String get earlyArrivalPayoutFloorExplanation =>
      'Arriving early does not make the payout available earlier than the protected payout date for this delivery.';

  @override
  String get earlyArrivalPayoutProtectedGateLabel => 'Payout eligible from';

  @override
  String get routeTitle => 'Route';

  @override
  String get routeUnavailableFunded =>
      'The travel route was not recorded for this delivery.';

  @override
  String get routeUnavailableBeforeFunding =>
      'The travel route appears here once the delivery is funded.';

  @override
  String get routeFlightMode => 'Flight';

  @override
  String get routeDriveMode => 'Drive';

  @override
  String get notificationArrivalReported => 'Traveler arrived early';

  @override
  String get notificationArrivalConfirmed => 'Early arrival confirmed';

  @override
  String get notificationArrivalDeclined => 'Early arrival not confirmed';

  @override
  String get routeBasisSnapshot => 'Frozen at booking';

  @override
  String get routeBasisLive => 'Live journey';

  @override
  String get pricingMinimumLabel => 'Minimum price';

  @override
  String get pricingRecommendedLabel => 'Recommended price';

  @override
  String get pricingYourOfferLabel => 'Your offer';

  @override
  String get pricingBelowRecommended =>
      'Below recommendation — travelers may take longer to accept.';

  @override
  String get pricingCompetitive =>
      'Competitive offer — matches more quickly with travelers.';

  @override
  String pricingBelowMinimumError(String amount) {
    return 'Offer must be at least $amount';
  }

  @override
  String get pricingTravelerReceives => 'Traveler receives';

  @override
  String get pricingPlatformFee => 'Wassla fee';

  @override
  String get pricingTotalSenderCost => 'Total sender cost';

  @override
  String get pricingIncrement50c => 'Increase by 50 cents';

  @override
  String get pricingDecrement50c => 'Decrease by 50 cents';

  @override
  String get depositSectionTitle => 'Posting deposit';

  @override
  String depositPresetMin(String amount) {
    return 'Minimum ($amount)';
  }

  @override
  String depositPresetRecommended(String amount) {
    return 'Recommended ($amount)';
  }

  @override
  String depositPresetFull(String amount) {
    return 'Pay in full ($amount)';
  }

  @override
  String get depositPresetCustom => 'Custom';

  @override
  String get depositFullDepositNotice =>
      'Your current amount is paid in full. If you increase the reward or Boost later, an additional balance may be due.';

  @override
  String get depositRemainingBalance => 'Remaining balance at delivery';

  @override
  String get depositCustomAmountLabel => 'Custom deposit amount';

  @override
  String get boostSectionTitle => 'Boost this request';

  @override
  String get boostPresetNone => 'No Boost (€0)';

  @override
  String get boostPreset5 => '+€5';

  @override
  String get boostPreset10 => '+€10';

  @override
  String get boostPresetCustom => 'Custom';

  @override
  String get boostCustomAmountLabel => 'Custom Boost amount';

  @override
  String boostCurrentActive(String amount) {
    return 'Active Boost: $amount';
  }

  @override
  String get boostEditAction => 'Change Boost';

  @override
  String get boostAddAction => 'Add Boost';

  @override
  String get boostPostPublicationOnly =>
      'You can add a Boost now that this request is live. Travelers receive all of it.';

  @override
  String get boostRemoveAction => 'Remove Boost';

  @override
  String get boostHistoryTitle => 'Boost history';

  @override
  String get boostNotEditable =>
      'Boost cannot be edited once an offer has been accepted or the request has expired.';

  @override
  String get guestPaymentTitle => 'Someone else can pay';

  @override
  String get guestCreateAction => 'Create payment link';

  @override
  String get guestShareLead =>
      'Share this secure payment link with someone you trust. They can pay without a Wassla account.';

  @override
  String get guestShareAction => 'Share link';

  @override
  String get guestCopyAction => 'Copy link';

  @override
  String get guestCopiedAction => 'Copied';

  @override
  String get guestLinkCopied => 'Link copied';

  @override
  String get guestShareSubject => 'Wassla payment request';

  @override
  String guestShareMessage(String amount, String link) {
    return 'Could you pay $amount for my Wassla delivery? Here is the secure link: $link';
  }

  @override
  String get guestLinkLabel => 'Payment link';

  @override
  String get guestStatusReady => 'Payment link ready';

  @override
  String guestStatusExpiresOn(String when) {
    return 'Expires $when';
  }

  @override
  String get guestStatusPaying => 'Someone is paying now';

  @override
  String get guestStatusPayingBody =>
      'This updates by itself as soon as their payment goes through.';

  @override
  String get guestStatusExpired => 'This payment link has expired';

  @override
  String get guestStatusRevoked => 'This payment link is no longer active';

  @override
  String get guestStatusNewLinkBody =>
      'Create a new link if someone else should still pay.';

  @override
  String get guestStatusHidden => 'Your earlier link still works';

  @override
  String get guestStatusHiddenBody =>
      'For security it can’t be shown again. Create a new link to share — the earlier one will then stop working.';

  @override
  String get guestStatusClosed => 'This payment can no longer be made by link.';

  @override
  String get guestCreateNewAction => 'Create a new payment link';

  @override
  String get guestMoreActions => 'More options';

  @override
  String get guestRevokeAction => 'Revoke link';

  @override
  String get guestRevokeConfirmTitle => 'Revoke this payment link?';

  @override
  String get guestRevokeConfirmBody =>
      'Anyone who has it won’t be able to pay with it. You can create a new link afterwards.';

  @override
  String get guestRevokeKeep => 'Keep link';

  @override
  String get guestRevokedDone => 'Link revoked';

  @override
  String get guestPaidTitle => 'Payment received';

  @override
  String guestPaidBody(String amount) {
    return '$amount has been paid.';
  }

  @override
  String get guestPaidBodyPlain => 'The payment has been received.';

  @override
  String get guestErrorLoad =>
      'We couldn’t load your payment link. Check your connection and try again.';

  @override
  String get guestErrorBusy =>
      'Someone is paying with your current link right now. Try again once they’ve finished.';

  @override
  String get guestErrorRevokeBusy =>
      'Someone is paying with this link right now, so it can’t be revoked.';

  @override
  String get guestErrorRevoke => 'We couldn’t revoke the link. Try again.';

  @override
  String get guestErrorShare =>
      'Sharing isn’t available right now. Copy the link instead.';

  @override
  String get guestPurposeDeposit => 'Deposit for your request';

  @override
  String get guestPurposeRemaining => 'Remaining delivery payment';

  @override
  String get guestPurposeDelivery => 'Delivery payment';

  @override
  String get guestPurposeBoost => 'Boost payment';

  @override
  String get guestPurposeOther => 'Wassla payment';

  @override
  String get guestPayingNowTitle => 'Someone else is paying this now';

  @override
  String get guestPayingNowBody =>
      'They opened your payment link. This updates as soon as their payment goes through.';

  @override
  String get guestPayPurposeDeposit => 'Deposit for a delivery request';

  @override
  String get guestPayPurposeDelivery => 'Payment for a delivery';

  @override
  String get guestPayPurposeBoost => 'Extra reward for a delivery';

  @override
  String get guestPayHandoff =>
      'You’ll finish on our payment partner’s secure page. Wassla never sees your card details.';

  @override
  String get paymentSuccessAmountPaid => 'Amount paid';

  @override
  String get paymentSuccessViewRequestAction => 'View request';

  @override
  String get paymentSuccessViewDeliveryAction => 'View delivery';

  @override
  String get boostBreakdownTitle => 'What the Boost costs';

  @override
  String get boostTravelerBonusLabel => 'Added to the Traveler reward';

  @override
  String get boostYourCostLabel => 'You pay for the Boost';

  @override
  String get boostAddsOnTop =>
      'The Boost is added on top of the delivery reward you already offered. Base reward + Boost is what the Traveler receives.';

  @override
  String get boostEstimateNotice =>
      'An estimate until you save. Wassla confirms the final amounts.';

  @override
  String boostAmountAboveMaximum(String amount) {
    return 'The most you can Boost is $amount';
  }

  @override
  String get boostHistoryReasonSenderSet => 'You added a Boost';

  @override
  String get boostHistoryReasonSenderIncreased => 'You raised the Boost';

  @override
  String get boostHistoryReasonSenderDecreased => 'You lowered the Boost';

  @override
  String get boostHistoryReasonSenderRemoved => 'You removed the Boost';

  @override
  String get boostHistoryReasonFrozen =>
      'Locked in when the delivery was agreed';

  @override
  String get boostHistoryReasonConsumed => 'Included in the delivery payment';

  @override
  String get boostHistoryReasonReleased =>
      'Released when the match fell through';

  @override
  String get boostHistoryReasonRequestClosed => 'Ended with the request';

  @override
  String get boostHistoryReasonOther => 'Boost updated';

  @override
  String get guestPaymentLinkFailed =>
      'We couldn\'t create a payment link. Try again.';

  @override
  String findTravelersCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count travelers',
      one: '1 traveler',
    );
    return '$_temp0';
  }

  @override
  String get findTravelersIneligibleUnknown =>
      'This request can\'t be matched right now.';

  @override
  String get findTravelersPayDeposit => 'Pay deposit';

  @override
  String findTravelersDepartureLabel(String when) {
    return 'Departs $when';
  }

  @override
  String findTravelersArrivalLabel(String when) {
    return 'Arrives $when';
  }

  @override
  String get findTravelersTrustTitle => 'Checks Wassla has done';

  @override
  String get offerBaseRewardLabel => 'Base delivery reward';

  @override
  String offerBoostAddedOnTop(String amount) {
    return 'Your Boost of $amount is added on top of this.';
  }

  @override
  String get deliveriesOpenOffersSection => 'Open offers';

  @override
  String get journeyPostNew => 'Post a trip';

  @override
  String depositBelowMinimum(String amount) {
    return 'The smallest deposit is $amount';
  }

  @override
  String depositAboveMaximum(String amount) {
    return 'That\'s more than the whole amount of $amount';
  }

  @override
  String offerBoostIncludedTraveler(String amount) {
    return 'Includes the sender\'s Boost of $amount. The total is locked in when you accept.';
  }

  @override
  String offerBoostIncludedSender(String amount) {
    return 'Includes your Boost of $amount, locked in when this offer is accepted. Changing your Boost before then updates this offer.';
  }

  @override
  String offerSenderBoostAddedOnTop(String amount) {
    return 'The sender\'s Boost of $amount is added on top of this.';
  }

  @override
  String offerHistoryBaseReward(String title, String amount) {
    return '$title: base reward $amount';
  }

  @override
  String get moneyTotalExcludingBoost => 'Total before any Boost';

  @override
  String get staleOfferEconomicsChanged =>
      'The amounts on this offer changed. Check the new figures before accepting.';

  @override
  String get offerEconomicsUpdated =>
      'Offer updated. These are the latest amounts.';

  @override
  String get payResultAlreadyCompleteTitle =>
      'This payment is already complete';

  @override
  String get payResultCheckingTitle => 'Checking your payment';

  @override
  String get payResultCheckingBody =>
      'If you finished paying, it will show here in a moment. You don\'t need to pay again.';

  @override
  String get payResultStillCheckingTitle =>
      'We\'re still confirming your payment';

  @override
  String get payResultStillCheckingBody =>
      'This is taking longer than usual. If the payment went through, it will appear here, and you won\'t be charged twice.';

  @override
  String get payResultBackToPayment => 'Back to payment';

  @override
  String get payResultCancelledTitle => 'Payment cancelled';

  @override
  String get payResultCancelledBody =>
      'No completed payment was recorded. You can try again when you\'re ready.';

  @override
  String payResultSomeoneElsePaid(String amount) {
    return 'Someone else paid $amount for this payment.';
  }

  @override
  String get payResultRequestPublished => 'Your request is now published';

  @override
  String get payResultDepositNext =>
      'Find a traveler going your way and send them an offer.';

  @override
  String get payResultPaidInFull => 'Paid in full';

  @override
  String get payResultDepositCoversTotal =>
      'This covers your delivery total as it stands. If you later add a Boost or raise the reward, only the difference would be due.';

  @override
  String get payResultPaidNow => 'Paid now';

  @override
  String get payResultDeliveryTotal => 'Delivery total';

  @override
  String get payResultRemaining => 'Remaining';

  @override
  String payResultRemainingNote(String amount) {
    return 'Pay the remaining $amount to confirm the delivery. The traveler can\'t collect the parcel until it\'s paid.';
  }

  @override
  String get payResultDealNext =>
      'Funds are held pending delivery. Follow the delivery steps to continue.';

  @override
  String get payResultNextTitle => 'What happens next';

  @override
  String get payResultBackHome => 'Back to Home';

  @override
  String payResultPayRemaining(String amount) {
    return 'Pay remaining $amount';
  }

  @override
  String a11yPaymentResultAmount(String label, String amount, String purpose) {
    return '$label: $amount. $purpose';
  }

  @override
  String get guestPayHandoffTitle => 'Finish on the payment page';

  @override
  String get guestPayHandoffBody =>
      'Complete the payment on our payment partner\'s secure page. That page will show you the result, and the person who asked you will see it in Wassla.';

  @override
  String get payResultDepositCredited =>
      'This deposit counts toward your delivery total when a traveler accepts.';

  @override
  String get alertsTitle => 'Route alerts';

  @override
  String get alertsIntro =>
      'We send at most one notification per alert every few hours.';

  @override
  String get alertsEmptyTitle => 'No route alerts yet';

  @override
  String get alertsEmptyBody =>
      'Get a notification when a trip or a parcel appears on a route you care about.';

  @override
  String get alertAdd => 'Add alert';

  @override
  String get alertAddTitle => 'New route alert';

  @override
  String get alertAddSubtitle =>
      'We\'ll notify you when something new appears on this route.';

  @override
  String get alertCreate => 'Create alert';

  @override
  String get alertPickCity => 'Choose a city';

  @override
  String get alertWatchLabel => 'Watch for';

  @override
  String get alertWatchesTrips => 'New trips';

  @override
  String get alertWatchesRequests => 'New parcels';

  @override
  String alertFollowing(String name) {
    return 'Following $name';
  }

  @override
  String alertRemoveA11y(String route) {
    return 'Remove alert for $route';
  }

  @override
  String get alertRemoved => 'Alert removed';

  @override
  String get alertSwitchLabel => 'Alert me about this route';

  @override
  String get alertTurnedOn => 'Alert turned on';

  @override
  String get alertTurnedOff => 'Alert turned off';

  @override
  String get alertLimitReached =>
      'You have reached the maximum number of active alerts. Remove one to add another.';

  @override
  String get alertSameCity => 'Choose two different cities.';

  @override
  String get alertSelf => 'You can\'t follow yourself.';

  @override
  String get browseTripsTitle => 'Trips leaving soon';

  @override
  String get browseRequestsTitle => 'Parcels looking for a traveler';

  @override
  String get browseTripsEmptyTitle => 'No trips right now';

  @override
  String get browseTripsEmptyBody =>
      'Trips appear here as soon as travelers publish them.';

  @override
  String get browseTripsEmptyAction => 'Send a parcel';

  @override
  String get browseRequestsEmptyTitle => 'No open parcels right now';

  @override
  String get browseRequestsEmptyBody =>
      'Parcels appear here as soon as senders post them.';

  @override
  String get browseRequestsEmptyAction => 'Add a journey';

  @override
  String get browseNoMatchTitle => 'No results';

  @override
  String get browseNoMatchBody =>
      'Nothing matches these filters. Try other cities or another date.';

  @override
  String get browseClearFilters => 'Clear filters';

  @override
  String browseClearFilter(String label) {
    return 'Clear $label';
  }

  @override
  String get browseFilterFrom => 'From';

  @override
  String get browseFilterTo => 'To';

  @override
  String get browseFilterDate => 'From date';

  @override
  String get countryAlgeria => 'Algeria';

  @override
  String get countryFrance => 'France';

  @override
  String get countrySpain => 'Spain';

  @override
  String get countryGermany => 'Germany';

  @override
  String get corridorAll => 'All routes';

  @override
  String corridorA11y(String from, String to) {
    return 'From $from to $to';
  }

  @override
  String get discoveryListingsOffTitle => 'Not available right now';

  @override
  String get discoveryListingsOff =>
      'Browsing trips and parcels is paused for now. Please check back later.';

  @override
  String get discoveryProfilesOffTitle => 'Not available right now';

  @override
  String get discoveryProfilesOff =>
      'Public profiles are paused for now. Please check back later.';

  @override
  String get discoveryProfileGone => 'This profile is no longer available.';

  @override
  String get discoveryShowingEarlier => 'Showing what we loaded earlier';

  @override
  String get requestCarryAction => 'I can carry this';

  @override
  String get carryExplain =>
      'Tell the sender you could carry this. It isn\'t an offer: there is no price, nothing is reserved, and the sender decides what happens next.';

  @override
  String get carryChooseTrip => 'Which trip?';

  @override
  String get carryChooseTripHint => 'Pick the journey you would carry this on.';

  @override
  String get carryPublishTrip => 'Add a journey to carry this';

  @override
  String get carrySentTitle => 'Sender notified';

  @override
  String get carryAlreadySentTitle => 'Already sent';

  @override
  String get carrySentBody =>
      'The sender got one notification that you can carry this. They can look at your trip and propose a delivery. Nothing is reserved.';

  @override
  String get carryIncompatible => 'This parcel doesn\'t fit that trip:';

  @override
  String get carryDailyCap =>
      'You have reached today\'s limit for \"I can carry this\". Try again tomorrow.';

  @override
  String get carryRequestGone => 'That parcel is no longer open.';

  @override
  String get carryJourneyGone => 'That trip is no longer available.';

  @override
  String get rejectCapacity => 'There isn\'t enough space left on every leg.';

  @override
  String get rejectDeadline => 'It would arrive after the deadline.';

  @override
  String get rejectTiming => 'The dates don\'t line up.';

  @override
  String get rejectRoute => 'The detour from the route is too large.';

  @override
  String get rejectClosed => 'One of them is no longer open.';

  @override
  String get rejectVerification =>
      'The traveler\'s verification isn\'t complete.';

  @override
  String get rejectItem => 'This item can\'t be carried on this trip.';

  @override
  String get rejectGeneric => 'The trip and the parcel don\'t match.';

  @override
  String get focusTripMissingTitle => 'That trip doesn\'t fit this parcel';

  @override
  String get focusTripMissingBody =>
      'This trip isn\'t in your list of compatible travelers.';

  @override
  String tripLeaves(String date) {
    return 'Leaves $date';
  }

  @override
  String get tripArrives => 'Arrives';

  @override
  String get tripSpace => 'Space left';

  @override
  String tripSpaceLeft(String kg) {
    return '$kg kg left';
  }

  @override
  String get tripSpaceLeftUnderOne => 'Less than 1 kg left';

  @override
  String tripSpaceKg(String kg) {
    return '$kg kg';
  }

  @override
  String get tripSpaceKgUnderOne => 'Less than 1 kg';

  @override
  String get tripPreviewSubtitle =>
      'You propose first. Nothing is booked from here.';

  @override
  String get tripChooseParcel => 'Choose one of your parcels';

  @override
  String get tripPostForRoute => 'Post a parcel for this route';

  @override
  String requestCardDeadline(String date) {
    return 'By $date';
  }

  @override
  String requestCardFrom(String name) {
    return 'From $name';
  }

  @override
  String get requestOfferedReward => 'Offered reward';

  @override
  String publicRatingA11y(String rating) {
    return 'Rated $rating out of 5';
  }

  @override
  String get profileNoUsualRoutes => 'No usual routes shown';

  @override
  String get homeMatchesTitle => 'Matches for you';

  @override
  String get homeMatchesEmptyTitle => 'No matches yet';

  @override
  String get homeMatchesSenderNone =>
      'Post a parcel and the travelers who fit it will show up here.';

  @override
  String get homeMatchesSenderWaiting =>
      'No traveler fits your open parcels yet. We\'ll show them here as soon as one does.';

  @override
  String get homeMatchesTravelerNone =>
      'Add a journey and the parcels that fit it will show up here.';

  @override
  String get homeMatchesTravelerWaiting =>
      'No parcel fits your journeys yet. We\'ll show them here as soon as one does.';

  @override
  String get homeTripsTitle => 'Trips leaving soon';

  @override
  String get homeTripsEmptyBody =>
      'Trips that are about to leave will show up here.';

  @override
  String get homeRequestsTitle => 'Parcels looking for a traveler';

  @override
  String get homeRequestsEmptyBody =>
      'Parcels that need a traveler will show up here.';

  @override
  String get homeListingsEmptyTitle => 'Nothing listed yet';

  @override
  String get homeListingsEmptyRouteTitle => 'Nothing on this route yet';

  @override
  String get homePeopleSenderTitle => 'Travelers on Wassla';

  @override
  String get homePeopleTravelerTitle => 'Senders on Wassla';

  @override
  String get homePeopleEmptyTitle => 'No public profiles yet';

  @override
  String get homePeopleEmptyBody =>
      'People who choose to show a public profile will appear here.';

  @override
  String get optInTitle => 'Be found on Wassla';

  @override
  String get optInBody =>
      'Let senders and travelers find you. Only your first name, your trust badges and the routes you choose are shown.';

  @override
  String get optInPreviewLabel => 'This is what others would see';

  @override
  String get optInShow => 'Show my profile';

  @override
  String get optInNotNow => 'Not now';

  @override
  String get personTitle => 'Profile';

  @override
  String get personGoneTitle => 'Profile unavailable';

  @override
  String get personUsualRoutes => 'Usual routes';

  @override
  String personAlertHint(String name) {
    return 'Turn on an alert to hear when $name posts on a route.';
  }

  @override
  String personNoUsualRoutes(String name) {
    return '$name hasn\'t added usual routes.';
  }

  @override
  String personTrips(String name) {
    return '$name\'s trips';
  }

  @override
  String personRequests(String name) {
    return '$name\'s parcels';
  }

  @override
  String personNothingListed(String name) {
    return '$name has no live trips or open parcels right now.';
  }

  @override
  String get publicProfileTitle => 'Public profile';

  @override
  String get publicProfileIntro =>
      'A public profile lets senders and travelers find you and follow your routes. It is off unless you turn it on, and you can turn it off at any time.';

  @override
  String get publicShownTitle => 'What others see';

  @override
  String get publicShownFirstName => 'Your first name';

  @override
  String get publicShownTrust =>
      'Whether your identity is verified, your rating and your completed deliveries';

  @override
  String get publicShownMemberSince => 'The month and year you joined';

  @override
  String get publicShownRoutes => 'The usual routes you choose';

  @override
  String get publicNeverTitle => 'Never shown';

  @override
  String get publicNeverContact => 'Your last name, email or phone number';

  @override
  String get publicNeverPlaces => 'An exact address or position';

  @override
  String get publicShowSwitch => 'Show my public profile';

  @override
  String get publicSwitchOn => 'Others can find you.';

  @override
  String get publicSwitchOff => 'Others can\'t find you.';

  @override
  String get publicProfileOn => 'Your public profile is on';

  @override
  String get publicHiddenNotice =>
      'Your profile is not currently visible to others.';

  @override
  String get publicRoutesTitle => 'Usual routes';

  @override
  String get publicRoutesHint =>
      'Up to three routes you often travel or send on.';

  @override
  String get publicRoutesLimit => 'You\'ve added the maximum of three routes.';

  @override
  String get publicRouteAdd => 'Add a usual route';

  @override
  String get publicRouteFrom => 'Usual route: from';

  @override
  String get publicRouteTo => 'Usual route: to';

  @override
  String publicRouteRemove(String route) {
    return 'Remove $route';
  }

  @override
  String get publicRouteDuplicate => 'That route is already on your profile.';

  @override
  String get publicPreviewTitle => 'Your public card';

  @override
  String get publicPreviewVisible => 'This is what others see right now.';

  @override
  String get publicPreviewHidden =>
      'This is what others would see if you turn it on.';

  @override
  String get notificationRouteAlert => 'New on a route you follow';

  @override
  String get notificationTravelerInterested =>
      'A traveler can carry your parcel';

  @override
  String get journeyModeSea => 'Ferry';

  @override
  String get routeSeaMode => 'Ferry';

  @override
  String get routeSeaSwitchedOff => 'Ferry legs are switched off for now.';

  @override
  String get routeSeaTicketNote =>
      'A ferry leg needs your ticket checked before the journey can go live. You add it after saving.';

  @override
  String get routeSeaRefusedSwitchedOff =>
      'Ferry legs are switched off right now. Choose another way to travel this part.';

  @override
  String get routeSeaRefusedNoCrossing =>
      'No ferry line runs between these two cities in this direction right now.';

  @override
  String get routeSeaRefusedNotPort =>
      'A ferry runs between port cities. Choose the city, not an airport, for each end of this part.';

  @override
  String get routeSeaLinesFailedTitle => 'Ferry lines didn\'t load';

  @override
  String get routeSeaLinesFailedBody =>
      'Flights and road legs work as usual. Try again to add a ferry leg.';

  @override
  String get routeErrorSeaRefused =>
      'A ferry leg on your route can\'t be used right now. The reason is shown on that leg.';

  @override
  String get journeyErrorStopInvalid =>
      'One of your stops has handover options we can\'t use. Check the options on each stop.';

  @override
  String get routeCapacityMore => 'More capacity options';

  @override
  String get routeCapacityMoreHelp =>
      'Optional. Leave a box empty to set no limit.';

  @override
  String get routeVolumeLabel => 'Volume (litres)';

  @override
  String get routeParcelsLabel => 'Number of parcels';

  @override
  String get routeVolumeInvalid =>
      'Enter a whole number of litres from 1 to 200,000.';

  @override
  String get routeParcelsInvalid =>
      'Enter a whole number of parcels from 1 to 10,000.';

  @override
  String get routeHandoverAction => 'Handover options';

  @override
  String get routeHandoverBoth => 'Takes pickups and drop-offs';

  @override
  String get routeHandoverPickups => 'Pickups only';

  @override
  String get routeHandoverDropoffs => 'Drop-offs only';

  @override
  String get routeHandoverNone => 'No handovers here';

  @override
  String routeHandoverSheetTitle(String stop) {
    return 'Handover at $stop';
  }

  @override
  String get routeHandoverPickupLabel => 'Accept pickups here';

  @override
  String get routeHandoverPickupHelp =>
      'A sender can hand you a parcel at this stop.';

  @override
  String get routeHandoverDropoffLabel => 'Accept drop-offs here';

  @override
  String get routeHandoverDropoffHelp =>
      'You can hand a parcel to its recipient at this stop.';

  @override
  String get routeHandoverWindowTitle => 'Time window';

  @override
  String get routeHandoverWindowHelp =>
      'Optional. When you can meet at this stop.';

  @override
  String get routeHandoverWindowFrom => 'From';

  @override
  String get routeHandoverWindowTo => 'Until';

  @override
  String get routeHandoverWindowClear => 'Remove time window';

  @override
  String get routeHandoverNoteLabel => 'Note';

  @override
  String get routeHandoverNoteHint =>
      'For example: meet at the café by the ferry terminal.';

  @override
  String get routeHandoverNoteSeen =>
      'Only you see this until a delivery that uses this stop is paid for. Then the sender of that delivery sees it too.';

  @override
  String get routeWindowIncomplete =>
      'Set both a start and an end, or remove the window.';

  @override
  String get routeWindowOrder => 'The window has to end after it starts.';

  @override
  String get routeWindowOutside =>
      'The window has to fall between arriving at this stop and leaving it.';

  @override
  String get routeCarryTitle => 'What you carry';

  @override
  String get routeCarryHelp =>
      'Switch off anything you won\'t take. Senders only find you for parcels you accept.';

  @override
  String get routeCarryFragile => 'Fragile items';

  @override
  String get routeCarryLastOne => 'At least one kind of item has to stay on.';

  @override
  String get journeyPauseAction => 'Pause journey';

  @override
  String get journeyPauseConfirmTitle => 'Pause this journey?';

  @override
  String get journeyPauseConfirmBody =>
      'Senders stop finding it and nobody can start a new offer on it. Deliveries already paid for carry on, and an offer already pending can\'t be accepted until you resume.';

  @override
  String get journeyPaused => 'Journey paused.';

  @override
  String get journeyResumeAction => 'Resume journey';

  @override
  String get journeyResumed => 'Journey resumed.';

  @override
  String get journeyPausedBannerTitle => 'This journey is paused';

  @override
  String get journeyPausedBannerBody =>
      'Senders can\'t find it and offers on it can\'t be accepted. Deliveries already paid for carry on as normal.';

  @override
  String get journeyPausedStaffBody =>
      'Wassla paused this journey. Contact support to have it resumed.';

  @override
  String get journeyErrorNotPausable =>
      'This journey can\'t be paused in its current state.';

  @override
  String get journeyErrorPausedByStaff =>
      'Wassla paused this journey, so only support can resume it.';

  @override
  String journeyCapacityVolumeValue(int litres) {
    return '$litres L';
  }

  @override
  String journeyCapacityParcelsValue(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count parcels',
      one: '1 parcel',
    );
    return '$_temp0';
  }

  @override
  String get journeyHandoverTitle => 'Handover at your stops';

  @override
  String journeyHandoverWindow(String from, String to) {
    return 'Between $from and $to';
  }

  @override
  String get journeyCarryTitle => 'What you carry';

  @override
  String get journeyCarryAll => 'Takes every kind of item';

  @override
  String journeyCarryRefuses(String items) {
    return 'Won\'t take: $items';
  }

  @override
  String get journeyCarryNoFragile => 'No fragile items';

  @override
  String get proofExplainerSea =>
      'Upload your ferry ticket or booking confirmation. We check it before your journey can match parcels.';

  @override
  String get proofChecklistTitle => 'A good photo shows';

  @override
  String get proofChecklistFlight =>
      'Your name, the flight number, the date and both airports.';

  @override
  String get proofChecklistSea =>
      'Your name, the ferry company, the date and both ports.';

  @override
  String get rejectSea =>
      'A ferry line on this trip isn\'t available right now.';

  @override
  String get rejectPaused => 'The traveler has paused this trip.';

  @override
  String get rejectHandover =>
      'The traveler doesn\'t take handovers at the places you need.';

  @override
  String get rejectNotAccepted =>
      'The traveler doesn\'t take this kind of item.';

  @override
  String get rejectVolume =>
      'There isn\'t enough room left for this parcel\'s size.';

  @override
  String get rejectParcelSlots => 'The traveler has no parcel places left.';

  @override
  String get findTravelersSeaProofApproved => 'Ferry ticket verified';

  @override
  String get findTravelersCaveatVolume =>
      'This traveler limits volume and your request has no size, so we couldn\'t check that your parcel fits. They decide when they accept.';

  @override
  String get staleJourneyPaused =>
      'This journey is paused, so nothing on it can be accepted until it resumes.';

  @override
  String get dealHandoverTitle => 'Where and when to meet';

  @override
  String get dealHandoverPickup => 'Pickup';

  @override
  String get dealHandoverDropoff => 'Drop-off';

  @override
  String get journeyPriceTitle => 'Your price';

  @override
  String get journeyPriceOptional => 'Optional';

  @override
  String get journeyPriceNote =>
      'Senders see your price plus Wassla\'s fee. Wassla\'s minimum for each parcel still applies.';

  @override
  String get journeyPricePerKgLabel => 'Price per kg';

  @override
  String get journeyPriceMinimumLabel => 'Minimum per parcel';

  @override
  String get journeyPriceErrorBoth =>
      'Fill in both amounts, or leave both empty.';

  @override
  String journeyPriceErrorMaximum(String amount) {
    return 'At most $amount.';
  }

  @override
  String get journeyPriceErrorTooHigh =>
      'That amount is higher than Wassla allows.';

  @override
  String get journeyPriceDisabled =>
      'Setting a price is not available right now.';

  @override
  String get journeyPriceNotEditable =>
      'The price can no longer be changed on this journey.';

  @override
  String get journeyPriceNone =>
      'No price set. Senders propose their own amount.';

  @override
  String get journeyPriceSet => 'Set a price';

  @override
  String get journeyPriceChange => 'Change';

  @override
  String get journeyPriceSave => 'Save price';

  @override
  String get journeyPriceRemove => 'Remove price';

  @override
  String get journeyPriceSaved => 'Price saved.';

  @override
  String get journeyPriceCleared => 'Price removed.';

  @override
  String get journeyPriceAppliesToNew =>
      'A new price applies to offers made from now on. Offers and deals already made keep theirs.';

  @override
  String journeyPricePerKgValue(String amount) {
    return '$amount per kg';
  }

  @override
  String journeyPriceMinimumValue(String amount) {
    return 'Minimum $amount per parcel';
  }

  @override
  String tripPriceFrom(String perKg, String minimum) {
    return 'from $perKg per kg, minimum $minimum';
  }

  @override
  String get findTravelersSortPrice => 'Lowest price';

  @override
  String findTravelersListedPrice(String amount) {
    return '$amount for this parcel';
  }

  @override
  String get offerListedLabel => 'Their price for this parcel';

  @override
  String offerSendListed(String amount) {
    return 'Offer $amount';
  }

  @override
  String get offerDifferentAmount => 'Offer a different amount';

  @override
  String get offerBelowListedNote =>
      'That is below their price, so they may decline or counter.';

  @override
  String get offerUseListed => 'Use their price';

  @override
  String get tripPrice => 'Price';

  @override
  String get trackingNumberLabel => 'Tracking number';

  @override
  String get trackingNumberCopy => 'Copy tracking number';

  @override
  String get trackingNumberCopied => 'Tracking number copied';

  @override
  String get progressTitle => 'Trip progress';

  @override
  String get progressIntro =>
      'Tell senders how your trip is going. They see your update marked as reported by you. It never moves a payment.';

  @override
  String get progressActionAtPort => 'I\'m at the port';

  @override
  String get progressActionDeparted => 'I\'ve departed';

  @override
  String get progressActionArrived => 'I\'ve arrived';

  @override
  String get progressReportedAtPort => 'At the port';

  @override
  String get progressReportedDeparted => 'Departed';

  @override
  String get progressReportedArrived => 'Arrived';

  @override
  String progressAvailableFrom(String time) {
    return 'You can report this from $time.';
  }

  @override
  String get progressNeedsNetwork =>
      'Needs a connection. Nothing is saved for later.';

  @override
  String get progressUndo => 'Undo';

  @override
  String get progressUndoHint => 'You can undo an update for 10 minutes.';

  @override
  String get progressSent => 'Update shared with the senders.';

  @override
  String get progressUndone => 'Update removed.';

  @override
  String get progressErrorOffline =>
      'No connection, so your update was not sent. Try again when you are back online.';

  @override
  String get progressErrorTooEarly =>
      'It is too early to report this. Reports open 24 hours before the planned time.';

  @override
  String get progressErrorOutOfOrder =>
      'That step does not come next. Pull down to refresh.';

  @override
  String get progressErrorNotReportable =>
      'This journey cannot take updates right now.';

  @override
  String get progressErrorUndoClosed =>
      'The 10 minutes to undo this update have passed.';

  @override
  String get progressErrorHasFollowup =>
      'A later update depends on this one, so it cannot be undone.';

  @override
  String progressQuestionDeparted(String place) {
    return 'Did you depart from $place?';
  }

  @override
  String get progressQuestionDepartedBare => 'Did you depart?';

  @override
  String progressQuestionArrived(String place) {
    return 'Did you arrive in $place?';
  }

  @override
  String get progressQuestionArrivedBare => 'Did you arrive?';

  @override
  String progressQuestionAtPort(String place) {
    return 'Are you at the port in $place?';
  }

  @override
  String get progressQuestionAtPortBare => 'Are you at the port?';

  @override
  String get progressYesDeparted => 'Yes, departed';

  @override
  String get progressYesArrived => 'Yes, arrived';

  @override
  String get progressYesAtPort => 'Yes, I\'m here';

  @override
  String get progressNotYet => 'Not yet';

  @override
  String get progressQuestionBody =>
      'Senders with a parcel on this leg will see your answer, marked as reported by you.';

  @override
  String get dealProgressAtPort => 'Your traveler is at the port';

  @override
  String get dealProgressDeparted => 'Your traveler has departed';

  @override
  String get dealProgressArrived => 'Your traveler has arrived';

  @override
  String get dealProgressReportedBy => 'Reported by the traveler';

  @override
  String get notificationProgressReported => 'Update from your traveler';

  @override
  String get notificationLegReminder => 'How is your trip going?';

  @override
  String get problemsTitle => 'Problems reported';

  @override
  String get problemReportAction => 'Report a problem';

  @override
  String get problemSheetTitle => 'Report a problem';

  @override
  String get problemSheetIntro => 'What went wrong with this delivery?';

  @override
  String get problemKindSenderUnavailable => 'The sender did not come';

  @override
  String get problemKindTravelerNoShow => 'The traveler did not come';

  @override
  String get problemKindRecipientUnavailable =>
      'The recipient is not available';

  @override
  String get problemKindParcelMismatch =>
      'The parcel is not what was described';

  @override
  String get problemKindParcelDamaged => 'The parcel is damaged';

  @override
  String get problemKindTripDisrupted => 'The trip is cancelled or delayed';

  @override
  String get problemKindCustomsDelay => 'Held up at customs';

  @override
  String get problemKindOther => 'Something else';

  @override
  String get problemNoteLabel => 'Note (optional)';

  @override
  String get problemNoteHint =>
      'Add anything that helps, such as where you are.';

  @override
  String get problemNextBody =>
      'The other person is told. Wassla staff look at damage and mismatches right away. Reporting does not cancel or refund anything.';

  @override
  String get problemSendAction => 'Send report';

  @override
  String get problemSent => 'Report sent. The other person has been told.';

  @override
  String get problemReportedByYou => 'Reported by you';

  @override
  String get problemReportedByOther => 'Reported by the other person';

  @override
  String get problemStatusOpen => 'Sent';

  @override
  String get problemStatusEscalated => 'With Wassla staff';

  @override
  String get problemStatusAcknowledged => 'Being looked at';

  @override
  String get problemStatusClosed => 'Closed';

  @override
  String get problemErrorOffline =>
      'No connection. Nothing was sent. Try again when you are online.';

  @override
  String get problemErrorNoShowClosed =>
      'This can’t be reported right now. The pickup time may not have come yet, or the parcel may already be collected.';

  @override
  String get problemErrorNotAllowed =>
      'This delivery can’t take a report right now.';

  @override
  String get problemErrorNoteTooLong =>
      'The note is too long. Keep it under 1,000 characters.';

  @override
  String get noShowActionSender => 'The sender did not come';

  @override
  String get noShowActionTraveler => 'The traveler did not come';

  @override
  String get noShowSheetIntro =>
      'Tell us if the other person has not shown up for the handover.';

  @override
  String get noShowNextBody =>
      'Wassla staff will look at it. Nothing is cancelled or refunded yet.';

  @override
  String get noShowSendAction => 'Send to Wassla';

  @override
  String get noShowReportedSender =>
      'You reported that the sender did not come';

  @override
  String get noShowReportedTraveler =>
      'You reported that the traveler did not come';

  @override
  String get noShowMessageInChat => 'Message in chat';

  @override
  String get noShowReplyInChat => 'Reply in chat';

  @override
  String get noShowAgainstSenderTitle => 'The traveler says you did not come';

  @override
  String get noShowAgainstSenderBody =>
      'If there is a mix-up, tell them in chat. Wassla staff will look at it. Nothing is cancelled or refunded yet.';

  @override
  String get noShowAgainstTravelerTitle => 'The sender says you did not come';

  @override
  String get noShowAgainstTravelerBody =>
      'If there is a mix-up, tell them in chat. Wassla staff will look at it. Nothing is cancelled or refunded yet.';

  @override
  String get notificationProblemReported =>
      'A problem was reported on a delivery';

  @override
  String get notificationScheduleChangeProposed => 'New times need your answer';

  @override
  String get notificationScheduleChangeAnswered =>
      'A sender answered your new times';

  @override
  String get notificationScheduleChangeApplied => 'The times of a trip changed';

  @override
  String get notificationScheduleChangeWithdrawn => 'New times were withdrawn';

  @override
  String get scheduleDeparture => 'Departure';

  @override
  String get scheduleArrival => 'Arrival';

  @override
  String get schedulePickup => 'Pickup';

  @override
  String get scheduleParcelFallback => 'A parcel';

  @override
  String get scheduleReasonDeadline =>
      'The new arrival is after your deadline.';

  @override
  String get scheduleReasonShift =>
      'The arrival moves by more than the allowed margin.';

  @override
  String get scheduleReasonPickup => 'The pickup time moves.';

  @override
  String get scheduleSectionTitle => 'Trip times';

  @override
  String get scheduleSectionIntro =>
      'Plans changed? Update your times. Senders whose parcel is affected are told, and some may need to agree.';

  @override
  String get scheduleChangeAction => 'Change times';

  @override
  String scheduleWaitingPill(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Waiting for $count senders',
      one: 'Waiting for 1 sender',
    );
    return '$_temp0';
  }

  @override
  String get scheduleWaitingBody =>
      'Your trip keeps its current times until every sender who must agree has answered.';

  @override
  String get scheduleSendersTitle => 'Senders asked';

  @override
  String get scheduleConsentPending => 'Waiting';

  @override
  String get scheduleConsentAccepted => 'Agreed';

  @override
  String get scheduleConsentDeclined => 'Declined';

  @override
  String get scheduleWithdrawAction => 'Withdraw the new times';

  @override
  String get scheduleWithdrawn => 'The new times were withdrawn.';

  @override
  String get scheduleWithdrawnByYou =>
      'You withdrew the last new times. Your trip keeps its earlier times.';

  @override
  String get scheduleWithdrawnNoLongerValid =>
      'The last new times were dropped because the trip had moved on. Your trip keeps its current times.';

  @override
  String get scheduleChangeTitle => 'Change times';

  @override
  String get scheduleChangeIntro =>
      'Pick the new departure and arrival for the legs that changed. You will see who is affected before anything is sent.';

  @override
  String get scheduleStopsNote =>
      'Only times can change on a live trip. To add or remove a stop, cancel the trip and create a new one.';

  @override
  String get scheduleReviewAction => 'Review the changes';

  @override
  String get scheduleReviewTitle => 'Review new times';

  @override
  String get scheduleEditTimes => 'Edit times';

  @override
  String get scheduleSendAction => 'Send new times';

  @override
  String get scheduleApplyAction => 'Apply new times';

  @override
  String get scheduleAppliesAtOnceTitle => 'No sender needs to agree';

  @override
  String get scheduleAppliesAtOnceBody =>
      'These times apply as soon as you send them. Affected senders are told.';

  @override
  String scheduleWaitsTitle(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count senders must agree first',
      one: '1 sender must agree first',
    );
    return '$_temp0';
  }

  @override
  String get scheduleWaitsBody =>
      'The new times apply once they all agree. Until then your trip keeps its current times. A sender who declines can cancel, and that cancellation is counted as yours.';

  @override
  String get scheduleNewTimesTitle => 'New times';

  @override
  String get scheduleAffectedTitle => 'Parcels affected';

  @override
  String get scheduleNoParcelsAffected =>
      'No parcel is affected by these times.';

  @override
  String get scheduleMustAgreeTitle => 'Senders who must agree';

  @override
  String get scheduleToldTitle => 'Senders who will be told';

  @override
  String get scheduleReasonLabel => 'Note to senders (optional)';

  @override
  String get scheduleReasonHint =>
      'For example: the flight was moved by the airline.';

  @override
  String get scheduleReasonHelper => 'Senders who are asked will read this.';

  @override
  String scheduleSentToSenders(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Sent. Waiting for $count senders.',
      one: 'Sent. Waiting for 1 sender.',
    );
    return '$_temp0';
  }

  @override
  String get scheduleApplied =>
      'New times saved. Affected senders have been told.';

  @override
  String get scheduleErrorOffline =>
      'No connection. Nothing was changed. Try again when you are online.';

  @override
  String get scheduleErrorNotReschedulable =>
      'Times can only change on a trip that is live and not finished.';

  @override
  String get scheduleErrorEmpty =>
      'These are the times already in force. Change at least one.';

  @override
  String get scheduleErrorPending =>
      'New times are already waiting for senders. Withdraw them first to send others.';

  @override
  String get scheduleErrorLegArrived =>
      'A leg that has already arrived can’t change.';

  @override
  String get scheduleErrorLegDeparted =>
      'A leg that has already departed keeps its departure. Only its arrival can move.';

  @override
  String get scheduleErrorDepartureInPast =>
      'A departure can’t be in the past.';

  @override
  String get scheduleErrorNotWaiting =>
      'These new times are no longer waiting. The screen has been refreshed.';

  @override
  String get scheduleAnswerTitle => 'New times';

  @override
  String get scheduleNoneTitle => 'No change to the times';

  @override
  String get scheduleNoneBody =>
      'The traveler has not changed the times of this delivery.';

  @override
  String get scheduleAskedHeadline => 'The traveler changed the times';

  @override
  String get scheduleAskedBody =>
      'Your delivery is affected. Check the new times and tell us if they work for you.';

  @override
  String get scheduleYouAcceptedHeadline => 'You agreed to the new times';

  @override
  String get scheduleYouDeclinedHeadline => 'You declined the new times';

  @override
  String get scheduleAppliedHeadline => 'The new times are in force';

  @override
  String get scheduleAppliedBody =>
      'The traveler’s trip now runs on the times below.';

  @override
  String get scheduleWithdrawnHeadline => 'The new times were withdrawn';

  @override
  String get scheduleWithdrawnBody =>
      'Nothing changes for your delivery. The earlier times still stand.';

  @override
  String get scheduleInformedHeadline => 'The traveler’s times changed';

  @override
  String get scheduleInformedBody =>
      'Your parcel has already been collected, so you are not asked to agree. The arrival you agreed to when you paid still protects you. If something is wrong, you can report a problem or open a dispute.';

  @override
  String get scheduleCompareTitle => 'Old and new times';

  @override
  String scheduleYourDeadline(String date) {
    return 'Your deadline: $date';
  }

  @override
  String get scheduleWhyTitle => 'Why we are asking';

  @override
  String get scheduleTravelerNote => 'Note from the traveler';

  @override
  String get scheduleLegsTitle => 'Changed legs';

  @override
  String get scheduleAcceptAction => 'Accept the new times';

  @override
  String get scheduleAcceptInstead => 'Accept the new times instead';

  @override
  String get scheduleDeclineAction => 'Decline';

  @override
  String get scheduleDeclineInstead => 'Decline instead';

  @override
  String get scheduleDeclineKeep => 'Go back';

  @override
  String get scheduleDeclineConfirmTitle => 'Decline the new times?';

  @override
  String get scheduleDeclineConfirmBody =>
      'Nothing is cancelled. You will then be able to cancel this delivery, and because the traveler changed the times, that cancellation is not counted as yours. You can still change your mind until the traveler decides.';

  @override
  String get scheduleAcceptedSnack => 'You agreed to the new times.';

  @override
  String get scheduleDeclinedSnack => 'You declined the new times.';

  @override
  String get scheduleIfYouCancelTitle => 'If you cancel now';

  @override
  String get scheduleCancelCountsAsTraveler =>
      'Counted as the traveler’s cancellation, because they changed the times.';

  @override
  String get scheduleCancelNotAvailable =>
      'This delivery can’t be cancelled right now.';

  @override
  String get scheduleInformedActionsTitle => 'If something is wrong';

  @override
  String get scheduleErrorNoAnswerNeeded =>
      'No answer is needed for this delivery.';

  @override
  String get scheduleViewAction => 'View';

  @override
  String get scheduleDealAskedBody =>
      'Check the new times and tell us if they work for you.';

  @override
  String get scheduleDealDeclinedBody =>
      'You can cancel this delivery, and it won’t be counted as yours.';

  @override
  String get scheduleDealAcceptedBody =>
      'You agreed to the new times. We are waiting for the other senders.';

  @override
  String get scheduleDealInformedBody =>
      'The traveler’s times changed after pickup. See the old and new times.';

  @override
  String offerAnswerBy(String when) {
    return 'Answer by $when';
  }

  @override
  String offerWaitingUntil(String when) {
    return 'Waiting for an answer until $when';
  }

  @override
  String offerAnswerWithin(String time) {
    return 'Answer within $time';
  }

  @override
  String offerWaitingWithin(String time) {
    return 'Waiting for an answer, $time left';
  }

  @override
  String offerMinutesLeft(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count minutes',
      one: '1 minute',
      zero: 'less than a minute',
    );
    return '$_temp0';
  }

  @override
  String get offerDeadlinePassed => 'The time to answer has passed';

  @override
  String offerExpiredOn(String when) {
    return 'Expired $when';
  }

  @override
  String get offerExpiredTitle => 'This proposal expired';

  @override
  String get offerExpiredBodySender =>
      'No answer came in time. Nothing was reserved or charged, and your parcel is still open for other travelers.';

  @override
  String get offerExpiredBodyTraveler =>
      'No answer came in time. Nothing was reserved or charged. Other parcels may fit your trip.';

  @override
  String get offerExpiredActionSender => 'Propose to another traveler';

  @override
  String get offerExpiredActionTraveler => 'Browse parcels';

  @override
  String get notificationOfferReminder => 'A proposal is about to expire';

  @override
  String get notificationFitsTrip => 'A parcel fits your trip';

  @override
  String requestFitsTripHint(String route) {
    return 'Suggested for your trip $route';
  }

  @override
  String get discoveryFocusGoneRequestTitle => 'This parcel is no longer open';

  @override
  String get discoveryFocusGoneRequestBody =>
      'It may have been taken or withdrawn. Here are the parcels that are open now.';

  @override
  String get discoveryFocusGoneTripTitle => 'This trip is no longer listed';

  @override
  String get discoveryFocusGoneTripBody =>
      'Here are the trips that are listed now.';

  @override
  String get reviewsTitle => 'Reviews';

  @override
  String reviewsCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count reviews',
      one: '1 review',
    );
    return '$_temp0';
  }

  @override
  String get reviewsOpenHint => 'See reviews';

  @override
  String reviewsRatingA11y(String rating, int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count reviews',
      one: '1 review',
    );
    return 'Rated $rating out of 5, $_temp0. Opens the reviews.';
  }

  @override
  String get reviewsNewSummary => 'No reviews yet';

  @override
  String get reviewsEmptyTitle => 'No reviews yet';

  @override
  String get reviewsEmptyBody =>
      'A review shows here once a delivery has been rated and the review is open to both sides.';

  @override
  String get reviewsOffTitle => 'Reviews are not available';

  @override
  String get reviewsOffBody =>
      'Reviews are switched off for now. Please check back later.';

  @override
  String get reviewsGoneTitle => 'This is not available any more';

  @override
  String get reviewsGoneBody =>
      'The person or trip is no longer listed, so its reviews cannot be shown.';

  @override
  String get reviewsFromSender => 'From a sender';

  @override
  String get reviewsFromTraveler => 'From a traveler';

  @override
  String get reviewsCommentRemoved => 'Comment removed by Wassla';

  @override
  String get reviewsMenuLabel => 'Review options';

  @override
  String get reviewsReportAction => 'Report';

  @override
  String get reviewsReportReceived => 'You reported this. We have received it.';

  @override
  String get reviewsReportReviewed => 'You reported this. We have reviewed it.';

  @override
  String get reviewReportSheetTitle => 'Report this review';

  @override
  String get reviewReportSheetIntro =>
      'Tell us what is wrong. We will look at it, and the person is not told that you reported it.';

  @override
  String get reviewReasonOffensive => 'Offensive or abusive';

  @override
  String get reviewReasonPersonalInformation => 'Shares personal information';

  @override
  String get reviewReasonUnrelated => 'Not about the delivery';

  @override
  String get reviewReasonUntrue => 'Not true';

  @override
  String get reviewReasonOther => 'Something else';

  @override
  String get reviewReportNoteLabel => 'Note (optional)';

  @override
  String get reviewReportNoteHint => 'Anything that helps us understand';

  @override
  String get reviewReportSend => 'Send report';

  @override
  String get reviewReportThanks => 'Thanks, we will review it';

  @override
  String get reviewReportOwn => 'You cannot report your own review.';

  @override
  String get reviewReportRemoved => 'Wassla has already removed this review.';

  @override
  String get reviewReportGone => 'This review is not available any more.';

  @override
  String get ratingRemovedByWassla => 'Removed by Wassla, not counted';

  @override
  String get ratingCommentHiddenByWassla =>
      'Wassla hid the comment from others. The score still counts.';

  @override
  String get supportEmailSubject => 'Help with Wassla';

  @override
  String supportEmailSubjectDelivery(String tracking) {
    return 'Help with Wassla delivery $tracking';
  }

  @override
  String supportEmailFailed(String email) {
    return 'No email app opened. Write to $email.';
  }

  @override
  String get journeyPausedStaffBodyNoContact => 'Wassla paused this journey.';

  @override
  String get authVerifyResent =>
      'We sent a new code. Use the code in the newest email.';

  @override
  String get authVerifyResend => 'Send the code again';

  @override
  String get profileVerifyEmail => 'Verify email';

  @override
  String get profileRating => 'Rating';

  @override
  String get accountGateStamp => 'Your Wassla account';

  @override
  String get accountGateEmail => 'Continue with email';

  @override
  String get accountGateHaveAccount => 'I already have an account';

  @override
  String get accountReasonPostRequestTitle =>
      'Create your account\nto send your parcel.';

  @override
  String get accountReasonPostRequestBody =>
      'Travelers see who is sending. Your payment is held, and the traveler is paid 48 hours after delivery.';

  @override
  String get accountReasonPostTripTitle =>
      'Create your account\nto post your trip.';

  @override
  String get accountReasonPostTripBody =>
      'Senders choose travelers they can trust: your account holds your ID check and your reviews.';

  @override
  String get accountReasonCarryTitle =>
      'Create your account\nto carry this parcel.';

  @override
  String get accountReasonCarryBody =>
      'The sender sees who offers to carry it. You are paid into your account 48 hours after delivery.';

  @override
  String get accountReasonAlertTitle =>
      'Create your account\nto get route alerts.';

  @override
  String get accountReasonAlertBody =>
      'We tell you when a trip or a parcel matches this route.';

  @override
  String get accountReasonReportTitle =>
      'Create your account\nto report a review.';

  @override
  String get accountReasonReportBody =>
      'Reports come from members, so we can look into them with you.';

  @override
  String get accountReasonDeliveriesTitle =>
      'Create your account\nto follow deliveries.';

  @override
  String get accountReasonDeliveriesBody =>
      'The parcels you send and the ones you carry all appear in one place.';

  @override
  String get accountReasonChatTitle => 'Create your account\nto chat.';

  @override
  String get accountReasonChatBody =>
      'Chat opens between a sender and a traveler once a delivery is paid for.';

  @override
  String get accountReasonNotificationsTitle =>
      'Create your account\nto get notifications.';

  @override
  String get accountReasonNotificationsBody =>
      'Offers, messages and delivery updates reach you here.';

  @override
  String get accountReasonGenericTitle =>
      'Create your account\nto get started.';

  @override
  String get accountReasonGenericBody =>
      'Send a parcel, or carry one on a trip you are already making.';

  @override
  String get guestSignedOutNotice => 'You were signed out. Sign in again.';

  @override
  String get guestNoticeDismiss => 'Dismiss';

  @override
  String get guestWelcomeTitle =>
      'Send it with someone already making the trip.';

  @override
  String get guestWelcomeBody =>
      'Look around: these are real trips and parcels. You need an account only to post, carry, set alerts or report a review.';

  @override
  String get guestHowItWorks => 'How Wassla works';

  @override
  String get guestAccountAction => 'Sign in or create an account';

  @override
  String get guestDeliveriesTitle => 'Your deliveries appear here';

  @override
  String get guestDeliveriesBody =>
      'Sign in to follow the parcels you send and the ones you carry.';

  @override
  String get guestChatTitle => 'Your conversations appear here';

  @override
  String get guestChatBody =>
      'Chat opens between a sender and a traveler once a delivery is paid for.';

  @override
  String get guestProfileTitle => 'You are looking around as a guest';

  @override
  String get guestProfileBody =>
      'Create an account to send a parcel or to carry one. It takes two minutes.';

  @override
  String get guestSettings => 'Settings';

  @override
  String get socialContinueWithApple => 'Continue with Apple';

  @override
  String get socialContinueWithGoogle => 'Continue with Google';

  @override
  String get socialOr => 'or';

  @override
  String get socialGoogleFailed =>
      'We couldn’t sign you in with Google. Try again.';

  @override
  String get socialAppleFailed =>
      'We couldn’t sign you in with Apple. Try again.';

  @override
  String get socialGoogleUnavailable =>
      'Sign in with Google is not available right now.';

  @override
  String get socialAppleUnavailable =>
      'Sign in with Apple is not available right now.';

  @override
  String get socialAccountDisabled =>
      'This account is disabled. Contact support if you think this is a mistake.';

  @override
  String get accountNameStamp => 'Almost there';

  @override
  String get accountNameTitle => 'What should we call you?';

  @override
  String get accountNameBody =>
      'Your account has no name yet. The people you send or carry with see it on your offers and deliveries.';

  @override
  String get accountNameLabel => 'Your name';

  @override
  String get chatSafetyTitle => 'Safety';

  @override
  String get chatSafetySubtitle => 'To report a message, press and hold it.';

  @override
  String get chatBlockAction => 'Block';

  @override
  String get chatBlockActionDetail =>
      'Stop messages and new deliveries between you.';

  @override
  String get chatUnblockAction => 'Unblock';

  @override
  String get chatUnblockActionDetail => 'You can message each other again.';

  @override
  String get chatBlockConfirmTitle => 'Block this member?';

  @override
  String get chatBlockConfirmBody =>
      'Neither of you will be able to send messages here, and neither of you can start a new delivery with the other. A delivery that is already paid goes on as agreed. You can unblock them from Profile at any time.';

  @override
  String get chatBlockDone => 'You blocked this member.';

  @override
  String get chatUnblockDone => 'You unblocked this member.';

  @override
  String get chatBlockedByMeTitle => 'You blocked this member';

  @override
  String get chatBlockedByMeBody =>
      'Neither of you can send messages here. A delivery that is already paid goes on as agreed.';

  @override
  String get chatBlockedTitle => 'Messaging is off';

  @override
  String get chatBlockedBody =>
      'You can no longer send messages in this conversation. A delivery that is already paid goes on as agreed.';

  @override
  String get chatBlockedPill => 'Blocked';

  @override
  String get chatReportTitle => 'Report this message';

  @override
  String get chatReportSubtitle =>
      'Wassla’s team reviews every report within a day. The sender is not told who reported it.';

  @override
  String get chatReportReasonLabel => 'What’s wrong with it?';

  @override
  String get chatReportReasonSpam => 'Spam or advertising';

  @override
  String get chatReportReasonHarassment => 'Harassment or threats';

  @override
  String get chatReportReasonScam =>
      'A scam, or a request to pay outside Wassla';

  @override
  String get chatReportReasonInappropriate => 'Offensive or inappropriate';

  @override
  String get chatReportReasonOther => 'Something else';

  @override
  String get chatReportChooseReason => 'Choose a reason.';

  @override
  String get chatReportNoteLabel => 'Anything to add? (optional)';

  @override
  String get chatReportAlsoBlock => 'Also block this member';

  @override
  String get chatReportAlsoBlockDetail =>
      'Neither of you can send messages here any more.';

  @override
  String get chatReportSend => 'Send report';

  @override
  String get chatReportSent => 'Thanks. Wassla’s team will review it.';

  @override
  String get chatMessageRemoved => 'Removed by Wassla';

  @override
  String get chatDeletedAccount => 'Deleted account';

  @override
  String get partyBlockedTitle => 'Not possible with this member';

  @override
  String get partyBlockedBody =>
      'One of you blocked the other, so neither of you can start a delivery with the other. You can see the people you block in Profile.';

  @override
  String get blockedPeopleTitle => 'Blocked people';

  @override
  String get blockedPeopleBody =>
      'You and these people can’t message each other or start a new delivery together. Unblocking lets you do both again.';

  @override
  String get blockedPeopleEmptyTitle => 'You haven’t blocked anyone';

  @override
  String get blockedPeopleEmptyBody =>
      'When you block someone from a chat, they appear here.';

  @override
  String blockedPeopleSince(String date) {
    return 'Blocked on $date';
  }

  @override
  String get profileDeleteAccount => 'Delete account';

  @override
  String get deleteAccountTitle => 'Delete your account';

  @override
  String get deleteAccountIntro =>
      'Deleting your account is permanent. You can’t sign in to it again, and we erase your name, email, phone number, sign-in methods, notifications, alerts and public profile.';

  @override
  String get deleteAccountKeptTitle => 'What we keep';

  @override
  String get deleteAccountKeptBody =>
      'The records other people and the law rely on stay, without your contact details: past deliveries, payments, payouts, ID check decisions, reviews, disputes and chat messages.';

  @override
  String get deleteAccountBlockedTitle => 'Finish these first';

  @override
  String get deleteAccountBlockedBody =>
      'Your account can be deleted once nothing is still open.';

  @override
  String get deleteAccountBlockerDeliveries =>
      'A delivery that hasn’t finished';

  @override
  String get deleteAccountBlockerDisputes => 'A dispute that is still open';

  @override
  String get deleteAccountBlockerPayouts =>
      'A payout that hasn’t reached you yet';

  @override
  String get deleteAccountBlockerRefunds =>
      'A refund that hasn’t reached you yet';

  @override
  String get deleteAccountBlockerRequests =>
      'A parcel request that is still open. Cancel it from Deliveries.';

  @override
  String get deleteAccountBlockerJourneys =>
      'A trip that is published or under way. Cancel or finish it from Deliveries.';

  @override
  String get deleteAccountBlockerOther =>
      'Something still open on your account';

  @override
  String get deleteAccountOpenDeliveries => 'Open Deliveries';

  @override
  String get deleteAccountCheckAgain => 'Check again';

  @override
  String get deleteAccountAppleNote =>
      'You use Sign in with Apple. Apple asks you to confirm, then Wassla stops using your Apple ID.';

  @override
  String get deleteAccountAppleElsewhereTitle => 'Delete it from an iPhone';

  @override
  String get deleteAccountAppleElsewhereBody =>
      'Your account uses Sign in with Apple, and only Apple can confirm its deletion. Open Wassla on an iPhone or iPad to delete it, or write to support.';

  @override
  String get deleteAccountPasswordLabel => 'Your password';

  @override
  String get deleteAccountPasswordHelp => 'To confirm it’s you.';

  @override
  String get deleteAccountPasswordMissing => 'Enter your password.';

  @override
  String get deleteAccountPasswordIncorrect => 'That password isn’t right.';

  @override
  String get deleteAccountAction => 'Delete my account';

  @override
  String get deleteAccountConfirmTitle => 'Delete your account?';

  @override
  String get deleteAccountConfirmBody =>
      'This can’t be undone. You will be signed out on every device.';

  @override
  String get deleteAccountConfirm => 'Delete';

  @override
  String get deleteAccountChanged =>
      'Something changed on your account. Check the list again.';

  @override
  String get deleteAccountAppleRefused =>
      'Apple didn’t confirm. Nothing was deleted. Try again.';

  @override
  String get deleteAccountAppleUnavailable =>
      'We couldn’t reach Apple. Nothing was deleted. Try again in a few minutes.';

  @override
  String get deleteAccountStaff =>
      'A staff account is closed by a Super Admin, not from the app.';

  @override
  String get deleteAccountDone => 'Your account is deleted.';
}
