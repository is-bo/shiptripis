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
  String get payoutLegalCountryBody =>
      'Select your legal Stripe account country to consent to payout setup. If your country is not listed, use DZD payouts.';

  @override
  String get appName => 'ShipTrip';

  @override
  String get actionContinue => 'Continue';

  @override
  String get actionCancel => 'Cancel';

  @override
  String get actionSave => 'Save';

  @override
  String get actionRetry => 'Try again';

  @override
  String get actionClose => 'Close';

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
  String get actionRemove => 'Remove';

  @override
  String get actionShare => 'Share';

  @override
  String get actionCopy => 'Copy';

  @override
  String get actionCopied => 'Copied';

  @override
  String get actionRefresh => 'Refresh';

  @override
  String get actionSeeAll => 'See all';

  @override
  String get actionLearnMore => 'Learn more';

  @override
  String get actionGoBack => 'Go back';

  @override
  String get actionNotNow => 'Not now';

  @override
  String get actionUnderstood => 'Got it';

  @override
  String get actionOpen => 'Open';

  @override
  String get actionAdd => 'Add';

  @override
  String get actionChange => 'Change';

  @override
  String get actionSelect => 'Select';

  @override
  String get actionSearch => 'Search';

  @override
  String get actionClear => 'Clear';

  @override
  String get actionApply => 'Apply';

  @override
  String get actionReport => 'Report a problem';

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
  String get roleTraveler => 'Travelling';

  @override
  String get roleSwitchLabel => 'Switch role';

  @override
  String get roleSwitchTitle => 'What are you doing today?';

  @override
  String get roleSenderDescription => 'Send a parcel with a traveller';

  @override
  String get roleTravelerDescription =>
      'Carry parcels on a trip you\'re taking';

  @override
  String get roleSwitchedToSender => 'Switched to sending';

  @override
  String get roleSwitchedToTraveler => 'Switched to travelling';

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
  String get authResetPassword => 'Reset password';

  @override
  String get authResetSent =>
      'If that email has an account, we\'ve sent a reset code.';

  @override
  String get authNoAccount => 'New to ShipTrip?';

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
  String get validationEmailInvalid => 'Enter a valid email address';

  @override
  String get validationPasswordTooShort => 'Use at least 8 characters';

  @override
  String get validationNumberInvalid => 'Enter a number';

  @override
  String get validationMustBePositive => 'Enter a number greater than zero';

  @override
  String validationTooLong(int max) {
    return 'Keep this under $max characters';
  }

  @override
  String get validationSelectOne => 'Choose one';

  @override
  String get validationDateInPast => 'Choose a date in the future';

  @override
  String get validationDeadlineBeforeReady =>
      'The deadline has to be after the parcel is ready';

  @override
  String get stateLoading => 'Loading…';

  @override
  String get stateOfflineTitle => 'You\'re offline';

  @override
  String get stateOfflineBody =>
      'Check your connection. We\'ll load this as soon as you\'re back.';

  @override
  String get stateTimeoutTitle => 'That took too long';

  @override
  String get stateTimeoutBody => 'The server didn\'t answer in time.';

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
      'Update ShipTrip to continue. This part of the app no longer works on this version.';

  @override
  String get staleTitle => 'This has changed';

  @override
  String get staleRefreshAction => 'Refresh';

  @override
  String get staleRequestNotOpen => 'This request isn\'t open any more.';

  @override
  String get staleRequestAlreadyMatched =>
      'This request has already been matched with a traveller.';

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
  String get staleCapacityExceededDetail =>
      'Someone else booked space while you were deciding.';

  @override
  String get staleRewardBelowMinimum => 'The minimum reward has changed.';

  @override
  String staleRewardBelowMinimumDetail(String amount) {
    return 'The minimum is now $amount.';
  }

  @override
  String get staleRouteChanged =>
      'The route details changed. We\'ve refreshed the price.';

  @override
  String get staleKycInvalid =>
      'Your identity check needs attention before you can do this.';

  @override
  String get staleFlightProofInvalid =>
      'Your flight proof needs attention before this journey can match.';

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
  String get moneyTravelerReceives => 'Traveller receives';

  @override
  String get moneyPlatformFee => 'ShipTrip fee';

  @override
  String get moneyMinimumReward => 'Minimum reward';

  @override
  String get moneyRecommendedReward => 'ShipTrip suggests';

  @override
  String get moneyYourReward => 'Your reward';

  @override
  String get moneyYourOffer => 'Your offer';

  @override
  String get moneyTotal => 'Total';

  @override
  String get moneyDepositPaid => 'Deposit already paid';

  @override
  String get moneyRemainingToPay => 'Remaining to pay';

  @override
  String get moneyRefundToYou => 'Refund to you';

  @override
  String get moneyTravelerCompensation => 'Traveller compensation';

  @override
  String get moneyBreakdownTitle => 'How this adds up';

  @override
  String get moneyRewardNotReduced =>
      'The traveller receives this full amount. The ShipTrip fee is added on top, not taken out of it.';

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
  String get moneyFree => 'Free';

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
  String get homeRecentActivity => 'Recent activity';

  @override
  String get homeNothingNeedsYou => 'Nothing needs you right now';

  @override
  String get homeEmptySenderTitle => 'Nothing on the way yet';

  @override
  String get homeEmptySenderBody =>
      'Post what you want to send and travellers heading that way will see it.';

  @override
  String get homeEmptyTravelerTitle => 'No journeys yet';

  @override
  String get homeEmptyTravelerBody =>
      'Add the trip you\'re taking and we\'ll show you parcels along your route.';

  @override
  String get deliveriesTitle => 'Deliveries';

  @override
  String get deliveriesFilterActive => 'Active';

  @override
  String get deliveriesFilterAwaitingYou => 'Needs you';

  @override
  String get deliveriesFilterHistory => 'History';

  @override
  String get deliveriesSenderSection => 'Sending';

  @override
  String get deliveriesTravelerSection => 'Carrying';

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
  String get requestStatusOpen => 'Finding a traveller';

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
  String get dealStatusPaymentProcessing => 'Confirming payment';

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
  String get requestPickupHint => 'Where the traveller collects the parcel';

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
      'Describe it accurately. This is what the traveller agrees to carry.';

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
  String get requestPhotosHelp =>
      'Photos protect both of you if there\'s a dispute later.';

  @override
  String get requestAddPhoto => 'Add photo';

  @override
  String get requestHandlingNotes => 'Handling notes';

  @override
  String get requestHandlingNotesHint => 'Anything the traveller should know';

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
      'Pay a small deposit to publish this request to travellers.';

  @override
  String get depositAmount => 'Deposit';

  @override
  String get depositCreditedNote =>
      'It\'s credited towards your final payment when a traveller accepts.';

  @override
  String get depositRefundNote =>
      'If nobody takes it, or you cancel before accepting an offer, you get it back in full.';

  @override
  String get depositGuidanceTitle => 'Deposit guidance';

  @override
  String get depositSuggestedTotal => 'ShipTrip suggested total';

  @override
  String get depositRecommended => 'Recommended deposit';

  @override
  String get depositMinimumAllowed => 'Minimum deposit';

  @override
  String get depositGuidanceNote =>
      'ShipTrip calculates the deposit from the suggested total and applies the current minimum and maximum. This is credit toward the final payment, not an extra fee.';

  @override
  String get depositPayAction => 'Pay deposit and publish';

  @override
  String get depositPending => 'Confirming your deposit…';

  @override
  String get depositPendingBody =>
      'We\'re waiting for your payment provider to confirm. This usually takes a few seconds.';

  @override
  String get depositPaidTitle => 'Published';

  @override
  String get depositPaidBody => 'Travellers heading your way can see this now.';

  @override
  String get journeyTitle => 'Journey';

  @override
  String get journeyCreateTitle => 'Add a journey';

  @override
  String get journeyOverallRoute => 'Where are you going?';

  @override
  String get journeyFrom => 'From';

  @override
  String get journeyTo => 'To';

  @override
  String get journeyLegs => 'Legs';

  @override
  String get journeyAddLeg => 'Add a leg';

  @override
  String journeyLegPosition(int position) {
    return 'Leg $position';
  }

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
  String get journeyCapacityHelp =>
      'Set this per leg. You can carry different amounts on different parts of the trip.';

  @override
  String get journeyFlightNumber => 'Flight number';

  @override
  String get journeyFlightNumberHint => 'e.g. AH1006';

  @override
  String get journeyFlightAirportsRequired =>
      'Flight legs must start and end at airports.';

  @override
  String get journeyPublish => 'Publish journey';

  @override
  String get journeyCancel => 'Cancel journey';

  @override
  String get journeySuggestLegTitle => 'Add the road leg?';

  @override
  String journeySuggestLegBody(String arrival, String destination) {
    return 'Your flight lands in $arrival, but you\'re going to $destination. Add the drive so parcels can be matched all the way.';
  }

  @override
  String get journeySuggestLegAccept => 'Add drive leg';

  @override
  String get journeySuggestLegDecline => 'No, I stop there';

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
  String get journeyModeLabel => 'How you\'re travelling';

  @override
  String get journeyLegStartsAt => 'Starts at';

  @override
  String get journeyLegEndsAt => 'Ends at';

  @override
  String get journeyLegEndPlaceholder => 'Choose where this leg ends';

  @override
  String get journeyChooseDateTime => 'Choose date and time';

  @override
  String get journeyArriveOptionalHelp =>
      'Optional. It lets us check the next leg leaves in time.';

  @override
  String get journeyRemoveLeg => 'Remove this leg';

  @override
  String get journeyAddLegDestinationTitle => 'Where does this leg end?';

  @override
  String get journeyMaxLegsReached => 'A journey can hold at most 20 legs.';

  @override
  String get journeyCapacityInvalid =>
      'Enter at least 0.01 kg, to two decimal places.';

  @override
  String get journeyLegDepartRequired => 'Say when this leg departs.';

  @override
  String get journeyLegDepartNotAfterPrevious =>
      'This leg has to depart after the leg before it.';

  @override
  String get journeyLegDepartBeforePreviousArrival =>
      'This leg departs before the previous one lands.';

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
  String get journeyLegsNeedProofTitle => 'Flights that need proof';

  @override
  String get journeyPublishBlockedProof =>
      'Every flight leg needs approved proof before this can go live.';

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
  String get journeyErrorLegsDisconnected =>
      'The legs don\'t join up into one route.';

  @override
  String get journeyErrorLegTimeOrder => 'The legs aren\'t in time order.';

  @override
  String get journeyErrorNotOwned => 'This journey belongs to someone else.';

  @override
  String get journeyRebuildHint =>
      'Cancel this journey and create it again with the corrected details.';

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
  String get journeyMatchesLoadFailed =>
      'We couldn\'t load parcels for this journey.';

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
      'Changing a flight\'s airports, number or times means its proof no longer shows that flight, so we\'ll check it again.';

  @override
  String get journeyEditProofWarningTitle =>
      'Your flight proof will be checked again';

  @override
  String get journeyEditProofWarningBody =>
      'You\'ve changed a flight that already has proof. That proof no longer shows this flight, so it goes back for review and the journey can\'t go live until it\'s approved again.';

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
  String get proofTitle => 'Flight proof';

  @override
  String get proofExplainer =>
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
  String get proofReplace => 'Upload a new one';

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
      'Senders are handing a stranger something that matters to them. Verifying travellers is what makes that reasonable.';

  @override
  String get kycStatusNotStarted => 'Not started';

  @override
  String get kycStatusInProgress => 'In progress';

  @override
  String get kycStatusPending => 'Being reviewed';

  @override
  String get kycStatusApproved => 'Verified';

  @override
  String get kycStatusRejected => 'Not approved';

  @override
  String get kycStatusActionRequired => 'Needs your attention';

  @override
  String get kycStartAction => 'Start identity check';

  @override
  String get kycResumeAction => 'Finish identity check';

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
  String get discoveryTravelersTitle => 'Travellers for this parcel';

  @override
  String get discoveryRequestsTitle => 'Parcels along your route';

  @override
  String get discoveryEmptyTravelersTitle => 'No travellers yet';

  @override
  String get discoveryEmptyTravelersBody =>
      'Nobody is going your way right now. We\'ll notify you when someone is.';

  @override
  String get discoveryEmptyRequestsTitle => 'No parcels yet';

  @override
  String get discoveryEmptyRequestsBody =>
      'Nothing matches your journey right now. We\'ll notify you when something does.';

  @override
  String discoveryCoveredLegs(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count legs',
      one: '1 leg',
    );
    return 'Covers $_temp0';
  }

  @override
  String get discoveryDetourSmall => 'Barely a detour';

  @override
  String get discoveryDetourModerate => 'Small detour';

  @override
  String get discoveryDetourLarge => 'Noticeable detour';

  @override
  String get discoveryVerifiedTraveler => 'Verified traveller';

  @override
  String get discoveryBoosted => 'Boosted';

  @override
  String get discoveryBoostedExplainer =>
      'The sender paid to be seen by more travellers. It doesn\'t change whether you\'re a match.';

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
      'You choose what the traveller earns. They can accept, decline, or come back with a different amount.';

  @override
  String get offerRewardLabel => 'Traveller\'s reward';

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
  String get offerAwaitingTraveler => 'Waiting for the traveller';

  @override
  String get offerAwaitingSender => 'Waiting for the sender';

  @override
  String get offerAwaitingYou => 'Your move';

  @override
  String offerYouProposed(String amount) {
    return 'You offered $amount';
  }

  @override
  String offerTheyProposed(String amount) {
    return 'They offered $amount';
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
  String offerAcceptConfirmTitle(String amount) {
    return 'Accept $amount?';
  }

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
  String get offerTravelerCounterTitle => 'Traveller\'s counter-offer';

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
    return 'Traveller asks $amount';
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
  String get paymentConfirmingTitle => 'Confirming your payment';

  @override
  String get paymentConfirmingBody =>
      'Your bank has told us, and we\'re confirming it with ShipTrip. Don\'t pay again — this usually takes a few seconds.';

  @override
  String get paymentSucceededTitle => 'Paid';

  @override
  String get paymentSucceededBody =>
      'Your money is held until the parcel is delivered.';

  @override
  String get paymentFailedTitle => 'Payment didn\'t go through';

  @override
  String get paymentFailedBody =>
      'Nothing was charged. You can try again or use a different method.';

  @override
  String get paymentExpiredTitle => 'Checkout expired';

  @override
  String get paymentExpiredBody =>
      'That checkout link timed out. Start again when you\'re ready.';

  @override
  String get paymentStatusRequired => 'Payment needed';

  @override
  String get paymentStatusStarted => 'Checkout open';

  @override
  String get paymentStatusProcessing => 'Processing';

  @override
  String get paymentStatusPaid => 'Paid';

  @override
  String get paymentStatusFailed => 'Failed';

  @override
  String get paymentStatusRefundPending => 'Refund on the way';

  @override
  String get paymentStatusPartiallyRefunded => 'Partly refunded';

  @override
  String get paymentStatusRefunded => 'Refunded';

  @override
  String get paymentReturnedTitle => 'Welcome back';

  @override
  String get paymentRedirectNotProof =>
      'We confirm every payment with the provider before marking it paid.';

  @override
  String get guestPayTitle => 'Have someone else pay';

  @override
  String get guestPayExplainer =>
      'Share a link and anyone can pay this amount for you. They don\'t need a ShipTrip account.';

  @override
  String get guestPayCreateLink => 'Create payment link';

  @override
  String get guestPayLinkReady => 'Link ready';

  @override
  String get guestPayCopyLink => 'Copy link';

  @override
  String get guestPayShareLink => 'Share link';

  @override
  String get guestPayRevoke => 'Cancel this link';

  @override
  String get guestPayRevoked => 'Link cancelled';

  @override
  String guestPayExpiresAt(String when) {
    return 'Expires $when';
  }

  @override
  String get guestPayWarning =>
      'Anyone with this link can pay this amount. They get nothing else — no access to your delivery, your chat, or your details.';

  @override
  String get guestPayPayerEmail => 'Your email for the receipt';

  @override
  String get guestPayPayerEmailHelp =>
      'We use it for your payment receipt, failure updates and any refund communication. It does not create a ShipTrip account.';

  @override
  String get guestPayAmountDue => 'Amount due';

  @override
  String get guestPayForDelivery => 'Payment for a ShipTrip delivery';

  @override
  String get guestPayThanksTitle => 'Thank you';

  @override
  String get guestPayThanksBody =>
      'The payment is confirmed. Nothing else is needed from you.';

  @override
  String get guestPayInvalidTitle => 'This link isn\'t valid';

  @override
  String get guestPayInvalidBody =>
      'It may have expired, been cancelled, or already been paid.';

  @override
  String get recipientTitle => 'Who\'s receiving this?';

  @override
  String get recipientExplainer =>
      'We email the delivery code to the recipient. The traveller can only complete the delivery if the recipient gives them that code.';

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
  String get recipientRequiredTitle => 'Recipient needed';

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
      'Give this code to the traveller only when you\'re physically handing over the parcel. It\'s how they confirm they have it.';

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
      'The traveller will ask for your pickup code when you meet.';

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
      'The recipient gives this to the traveller at the door. Only share it with the recipient.';

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
  String protectionEndsIn(String countdown) {
    return 'Ends in $countdown';
  }

  @override
  String get protectionEnded => 'Protection window closed';

  @override
  String get protectionExplainerTitle => 'What this means';

  @override
  String get protectionExplainerBody =>
      'Funds are held pending delivery confirmation and the 48-hour protection period. ShipTrip releases them only after that period ends and no dispute is open.';

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
  String get payoutPendingTitle => 'Payout pending';

  @override
  String get payoutEmptyTitle => 'No payouts yet';

  @override
  String get payoutEmptyBody =>
      'Complete a delivery and your earnings appear here.';

  @override
  String get disputeOpenTitle => 'Open a dispute';

  @override
  String get disputeOpenExplainer =>
      'Tell us what went wrong. Opening a dispute puts the traveller\'s payout on hold while we look into it.';

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
  String get disputeUploadFailed => 'Upload failed';

  @override
  String get disputeUploadRetry => 'Retry upload';

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
  String get disputeResolutionTravelerPaid => 'Paid to the traveller';

  @override
  String get disputeResolutionPartial => 'Split between both sides';

  @override
  String get disputeWindowClosedTitle => 'The dispute window has closed';

  @override
  String get disputeWindowClosedBody =>
      'Disputes can be opened for 48 hours after delivery. Contact support if you still need help.';

  @override
  String get disputeEmptyTitle => 'No disputes';

  @override
  String get disputeEmptyBody => 'Nothing is under dispute.';

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
      'Because it\'s close to pickup, the traveller is compensated for holding the space.';

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
  String get ratingSenderPrompt => 'Rate the traveller';

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
      'A boost puts your request higher in the list for travellers who already match it.';

  @override
  String get boostDoesNotGuarantee =>
      'It doesn\'t change who you match with, and it doesn\'t guarantee a delivery.';

  @override
  String get boostChoosePackage => 'Choose a boost';

  @override
  String get boostAmountLabel => 'Boost amount';

  @override
  String boostAmountHelper(String amount) {
    return 'Minimum $amount. You can choose any higher amount.';
  }

  @override
  String get boostPreviewTitle => 'Review before paying';

  @override
  String get boostSenderPays => 'You pay';

  @override
  String get boostTravelerGets => 'Traveler gets if delivered';

  @override
  String get boostPlatformKeeps => 'ShipTrip keeps';

  @override
  String get boostEarningsCondition =>
      'The Traveler bonus becomes part of protected deal earnings. If no delivery reaches an earning outcome, the boost payment is refunded.';

  @override
  String get boostReviewAction => 'Review boost';

  @override
  String get boostConfirmAction => 'Continue to payment';

  @override
  String get boostAmountBelowMinimum =>
      'Enter at least the minimum boost amount.';

  @override
  String get boostPreviewStale =>
      'The boost split changed. Review the updated amounts before continuing.';

  @override
  String boostDuration(int hours) {
    String _temp0 = intl.Intl.pluralLogic(
      hours,
      locale: localeName,
      other: '$hours hours',
      one: '1 hour',
    );
    return '$_temp0';
  }

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
  String get boostActive => 'Boost active';

  @override
  String boostActiveUntil(String when) {
    return 'Active until $when';
  }

  @override
  String get boostPendingPayment => 'Waiting for payment';

  @override
  String get boostExpired => 'Boost ended';

  @override
  String boostPurchase(String amount) {
    return 'Boost for $amount';
  }

  @override
  String get boostNotEligible => 'This request can\'t be boosted right now.';

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
  String get chatSendFailed => 'Not sent';

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
  String notificationsUnreadCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count unread',
      one: '1 unread',
      zero: 'No unread',
    );
    return '$_temp0';
  }

  @override
  String get profileTitle => 'Profile';

  @override
  String get profileAccount => 'Account';

  @override
  String get profilePassportStamp => 'SHIPTRIP · MEMBER';

  @override
  String get profileCompletedDeliveries => 'Completed';

  @override
  String get profileRecentRating => 'Recent rating';

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
      'What you read inside ShipTrip. Stored on this phone.';

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
    return 'With ShipTrip since $date';
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
  String get locationSelectCountry => 'Choose a country first';

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
  String get locationTypeLocality => 'Locality';

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
  String get locationPrivacyAfterFunding =>
      'Full address shared with the traveller.';

  @override
  String get locationHiddenUntilFunded =>
      'Exact address available after payment';

  @override
  String get locationSearchEmptyTitle => 'No results';

  @override
  String get locationSearchEmptyBody =>
      'Try a different spelling, or pick the point on the map.';

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
  String get locationCountryStep => 'Country';

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
    return 'Travellers are matched on $place. A preferred point only says where you would rather meet inside it.';
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
  String get locationDropPinHelp =>
      'Move the map until the crosshair sits where you mean, then confirm.';

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
  String get locationChoosePreferredPoint => 'Choose on map';

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
  String get timelineWaitingOnYou => 'Waiting on you';

  @override
  String get timelineWaitingOnThem => 'Waiting on them';

  @override
  String get timelineDone => 'Done';

  @override
  String get timelineUpcoming => 'Next';

  @override
  String get a11yStatusPrefix => 'Status';

  @override
  String get a11yMoneyAmount => 'Amount';

  @override
  String get a11yRequiredField => 'Required';

  @override
  String get a11yCloseSheet => 'Close';

  @override
  String get a11yBack => 'Go back';

  @override
  String get a11yLoadingContent => 'Loading content';

  @override
  String get a11yImageOfParcel => 'Photo of the parcel';

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
  String unitDistanceKm(String value) {
    return '$value km';
  }

  @override
  String get weightChargeableVolumetric => 'Priced on size, not weight';

  @override
  String get weightChargeableActual => 'Priced on weight';

  @override
  String get homeVerifyIdentityTitle => 'Verify your identity';

  @override
  String get homeVerifyIdentityBody =>
      'Travellers must be verified before a journey can go live.';

  @override
  String get homeAttentionOfferAwaiting =>
      'An offer is waiting for your answer';

  @override
  String get homeAttentionFunding => 'Pay to confirm this delivery';

  @override
  String get homeAttentionRecipient => 'Add who receives the parcel';

  @override
  String get homeAttentionRevealPickup =>
      'Show the pickup code to your traveller';

  @override
  String get homeAttentionSubmitPickup => 'Enter the pickup code';

  @override
  String get homeAttentionRevealDelivery => 'The delivery code is ready';

  @override
  String get homeAttentionSubmitDelivery => 'Enter the delivery code';

  @override
  String get homeAttentionRating => 'Rate this delivery';

  @override
  String get homeOpenAction => 'Open';

  @override
  String get deliveriesTabAll => 'All';

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
      other: '$count flights need proof',
      one: '1 flight needs proof',
    );
    return '$_temp0';
  }

  @override
  String requestOffersCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count offers',
      one: '1 offer',
      zero: 'No offers yet',
    );
    return '$_temp0';
  }

  @override
  String get onboardingSendTitle => 'Send something home';

  @override
  String get onboardingSendBody =>
      'Post what you want delivered. Travellers already heading that way can carry it, and you agree the price between you.';

  @override
  String get onboardingCarryTitle => 'Earn on a trip you\'re already taking';

  @override
  String get onboardingCarryBody =>
      'Add your journey, and we\'ll show you parcels that fit your route and your spare kilos.';

  @override
  String get onboardingSafeTitle => 'The money waits until it arrives';

  @override
  String get onboardingSafeBody =>
      'We hold the payment from the moment you book until 48 hours after delivery is confirmed.';

  @override
  String get onboardingGetStarted => 'Create an account';

  @override
  String get onboardingHaveAccount => 'I already have an account';

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
  String get authWilaya => 'Wilaya';

  @override
  String get authWilayaHelp =>
      'Your home wilaya in Algeria. Choose the one you\'re connected to if you live in Europe.';

  @override
  String get authWilayaSheetTitle => 'Choose a wilaya';

  @override
  String get authResetCodeSent =>
      'If that address has an account, we\'ve sent it a six-digit code.';

  @override
  String get authResetCodeLabel => 'Six-digit code';

  @override
  String get authNewPassword => 'New password';

  @override
  String get authResetDone => 'Password changed. You can sign in now.';

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
      'Nothing arrived? Check your spam folder. If it still isn\'t there, contact support and we\'ll sort it out.';

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
  String get payoutEligibleIn => 'Released in';

  @override
  String get notificationOffer => 'Offer update';

  @override
  String get notificationMatch => 'New match';

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
  String get chatLoadEarlier => 'Load earlier messages';

  @override
  String get chatToday => 'Today';

  @override
  String get chatYesterday => 'Yesterday';

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
  String get paymentStillConfirmingTitle => 'Still confirming';

  @override
  String get paymentStillConfirmingBody =>
      'This is taking longer than usual. Nothing is lost, and you have not been charged twice.';

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
      'The stretch of time a traveller could collect it. Give a window, not a minute.';

  @override
  String get requestDeadlineHelp =>
      'The latest it can arrive. This has to be after your ready window closes.';

  @override
  String get requestWeightHelp => 'Between 0.01 and 100 kg.';

  @override
  String get requestDimensionsHelp =>
      'Optional. Enter all three, or leave all three empty.';

  @override
  String get requestDimensionsPartial =>
      'Enter all three measurements, or clear them all.';

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
      'A starting point, not a price. Travellers can accept it or come back with a different amount.';

  @override
  String get requestRewardIsIntent =>
      'This is what you proposed. The price is settled when a traveller accepts an offer.';

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
  String get requestMatchesSection => 'Travellers you\'ve approached';

  @override
  String get requestNoMatchesYet => 'You haven\'t proposed to anyone yet.';

  @override
  String get requestAwaitingDepositNotice =>
      'Travellers can\'t see this yet. Pay the deposit to publish it.';

  @override
  String get requestFindTravelers => 'Find travellers';

  @override
  String get requestPayDepositAction => 'Pay deposit';

  @override
  String get requestCancelAction => 'Cancel request';

  @override
  String get requestCancelConfirmTitle => 'Cancel this request?';

  @override
  String get requestCancelConfirmBody =>
      'It stops being visible to travellers. Any deposit you paid comes back to you.';

  @override
  String get requestCancelled => 'Request cancelled';

  @override
  String get requestCancelNotCancellableBody =>
      'A traveller is already matched with this request, so it can\'t be cancelled here.';

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
      'You addressed this request to one traveller. Nobody else can see it.';

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
  String get discoveryMatchedDistance => 'Distance carried';

  @override
  String get discoveryDetourLabel => 'Detour for the traveller';

  @override
  String get discoveryFirstDeparture => 'Leaves';

  @override
  String get discoveryProposeBlocked =>
      'We can\'t work out which part of this journey fits your parcel. Refresh and try again.';

  @override
  String get discoveryVolumetricExplainer =>
      'This parcel is bulkier than it is heavy, so its size sets the price.';

  @override
  String get discoveryBreakdownNote =>
      'This is how the suggested amount adds up. Offer something different and the total moves with it.';

  @override
  String get discoveryProposalSent => 'Offer sent';

  @override
  String get discoveryLegRangeMoved =>
      'This traveller\'s route changed while you were looking. We\'ve refreshed it.';

  @override
  String discoveryIncompatibleCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'This traveller no longer fits your parcel, for $count reasons.',
      one: 'This traveller no longer fits your parcel, for 1 reason.',
    );
    return '$_temp0';
  }

  @override
  String get boostRankingLabel => 'Visibility';

  @override
  String get boostRankingModest => 'Higher in the list';

  @override
  String get boostRankingStrong => 'Much higher in the list';

  @override
  String get boostRankingTop => 'Top of the list';

  @override
  String get boostDurationLabel => 'Runs for';

  @override
  String get boostPriceLabel => 'Price';

  @override
  String get boostCompatibilityNote =>
      'Only travellers who already match your parcel ever see it. A boost doesn\'t change who those travellers are.';

  @override
  String get boostActivatesOnPayment =>
      'The boost starts once your payment is confirmed, not when you leave the checkout page.';

  @override
  String get boostBuyAction => 'Buy this boost';

  @override
  String get boostPayAction => 'Pay for this boost';

  @override
  String get boostPurchasesSection => 'Your boosts';

  @override
  String get boostNoPackagesTitle => 'No boosts available';

  @override
  String get boostNoPackagesBody =>
      'There are no boost packages on offer at the moment.';

  @override
  String get boostDisabledTitle => 'Boosts are switched off';

  @override
  String get boostDisabledBody =>
      'Nobody can buy a boost right now. Your request is unaffected.';

  @override
  String get boostLimitReachedTitle => 'Boost limit reached';

  @override
  String boostLimitReachedBody(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'You can have $count boosts running on a request at a time.',
      one: 'You can have 1 boost running on a request at a time.',
    );
    return '$_temp0';
  }

  @override
  String get boostRequestExpiredBody =>
      'This request has expired, so it can no longer be boosted.';

  @override
  String get boostPackageUnknownBody =>
      'That boost is no longer offered. Choose another one.';

  @override
  String get boostStatusCancelled => 'Cancelled';

  @override
  String get boostStatusUnusable =>
      'Refunded — the request stopped being boostable';

  @override
  String get boostStatusRefunded => 'Refunded';

  @override
  String get moneyBaseReward => 'Base delivery reward';

  @override
  String get moneyBoostBonus => 'Boost bonus';

  @override
  String get moneyPlatformBoostRevenue => 'ShipTrip boost share';

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
  String get dealParcelSection => 'The parcel';

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
  String get dealLocationsHiddenUntilFunded =>
      'Exact addresses appear once the delivery is paid for.';

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
      'The delivery code is now available to your recipient. Only they can pass it to the traveller.';

  @override
  String get pickupConfirmedTravelerNext =>
      'Carry the parcel to the recipient. They read you the delivery code at the door — you are never shown it yourself.';

  @override
  String get deliverySafetyWaitingTitle => 'Waiting for the safety period';

  @override
  String get deliverySafetyWaitingSenderBody =>
      'Pickup is confirmed. Delivery confirmation becomes available after the safety period; then ShipTrip emails the delivery code to your recipient.';

  @override
  String get deliverySafetyWaitingTravelerBody =>
      'Pickup is confirmed. Continue to the recipient. After the safety period, ask them for the delivery code — ShipTrip never shows it to you.';

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
      'The recipient receives this code by email. They read it to the traveller at the door, and that is what confirms the delivery.';

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
  String get disputeOpenAction => 'Open a dispute';

  @override
  String get disputeOpened => 'Dispute opened';

  @override
  String get disputeExistingOpenedBody =>
      'You already have a dispute open on this delivery. We\'ve taken you to it.';

  @override
  String get disputeFreezesPayoutTitle =>
      'The traveller\'s payout goes on hold';

  @override
  String get disputeFreezesPayoutBody =>
      'Nothing is paid out while we look into this. Both sides can add evidence.';

  @override
  String get disputeNotAvailableTitle => 'You can\'t open a dispute yet';

  @override
  String get disputeNotAvailableBody =>
      'A dispute can be opened once the parcel has been picked up. Before that, cancel the delivery instead.';

  @override
  String get disputeAlreadyResolvedTitle => 'This has already been decided';

  @override
  String get disputeAlreadyResolvedBody =>
      'There\'s already a resolved dispute on this delivery.';

  @override
  String get disputeDetailTitle => 'Dispute';

  @override
  String get disputeReferenceLabel => 'Reference';

  @override
  String get disputeCategoryTitle => 'Category';

  @override
  String get disputeReasonLabel => 'What was reported';

  @override
  String get disputeOpenedByLabel => 'Opened by';

  @override
  String get disputeOpenedBySender => 'The sender';

  @override
  String get disputeOpenedByTraveler => 'The traveller';

  @override
  String get disputeOpenedAtLabel => 'Opened';

  @override
  String get disputeResolvedAtLabel => 'Decided';

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
      'These amounts are ShipTrip\'s decision. Nothing here is worked out on your phone.';

  @override
  String get disputeCollectedTotal => 'Collected from the sender';

  @override
  String get disputeResolutionNoteLabel => 'Note from ShipTrip';

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
  String unitFileSizeMb(String value) {
    return '$value MB';
  }

  @override
  String get paymentPollingHint =>
      'This can take a moment. You can leave this screen — we\'ll keep checking.';

  @override
  String get paymentOpenProvider => 'Continue payment';

  @override
  String get guestPayPoweredBy => 'Paid securely through ShipTrip';

  @override
  String get onboardingEyebrow => 'Welcome';

  @override
  String get onboardingHeadline =>
      'Send anything,\nthe travellers\ndo the rest.';

  @override
  String get onboardingBody =>
      'A peer-to-peer corridor between Algeria and France. Travellers carry, senders save, and the money is held until it arrives.';

  @override
  String get onboardingStamp => 'EST. 2026 · ALG ↔ FR';

  @override
  String get onboardingTrust => 'ID verified · Payment held · Priced in euros';

  @override
  String get onboardingRouteFrom => 'ALGIERS';

  @override
  String get onboardingRouteTo => 'PARIS';

  @override
  String get onboardingRouteMeta => 'DIRECT · 2H 25M';

  @override
  String get benefitsSkip => 'Skip';

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
      'Travellers carry your parcel as part of their luggage. You pay a sliver of express shipping.';

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
  String get benefitsHandoverCaption => 'HANDOVER · 6 CHARACTERS';

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
  String get onboardingGetStartedShort => 'Get started';

  @override
  String get requestItemPhoto => 'Photo of the item';

  @override
  String get requestItemPhotoHelp =>
      'Add a clear photo of what you\'re sending. Travellers decide from this.';

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
  String get requestItemPhotoExpired =>
      'That photo is no longer available. Add it again.';

  @override
  String get requestItemPhotoPrivacy =>
      'Only travellers who can see this request can see the photo.';

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
  String get formStepLockedUntilValid => 'Finish this step first.';

  @override
  String get pushPermissionHeading => 'On this phone';

  @override
  String get pushPermissionBody =>
      'Get timely updates about offers, payments, delivery, messages and verification. ShipTrip asks only when you choose Enable.';

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
      'Push could not start on this phone. Your in-app notifications still work; reopen ShipTrip to try again.';

  @override
  String get pushEnableAction => 'Enable notifications';

  @override
  String get pushOpenSettingsAction => 'Open notification settings';

  @override
  String get pushRegistrationPending =>
      'System notification permission is on. ShipTrip is finishing notification setup for this phone.';

  @override
  String get pushRegistrationFailed =>
      'System notification permission is on, but ShipTrip could not finish registering this phone. Check your connection and try again.';

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
  String get notificationJourney => 'Journey update';

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
  String get profilePayoutHistory => 'Payout history';

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
  String get payoutPreferenceRequired =>
      'Please select your payout preference.';

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
  String payoutDzdSubmittedAt(String date) {
    return 'Submitted on $date';
  }

  @override
  String get payoutDzdFutureScopeNote =>
      'The new method applies to future eligible payouts. Already-funded payouts keep their historical payout destination.';

  @override
  String get dzdFormTitle => 'Set up DZD payouts';

  @override
  String get dzdFormUpdateTitle => 'Update payout information';

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
  String get dzdChequeRemovePhoto => 'Remove photo';

  @override
  String get dzdSubmitAction => 'Submit payout information';

  @override
  String get dzdUpdateAction => 'Update payout information';

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
  String get deliveryPayoutSectionTitle => 'Payout status';

  @override
  String get deliveryPayoutProtectionExplainer =>
      '48-hour protection period is active. Funds are held until the period ends.';

  @override
  String get deliveryPayoutReadyExplainer =>
      'Delivery is complete and payout is now eligible.';

  @override
  String get deliveryPayoutProcessingExplainer =>
      'Payout processing has started.';

  @override
  String get deliveryPayoutSentExplainer =>
      'Payout has been sent and is in transit.';

  @override
  String get deliveryPayoutPaidExplainer =>
      'Payout has been settled to your account.';

  @override
  String get deliveryPayoutReturnedExplainer =>
      'The bank returned this payout. Please check your payout method.';

  @override
  String get deliveryPayoutNeedsAttentionExplainer =>
      'This payout requires attention before it can be settled.';

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
  String get payoutStatusReturned => 'Payout returned';

  @override
  String get payoutStatusNeedsAttention => 'Needs attention';

  @override
  String get payoutProfileReady => 'Payout method ready';

  @override
  String get payoutProfileNeedsAttention => 'Method needs attention';

  @override
  String get payoutReasonScheduledArrivalPending => 'Scheduled arrival pending';

  @override
  String get deliveryPayoutScheduledArrivalPendingExplainer =>
      'The 48-hour delivery protection has ended, but payout remains held until the scheduled arrival date agreed when funded.';

  @override
  String get earlyArrivalAction => 'I arrived early';

  @override
  String get earlyArrivalConfirmSheetTitle => 'Report early arrival';

  @override
  String get earlyArrivalConfirmSheetBody =>
      'This notifies the sender that you arrived before the scheduled arrival. It does not confirm delivery of the parcel. The sender must confirm your arrival, and payout timing still follows ShipTrip protection rules.';

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
  String get earlyArrivalReportedTimeLabel => 'Reported arrival';

  @override
  String get earlyArrivalEarlyByLabel => 'Early by';

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
  String get routeDepartureLabel => 'Departure';

  @override
  String get routeArrivalLabel => 'Arrival';

  @override
  String get routeCarryingLegsOnly => 'Carrying route for this delivery';

  @override
  String get notificationArrivalReported => 'Traveler arrived early';

  @override
  String get notificationArrivalReportedBody =>
      'Open ShipTrip to confirm the early arrival.';

  @override
  String get notificationArrivalConfirmed => 'Early arrival confirmed';

  @override
  String get notificationArrivalConfirmedBody =>
      'The sender confirmed your arrival. Delivery is still to come.';

  @override
  String get notificationArrivalDeclined => 'Early arrival not confirmed';

  @override
  String get notificationArrivalDeclinedBody =>
      'Open ShipTrip to review the delivery.';

  @override
  String get routeBasisSnapshot => 'Frozen at booking';

  @override
  String get routeBasisLive => 'Live journey';
}
