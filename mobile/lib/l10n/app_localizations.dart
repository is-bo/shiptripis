import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_ar.dart';
import 'app_localizations_en.dart';
import 'app_localizations_fr.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of L
/// returned by `L.of(context)`.
///
/// Applications need to include `L.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: L.localizationsDelegates,
///   supportedLocales: L.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the L.supportedLocales
/// property.
abstract class L {
  L(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static L of(BuildContext context) {
    return Localizations.of<L>(context, L)!;
  }

  static const LocalizationsDelegate<L> delegate = _LDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('ar'),
    Locale('en'),
    Locale('fr'),
  ];

  /// No description provided for @appName.
  ///
  /// In en, this message translates to:
  /// **'ShipTrip'**
  String get appName;

  /// No description provided for @actionContinue.
  ///
  /// In en, this message translates to:
  /// **'Continue'**
  String get actionContinue;

  /// No description provided for @actionCancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get actionCancel;

  /// No description provided for @actionSave.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get actionSave;

  /// No description provided for @actionRetry.
  ///
  /// In en, this message translates to:
  /// **'Try again'**
  String get actionRetry;

  /// No description provided for @actionClose.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get actionClose;

  /// No description provided for @actionDone.
  ///
  /// In en, this message translates to:
  /// **'Done'**
  String get actionDone;

  /// No description provided for @actionBack.
  ///
  /// In en, this message translates to:
  /// **'Back'**
  String get actionBack;

  /// No description provided for @actionNext.
  ///
  /// In en, this message translates to:
  /// **'Next'**
  String get actionNext;

  /// No description provided for @actionConfirm.
  ///
  /// In en, this message translates to:
  /// **'Confirm'**
  String get actionConfirm;

  /// No description provided for @actionEdit.
  ///
  /// In en, this message translates to:
  /// **'Edit'**
  String get actionEdit;

  /// No description provided for @actionRemove.
  ///
  /// In en, this message translates to:
  /// **'Remove'**
  String get actionRemove;

  /// No description provided for @actionShare.
  ///
  /// In en, this message translates to:
  /// **'Share'**
  String get actionShare;

  /// No description provided for @actionCopy.
  ///
  /// In en, this message translates to:
  /// **'Copy'**
  String get actionCopy;

  /// No description provided for @actionCopied.
  ///
  /// In en, this message translates to:
  /// **'Copied'**
  String get actionCopied;

  /// No description provided for @actionRefresh.
  ///
  /// In en, this message translates to:
  /// **'Refresh'**
  String get actionRefresh;

  /// No description provided for @actionSeeAll.
  ///
  /// In en, this message translates to:
  /// **'See all'**
  String get actionSeeAll;

  /// No description provided for @actionLearnMore.
  ///
  /// In en, this message translates to:
  /// **'Learn more'**
  String get actionLearnMore;

  /// No description provided for @actionGoBack.
  ///
  /// In en, this message translates to:
  /// **'Go back'**
  String get actionGoBack;

  /// No description provided for @actionNotNow.
  ///
  /// In en, this message translates to:
  /// **'Not now'**
  String get actionNotNow;

  /// No description provided for @actionUnderstood.
  ///
  /// In en, this message translates to:
  /// **'Got it'**
  String get actionUnderstood;

  /// No description provided for @actionOpen.
  ///
  /// In en, this message translates to:
  /// **'Open'**
  String get actionOpen;

  /// No description provided for @actionAdd.
  ///
  /// In en, this message translates to:
  /// **'Add'**
  String get actionAdd;

  /// No description provided for @actionChange.
  ///
  /// In en, this message translates to:
  /// **'Change'**
  String get actionChange;

  /// No description provided for @actionSelect.
  ///
  /// In en, this message translates to:
  /// **'Select'**
  String get actionSelect;

  /// No description provided for @actionSearch.
  ///
  /// In en, this message translates to:
  /// **'Search'**
  String get actionSearch;

  /// No description provided for @actionClear.
  ///
  /// In en, this message translates to:
  /// **'Clear'**
  String get actionClear;

  /// No description provided for @actionApply.
  ///
  /// In en, this message translates to:
  /// **'Apply'**
  String get actionApply;

  /// No description provided for @actionReport.
  ///
  /// In en, this message translates to:
  /// **'Report a problem'**
  String get actionReport;

  /// No description provided for @actionContactSupport.
  ///
  /// In en, this message translates to:
  /// **'Contact support'**
  String get actionContactSupport;

  /// No description provided for @navHome.
  ///
  /// In en, this message translates to:
  /// **'Home'**
  String get navHome;

  /// No description provided for @navDeliveries.
  ///
  /// In en, this message translates to:
  /// **'Deliveries'**
  String get navDeliveries;

  /// No description provided for @navChat.
  ///
  /// In en, this message translates to:
  /// **'Chat'**
  String get navChat;

  /// No description provided for @navProfile.
  ///
  /// In en, this message translates to:
  /// **'Profile'**
  String get navProfile;

  /// No description provided for @navNotifications.
  ///
  /// In en, this message translates to:
  /// **'Notifications'**
  String get navNotifications;

  /// Screen-reader label for the header bell.
  ///
  /// In en, this message translates to:
  /// **'Notifications, {count} unread'**
  String navNotificationsWithCount(int count);

  /// No description provided for @roleSender.
  ///
  /// In en, this message translates to:
  /// **'Sending'**
  String get roleSender;

  /// No description provided for @roleTraveler.
  ///
  /// In en, this message translates to:
  /// **'Travelling'**
  String get roleTraveler;

  /// No description provided for @roleSwitchLabel.
  ///
  /// In en, this message translates to:
  /// **'Switch role'**
  String get roleSwitchLabel;

  /// No description provided for @roleSwitchTitle.
  ///
  /// In en, this message translates to:
  /// **'What are you doing today?'**
  String get roleSwitchTitle;

  /// No description provided for @roleSenderDescription.
  ///
  /// In en, this message translates to:
  /// **'Send a parcel with a traveller'**
  String get roleSenderDescription;

  /// No description provided for @roleTravelerDescription.
  ///
  /// In en, this message translates to:
  /// **'Carry parcels on a trip you\'re taking'**
  String get roleTravelerDescription;

  /// No description provided for @roleSwitchedToSender.
  ///
  /// In en, this message translates to:
  /// **'Switched to sending'**
  String get roleSwitchedToSender;

  /// No description provided for @roleSwitchedToTraveler.
  ///
  /// In en, this message translates to:
  /// **'Switched to travelling'**
  String get roleSwitchedToTraveler;

  /// No description provided for @authSignIn.
  ///
  /// In en, this message translates to:
  /// **'Sign in'**
  String get authSignIn;

  /// No description provided for @authSignUp.
  ///
  /// In en, this message translates to:
  /// **'Create account'**
  String get authSignUp;

  /// No description provided for @authSignOut.
  ///
  /// In en, this message translates to:
  /// **'Sign out'**
  String get authSignOut;

  /// No description provided for @authEmail.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get authEmail;

  /// No description provided for @authPassword.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get authPassword;

  /// No description provided for @authFullName.
  ///
  /// In en, this message translates to:
  /// **'Full name'**
  String get authFullName;

  /// No description provided for @authForgotPassword.
  ///
  /// In en, this message translates to:
  /// **'Forgot your password?'**
  String get authForgotPassword;

  /// No description provided for @authResetPassword.
  ///
  /// In en, this message translates to:
  /// **'Reset password'**
  String get authResetPassword;

  /// No description provided for @authResetSent.
  ///
  /// In en, this message translates to:
  /// **'If that email has an account, we\'ve sent a reset code.'**
  String get authResetSent;

  /// No description provided for @authNoAccount.
  ///
  /// In en, this message translates to:
  /// **'New to ShipTrip?'**
  String get authNoAccount;

  /// No description provided for @authHaveAccount.
  ///
  /// In en, this message translates to:
  /// **'Already have an account?'**
  String get authHaveAccount;

  /// No description provided for @authVerifyEmailTitle.
  ///
  /// In en, this message translates to:
  /// **'Confirm your email'**
  String get authVerifyEmailTitle;

  /// No description provided for @authVerifyEmailBody.
  ///
  /// In en, this message translates to:
  /// **'We sent a link to {email}. Confirm it to keep your account secure.'**
  String authVerifyEmailBody(String email);

  /// No description provided for @authSignOutConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Sign out?'**
  String get authSignOutConfirmTitle;

  /// No description provided for @authSignOutConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'You\'ll need to sign in again to see your deliveries.'**
  String get authSignOutConfirmBody;

  /// No description provided for @validationRequired.
  ///
  /// In en, this message translates to:
  /// **'This is required'**
  String get validationRequired;

  /// No description provided for @validationEmailInvalid.
  ///
  /// In en, this message translates to:
  /// **'Enter a valid email address'**
  String get validationEmailInvalid;

  /// No description provided for @validationPasswordTooShort.
  ///
  /// In en, this message translates to:
  /// **'Use at least 8 characters'**
  String get validationPasswordTooShort;

  /// No description provided for @validationNumberInvalid.
  ///
  /// In en, this message translates to:
  /// **'Enter a number'**
  String get validationNumberInvalid;

  /// No description provided for @validationMustBePositive.
  ///
  /// In en, this message translates to:
  /// **'Enter a number greater than zero'**
  String get validationMustBePositive;

  /// No description provided for @validationTooLong.
  ///
  /// In en, this message translates to:
  /// **'Keep this under {max} characters'**
  String validationTooLong(int max);

  /// No description provided for @validationSelectOne.
  ///
  /// In en, this message translates to:
  /// **'Choose one'**
  String get validationSelectOne;

  /// No description provided for @validationDateInPast.
  ///
  /// In en, this message translates to:
  /// **'Choose a date in the future'**
  String get validationDateInPast;

  /// No description provided for @validationDeadlineBeforeReady.
  ///
  /// In en, this message translates to:
  /// **'The deadline has to be after the parcel is ready'**
  String get validationDeadlineBeforeReady;

  /// No description provided for @stateLoading.
  ///
  /// In en, this message translates to:
  /// **'Loading…'**
  String get stateLoading;

  /// No description provided for @stateOfflineTitle.
  ///
  /// In en, this message translates to:
  /// **'You\'re offline'**
  String get stateOfflineTitle;

  /// No description provided for @stateOfflineBody.
  ///
  /// In en, this message translates to:
  /// **'Check your connection. We\'ll load this as soon as you\'re back.'**
  String get stateOfflineBody;

  /// No description provided for @stateTimeoutTitle.
  ///
  /// In en, this message translates to:
  /// **'That took too long'**
  String get stateTimeoutTitle;

  /// No description provided for @stateTimeoutBody.
  ///
  /// In en, this message translates to:
  /// **'The server didn\'t answer in time.'**
  String get stateTimeoutBody;

  /// No description provided for @stateServerErrorTitle.
  ///
  /// In en, this message translates to:
  /// **'Something went wrong on our side'**
  String get stateServerErrorTitle;

  /// No description provided for @stateServerErrorBody.
  ///
  /// In en, this message translates to:
  /// **'This isn\'t your fault. Try again in a moment.'**
  String get stateServerErrorBody;

  /// No description provided for @stateNotFoundTitle.
  ///
  /// In en, this message translates to:
  /// **'Not found'**
  String get stateNotFoundTitle;

  /// No description provided for @stateNotFoundBody.
  ///
  /// In en, this message translates to:
  /// **'This may have been removed, or it was never yours to see.'**
  String get stateNotFoundBody;

  /// No description provided for @stateForbiddenTitle.
  ///
  /// In en, this message translates to:
  /// **'You can\'t do that here'**
  String get stateForbiddenTitle;

  /// No description provided for @stateForbiddenBody.
  ///
  /// In en, this message translates to:
  /// **'Your account doesn\'t have access to this.'**
  String get stateForbiddenBody;

  /// No description provided for @stateSessionExpiredTitle.
  ///
  /// In en, this message translates to:
  /// **'Please sign in again'**
  String get stateSessionExpiredTitle;

  /// No description provided for @stateSessionExpiredBody.
  ///
  /// In en, this message translates to:
  /// **'Your session ended. Sign in to pick up where you left off.'**
  String get stateSessionExpiredBody;

  /// No description provided for @stateRateLimitedTitle.
  ///
  /// In en, this message translates to:
  /// **'Too many attempts'**
  String get stateRateLimitedTitle;

  /// No description provided for @stateRateLimitedBody.
  ///
  /// In en, this message translates to:
  /// **'Wait a moment before trying again.'**
  String get stateRateLimitedBody;

  /// No description provided for @stateUnexpectedTitle.
  ///
  /// In en, this message translates to:
  /// **'Something unexpected happened'**
  String get stateUnexpectedTitle;

  /// No description provided for @stateUnexpectedBody.
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t complete that. Try again, and tell us if it keeps happening.'**
  String get stateUnexpectedBody;

  /// No description provided for @stateAppOutdatedTitle.
  ///
  /// In en, this message translates to:
  /// **'This version is out of date'**
  String get stateAppOutdatedTitle;

  /// No description provided for @stateAppOutdatedBody.
  ///
  /// In en, this message translates to:
  /// **'Update ShipTrip to continue. This part of the app no longer works on this version.'**
  String get stateAppOutdatedBody;

  /// No description provided for @staleTitle.
  ///
  /// In en, this message translates to:
  /// **'This has changed'**
  String get staleTitle;

  /// No description provided for @staleRefreshAction.
  ///
  /// In en, this message translates to:
  /// **'Refresh'**
  String get staleRefreshAction;

  /// No description provided for @staleRequestNotOpen.
  ///
  /// In en, this message translates to:
  /// **'This request isn\'t open any more.'**
  String get staleRequestNotOpen;

  /// No description provided for @staleRequestAlreadyMatched.
  ///
  /// In en, this message translates to:
  /// **'This request has already been matched with a traveller.'**
  String get staleRequestAlreadyMatched;

  /// No description provided for @staleJourneyNotActive.
  ///
  /// In en, this message translates to:
  /// **'This journey isn\'t active any more.'**
  String get staleJourneyNotActive;

  /// No description provided for @staleOfferNotPending.
  ///
  /// In en, this message translates to:
  /// **'This offer has already been answered.'**
  String get staleOfferNotPending;

  /// No description provided for @staleMatchNotPending.
  ///
  /// In en, this message translates to:
  /// **'This match isn\'t waiting on anyone any more.'**
  String get staleMatchNotPending;

  /// No description provided for @staleCapacityExceeded.
  ///
  /// In en, this message translates to:
  /// **'There isn\'t enough space left on this journey.'**
  String get staleCapacityExceeded;

  /// No description provided for @staleCapacityExceededDetail.
  ///
  /// In en, this message translates to:
  /// **'Someone else booked space while you were deciding.'**
  String get staleCapacityExceededDetail;

  /// No description provided for @staleRewardBelowMinimum.
  ///
  /// In en, this message translates to:
  /// **'The minimum reward has changed.'**
  String get staleRewardBelowMinimum;

  /// No description provided for @staleRewardBelowMinimumDetail.
  ///
  /// In en, this message translates to:
  /// **'The minimum is now {amount}.'**
  String staleRewardBelowMinimumDetail(String amount);

  /// No description provided for @staleRouteChanged.
  ///
  /// In en, this message translates to:
  /// **'The route details changed. We\'ve refreshed the price.'**
  String get staleRouteChanged;

  /// No description provided for @staleKycInvalid.
  ///
  /// In en, this message translates to:
  /// **'Your identity check needs attention before you can do this.'**
  String get staleKycInvalid;

  /// No description provided for @staleFlightProofInvalid.
  ///
  /// In en, this message translates to:
  /// **'Your flight proof needs attention before this journey can match.'**
  String get staleFlightProofInvalid;

  /// No description provided for @staleReservationExpired.
  ///
  /// In en, this message translates to:
  /// **'Your reserved space expired.'**
  String get staleReservationExpired;

  /// No description provided for @staleDealClosed.
  ///
  /// In en, this message translates to:
  /// **'This delivery is closed.'**
  String get staleDealClosed;

  /// No description provided for @staleOfferExpired.
  ///
  /// In en, this message translates to:
  /// **'This offer is no longer available.'**
  String get staleOfferExpired;

  /// No description provided for @moneyYouPay.
  ///
  /// In en, this message translates to:
  /// **'You pay'**
  String get moneyYouPay;

  /// No description provided for @moneyTravelerReceives.
  ///
  /// In en, this message translates to:
  /// **'Traveller receives'**
  String get moneyTravelerReceives;

  /// No description provided for @moneyPlatformFee.
  ///
  /// In en, this message translates to:
  /// **'ShipTrip fee'**
  String get moneyPlatformFee;

  /// No description provided for @moneyMinimumReward.
  ///
  /// In en, this message translates to:
  /// **'Minimum reward'**
  String get moneyMinimumReward;

  /// No description provided for @moneyRecommendedReward.
  ///
  /// In en, this message translates to:
  /// **'ShipTrip suggests'**
  String get moneyRecommendedReward;

  /// No description provided for @moneyYourReward.
  ///
  /// In en, this message translates to:
  /// **'Your reward'**
  String get moneyYourReward;

  /// No description provided for @moneyYourOffer.
  ///
  /// In en, this message translates to:
  /// **'Your offer'**
  String get moneyYourOffer;

  /// No description provided for @moneyTotal.
  ///
  /// In en, this message translates to:
  /// **'Total'**
  String get moneyTotal;

  /// No description provided for @moneyDepositPaid.
  ///
  /// In en, this message translates to:
  /// **'Deposit already paid'**
  String get moneyDepositPaid;

  /// No description provided for @moneyRemainingToPay.
  ///
  /// In en, this message translates to:
  /// **'Remaining to pay'**
  String get moneyRemainingToPay;

  /// No description provided for @moneyRefundToYou.
  ///
  /// In en, this message translates to:
  /// **'Refund to you'**
  String get moneyRefundToYou;

  /// No description provided for @moneyTravelerCompensation.
  ///
  /// In en, this message translates to:
  /// **'Traveller compensation'**
  String get moneyTravelerCompensation;

  /// No description provided for @moneyBreakdownTitle.
  ///
  /// In en, this message translates to:
  /// **'How this adds up'**
  String get moneyBreakdownTitle;

  /// No description provided for @moneyRewardNotReduced.
  ///
  /// In en, this message translates to:
  /// **'The traveller receives this full amount. The ShipTrip fee is added on top, not taken out of it.'**
  String get moneyRewardNotReduced;

  /// No description provided for @moneyDepositNotExtra.
  ///
  /// In en, this message translates to:
  /// **'This is credited towards your final payment. It isn\'t an extra fee.'**
  String get moneyDepositNotExtra;

  /// No description provided for @moneyAmountCharged.
  ///
  /// In en, this message translates to:
  /// **'You\'ll be charged'**
  String get moneyAmountCharged;

  /// No description provided for @moneyExchangeRate.
  ///
  /// In en, this message translates to:
  /// **'Rate: €1 = {rate} DA'**
  String moneyExchangeRate(String rate);

  /// No description provided for @moneyChargedInDinars.
  ///
  /// In en, this message translates to:
  /// **'Chargily charges in Algerian dinars. The delivery price stays in euros.'**
  String get moneyChargedInDinars;

  /// No description provided for @moneyFree.
  ///
  /// In en, this message translates to:
  /// **'Free'**
  String get moneyFree;

  /// No description provided for @homeSenderGreeting.
  ///
  /// In en, this message translates to:
  /// **'Send something home'**
  String get homeSenderGreeting;

  /// No description provided for @homeTravelerGreeting.
  ///
  /// In en, this message translates to:
  /// **'Earn on a trip you\'re already taking'**
  String get homeTravelerGreeting;

  /// No description provided for @homeCreateRequest.
  ///
  /// In en, this message translates to:
  /// **'Send a parcel'**
  String get homeCreateRequest;

  /// No description provided for @homeCreateJourney.
  ///
  /// In en, this message translates to:
  /// **'Add a journey'**
  String get homeCreateJourney;

  /// No description provided for @homeNeedsYourAction.
  ///
  /// In en, this message translates to:
  /// **'Needs you'**
  String get homeNeedsYourAction;

  /// No description provided for @homeInProgress.
  ///
  /// In en, this message translates to:
  /// **'In progress'**
  String get homeInProgress;

  /// No description provided for @homeRecentActivity.
  ///
  /// In en, this message translates to:
  /// **'Recent activity'**
  String get homeRecentActivity;

  /// No description provided for @homeNothingNeedsYou.
  ///
  /// In en, this message translates to:
  /// **'Nothing needs you right now'**
  String get homeNothingNeedsYou;

  /// No description provided for @homeEmptySenderTitle.
  ///
  /// In en, this message translates to:
  /// **'Nothing on the way yet'**
  String get homeEmptySenderTitle;

  /// No description provided for @homeEmptySenderBody.
  ///
  /// In en, this message translates to:
  /// **'Post what you want to send and travellers heading that way will see it.'**
  String get homeEmptySenderBody;

  /// No description provided for @homeEmptyTravelerTitle.
  ///
  /// In en, this message translates to:
  /// **'No journeys yet'**
  String get homeEmptyTravelerTitle;

  /// No description provided for @homeEmptyTravelerBody.
  ///
  /// In en, this message translates to:
  /// **'Add the trip you\'re taking and we\'ll show you parcels along your route.'**
  String get homeEmptyTravelerBody;

  /// No description provided for @deliveriesTitle.
  ///
  /// In en, this message translates to:
  /// **'Deliveries'**
  String get deliveriesTitle;

  /// No description provided for @deliveriesFilterActive.
  ///
  /// In en, this message translates to:
  /// **'Active'**
  String get deliveriesFilterActive;

  /// No description provided for @deliveriesFilterAwaitingYou.
  ///
  /// In en, this message translates to:
  /// **'Needs you'**
  String get deliveriesFilterAwaitingYou;

  /// No description provided for @deliveriesFilterHistory.
  ///
  /// In en, this message translates to:
  /// **'History'**
  String get deliveriesFilterHistory;

  /// No description provided for @deliveriesSenderSection.
  ///
  /// In en, this message translates to:
  /// **'Sending'**
  String get deliveriesSenderSection;

  /// No description provided for @deliveriesTravelerSection.
  ///
  /// In en, this message translates to:
  /// **'Carrying'**
  String get deliveriesTravelerSection;

  /// No description provided for @deliveriesJourneysSection.
  ///
  /// In en, this message translates to:
  /// **'My journeys'**
  String get deliveriesJourneysSection;

  /// No description provided for @deliveriesEmptyActiveTitle.
  ///
  /// In en, this message translates to:
  /// **'Nothing active'**
  String get deliveriesEmptyActiveTitle;

  /// No description provided for @deliveriesEmptyActiveBody.
  ///
  /// In en, this message translates to:
  /// **'Deliveries you\'re sending or carrying will appear here.'**
  String get deliveriesEmptyActiveBody;

  /// No description provided for @deliveriesEmptyHistoryTitle.
  ///
  /// In en, this message translates to:
  /// **'No history yet'**
  String get deliveriesEmptyHistoryTitle;

  /// No description provided for @deliveriesEmptyHistoryBody.
  ///
  /// In en, this message translates to:
  /// **'Completed and cancelled deliveries stay here.'**
  String get deliveriesEmptyHistoryBody;

  /// No description provided for @deliveriesEmptyAwaitingTitle.
  ///
  /// In en, this message translates to:
  /// **'You\'re all caught up'**
  String get deliveriesEmptyAwaitingTitle;

  /// No description provided for @deliveriesEmptyAwaitingBody.
  ///
  /// In en, this message translates to:
  /// **'Nothing is waiting on you.'**
  String get deliveriesEmptyAwaitingBody;

  /// No description provided for @requestStatusAwaitingDeposit.
  ///
  /// In en, this message translates to:
  /// **'Deposit needed'**
  String get requestStatusAwaitingDeposit;

  /// No description provided for @requestStatusOpen.
  ///
  /// In en, this message translates to:
  /// **'Finding a traveller'**
  String get requestStatusOpen;

  /// No description provided for @requestStatusMatched.
  ///
  /// In en, this message translates to:
  /// **'Matched'**
  String get requestStatusMatched;

  /// No description provided for @requestStatusInTransit.
  ///
  /// In en, this message translates to:
  /// **'On the way'**
  String get requestStatusInTransit;

  /// No description provided for @requestStatusDelivered.
  ///
  /// In en, this message translates to:
  /// **'Delivered'**
  String get requestStatusDelivered;

  /// No description provided for @requestStatusCompleted.
  ///
  /// In en, this message translates to:
  /// **'Completed'**
  String get requestStatusCompleted;

  /// No description provided for @requestStatusCancelled.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get requestStatusCancelled;

  /// No description provided for @requestStatusExpired.
  ///
  /// In en, this message translates to:
  /// **'Expired'**
  String get requestStatusExpired;

  /// No description provided for @dealStatusOfferAccepted.
  ///
  /// In en, this message translates to:
  /// **'Offer accepted'**
  String get dealStatusOfferAccepted;

  /// No description provided for @dealStatusPaymentRequired.
  ///
  /// In en, this message translates to:
  /// **'Payment needed'**
  String get dealStatusPaymentRequired;

  /// No description provided for @dealStatusPaymentProcessing.
  ///
  /// In en, this message translates to:
  /// **'Confirming payment'**
  String get dealStatusPaymentProcessing;

  /// No description provided for @dealStatusFunded.
  ///
  /// In en, this message translates to:
  /// **'Paid and protected'**
  String get dealStatusFunded;

  /// No description provided for @dealStatusPickupReady.
  ///
  /// In en, this message translates to:
  /// **'Ready for pickup'**
  String get dealStatusPickupReady;

  /// No description provided for @dealStatusPickedUp.
  ///
  /// In en, this message translates to:
  /// **'Picked up'**
  String get dealStatusPickedUp;

  /// No description provided for @dealStatusInTransit.
  ///
  /// In en, this message translates to:
  /// **'On the way'**
  String get dealStatusInTransit;

  /// No description provided for @dealStatusDeliveryReady.
  ///
  /// In en, this message translates to:
  /// **'Ready to deliver'**
  String get dealStatusDeliveryReady;

  /// No description provided for @dealStatusDeliveryConfirmed.
  ///
  /// In en, this message translates to:
  /// **'Delivered'**
  String get dealStatusDeliveryConfirmed;

  /// No description provided for @dealStatusProtection.
  ///
  /// In en, this message translates to:
  /// **'Payment protected'**
  String get dealStatusProtection;

  /// No description provided for @dealStatusCompleted.
  ///
  /// In en, this message translates to:
  /// **'Completed'**
  String get dealStatusCompleted;

  /// No description provided for @dealStatusCancelled.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get dealStatusCancelled;

  /// No description provided for @dealStatusDisputed.
  ///
  /// In en, this message translates to:
  /// **'Under dispute'**
  String get dealStatusDisputed;

  /// No description provided for @dealStatusRefunded.
  ///
  /// In en, this message translates to:
  /// **'Refunded'**
  String get dealStatusRefunded;

  /// No description provided for @dealStatusPartiallyRefunded.
  ///
  /// In en, this message translates to:
  /// **'Partly refunded'**
  String get dealStatusPartiallyRefunded;

  /// No description provided for @dealStatusPaymentFailed.
  ///
  /// In en, this message translates to:
  /// **'Payment failed'**
  String get dealStatusPaymentFailed;

  /// No description provided for @dealStatusExpired.
  ///
  /// In en, this message translates to:
  /// **'Expired'**
  String get dealStatusExpired;

  /// No description provided for @requestCreateTitle.
  ///
  /// In en, this message translates to:
  /// **'Send a parcel'**
  String get requestCreateTitle;

  /// No description provided for @requestStepRoute.
  ///
  /// In en, this message translates to:
  /// **'Route'**
  String get requestStepRoute;

  /// No description provided for @requestStepParcel.
  ///
  /// In en, this message translates to:
  /// **'Parcel'**
  String get requestStepParcel;

  /// No description provided for @requestStepTiming.
  ///
  /// In en, this message translates to:
  /// **'Timing'**
  String get requestStepTiming;

  /// No description provided for @requestStepReview.
  ///
  /// In en, this message translates to:
  /// **'Review'**
  String get requestStepReview;

  /// No description provided for @requestPickupLocation.
  ///
  /// In en, this message translates to:
  /// **'Pickup from'**
  String get requestPickupLocation;

  /// No description provided for @requestDeliveryLocation.
  ///
  /// In en, this message translates to:
  /// **'Deliver to'**
  String get requestDeliveryLocation;

  /// No description provided for @requestPickupHint.
  ///
  /// In en, this message translates to:
  /// **'Where the traveller collects the parcel'**
  String get requestPickupHint;

  /// No description provided for @requestDeliveryHint.
  ///
  /// In en, this message translates to:
  /// **'Where the parcel is handed to the recipient'**
  String get requestDeliveryHint;

  /// No description provided for @requestReadyFrom.
  ///
  /// In en, this message translates to:
  /// **'Ready from'**
  String get requestReadyFrom;

  /// No description provided for @requestDeadline.
  ///
  /// In en, this message translates to:
  /// **'Must arrive by'**
  String get requestDeadline;

  /// No description provided for @requestTitle.
  ///
  /// In en, this message translates to:
  /// **'What are you sending?'**
  String get requestTitle;

  /// No description provided for @requestTitleHint.
  ///
  /// In en, this message translates to:
  /// **'Documents, medicine, clothes…'**
  String get requestTitleHint;

  /// No description provided for @requestDescription.
  ///
  /// In en, this message translates to:
  /// **'Description'**
  String get requestDescription;

  /// No description provided for @requestDescriptionHint.
  ///
  /// In en, this message translates to:
  /// **'Describe it accurately. This is what the traveller agrees to carry.'**
  String get requestDescriptionHint;

  /// No description provided for @requestCategory.
  ///
  /// In en, this message translates to:
  /// **'Category'**
  String get requestCategory;

  /// No description provided for @requestWeight.
  ///
  /// In en, this message translates to:
  /// **'Weight'**
  String get requestWeight;

  /// No description provided for @requestWeightUnit.
  ///
  /// In en, this message translates to:
  /// **'kg'**
  String get requestWeightUnit;

  /// No description provided for @requestDimensions.
  ///
  /// In en, this message translates to:
  /// **'Size'**
  String get requestDimensions;

  /// No description provided for @requestLength.
  ///
  /// In en, this message translates to:
  /// **'Length'**
  String get requestLength;

  /// No description provided for @requestWidth.
  ///
  /// In en, this message translates to:
  /// **'Width'**
  String get requestWidth;

  /// No description provided for @requestHeight.
  ///
  /// In en, this message translates to:
  /// **'Height'**
  String get requestHeight;

  /// No description provided for @requestDimensionUnit.
  ///
  /// In en, this message translates to:
  /// **'cm'**
  String get requestDimensionUnit;

  /// No description provided for @requestDeclaredValue.
  ///
  /// In en, this message translates to:
  /// **'Declared value'**
  String get requestDeclaredValue;

  /// No description provided for @requestDeclaredValueHelp.
  ///
  /// In en, this message translates to:
  /// **'What it would cost to replace. Used if something goes wrong.'**
  String get requestDeclaredValueHelp;

  /// No description provided for @requestPhotos.
  ///
  /// In en, this message translates to:
  /// **'Photos'**
  String get requestPhotos;

  /// No description provided for @requestPhotosHelp.
  ///
  /// In en, this message translates to:
  /// **'Photos protect both of you if there\'s a dispute later.'**
  String get requestPhotosHelp;

  /// No description provided for @requestAddPhoto.
  ///
  /// In en, this message translates to:
  /// **'Add photo'**
  String get requestAddPhoto;

  /// No description provided for @requestHandlingNotes.
  ///
  /// In en, this message translates to:
  /// **'Handling notes'**
  String get requestHandlingNotes;

  /// No description provided for @requestHandlingNotesHint.
  ///
  /// In en, this message translates to:
  /// **'Anything the traveller should know'**
  String get requestHandlingNotesHint;

  /// No description provided for @requestFragile.
  ///
  /// In en, this message translates to:
  /// **'Fragile'**
  String get requestFragile;

  /// No description provided for @requestAcknowledgementsTitle.
  ///
  /// In en, this message translates to:
  /// **'Before you post this'**
  String get requestAcknowledgementsTitle;

  /// No description provided for @requestAckDescriptionAccurate.
  ///
  /// In en, this message translates to:
  /// **'My description of this parcel is accurate'**
  String get requestAckDescriptionAccurate;

  /// No description provided for @requestAckItemLegal.
  ///
  /// In en, this message translates to:
  /// **'This item is legal to send and to receive'**
  String get requestAckItemLegal;

  /// No description provided for @requestAckNoProhibited.
  ///
  /// In en, this message translates to:
  /// **'It contains no prohibited goods'**
  String get requestAckNoProhibited;

  /// No description provided for @requestAckValueAccurate.
  ///
  /// In en, this message translates to:
  /// **'The declared value is accurate'**
  String get requestAckValueAccurate;

  /// No description provided for @requestAckCustoms.
  ///
  /// In en, this message translates to:
  /// **'I understand I\'m responsible for any customs or import rules that apply'**
  String get requestAckCustoms;

  /// No description provided for @requestProhibitedItemsLink.
  ///
  /// In en, this message translates to:
  /// **'See what can\'t be sent'**
  String get requestProhibitedItemsLink;

  /// No description provided for @requestSizeExplainer.
  ///
  /// In en, this message translates to:
  /// **'Size matters as much as weight. We charge on whichever is greater.'**
  String get requestSizeExplainer;

  /// No description provided for @requestCreated.
  ///
  /// In en, this message translates to:
  /// **'Posted'**
  String get requestCreated;

  /// No description provided for @depositTitle.
  ///
  /// In en, this message translates to:
  /// **'Publish your request'**
  String get depositTitle;

  /// No description provided for @depositExplainer.
  ///
  /// In en, this message translates to:
  /// **'Pay a small deposit to publish this request to travellers.'**
  String get depositExplainer;

  /// No description provided for @depositAmount.
  ///
  /// In en, this message translates to:
  /// **'Deposit'**
  String get depositAmount;

  /// No description provided for @depositCreditedNote.
  ///
  /// In en, this message translates to:
  /// **'It\'s credited towards your final payment when a traveller accepts.'**
  String get depositCreditedNote;

  /// No description provided for @depositRefundNote.
  ///
  /// In en, this message translates to:
  /// **'If nobody takes it, or you cancel before accepting an offer, you get it back in full.'**
  String get depositRefundNote;

  /// No description provided for @depositPayAction.
  ///
  /// In en, this message translates to:
  /// **'Pay deposit and publish'**
  String get depositPayAction;

  /// No description provided for @depositPending.
  ///
  /// In en, this message translates to:
  /// **'Confirming your deposit…'**
  String get depositPending;

  /// No description provided for @depositPendingBody.
  ///
  /// In en, this message translates to:
  /// **'We\'re waiting for your payment provider to confirm. This usually takes a few seconds.'**
  String get depositPendingBody;

  /// No description provided for @depositPaidTitle.
  ///
  /// In en, this message translates to:
  /// **'Published'**
  String get depositPaidTitle;

  /// No description provided for @depositPaidBody.
  ///
  /// In en, this message translates to:
  /// **'Travellers heading your way can see this now.'**
  String get depositPaidBody;

  /// No description provided for @journeyTitle.
  ///
  /// In en, this message translates to:
  /// **'Journey'**
  String get journeyTitle;

  /// No description provided for @journeyCreateTitle.
  ///
  /// In en, this message translates to:
  /// **'Add a journey'**
  String get journeyCreateTitle;

  /// No description provided for @journeyOverallRoute.
  ///
  /// In en, this message translates to:
  /// **'Where are you going?'**
  String get journeyOverallRoute;

  /// No description provided for @journeyFrom.
  ///
  /// In en, this message translates to:
  /// **'From'**
  String get journeyFrom;

  /// No description provided for @journeyTo.
  ///
  /// In en, this message translates to:
  /// **'To'**
  String get journeyTo;

  /// No description provided for @journeyLegs.
  ///
  /// In en, this message translates to:
  /// **'Legs'**
  String get journeyLegs;

  /// No description provided for @journeyAddLeg.
  ///
  /// In en, this message translates to:
  /// **'Add a leg'**
  String get journeyAddLeg;

  /// No description provided for @journeyLegPosition.
  ///
  /// In en, this message translates to:
  /// **'Leg {position}'**
  String journeyLegPosition(int position);

  /// No description provided for @journeyModeFlight.
  ///
  /// In en, this message translates to:
  /// **'Flight'**
  String get journeyModeFlight;

  /// No description provided for @journeyModeDrive.
  ///
  /// In en, this message translates to:
  /// **'Drive'**
  String get journeyModeDrive;

  /// No description provided for @journeyDeparts.
  ///
  /// In en, this message translates to:
  /// **'Departs'**
  String get journeyDeparts;

  /// No description provided for @journeyArrives.
  ///
  /// In en, this message translates to:
  /// **'Arrives'**
  String get journeyArrives;

  /// No description provided for @journeyCapacity.
  ///
  /// In en, this message translates to:
  /// **'Space you can carry'**
  String get journeyCapacity;

  /// No description provided for @journeyCapacityHelp.
  ///
  /// In en, this message translates to:
  /// **'Set this per leg. You can carry different amounts on different parts of the trip.'**
  String get journeyCapacityHelp;

  /// No description provided for @journeyFlightNumber.
  ///
  /// In en, this message translates to:
  /// **'Flight number'**
  String get journeyFlightNumber;

  /// No description provided for @journeyFlightNumberHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. AH1006'**
  String get journeyFlightNumberHint;

  /// No description provided for @journeyFlightAirportsRequired.
  ///
  /// In en, this message translates to:
  /// **'Flight legs must start and end at airports.'**
  String get journeyFlightAirportsRequired;

  /// No description provided for @journeyPublish.
  ///
  /// In en, this message translates to:
  /// **'Publish journey'**
  String get journeyPublish;

  /// No description provided for @journeyCancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel journey'**
  String get journeyCancel;

  /// No description provided for @journeySuggestLegTitle.
  ///
  /// In en, this message translates to:
  /// **'Add the road leg?'**
  String get journeySuggestLegTitle;

  /// No description provided for @journeySuggestLegBody.
  ///
  /// In en, this message translates to:
  /// **'Your flight lands in {arrival}, but you\'re going to {destination}. Add the drive so parcels can be matched all the way.'**
  String journeySuggestLegBody(String arrival, String destination);

  /// No description provided for @journeySuggestLegAccept.
  ///
  /// In en, this message translates to:
  /// **'Add drive leg'**
  String get journeySuggestLegAccept;

  /// No description provided for @journeySuggestLegDecline.
  ///
  /// In en, this message translates to:
  /// **'No, I stop there'**
  String get journeySuggestLegDecline;

  /// No description provided for @journeyStatusDraft.
  ///
  /// In en, this message translates to:
  /// **'Draft'**
  String get journeyStatusDraft;

  /// No description provided for @journeyStatusPendingVerification.
  ///
  /// In en, this message translates to:
  /// **'Being checked'**
  String get journeyStatusPendingVerification;

  /// No description provided for @journeyStatusActive.
  ///
  /// In en, this message translates to:
  /// **'Live'**
  String get journeyStatusActive;

  /// No description provided for @journeyStatusInProgress.
  ///
  /// In en, this message translates to:
  /// **'Under way'**
  String get journeyStatusInProgress;

  /// No description provided for @journeyStatusCompleted.
  ///
  /// In en, this message translates to:
  /// **'Completed'**
  String get journeyStatusCompleted;

  /// No description provided for @journeyStatusCancelled.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get journeyStatusCancelled;

  /// No description provided for @journeyStatusExpired.
  ///
  /// In en, this message translates to:
  /// **'Expired'**
  String get journeyStatusExpired;

  /// No description provided for @journeyEmptyLegsTitle.
  ///
  /// In en, this message translates to:
  /// **'Add your first leg'**
  String get journeyEmptyLegsTitle;

  /// No description provided for @journeyEmptyLegsBody.
  ///
  /// In en, this message translates to:
  /// **'A journey is made of legs. Paris to Algiers by plane, then Algiers to Jijel by road.'**
  String get journeyEmptyLegsBody;

  /// No description provided for @journeyRouteShape.
  ///
  /// In en, this message translates to:
  /// **'Your route'**
  String get journeyRouteShape;

  /// No description provided for @journeyModeLabel.
  ///
  /// In en, this message translates to:
  /// **'How you\'re travelling'**
  String get journeyModeLabel;

  /// No description provided for @journeyLegStartsAt.
  ///
  /// In en, this message translates to:
  /// **'Starts at'**
  String get journeyLegStartsAt;

  /// No description provided for @journeyLegEndsAt.
  ///
  /// In en, this message translates to:
  /// **'Ends at'**
  String get journeyLegEndsAt;

  /// No description provided for @journeyLegEndPlaceholder.
  ///
  /// In en, this message translates to:
  /// **'Choose where this leg ends'**
  String get journeyLegEndPlaceholder;

  /// No description provided for @journeyChooseDateTime.
  ///
  /// In en, this message translates to:
  /// **'Choose date and time'**
  String get journeyChooseDateTime;

  /// No description provided for @journeyArriveOptionalHelp.
  ///
  /// In en, this message translates to:
  /// **'Optional. It lets us check the next leg leaves in time.'**
  String get journeyArriveOptionalHelp;

  /// No description provided for @journeyRemoveLeg.
  ///
  /// In en, this message translates to:
  /// **'Remove this leg'**
  String get journeyRemoveLeg;

  /// No description provided for @journeyAddLegDestinationTitle.
  ///
  /// In en, this message translates to:
  /// **'Where does this leg end?'**
  String get journeyAddLegDestinationTitle;

  /// No description provided for @journeyMaxLegsReached.
  ///
  /// In en, this message translates to:
  /// **'A journey can hold at most 20 legs.'**
  String get journeyMaxLegsReached;

  /// No description provided for @journeyCapacityInvalid.
  ///
  /// In en, this message translates to:
  /// **'Enter at least 0.01 kg, to two decimal places.'**
  String get journeyCapacityInvalid;

  /// No description provided for @journeyLegDepartRequired.
  ///
  /// In en, this message translates to:
  /// **'Say when this leg departs.'**
  String get journeyLegDepartRequired;

  /// No description provided for @journeyLegDepartNotAfterPrevious.
  ///
  /// In en, this message translates to:
  /// **'This leg has to depart after the leg before it.'**
  String get journeyLegDepartNotAfterPrevious;

  /// No description provided for @journeyLegDepartBeforePreviousArrival.
  ///
  /// In en, this message translates to:
  /// **'This leg departs before the previous one lands.'**
  String get journeyLegDepartBeforePreviousArrival;

  /// No description provided for @journeyLegArriveBeforeDepart.
  ///
  /// In en, this message translates to:
  /// **'Arrival has to be after departure.'**
  String get journeyLegArriveBeforeDepart;

  /// No description provided for @journeyNotesLabel.
  ///
  /// In en, this message translates to:
  /// **'Anything senders should know'**
  String get journeyNotesLabel;

  /// No description provided for @journeyNotesHint.
  ///
  /// In en, this message translates to:
  /// **'No liquids, small parcels only, meeting near the terminal…'**
  String get journeyNotesHint;

  /// No description provided for @journeySaveDraft.
  ///
  /// In en, this message translates to:
  /// **'Save journey'**
  String get journeySaveDraft;

  /// No description provided for @journeyCreatedDraft.
  ///
  /// In en, this message translates to:
  /// **'Saved as a draft. Add flight proof, then publish it.'**
  String get journeyCreatedDraft;

  /// No description provided for @journeyDraftNextSteps.
  ///
  /// In en, this message translates to:
  /// **'Nothing is visible to senders yet. Publish it when your flight proof is approved.'**
  String get journeyDraftNextSteps;

  /// No description provided for @journeyLegsNeedProofTitle.
  ///
  /// In en, this message translates to:
  /// **'Flights that need proof'**
  String get journeyLegsNeedProofTitle;

  /// No description provided for @journeyPublishBlockedProof.
  ///
  /// In en, this message translates to:
  /// **'Every flight leg needs approved proof before this can go live.'**
  String get journeyPublishBlockedProof;

  /// No description provided for @journeyPublished.
  ///
  /// In en, this message translates to:
  /// **'Your journey is live. Senders heading your way can see it.'**
  String get journeyPublished;

  /// No description provided for @journeyErrorNotPublishable.
  ///
  /// In en, this message translates to:
  /// **'This journey can\'t be published from where it is now.'**
  String get journeyErrorNotPublishable;

  /// No description provided for @journeyErrorNoLegs.
  ///
  /// In en, this message translates to:
  /// **'This journey has no legs, so there is nothing to publish.'**
  String get journeyErrorNoLegs;

  /// No description provided for @journeyErrorLegPositions.
  ///
  /// In en, this message translates to:
  /// **'The legs are numbered wrongly. Cancel this journey and create it again.'**
  String get journeyErrorLegPositions;

  /// No description provided for @journeyErrorEndpointsMismatch.
  ///
  /// In en, this message translates to:
  /// **'The first and last legs don\'t match the journey\'s start and destination.'**
  String get journeyErrorEndpointsMismatch;

  /// No description provided for @journeyErrorLegEndpoints.
  ///
  /// In en, this message translates to:
  /// **'One leg starts or ends somewhere the route doesn\'t pass through.'**
  String get journeyErrorLegEndpoints;

  /// No description provided for @journeyErrorLegTime.
  ///
  /// In en, this message translates to:
  /// **'One leg arrives before it departs.'**
  String get journeyErrorLegTime;

  /// No description provided for @journeyErrorLegsDisconnected.
  ///
  /// In en, this message translates to:
  /// **'The legs don\'t join up into one route.'**
  String get journeyErrorLegsDisconnected;

  /// No description provided for @journeyErrorLegTimeOrder.
  ///
  /// In en, this message translates to:
  /// **'The legs aren\'t in time order.'**
  String get journeyErrorLegTimeOrder;

  /// No description provided for @journeyErrorNotOwned.
  ///
  /// In en, this message translates to:
  /// **'This journey belongs to someone else.'**
  String get journeyErrorNotOwned;

  /// No description provided for @journeyRebuildHint.
  ///
  /// In en, this message translates to:
  /// **'Cancel this journey and create it again with the corrected details.'**
  String get journeyRebuildHint;

  /// No description provided for @journeyCancelConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Cancel this journey?'**
  String get journeyCancelConfirmTitle;

  /// No description provided for @journeyCancelConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'Senders stop seeing it and any space they were holding is released. This can\'t be undone.'**
  String get journeyCancelConfirmBody;

  /// No description provided for @journeyCancelled.
  ///
  /// In en, this message translates to:
  /// **'Journey cancelled.'**
  String get journeyCancelled;

  /// How many pending capacity reservations the server released when a journey was cancelled.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =0{No reserved space was being held.} =1{1 reserved space was released.} other{{count} reserved spaces were released.}}'**
  String journeyReleasedAllocations(int count);

  /// No description provided for @journeyErrorNotCancellable.
  ///
  /// In en, this message translates to:
  /// **'This journey can\'t be cancelled from where it is now.'**
  String get journeyErrorNotCancellable;

  /// No description provided for @journeyErrorHasFundedDeal.
  ///
  /// In en, this message translates to:
  /// **'A paid delivery is riding on this journey. Sort that delivery out first.'**
  String get journeyErrorHasFundedDeal;

  /// No description provided for @journeyMatchesInfoTitle.
  ///
  /// In en, this message translates to:
  /// **'Senders make the first move'**
  String get journeyMatchesInfoTitle;

  /// No description provided for @journeyMatchesInfoBody.
  ///
  /// In en, this message translates to:
  /// **'You can\'t offer on these. If one of these senders picks you, their offer arrives in Deliveries.'**
  String get journeyMatchesInfoBody;

  /// No description provided for @journeyMatchesLoadFailed.
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t load parcels for this journey.'**
  String get journeyMatchesLoadFailed;

  /// No description provided for @proofTitle.
  ///
  /// In en, this message translates to:
  /// **'Flight proof'**
  String get proofTitle;

  /// No description provided for @proofExplainer.
  ///
  /// In en, this message translates to:
  /// **'Upload your boarding pass or booking confirmation. We check it before your journey can match parcels.'**
  String get proofExplainer;

  /// No description provided for @proofDriveNotRequired.
  ///
  /// In en, this message translates to:
  /// **'Driving legs don\'t need any proof.'**
  String get proofDriveNotRequired;

  /// No description provided for @proofUpload.
  ///
  /// In en, this message translates to:
  /// **'Upload proof'**
  String get proofUpload;

  /// No description provided for @proofStatusMissing.
  ///
  /// In en, this message translates to:
  /// **'Not uploaded'**
  String get proofStatusMissing;

  /// No description provided for @proofStatusPending.
  ///
  /// In en, this message translates to:
  /// **'Being reviewed'**
  String get proofStatusPending;

  /// No description provided for @proofStatusApproved.
  ///
  /// In en, this message translates to:
  /// **'Approved'**
  String get proofStatusApproved;

  /// No description provided for @proofStatusRejected.
  ///
  /// In en, this message translates to:
  /// **'Not accepted'**
  String get proofStatusRejected;

  /// No description provided for @proofRejectedReason.
  ///
  /// In en, this message translates to:
  /// **'Reason: {reason}'**
  String proofRejectedReason(String reason);

  /// No description provided for @proofReplace.
  ///
  /// In en, this message translates to:
  /// **'Upload a new one'**
  String get proofReplace;

  /// No description provided for @proofKindLabel.
  ///
  /// In en, this message translates to:
  /// **'What are you uploading?'**
  String get proofKindLabel;

  /// No description provided for @proofKindTicket.
  ///
  /// In en, this message translates to:
  /// **'Ticket'**
  String get proofKindTicket;

  /// No description provided for @proofKindBoardingPass.
  ///
  /// In en, this message translates to:
  /// **'Boarding pass'**
  String get proofKindBoardingPass;

  /// No description provided for @proofKindBookingConfirmation.
  ///
  /// In en, this message translates to:
  /// **'Booking'**
  String get proofKindBookingConfirmation;

  /// No description provided for @proofFormatRule.
  ///
  /// In en, this message translates to:
  /// **'JPEG, PNG or WebP, up to 10 MB. We check the file itself, so renaming one won\'t get it through.'**
  String get proofFormatRule;

  /// No description provided for @proofFileTooLarge.
  ///
  /// In en, this message translates to:
  /// **'That image is over 10 MB. Pick a smaller one.'**
  String get proofFileTooLarge;

  /// No description provided for @proofFileTypeNotAllowed.
  ///
  /// In en, this message translates to:
  /// **'Only JPEG, PNG and WebP images are accepted.'**
  String get proofFileTypeNotAllowed;

  /// No description provided for @proofChooseImage.
  ///
  /// In en, this message translates to:
  /// **'Choose an image'**
  String get proofChooseImage;

  /// No description provided for @proofTakePhoto.
  ///
  /// In en, this message translates to:
  /// **'Take a photo'**
  String get proofTakePhoto;

  /// No description provided for @proofSelectedFile.
  ///
  /// In en, this message translates to:
  /// **'Ready to upload'**
  String get proofSelectedFile;

  /// No description provided for @proofUploading.
  ///
  /// In en, this message translates to:
  /// **'Uploading your proof…'**
  String get proofUploading;

  /// No description provided for @proofUploaded.
  ///
  /// In en, this message translates to:
  /// **'Proof received. We\'ll review it shortly.'**
  String get proofUploaded;

  /// No description provided for @proofExistingTitle.
  ///
  /// In en, this message translates to:
  /// **'What you\'ve already sent'**
  String get proofExistingTitle;

  /// No description provided for @proofErrorUploadClosed.
  ///
  /// In en, this message translates to:
  /// **'This journey is past the point where proof can be added.'**
  String get proofErrorUploadClosed;

  /// Names the leg a proof upload belongs to.
  ///
  /// In en, this message translates to:
  /// **'Leg {position}: {from} to {to}'**
  String proofLegLabel(int position, String from, String to);

  /// No description provided for @kycTitle.
  ///
  /// In en, this message translates to:
  /// **'Identity check'**
  String get kycTitle;

  /// No description provided for @kycWhyTitle.
  ///
  /// In en, this message translates to:
  /// **'Why we ask'**
  String get kycWhyTitle;

  /// No description provided for @kycWhyBody.
  ///
  /// In en, this message translates to:
  /// **'Senders are handing a stranger something that matters to them. Verifying travellers is what makes that reasonable.'**
  String get kycWhyBody;

  /// No description provided for @kycStatusNotStarted.
  ///
  /// In en, this message translates to:
  /// **'Not started'**
  String get kycStatusNotStarted;

  /// No description provided for @kycStatusInProgress.
  ///
  /// In en, this message translates to:
  /// **'In progress'**
  String get kycStatusInProgress;

  /// No description provided for @kycStatusPending.
  ///
  /// In en, this message translates to:
  /// **'Being reviewed'**
  String get kycStatusPending;

  /// No description provided for @kycStatusApproved.
  ///
  /// In en, this message translates to:
  /// **'Verified'**
  String get kycStatusApproved;

  /// No description provided for @kycStatusRejected.
  ///
  /// In en, this message translates to:
  /// **'Not approved'**
  String get kycStatusRejected;

  /// No description provided for @kycStatusActionRequired.
  ///
  /// In en, this message translates to:
  /// **'Needs your attention'**
  String get kycStatusActionRequired;

  /// No description provided for @kycStartAction.
  ///
  /// In en, this message translates to:
  /// **'Start identity check'**
  String get kycStartAction;

  /// No description provided for @kycResumeAction.
  ///
  /// In en, this message translates to:
  /// **'Finish identity check'**
  String get kycResumeAction;

  /// No description provided for @kycRetryAction.
  ///
  /// In en, this message translates to:
  /// **'Try again'**
  String get kycRetryAction;

  /// No description provided for @kycPendingBody.
  ///
  /// In en, this message translates to:
  /// **'We\'re reviewing your documents. This usually takes less than a day.'**
  String get kycPendingBody;

  /// No description provided for @kycApprovedBody.
  ///
  /// In en, this message translates to:
  /// **'You\'re verified. You can publish journeys and carry parcels.'**
  String get kycApprovedBody;

  /// No description provided for @kycRejectedBody.
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t verify your documents. You can submit again.'**
  String get kycRejectedBody;

  /// No description provided for @kycRequiredForJourney.
  ///
  /// In en, this message translates to:
  /// **'You need to be verified before you can publish a journey.'**
  String get kycRequiredForJourney;

  /// No description provided for @kycDocumentType.
  ///
  /// In en, this message translates to:
  /// **'Document type'**
  String get kycDocumentType;

  /// No description provided for @kycFrontImage.
  ///
  /// In en, this message translates to:
  /// **'Front of document'**
  String get kycFrontImage;

  /// No description provided for @kycBackImage.
  ///
  /// In en, this message translates to:
  /// **'Back of document'**
  String get kycBackImage;

  /// No description provided for @kycSelfie.
  ///
  /// In en, this message translates to:
  /// **'Selfie'**
  String get kycSelfie;

  /// No description provided for @discoveryTravelersTitle.
  ///
  /// In en, this message translates to:
  /// **'Travellers for this parcel'**
  String get discoveryTravelersTitle;

  /// No description provided for @discoveryRequestsTitle.
  ///
  /// In en, this message translates to:
  /// **'Parcels along your route'**
  String get discoveryRequestsTitle;

  /// No description provided for @discoveryEmptyTravelersTitle.
  ///
  /// In en, this message translates to:
  /// **'No travellers yet'**
  String get discoveryEmptyTravelersTitle;

  /// No description provided for @discoveryEmptyTravelersBody.
  ///
  /// In en, this message translates to:
  /// **'Nobody is going your way right now. We\'ll notify you when someone is.'**
  String get discoveryEmptyTravelersBody;

  /// No description provided for @discoveryEmptyRequestsTitle.
  ///
  /// In en, this message translates to:
  /// **'No parcels yet'**
  String get discoveryEmptyRequestsTitle;

  /// No description provided for @discoveryEmptyRequestsBody.
  ///
  /// In en, this message translates to:
  /// **'Nothing matches your journey right now. We\'ll notify you when something does.'**
  String get discoveryEmptyRequestsBody;

  /// No description provided for @discoveryCoveredLegs.
  ///
  /// In en, this message translates to:
  /// **'Covers {count, plural, =1{1 leg} other{{count} legs}}'**
  String discoveryCoveredLegs(int count);

  /// No description provided for @discoveryDetourSmall.
  ///
  /// In en, this message translates to:
  /// **'Barely a detour'**
  String get discoveryDetourSmall;

  /// No description provided for @discoveryDetourModerate.
  ///
  /// In en, this message translates to:
  /// **'Small detour'**
  String get discoveryDetourModerate;

  /// No description provided for @discoveryDetourLarge.
  ///
  /// In en, this message translates to:
  /// **'Noticeable detour'**
  String get discoveryDetourLarge;

  /// No description provided for @discoveryVerifiedTraveler.
  ///
  /// In en, this message translates to:
  /// **'Verified traveller'**
  String get discoveryVerifiedTraveler;

  /// No description provided for @discoveryBoosted.
  ///
  /// In en, this message translates to:
  /// **'Boosted'**
  String get discoveryBoosted;

  /// No description provided for @discoveryBoostedExplainer.
  ///
  /// In en, this message translates to:
  /// **'The sender paid to be seen by more travellers. It doesn\'t change whether you\'re a match.'**
  String get discoveryBoostedExplainer;

  /// No description provided for @discoveryRatingCount.
  ///
  /// In en, this message translates to:
  /// **'{rating} ({count})'**
  String discoveryRatingCount(String rating, int count);

  /// No description provided for @discoveryNoRatingsYet.
  ///
  /// In en, this message translates to:
  /// **'No ratings yet'**
  String get discoveryNoRatingsYet;

  /// No description provided for @offerProposeTitle.
  ///
  /// In en, this message translates to:
  /// **'Make an offer'**
  String get offerProposeTitle;

  /// No description provided for @offerProposeExplainer.
  ///
  /// In en, this message translates to:
  /// **'You choose what the traveller earns. They can accept, decline, or come back with a different amount.'**
  String get offerProposeExplainer;

  /// No description provided for @offerRewardLabel.
  ///
  /// In en, this message translates to:
  /// **'Traveller\'s reward'**
  String get offerRewardLabel;

  /// No description provided for @offerUseRecommended.
  ///
  /// In en, this message translates to:
  /// **'Use suggested'**
  String get offerUseRecommended;

  /// No description provided for @offerSend.
  ///
  /// In en, this message translates to:
  /// **'Send offer'**
  String get offerSend;

  /// No description provided for @offerCounter.
  ///
  /// In en, this message translates to:
  /// **'Counter'**
  String get offerCounter;

  /// No description provided for @offerAccept.
  ///
  /// In en, this message translates to:
  /// **'Accept'**
  String get offerAccept;

  /// No description provided for @offerDecline.
  ///
  /// In en, this message translates to:
  /// **'Decline'**
  String get offerDecline;

  /// No description provided for @offerWithdraw.
  ///
  /// In en, this message translates to:
  /// **'Withdraw'**
  String get offerWithdraw;

  /// No description provided for @offerAwaitingTraveler.
  ///
  /// In en, this message translates to:
  /// **'Waiting for the traveller'**
  String get offerAwaitingTraveler;

  /// No description provided for @offerAwaitingSender.
  ///
  /// In en, this message translates to:
  /// **'Waiting for the sender'**
  String get offerAwaitingSender;

  /// No description provided for @offerAwaitingYou.
  ///
  /// In en, this message translates to:
  /// **'Your move'**
  String get offerAwaitingYou;

  /// No description provided for @offerYouProposed.
  ///
  /// In en, this message translates to:
  /// **'You offered {amount}'**
  String offerYouProposed(String amount);

  /// No description provided for @offerTheyProposed.
  ///
  /// In en, this message translates to:
  /// **'They offered {amount}'**
  String offerTheyProposed(String amount);

  /// No description provided for @offerHistoryTitle.
  ///
  /// In en, this message translates to:
  /// **'Offer history'**
  String get offerHistoryTitle;

  /// No description provided for @offerStatusPending.
  ///
  /// In en, this message translates to:
  /// **'Waiting'**
  String get offerStatusPending;

  /// No description provided for @offerStatusAccepted.
  ///
  /// In en, this message translates to:
  /// **'Accepted'**
  String get offerStatusAccepted;

  /// No description provided for @offerStatusDeclined.
  ///
  /// In en, this message translates to:
  /// **'Declined'**
  String get offerStatusDeclined;

  /// No description provided for @offerStatusWithdrawn.
  ///
  /// In en, this message translates to:
  /// **'Withdrawn'**
  String get offerStatusWithdrawn;

  /// No description provided for @offerStatusExpired.
  ///
  /// In en, this message translates to:
  /// **'Expired'**
  String get offerStatusExpired;

  /// No description provided for @offerDeclineConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Decline this offer?'**
  String get offerDeclineConfirmTitle;

  /// No description provided for @offerDeclineConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'The other side will be told. You can still negotiate afterwards.'**
  String get offerDeclineConfirmBody;

  /// No description provided for @offerAcceptConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Accept {amount}?'**
  String offerAcceptConfirmTitle(String amount);

  /// No description provided for @offerAcceptTravelerBody.
  ///
  /// In en, this message translates to:
  /// **'Space on your journey is reserved as soon as you accept. The sender then has to pay.'**
  String get offerAcceptTravelerBody;

  /// No description provided for @offerAcceptSenderBody.
  ///
  /// In en, this message translates to:
  /// **'Once you accept, you\'ll be asked to pay so the delivery can start.'**
  String get offerAcceptSenderBody;

  /// No description provided for @offerBelowMinimum.
  ///
  /// In en, this message translates to:
  /// **'Offer at least {amount}'**
  String offerBelowMinimum(String amount);

  /// No description provided for @offerEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No offers yet'**
  String get offerEmptyTitle;

  /// No description provided for @offerEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'When someone makes an offer, it shows up here.'**
  String get offerEmptyBody;

  /// No description provided for @paymentTitle.
  ///
  /// In en, this message translates to:
  /// **'Payment'**
  String get paymentTitle;

  /// No description provided for @paymentChooseProvider.
  ///
  /// In en, this message translates to:
  /// **'How would you like to pay?'**
  String get paymentChooseProvider;

  /// No description provided for @paymentProviderStripe.
  ///
  /// In en, this message translates to:
  /// **'Card'**
  String get paymentProviderStripe;

  /// No description provided for @paymentProviderStripeSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Visa, Mastercard and others, in euros'**
  String get paymentProviderStripeSubtitle;

  /// No description provided for @paymentProviderChargily.
  ///
  /// In en, this message translates to:
  /// **'Chargily'**
  String get paymentProviderChargily;

  /// No description provided for @paymentProviderChargilySubtitle.
  ///
  /// In en, this message translates to:
  /// **'Algerian cards, charged in dinars'**
  String get paymentProviderChargilySubtitle;

  /// No description provided for @paymentProviderUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Unavailable right now'**
  String get paymentProviderUnavailable;

  /// No description provided for @paymentProviderNotConfigured.
  ///
  /// In en, this message translates to:
  /// **'Not available yet'**
  String get paymentProviderNotConfigured;

  /// No description provided for @paymentProviderDisabled.
  ///
  /// In en, this message translates to:
  /// **'Temporarily switched off'**
  String get paymentProviderDisabled;

  /// No description provided for @paymentNoProvidersTitle.
  ///
  /// In en, this message translates to:
  /// **'No payment method available'**
  String get paymentNoProvidersTitle;

  /// No description provided for @paymentNoProvidersBody.
  ///
  /// In en, this message translates to:
  /// **'Payment is temporarily unavailable. Nothing has been charged and your delivery is unaffected.'**
  String get paymentNoProvidersBody;

  /// No description provided for @paymentPayAction.
  ///
  /// In en, this message translates to:
  /// **'Pay {amount}'**
  String paymentPayAction(String amount);

  /// No description provided for @paymentOpeningProvider.
  ///
  /// In en, this message translates to:
  /// **'Opening secure checkout…'**
  String get paymentOpeningProvider;

  /// No description provided for @paymentConfirmingTitle.
  ///
  /// In en, this message translates to:
  /// **'Confirming your payment'**
  String get paymentConfirmingTitle;

  /// No description provided for @paymentConfirmingBody.
  ///
  /// In en, this message translates to:
  /// **'Your bank has told us, and we\'re confirming it with ShipTrip. Don\'t pay again — this usually takes a few seconds.'**
  String get paymentConfirmingBody;

  /// No description provided for @paymentSucceededTitle.
  ///
  /// In en, this message translates to:
  /// **'Paid'**
  String get paymentSucceededTitle;

  /// No description provided for @paymentSucceededBody.
  ///
  /// In en, this message translates to:
  /// **'Your money is held until the parcel is delivered.'**
  String get paymentSucceededBody;

  /// No description provided for @paymentFailedTitle.
  ///
  /// In en, this message translates to:
  /// **'Payment didn\'t go through'**
  String get paymentFailedTitle;

  /// No description provided for @paymentFailedBody.
  ///
  /// In en, this message translates to:
  /// **'Nothing was charged. You can try again or use a different method.'**
  String get paymentFailedBody;

  /// No description provided for @paymentExpiredTitle.
  ///
  /// In en, this message translates to:
  /// **'Checkout expired'**
  String get paymentExpiredTitle;

  /// No description provided for @paymentExpiredBody.
  ///
  /// In en, this message translates to:
  /// **'That checkout link timed out. Start again when you\'re ready.'**
  String get paymentExpiredBody;

  /// No description provided for @paymentStatusRequired.
  ///
  /// In en, this message translates to:
  /// **'Payment needed'**
  String get paymentStatusRequired;

  /// No description provided for @paymentStatusStarted.
  ///
  /// In en, this message translates to:
  /// **'Checkout open'**
  String get paymentStatusStarted;

  /// No description provided for @paymentStatusProcessing.
  ///
  /// In en, this message translates to:
  /// **'Processing'**
  String get paymentStatusProcessing;

  /// No description provided for @paymentStatusPaid.
  ///
  /// In en, this message translates to:
  /// **'Paid'**
  String get paymentStatusPaid;

  /// No description provided for @paymentStatusFailed.
  ///
  /// In en, this message translates to:
  /// **'Failed'**
  String get paymentStatusFailed;

  /// No description provided for @paymentStatusRefundPending.
  ///
  /// In en, this message translates to:
  /// **'Refund on the way'**
  String get paymentStatusRefundPending;

  /// No description provided for @paymentStatusPartiallyRefunded.
  ///
  /// In en, this message translates to:
  /// **'Partly refunded'**
  String get paymentStatusPartiallyRefunded;

  /// No description provided for @paymentStatusRefunded.
  ///
  /// In en, this message translates to:
  /// **'Refunded'**
  String get paymentStatusRefunded;

  /// No description provided for @paymentReturnedTitle.
  ///
  /// In en, this message translates to:
  /// **'Welcome back'**
  String get paymentReturnedTitle;

  /// No description provided for @paymentRedirectNotProof.
  ///
  /// In en, this message translates to:
  /// **'We confirm every payment with the provider before marking it paid.'**
  String get paymentRedirectNotProof;

  /// No description provided for @guestPayTitle.
  ///
  /// In en, this message translates to:
  /// **'Have someone else pay'**
  String get guestPayTitle;

  /// No description provided for @guestPayExplainer.
  ///
  /// In en, this message translates to:
  /// **'Share a link and anyone can pay this amount for you. They don\'t need a ShipTrip account.'**
  String get guestPayExplainer;

  /// No description provided for @guestPayCreateLink.
  ///
  /// In en, this message translates to:
  /// **'Create payment link'**
  String get guestPayCreateLink;

  /// No description provided for @guestPayLinkReady.
  ///
  /// In en, this message translates to:
  /// **'Link ready'**
  String get guestPayLinkReady;

  /// No description provided for @guestPayCopyLink.
  ///
  /// In en, this message translates to:
  /// **'Copy link'**
  String get guestPayCopyLink;

  /// No description provided for @guestPayShareLink.
  ///
  /// In en, this message translates to:
  /// **'Share link'**
  String get guestPayShareLink;

  /// No description provided for @guestPayRevoke.
  ///
  /// In en, this message translates to:
  /// **'Cancel this link'**
  String get guestPayRevoke;

  /// No description provided for @guestPayRevoked.
  ///
  /// In en, this message translates to:
  /// **'Link cancelled'**
  String get guestPayRevoked;

  /// No description provided for @guestPayExpiresAt.
  ///
  /// In en, this message translates to:
  /// **'Expires {when}'**
  String guestPayExpiresAt(String when);

  /// No description provided for @guestPayWarning.
  ///
  /// In en, this message translates to:
  /// **'Anyone with this link can pay this amount. They get nothing else — no access to your delivery, your chat, or your details.'**
  String get guestPayWarning;

  /// No description provided for @guestPayPayerEmail.
  ///
  /// In en, this message translates to:
  /// **'Your email for the receipt'**
  String get guestPayPayerEmail;

  /// No description provided for @guestPayPayerEmailHelp.
  ///
  /// In en, this message translates to:
  /// **'We use it for your payment receipt, failure updates and any refund communication. It does not create a ShipTrip account.'**
  String get guestPayPayerEmailHelp;

  /// No description provided for @guestPayAmountDue.
  ///
  /// In en, this message translates to:
  /// **'Amount due'**
  String get guestPayAmountDue;

  /// No description provided for @guestPayForDelivery.
  ///
  /// In en, this message translates to:
  /// **'Payment for a ShipTrip delivery'**
  String get guestPayForDelivery;

  /// No description provided for @guestPayThanksTitle.
  ///
  /// In en, this message translates to:
  /// **'Thank you'**
  String get guestPayThanksTitle;

  /// No description provided for @guestPayThanksBody.
  ///
  /// In en, this message translates to:
  /// **'The payment is confirmed. Nothing else is needed from you.'**
  String get guestPayThanksBody;

  /// No description provided for @guestPayInvalidTitle.
  ///
  /// In en, this message translates to:
  /// **'This link isn\'t valid'**
  String get guestPayInvalidTitle;

  /// No description provided for @guestPayInvalidBody.
  ///
  /// In en, this message translates to:
  /// **'It may have expired, been cancelled, or already been paid.'**
  String get guestPayInvalidBody;

  /// No description provided for @recipientTitle.
  ///
  /// In en, this message translates to:
  /// **'Who\'s receiving this?'**
  String get recipientTitle;

  /// No description provided for @recipientExplainer.
  ///
  /// In en, this message translates to:
  /// **'We email the delivery code to the recipient. The traveller can only complete the delivery if the recipient gives them that code.'**
  String get recipientExplainer;

  /// No description provided for @recipientName.
  ///
  /// In en, this message translates to:
  /// **'Recipient\'s name'**
  String get recipientName;

  /// No description provided for @recipientEmail.
  ///
  /// In en, this message translates to:
  /// **'Recipient\'s email'**
  String get recipientEmail;

  /// No description provided for @recipientEmailHelp.
  ///
  /// In en, this message translates to:
  /// **'The delivery code is sent here. Make sure it\'s right.'**
  String get recipientEmailHelp;

  /// No description provided for @recipientLanguage.
  ///
  /// In en, this message translates to:
  /// **'Recipient\'s language'**
  String get recipientLanguage;

  /// No description provided for @recipientLanguageHelp.
  ///
  /// In en, this message translates to:
  /// **'This is the language we\'ll use for the recipient\'s delivery email.'**
  String get recipientLanguageHelp;

  /// No description provided for @recipientPhone.
  ///
  /// In en, this message translates to:
  /// **'Phone (optional)'**
  String get recipientPhone;

  /// No description provided for @recipientNote.
  ///
  /// In en, this message translates to:
  /// **'Note for the recipient (optional)'**
  String get recipientNote;

  /// No description provided for @recipientSave.
  ///
  /// In en, this message translates to:
  /// **'Save recipient'**
  String get recipientSave;

  /// No description provided for @recipientSaved.
  ///
  /// In en, this message translates to:
  /// **'Recipient saved'**
  String get recipientSaved;

  /// No description provided for @recipientRequiredTitle.
  ///
  /// In en, this message translates to:
  /// **'Recipient needed'**
  String get recipientRequiredTitle;

  /// No description provided for @recipientRequiredBody.
  ///
  /// In en, this message translates to:
  /// **'Add the recipient before pickup so we can send them the delivery code.'**
  String get recipientRequiredBody;

  /// No description provided for @recipientRecordedForTraveler.
  ///
  /// In en, this message translates to:
  /// **'The sender has provided the recipient\'s details.'**
  String get recipientRecordedForTraveler;

  /// No description provided for @pickupSenderTitle.
  ///
  /// In en, this message translates to:
  /// **'Pickup code'**
  String get pickupSenderTitle;

  /// No description provided for @pickupSenderExplainer.
  ///
  /// In en, this message translates to:
  /// **'Give this code to the traveller only when you\'re physically handing over the parcel. It\'s how they confirm they have it.'**
  String get pickupSenderExplainer;

  /// No description provided for @pickupSenderReveal.
  ///
  /// In en, this message translates to:
  /// **'Show pickup code'**
  String get pickupSenderReveal;

  /// No description provided for @pickupSenderWarning.
  ///
  /// In en, this message translates to:
  /// **'Don\'t send this code in a message. Say it in person, at handover.'**
  String get pickupSenderWarning;

  /// No description provided for @pickupTravelerTitle.
  ///
  /// In en, this message translates to:
  /// **'Confirm pickup'**
  String get pickupTravelerTitle;

  /// No description provided for @pickupTravelerExplainer.
  ///
  /// In en, this message translates to:
  /// **'Ask the sender for their pickup code when they hand you the parcel.'**
  String get pickupTravelerExplainer;

  /// No description provided for @pickupCodeLabel.
  ///
  /// In en, this message translates to:
  /// **'Pickup code'**
  String get pickupCodeLabel;

  /// No description provided for @pickupConfirmAction.
  ///
  /// In en, this message translates to:
  /// **'Confirm pickup'**
  String get pickupConfirmAction;

  /// No description provided for @pickupConfirmedTitle.
  ///
  /// In en, this message translates to:
  /// **'Pickup confirmed'**
  String get pickupConfirmedTitle;

  /// No description provided for @pickupConfirmedBody.
  ///
  /// In en, this message translates to:
  /// **'You\'re carrying this parcel now.'**
  String get pickupConfirmedBody;

  /// No description provided for @pickupAwaitingTitle.
  ///
  /// In en, this message translates to:
  /// **'Waiting for pickup'**
  String get pickupAwaitingTitle;

  /// No description provided for @pickupAwaitingSenderBody.
  ///
  /// In en, this message translates to:
  /// **'The traveller will ask for your pickup code when you meet.'**
  String get pickupAwaitingSenderBody;

  /// No description provided for @pickupAwaitingTravelerBody.
  ///
  /// In en, this message translates to:
  /// **'Meet the sender and ask for their pickup code.'**
  String get pickupAwaitingTravelerBody;

  /// No description provided for @deliveryTravelerTitle.
  ///
  /// In en, this message translates to:
  /// **'Confirm delivery'**
  String get deliveryTravelerTitle;

  /// No description provided for @deliveryTravelerExplainer.
  ///
  /// In en, this message translates to:
  /// **'Ask the recipient for the code that was emailed to them.'**
  String get deliveryTravelerExplainer;

  /// No description provided for @deliveryCodeLabel.
  ///
  /// In en, this message translates to:
  /// **'Delivery code'**
  String get deliveryCodeLabel;

  /// No description provided for @deliveryConfirmAction.
  ///
  /// In en, this message translates to:
  /// **'Confirm delivery'**
  String get deliveryConfirmAction;

  /// No description provided for @deliveryConfirmedTitle.
  ///
  /// In en, this message translates to:
  /// **'Delivered'**
  String get deliveryConfirmedTitle;

  /// No description provided for @deliveryConfirmedTravelerBody.
  ///
  /// In en, this message translates to:
  /// **'Thank you. Your payout is being prepared.'**
  String get deliveryConfirmedTravelerBody;

  /// No description provided for @deliveryConfirmedSenderBody.
  ///
  /// In en, this message translates to:
  /// **'Your parcel arrived. Your payment stays protected for a little longer.'**
  String get deliveryConfirmedSenderBody;

  /// No description provided for @deliverySenderTitle.
  ///
  /// In en, this message translates to:
  /// **'Delivery code'**
  String get deliverySenderTitle;

  /// No description provided for @deliveryCodeLockedTitle.
  ///
  /// In en, this message translates to:
  /// **'Available in {countdown}'**
  String deliveryCodeLockedTitle(String countdown);

  /// No description provided for @deliveryCodeLockedBody.
  ///
  /// In en, this message translates to:
  /// **'For safety, the delivery code stays locked for 30 minutes after pickup. The recipient hasn\'t been emailed yet either.'**
  String get deliveryCodeLockedBody;

  /// No description provided for @deliveryCodeLockedWhy.
  ///
  /// In en, this message translates to:
  /// **'Why the wait?'**
  String get deliveryCodeLockedWhy;

  /// No description provided for @deliveryCodeLockedWhyBody.
  ///
  /// In en, this message translates to:
  /// **'The pause means a code can\'t be handed over at the same moment as the parcel. It\'s what stops a delivery being marked complete before it happens.'**
  String get deliveryCodeLockedWhyBody;

  /// No description provided for @deliveryCodeReadyTitle.
  ///
  /// In en, this message translates to:
  /// **'Delivery code ready'**
  String get deliveryCodeReadyTitle;

  /// No description provided for @deliveryCodeSentToRecipient.
  ///
  /// In en, this message translates to:
  /// **'We\'ve emailed the code to {recipient}.'**
  String deliveryCodeSentToRecipient(String recipient);

  /// No description provided for @deliveryCodeReveal.
  ///
  /// In en, this message translates to:
  /// **'Show delivery code'**
  String get deliveryCodeReveal;

  /// No description provided for @deliveryCodeSenderWarning.
  ///
  /// In en, this message translates to:
  /// **'The recipient gives this to the traveller at the door. Only share it with the recipient.'**
  String get deliveryCodeSenderWarning;

  /// No description provided for @deliveryCodeTravelerNever.
  ///
  /// In en, this message translates to:
  /// **'Only the recipient has this code. Ask them for it when you arrive.'**
  String get deliveryCodeTravelerNever;

  /// No description provided for @codeAttemptsRemaining.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 attempt left} other{{count} attempts left}}'**
  String codeAttemptsRemaining(int count);

  /// No description provided for @codeIncorrect.
  ///
  /// In en, this message translates to:
  /// **'That code isn\'t right'**
  String get codeIncorrect;

  /// No description provided for @codeLockedTitle.
  ///
  /// In en, this message translates to:
  /// **'Too many wrong attempts'**
  String get codeLockedTitle;

  /// No description provided for @codeLockedBody.
  ///
  /// In en, this message translates to:
  /// **'Try again {when}. If you\'re stuck, ask for a new code.'**
  String codeLockedBody(String when);

  /// No description provided for @codeRotate.
  ///
  /// In en, this message translates to:
  /// **'Get a new code'**
  String get codeRotate;

  /// No description provided for @codeRotated.
  ///
  /// In en, this message translates to:
  /// **'New code issued. The old one no longer works.'**
  String get codeRotated;

  /// No description provided for @codeRotateConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Issue a new code?'**
  String get codeRotateConfirmTitle;

  /// No description provided for @codeRotateConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'The code you already shared will stop working immediately.'**
  String get codeRotateConfirmBody;

  /// No description provided for @codeNotAvailableYet.
  ///
  /// In en, this message translates to:
  /// **'This code isn\'t available yet'**
  String get codeNotAvailableYet;

  /// No description provided for @codeCopyForReading.
  ///
  /// In en, this message translates to:
  /// **'Read the code out loud rather than sending it.'**
  String get codeCopyForReading;

  /// No description provided for @protectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Payment protected'**
  String get protectionTitle;

  /// No description provided for @protectionSenderBody.
  ///
  /// In en, this message translates to:
  /// **'Your payment is held until {when}. If something\'s wrong with the delivery, open a dispute before then.'**
  String protectionSenderBody(String when);

  /// No description provided for @protectionTravelerBody.
  ///
  /// In en, this message translates to:
  /// **'Delivered. Your payout is released after {when}, once the protection window closes.'**
  String protectionTravelerBody(String when);

  /// No description provided for @protectionEndsIn.
  ///
  /// In en, this message translates to:
  /// **'Ends in {countdown}'**
  String protectionEndsIn(String countdown);

  /// No description provided for @protectionEnded.
  ///
  /// In en, this message translates to:
  /// **'Protection window closed'**
  String get protectionEnded;

  /// No description provided for @protectionExplainerTitle.
  ///
  /// In en, this message translates to:
  /// **'What this means'**
  String get protectionExplainerTitle;

  /// No description provided for @protectionExplainerBody.
  ///
  /// In en, this message translates to:
  /// **'Funds are held pending delivery confirmation and a 48-hour window. This isn\'t a bank escrow account — it\'s ShipTrip holding the payment until both sides are settled.'**
  String get protectionExplainerBody;

  /// No description provided for @payoutTitle.
  ///
  /// In en, this message translates to:
  /// **'Payout'**
  String get payoutTitle;

  /// No description provided for @payoutStatusNotEligible.
  ///
  /// In en, this message translates to:
  /// **'Not yet'**
  String get payoutStatusNotEligible;

  /// No description provided for @payoutStatusEligible.
  ///
  /// In en, this message translates to:
  /// **'Ready'**
  String get payoutStatusEligible;

  /// No description provided for @payoutStatusScheduled.
  ///
  /// In en, this message translates to:
  /// **'Scheduled'**
  String get payoutStatusScheduled;

  /// No description provided for @payoutStatusProcessing.
  ///
  /// In en, this message translates to:
  /// **'On the way'**
  String get payoutStatusProcessing;

  /// No description provided for @payoutStatusPaid.
  ///
  /// In en, this message translates to:
  /// **'Paid'**
  String get payoutStatusPaid;

  /// No description provided for @payoutStatusFailed.
  ///
  /// In en, this message translates to:
  /// **'Failed'**
  String get payoutStatusFailed;

  /// No description provided for @payoutStatusCancelled.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get payoutStatusCancelled;

  /// No description provided for @payoutStatusFrozen.
  ///
  /// In en, this message translates to:
  /// **'On hold'**
  String get payoutStatusFrozen;

  /// No description provided for @payoutFrozenBody.
  ///
  /// In en, this message translates to:
  /// **'A dispute is open on this delivery, so the payout is on hold until it\'s resolved.'**
  String get payoutFrozenBody;

  /// No description provided for @payoutPendingTitle.
  ///
  /// In en, this message translates to:
  /// **'Payout pending'**
  String get payoutPendingTitle;

  /// No description provided for @payoutEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No payouts yet'**
  String get payoutEmptyTitle;

  /// No description provided for @payoutEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Complete a delivery and your earnings appear here.'**
  String get payoutEmptyBody;

  /// No description provided for @disputeOpenTitle.
  ///
  /// In en, this message translates to:
  /// **'Open a dispute'**
  String get disputeOpenTitle;

  /// No description provided for @disputeOpenExplainer.
  ///
  /// In en, this message translates to:
  /// **'Tell us what went wrong. Opening a dispute puts the traveller\'s payout on hold while we look into it.'**
  String get disputeOpenExplainer;

  /// No description provided for @disputeCategory.
  ///
  /// In en, this message translates to:
  /// **'What happened?'**
  String get disputeCategory;

  /// No description provided for @disputeDescription.
  ///
  /// In en, this message translates to:
  /// **'Describe the problem'**
  String get disputeDescription;

  /// No description provided for @disputeDescriptionHint.
  ///
  /// In en, this message translates to:
  /// **'What you expected, and what actually happened'**
  String get disputeDescriptionHint;

  /// No description provided for @disputeSubmit.
  ///
  /// In en, this message translates to:
  /// **'Open dispute'**
  String get disputeSubmit;

  /// No description provided for @disputeStatusOpen.
  ///
  /// In en, this message translates to:
  /// **'Open'**
  String get disputeStatusOpen;

  /// No description provided for @disputeStatusAwaitingEvidence.
  ///
  /// In en, this message translates to:
  /// **'Waiting for evidence'**
  String get disputeStatusAwaitingEvidence;

  /// No description provided for @disputeStatusUnderReview.
  ///
  /// In en, this message translates to:
  /// **'Being reviewed'**
  String get disputeStatusUnderReview;

  /// No description provided for @disputeStatusResolved.
  ///
  /// In en, this message translates to:
  /// **'Resolved'**
  String get disputeStatusResolved;

  /// No description provided for @disputeStatusClosed.
  ///
  /// In en, this message translates to:
  /// **'Closed'**
  String get disputeStatusClosed;

  /// No description provided for @disputeEvidenceTitle.
  ///
  /// In en, this message translates to:
  /// **'Evidence'**
  String get disputeEvidenceTitle;

  /// No description provided for @disputeEvidenceExplainer.
  ///
  /// In en, this message translates to:
  /// **'Photos and video help us understand what happened.'**
  String get disputeEvidenceExplainer;

  /// No description provided for @disputeAddPhoto.
  ///
  /// In en, this message translates to:
  /// **'Add photo'**
  String get disputeAddPhoto;

  /// No description provided for @disputeAddVideo.
  ///
  /// In en, this message translates to:
  /// **'Add video'**
  String get disputeAddVideo;

  /// No description provided for @disputeAddNote.
  ///
  /// In en, this message translates to:
  /// **'Add a note'**
  String get disputeAddNote;

  /// No description provided for @disputeUploading.
  ///
  /// In en, this message translates to:
  /// **'Uploading… {percent}%'**
  String disputeUploading(int percent);

  /// No description provided for @disputeUploadFailed.
  ///
  /// In en, this message translates to:
  /// **'Upload failed'**
  String get disputeUploadFailed;

  /// No description provided for @disputeUploadRetry.
  ///
  /// In en, this message translates to:
  /// **'Retry upload'**
  String get disputeUploadRetry;

  /// No description provided for @disputeFileTooLarge.
  ///
  /// In en, this message translates to:
  /// **'That file is too large. The limit is {limit}.'**
  String disputeFileTooLarge(String limit);

  /// No description provided for @disputeFileTypeNotAllowed.
  ///
  /// In en, this message translates to:
  /// **'That file type isn\'t supported. Use a JPEG, PNG, WebP, MP4 or MOV.'**
  String get disputeFileTypeNotAllowed;

  /// No description provided for @disputeEvidenceLimitReached.
  ///
  /// In en, this message translates to:
  /// **'You\'ve added the maximum number of items.'**
  String get disputeEvidenceLimitReached;

  /// No description provided for @disputeResolutionTitle.
  ///
  /// In en, this message translates to:
  /// **'Outcome'**
  String get disputeResolutionTitle;

  /// No description provided for @disputeResolutionRefunded.
  ///
  /// In en, this message translates to:
  /// **'Refunded to the sender'**
  String get disputeResolutionRefunded;

  /// No description provided for @disputeResolutionTravelerPaid.
  ///
  /// In en, this message translates to:
  /// **'Paid to the traveller'**
  String get disputeResolutionTravelerPaid;

  /// No description provided for @disputeResolutionPartial.
  ///
  /// In en, this message translates to:
  /// **'Split between both sides'**
  String get disputeResolutionPartial;

  /// No description provided for @disputeWindowClosedTitle.
  ///
  /// In en, this message translates to:
  /// **'The dispute window has closed'**
  String get disputeWindowClosedTitle;

  /// No description provided for @disputeWindowClosedBody.
  ///
  /// In en, this message translates to:
  /// **'Disputes can be opened for 48 hours after delivery. Contact support if you still need help.'**
  String get disputeWindowClosedBody;

  /// No description provided for @disputeEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No disputes'**
  String get disputeEmptyTitle;

  /// No description provided for @disputeEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Nothing is under dispute.'**
  String get disputeEmptyBody;

  /// No description provided for @cancelTitle.
  ///
  /// In en, this message translates to:
  /// **'Cancel this delivery'**
  String get cancelTitle;

  /// No description provided for @cancelConfirmAction.
  ///
  /// In en, this message translates to:
  /// **'Cancel delivery'**
  String get cancelConfirmAction;

  /// No description provided for @cancelKeepAction.
  ///
  /// In en, this message translates to:
  /// **'Keep it'**
  String get cancelKeepAction;

  /// No description provided for @cancelFullRefund.
  ///
  /// In en, this message translates to:
  /// **'You\'ll be refunded in full.'**
  String get cancelFullRefund;

  /// No description provided for @cancelWithCompensation.
  ///
  /// In en, this message translates to:
  /// **'Because it\'s close to pickup, the traveller is compensated for holding the space.'**
  String get cancelWithCompensation;

  /// No description provided for @cancelNotAllowedTitle.
  ///
  /// In en, this message translates to:
  /// **'This can\'t be cancelled here'**
  String get cancelNotAllowedTitle;

  /// No description provided for @cancelAfterPickupBody.
  ///
  /// In en, this message translates to:
  /// **'The parcel has already been picked up. If something\'s wrong, open a dispute instead.'**
  String get cancelAfterPickupBody;

  /// No description provided for @cancelOutcomeTitle.
  ///
  /// In en, this message translates to:
  /// **'What happens'**
  String get cancelOutcomeTitle;

  /// No description provided for @cancelCancelledTitle.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get cancelCancelledTitle;

  /// No description provided for @cancelRefundOnWay.
  ///
  /// In en, this message translates to:
  /// **'Your refund is on the way.'**
  String get cancelRefundOnWay;

  /// No description provided for @ratingTitle.
  ///
  /// In en, this message translates to:
  /// **'How did it go?'**
  String get ratingTitle;

  /// No description provided for @ratingSenderPrompt.
  ///
  /// In en, this message translates to:
  /// **'Rate the traveller'**
  String get ratingSenderPrompt;

  /// No description provided for @ratingTravelerPrompt.
  ///
  /// In en, this message translates to:
  /// **'Rate the sender'**
  String get ratingTravelerPrompt;

  /// No description provided for @ratingScoreLabel.
  ///
  /// In en, this message translates to:
  /// **'{score} out of 5'**
  String ratingScoreLabel(int score);

  /// No description provided for @ratingTagsLabel.
  ///
  /// In en, this message translates to:
  /// **'What stood out?'**
  String get ratingTagsLabel;

  /// No description provided for @ratingCommentLabel.
  ///
  /// In en, this message translates to:
  /// **'Anything else? (optional)'**
  String get ratingCommentLabel;

  /// No description provided for @ratingSubmit.
  ///
  /// In en, this message translates to:
  /// **'Submit rating'**
  String get ratingSubmit;

  /// No description provided for @ratingSubmitted.
  ///
  /// In en, this message translates to:
  /// **'Thanks for the rating'**
  String get ratingSubmitted;

  /// No description provided for @ratingWaitingForOther.
  ///
  /// In en, this message translates to:
  /// **'Your rating is saved. You\'ll see theirs once they\'ve rated you too.'**
  String get ratingWaitingForOther;

  /// No description provided for @ratingHiddenUntilBoth.
  ///
  /// In en, this message translates to:
  /// **'Hidden until you both rate'**
  String get ratingHiddenUntilBoth;

  /// No description provided for @ratingWindowClosed.
  ///
  /// In en, this message translates to:
  /// **'The rating window has closed.'**
  String get ratingWindowClosed;

  /// No description provided for @ratingEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No ratings yet'**
  String get ratingEmptyTitle;

  /// No description provided for @ratingEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Ratings appear after a delivery is completed.'**
  String get ratingEmptyBody;

  /// No description provided for @boostTitle.
  ///
  /// In en, this message translates to:
  /// **'Boost this request'**
  String get boostTitle;

  /// No description provided for @boostExplainer.
  ///
  /// In en, this message translates to:
  /// **'A boost puts your request higher in the list for travellers who already match it.'**
  String get boostExplainer;

  /// No description provided for @boostDoesNotGuarantee.
  ///
  /// In en, this message translates to:
  /// **'It doesn\'t change who you match with, and it doesn\'t guarantee a delivery.'**
  String get boostDoesNotGuarantee;

  /// No description provided for @boostChoosePackage.
  ///
  /// In en, this message translates to:
  /// **'Choose a boost'**
  String get boostChoosePackage;

  /// No description provided for @boostDuration.
  ///
  /// In en, this message translates to:
  /// **'{hours, plural, =1{1 hour} other{{hours} hours}}'**
  String boostDuration(int hours);

  /// No description provided for @boostDurationDays.
  ///
  /// In en, this message translates to:
  /// **'{days, plural, =1{1 day} other{{days} days}}'**
  String boostDurationDays(int days);

  /// No description provided for @boostActive.
  ///
  /// In en, this message translates to:
  /// **'Boost active'**
  String get boostActive;

  /// No description provided for @boostActiveUntil.
  ///
  /// In en, this message translates to:
  /// **'Active until {when}'**
  String boostActiveUntil(String when);

  /// No description provided for @boostPendingPayment.
  ///
  /// In en, this message translates to:
  /// **'Waiting for payment'**
  String get boostPendingPayment;

  /// No description provided for @boostExpired.
  ///
  /// In en, this message translates to:
  /// **'Boost ended'**
  String get boostExpired;

  /// No description provided for @boostPurchase.
  ///
  /// In en, this message translates to:
  /// **'Boost for {amount}'**
  String boostPurchase(String amount);

  /// No description provided for @boostNotEligible.
  ///
  /// In en, this message translates to:
  /// **'This request can\'t be boosted right now.'**
  String get boostNotEligible;

  /// No description provided for @chatTitle.
  ///
  /// In en, this message translates to:
  /// **'Chat'**
  String get chatTitle;

  /// No description provided for @chatEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No conversations'**
  String get chatEmptyTitle;

  /// No description provided for @chatEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Chat opens once a delivery is paid for.'**
  String get chatEmptyBody;

  /// No description provided for @chatThreadEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'Say hello'**
  String get chatThreadEmptyTitle;

  /// No description provided for @chatThreadEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Arrange where and when to meet.'**
  String get chatThreadEmptyBody;

  /// No description provided for @chatComposerHint.
  ///
  /// In en, this message translates to:
  /// **'Write a message'**
  String get chatComposerHint;

  /// No description provided for @chatSend.
  ///
  /// In en, this message translates to:
  /// **'Send'**
  String get chatSend;

  /// No description provided for @chatSendFailed.
  ///
  /// In en, this message translates to:
  /// **'Not sent'**
  String get chatSendFailed;

  /// No description provided for @chatRetrySend.
  ///
  /// In en, this message translates to:
  /// **'Tap to retry'**
  String get chatRetrySend;

  /// No description provided for @chatSending.
  ///
  /// In en, this message translates to:
  /// **'Sending…'**
  String get chatSending;

  /// No description provided for @chatClosedTitle.
  ///
  /// In en, this message translates to:
  /// **'This conversation is closed'**
  String get chatClosedTitle;

  /// No description provided for @chatClosedBody.
  ///
  /// In en, this message translates to:
  /// **'You can still read it, but new messages aren\'t possible.'**
  String get chatClosedBody;

  /// No description provided for @chatUnavailableTitle.
  ///
  /// In en, this message translates to:
  /// **'Chat isn\'t available yet'**
  String get chatUnavailableTitle;

  /// No description provided for @chatUnavailableBody.
  ///
  /// In en, this message translates to:
  /// **'Chat opens for this delivery once payment is confirmed.'**
  String get chatUnavailableBody;

  /// No description provided for @chatNeverShareCodes.
  ///
  /// In en, this message translates to:
  /// **'Never send a pickup or delivery code in chat.'**
  String get chatNeverShareCodes;

  /// No description provided for @notificationsTitle.
  ///
  /// In en, this message translates to:
  /// **'Notifications'**
  String get notificationsTitle;

  /// No description provided for @notificationsMarkAllRead.
  ///
  /// In en, this message translates to:
  /// **'Mark all as read'**
  String get notificationsMarkAllRead;

  /// No description provided for @notificationsEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'Nothing new'**
  String get notificationsEmptyTitle;

  /// No description provided for @notificationsEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Offers, payments and delivery updates show up here.'**
  String get notificationsEmptyBody;

  /// No description provided for @notificationsUnreadCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =0{No unread} =1{1 unread} other{{count} unread}}'**
  String notificationsUnreadCount(int count);

  /// No description provided for @profileTitle.
  ///
  /// In en, this message translates to:
  /// **'Profile'**
  String get profileTitle;

  /// No description provided for @profileAccount.
  ///
  /// In en, this message translates to:
  /// **'Account'**
  String get profileAccount;

  /// No description provided for @profilePassportStamp.
  ///
  /// In en, this message translates to:
  /// **'SHIPTRIP · MEMBER'**
  String get profilePassportStamp;

  /// No description provided for @profileCompletedDeliveries.
  ///
  /// In en, this message translates to:
  /// **'Completed'**
  String get profileCompletedDeliveries;

  /// No description provided for @profileRecentRating.
  ///
  /// In en, this message translates to:
  /// **'Recent rating'**
  String get profileRecentRating;

  /// No description provided for @profileRoles.
  ///
  /// In en, this message translates to:
  /// **'What you do'**
  String get profileRoles;

  /// No description provided for @profileVerification.
  ///
  /// In en, this message translates to:
  /// **'Verification'**
  String get profileVerification;

  /// No description provided for @profileRatings.
  ///
  /// In en, this message translates to:
  /// **'Ratings'**
  String get profileRatings;

  /// No description provided for @profilePayments.
  ///
  /// In en, this message translates to:
  /// **'Payments and payouts'**
  String get profilePayments;

  /// No description provided for @profileNotificationSettings.
  ///
  /// In en, this message translates to:
  /// **'Notifications'**
  String get profileNotificationSettings;

  /// No description provided for @profileLanguage.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get profileLanguage;

  /// No description provided for @profileLanguageSystem.
  ///
  /// In en, this message translates to:
  /// **'Device language'**
  String get profileLanguageSystem;

  /// No description provided for @profileAppLanguage.
  ///
  /// In en, this message translates to:
  /// **'App language'**
  String get profileAppLanguage;

  /// No description provided for @profileAppLanguageHelp.
  ///
  /// In en, this message translates to:
  /// **'What you read inside ShipTrip. Stored on this phone.'**
  String get profileAppLanguageHelp;

  /// No description provided for @profileEmailLanguage.
  ///
  /// In en, this message translates to:
  /// **'Email language'**
  String get profileEmailLanguage;

  /// No description provided for @profileEmailLanguageHelp.
  ///
  /// In en, this message translates to:
  /// **'What we write to you in — payments, verification, deliveries, disputes and account security. Saved to your account.'**
  String get profileEmailLanguageHelp;

  /// No description provided for @profileEmailLanguageSaved.
  ///
  /// In en, this message translates to:
  /// **'Email language updated'**
  String get profileEmailLanguageSaved;

  /// No description provided for @profileSupport.
  ///
  /// In en, this message translates to:
  /// **'Help and support'**
  String get profileSupport;

  /// No description provided for @profileTerms.
  ///
  /// In en, this message translates to:
  /// **'Terms of service'**
  String get profileTerms;

  /// No description provided for @profilePrivacy.
  ///
  /// In en, this message translates to:
  /// **'Privacy policy'**
  String get profilePrivacy;

  /// No description provided for @profileAppearance.
  ///
  /// In en, this message translates to:
  /// **'Appearance'**
  String get profileAppearance;

  /// No description provided for @profileAppearanceSystem.
  ///
  /// In en, this message translates to:
  /// **'Match device'**
  String get profileAppearanceSystem;

  /// No description provided for @profileAppearanceLight.
  ///
  /// In en, this message translates to:
  /// **'Light'**
  String get profileAppearanceLight;

  /// No description provided for @profileAppearanceDark.
  ///
  /// In en, this message translates to:
  /// **'Dark'**
  String get profileAppearanceDark;

  /// No description provided for @profileEmailVerified.
  ///
  /// In en, this message translates to:
  /// **'Email verified'**
  String get profileEmailVerified;

  /// No description provided for @profileEmailUnverified.
  ///
  /// In en, this message translates to:
  /// **'Email not verified'**
  String get profileEmailUnverified;

  /// No description provided for @profileMemberSince.
  ///
  /// In en, this message translates to:
  /// **'With ShipTrip since {date}'**
  String profileMemberSince(String date);

  /// No description provided for @profileVersion.
  ///
  /// In en, this message translates to:
  /// **'Version {version}'**
  String profileVersion(String version);

  /// No description provided for @locationSearchTitle.
  ///
  /// In en, this message translates to:
  /// **'Choose a place'**
  String get locationSearchTitle;

  /// No description provided for @locationSearchHint.
  ///
  /// In en, this message translates to:
  /// **'Search localities and airports'**
  String get locationSearchHint;

  /// No description provided for @locationSelectCountry.
  ///
  /// In en, this message translates to:
  /// **'Choose a country first'**
  String get locationSelectCountry;

  /// No description provided for @locationSearchStart.
  ///
  /// In en, this message translates to:
  /// **'Type a locality, municipality, commune, or airport'**
  String get locationSearchStart;

  /// No description provided for @placeTierWilaya.
  ///
  /// In en, this message translates to:
  /// **'{name} Wilaya'**
  String placeTierWilaya(String name);

  /// No description provided for @placeTierDepartment.
  ///
  /// In en, this message translates to:
  /// **'{name} department'**
  String placeTierDepartment(String name);

  /// No description provided for @placeTierRegion.
  ///
  /// In en, this message translates to:
  /// **'{name} region'**
  String placeTierRegion(String name);

  /// No description provided for @placeTierProvince.
  ///
  /// In en, this message translates to:
  /// **'{name} province'**
  String placeTierProvince(String name);

  /// No description provided for @placeTierAutonomousCommunity.
  ///
  /// In en, this message translates to:
  /// **'{name} autonomous community'**
  String placeTierAutonomousCommunity(String name);

  /// No description provided for @placeTierState.
  ///
  /// In en, this message translates to:
  /// **'{name} state'**
  String placeTierState(String name);

  /// No description provided for @placeTierDistrict.
  ///
  /// In en, this message translates to:
  /// **'{name} district'**
  String placeTierDistrict(String name);

  /// No description provided for @locationTypeAirport.
  ///
  /// In en, this message translates to:
  /// **'Airport'**
  String get locationTypeAirport;

  /// No description provided for @locationTypeLocality.
  ///
  /// In en, this message translates to:
  /// **'Locality'**
  String get locationTypeLocality;

  /// No description provided for @locationUseMap.
  ///
  /// In en, this message translates to:
  /// **'Choose on map'**
  String get locationUseMap;

  /// No description provided for @locationConfirmPoint.
  ///
  /// In en, this message translates to:
  /// **'Use this point'**
  String get locationConfirmPoint;

  /// No description provided for @locationSaved.
  ///
  /// In en, this message translates to:
  /// **'Saved places'**
  String get locationSaved;

  /// No description provided for @locationPrivacyBeforeFunding.
  ///
  /// In en, this message translates to:
  /// **'Only the city is shared until the delivery is paid for.'**
  String get locationPrivacyBeforeFunding;

  /// No description provided for @locationPrivacyAfterFunding.
  ///
  /// In en, this message translates to:
  /// **'Full address shared with the traveller.'**
  String get locationPrivacyAfterFunding;

  /// No description provided for @locationHiddenUntilFunded.
  ///
  /// In en, this message translates to:
  /// **'Exact address available after payment'**
  String get locationHiddenUntilFunded;

  /// No description provided for @locationSearchEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No results'**
  String get locationSearchEmptyTitle;

  /// No description provided for @locationSearchEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Try a different spelling, or pick the point on the map.'**
  String get locationSearchEmptyBody;

  /// No description provided for @countryNameAlgeria.
  ///
  /// In en, this message translates to:
  /// **'Algeria'**
  String get countryNameAlgeria;

  /// No description provided for @countryNameFrance.
  ///
  /// In en, this message translates to:
  /// **'France'**
  String get countryNameFrance;

  /// No description provided for @countryNameSpain.
  ///
  /// In en, this message translates to:
  /// **'Spain'**
  String get countryNameSpain;

  /// No description provided for @countryNameGermany.
  ///
  /// In en, this message translates to:
  /// **'Germany'**
  String get countryNameGermany;

  /// No description provided for @locationCountryQuestion.
  ///
  /// In en, this message translates to:
  /// **'Which country?'**
  String get locationCountryQuestion;

  /// No description provided for @locationChangeCountry.
  ///
  /// In en, this message translates to:
  /// **'Change'**
  String get locationChangeCountry;

  /// No description provided for @locationCountryStep.
  ///
  /// In en, this message translates to:
  /// **'Country'**
  String get locationCountryStep;

  /// No description provided for @locationCountriesUnavailable.
  ///
  /// In en, this message translates to:
  /// **'No countries are available right now.'**
  String get locationCountriesUnavailable;

  /// No description provided for @locationSelectCountryBody.
  ///
  /// In en, this message translates to:
  /// **'Pick a country above, then search for the town, commune or airport.'**
  String get locationSelectCountryBody;

  /// No description provided for @locationSearchReadyTitle.
  ///
  /// In en, this message translates to:
  /// **'Ready when you are'**
  String get locationSearchReadyTitle;

  /// No description provided for @locationSearchHintAirports.
  ///
  /// In en, this message translates to:
  /// **'Search airports'**
  String get locationSearchHintAirports;

  /// No description provided for @locationSearchStartAirports.
  ///
  /// In en, this message translates to:
  /// **'Type an airport name or its three-letter code.'**
  String get locationSearchStartAirports;

  /// No description provided for @locationAirportsOnly.
  ///
  /// In en, this message translates to:
  /// **'This leg flies, so only airports are offered.'**
  String get locationAirportsOnly;

  /// No description provided for @locationCurrentSelection.
  ///
  /// In en, this message translates to:
  /// **'Currently selected'**
  String get locationCurrentSelection;

  /// No description provided for @locationSearchNoMatch.
  ///
  /// In en, this message translates to:
  /// **'Nothing here matches “{query}”. Check the spelling, or try the nearest larger town.'**
  String locationSearchNoMatch(String query);

  /// No description provided for @locationSearchNoMatchAirports.
  ///
  /// In en, this message translates to:
  /// **'No airport here matches “{query}”. Try the city name, or the three-letter code.'**
  String locationSearchNoMatchAirports(String query);

  /// No description provided for @locationPreferredExplainer.
  ///
  /// In en, this message translates to:
  /// **'Travellers are matched on {place}. A preferred point only says where you would rather meet inside it.'**
  String locationPreferredExplainer(String place);

  /// No description provided for @locationPreferredFlexibleHint.
  ///
  /// In en, this message translates to:
  /// **'No exact point needed'**
  String get locationPreferredFlexibleHint;

  /// No description provided for @locationAddPreferredPoint.
  ///
  /// In en, this message translates to:
  /// **'Add a preferred point'**
  String get locationAddPreferredPoint;

  /// No description provided for @locationChangePreferredPoint.
  ///
  /// In en, this message translates to:
  /// **'Change point'**
  String get locationChangePreferredPoint;

  /// No description provided for @locationRemovePreferredPoint.
  ///
  /// In en, this message translates to:
  /// **'Remove preferred point'**
  String get locationRemovePreferredPoint;

  /// No description provided for @locationPreferredRemoved.
  ///
  /// In en, this message translates to:
  /// **'Preferred point removed.'**
  String get locationPreferredRemoved;

  /// No description provided for @locationPreferredClearedByPlace.
  ///
  /// In en, this message translates to:
  /// **'Preferred point removed — it belonged to the place you just changed.'**
  String get locationPreferredClearedByPlace;

  /// No description provided for @locationDecideLater.
  ///
  /// In en, this message translates to:
  /// **'Decide later'**
  String get locationDecideLater;

  /// No description provided for @locationPointInside.
  ///
  /// In en, this message translates to:
  /// **'Point inside'**
  String get locationPointInside;

  /// No description provided for @locationDropPinHelpIn.
  ///
  /// In en, this message translates to:
  /// **'Move the map until the crosshair sits where you mean inside {place}, then confirm.'**
  String locationDropPinHelpIn(String place);

  /// No description provided for @locationNoCentre.
  ///
  /// In en, this message translates to:
  /// **'We have no centre on file for {place}, so the map starts wide. Move it to the right area before you confirm.'**
  String locationNoCentre(String place);

  /// No description provided for @mapAttribution.
  ///
  /// In en, this message translates to:
  /// **'Map data {attribution}'**
  String mapAttribution(String attribution);

  /// No description provided for @locationYourPlaces.
  ///
  /// In en, this message translates to:
  /// **'Your places'**
  String get locationYourPlaces;

  /// No description provided for @locationEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No saved places yet'**
  String get locationEmptyTitle;

  /// No description provided for @locationEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Drop a pin on the map to save your first address.'**
  String get locationEmptyBody;

  /// No description provided for @locationDropPinHelp.
  ///
  /// In en, this message translates to:
  /// **'Move the map until the crosshair sits where you mean, then confirm.'**
  String get locationDropPinHelp;

  /// No description provided for @locationNamePlaceTitle.
  ///
  /// In en, this message translates to:
  /// **'Name this place'**
  String get locationNamePlaceTitle;

  /// No description provided for @locationNamePlaceBody.
  ///
  /// In en, this message translates to:
  /// **'Only you see the label. Other people see the city until a delivery is paid for.'**
  String get locationNamePlaceBody;

  /// No description provided for @locationLabelField.
  ///
  /// In en, this message translates to:
  /// **'Label'**
  String get locationLabelField;

  /// No description provided for @locationLabelHint.
  ///
  /// In en, this message translates to:
  /// **'Home, Mum\'s place, the office'**
  String get locationLabelHint;

  /// No description provided for @locationSavePlace.
  ///
  /// In en, this message translates to:
  /// **'Save this place'**
  String get locationSavePlace;

  /// No description provided for @locationPlaceSaved.
  ///
  /// In en, this message translates to:
  /// **'Place saved.'**
  String get locationPlaceSaved;

  /// No description provided for @locationPreferredMeetingPoint.
  ///
  /// In en, this message translates to:
  /// **'Preferred meeting point'**
  String get locationPreferredMeetingPoint;

  /// No description provided for @locationPreferredOptional.
  ///
  /// In en, this message translates to:
  /// **'Optional'**
  String get locationPreferredOptional;

  /// No description provided for @locationChoosePreferredPoint.
  ///
  /// In en, this message translates to:
  /// **'Choose on map'**
  String get locationChoosePreferredPoint;

  /// No description provided for @locationFlexibleWithin.
  ///
  /// In en, this message translates to:
  /// **'Flexible within {place}'**
  String locationFlexibleWithin(String place);

  /// No description provided for @locationPreferredValidation.
  ///
  /// In en, this message translates to:
  /// **'The map provider will verify that this point belongs to {place}.'**
  String locationPreferredValidation(String place);

  /// No description provided for @mapZoomIn.
  ///
  /// In en, this message translates to:
  /// **'Zoom in'**
  String get mapZoomIn;

  /// No description provided for @mapZoomOut.
  ///
  /// In en, this message translates to:
  /// **'Zoom out'**
  String get mapZoomOut;

  /// No description provided for @timelineTitle.
  ///
  /// In en, this message translates to:
  /// **'Progress'**
  String get timelineTitle;

  /// No description provided for @timelineWaitingOnYou.
  ///
  /// In en, this message translates to:
  /// **'Waiting on you'**
  String get timelineWaitingOnYou;

  /// No description provided for @timelineWaitingOnThem.
  ///
  /// In en, this message translates to:
  /// **'Waiting on them'**
  String get timelineWaitingOnThem;

  /// No description provided for @timelineDone.
  ///
  /// In en, this message translates to:
  /// **'Done'**
  String get timelineDone;

  /// No description provided for @timelineUpcoming.
  ///
  /// In en, this message translates to:
  /// **'Next'**
  String get timelineUpcoming;

  /// No description provided for @a11yStatusPrefix.
  ///
  /// In en, this message translates to:
  /// **'Status'**
  String get a11yStatusPrefix;

  /// No description provided for @a11yMoneyAmount.
  ///
  /// In en, this message translates to:
  /// **'Amount'**
  String get a11yMoneyAmount;

  /// No description provided for @a11yRequiredField.
  ///
  /// In en, this message translates to:
  /// **'Required'**
  String get a11yRequiredField;

  /// No description provided for @a11yCloseSheet.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get a11yCloseSheet;

  /// No description provided for @a11yBack.
  ///
  /// In en, this message translates to:
  /// **'Go back'**
  String get a11yBack;

  /// No description provided for @a11yLoadingContent.
  ///
  /// In en, this message translates to:
  /// **'Loading content'**
  String get a11yLoadingContent;

  /// No description provided for @a11yImageOfParcel.
  ///
  /// In en, this message translates to:
  /// **'Photo of the parcel'**
  String get a11yImageOfParcel;

  /// No description provided for @a11ySelected.
  ///
  /// In en, this message translates to:
  /// **'Selected'**
  String get a11ySelected;

  /// No description provided for @a11yNotSelected.
  ///
  /// In en, this message translates to:
  /// **'Not selected'**
  String get a11yNotSelected;

  /// No description provided for @a11yExpandSection.
  ///
  /// In en, this message translates to:
  /// **'Expand'**
  String get a11yExpandSection;

  /// No description provided for @a11yCollapseSection.
  ///
  /// In en, this message translates to:
  /// **'Collapse'**
  String get a11yCollapseSection;

  /// No description provided for @disputeCategoryNotDelivered.
  ///
  /// In en, this message translates to:
  /// **'Never arrived'**
  String get disputeCategoryNotDelivered;

  /// No description provided for @disputeCategoryDamaged.
  ///
  /// In en, this message translates to:
  /// **'Arrived damaged'**
  String get disputeCategoryDamaged;

  /// No description provided for @disputeCategoryWrongItem.
  ///
  /// In en, this message translates to:
  /// **'Wrong item'**
  String get disputeCategoryWrongItem;

  /// No description provided for @disputeCategoryLate.
  ///
  /// In en, this message translates to:
  /// **'Arrived too late'**
  String get disputeCategoryLate;

  /// No description provided for @disputeCategoryNoShow.
  ///
  /// In en, this message translates to:
  /// **'The other person didn\'t show up'**
  String get disputeCategoryNoShow;

  /// No description provided for @disputeCategoryPayment.
  ///
  /// In en, this message translates to:
  /// **'Something is wrong with the money'**
  String get disputeCategoryPayment;

  /// No description provided for @disputeCategoryOther.
  ///
  /// In en, this message translates to:
  /// **'Something else'**
  String get disputeCategoryOther;

  /// A weight with its unit.
  ///
  /// In en, this message translates to:
  /// **'{value} kg'**
  String unitWeightKg(String value);

  /// Parcel dimensions.
  ///
  /// In en, this message translates to:
  /// **'{length} × {width} × {height} cm'**
  String unitDimensions(String length, String width, String height);

  /// Remaining declared capacity on a leg.
  ///
  /// In en, this message translates to:
  /// **'{value} kg free'**
  String unitCapacityKg(String value);

  /// A duration in hours and minutes.
  ///
  /// In en, this message translates to:
  /// **'{hours}h {minutes}m'**
  String unitDurationHm(int hours, int minutes);

  /// A duration under an hour.
  ///
  /// In en, this message translates to:
  /// **'{minutes}m'**
  String unitDurationM(int minutes);

  /// Upper-bounded distance band.
  ///
  /// In en, this message translates to:
  /// **'Under {max} km'**
  String distanceUnder(String max);

  /// A bounded distance band.
  ///
  /// In en, this message translates to:
  /// **'{min}–{max} km'**
  String distanceBetween(String min, String max);

  /// Lower-bounded distance band.
  ///
  /// In en, this message translates to:
  /// **'Over {min} km'**
  String distanceOver(String min);

  /// An exact distance, which the server only releases to the owner of a journey.
  ///
  /// In en, this message translates to:
  /// **'{value} km'**
  String unitDistanceKm(String value);

  /// No description provided for @weightChargeableVolumetric.
  ///
  /// In en, this message translates to:
  /// **'Priced on size, not weight'**
  String get weightChargeableVolumetric;

  /// No description provided for @weightChargeableActual.
  ///
  /// In en, this message translates to:
  /// **'Priced on weight'**
  String get weightChargeableActual;

  /// No description provided for @homeVerifyIdentityTitle.
  ///
  /// In en, this message translates to:
  /// **'Verify your identity'**
  String get homeVerifyIdentityTitle;

  /// No description provided for @homeVerifyIdentityBody.
  ///
  /// In en, this message translates to:
  /// **'Travellers must be verified before a journey can go live.'**
  String get homeVerifyIdentityBody;

  /// No description provided for @homeAttentionOfferAwaiting.
  ///
  /// In en, this message translates to:
  /// **'An offer is waiting for your answer'**
  String get homeAttentionOfferAwaiting;

  /// No description provided for @homeAttentionFunding.
  ///
  /// In en, this message translates to:
  /// **'Pay to confirm this delivery'**
  String get homeAttentionFunding;

  /// No description provided for @homeAttentionRecipient.
  ///
  /// In en, this message translates to:
  /// **'Add who receives the parcel'**
  String get homeAttentionRecipient;

  /// No description provided for @homeAttentionRevealPickup.
  ///
  /// In en, this message translates to:
  /// **'Show the pickup code to your traveller'**
  String get homeAttentionRevealPickup;

  /// No description provided for @homeAttentionSubmitPickup.
  ///
  /// In en, this message translates to:
  /// **'Enter the pickup code'**
  String get homeAttentionSubmitPickup;

  /// No description provided for @homeAttentionRevealDelivery.
  ///
  /// In en, this message translates to:
  /// **'The delivery code is ready'**
  String get homeAttentionRevealDelivery;

  /// No description provided for @homeAttentionSubmitDelivery.
  ///
  /// In en, this message translates to:
  /// **'Enter the delivery code'**
  String get homeAttentionSubmitDelivery;

  /// No description provided for @homeAttentionRating.
  ///
  /// In en, this message translates to:
  /// **'Rate this delivery'**
  String get homeAttentionRating;

  /// No description provided for @homeOpenAction.
  ///
  /// In en, this message translates to:
  /// **'Open'**
  String get homeOpenAction;

  /// No description provided for @deliveriesTabAll.
  ///
  /// In en, this message translates to:
  /// **'All'**
  String get deliveriesTabAll;

  /// No description provided for @deliveryCardSending.
  ///
  /// In en, this message translates to:
  /// **'Sending'**
  String get deliveryCardSending;

  /// No description provided for @deliveryCardCarrying.
  ///
  /// In en, this message translates to:
  /// **'Carrying'**
  String get deliveryCardCarrying;

  /// Names the counterparty on a delivery card.
  ///
  /// In en, this message translates to:
  /// **'with {name}'**
  String deliveryCardWith(String name);

  /// No description provided for @journeyLegCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 leg} other{{count} legs}}'**
  String journeyLegCount(int count);

  /// No description provided for @journeyProofNeeded.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 flight needs proof} other{{count} flights need proof}}'**
  String journeyProofNeeded(int count);

  /// No description provided for @requestOffersCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =0{No offers yet} =1{1 offer} other{{count} offers}}'**
  String requestOffersCount(int count);

  /// No description provided for @onboardingSendTitle.
  ///
  /// In en, this message translates to:
  /// **'Send something home'**
  String get onboardingSendTitle;

  /// No description provided for @onboardingSendBody.
  ///
  /// In en, this message translates to:
  /// **'Post what you want delivered. Travellers already heading that way can carry it, and you agree the price between you.'**
  String get onboardingSendBody;

  /// No description provided for @onboardingCarryTitle.
  ///
  /// In en, this message translates to:
  /// **'Earn on a trip you\'re already taking'**
  String get onboardingCarryTitle;

  /// No description provided for @onboardingCarryBody.
  ///
  /// In en, this message translates to:
  /// **'Add your journey, and we\'ll show you parcels that fit your route and your spare kilos.'**
  String get onboardingCarryBody;

  /// No description provided for @onboardingSafeTitle.
  ///
  /// In en, this message translates to:
  /// **'The money waits until it arrives'**
  String get onboardingSafeTitle;

  /// No description provided for @onboardingSafeBody.
  ///
  /// In en, this message translates to:
  /// **'We hold the payment from the moment you book until 48 hours after delivery is confirmed.'**
  String get onboardingSafeBody;

  /// No description provided for @onboardingGetStarted.
  ///
  /// In en, this message translates to:
  /// **'Create an account'**
  String get onboardingGetStarted;

  /// No description provided for @onboardingHaveAccount.
  ///
  /// In en, this message translates to:
  /// **'I already have an account'**
  String get onboardingHaveAccount;

  /// Screen-reader position in the onboarding carousel.
  ///
  /// In en, this message translates to:
  /// **'Page {current} of {total}'**
  String onboardingPageOf(int current, int total);

  /// No description provided for @authInvalidCredentials.
  ///
  /// In en, this message translates to:
  /// **'Email or password is incorrect'**
  String get authInvalidCredentials;

  /// No description provided for @authShowPassword.
  ///
  /// In en, this message translates to:
  /// **'Show password'**
  String get authShowPassword;

  /// No description provided for @authHidePassword.
  ///
  /// In en, this message translates to:
  /// **'Hide password'**
  String get authHidePassword;

  /// No description provided for @authPhone.
  ///
  /// In en, this message translates to:
  /// **'Phone number'**
  String get authPhone;

  /// No description provided for @authWilaya.
  ///
  /// In en, this message translates to:
  /// **'Wilaya'**
  String get authWilaya;

  /// No description provided for @authWilayaHelp.
  ///
  /// In en, this message translates to:
  /// **'Your home wilaya in Algeria. Choose the one you\'re connected to if you live in Europe.'**
  String get authWilayaHelp;

  /// No description provided for @authWilayaSheetTitle.
  ///
  /// In en, this message translates to:
  /// **'Choose a wilaya'**
  String get authWilayaSheetTitle;

  /// No description provided for @authResetCodeSent.
  ///
  /// In en, this message translates to:
  /// **'If that address has an account, we\'ve sent it a six-digit code.'**
  String get authResetCodeSent;

  /// No description provided for @authResetCodeLabel.
  ///
  /// In en, this message translates to:
  /// **'Six-digit code'**
  String get authResetCodeLabel;

  /// No description provided for @authNewPassword.
  ///
  /// In en, this message translates to:
  /// **'New password'**
  String get authNewPassword;

  /// No description provided for @authResetDone.
  ///
  /// In en, this message translates to:
  /// **'Password changed. You can sign in now.'**
  String get authResetDone;

  /// No description provided for @authSendCode.
  ///
  /// In en, this message translates to:
  /// **'Send code'**
  String get authSendCode;

  /// No description provided for @authResendCode.
  ///
  /// In en, this message translates to:
  /// **'Send a new code'**
  String get authResendCode;

  /// No description provided for @authVerifyDone.
  ///
  /// In en, this message translates to:
  /// **'Email verified'**
  String get authVerifyDone;

  /// No description provided for @authTermsNotice.
  ///
  /// In en, this message translates to:
  /// **'By creating an account you accept the Terms and the Privacy Policy.'**
  String get authTermsNotice;

  /// No description provided for @authVerifyNoCode.
  ///
  /// In en, this message translates to:
  /// **'Nothing arrived? Check your spam folder. If it still isn\'t there, contact support and we\'ll sort it out.'**
  String get authVerifyNoCode;

  /// No description provided for @kycDocIdCard.
  ///
  /// In en, this message translates to:
  /// **'National ID card'**
  String get kycDocIdCard;

  /// No description provided for @kycDocPassport.
  ///
  /// In en, this message translates to:
  /// **'Passport'**
  String get kycDocPassport;

  /// No description provided for @kycDocDrivingLicense.
  ///
  /// In en, this message translates to:
  /// **'Driving licence'**
  String get kycDocDrivingLicense;

  /// No description provided for @kycAddPhoto.
  ///
  /// In en, this message translates to:
  /// **'Add photo'**
  String get kycAddPhoto;

  /// No description provided for @kycReplacePhoto.
  ///
  /// In en, this message translates to:
  /// **'Replace'**
  String get kycReplacePhoto;

  /// No description provided for @kycFileTooLarge.
  ///
  /// In en, this message translates to:
  /// **'That image is too large. Each photo must be under 8 MB.'**
  String get kycFileTooLarge;

  /// No description provided for @kycFileTypeNotAllowed.
  ///
  /// In en, this message translates to:
  /// **'Only JPEG and PNG photos are accepted.'**
  String get kycFileTypeNotAllowed;

  /// No description provided for @kycUploading.
  ///
  /// In en, this message translates to:
  /// **'Sending your documents…'**
  String get kycUploading;

  /// No description provided for @kycSubmitAction.
  ///
  /// In en, this message translates to:
  /// **'Submit for review'**
  String get kycSubmitAction;

  /// No description provided for @kycSubmitted.
  ///
  /// In en, this message translates to:
  /// **'Documents received. We\'ll review them shortly.'**
  String get kycSubmitted;

  /// No description provided for @kycBackNotNeeded.
  ///
  /// In en, this message translates to:
  /// **'A passport only needs its photo page.'**
  String get kycBackNotNeeded;

  /// No description provided for @kycSelfieHelp.
  ///
  /// In en, this message translates to:
  /// **'A clear photo of your face, taken now — it\'s checked against your document.'**
  String get kycSelfieHelp;

  /// No description provided for @kycUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Verification is temporarily unavailable. Please try again shortly.'**
  String get kycUnavailable;

  /// No description provided for @payoutEligibleIn.
  ///
  /// In en, this message translates to:
  /// **'Released in'**
  String get payoutEligibleIn;

  /// No description provided for @notificationOffer.
  ///
  /// In en, this message translates to:
  /// **'Offer update'**
  String get notificationOffer;

  /// No description provided for @notificationMatch.
  ///
  /// In en, this message translates to:
  /// **'New match'**
  String get notificationMatch;

  /// No description provided for @notificationPayment.
  ///
  /// In en, this message translates to:
  /// **'Payment update'**
  String get notificationPayment;

  /// No description provided for @notificationChat.
  ///
  /// In en, this message translates to:
  /// **'New message'**
  String get notificationChat;

  /// No description provided for @notificationRequest.
  ///
  /// In en, this message translates to:
  /// **'Request update'**
  String get notificationRequest;

  /// No description provided for @notificationDelivery.
  ///
  /// In en, this message translates to:
  /// **'Delivery update'**
  String get notificationDelivery;

  /// No description provided for @notificationOther.
  ///
  /// In en, this message translates to:
  /// **'Update'**
  String get notificationOther;

  /// No description provided for @chatBlockedPayAction.
  ///
  /// In en, this message translates to:
  /// **'Go to payment'**
  String get chatBlockedPayAction;

  /// No description provided for @chatLoadEarlier.
  ///
  /// In en, this message translates to:
  /// **'Load earlier messages'**
  String get chatLoadEarlier;

  /// No description provided for @chatToday.
  ///
  /// In en, this message translates to:
  /// **'Today'**
  String get chatToday;

  /// No description provided for @chatYesterday.
  ///
  /// In en, this message translates to:
  /// **'Yesterday'**
  String get chatYesterday;

  /// No description provided for @paymentProviderNewCheckoutsDisabled.
  ///
  /// In en, this message translates to:
  /// **'Not taking new payments right now'**
  String get paymentProviderNewCheckoutsDisabled;

  /// No description provided for @paymentProviderPickAnother.
  ///
  /// In en, this message translates to:
  /// **'Try a different payment method.'**
  String get paymentProviderPickAnother;

  /// No description provided for @paymentContinueTitle.
  ///
  /// In en, this message translates to:
  /// **'A checkout is already open'**
  String get paymentContinueTitle;

  /// No description provided for @paymentContinueBody.
  ///
  /// In en, this message translates to:
  /// **'Finish the payment you started instead of opening a second one.'**
  String get paymentContinueBody;

  /// No description provided for @paymentContinueAction.
  ///
  /// In en, this message translates to:
  /// **'Continue your payment'**
  String get paymentContinueAction;

  /// No description provided for @paymentCouldNotOpen.
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t open the checkout page. Check that you have a browser installed.'**
  String get paymentCouldNotOpen;

  /// No description provided for @paymentStillConfirmingTitle.
  ///
  /// In en, this message translates to:
  /// **'Still confirming'**
  String get paymentStillConfirmingTitle;

  /// No description provided for @paymentStillConfirmingBody.
  ///
  /// In en, this message translates to:
  /// **'This is taking longer than usual. Nothing is lost, and you have not been charged twice.'**
  String get paymentStillConfirmingBody;

  /// No description provided for @paymentCheckAgain.
  ///
  /// In en, this message translates to:
  /// **'Check again'**
  String get paymentCheckAgain;

  /// No description provided for @paymentNothingOutstandingTitle.
  ///
  /// In en, this message translates to:
  /// **'Nothing left to pay'**
  String get paymentNothingOutstandingTitle;

  /// No description provided for @paymentNothingOutstandingBody.
  ///
  /// In en, this message translates to:
  /// **'This has already been settled.'**
  String get paymentNothingOutstandingBody;

  /// No description provided for @paymentOrderClosedTitle.
  ///
  /// In en, this message translates to:
  /// **'This can\'t be paid now'**
  String get paymentOrderClosedTitle;

  /// No description provided for @paymentOrderClosedBody.
  ///
  /// In en, this message translates to:
  /// **'This payment was closed or refunded, so no new checkout can be opened.'**
  String get paymentOrderClosedBody;

  /// No description provided for @requestReadyUntil.
  ///
  /// In en, this message translates to:
  /// **'Ready until'**
  String get requestReadyUntil;

  /// No description provided for @requestReadyWindow.
  ///
  /// In en, this message translates to:
  /// **'Ready window'**
  String get requestReadyWindow;

  /// No description provided for @requestReadyWindowHelp.
  ///
  /// In en, this message translates to:
  /// **'The stretch of time a traveller could collect it. Give a window, not a minute.'**
  String get requestReadyWindowHelp;

  /// No description provided for @requestDeadlineHelp.
  ///
  /// In en, this message translates to:
  /// **'The latest it can arrive. This has to be after your ready window closes.'**
  String get requestDeadlineHelp;

  /// No description provided for @requestWeightHelp.
  ///
  /// In en, this message translates to:
  /// **'Between 0.01 and 100 kg.'**
  String get requestWeightHelp;

  /// No description provided for @requestDimensionsHelp.
  ///
  /// In en, this message translates to:
  /// **'Optional. Enter all three, or leave all three empty.'**
  String get requestDimensionsHelp;

  /// No description provided for @requestDimensionsPartial.
  ///
  /// In en, this message translates to:
  /// **'Enter all three measurements, or clear them all.'**
  String get requestDimensionsPartial;

  /// No description provided for @requestCategoryDocuments.
  ///
  /// In en, this message translates to:
  /// **'Documents'**
  String get requestCategoryDocuments;

  /// No description provided for @requestCategorySmallBox.
  ///
  /// In en, this message translates to:
  /// **'Small box'**
  String get requestCategorySmallBox;

  /// No description provided for @requestCategoryElectronics.
  ///
  /// In en, this message translates to:
  /// **'Electronics'**
  String get requestCategoryElectronics;

  /// No description provided for @requestCategoryClothing.
  ///
  /// In en, this message translates to:
  /// **'Clothing'**
  String get requestCategoryClothing;

  /// No description provided for @requestCategoryOther.
  ///
  /// In en, this message translates to:
  /// **'Something else'**
  String get requestCategoryOther;

  /// No description provided for @requestProposedReward.
  ///
  /// In en, this message translates to:
  /// **'What you propose to pay'**
  String get requestProposedReward;

  /// No description provided for @requestProposedRewardHelp.
  ///
  /// In en, this message translates to:
  /// **'A starting point, not a price. Travellers can accept it or come back with a different amount.'**
  String get requestProposedRewardHelp;

  /// No description provided for @requestRewardIsIntent.
  ///
  /// In en, this message translates to:
  /// **'This is what you proposed. The price is settled when a traveller accepts an offer.'**
  String get requestRewardIsIntent;

  /// No description provided for @requestReviewTitle.
  ///
  /// In en, this message translates to:
  /// **'Check this over'**
  String get requestReviewTitle;

  /// No description provided for @requestAckAllRequired.
  ///
  /// In en, this message translates to:
  /// **'Confirm all five before you post.'**
  String get requestAckAllRequired;

  /// No description provided for @requestPostAction.
  ///
  /// In en, this message translates to:
  /// **'Post this request'**
  String get requestPostAction;

  /// No description provided for @requestDetailTitle.
  ///
  /// In en, this message translates to:
  /// **'Your request'**
  String get requestDetailTitle;

  /// No description provided for @requestParcelSection.
  ///
  /// In en, this message translates to:
  /// **'The parcel'**
  String get requestParcelSection;

  /// No description provided for @requestTimingSection.
  ///
  /// In en, this message translates to:
  /// **'Timing'**
  String get requestTimingSection;

  /// No description provided for @requestRouteSection.
  ///
  /// In en, this message translates to:
  /// **'Route'**
  String get requestRouteSection;

  /// No description provided for @requestMatchesSection.
  ///
  /// In en, this message translates to:
  /// **'Travellers you\'ve approached'**
  String get requestMatchesSection;

  /// No description provided for @requestNoMatchesYet.
  ///
  /// In en, this message translates to:
  /// **'You haven\'t proposed to anyone yet.'**
  String get requestNoMatchesYet;

  /// No description provided for @requestAwaitingDepositNotice.
  ///
  /// In en, this message translates to:
  /// **'Travellers can\'t see this yet. Pay the deposit to publish it.'**
  String get requestAwaitingDepositNotice;

  /// No description provided for @requestFindTravelers.
  ///
  /// In en, this message translates to:
  /// **'Find travellers'**
  String get requestFindTravelers;

  /// No description provided for @requestPayDepositAction.
  ///
  /// In en, this message translates to:
  /// **'Pay deposit'**
  String get requestPayDepositAction;

  /// No description provided for @requestCancelAction.
  ///
  /// In en, this message translates to:
  /// **'Cancel request'**
  String get requestCancelAction;

  /// No description provided for @requestCancelConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Cancel this request?'**
  String get requestCancelConfirmTitle;

  /// No description provided for @requestCancelConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'It stops being visible to travellers. Any deposit you paid comes back to you.'**
  String get requestCancelConfirmBody;

  /// No description provided for @requestCancelled.
  ///
  /// In en, this message translates to:
  /// **'Request cancelled'**
  String get requestCancelled;

  /// No description provided for @requestCancelNotCancellableBody.
  ///
  /// In en, this message translates to:
  /// **'A traveller is already matched with this request, so it can\'t be cancelled here.'**
  String get requestCancelNotCancellableBody;

  /// No description provided for @requestCancelViaDealBody.
  ///
  /// In en, this message translates to:
  /// **'This request has become a delivery. Cancel it from the delivery instead.'**
  String get requestCancelViaDealBody;

  /// No description provided for @requestPhotoCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =0{No photos} =1{1 photo} other{{count} photos}}'**
  String requestPhotoCount(int count);

  /// No description provided for @requestNotFragile.
  ///
  /// In en, this message translates to:
  /// **'Standard handling'**
  String get requestNotFragile;

  /// No description provided for @requestFragileYes.
  ///
  /// In en, this message translates to:
  /// **'Handle with care'**
  String get requestFragileYes;

  /// No description provided for @requestTargetedNotice.
  ///
  /// In en, this message translates to:
  /// **'You addressed this request to one traveller. Nobody else can see it.'**
  String get requestTargetedNotice;

  /// No description provided for @depositNotRequiredTitle.
  ///
  /// In en, this message translates to:
  /// **'No deposit needed'**
  String get depositNotRequiredTitle;

  /// No description provided for @depositNotRequiredBody.
  ///
  /// In en, this message translates to:
  /// **'This request publishes without one. There is nothing to pay here.'**
  String get depositNotRequiredBody;

  /// No description provided for @depositClampedMin.
  ///
  /// In en, this message translates to:
  /// **'This is the smallest deposit we take.'**
  String get depositClampedMin;

  /// No description provided for @depositClampedMax.
  ///
  /// In en, this message translates to:
  /// **'This is the largest deposit we take, whatever the parcel is worth.'**
  String get depositClampedMax;

  /// No description provided for @discoveryMatchedDistance.
  ///
  /// In en, this message translates to:
  /// **'Distance carried'**
  String get discoveryMatchedDistance;

  /// No description provided for @discoveryDetourLabel.
  ///
  /// In en, this message translates to:
  /// **'Detour for the traveller'**
  String get discoveryDetourLabel;

  /// No description provided for @discoveryFirstDeparture.
  ///
  /// In en, this message translates to:
  /// **'Leaves'**
  String get discoveryFirstDeparture;

  /// No description provided for @discoveryProposeBlocked.
  ///
  /// In en, this message translates to:
  /// **'We can\'t work out which part of this journey fits your parcel. Refresh and try again.'**
  String get discoveryProposeBlocked;

  /// No description provided for @discoveryVolumetricExplainer.
  ///
  /// In en, this message translates to:
  /// **'This parcel is bulkier than it is heavy, so its size sets the price.'**
  String get discoveryVolumetricExplainer;

  /// No description provided for @discoveryBreakdownNote.
  ///
  /// In en, this message translates to:
  /// **'This is how the suggested amount adds up. Offer something different and the total moves with it.'**
  String get discoveryBreakdownNote;

  /// No description provided for @discoveryProposalSent.
  ///
  /// In en, this message translates to:
  /// **'Offer sent'**
  String get discoveryProposalSent;

  /// No description provided for @discoveryLegRangeMoved.
  ///
  /// In en, this message translates to:
  /// **'This traveller\'s route changed while you were looking. We\'ve refreshed it.'**
  String get discoveryLegRangeMoved;

  /// No description provided for @discoveryIncompatibleCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{This traveller no longer fits your parcel, for 1 reason.} other{This traveller no longer fits your parcel, for {count} reasons.}}'**
  String discoveryIncompatibleCount(int count);

  /// No description provided for @boostRankingLabel.
  ///
  /// In en, this message translates to:
  /// **'Visibility'**
  String get boostRankingLabel;

  /// No description provided for @boostRankingModest.
  ///
  /// In en, this message translates to:
  /// **'Higher in the list'**
  String get boostRankingModest;

  /// No description provided for @boostRankingStrong.
  ///
  /// In en, this message translates to:
  /// **'Much higher in the list'**
  String get boostRankingStrong;

  /// No description provided for @boostRankingTop.
  ///
  /// In en, this message translates to:
  /// **'Top of the list'**
  String get boostRankingTop;

  /// No description provided for @boostDurationLabel.
  ///
  /// In en, this message translates to:
  /// **'Runs for'**
  String get boostDurationLabel;

  /// No description provided for @boostPriceLabel.
  ///
  /// In en, this message translates to:
  /// **'Price'**
  String get boostPriceLabel;

  /// No description provided for @boostCompatibilityNote.
  ///
  /// In en, this message translates to:
  /// **'Only travellers who already match your parcel ever see it. A boost doesn\'t change who those travellers are.'**
  String get boostCompatibilityNote;

  /// No description provided for @boostActivatesOnPayment.
  ///
  /// In en, this message translates to:
  /// **'The boost starts once your payment is confirmed, not when you leave the checkout page.'**
  String get boostActivatesOnPayment;

  /// No description provided for @boostBuyAction.
  ///
  /// In en, this message translates to:
  /// **'Buy this boost'**
  String get boostBuyAction;

  /// No description provided for @boostPayAction.
  ///
  /// In en, this message translates to:
  /// **'Pay for this boost'**
  String get boostPayAction;

  /// No description provided for @boostPurchasesSection.
  ///
  /// In en, this message translates to:
  /// **'Your boosts'**
  String get boostPurchasesSection;

  /// No description provided for @boostNoPackagesTitle.
  ///
  /// In en, this message translates to:
  /// **'No boosts available'**
  String get boostNoPackagesTitle;

  /// No description provided for @boostNoPackagesBody.
  ///
  /// In en, this message translates to:
  /// **'There are no boost packages on offer at the moment.'**
  String get boostNoPackagesBody;

  /// No description provided for @boostDisabledTitle.
  ///
  /// In en, this message translates to:
  /// **'Boosts are switched off'**
  String get boostDisabledTitle;

  /// No description provided for @boostDisabledBody.
  ///
  /// In en, this message translates to:
  /// **'Nobody can buy a boost right now. Your request is unaffected.'**
  String get boostDisabledBody;

  /// No description provided for @boostLimitReachedTitle.
  ///
  /// In en, this message translates to:
  /// **'Boost limit reached'**
  String get boostLimitReachedTitle;

  /// No description provided for @boostLimitReachedBody.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{You can have 1 boost running on a request at a time.} other{You can have {count} boosts running on a request at a time.}}'**
  String boostLimitReachedBody(int count);

  /// No description provided for @boostRequestExpiredBody.
  ///
  /// In en, this message translates to:
  /// **'This request has expired, so it can no longer be boosted.'**
  String get boostRequestExpiredBody;

  /// No description provided for @boostPackageUnknownBody.
  ///
  /// In en, this message translates to:
  /// **'That boost is no longer offered. Choose another one.'**
  String get boostPackageUnknownBody;

  /// No description provided for @boostStatusCancelled.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get boostStatusCancelled;

  /// No description provided for @boostStatusUnusable.
  ///
  /// In en, this message translates to:
  /// **'Refunded — the request stopped being boostable'**
  String get boostStatusUnusable;

  /// No description provided for @boostStatusRefunded.
  ///
  /// In en, this message translates to:
  /// **'Refunded'**
  String get boostStatusRefunded;

  /// No description provided for @validationReadyWindowOrder.
  ///
  /// In en, this message translates to:
  /// **'The ready window has to end after it starts'**
  String get validationReadyWindowOrder;

  /// No description provided for @validationWeightRange.
  ///
  /// In en, this message translates to:
  /// **'Enter a weight between {min} and {max} kg'**
  String validationWeightRange(String min, String max);

  /// No description provided for @dealStepAgreed.
  ///
  /// In en, this message translates to:
  /// **'Terms agreed'**
  String get dealStepAgreed;

  /// No description provided for @dealStepPaid.
  ///
  /// In en, this message translates to:
  /// **'Payment held'**
  String get dealStepPaid;

  /// No description provided for @dealStepRecipient.
  ///
  /// In en, this message translates to:
  /// **'Recipient added'**
  String get dealStepRecipient;

  /// No description provided for @dealStepPickedUp.
  ///
  /// In en, this message translates to:
  /// **'Parcel collected'**
  String get dealStepPickedUp;

  /// No description provided for @dealStepDelivered.
  ///
  /// In en, this message translates to:
  /// **'Delivered'**
  String get dealStepDelivered;

  /// No description provided for @dealStepProtection.
  ///
  /// In en, this message translates to:
  /// **'Protected payment'**
  String get dealStepProtection;

  /// No description provided for @dealStepCompleted.
  ///
  /// In en, this message translates to:
  /// **'Completed'**
  String get dealStepCompleted;

  /// No description provided for @dealOpenChat.
  ///
  /// In en, this message translates to:
  /// **'Message'**
  String get dealOpenChat;

  /// No description provided for @dealParcelSection.
  ///
  /// In en, this message translates to:
  /// **'The parcel'**
  String get dealParcelSection;

  /// No description provided for @dealMoneySection.
  ///
  /// In en, this message translates to:
  /// **'The money'**
  String get dealMoneySection;

  /// No description provided for @dealActionPay.
  ///
  /// In en, this message translates to:
  /// **'Pay now'**
  String get dealActionPay;

  /// No description provided for @dealActionRecipient.
  ///
  /// In en, this message translates to:
  /// **'Add recipient'**
  String get dealActionRecipient;

  /// No description provided for @dealActionPickup.
  ///
  /// In en, this message translates to:
  /// **'Pickup'**
  String get dealActionPickup;

  /// No description provided for @dealActionDelivery.
  ///
  /// In en, this message translates to:
  /// **'Delivery'**
  String get dealActionDelivery;

  /// No description provided for @dealActionDispute.
  ///
  /// In en, this message translates to:
  /// **'Open a dispute'**
  String get dealActionDispute;

  /// No description provided for @dealActionCancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel this delivery'**
  String get dealActionCancel;

  /// No description provided for @dealActionRate.
  ///
  /// In en, this message translates to:
  /// **'Leave a rating'**
  String get dealActionRate;

  /// No description provided for @dealFundingDeadline.
  ///
  /// In en, this message translates to:
  /// **'Pay before {time} or the space is released'**
  String dealFundingDeadline(String time);

  /// No description provided for @dealLocationsHiddenUntilFunded.
  ///
  /// In en, this message translates to:
  /// **'Exact addresses appear once the delivery is paid for.'**
  String get dealLocationsHiddenUntilFunded;

  /// No description provided for @ratingBlindNote.
  ///
  /// In en, this message translates to:
  /// **'Neither of you sees the other\'s rating until you\'ve both left one, or the window closes.'**
  String get ratingBlindNote;

  /// No description provided for @ratingSubmittedTitle.
  ///
  /// In en, this message translates to:
  /// **'Rating saved'**
  String get ratingSubmittedTitle;

  /// Top bar of the pickup handover screen. Neutral: the same screen serves both parties.
  ///
  /// In en, this message translates to:
  /// **'Pickup'**
  String get pickupTitle;

  /// Section header shown once pickup is confirmed.
  ///
  /// In en, this message translates to:
  /// **'What happens next'**
  String get pickupNextTitle;

  /// Sender copy after pickup is confirmed.
  ///
  /// In en, this message translates to:
  /// **'The delivery code unlocks 30 minutes from now. We email it to your recipient, and only they can pass it to the traveller.'**
  String get pickupConfirmedSenderNext;

  /// Traveller copy after pickup is confirmed. States the invariant plainly.
  ///
  /// In en, this message translates to:
  /// **'Carry the parcel to the recipient. They read you the delivery code at the door — you are never shown it yourself.'**
  String get pickupConfirmedTravelerNext;

  /// Action that moves from the pickup screen to the delivery screen.
  ///
  /// In en, this message translates to:
  /// **'Go to delivery'**
  String get pickupGoToDeliveryAction;

  /// Shown when the server refuses a pickup code with deal_not_funded.
  ///
  /// In en, this message translates to:
  /// **'This delivery isn\'t funded yet, so there\'s no pickup code to show.'**
  String get pickupNotFundedBody;

  /// Shown when the server refuses a pickup submission with deal_not_pickup_ready.
  ///
  /// In en, this message translates to:
  /// **'This delivery isn\'t ready for pickup yet.'**
  String get pickupNotReadyBody;

  /// Shown when the server refuses with pickup_already_confirmed.
  ///
  /// In en, this message translates to:
  /// **'Pickup is already confirmed on this delivery.'**
  String get pickupAlreadyConfirmedBody;

  /// Traveller-facing form of recipient_not_set. Never blames the traveller.
  ///
  /// In en, this message translates to:
  /// **'The sender hasn\'t added the recipient yet. Ask them to do that, then try the code again.'**
  String get recipientRequiredTravelerBody;

  /// Shown when handover_code_invalid carries requires_new_code.
  ///
  /// In en, this message translates to:
  /// **'This code can\'t be used again. A new one has to be issued before you can confirm.'**
  String get codeRequiresNewCodeBody;

  /// Shown when handover_rate_limited carries retry_after_seconds.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{Too many tries. Wait a second and try again.} other{Too many tries. Wait {count} seconds and try again.}}'**
  String codeRateLimitedBody(int count);

  /// Top bar of the delivery handover screen. Neutral: the same screen serves both parties.
  ///
  /// In en, this message translates to:
  /// **'Delivery'**
  String get deliveryTitle;

  /// Sender explainer on the delivery screen.
  ///
  /// In en, this message translates to:
  /// **'The recipient receives this code by email. They read it to the traveller at the door, and that is what confirms the delivery.'**
  String get deliverySenderExplainer;

  /// Fallback for deliveryCodeSentToRecipient when no recipient contact is on the record.
  ///
  /// In en, this message translates to:
  /// **'We\'ve emailed the code to your recipient.'**
  String get deliveryCodeSentToRecipientUnknown;

  /// Shown when the server refuses with delivery_code_buffer_open.
  ///
  /// In en, this message translates to:
  /// **'The delivery code is still locked. It unlocks 30 minutes after pickup.'**
  String get deliveryCodeBufferOpenBody;

  /// Shown when a delivery-code rotation is refused with deal_not_in_carriage.
  ///
  /// In en, this message translates to:
  /// **'This delivery isn\'t in transit, so a new code can\'t be issued.'**
  String get deliveryNotInCarriageBody;

  /// Traveller copy immediately after a delivery is confirmed.
  ///
  /// In en, this message translates to:
  /// **'The protection window has started. Your payout is released once it closes — nothing is paid out before then.'**
  String get deliveryConfirmedTravelerNext;

  /// Title of the delivery screen before the code exists.
  ///
  /// In en, this message translates to:
  /// **'Not yet'**
  String get deliveryAwaitingTitle;

  /// Sender copy before the delivery code exists.
  ///
  /// In en, this message translates to:
  /// **'The delivery code appears here once the parcel has been picked up.'**
  String get deliveryAwaitingSenderBody;

  /// Traveller copy before the delivery code can be submitted.
  ///
  /// In en, this message translates to:
  /// **'Confirm the pickup first. The delivery code can only be used after that.'**
  String get deliveryAwaitingTravelerBody;

  /// Label placed before a live protection-window countdown.
  ///
  /// In en, this message translates to:
  /// **'Ends in'**
  String get protectionEndsInLabel;

  /// Label for the payout amount on a deal.
  ///
  /// In en, this message translates to:
  /// **'Amount'**
  String get payoutAmountLabel;

  /// Label for the date a payout becomes eligible.
  ///
  /// In en, this message translates to:
  /// **'Expected'**
  String get payoutEligibleLabel;

  /// Action that opens the dispute attached to this delivery.
  ///
  /// In en, this message translates to:
  /// **'View the dispute'**
  String get disputeViewAction;

  /// Action that starts the dispute form.
  ///
  /// In en, this message translates to:
  /// **'Open a dispute'**
  String get disputeOpenAction;

  /// Confirmation after a dispute is created.
  ///
  /// In en, this message translates to:
  /// **'Dispute opened'**
  String get disputeOpened;

  /// Shown when the idempotent open endpoint returned an existing dispute.
  ///
  /// In en, this message translates to:
  /// **'You already have a dispute open on this delivery. We\'ve taken you to it.'**
  String get disputeExistingOpenedBody;

  /// Notice title on the dispute form.
  ///
  /// In en, this message translates to:
  /// **'The traveller\'s payout goes on hold'**
  String get disputeFreezesPayoutTitle;

  /// Notice body on the dispute form.
  ///
  /// In en, this message translates to:
  /// **'Nothing is paid out while we look into this. Both sides can add evidence.'**
  String get disputeFreezesPayoutBody;

  /// Shown when the server refuses with dispute_not_available.
  ///
  /// In en, this message translates to:
  /// **'You can\'t open a dispute yet'**
  String get disputeNotAvailableTitle;

  /// Body for dispute_not_available.
  ///
  /// In en, this message translates to:
  /// **'A dispute can be opened once the parcel has been picked up. Before that, cancel the delivery instead.'**
  String get disputeNotAvailableBody;

  /// Shown when the server refuses with dispute_already_resolved.
  ///
  /// In en, this message translates to:
  /// **'This has already been decided'**
  String get disputeAlreadyResolvedTitle;

  /// Body for dispute_already_resolved.
  ///
  /// In en, this message translates to:
  /// **'There\'s already a resolved dispute on this delivery.'**
  String get disputeAlreadyResolvedBody;

  /// Top bar of the dispute detail screen.
  ///
  /// In en, this message translates to:
  /// **'Dispute'**
  String get disputeDetailTitle;

  /// Label for the dispute's public reference.
  ///
  /// In en, this message translates to:
  /// **'Reference'**
  String get disputeReferenceLabel;

  /// Row label for the reported category on the dispute detail screen.
  ///
  /// In en, this message translates to:
  /// **'Category'**
  String get disputeCategoryTitle;

  /// Row label for the free-text reason on the dispute detail screen.
  ///
  /// In en, this message translates to:
  /// **'What was reported'**
  String get disputeReasonLabel;

  /// Row label for which party opened the dispute.
  ///
  /// In en, this message translates to:
  /// **'Opened by'**
  String get disputeOpenedByLabel;

  /// Value for opened_by_role = sender.
  ///
  /// In en, this message translates to:
  /// **'The sender'**
  String get disputeOpenedBySender;

  /// Value for opened_by_role = traveler.
  ///
  /// In en, this message translates to:
  /// **'The traveller'**
  String get disputeOpenedByTraveler;

  /// Row label for when the dispute was opened.
  ///
  /// In en, this message translates to:
  /// **'Opened'**
  String get disputeOpenedAtLabel;

  /// Row label for when the dispute was resolved.
  ///
  /// In en, this message translates to:
  /// **'Decided'**
  String get disputeResolvedAtLabel;

  /// Row label for the dispute's protection deadline.
  ///
  /// In en, this message translates to:
  /// **'Protection window ends'**
  String get disputeProtectionEndsLabel;

  /// Notice title while payout_frozen is true.
  ///
  /// In en, this message translates to:
  /// **'Payout on hold'**
  String get disputePayoutFrozenTitle;

  /// Shown when payout_already_settled is true.
  ///
  /// In en, this message translates to:
  /// **'The payout had already gone out before this dispute was opened.'**
  String get disputePayoutSettledBody;

  /// Title of the settlement breakdown.
  ///
  /// In en, this message translates to:
  /// **'How this was settled'**
  String get disputeAmountsTitle;

  /// Explainer under the settlement breakdown.
  ///
  /// In en, this message translates to:
  /// **'These amounts are ShipTrip\'s decision. Nothing here is worked out on your phone.'**
  String get disputeAmountsExplainer;

  /// Breakdown line for the total the sender originally paid.
  ///
  /// In en, this message translates to:
  /// **'Collected from the sender'**
  String get disputeCollectedTotal;

  /// Row label for the resolution note.
  ///
  /// In en, this message translates to:
  /// **'Note from ShipTrip'**
  String get disputeResolutionNoteLabel;

  /// Section header for the dispute event log.
  ///
  /// In en, this message translates to:
  /// **'What\'s happened'**
  String get disputeTimelineTitle;

  /// Timeline entry for the 'opened' event.
  ///
  /// In en, this message translates to:
  /// **'Dispute opened'**
  String get disputeEventOpened;

  /// Timeline entry for the 'status_changed' event.
  ///
  /// In en, this message translates to:
  /// **'Status changed to {status}'**
  String disputeEventStatusChanged(String status);

  /// Timeline entry for the 'evidence_added' event.
  ///
  /// In en, this message translates to:
  /// **'Evidence added'**
  String get disputeEventEvidenceAdded;

  /// Timeline entry for the 'resolved' event.
  ///
  /// In en, this message translates to:
  /// **'Decision made'**
  String get disputeEventResolved;

  /// Timeline entry for the 'closed' event.
  ///
  /// In en, this message translates to:
  /// **'Dispute closed'**
  String get disputeEventClosed;

  /// Timeline entry for the 'payout_frozen' event.
  ///
  /// In en, this message translates to:
  /// **'Payout put on hold'**
  String get disputeEventPayoutFrozen;

  /// Timeline entry for the 'note' event.
  ///
  /// In en, this message translates to:
  /// **'Note added'**
  String get disputeEventNote;

  /// Timeline entry for an event kind this release does not recognise.
  ///
  /// In en, this message translates to:
  /// **'Update'**
  String get disputeEventOther;

  /// Empty state for the evidence list.
  ///
  /// In en, this message translates to:
  /// **'Nothing added yet'**
  String get disputeEvidenceNone;

  /// Action that opens a piece of file evidence.
  ///
  /// In en, this message translates to:
  /// **'View'**
  String get disputeEvidenceView;

  /// Shown when a signed evidence URL could not be opened.
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t open that. Try again.'**
  String get disputeEvidenceOpenFailed;

  /// Label for text evidence.
  ///
  /// In en, this message translates to:
  /// **'Note'**
  String get disputeEvidenceKindText;

  /// Label for photo evidence.
  ///
  /// In en, this message translates to:
  /// **'Photo'**
  String get disputeEvidenceKindPhoto;

  /// Label for video evidence.
  ///
  /// In en, this message translates to:
  /// **'Video'**
  String get disputeEvidenceKindVideo;

  /// How many evidence items have been used out of the allowance.
  ///
  /// In en, this message translates to:
  /// **'{count} of {max} added'**
  String disputeEvidenceCount(int count, int max);

  /// Hint for the evidence note field.
  ///
  /// In en, this message translates to:
  /// **'What you want us to know'**
  String get disputeEvidenceNoteHint;

  /// Confirmation after evidence is uploaded.
  ///
  /// In en, this message translates to:
  /// **'Evidence added'**
  String get disputeEvidenceAdded;

  /// Shown when the server refuses with dispute_not_active.
  ///
  /// In en, this message translates to:
  /// **'This dispute is closed, so nothing more can be added.'**
  String get disputeEvidenceClosedBody;

  /// Shown for dispute_evidence_type_mismatch.
  ///
  /// In en, this message translates to:
  /// **'That file doesn\'t match the type you chose.'**
  String get disputeEvidenceTypeMismatchBody;

  /// Shown for dispute_evidence_content_mismatch.
  ///
  /// In en, this message translates to:
  /// **'That file isn\'t what it claims to be. Try a different one.'**
  String get disputeEvidenceContentMismatchBody;

  /// Explains why viewing evidence takes a moment.
  ///
  /// In en, this message translates to:
  /// **'Evidence links expire after a few minutes, so we fetch a fresh one each time you open something.'**
  String get disputeEvidenceLinkNote;

  /// Shown for dispute_evidence_text_required.
  ///
  /// In en, this message translates to:
  /// **'Write something before adding a note.'**
  String get disputeEvidenceTextRequiredBody;

  /// Shown for dispute_evidence_file_required.
  ///
  /// In en, this message translates to:
  /// **'Choose a file first.'**
  String get disputeEvidenceFileRequiredBody;

  /// A file size in megabytes.
  ///
  /// In en, this message translates to:
  /// **'{value} MB'**
  String unitFileSizeMb(String value);

  /// No description provided for @paymentPollingHint.
  ///
  /// In en, this message translates to:
  /// **'This can take a moment. You can leave this screen — we\'ll keep checking.'**
  String get paymentPollingHint;

  /// No description provided for @paymentOpenProvider.
  ///
  /// In en, this message translates to:
  /// **'Continue payment'**
  String get paymentOpenProvider;

  /// No description provided for @guestPayPoweredBy.
  ///
  /// In en, this message translates to:
  /// **'Paid securely through ShipTrip'**
  String get guestPayPoweredBy;

  /// No description provided for @onboardingEyebrow.
  ///
  /// In en, this message translates to:
  /// **'Welcome'**
  String get onboardingEyebrow;

  /// No description provided for @onboardingHeadline.
  ///
  /// In en, this message translates to:
  /// **'Send anything,\nthe travellers\ndo the rest.'**
  String get onboardingHeadline;

  /// No description provided for @onboardingBody.
  ///
  /// In en, this message translates to:
  /// **'A peer-to-peer corridor between Algeria and France. Travellers carry, senders save, and the money is held until it arrives.'**
  String get onboardingBody;

  /// No description provided for @onboardingStamp.
  ///
  /// In en, this message translates to:
  /// **'EST. 2026 · ALG ↔ FR'**
  String get onboardingStamp;

  /// No description provided for @onboardingTrust.
  ///
  /// In en, this message translates to:
  /// **'ID verified · Payment held · Priced in euros'**
  String get onboardingTrust;

  /// No description provided for @onboardingRouteFrom.
  ///
  /// In en, this message translates to:
  /// **'ALGIERS'**
  String get onboardingRouteFrom;

  /// No description provided for @onboardingRouteTo.
  ///
  /// In en, this message translates to:
  /// **'PARIS'**
  String get onboardingRouteTo;

  /// No description provided for @onboardingRouteMeta.
  ///
  /// In en, this message translates to:
  /// **'DIRECT · 2H 25M'**
  String get onboardingRouteMeta;

  /// No description provided for @benefitsSkip.
  ///
  /// In en, this message translates to:
  /// **'Skip'**
  String get benefitsSkip;

  /// Position marker in the onboarding chapter carousel.
  ///
  /// In en, this message translates to:
  /// **'{current} / {total}'**
  String benefitsIndex(int current, int total);

  /// No description provided for @benefitsChapterOneEyebrow.
  ///
  /// In en, this message translates to:
  /// **'Chapter I · The post'**
  String get benefitsChapterOneEyebrow;

  /// No description provided for @benefitsChapterOneTitle.
  ///
  /// In en, this message translates to:
  /// **'Send anywhere,\nfor a fraction.'**
  String get benefitsChapterOneTitle;

  /// No description provided for @benefitsChapterOneAccent.
  ///
  /// In en, this message translates to:
  /// **'Envoyez vers la France, l’Algérie, et plus loin.'**
  String get benefitsChapterOneAccent;

  /// No description provided for @benefitsChapterOneBody.
  ///
  /// In en, this message translates to:
  /// **'Travellers carry your parcel as part of their luggage. You pay a sliver of express shipping.'**
  String get benefitsChapterOneBody;

  /// No description provided for @benefitsChapterOneStamp.
  ///
  /// In en, this message translates to:
  /// **'Par avion'**
  String get benefitsChapterOneStamp;

  /// No description provided for @benefitsChapterTwoEyebrow.
  ///
  /// In en, this message translates to:
  /// **'Chapter II · The suitcase'**
  String get benefitsChapterTwoEyebrow;

  /// No description provided for @benefitsChapterTwoTitle.
  ///
  /// In en, this message translates to:
  /// **'Earn while\nyou travel.'**
  String get benefitsChapterTwoTitle;

  /// No description provided for @benefitsChapterTwoAccent.
  ///
  /// In en, this message translates to:
  /// **'Voyagez. Gagnez.'**
  String get benefitsChapterTwoAccent;

  /// No description provided for @benefitsChapterTwoBody.
  ///
  /// In en, this message translates to:
  /// **'Going to Algiers, Paris or Oran already? Fill the unused kilos in your luggage.'**
  String get benefitsChapterTwoBody;

  /// No description provided for @benefitsChapterTwoStamp.
  ///
  /// In en, this message translates to:
  /// **'Boarding'**
  String get benefitsChapterTwoStamp;

  /// No description provided for @benefitsChapterThreeEyebrow.
  ///
  /// In en, this message translates to:
  /// **'Chapter III · The seal'**
  String get benefitsChapterThreeEyebrow;

  /// No description provided for @benefitsChapterThreeTitle.
  ///
  /// In en, this message translates to:
  /// **'Built for\ntrust.'**
  String get benefitsChapterThreeTitle;

  /// No description provided for @benefitsChapterThreeAccent.
  ///
  /// In en, this message translates to:
  /// **'Conçu pour la confiance.'**
  String get benefitsChapterThreeAccent;

  /// No description provided for @benefitsChapterThreeBody.
  ///
  /// In en, this message translates to:
  /// **'Verified identities, payment held until delivery, a code at every handover. Nothing moves on trust alone.'**
  String get benefitsChapterThreeBody;

  /// No description provided for @benefitsChapterThreeStamp.
  ///
  /// In en, this message translates to:
  /// **'Verified'**
  String get benefitsChapterThreeStamp;

  /// No description provided for @benefitsHandoverCaption.
  ///
  /// In en, this message translates to:
  /// **'HANDOVER · 6 CHARACTERS'**
  String get benefitsHandoverCaption;

  /// No description provided for @benefitsKilosFree.
  ///
  /// In en, this message translates to:
  /// **'KG\nFREE'**
  String get benefitsKilosFree;

  /// No description provided for @authWelcomeBackStamp.
  ///
  /// In en, this message translates to:
  /// **'Welcome back'**
  String get authWelcomeBackStamp;

  /// No description provided for @authSignInHeadline.
  ///
  /// In en, this message translates to:
  /// **'Good to see\nyou again.'**
  String get authSignInHeadline;

  /// No description provided for @authSignInSubhead.
  ///
  /// In en, this message translates to:
  /// **'Sign in to pick up where your deliveries left off.'**
  String get authSignInSubhead;

  /// No description provided for @authJoinStamp.
  ///
  /// In en, this message translates to:
  /// **'Join the corridor'**
  String get authJoinStamp;

  /// No description provided for @authSignUpHeadline.
  ///
  /// In en, this message translates to:
  /// **'Create your\npassport.'**
  String get authSignUpHeadline;

  /// No description provided for @authSignUpSubhead.
  ///
  /// In en, this message translates to:
  /// **'Two minutes — then you can send or travel.'**
  String get authSignUpSubhead;

  /// No description provided for @authForgotStamp.
  ///
  /// In en, this message translates to:
  /// **'Locked out'**
  String get authForgotStamp;

  /// No description provided for @authForgotHeadline.
  ///
  /// In en, this message translates to:
  /// **'Let\'s get you\nback in.'**
  String get authForgotHeadline;

  /// No description provided for @authVerifyStamp.
  ///
  /// In en, this message translates to:
  /// **'One more stamp'**
  String get authVerifyStamp;

  /// Throttle message when the server sent a Retry-After delay.
  ///
  /// In en, this message translates to:
  /// **'Wait about {seconds} seconds before trying again.'**
  String stateRateLimitedWait(int seconds);

  /// No description provided for @authForgotSubhead.
  ///
  /// In en, this message translates to:
  /// **'Tell us the address on your account and we\'ll send a six-digit code to it.'**
  String get authForgotSubhead;

  /// No description provided for @authVerifySubhead.
  ///
  /// In en, this message translates to:
  /// **'Enter the six-digit code we emailed you. It\'s the last step.'**
  String get authVerifySubhead;

  /// No description provided for @onboardingGetStartedShort.
  ///
  /// In en, this message translates to:
  /// **'Get started'**
  String get onboardingGetStartedShort;
}

class _LDelegate extends LocalizationsDelegate<L> {
  const _LDelegate();

  @override
  Future<L> load(Locale locale) {
    return SynchronousFuture<L>(lookupL(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['ar', 'en', 'fr'].contains(locale.languageCode);

  @override
  bool shouldReload(_LDelegate old) => false;
}

L lookupL(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'ar':
      return LAr();
    case 'en':
      return LEn();
    case 'fr':
      return LFr();
  }

  throw FlutterError(
    'L.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
