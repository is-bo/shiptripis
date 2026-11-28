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

  /// No description provided for @payoutLegalCountryTitle.
  ///
  /// In en, this message translates to:
  /// **'Payout account country'**
  String get payoutLegalCountryTitle;

  /// No description provided for @payoutLegalCountryLabel.
  ///
  /// In en, this message translates to:
  /// **'Country'**
  String get payoutLegalCountryLabel;

  /// No description provided for @payoutLegalCountryBody.
  ///
  /// In en, this message translates to:
  /// **'Select your legal Stripe account country to consent to payout setup. If your country is not listed, use DZD payouts.'**
  String get payoutLegalCountryBody;

  /// No description provided for @appName.
  ///
  /// In en, this message translates to:
  /// **'Wassla'**
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

  /// No description provided for @actionSelect.
  ///
  /// In en, this message translates to:
  /// **'Select'**
  String get actionSelect;

  /// No description provided for @actionClear.
  ///
  /// In en, this message translates to:
  /// **'Clear'**
  String get actionClear;

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
  /// **'Traveling'**
  String get roleTraveler;

  /// No description provided for @roleSwitchLabel.
  ///
  /// In en, this message translates to:
  /// **'Switch role'**
  String get roleSwitchLabel;

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

  /// No description provided for @authNoAccount.
  ///
  /// In en, this message translates to:
  /// **'New to Wassla?'**
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

  /// No description provided for @validationCodeSixDigits.
  ///
  /// In en, this message translates to:
  /// **'Code must be 6 digits'**
  String get validationCodeSixDigits;

  /// No description provided for @validationCcpNumberDigits.
  ///
  /// In en, this message translates to:
  /// **'CCP account number must contain 1 to 20 digits'**
  String get validationCcpNumberDigits;

  /// No description provided for @validationCcpKeyDigits.
  ///
  /// In en, this message translates to:
  /// **'CCP key must be exactly 2 digits'**
  String get validationCcpKeyDigits;

  /// No description provided for @validationRipDigits.
  ///
  /// In en, this message translates to:
  /// **'RIP must be exactly 20 digits'**
  String get validationRipDigits;

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

  /// No description provided for @validationMoneyPrecision.
  ///
  /// In en, this message translates to:
  /// **'Use no more than 2 decimal places'**
  String get validationMoneyPrecision;

  /// No description provided for @validationMustBePositive.
  ///
  /// In en, this message translates to:
  /// **'Enter a number greater than zero'**
  String get validationMustBePositive;

  /// No description provided for @validationTooLong.
  ///
  /// In en, this message translates to:
  /// **'Use at most {max} characters'**
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
  /// **'The server didn’t answer in time. Nothing was lost — try again.'**
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

  /// No description provided for @stateSessionNotSavedTitle.
  ///
  /// In en, this message translates to:
  /// **'This phone couldn\'t save that'**
  String get stateSessionNotSavedTitle;

  /// No description provided for @stateSessionNotSavedBody.
  ///
  /// In en, this message translates to:
  /// **'Nothing changed. Try again, and restart your phone if it keeps happening.'**
  String get stateSessionNotSavedBody;

  /// No description provided for @stateAppOutdatedTitle.
  ///
  /// In en, this message translates to:
  /// **'This version is out of date'**
  String get stateAppOutdatedTitle;

  /// No description provided for @stateAppOutdatedBody.
  ///
  /// In en, this message translates to:
  /// **'Update Wassla to continue. This part of the app no longer works on this version.'**
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
  /// **'This request has already been matched with a traveler.'**
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

  /// No description provided for @staleRewardBelowMinimum.
  ///
  /// In en, this message translates to:
  /// **'The minimum reward has changed.'**
  String get staleRewardBelowMinimum;

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

  /// No description provided for @staleTicketInvalid.
  ///
  /// In en, this message translates to:
  /// **'A ticket on this journey needs attention before it can match.'**
  String get staleTicketInvalid;

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

  /// No description provided for @stalePayoutProfileInvalid.
  ///
  /// In en, this message translates to:
  /// **'Your payout details changed while you were on this page. Pull down to refresh, then try again.'**
  String get stalePayoutProfileInvalid;

  /// No description provided for @stalePayoutCountryUnsupported.
  ///
  /// In en, this message translates to:
  /// **'EUR payouts are not available in that country yet. Choose another country, or use DZD payouts.'**
  String get stalePayoutCountryUnsupported;

  /// No description provided for @staleStripeConnectUnavailable.
  ///
  /// In en, this message translates to:
  /// **'EUR payout setup is temporarily unavailable. Your details are unchanged — please try again shortly.'**
  String get staleStripeConnectUnavailable;

  /// No description provided for @staleStripeConnectProviderError.
  ///
  /// In en, this message translates to:
  /// **'Stripe could not complete the request. Nothing was changed; please try again shortly.'**
  String get staleStripeConnectProviderError;

  /// No description provided for @stalePayoutSetupInvalid.
  ///
  /// In en, this message translates to:
  /// **'That payout setup could not be completed. Check the details and try again.'**
  String get stalePayoutSetupInvalid;

  /// No description provided for @stalePayoutEvidenceUnavailable.
  ///
  /// In en, this message translates to:
  /// **'The uploaded document is no longer available. Please upload the crossed cheque again.'**
  String get stalePayoutEvidenceUnavailable;

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

  /// No description provided for @moneyYouReceive.
  ///
  /// In en, this message translates to:
  /// **'You receive'**
  String get moneyYouReceive;

  /// No description provided for @moneyYourEarnings.
  ///
  /// In en, this message translates to:
  /// **'Your earnings'**
  String get moneyYourEarnings;

  /// No description provided for @moneyTotalYouReceive.
  ///
  /// In en, this message translates to:
  /// **'Total you receive'**
  String get moneyTotalYouReceive;

  /// No description provided for @moneyTravelerReceives.
  ///
  /// In en, this message translates to:
  /// **'Traveler receives'**
  String get moneyTravelerReceives;

  /// No description provided for @moneyPlatformFee.
  ///
  /// In en, this message translates to:
  /// **'Wassla fee'**
  String get moneyPlatformFee;

  /// No description provided for @moneyMinimumReward.
  ///
  /// In en, this message translates to:
  /// **'Minimum reward'**
  String get moneyMinimumReward;

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
  /// **'Traveler compensation'**
  String get moneyTravelerCompensation;

  /// No description provided for @moneyBreakdownTitle.
  ///
  /// In en, this message translates to:
  /// **'How this adds up'**
  String get moneyBreakdownTitle;

  /// No description provided for @moneyRewardNotReduced.
  ///
  /// In en, this message translates to:
  /// **'The traveler receives this full amount. The Wassla fee is added on top, not taken out of it.'**
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
  /// **'Post what you want to send and travelers heading that way will see it.'**
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

  /// No description provided for @dealUnavailableTitle.
  ///
  /// In en, this message translates to:
  /// **'Delivery unavailable'**
  String get dealUnavailableTitle;

  /// No description provided for @dealUnavailableBody.
  ///
  /// In en, this message translates to:
  /// **'This delivery is not available for this account. It may have changed, or the link may be out of date.'**
  String get dealUnavailableBody;

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
  /// **'Finding a traveler'**
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
  /// **'Where the traveler collects the parcel'**
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
  /// **'Describe it accurately. This is what the traveler agrees to carry.'**
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

  /// No description provided for @requestHandlingNotes.
  ///
  /// In en, this message translates to:
  /// **'Handling notes'**
  String get requestHandlingNotes;

  /// No description provided for @requestHandlingNotesHint.
  ///
  /// In en, this message translates to:
  /// **'Anything the traveler should know'**
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
  /// **'Paid now to list your request. 100% credited toward your final delivery payment.'**
  String get depositExplainer;

  /// No description provided for @depositAmount.
  ///
  /// In en, this message translates to:
  /// **'Deposit'**
  String get depositAmount;

  /// No description provided for @depositCreditedNote.
  ///
  /// In en, this message translates to:
  /// **'It\'s credited towards your final payment when a traveler accepts.'**
  String get depositCreditedNote;

  /// No description provided for @depositRefundNote.
  ///
  /// In en, this message translates to:
  /// **'If nobody takes it, or you cancel before accepting an offer, you get it back in full.'**
  String get depositRefundNote;

  /// No description provided for @depositGuidanceTitle.
  ///
  /// In en, this message translates to:
  /// **'Deposit guidance'**
  String get depositGuidanceTitle;

  /// No description provided for @depositSuggestedTotal.
  ///
  /// In en, this message translates to:
  /// **'Wassla suggested total'**
  String get depositSuggestedTotal;

  /// No description provided for @depositWholeAmount.
  ///
  /// In en, this message translates to:
  /// **'Your total for this delivery'**
  String get depositWholeAmount;

  /// No description provided for @pricingUpdating.
  ///
  /// In en, this message translates to:
  /// **'Updating the price'**
  String get pricingUpdating;

  /// No description provided for @depositRecommended.
  ///
  /// In en, this message translates to:
  /// **'Recommended deposit'**
  String get depositRecommended;

  /// No description provided for @depositMinimumAllowed.
  ///
  /// In en, this message translates to:
  /// **'Minimum deposit'**
  String get depositMinimumAllowed;

  /// No description provided for @depositGuidanceNote.
  ///
  /// In en, this message translates to:
  /// **'Wassla calculates the deposit from the suggested total and applies the current minimum and maximum. This is credit toward the final payment, not an extra fee.'**
  String get depositGuidanceNote;

  /// No description provided for @depositPayAction.
  ///
  /// In en, this message translates to:
  /// **'Pay deposit and publish'**
  String get depositPayAction;

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
  /// **'How you\'re traveling'**
  String get journeyModeLabel;

  /// No description provided for @journeyChooseDateTime.
  ///
  /// In en, this message translates to:
  /// **'Choose date and time'**
  String get journeyChooseDateTime;

  /// No description provided for @journeyArriveHelp.
  ///
  /// In en, this message translates to:
  /// **'Needed to match you with senders: their deadline is checked against this time.'**
  String get journeyArriveHelp;

  /// No description provided for @journeyMaxLegsReached.
  ///
  /// In en, this message translates to:
  /// **'A journey can hold at most 20 legs.'**
  String get journeyMaxLegsReached;

  /// No description provided for @journeyCapacityInvalid.
  ///
  /// In en, this message translates to:
  /// **'Enter between 0.01 and 200 kg, to two decimal places.'**
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

  /// No description provided for @journeyLegArriveRequired.
  ///
  /// In en, this message translates to:
  /// **'Add when this leg arrives.'**
  String get journeyLegArriveRequired;

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
  /// **'Tickets to check'**
  String get journeyLegsNeedProofTitle;

  /// No description provided for @journeyPublishBlockedProof.
  ///
  /// In en, this message translates to:
  /// **'Every flight and ferry leg needs an approved ticket before this can go live.'**
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

  /// No description provided for @journeyErrorLegArrivalRequired.
  ///
  /// In en, this message translates to:
  /// **'Every leg needs an arrival time before you publish. Without it, no sender can be matched with this trip.'**
  String get journeyErrorLegArrivalRequired;

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

  /// No description provided for @routeStopsTitle.
  ///
  /// In en, this message translates to:
  /// **'Your stops'**
  String get routeStopsTitle;

  /// No description provided for @routeStopsHelp.
  ///
  /// In en, this message translates to:
  /// **'Add where you start, where you end, and anywhere you stop on the way. We work out the legs between them.'**
  String get routeStopsHelp;

  /// No description provided for @routeStopLabel.
  ///
  /// In en, this message translates to:
  /// **'Stop'**
  String get routeStopLabel;

  /// No description provided for @routeAddStopHere.
  ///
  /// In en, this message translates to:
  /// **'Add a stop here'**
  String get routeAddStopHere;

  /// No description provided for @routeAddStopTitle.
  ///
  /// In en, this message translates to:
  /// **'Where do you stop?'**
  String get routeAddStopTitle;

  /// No description provided for @routeChangeStopTitle.
  ///
  /// In en, this message translates to:
  /// **'Change this stop'**
  String get routeChangeStopTitle;

  /// No description provided for @routeRemoveStop.
  ///
  /// In en, this message translates to:
  /// **'Remove this stop'**
  String get routeRemoveStop;

  /// No description provided for @routeMoveStopEarlier.
  ///
  /// In en, this message translates to:
  /// **'Move this stop earlier'**
  String get routeMoveStopEarlier;

  /// No description provided for @routeMoveStopLater.
  ///
  /// In en, this message translates to:
  /// **'Move this stop later'**
  String get routeMoveStopLater;

  /// No description provided for @routeStopSameAsPrevious.
  ///
  /// In en, this message translates to:
  /// **'This is the same city as the stop before it. Choose somewhere else, or remove one of them.'**
  String get routeStopSameAsPrevious;

  /// Heading on the leg editor between two stops.
  ///
  /// In en, this message translates to:
  /// **'{from} to {to}'**
  String routeSegmentBetween(String from, String to);

  /// No description provided for @routeFlightOnlyExplainer.
  ///
  /// In en, this message translates to:
  /// **'There\'s no road between these two countries, so this part has to be a flight.'**
  String get routeFlightOnlyExplainer;

  /// No description provided for @routeFlightAirportsRequired.
  ///
  /// In en, this message translates to:
  /// **'A flight starts and ends at an airport. Choose the airport for each end of this part.'**
  String get routeFlightAirportsRequired;

  /// No description provided for @routeAirportNeededTitle.
  ///
  /// In en, this message translates to:
  /// **'Which airport?'**
  String get routeAirportNeededTitle;

  /// Asks for the airport a stop is reached by, without replacing the city.
  ///
  /// In en, this message translates to:
  /// **'You\'re flying from {stop}, so we need the airport. The stop stays {stop} — we just need to know how you leave it.'**
  String routeAirportNeededBody(String stop);

  /// No description provided for @routeChooseAirport.
  ///
  /// In en, this message translates to:
  /// **'Choose airport'**
  String get routeChooseAirport;

  /// No description provided for @routeChooseAirportTitle.
  ///
  /// In en, this message translates to:
  /// **'Which airport?'**
  String get routeChooseAirportTitle;

  /// No description provided for @routeChangeAirport.
  ///
  /// In en, this message translates to:
  /// **'Change'**
  String get routeChangeAirport;

  /// Confirms the airport a stop is reached by.
  ///
  /// In en, this message translates to:
  /// **'Flying via {airport}'**
  String routeAirportChosen(String airport);

  /// No description provided for @routeErrorModeUnavailable.
  ///
  /// In en, this message translates to:
  /// **'That part of the route can\'t be driven. There\'s no road between those two countries, so it has to be a flight.'**
  String get routeErrorModeUnavailable;

  /// No description provided for @journeyEditTitle.
  ///
  /// In en, this message translates to:
  /// **'Edit journey'**
  String get journeyEditTitle;

  /// No description provided for @journeyEditAction.
  ///
  /// In en, this message translates to:
  /// **'Edit'**
  String get journeyEditAction;

  /// No description provided for @journeySaveChanges.
  ///
  /// In en, this message translates to:
  /// **'Save changes'**
  String get journeySaveChanges;

  /// No description provided for @journeyEditSaved.
  ///
  /// In en, this message translates to:
  /// **'Journey updated.'**
  String get journeyEditSaved;

  /// How much reviewed flight proof an edit sent back to the queue.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{Journey updated. One flight proof went back for review because that flight changed.} other{Journey updated. {count} flight proofs went back for review because those flights changed.}}'**
  String journeyEditSavedProofReset(int count);

  /// No description provided for @journeyEditBlockedTitle.
  ///
  /// In en, this message translates to:
  /// **'This journey can\'t be edited'**
  String get journeyEditBlockedTitle;

  /// No description provided for @journeyEditBlockedStatus.
  ///
  /// In en, this message translates to:
  /// **'This journey can no longer be edited because it is already published. Cancel it and create a new one if the route has changed.'**
  String get journeyEditBlockedStatus;

  /// No description provided for @journeyEditBlockedDependent.
  ///
  /// In en, this message translates to:
  /// **'This journey can no longer be edited because a sender is already counting on this route.'**
  String get journeyEditBlockedDependent;

  /// No description provided for @journeyEditStaleRoute.
  ///
  /// In en, this message translates to:
  /// **'This route changed while you were editing it. Reopen it and try again.'**
  String get journeyEditStaleRoute;

  /// No description provided for @journeyEditProofNotice.
  ///
  /// In en, this message translates to:
  /// **'Changing a flight or ferry leg\'s places, number or times means its ticket no longer shows that trip, so we\'ll check it again.'**
  String get journeyEditProofNotice;

  /// No description provided for @journeyEditProofWarningTitle.
  ///
  /// In en, this message translates to:
  /// **'Your ticket will be checked again'**
  String get journeyEditProofWarningTitle;

  /// No description provided for @journeyEditProofWarningBody.
  ///
  /// In en, this message translates to:
  /// **'You\'ve changed a leg that already has a ticket. That ticket no longer shows this trip, so it goes back for review and the journey can\'t go live until it\'s approved again.'**
  String get journeyEditProofWarningBody;

  /// No description provided for @proofErrorStorageUnavailable.
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t store your file just now.'**
  String get proofErrorStorageUnavailable;

  /// No description provided for @proofRetryTitle.
  ///
  /// In en, this message translates to:
  /// **'Upload didn\'t finish'**
  String get proofRetryTitle;

  /// No description provided for @proofRetryFileKept.
  ///
  /// In en, this message translates to:
  /// **'Your image is still selected.'**
  String get proofRetryFileKept;

  /// No description provided for @proofRetry.
  ///
  /// In en, this message translates to:
  /// **'Try again'**
  String get proofRetry;

  /// No description provided for @proofTitle.
  ///
  /// In en, this message translates to:
  /// **'Ticket proof'**
  String get proofTitle;

  /// No description provided for @proofExplainerFlight.
  ///
  /// In en, this message translates to:
  /// **'Upload your boarding pass or booking confirmation. We check it before your journey can match parcels.'**
  String get proofExplainerFlight;

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
  /// **'Senders are handing a stranger something that matters to them. Verifying travelers is what makes that reasonable.'**
  String get kycWhyBody;

  /// No description provided for @kycStatusNotStarted.
  ///
  /// In en, this message translates to:
  /// **'Not started'**
  String get kycStatusNotStarted;

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

  /// No description provided for @kycStartAction.
  ///
  /// In en, this message translates to:
  /// **'Start identity check'**
  String get kycStartAction;

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
  /// **'Travelers for this parcel'**
  String get discoveryTravelersTitle;

  /// No description provided for @discoveryRequestsTitle.
  ///
  /// In en, this message translates to:
  /// **'Parcels along your route'**
  String get discoveryRequestsTitle;

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

  /// No description provided for @findTravelersRouteFitExcellent.
  ///
  /// In en, this message translates to:
  /// **'Excellent route match'**
  String get findTravelersRouteFitExcellent;

  /// No description provided for @findTravelersRouteFitGood.
  ///
  /// In en, this message translates to:
  /// **'Good route match'**
  String get findTravelersRouteFitGood;

  /// No description provided for @findTravelersRouteFitCompatible.
  ///
  /// In en, this message translates to:
  /// **'Compatible route'**
  String get findTravelersRouteFitCompatible;

  /// No description provided for @findTravelersTimingComfortable.
  ///
  /// In en, this message translates to:
  /// **'Arrives with time to spare'**
  String get findTravelersTimingComfortable;

  /// No description provided for @findTravelersTimingFits.
  ///
  /// In en, this message translates to:
  /// **'Fits your delivery window'**
  String get findTravelersTimingFits;

  /// No description provided for @findTravelersNewTraveller.
  ///
  /// In en, this message translates to:
  /// **'New'**
  String get findTravelersNewTraveller;

  /// No description provided for @findTravelersViewTrip.
  ///
  /// In en, this message translates to:
  /// **'View trip'**
  String get findTravelersViewTrip;

  /// No description provided for @findTravelersWhyThisFits.
  ///
  /// In en, this message translates to:
  /// **'Why this trip fits'**
  String get findTravelersWhyThisFits;

  /// No description provided for @findTravelersEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No travelers going your way yet'**
  String get findTravelersEmptyTitle;

  /// No description provided for @findTravelersEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Your request stays active. We’ll tell you as soon as somebody posts a trip along your route.'**
  String get findTravelersEmptyBody;

  /// No description provided for @findTravelersIneligibleAwaitingDeposit.
  ///
  /// In en, this message translates to:
  /// **'Pay the posting deposit to publish this request.'**
  String get findTravelersIneligibleAwaitingDeposit;

  /// No description provided for @findTravelersIneligibleAlreadyMatched.
  ///
  /// In en, this message translates to:
  /// **'This parcel already has a traveler.'**
  String get findTravelersIneligibleAlreadyMatched;

  /// No description provided for @findTravelersIneligibleClosed.
  ///
  /// In en, this message translates to:
  /// **'This request is closed.'**
  String get findTravelersIneligibleClosed;

  /// No description provided for @findTravelersIneligibleInProgress.
  ///
  /// In en, this message translates to:
  /// **'This parcel is already on its way.'**
  String get findTravelersIneligibleInProgress;

  /// No description provided for @findTravelersDirectLeg.
  ///
  /// In en, this message translates to:
  /// **'Carried in one leg'**
  String get findTravelersDirectLeg;

  /// No description provided for @findTravelersWholeTripMatches.
  ///
  /// In en, this message translates to:
  /// **'This whole trip is your route'**
  String get findTravelersWholeTripMatches;

  /// No description provided for @findTravelersIdentityVerified.
  ///
  /// In en, this message translates to:
  /// **'Identity verified'**
  String get findTravelersIdentityVerified;

  /// No description provided for @findTravelersFlightProofApproved.
  ///
  /// In en, this message translates to:
  /// **'Flight ticket verified'**
  String get findTravelersFlightProofApproved;

  /// No description provided for @findTravelersSortBestMatch.
  ///
  /// In en, this message translates to:
  /// **'Best match'**
  String get findTravelersSortBestMatch;

  /// No description provided for @findTravelersSortSoonest.
  ///
  /// In en, this message translates to:
  /// **'Soonest trip'**
  String get findTravelersSortSoonest;

  /// No description provided for @findTravelersShowMore.
  ///
  /// In en, this message translates to:
  /// **'Show more travelers'**
  String get findTravelersShowMore;

  /// A route stop reached by air: the city first, the airport code beside it. Airports are a facet of a stop, never a stop of their own.
  ///
  /// In en, this message translates to:
  /// **'{city} · {iata}'**
  String findTravelersStop(String city, String iata);

  /// No description provided for @findTravelersTransfers.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 transfer} other{{count} transfers}}'**
  String findTravelersTransfers(int count);

  /// No description provided for @findTravelersPicksUpIn.
  ///
  /// In en, this message translates to:
  /// **'Picks up in {place}'**
  String findTravelersPicksUpIn(String place);

  /// No description provided for @findTravelersArrivesIn.
  ///
  /// In en, this message translates to:
  /// **'Arrives in {place}'**
  String findTravelersArrivesIn(String place);

  /// Both dates arrive already formatted by the client for the reader's locale.
  ///
  /// In en, this message translates to:
  /// **'Arrives {arrival}, before your {deadline} deadline'**
  String findTravelersArrivesBeforeDeadline(String arrival, String deadline);

  /// No description provided for @findTravelersHasRoomFor.
  ///
  /// In en, this message translates to:
  /// **'Has room for {weight} kg'**
  String findTravelersHasRoomFor(String weight);

  /// No description provided for @findTravelersDeliveries.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =0{No deliveries yet} =1{1 delivery} other{{count} deliveries}}'**
  String findTravelersDeliveries(int count);

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
  /// **'You choose what the traveler earns. They can accept, decline, or come back with a different amount.'**
  String get offerProposeExplainer;

  /// No description provided for @offerRewardLabel.
  ///
  /// In en, this message translates to:
  /// **'Traveler\'s reward'**
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

  /// No description provided for @offerSendCounter.
  ///
  /// In en, this message translates to:
  /// **'Send counter-offer'**
  String get offerSendCounter;

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
  /// **'Waiting for the traveler'**
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

  /// No description provided for @offerAcceptSenderConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Pay {amount} for this delivery?'**
  String offerAcceptSenderConfirmTitle(String amount);

  /// No description provided for @offerAcceptTravelerConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Receive {amount} for this delivery?'**
  String offerAcceptTravelerConfirmTitle(String amount);

  /// No description provided for @offerCounterTravelerExplainer.
  ///
  /// In en, this message translates to:
  /// **'Choose how much you receive for this delivery. The sender can accept, decline, or counter again.'**
  String get offerCounterTravelerExplainer;

  /// No description provided for @offerYourOfferTitle.
  ///
  /// In en, this message translates to:
  /// **'Your offer'**
  String get offerYourOfferTitle;

  /// No description provided for @offerTravelerCounterTitle.
  ///
  /// In en, this message translates to:
  /// **'Traveler\'s counter-offer'**
  String get offerTravelerCounterTitle;

  /// No description provided for @offerYourCounterTitle.
  ///
  /// In en, this message translates to:
  /// **'Your counter-offer'**
  String get offerYourCounterTitle;

  /// No description provided for @offerSenderOfferTitle.
  ///
  /// In en, this message translates to:
  /// **'Sender\'s offer'**
  String get offerSenderOfferTitle;

  /// No description provided for @offerYouWouldPay.
  ///
  /// In en, this message translates to:
  /// **'You would pay {amount}'**
  String offerYouWouldPay(String amount);

  /// No description provided for @offerTravelerAsks.
  ///
  /// In en, this message translates to:
  /// **'Traveler asks {amount}'**
  String offerTravelerAsks(String amount);

  /// No description provided for @offerYouWouldReceive.
  ///
  /// In en, this message translates to:
  /// **'You would receive {amount}'**
  String offerYouWouldReceive(String amount);

  /// No description provided for @offerSenderOffers.
  ///
  /// In en, this message translates to:
  /// **'Sender offers {amount}'**
  String offerSenderOffers(String amount);

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
  /// **'Stripe'**
  String get paymentProviderStripe;

  /// No description provided for @paymentProviderStripeSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Visa, Mastercard and other cards'**
  String get paymentProviderStripeSubtitle;

  /// No description provided for @paymentProviderChargily.
  ///
  /// In en, this message translates to:
  /// **'Chargily'**
  String get paymentProviderChargily;

  /// No description provided for @paymentProviderChargilySubtitle.
  ///
  /// In en, this message translates to:
  /// **'Algerian cards — CIB and Edahabia'**
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

  /// No description provided for @paymentProviderConfigurationInvalid.
  ///
  /// In en, this message translates to:
  /// **'Not ready yet'**
  String get paymentProviderConfigurationInvalid;

  /// No description provided for @paymentProviderAmountTooSmall.
  ///
  /// In en, this message translates to:
  /// **'Below this method\'s minimum'**
  String get paymentProviderAmountTooSmall;

  /// No description provided for @paymentCheckoutFailedTitle.
  ///
  /// In en, this message translates to:
  /// **'We could not start this payment'**
  String get paymentCheckoutFailedTitle;

  /// No description provided for @paymentCheckoutFailedBody.
  ///
  /// In en, this message translates to:
  /// **'The payment provider refused to open a checkout. Nothing has been charged. Try the other method, or come back shortly.'**
  String get paymentCheckoutFailedBody;

  /// No description provided for @paymentRailEquivalent.
  ///
  /// In en, this message translates to:
  /// **'Equivalent to {amount}'**
  String paymentRailEquivalent(String amount);

  /// No description provided for @paymentRailRate.
  ///
  /// In en, this message translates to:
  /// **'€1 = {rate} DA'**
  String paymentRailRate(String rate);

  /// No description provided for @paymentRailRateLocked.
  ///
  /// In en, this message translates to:
  /// **'The rate is locked when you start the payment. The delivery price stays in euros.'**
  String get paymentRailRateLocked;

  /// No description provided for @paymentPayWith.
  ///
  /// In en, this message translates to:
  /// **'Pay {amount} with {provider}'**
  String paymentPayWith(String amount, String provider);

  /// No description provided for @a11yPaymentRailCharge.
  ///
  /// In en, this message translates to:
  /// **'{provider}, charges {amount}'**
  String a11yPaymentRailCharge(String provider, String amount);

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

  /// No description provided for @paymentStatusRequired.
  ///
  /// In en, this message translates to:
  /// **'Payment needed'**
  String get paymentStatusRequired;

  /// No description provided for @paymentStatusPaid.
  ///
  /// In en, this message translates to:
  /// **'Paid'**
  String get paymentStatusPaid;

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

  /// No description provided for @paymentRedirectNotProof.
  ///
  /// In en, this message translates to:
  /// **'We confirm every payment with the provider before marking it paid.'**
  String get paymentRedirectNotProof;

  /// No description provided for @guestPayTitle.
  ///
  /// In en, this message translates to:
  /// **'Payment request'**
  String get guestPayTitle;

  /// No description provided for @guestPayExplainer.
  ///
  /// In en, this message translates to:
  /// **'The person who sent you this link is asking you to pay this for their Wassla delivery. You don’t need an account.'**
  String get guestPayExplainer;

  /// No description provided for @guestPayExpiresAt.
  ///
  /// In en, this message translates to:
  /// **'Expires {when}'**
  String guestPayExpiresAt(String when);

  /// No description provided for @guestPayWarning.
  ///
  /// In en, this message translates to:
  /// **'This link only lets you pay this amount. It gives no access to the delivery or to anyone’s details.'**
  String get guestPayWarning;

  /// No description provided for @guestPayPayerEmail.
  ///
  /// In en, this message translates to:
  /// **'Email for your receipt'**
  String get guestPayPayerEmail;

  /// No description provided for @guestPayPayerEmailHelp.
  ///
  /// In en, this message translates to:
  /// **'We’ll send your receipt here, and tell you if a refund is ever due. It doesn’t create an account.'**
  String get guestPayPayerEmailHelp;

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
  /// **'We email the delivery code to the recipient. The traveler can only complete the delivery if the recipient gives them that code.'**
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
  /// **'Give this code to the traveler only when you\'re physically handing over the parcel. It\'s how they confirm they have it.'**
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
  /// **'The traveler will ask for your pickup code when you meet.'**
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
  /// **'Delivery confirmed'**
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
  /// **'The recipient gives this to the traveler at the door. Only share it with the recipient.'**
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
  /// **'Funds are held pending delivery confirmation and the 48-hour protection period. Wassla releases them only after that period ends and no dispute is open.'**
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
  /// **'Tell us what went wrong. Opening a dispute puts the traveler\'s payout on hold while we look into it.'**
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
  /// **'Paid to the traveler'**
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
  /// **'Disputes can be opened for 48 hours after delivery.'**
  String get disputeWindowClosedBody;

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
  /// **'Because it\'s close to pickup, the traveler is compensated for holding the space.'**
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
  /// **'Rate the traveler'**
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
  /// **'Travelers receive 100% of the Boost bonus. Boosted requests appear higher in traveler search.'**
  String get boostExplainer;

  /// No description provided for @boostDurationDays.
  ///
  /// In en, this message translates to:
  /// **'{days, plural, =1{1 day} other{{days} days}}'**
  String boostDurationDays(int days);

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
  /// **'Wassla · MEMBER'**
  String get profilePassportStamp;

  /// No description provided for @profileCompletedDeliveries.
  ///
  /// In en, this message translates to:
  /// **'Completed'**
  String get profileCompletedDeliveries;

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
  /// **'What you read inside Wassla. Stored on this phone.'**
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

  /// Shown when tapping a legal link like Terms or Privacy cannot open in an external browser.
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t open that page. Check that you have a browser installed.'**
  String get profileLinkOpenFailed;

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
  /// **'With Wassla since {date}'**
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

  /// No description provided for @locationAirportServesPlace.
  ///
  /// In en, this message translates to:
  /// **'Serves {place}'**
  String locationAirportServesPlace(String place);

  /// No description provided for @locationAirportNearPlace.
  ///
  /// In en, this message translates to:
  /// **'Near {place}'**
  String locationAirportNearPlace(String place);

  /// Shown under an airport suggested only because it is close to the searched place. It must not read as an official served-city relationship, and it states the distance so the reader can judge it.
  ///
  /// In en, this message translates to:
  /// **'Nearby airport · {distance} km'**
  String locationAirportNearbyDistance(String distance);

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
  /// **'Travelers are matched on {place}. A preferred point only says where you would rather meet inside it.'**
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

  /// No description provided for @timelineDone.
  ///
  /// In en, this message translates to:
  /// **'Done'**
  String get timelineDone;

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

  /// No description provided for @a11yLoadingContent.
  ///
  /// In en, this message translates to:
  /// **'Loading content'**
  String get a11yLoadingContent;

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

  /// No description provided for @homeVerifyIdentityTitle.
  ///
  /// In en, this message translates to:
  /// **'Verify your identity'**
  String get homeVerifyIdentityTitle;

  /// No description provided for @homeVerifyIdentityBody.
  ///
  /// In en, this message translates to:
  /// **'Travelers must be verified before a journey can go live.'**
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
  /// **'Show the pickup code to your traveler'**
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
  /// **'{count, plural, =1{1 ticket needs checking} other{{count} tickets need checking}}'**
  String journeyProofNeeded(int count);

  /// No description provided for @onboardingGetStarted.
  ///
  /// In en, this message translates to:
  /// **'Create an account'**
  String get onboardingGetStarted;

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
  /// **'Password changed. You were signed out everywhere. Sign in with the new password.'**
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
  /// **'Nothing arrived? Check your spam folder, then ask for a new code. Only the code in the newest email works.'**
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

  /// No description provided for @notificationOffer.
  ///
  /// In en, this message translates to:
  /// **'Offer update'**
  String get notificationOffer;

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
  /// **'The stretch of time a traveler could collect it. Give a window, not a minute.'**
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
  /// **'A starting point, not a price. Travelers can accept it or come back with a different amount.'**
  String get requestProposedRewardHelp;

  /// No description provided for @requestRewardIsIntent.
  ///
  /// In en, this message translates to:
  /// **'This is what you proposed. The price is settled when a traveler accepts an offer.'**
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

  /// No description provided for @requestRouteNotRecorded.
  ///
  /// In en, this message translates to:
  /// **'Route not recorded'**
  String get requestRouteNotRecorded;

  /// No description provided for @requestMatchesSection.
  ///
  /// In en, this message translates to:
  /// **'Travelers you\'ve approached'**
  String get requestMatchesSection;

  /// No description provided for @requestNoMatchesYet.
  ///
  /// In en, this message translates to:
  /// **'You haven\'t proposed to anyone yet.'**
  String get requestNoMatchesYet;

  /// No description provided for @requestAwaitingDepositNotice.
  ///
  /// In en, this message translates to:
  /// **'Travelers can\'t see this yet. Pay the deposit to publish it.'**
  String get requestAwaitingDepositNotice;

  /// No description provided for @requestFindTravelers.
  ///
  /// In en, this message translates to:
  /// **'Find travelers'**
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
  /// **'It stops being visible to travelers. Any deposit you paid comes back to you.'**
  String get requestCancelConfirmBody;

  /// No description provided for @requestCancelled.
  ///
  /// In en, this message translates to:
  /// **'Request cancelled'**
  String get requestCancelled;

  /// No description provided for @requestCancelNotCancellableBody.
  ///
  /// In en, this message translates to:
  /// **'A traveler is already matched with this request, so it can\'t be cancelled here.'**
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
  /// **'You addressed this request to one traveler. Nobody else can see it.'**
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

  /// No description provided for @discoveryProposeBlocked.
  ///
  /// In en, this message translates to:
  /// **'We can\'t work out which part of this journey fits your parcel. Refresh and try again.'**
  String get discoveryProposeBlocked;

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
  /// **'This traveler\'s route changed while you were looking. We\'ve refreshed it.'**
  String get discoveryLegRangeMoved;

  /// No description provided for @discoveryIncompatibleCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{This traveler no longer fits your parcel, for 1 reason.} other{This traveler no longer fits your parcel, for {count} reasons.}}'**
  String discoveryIncompatibleCount(int count);

  /// No description provided for @boostCompatibilityNote.
  ///
  /// In en, this message translates to:
  /// **'Only travelers who already match your parcel ever see it. A boost doesn\'t change who those travelers are.'**
  String get boostCompatibilityNote;

  /// No description provided for @moneyBaseReward.
  ///
  /// In en, this message translates to:
  /// **'Base delivery reward'**
  String get moneyBaseReward;

  /// No description provided for @moneyBoostBonus.
  ///
  /// In en, this message translates to:
  /// **'Boost bonus'**
  String get moneyBoostBonus;

  /// No description provided for @moneyBoostFee.
  ///
  /// In en, this message translates to:
  /// **'Boost fee'**
  String get moneyBoostFee;

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

  /// No description provided for @dealTravelerAwaitingPayment.
  ///
  /// In en, this message translates to:
  /// **'Waiting for the sender to pay.'**
  String get dealTravelerAwaitingPayment;

  /// No description provided for @dealTravelerPaymentFunded.
  ///
  /// In en, this message translates to:
  /// **'The sender\'s payment is confirmed and protected.'**
  String get dealTravelerPaymentFunded;

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

  /// No description provided for @ratingClosedTitle.
  ///
  /// In en, this message translates to:
  /// **'Rating closed'**
  String get ratingClosedTitle;

  /// No description provided for @ratingTheirsTitle.
  ///
  /// In en, this message translates to:
  /// **'Their rating'**
  String get ratingTheirsTitle;

  /// No description provided for @ratingRevealedNote.
  ///
  /// In en, this message translates to:
  /// **'You have both rated, so your ratings are now visible to each other.'**
  String get ratingRevealedNote;

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
  /// **'The delivery code is now available to your recipient. Only they can pass it to the traveler.'**
  String get pickupConfirmedSenderNext;

  /// Traveller copy after pickup is confirmed. States the invariant plainly.
  ///
  /// In en, this message translates to:
  /// **'Carry the parcel to the recipient. They read you the delivery code at the door — you are never shown it yourself.'**
  String get pickupConfirmedTravelerNext;

  /// No description provided for @deliverySafetyWaitingTitle.
  ///
  /// In en, this message translates to:
  /// **'Waiting for the safety period'**
  String get deliverySafetyWaitingTitle;

  /// No description provided for @deliverySafetyWaitingSenderBody.
  ///
  /// In en, this message translates to:
  /// **'Pickup is confirmed. Delivery confirmation becomes available after the safety period; then Wassla emails the delivery code to your recipient.'**
  String get deliverySafetyWaitingSenderBody;

  /// No description provided for @deliverySafetyWaitingTravelerBody.
  ///
  /// In en, this message translates to:
  /// **'Pickup is confirmed. Continue to the recipient. After the safety period, ask them for the delivery code — Wassla never shows it to you.'**
  String get deliverySafetyWaitingTravelerBody;

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
  /// **'The recipient receives this code by email. They read it to the traveler at the door, and that is what confirms the delivery.'**
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
  /// **'The traveler\'s payout goes on hold'**
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
  /// **'The traveler'**
  String get disputeOpenedByTraveler;

  /// Row label for when the dispute was opened.
  ///
  /// In en, this message translates to:
  /// **'Opened'**
  String get disputeOpenedAtLabel;

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
  /// **'These amounts are Wassla\'s decision. Nothing here is worked out on your phone.'**
  String get disputeAmountsExplainer;

  /// Breakdown line for the total the sender originally paid.
  ///
  /// In en, this message translates to:
  /// **'Collected from the sender'**
  String get disputeCollectedTotal;

  /// Row label for the resolution note.
  ///
  /// In en, this message translates to:
  /// **'Note from Wassla'**
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

  /// No description provided for @onboardingStamp.
  ///
  /// In en, this message translates to:
  /// **'EST. 2026 · ALG ↔ FR'**
  String get onboardingStamp;

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
  /// **'Travelers carry your parcel as part of their luggage. You pay a sliver of express shipping.'**
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
  /// **'HANDOVER CODE'**
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

  /// No description provided for @requestItemPhoto.
  ///
  /// In en, this message translates to:
  /// **'Photo of the item'**
  String get requestItemPhoto;

  /// No description provided for @requestItemPhotoHelp.
  ///
  /// In en, this message translates to:
  /// **'Add a clear photo of what you\'re sending. Travelers decide from this.'**
  String get requestItemPhotoHelp;

  /// No description provided for @requestItemPhotoChoose.
  ///
  /// In en, this message translates to:
  /// **'Choose a photo'**
  String get requestItemPhotoChoose;

  /// No description provided for @requestItemPhotoFromGallery.
  ///
  /// In en, this message translates to:
  /// **'From gallery'**
  String get requestItemPhotoFromGallery;

  /// No description provided for @requestItemPhotoTakePhoto.
  ///
  /// In en, this message translates to:
  /// **'Take a photo'**
  String get requestItemPhotoTakePhoto;

  /// No description provided for @requestItemPhotoReplace.
  ///
  /// In en, this message translates to:
  /// **'Replace'**
  String get requestItemPhotoReplace;

  /// No description provided for @requestItemPhotoRemove.
  ///
  /// In en, this message translates to:
  /// **'Remove photo'**
  String get requestItemPhotoRemove;

  /// No description provided for @requestItemPhotoUploading.
  ///
  /// In en, this message translates to:
  /// **'Uploading your photo…'**
  String get requestItemPhotoUploading;

  /// No description provided for @requestItemPhotoReady.
  ///
  /// In en, this message translates to:
  /// **'Photo added'**
  String get requestItemPhotoReady;

  /// No description provided for @requestItemPhotoRequired.
  ///
  /// In en, this message translates to:
  /// **'A photo of the item is required.'**
  String get requestItemPhotoRequired;

  /// No description provided for @requestItemPhotoFormatRule.
  ///
  /// In en, this message translates to:
  /// **'JPEG, PNG or WebP, up to 10 MB.'**
  String get requestItemPhotoFormatRule;

  /// No description provided for @requestItemPhotoTooLarge.
  ///
  /// In en, this message translates to:
  /// **'That image is too large. Choose one under 10 MB.'**
  String get requestItemPhotoTooLarge;

  /// No description provided for @requestItemPhotoTypeNotAllowed.
  ///
  /// In en, this message translates to:
  /// **'That file type isn\'t accepted. Use a JPEG, PNG or WebP image.'**
  String get requestItemPhotoTypeNotAllowed;

  /// No description provided for @requestItemPhotoUploadFailed.
  ///
  /// In en, this message translates to:
  /// **'The photo didn\'t upload. It\'s still selected — try again.'**
  String get requestItemPhotoUploadFailed;

  /// No description provided for @requestItemPhotoStorageUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Photo storage is unavailable right now. Try again in a moment.'**
  String get requestItemPhotoStorageUnavailable;

  /// No description provided for @requestItemPhotoPrivacy.
  ///
  /// In en, this message translates to:
  /// **'Only travelers who can see this request can see the photo.'**
  String get requestItemPhotoPrivacy;

  /// No description provided for @fieldOptional.
  ///
  /// In en, this message translates to:
  /// **'Optional'**
  String get fieldOptional;

  /// No description provided for @requestDimensionsOptionalHelp.
  ///
  /// In en, this message translates to:
  /// **'Optional. Leave empty if you haven\'t measured it — or enter all three.'**
  String get requestDimensionsOptionalHelp;

  /// No description provided for @requestDimensionsPartialFix.
  ///
  /// In en, this message translates to:
  /// **'Enter length, width and height together, or clear all three.'**
  String get requestDimensionsPartialFix;

  /// No description provided for @formFixBeforeContinuing.
  ///
  /// In en, this message translates to:
  /// **'Fix the highlighted field before continuing.'**
  String get formFixBeforeContinuing;

  /// Shown when a step cannot be left because fields are invalid.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{Fix 1 field before continuing.} other{Fix {count} fields before continuing.}}'**
  String formFixCountBeforeContinuing(int count);

  /// No description provided for @formServerRefusedOnStep.
  ///
  /// In en, this message translates to:
  /// **'The server refused this request. The problem is on this step, marked below.'**
  String get formServerRefusedOnStep;

  /// No description provided for @pushPermissionHeading.
  ///
  /// In en, this message translates to:
  /// **'On this phone'**
  String get pushPermissionHeading;

  /// No description provided for @pushPermissionBody.
  ///
  /// In en, this message translates to:
  /// **'Get timely updates about offers, payments, delivery, messages and verification. Wassla asks once, when you first open the app, and you can enable notifications here at any time.'**
  String get pushPermissionBody;

  /// No description provided for @pushPermissionEnabled.
  ///
  /// In en, this message translates to:
  /// **'Notifications are enabled.'**
  String get pushPermissionEnabled;

  /// No description provided for @pushPermissionEnabledGuest.
  ///
  /// In en, this message translates to:
  /// **'Notifications are allowed on this phone. Sign in and Wassla will start sending them here.'**
  String get pushPermissionEnabledGuest;

  /// No description provided for @pushGuestSignInNote.
  ///
  /// In en, this message translates to:
  /// **'Sign in to receive notifications for your account and to choose which kinds you get.'**
  String get pushGuestSignInNote;

  /// No description provided for @pushPermissionDeniedRequestable.
  ///
  /// In en, this message translates to:
  /// **'Notifications are still off. Choose Enable notifications to ask Android again. Your in-app inbox keeps working either way.'**
  String get pushPermissionDeniedRequestable;

  /// No description provided for @pushPermissionDeniedRequestableGuest.
  ///
  /// In en, this message translates to:
  /// **'Notifications are still off. Choose Enable notifications to ask Android again.'**
  String get pushPermissionDeniedRequestableGuest;

  /// No description provided for @pushPermissionDenied.
  ///
  /// In en, this message translates to:
  /// **'Notifications are off at system level. You can enable them in Settings.'**
  String get pushPermissionDenied;

  /// No description provided for @pushPermissionUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Push is not configured in this build. In-app notifications still work.'**
  String get pushPermissionUnavailable;

  /// No description provided for @pushPermissionInitializationFailed.
  ///
  /// In en, this message translates to:
  /// **'Push could not start on this phone. Your in-app notifications still work; reopen Wassla to try again.'**
  String get pushPermissionInitializationFailed;

  /// No description provided for @pushPermissionUnavailableGuest.
  ///
  /// In en, this message translates to:
  /// **'Push is not configured in this build.'**
  String get pushPermissionUnavailableGuest;

  /// No description provided for @pushPermissionInitializationFailedGuest.
  ///
  /// In en, this message translates to:
  /// **'Push could not start on this phone. Reopen Wassla to try again.'**
  String get pushPermissionInitializationFailedGuest;

  /// No description provided for @pushEnableAction.
  ///
  /// In en, this message translates to:
  /// **'Enable notifications'**
  String get pushEnableAction;

  /// No description provided for @pushOpenSettingsAction.
  ///
  /// In en, this message translates to:
  /// **'Open notification settings'**
  String get pushOpenSettingsAction;

  /// No description provided for @pushRegistrationPending.
  ///
  /// In en, this message translates to:
  /// **'System notification permission is on. Wassla is finishing notification setup for this phone.'**
  String get pushRegistrationPending;

  /// No description provided for @pushRegistrationFailed.
  ///
  /// In en, this message translates to:
  /// **'System notification permission is on, but Wassla could not finish registering this phone. Check your connection and try again.'**
  String get pushRegistrationFailed;

  /// No description provided for @pushRetryRegistrationAction.
  ///
  /// In en, this message translates to:
  /// **'Retry notification setup'**
  String get pushRetryRegistrationAction;

  /// No description provided for @pushPreferencesHeading.
  ///
  /// In en, this message translates to:
  /// **'Notification types'**
  String get pushPreferencesHeading;

  /// No description provided for @pushPreferencesBody.
  ///
  /// In en, this message translates to:
  /// **'These choices control messages and marketplace activity. They do not change this phone\'s system permission, and essential delivery and account updates stay available.'**
  String get pushPreferencesBody;

  /// No description provided for @pushEssentialTitle.
  ///
  /// In en, this message translates to:
  /// **'Essential updates'**
  String get pushEssentialTitle;

  /// No description provided for @pushEssentialBody.
  ///
  /// In en, this message translates to:
  /// **'Payment, delivery, dispute, verification and account-security updates stay on.'**
  String get pushEssentialBody;

  /// No description provided for @pushMessagesTitle.
  ///
  /// In en, this message translates to:
  /// **'Messages'**
  String get pushMessagesTitle;

  /// No description provided for @pushMessagesBody.
  ///
  /// In en, this message translates to:
  /// **'New chat activity.'**
  String get pushMessagesBody;

  /// No description provided for @pushMarketplaceTitle.
  ///
  /// In en, this message translates to:
  /// **'Marketplace activity'**
  String get pushMarketplaceTitle;

  /// No description provided for @pushMarketplaceBody.
  ///
  /// In en, this message translates to:
  /// **'Offers, matches, journeys and requests.'**
  String get pushMarketplaceBody;

  /// No description provided for @notificationAccount.
  ///
  /// In en, this message translates to:
  /// **'Verification update'**
  String get notificationAccount;

  /// No description provided for @notificationDispute.
  ///
  /// In en, this message translates to:
  /// **'Dispute update'**
  String get notificationDispute;

  /// No description provided for @notificationPayout.
  ///
  /// In en, this message translates to:
  /// **'Payout update'**
  String get notificationPayout;

  /// No description provided for @payoutMethodsTitle.
  ///
  /// In en, this message translates to:
  /// **'Payout methods'**
  String get payoutMethodsTitle;

  /// No description provided for @profilePayoutMethods.
  ///
  /// In en, this message translates to:
  /// **'Payout methods'**
  String get profilePayoutMethods;

  /// No description provided for @payoutPreferenceTitle.
  ///
  /// In en, this message translates to:
  /// **'Payout preference'**
  String get payoutPreferenceTitle;

  /// No description provided for @payoutPreferenceEurOnly.
  ///
  /// In en, this message translates to:
  /// **'EUR only'**
  String get payoutPreferenceEurOnly;

  /// No description provided for @payoutPreferenceDzdOnly.
  ///
  /// In en, this message translates to:
  /// **'DZD only'**
  String get payoutPreferenceDzdOnly;

  /// No description provided for @payoutPreferenceBoth.
  ///
  /// In en, this message translates to:
  /// **'Both'**
  String get payoutPreferenceBoth;

  /// No description provided for @payoutPreferenceBothExplainer.
  ///
  /// In en, this message translates to:
  /// **'Stripe-funded deliveries are paid in EUR; Chargily-funded deliveries are paid in DZD.'**
  String get payoutPreferenceBothExplainer;

  /// No description provided for @payoutPreferenceScopeNote.
  ///
  /// In en, this message translates to:
  /// **'Preferences apply to future payouts only.'**
  String get payoutPreferenceScopeNote;

  /// No description provided for @payoutEurTitle.
  ///
  /// In en, this message translates to:
  /// **'EUR payouts (Stripe)'**
  String get payoutEurTitle;

  /// No description provided for @payoutEurNotConfiguredBody.
  ///
  /// In en, this message translates to:
  /// **'Connect your European bank account to receive payouts in EUR.'**
  String get payoutEurNotConfiguredBody;

  /// No description provided for @payoutEurSetupRequiredBody.
  ///
  /// In en, this message translates to:
  /// **'Complete your account setup with Stripe to enable EUR payouts.'**
  String get payoutEurSetupRequiredBody;

  /// No description provided for @payoutEurPendingVerificationBody.
  ///
  /// In en, this message translates to:
  /// **'Stripe is verifying your account details. You\'ll be notified once approved.'**
  String get payoutEurPendingVerificationBody;

  /// No description provided for @payoutEurReadyBody.
  ///
  /// In en, this message translates to:
  /// **'Your EUR account is verified and ready to receive payouts.'**
  String get payoutEurReadyBody;

  /// No description provided for @payoutEurNeedsAttentionBody.
  ///
  /// In en, this message translates to:
  /// **'Your Stripe account requires attention before payouts can proceed.'**
  String get payoutEurNeedsAttentionBody;

  /// No description provided for @payoutActionSetupEur.
  ///
  /// In en, this message translates to:
  /// **'Set up EUR payouts'**
  String get payoutActionSetupEur;

  /// No description provided for @payoutActionResumeEur.
  ///
  /// In en, this message translates to:
  /// **'Resume setup'**
  String get payoutActionResumeEur;

  /// No description provided for @payoutActionManageEur.
  ///
  /// In en, this message translates to:
  /// **'Manage with Stripe'**
  String get payoutActionManageEur;

  /// No description provided for @payoutActionRefresh.
  ///
  /// In en, this message translates to:
  /// **'Refresh status'**
  String get payoutActionRefresh;

  /// No description provided for @payoutDzdTitle.
  ///
  /// In en, this message translates to:
  /// **'DZD payouts (CCP / BaridiMob)'**
  String get payoutDzdTitle;

  /// No description provided for @payoutDzdNotConfiguredBody.
  ///
  /// In en, this message translates to:
  /// **'Add your CCP account and crossed cheque to receive payouts in Algeria.'**
  String get payoutDzdNotConfiguredBody;

  /// No description provided for @payoutDzdSetupRequiredBody.
  ///
  /// In en, this message translates to:
  /// **'Submit your CCP information and crossed cheque to proceed.'**
  String get payoutDzdSetupRequiredBody;

  /// No description provided for @payoutDzdPendingReviewBody.
  ///
  /// In en, this message translates to:
  /// **'Your CCP details and crossed cheque are being reviewed by our team.'**
  String get payoutDzdPendingReviewBody;

  /// No description provided for @payoutDzdReadyBody.
  ///
  /// In en, this message translates to:
  /// **'Your CCP account is verified and ready for DZD payouts.'**
  String get payoutDzdReadyBody;

  /// No description provided for @payoutDzdNeedsAttentionBody.
  ///
  /// In en, this message translates to:
  /// **'Your payout profile requires verification or an update.'**
  String get payoutDzdNeedsAttentionBody;

  /// No description provided for @payoutDzdRejectedBody.
  ///
  /// In en, this message translates to:
  /// **'This CCP account was not accepted for payouts. Submit a different account in your own name.'**
  String get payoutDzdRejectedBody;

  /// No description provided for @payoutDzdCorrectionBody.
  ///
  /// In en, this message translates to:
  /// **'Your payout details need a correction. Submit them again with a clear photo of the whole crossed cheque.'**
  String get payoutDzdCorrectionBody;

  /// No description provided for @payoutDzdInactiveBody.
  ///
  /// In en, this message translates to:
  /// **'DZD payouts are currently inactive for your account.'**
  String get payoutDzdInactiveBody;

  /// No description provided for @payoutActionSetupDzd.
  ///
  /// In en, this message translates to:
  /// **'Set up DZD payouts'**
  String get payoutActionSetupDzd;

  /// No description provided for @payoutActionReplaceDzd.
  ///
  /// In en, this message translates to:
  /// **'Update payout information'**
  String get payoutActionReplaceDzd;

  /// No description provided for @payoutDzdCcpLabel.
  ///
  /// In en, this message translates to:
  /// **'CCP account'**
  String get payoutDzdCcpLabel;

  /// No description provided for @payoutDzdRipLabel.
  ///
  /// In en, this message translates to:
  /// **'RIP'**
  String get payoutDzdRipLabel;

  /// No description provided for @dzdFormTitle.
  ///
  /// In en, this message translates to:
  /// **'Set up DZD payouts'**
  String get dzdFormTitle;

  /// No description provided for @dzdFormScopeExplainer.
  ///
  /// In en, this message translates to:
  /// **'This information applies to future eligible payouts. Already-funded payouts keep their historical payout destination.'**
  String get dzdFormScopeExplainer;

  /// No description provided for @dzdFirstNameLabel.
  ///
  /// In en, this message translates to:
  /// **'First name'**
  String get dzdFirstNameLabel;

  /// No description provided for @dzdLastNameLabel.
  ///
  /// In en, this message translates to:
  /// **'Last name'**
  String get dzdLastNameLabel;

  /// No description provided for @dzdCcpNumberLabel.
  ///
  /// In en, this message translates to:
  /// **'CCP account number'**
  String get dzdCcpNumberLabel;

  /// No description provided for @dzdCcpNumberHint.
  ///
  /// In en, this message translates to:
  /// **'1 to 20 digits'**
  String get dzdCcpNumberHint;

  /// No description provided for @dzdCcpKeyLabel.
  ///
  /// In en, this message translates to:
  /// **'CCP key'**
  String get dzdCcpKeyLabel;

  /// No description provided for @dzdCcpKeyHint.
  ///
  /// In en, this message translates to:
  /// **'2 digits'**
  String get dzdCcpKeyHint;

  /// No description provided for @dzdRipLabel.
  ///
  /// In en, this message translates to:
  /// **'RIP'**
  String get dzdRipLabel;

  /// No description provided for @dzdRipHint.
  ///
  /// In en, this message translates to:
  /// **'20 digits'**
  String get dzdRipHint;

  /// No description provided for @dzdChequeProofLabel.
  ///
  /// In en, this message translates to:
  /// **'Photo of the full crossed cheque'**
  String get dzdChequeProofLabel;

  /// No description provided for @dzdChequeProofHelper.
  ///
  /// In en, this message translates to:
  /// **'Upload a clear photo of the full crossed cheque.'**
  String get dzdChequeProofHelper;

  /// No description provided for @dzdChequeAddPhoto.
  ///
  /// In en, this message translates to:
  /// **'Upload photo'**
  String get dzdChequeAddPhoto;

  /// No description provided for @dzdChequeReplacePhoto.
  ///
  /// In en, this message translates to:
  /// **'Replace photo'**
  String get dzdChequeReplacePhoto;

  /// No description provided for @dzdSubmitAction.
  ///
  /// In en, this message translates to:
  /// **'Submit payout information'**
  String get dzdSubmitAction;

  /// No description provided for @dzdSubmitSuccess.
  ///
  /// In en, this message translates to:
  /// **'Payout information submitted successfully.'**
  String get dzdSubmitSuccess;

  /// No description provided for @payoutReasonSetupRequired.
  ///
  /// In en, this message translates to:
  /// **'Payout setup required'**
  String get payoutReasonSetupRequired;

  /// No description provided for @payoutReasonUnderReview.
  ///
  /// In en, this message translates to:
  /// **'Profile under review'**
  String get payoutReasonUnderReview;

  /// No description provided for @payoutReasonNeedsAttention.
  ///
  /// In en, this message translates to:
  /// **'Profile needs attention'**
  String get payoutReasonNeedsAttention;

  /// No description provided for @payoutReasonOnHold.
  ///
  /// In en, this message translates to:
  /// **'Payout on hold'**
  String get payoutReasonOnHold;

  /// No description provided for @payoutReasonDisputeActive.
  ///
  /// In en, this message translates to:
  /// **'Dispute open on this delivery'**
  String get payoutReasonDisputeActive;

  /// No description provided for @payoutReasonFailed.
  ///
  /// In en, this message translates to:
  /// **'Payout attempt failed'**
  String get payoutReasonFailed;

  /// No description provided for @payoutReasonReturned.
  ///
  /// In en, this message translates to:
  /// **'Bank payout was returned'**
  String get payoutReasonReturned;

  /// No description provided for @payoutReasonCountryUnsupported.
  ///
  /// In en, this message translates to:
  /// **'Country not supported for Stripe EUR payouts'**
  String get payoutReasonCountryUnsupported;

  /// No description provided for @payoutRateLabel.
  ///
  /// In en, this message translates to:
  /// **'Frozen rate: 1 EUR = {rate} DZD'**
  String payoutRateLabel(String rate);

  /// No description provided for @payoutHistoryTitle.
  ///
  /// In en, this message translates to:
  /// **'Payout history'**
  String get payoutHistoryTitle;

  /// No description provided for @payoutDetailTitle.
  ///
  /// In en, this message translates to:
  /// **'Payout detail'**
  String get payoutDetailTitle;

  /// No description provided for @payoutRailLabel.
  ///
  /// In en, this message translates to:
  /// **'Payout rail'**
  String get payoutRailLabel;

  /// No description provided for @payoutRailStripeEur.
  ///
  /// In en, this message translates to:
  /// **'Stripe EUR'**
  String get payoutRailStripeEur;

  /// No description provided for @payoutRailManualDzd.
  ///
  /// In en, this message translates to:
  /// **'CCP Transfer (DZD)'**
  String get payoutRailManualDzd;

  /// No description provided for @payoutRailUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Unavailable'**
  String get payoutRailUnavailable;

  /// No description provided for @payoutReferenceLabel.
  ///
  /// In en, this message translates to:
  /// **'Payout reference'**
  String get payoutReferenceLabel;

  /// No description provided for @payoutDeliveryLabel.
  ///
  /// In en, this message translates to:
  /// **'Associated delivery'**
  String get payoutDeliveryLabel;

  /// No description provided for @payoutEligibleAtLabel.
  ///
  /// In en, this message translates to:
  /// **'Eligible at'**
  String get payoutEligibleAtLabel;

  /// No description provided for @payoutSentAtLabel.
  ///
  /// In en, this message translates to:
  /// **'Sent at'**
  String get payoutSentAtLabel;

  /// No description provided for @payoutPaidAtLabel.
  ///
  /// In en, this message translates to:
  /// **'Paid at'**
  String get payoutPaidAtLabel;

  /// No description provided for @payoutProtectionEndsAtLabel.
  ///
  /// In en, this message translates to:
  /// **'Protection ends at'**
  String get payoutProtectionEndsAtLabel;

  /// No description provided for @payoutViewAction.
  ///
  /// In en, this message translates to:
  /// **'View payout'**
  String get payoutViewAction;

  /// No description provided for @payoutViewHistoryAction.
  ///
  /// In en, this message translates to:
  /// **'View payout history'**
  String get payoutViewHistoryAction;

  /// No description provided for @payoutOpenStripeError.
  ///
  /// In en, this message translates to:
  /// **'Could not open Stripe setup link. Please try again.'**
  String get payoutOpenStripeError;

  /// No description provided for @payoutStatusAwaitingDelivery.
  ///
  /// In en, this message translates to:
  /// **'Awaiting delivery'**
  String get payoutStatusAwaitingDelivery;

  /// No description provided for @payoutStatusProtectionActive.
  ///
  /// In en, this message translates to:
  /// **'Protection period'**
  String get payoutStatusProtectionActive;

  /// No description provided for @payoutStatusReleasePending.
  ///
  /// In en, this message translates to:
  /// **'Awaiting release'**
  String get payoutStatusReleasePending;

  /// No description provided for @payoutStatusReady.
  ///
  /// In en, this message translates to:
  /// **'Payout ready'**
  String get payoutStatusReady;

  /// No description provided for @payoutStatusSent.
  ///
  /// In en, this message translates to:
  /// **'Payout sent'**
  String get payoutStatusSent;

  /// No description provided for @payoutStatusNeedsAttention.
  ///
  /// In en, this message translates to:
  /// **'Needs attention'**
  String get payoutStatusNeedsAttention;

  /// No description provided for @payoutProfileReady.
  ///
  /// In en, this message translates to:
  /// **'Payout method ready'**
  String get payoutProfileReady;

  /// No description provided for @payoutProfileNeedsAttention.
  ///
  /// In en, this message translates to:
  /// **'Method needs attention'**
  String get payoutProfileNeedsAttention;

  /// No description provided for @earlyArrivalAction.
  ///
  /// In en, this message translates to:
  /// **'I arrived early'**
  String get earlyArrivalAction;

  /// No description provided for @earlyArrivalConfirmSheetTitle.
  ///
  /// In en, this message translates to:
  /// **'Report early arrival'**
  String get earlyArrivalConfirmSheetTitle;

  /// No description provided for @earlyArrivalConfirmSheetBody.
  ///
  /// In en, this message translates to:
  /// **'This notifies the sender that you arrived before the scheduled arrival. It does not confirm delivery of the parcel. The sender must confirm your arrival, and payout timing still follows Wassla protection rules.'**
  String get earlyArrivalConfirmSheetBody;

  /// No description provided for @earlyArrivalWaitingSenderTitle.
  ///
  /// In en, this message translates to:
  /// **'Waiting for Sender confirmation'**
  String get earlyArrivalWaitingSenderTitle;

  /// No description provided for @earlyArrivalWaitingSenderBody.
  ///
  /// In en, this message translates to:
  /// **'You reported your early arrival. The sender has been notified to confirm it. Handover and delivery remain separate.'**
  String get earlyArrivalWaitingSenderBody;

  /// No description provided for @earlyArrivalSenderNoticeTitle.
  ///
  /// In en, this message translates to:
  /// **'Traveler says they arrived early'**
  String get earlyArrivalSenderNoticeTitle;

  /// No description provided for @earlyArrivalSenderNoticeBody.
  ///
  /// In en, this message translates to:
  /// **'The traveler reported early arrival for this delivery. Confirming arrival acknowledges their presence; parcel delivery and payout protection remain separate.'**
  String get earlyArrivalSenderNoticeBody;

  /// No description provided for @earlyArrivalConfirmAction.
  ///
  /// In en, this message translates to:
  /// **'Confirm arrival'**
  String get earlyArrivalConfirmAction;

  /// No description provided for @earlyArrivalDeclineAction.
  ///
  /// In en, this message translates to:
  /// **'Decline'**
  String get earlyArrivalDeclineAction;

  /// No description provided for @earlyArrivalConfirmedTitle.
  ///
  /// In en, this message translates to:
  /// **'Arrival confirmed'**
  String get earlyArrivalConfirmedTitle;

  /// No description provided for @earlyArrivalConfirmedBody.
  ///
  /// In en, this message translates to:
  /// **'Early arrival is confirmed. Parcel delivery and 48-hour protection will begin only after the delivery code is verified.'**
  String get earlyArrivalConfirmedBody;

  /// No description provided for @earlyArrivalDeclinedTitle.
  ///
  /// In en, this message translates to:
  /// **'Early arrival not confirmed'**
  String get earlyArrivalDeclinedTitle;

  /// No description provided for @earlyArrivalDeclinedBody.
  ///
  /// In en, this message translates to:
  /// **'The early arrival report was not confirmed. Delivery will proceed according to the scheduled route.'**
  String get earlyArrivalDeclinedBody;

  /// No description provided for @earlyArrivalScheduledArrivalLabel.
  ///
  /// In en, this message translates to:
  /// **'Scheduled arrival for this delivery'**
  String get earlyArrivalScheduledArrivalLabel;

  /// No description provided for @earlyArrivalPayoutFloorExplanation.
  ///
  /// In en, this message translates to:
  /// **'Arriving early does not make the payout available earlier than the protected payout date for this delivery.'**
  String get earlyArrivalPayoutFloorExplanation;

  /// No description provided for @earlyArrivalPayoutProtectedGateLabel.
  ///
  /// In en, this message translates to:
  /// **'Payout eligible from'**
  String get earlyArrivalPayoutProtectedGateLabel;

  /// No description provided for @routeTitle.
  ///
  /// In en, this message translates to:
  /// **'Route'**
  String get routeTitle;

  /// No description provided for @routeUnavailableFunded.
  ///
  /// In en, this message translates to:
  /// **'The travel route was not recorded for this delivery.'**
  String get routeUnavailableFunded;

  /// No description provided for @routeUnavailableBeforeFunding.
  ///
  /// In en, this message translates to:
  /// **'The travel route appears here once the delivery is funded.'**
  String get routeUnavailableBeforeFunding;

  /// No description provided for @routeFlightMode.
  ///
  /// In en, this message translates to:
  /// **'Flight'**
  String get routeFlightMode;

  /// No description provided for @routeDriveMode.
  ///
  /// In en, this message translates to:
  /// **'Drive'**
  String get routeDriveMode;

  /// No description provided for @notificationArrivalReported.
  ///
  /// In en, this message translates to:
  /// **'Traveler arrived early'**
  String get notificationArrivalReported;

  /// No description provided for @notificationArrivalConfirmed.
  ///
  /// In en, this message translates to:
  /// **'Early arrival confirmed'**
  String get notificationArrivalConfirmed;

  /// No description provided for @notificationArrivalDeclined.
  ///
  /// In en, this message translates to:
  /// **'Early arrival not confirmed'**
  String get notificationArrivalDeclined;

  /// No description provided for @routeBasisSnapshot.
  ///
  /// In en, this message translates to:
  /// **'Frozen at booking'**
  String get routeBasisSnapshot;

  /// No description provided for @routeBasisLive.
  ///
  /// In en, this message translates to:
  /// **'Live journey'**
  String get routeBasisLive;

  /// No description provided for @pricingMinimumLabel.
  ///
  /// In en, this message translates to:
  /// **'Minimum price'**
  String get pricingMinimumLabel;

  /// No description provided for @pricingRecommendedLabel.
  ///
  /// In en, this message translates to:
  /// **'Recommended price'**
  String get pricingRecommendedLabel;

  /// No description provided for @pricingYourOfferLabel.
  ///
  /// In en, this message translates to:
  /// **'Your offer'**
  String get pricingYourOfferLabel;

  /// No description provided for @pricingBelowRecommended.
  ///
  /// In en, this message translates to:
  /// **'Below recommendation — travelers may take longer to accept.'**
  String get pricingBelowRecommended;

  /// No description provided for @pricingCompetitive.
  ///
  /// In en, this message translates to:
  /// **'Competitive offer — matches more quickly with travelers.'**
  String get pricingCompetitive;

  /// No description provided for @pricingBelowMinimumError.
  ///
  /// In en, this message translates to:
  /// **'Offer must be at least {amount}'**
  String pricingBelowMinimumError(String amount);

  /// No description provided for @pricingTravelerReceives.
  ///
  /// In en, this message translates to:
  /// **'Traveler receives'**
  String get pricingTravelerReceives;

  /// No description provided for @pricingPlatformFee.
  ///
  /// In en, this message translates to:
  /// **'Wassla fee'**
  String get pricingPlatformFee;

  /// No description provided for @pricingTotalSenderCost.
  ///
  /// In en, this message translates to:
  /// **'Total sender cost'**
  String get pricingTotalSenderCost;

  /// No description provided for @pricingIncrement50c.
  ///
  /// In en, this message translates to:
  /// **'Increase by 50 cents'**
  String get pricingIncrement50c;

  /// No description provided for @pricingDecrement50c.
  ///
  /// In en, this message translates to:
  /// **'Decrease by 50 cents'**
  String get pricingDecrement50c;

  /// No description provided for @depositSectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Posting deposit'**
  String get depositSectionTitle;

  /// No description provided for @depositPresetMin.
  ///
  /// In en, this message translates to:
  /// **'Minimum ({amount})'**
  String depositPresetMin(String amount);

  /// No description provided for @depositPresetRecommended.
  ///
  /// In en, this message translates to:
  /// **'Recommended ({amount})'**
  String depositPresetRecommended(String amount);

  /// No description provided for @depositPresetFull.
  ///
  /// In en, this message translates to:
  /// **'Pay in full ({amount})'**
  String depositPresetFull(String amount);

  /// No description provided for @depositPresetCustom.
  ///
  /// In en, this message translates to:
  /// **'Custom'**
  String get depositPresetCustom;

  /// No description provided for @depositFullDepositNotice.
  ///
  /// In en, this message translates to:
  /// **'Your current amount is paid in full. If you increase the reward or Boost later, an additional balance may be due.'**
  String get depositFullDepositNotice;

  /// No description provided for @depositRemainingBalance.
  ///
  /// In en, this message translates to:
  /// **'Remaining balance at delivery'**
  String get depositRemainingBalance;

  /// No description provided for @depositCustomAmountLabel.
  ///
  /// In en, this message translates to:
  /// **'Custom deposit amount'**
  String get depositCustomAmountLabel;

  /// No description provided for @boostSectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Boost this request'**
  String get boostSectionTitle;

  /// No description provided for @boostPresetNone.
  ///
  /// In en, this message translates to:
  /// **'No Boost (€0)'**
  String get boostPresetNone;

  /// No description provided for @boostPreset5.
  ///
  /// In en, this message translates to:
  /// **'+€5'**
  String get boostPreset5;

  /// No description provided for @boostPreset10.
  ///
  /// In en, this message translates to:
  /// **'+€10'**
  String get boostPreset10;

  /// No description provided for @boostPresetCustom.
  ///
  /// In en, this message translates to:
  /// **'Custom'**
  String get boostPresetCustom;

  /// No description provided for @boostCustomAmountLabel.
  ///
  /// In en, this message translates to:
  /// **'Custom Boost amount'**
  String get boostCustomAmountLabel;

  /// No description provided for @boostCurrentActive.
  ///
  /// In en, this message translates to:
  /// **'Active Boost: {amount}'**
  String boostCurrentActive(String amount);

  /// No description provided for @boostEditAction.
  ///
  /// In en, this message translates to:
  /// **'Change Boost'**
  String get boostEditAction;

  /// No description provided for @boostAddAction.
  ///
  /// In en, this message translates to:
  /// **'Add Boost'**
  String get boostAddAction;

  /// No description provided for @boostPostPublicationOnly.
  ///
  /// In en, this message translates to:
  /// **'You can add a Boost now that this request is live. Travelers receive all of it.'**
  String get boostPostPublicationOnly;

  /// No description provided for @boostRemoveAction.
  ///
  /// In en, this message translates to:
  /// **'Remove Boost'**
  String get boostRemoveAction;

  /// No description provided for @boostHistoryTitle.
  ///
  /// In en, this message translates to:
  /// **'Boost history'**
  String get boostHistoryTitle;

  /// No description provided for @boostNotEditable.
  ///
  /// In en, this message translates to:
  /// **'Boost cannot be edited once an offer has been accepted or the request has expired.'**
  String get boostNotEditable;

  /// No description provided for @guestPaymentTitle.
  ///
  /// In en, this message translates to:
  /// **'Someone else can pay'**
  String get guestPaymentTitle;

  /// No description provided for @guestCreateAction.
  ///
  /// In en, this message translates to:
  /// **'Create payment link'**
  String get guestCreateAction;

  /// No description provided for @guestShareLead.
  ///
  /// In en, this message translates to:
  /// **'Share this secure payment link with someone you trust. They can pay without a Wassla account.'**
  String get guestShareLead;

  /// No description provided for @guestShareAction.
  ///
  /// In en, this message translates to:
  /// **'Share link'**
  String get guestShareAction;

  /// No description provided for @guestCopyAction.
  ///
  /// In en, this message translates to:
  /// **'Copy link'**
  String get guestCopyAction;

  /// No description provided for @guestCopiedAction.
  ///
  /// In en, this message translates to:
  /// **'Copied'**
  String get guestCopiedAction;

  /// No description provided for @guestLinkCopied.
  ///
  /// In en, this message translates to:
  /// **'Link copied'**
  String get guestLinkCopied;

  /// No description provided for @guestShareSubject.
  ///
  /// In en, this message translates to:
  /// **'Wassla payment request'**
  String get guestShareSubject;

  /// No description provided for @guestShareMessage.
  ///
  /// In en, this message translates to:
  /// **'Could you pay {amount} for my Wassla delivery? Here is the secure link: {link}'**
  String guestShareMessage(String amount, String link);

  /// No description provided for @guestLinkLabel.
  ///
  /// In en, this message translates to:
  /// **'Payment link'**
  String get guestLinkLabel;

  /// No description provided for @guestStatusReady.
  ///
  /// In en, this message translates to:
  /// **'Payment link ready'**
  String get guestStatusReady;

  /// No description provided for @guestStatusExpiresOn.
  ///
  /// In en, this message translates to:
  /// **'Expires {when}'**
  String guestStatusExpiresOn(String when);

  /// No description provided for @guestStatusPaying.
  ///
  /// In en, this message translates to:
  /// **'Someone is paying now'**
  String get guestStatusPaying;

  /// No description provided for @guestStatusPayingBody.
  ///
  /// In en, this message translates to:
  /// **'This updates by itself as soon as their payment goes through.'**
  String get guestStatusPayingBody;

  /// No description provided for @guestStatusExpired.
  ///
  /// In en, this message translates to:
  /// **'This payment link has expired'**
  String get guestStatusExpired;

  /// No description provided for @guestStatusRevoked.
  ///
  /// In en, this message translates to:
  /// **'This payment link is no longer active'**
  String get guestStatusRevoked;

  /// No description provided for @guestStatusNewLinkBody.
  ///
  /// In en, this message translates to:
  /// **'Create a new link if someone else should still pay.'**
  String get guestStatusNewLinkBody;

  /// No description provided for @guestStatusHidden.
  ///
  /// In en, this message translates to:
  /// **'Your earlier link still works'**
  String get guestStatusHidden;

  /// No description provided for @guestStatusHiddenBody.
  ///
  /// In en, this message translates to:
  /// **'For security it can’t be shown again. Create a new link to share — the earlier one will then stop working.'**
  String get guestStatusHiddenBody;

  /// No description provided for @guestStatusClosed.
  ///
  /// In en, this message translates to:
  /// **'This payment can no longer be made by link.'**
  String get guestStatusClosed;

  /// No description provided for @guestCreateNewAction.
  ///
  /// In en, this message translates to:
  /// **'Create a new payment link'**
  String get guestCreateNewAction;

  /// No description provided for @guestMoreActions.
  ///
  /// In en, this message translates to:
  /// **'More options'**
  String get guestMoreActions;

  /// No description provided for @guestRevokeAction.
  ///
  /// In en, this message translates to:
  /// **'Revoke link'**
  String get guestRevokeAction;

  /// No description provided for @guestRevokeConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Revoke this payment link?'**
  String get guestRevokeConfirmTitle;

  /// No description provided for @guestRevokeConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'Anyone who has it won’t be able to pay with it. You can create a new link afterwards.'**
  String get guestRevokeConfirmBody;

  /// No description provided for @guestRevokeKeep.
  ///
  /// In en, this message translates to:
  /// **'Keep link'**
  String get guestRevokeKeep;

  /// No description provided for @guestRevokedDone.
  ///
  /// In en, this message translates to:
  /// **'Link revoked'**
  String get guestRevokedDone;

  /// No description provided for @guestPaidTitle.
  ///
  /// In en, this message translates to:
  /// **'Payment received'**
  String get guestPaidTitle;

  /// No description provided for @guestPaidBody.
  ///
  /// In en, this message translates to:
  /// **'{amount} has been paid.'**
  String guestPaidBody(String amount);

  /// No description provided for @guestPaidBodyPlain.
  ///
  /// In en, this message translates to:
  /// **'The payment has been received.'**
  String get guestPaidBodyPlain;

  /// No description provided for @guestErrorLoad.
  ///
  /// In en, this message translates to:
  /// **'We couldn’t load your payment link. Check your connection and try again.'**
  String get guestErrorLoad;

  /// No description provided for @guestErrorBusy.
  ///
  /// In en, this message translates to:
  /// **'Someone is paying with your current link right now. Try again once they’ve finished.'**
  String get guestErrorBusy;

  /// No description provided for @guestErrorRevokeBusy.
  ///
  /// In en, this message translates to:
  /// **'Someone is paying with this link right now, so it can’t be revoked.'**
  String get guestErrorRevokeBusy;

  /// No description provided for @guestErrorRevoke.
  ///
  /// In en, this message translates to:
  /// **'We couldn’t revoke the link. Try again.'**
  String get guestErrorRevoke;

  /// No description provided for @guestErrorShare.
  ///
  /// In en, this message translates to:
  /// **'Sharing isn’t available right now. Copy the link instead.'**
  String get guestErrorShare;

  /// No description provided for @guestPurposeDeposit.
  ///
  /// In en, this message translates to:
  /// **'Deposit for your request'**
  String get guestPurposeDeposit;

  /// No description provided for @guestPurposeRemaining.
  ///
  /// In en, this message translates to:
  /// **'Remaining delivery payment'**
  String get guestPurposeRemaining;

  /// No description provided for @guestPurposeDelivery.
  ///
  /// In en, this message translates to:
  /// **'Delivery payment'**
  String get guestPurposeDelivery;

  /// No description provided for @guestPurposeBoost.
  ///
  /// In en, this message translates to:
  /// **'Boost payment'**
  String get guestPurposeBoost;

  /// No description provided for @guestPurposeOther.
  ///
  /// In en, this message translates to:
  /// **'Wassla payment'**
  String get guestPurposeOther;

  /// No description provided for @guestPayingNowTitle.
  ///
  /// In en, this message translates to:
  /// **'Someone else is paying this now'**
  String get guestPayingNowTitle;

  /// No description provided for @guestPayingNowBody.
  ///
  /// In en, this message translates to:
  /// **'They opened your payment link. This updates as soon as their payment goes through.'**
  String get guestPayingNowBody;

  /// No description provided for @guestPayPurposeDeposit.
  ///
  /// In en, this message translates to:
  /// **'Deposit for a delivery request'**
  String get guestPayPurposeDeposit;

  /// No description provided for @guestPayPurposeDelivery.
  ///
  /// In en, this message translates to:
  /// **'Payment for a delivery'**
  String get guestPayPurposeDelivery;

  /// No description provided for @guestPayPurposeBoost.
  ///
  /// In en, this message translates to:
  /// **'Extra reward for a delivery'**
  String get guestPayPurposeBoost;

  /// No description provided for @guestPayHandoff.
  ///
  /// In en, this message translates to:
  /// **'You’ll finish on our payment partner’s secure page. Wassla never sees your card details.'**
  String get guestPayHandoff;

  /// No description provided for @paymentSuccessAmountPaid.
  ///
  /// In en, this message translates to:
  /// **'Amount paid'**
  String get paymentSuccessAmountPaid;

  /// No description provided for @paymentSuccessViewRequestAction.
  ///
  /// In en, this message translates to:
  /// **'View request'**
  String get paymentSuccessViewRequestAction;

  /// No description provided for @paymentSuccessViewDeliveryAction.
  ///
  /// In en, this message translates to:
  /// **'View delivery'**
  String get paymentSuccessViewDeliveryAction;

  /// boostBreakdownTitle
  ///
  /// In en, this message translates to:
  /// **'What the Boost costs'**
  String get boostBreakdownTitle;

  /// boostTravelerBonusLabel
  ///
  /// In en, this message translates to:
  /// **'Added to the Traveler reward'**
  String get boostTravelerBonusLabel;

  /// boostYourCostLabel
  ///
  /// In en, this message translates to:
  /// **'You pay for the Boost'**
  String get boostYourCostLabel;

  /// boostAddsOnTop
  ///
  /// In en, this message translates to:
  /// **'The Boost is added on top of the delivery reward you already offered. Base reward + Boost is what the Traveler receives.'**
  String get boostAddsOnTop;

  /// boostEstimateNotice
  ///
  /// In en, this message translates to:
  /// **'An estimate until you save. Wassla confirms the final amounts.'**
  String get boostEstimateNotice;

  /// boostAmountAboveMaximum
  ///
  /// In en, this message translates to:
  /// **'The most you can Boost is {amount}'**
  String boostAmountAboveMaximum(String amount);

  /// boostHistoryReasonSenderSet
  ///
  /// In en, this message translates to:
  /// **'You added a Boost'**
  String get boostHistoryReasonSenderSet;

  /// boostHistoryReasonSenderIncreased
  ///
  /// In en, this message translates to:
  /// **'You raised the Boost'**
  String get boostHistoryReasonSenderIncreased;

  /// boostHistoryReasonSenderDecreased
  ///
  /// In en, this message translates to:
  /// **'You lowered the Boost'**
  String get boostHistoryReasonSenderDecreased;

  /// boostHistoryReasonSenderRemoved
  ///
  /// In en, this message translates to:
  /// **'You removed the Boost'**
  String get boostHistoryReasonSenderRemoved;

  /// boostHistoryReasonFrozen
  ///
  /// In en, this message translates to:
  /// **'Locked in when the delivery was agreed'**
  String get boostHistoryReasonFrozen;

  /// boostHistoryReasonConsumed
  ///
  /// In en, this message translates to:
  /// **'Included in the delivery payment'**
  String get boostHistoryReasonConsumed;

  /// boostHistoryReasonReleased
  ///
  /// In en, this message translates to:
  /// **'Released when the match fell through'**
  String get boostHistoryReasonReleased;

  /// boostHistoryReasonRequestClosed
  ///
  /// In en, this message translates to:
  /// **'Ended with the request'**
  String get boostHistoryReasonRequestClosed;

  /// boostHistoryReasonOther
  ///
  /// In en, this message translates to:
  /// **'Boost updated'**
  String get boostHistoryReasonOther;

  /// guestPaymentLinkFailed
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t create a payment link. Try again.'**
  String get guestPaymentLinkFailed;

  /// findTravelersCount
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 traveler} other{{count} travelers}}'**
  String findTravelersCount(int count);

  /// findTravelersIneligibleUnknown
  ///
  /// In en, this message translates to:
  /// **'This request can\'t be matched right now.'**
  String get findTravelersIneligibleUnknown;

  /// findTravelersPayDeposit
  ///
  /// In en, this message translates to:
  /// **'Pay deposit'**
  String get findTravelersPayDeposit;

  /// findTravelersDepartureLabel
  ///
  /// In en, this message translates to:
  /// **'Departs {when}'**
  String findTravelersDepartureLabel(String when);

  /// findTravelersArrivalLabel
  ///
  /// In en, this message translates to:
  /// **'Arrives {when}'**
  String findTravelersArrivalLabel(String when);

  /// findTravelersTrustTitle
  ///
  /// In en, this message translates to:
  /// **'Checks Wassla has done'**
  String get findTravelersTrustTitle;

  /// offerBaseRewardLabel
  ///
  /// In en, this message translates to:
  /// **'Base delivery reward'**
  String get offerBaseRewardLabel;

  /// offerBoostAddedOnTop
  ///
  /// In en, this message translates to:
  /// **'Your Boost of {amount} is added on top of this.'**
  String offerBoostAddedOnTop(String amount);

  /// deliveriesOpenOffersSection
  ///
  /// In en, this message translates to:
  /// **'Open offers'**
  String get deliveriesOpenOffersSection;

  /// journeyPostNew
  ///
  /// In en, this message translates to:
  /// **'Post a trip'**
  String get journeyPostNew;

  /// depositBelowMinimum
  ///
  /// In en, this message translates to:
  /// **'The smallest deposit is {amount}'**
  String depositBelowMinimum(String amount);

  /// depositAboveMaximum
  ///
  /// In en, this message translates to:
  /// **'That\'s more than the whole amount of {amount}'**
  String depositAboveMaximum(String amount);

  /// offerBoostIncludedTraveler
  ///
  /// In en, this message translates to:
  /// **'Includes the sender\'s Boost of {amount}. The total is locked in when you accept.'**
  String offerBoostIncludedTraveler(String amount);

  /// offerBoostIncludedSender
  ///
  /// In en, this message translates to:
  /// **'Includes your Boost of {amount}, locked in when this offer is accepted. Changing your Boost before then updates this offer.'**
  String offerBoostIncludedSender(String amount);

  /// offerSenderBoostAddedOnTop
  ///
  /// In en, this message translates to:
  /// **'The sender\'s Boost of {amount} is added on top of this.'**
  String offerSenderBoostAddedOnTop(String amount);

  /// offerHistoryBaseReward
  ///
  /// In en, this message translates to:
  /// **'{title}: base reward {amount}'**
  String offerHistoryBaseReward(String title, String amount);

  /// moneyTotalExcludingBoost
  ///
  /// In en, this message translates to:
  /// **'Total before any Boost'**
  String get moneyTotalExcludingBoost;

  /// staleOfferEconomicsChanged
  ///
  /// In en, this message translates to:
  /// **'The amounts on this offer changed. Check the new figures before accepting.'**
  String get staleOfferEconomicsChanged;

  /// Shown on an open offer when its amounts changed while the viewer was looking at it, for example because the sender changed their Boost.
  ///
  /// In en, this message translates to:
  /// **'Offer updated. These are the latest amounts.'**
  String get offerEconomicsUpdated;

  /// No description provided for @payResultAlreadyCompleteTitle.
  ///
  /// In en, this message translates to:
  /// **'This payment is already complete'**
  String get payResultAlreadyCompleteTitle;

  /// No description provided for @payResultCheckingTitle.
  ///
  /// In en, this message translates to:
  /// **'Checking your payment'**
  String get payResultCheckingTitle;

  /// No description provided for @payResultCheckingBody.
  ///
  /// In en, this message translates to:
  /// **'If you finished paying, it will show here in a moment. You don\'t need to pay again.'**
  String get payResultCheckingBody;

  /// No description provided for @payResultStillCheckingTitle.
  ///
  /// In en, this message translates to:
  /// **'We\'re still confirming your payment'**
  String get payResultStillCheckingTitle;

  /// No description provided for @payResultStillCheckingBody.
  ///
  /// In en, this message translates to:
  /// **'This is taking longer than usual. If the payment went through, it will appear here, and you won\'t be charged twice.'**
  String get payResultStillCheckingBody;

  /// No description provided for @payResultBackToPayment.
  ///
  /// In en, this message translates to:
  /// **'Back to payment'**
  String get payResultBackToPayment;

  /// No description provided for @payResultCancelledTitle.
  ///
  /// In en, this message translates to:
  /// **'Payment cancelled'**
  String get payResultCancelledTitle;

  /// No description provided for @payResultCancelledBody.
  ///
  /// In en, this message translates to:
  /// **'No completed payment was recorded. You can try again when you\'re ready.'**
  String get payResultCancelledBody;

  /// Payment result shown to the Sender when a guest payer paid. amount is the server's figure for that one payment. Never names the payer.
  ///
  /// In en, this message translates to:
  /// **'Someone else paid {amount} for this payment.'**
  String payResultSomeoneElsePaid(String amount);

  /// No description provided for @payResultRequestPublished.
  ///
  /// In en, this message translates to:
  /// **'Your request is now published'**
  String get payResultRequestPublished;

  /// No description provided for @payResultDepositNext.
  ///
  /// In en, this message translates to:
  /// **'Find a traveler going your way and send them an offer.'**
  String get payResultDepositNext;

  /// No description provided for @payResultPaidInFull.
  ///
  /// In en, this message translates to:
  /// **'Paid in full'**
  String get payResultPaidInFull;

  /// Deposit result when the deposit paid the whole current delivery total. Must not promise that nothing can ever be due again.
  ///
  /// In en, this message translates to:
  /// **'This covers your delivery total as it stands. If you later add a Boost or raise the reward, only the difference would be due.'**
  String get payResultDepositCoversTotal;

  /// No description provided for @payResultPaidNow.
  ///
  /// In en, this message translates to:
  /// **'Paid now'**
  String get payResultPaidNow;

  /// No description provided for @payResultDeliveryTotal.
  ///
  /// In en, this message translates to:
  /// **'Delivery total'**
  String get payResultDeliveryTotal;

  /// No description provided for @payResultRemaining.
  ///
  /// In en, this message translates to:
  /// **'Remaining'**
  String get payResultRemaining;

  /// Deal payment result when money is still owed after this payment. amount is the server's remaining balance.
  ///
  /// In en, this message translates to:
  /// **'Pay the remaining {amount} to confirm the delivery. The traveler can\'t collect the parcel until it\'s paid.'**
  String payResultRemainingNote(String amount);

  /// No description provided for @payResultDealNext.
  ///
  /// In en, this message translates to:
  /// **'Funds are held pending delivery. Follow the delivery steps to continue.'**
  String get payResultDealNext;

  /// No description provided for @payResultNextTitle.
  ///
  /// In en, this message translates to:
  /// **'What happens next'**
  String get payResultNextTitle;

  /// No description provided for @payResultBackHome.
  ///
  /// In en, this message translates to:
  /// **'Back to Home'**
  String get payResultBackHome;

  /// Button on a partial Deal payment result; amount is the server's remaining balance.
  ///
  /// In en, this message translates to:
  /// **'Pay remaining {amount}'**
  String payResultPayRemaining(String amount);

  /// Screen-reader label for the hero amount on a payment result: e.g. 'Amount paid: €42.50. Delivery payment'.
  ///
  /// In en, this message translates to:
  /// **'{label}: {amount}. {purpose}'**
  String a11yPaymentResultAmount(String label, String amount, String purpose);

  /// No description provided for @guestPayHandoffTitle.
  ///
  /// In en, this message translates to:
  /// **'Finish on the payment page'**
  String get guestPayHandoffTitle;

  /// No description provided for @guestPayHandoffBody.
  ///
  /// In en, this message translates to:
  /// **'Complete the payment on our payment partner\'s secure page. That page will show you the result, and the person who asked you will see it in Wassla.'**
  String get guestPayHandoffBody;

  /// No description provided for @payResultDepositCredited.
  ///
  /// In en, this message translates to:
  /// **'This deposit counts toward your delivery total when a traveler accepts.'**
  String get payResultDepositCredited;

  /// No description provided for @alertsTitle.
  ///
  /// In en, this message translates to:
  /// **'Route alerts'**
  String get alertsTitle;

  /// No description provided for @alertsIntro.
  ///
  /// In en, this message translates to:
  /// **'We send at most one notification per alert every few hours.'**
  String get alertsIntro;

  /// No description provided for @alertsEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No route alerts yet'**
  String get alertsEmptyTitle;

  /// No description provided for @alertsEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Get a notification when a trip or a parcel appears on a route you care about.'**
  String get alertsEmptyBody;

  /// No description provided for @alertAdd.
  ///
  /// In en, this message translates to:
  /// **'Add alert'**
  String get alertAdd;

  /// No description provided for @alertAddTitle.
  ///
  /// In en, this message translates to:
  /// **'New route alert'**
  String get alertAddTitle;

  /// No description provided for @alertAddSubtitle.
  ///
  /// In en, this message translates to:
  /// **'We\'ll notify you when something new appears on this route.'**
  String get alertAddSubtitle;

  /// No description provided for @alertCreate.
  ///
  /// In en, this message translates to:
  /// **'Create alert'**
  String get alertCreate;

  /// No description provided for @alertPickCity.
  ///
  /// In en, this message translates to:
  /// **'Choose a city'**
  String get alertPickCity;

  /// No description provided for @alertWatchLabel.
  ///
  /// In en, this message translates to:
  /// **'Watch for'**
  String get alertWatchLabel;

  /// No description provided for @alertWatchesTrips.
  ///
  /// In en, this message translates to:
  /// **'New trips'**
  String get alertWatchesTrips;

  /// No description provided for @alertWatchesRequests.
  ///
  /// In en, this message translates to:
  /// **'New parcels'**
  String get alertWatchesRequests;

  /// No description provided for @alertFollowing.
  ///
  /// In en, this message translates to:
  /// **'Following {name}'**
  String alertFollowing(String name);

  /// No description provided for @alertRemoveA11y.
  ///
  /// In en, this message translates to:
  /// **'Remove alert for {route}'**
  String alertRemoveA11y(String route);

  /// No description provided for @alertRemoved.
  ///
  /// In en, this message translates to:
  /// **'Alert removed'**
  String get alertRemoved;

  /// No description provided for @alertSwitchLabel.
  ///
  /// In en, this message translates to:
  /// **'Alert me about this route'**
  String get alertSwitchLabel;

  /// No description provided for @alertTurnedOn.
  ///
  /// In en, this message translates to:
  /// **'Alert turned on'**
  String get alertTurnedOn;

  /// No description provided for @alertTurnedOff.
  ///
  /// In en, this message translates to:
  /// **'Alert turned off'**
  String get alertTurnedOff;

  /// No description provided for @alertLimitReached.
  ///
  /// In en, this message translates to:
  /// **'You have reached the maximum number of active alerts. Remove one to add another.'**
  String get alertLimitReached;

  /// No description provided for @alertSameCity.
  ///
  /// In en, this message translates to:
  /// **'Choose two different cities.'**
  String get alertSameCity;

  /// No description provided for @alertSelf.
  ///
  /// In en, this message translates to:
  /// **'You can\'t follow yourself.'**
  String get alertSelf;

  /// No description provided for @browseTripsTitle.
  ///
  /// In en, this message translates to:
  /// **'Trips leaving soon'**
  String get browseTripsTitle;

  /// No description provided for @browseRequestsTitle.
  ///
  /// In en, this message translates to:
  /// **'Parcels looking for a traveler'**
  String get browseRequestsTitle;

  /// No description provided for @browseTripsEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No trips right now'**
  String get browseTripsEmptyTitle;

  /// No description provided for @browseTripsEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Trips appear here as soon as travelers publish them.'**
  String get browseTripsEmptyBody;

  /// No description provided for @browseTripsEmptyAction.
  ///
  /// In en, this message translates to:
  /// **'Send a parcel'**
  String get browseTripsEmptyAction;

  /// No description provided for @browseRequestsEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No open parcels right now'**
  String get browseRequestsEmptyTitle;

  /// No description provided for @browseRequestsEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Parcels appear here as soon as senders post them.'**
  String get browseRequestsEmptyBody;

  /// No description provided for @browseRequestsEmptyAction.
  ///
  /// In en, this message translates to:
  /// **'Add a journey'**
  String get browseRequestsEmptyAction;

  /// No description provided for @browseNoMatchTitle.
  ///
  /// In en, this message translates to:
  /// **'No results'**
  String get browseNoMatchTitle;

  /// No description provided for @browseNoMatchBody.
  ///
  /// In en, this message translates to:
  /// **'Nothing matches these filters. Try other cities or another date.'**
  String get browseNoMatchBody;

  /// No description provided for @browseClearFilters.
  ///
  /// In en, this message translates to:
  /// **'Clear filters'**
  String get browseClearFilters;

  /// No description provided for @browseClearFilter.
  ///
  /// In en, this message translates to:
  /// **'Clear {label}'**
  String browseClearFilter(String label);

  /// No description provided for @browseFilterFrom.
  ///
  /// In en, this message translates to:
  /// **'From'**
  String get browseFilterFrom;

  /// No description provided for @browseFilterTo.
  ///
  /// In en, this message translates to:
  /// **'To'**
  String get browseFilterTo;

  /// No description provided for @browseFilterDate.
  ///
  /// In en, this message translates to:
  /// **'From date'**
  String get browseFilterDate;

  /// No description provided for @countryAlgeria.
  ///
  /// In en, this message translates to:
  /// **'Algeria'**
  String get countryAlgeria;

  /// No description provided for @countryFrance.
  ///
  /// In en, this message translates to:
  /// **'France'**
  String get countryFrance;

  /// No description provided for @countrySpain.
  ///
  /// In en, this message translates to:
  /// **'Spain'**
  String get countrySpain;

  /// No description provided for @countryGermany.
  ///
  /// In en, this message translates to:
  /// **'Germany'**
  String get countryGermany;

  /// No description provided for @corridorAll.
  ///
  /// In en, this message translates to:
  /// **'All routes'**
  String get corridorAll;

  /// No description provided for @corridorA11y.
  ///
  /// In en, this message translates to:
  /// **'From {from} to {to}'**
  String corridorA11y(String from, String to);

  /// No description provided for @discoveryListingsOffTitle.
  ///
  /// In en, this message translates to:
  /// **'Not available right now'**
  String get discoveryListingsOffTitle;

  /// No description provided for @discoveryListingsOff.
  ///
  /// In en, this message translates to:
  /// **'Browsing trips and parcels is paused for now. Please check back later.'**
  String get discoveryListingsOff;

  /// No description provided for @discoveryProfilesOffTitle.
  ///
  /// In en, this message translates to:
  /// **'Not available right now'**
  String get discoveryProfilesOffTitle;

  /// No description provided for @discoveryProfilesOff.
  ///
  /// In en, this message translates to:
  /// **'Public profiles are paused for now. Please check back later.'**
  String get discoveryProfilesOff;

  /// No description provided for @discoveryProfileGone.
  ///
  /// In en, this message translates to:
  /// **'This profile is no longer available.'**
  String get discoveryProfileGone;

  /// No description provided for @discoveryShowingEarlier.
  ///
  /// In en, this message translates to:
  /// **'Showing what we loaded earlier'**
  String get discoveryShowingEarlier;

  /// No description provided for @requestCarryAction.
  ///
  /// In en, this message translates to:
  /// **'I can carry this'**
  String get requestCarryAction;

  /// No description provided for @carryExplain.
  ///
  /// In en, this message translates to:
  /// **'Tell the sender you could carry this. It isn\'t an offer: there is no price, nothing is reserved, and the sender decides what happens next.'**
  String get carryExplain;

  /// No description provided for @carryChooseTrip.
  ///
  /// In en, this message translates to:
  /// **'Which trip?'**
  String get carryChooseTrip;

  /// No description provided for @carryChooseTripHint.
  ///
  /// In en, this message translates to:
  /// **'Pick the journey you would carry this on.'**
  String get carryChooseTripHint;

  /// No description provided for @carryPublishTrip.
  ///
  /// In en, this message translates to:
  /// **'Add a journey to carry this'**
  String get carryPublishTrip;

  /// No description provided for @carrySentTitle.
  ///
  /// In en, this message translates to:
  /// **'Sender notified'**
  String get carrySentTitle;

  /// No description provided for @carryAlreadySentTitle.
  ///
  /// In en, this message translates to:
  /// **'Already sent'**
  String get carryAlreadySentTitle;

  /// No description provided for @carrySentBody.
  ///
  /// In en, this message translates to:
  /// **'The sender got one notification that you can carry this. They can look at your trip and propose a delivery. Nothing is reserved.'**
  String get carrySentBody;

  /// No description provided for @carryIncompatible.
  ///
  /// In en, this message translates to:
  /// **'This parcel doesn\'t fit that trip:'**
  String get carryIncompatible;

  /// No description provided for @carryDailyCap.
  ///
  /// In en, this message translates to:
  /// **'You have reached today\'s limit for \"I can carry this\". Try again tomorrow.'**
  String get carryDailyCap;

  /// No description provided for @carryRequestGone.
  ///
  /// In en, this message translates to:
  /// **'That parcel is no longer open.'**
  String get carryRequestGone;

  /// No description provided for @carryJourneyGone.
  ///
  /// In en, this message translates to:
  /// **'That trip is no longer available.'**
  String get carryJourneyGone;

  /// No description provided for @rejectCapacity.
  ///
  /// In en, this message translates to:
  /// **'There isn\'t enough space left on every leg.'**
  String get rejectCapacity;

  /// No description provided for @rejectDeadline.
  ///
  /// In en, this message translates to:
  /// **'It would arrive after the deadline.'**
  String get rejectDeadline;

  /// No description provided for @rejectTiming.
  ///
  /// In en, this message translates to:
  /// **'The dates don\'t line up.'**
  String get rejectTiming;

  /// No description provided for @rejectRoute.
  ///
  /// In en, this message translates to:
  /// **'The detour from the route is too large.'**
  String get rejectRoute;

  /// No description provided for @rejectClosed.
  ///
  /// In en, this message translates to:
  /// **'One of them is no longer open.'**
  String get rejectClosed;

  /// No description provided for @rejectVerification.
  ///
  /// In en, this message translates to:
  /// **'The traveler\'s verification isn\'t complete.'**
  String get rejectVerification;

  /// No description provided for @rejectItem.
  ///
  /// In en, this message translates to:
  /// **'This item can\'t be carried on this trip.'**
  String get rejectItem;

  /// No description provided for @rejectGeneric.
  ///
  /// In en, this message translates to:
  /// **'The trip and the parcel don\'t match.'**
  String get rejectGeneric;

  /// No description provided for @focusTripMissingTitle.
  ///
  /// In en, this message translates to:
  /// **'That trip doesn\'t fit this parcel'**
  String get focusTripMissingTitle;

  /// No description provided for @focusTripMissingBody.
  ///
  /// In en, this message translates to:
  /// **'This trip isn\'t in your list of compatible travelers.'**
  String get focusTripMissingBody;

  /// No description provided for @tripLeaves.
  ///
  /// In en, this message translates to:
  /// **'Leaves {date}'**
  String tripLeaves(String date);

  /// No description provided for @tripArrives.
  ///
  /// In en, this message translates to:
  /// **'Arrives'**
  String get tripArrives;

  /// No description provided for @tripSpace.
  ///
  /// In en, this message translates to:
  /// **'Space left'**
  String get tripSpace;

  /// No description provided for @tripSpaceLeft.
  ///
  /// In en, this message translates to:
  /// **'{kg} kg left'**
  String tripSpaceLeft(String kg);

  /// No description provided for @tripSpaceLeftUnderOne.
  ///
  /// In en, this message translates to:
  /// **'Less than 1 kg left'**
  String get tripSpaceLeftUnderOne;

  /// No description provided for @tripSpaceKg.
  ///
  /// In en, this message translates to:
  /// **'{kg} kg'**
  String tripSpaceKg(String kg);

  /// No description provided for @tripSpaceKgUnderOne.
  ///
  /// In en, this message translates to:
  /// **'Less than 1 kg'**
  String get tripSpaceKgUnderOne;

  /// No description provided for @tripPreviewSubtitle.
  ///
  /// In en, this message translates to:
  /// **'You propose first. Nothing is booked from here.'**
  String get tripPreviewSubtitle;

  /// No description provided for @tripChooseParcel.
  ///
  /// In en, this message translates to:
  /// **'Choose one of your parcels'**
  String get tripChooseParcel;

  /// No description provided for @tripPostForRoute.
  ///
  /// In en, this message translates to:
  /// **'Post a parcel for this route'**
  String get tripPostForRoute;

  /// No description provided for @requestCardDeadline.
  ///
  /// In en, this message translates to:
  /// **'By {date}'**
  String requestCardDeadline(String date);

  /// No description provided for @requestCardFrom.
  ///
  /// In en, this message translates to:
  /// **'From {name}'**
  String requestCardFrom(String name);

  /// No description provided for @requestOfferedReward.
  ///
  /// In en, this message translates to:
  /// **'Offered reward'**
  String get requestOfferedReward;

  /// No description provided for @publicRatingA11y.
  ///
  /// In en, this message translates to:
  /// **'Rated {rating} out of 5'**
  String publicRatingA11y(String rating);

  /// No description provided for @profileNoUsualRoutes.
  ///
  /// In en, this message translates to:
  /// **'No usual routes shown'**
  String get profileNoUsualRoutes;

  /// No description provided for @homeMatchesTitle.
  ///
  /// In en, this message translates to:
  /// **'Matches for you'**
  String get homeMatchesTitle;

  /// No description provided for @homeMatchesEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No matches yet'**
  String get homeMatchesEmptyTitle;

  /// No description provided for @homeMatchesSenderNone.
  ///
  /// In en, this message translates to:
  /// **'Post a parcel and the travelers who fit it will show up here.'**
  String get homeMatchesSenderNone;

  /// No description provided for @homeMatchesSenderWaiting.
  ///
  /// In en, this message translates to:
  /// **'No traveler fits your open parcels yet. We\'ll show them here as soon as one does.'**
  String get homeMatchesSenderWaiting;

  /// No description provided for @homeMatchesTravelerNone.
  ///
  /// In en, this message translates to:
  /// **'Add a journey and the parcels that fit it will show up here.'**
  String get homeMatchesTravelerNone;

  /// No description provided for @homeMatchesTravelerWaiting.
  ///
  /// In en, this message translates to:
  /// **'No parcel fits your journeys yet. We\'ll show them here as soon as one does.'**
  String get homeMatchesTravelerWaiting;

  /// No description provided for @homeTripsTitle.
  ///
  /// In en, this message translates to:
  /// **'Trips leaving soon'**
  String get homeTripsTitle;

  /// No description provided for @homeTripsEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Trips that are about to leave will show up here.'**
  String get homeTripsEmptyBody;

  /// No description provided for @homeRequestsTitle.
  ///
  /// In en, this message translates to:
  /// **'Parcels looking for a traveler'**
  String get homeRequestsTitle;

  /// No description provided for @homeRequestsEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Parcels that need a traveler will show up here.'**
  String get homeRequestsEmptyBody;

  /// No description provided for @homeListingsEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'Nothing listed yet'**
  String get homeListingsEmptyTitle;

  /// No description provided for @homeListingsEmptyRouteTitle.
  ///
  /// In en, this message translates to:
  /// **'Nothing on this route yet'**
  String get homeListingsEmptyRouteTitle;

  /// No description provided for @homePeopleSenderTitle.
  ///
  /// In en, this message translates to:
  /// **'Travelers on Wassla'**
  String get homePeopleSenderTitle;

  /// No description provided for @homePeopleTravelerTitle.
  ///
  /// In en, this message translates to:
  /// **'Senders on Wassla'**
  String get homePeopleTravelerTitle;

  /// No description provided for @homePeopleEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No public profiles yet'**
  String get homePeopleEmptyTitle;

  /// No description provided for @homePeopleEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'People who choose to show a public profile will appear here.'**
  String get homePeopleEmptyBody;

  /// No description provided for @optInTitle.
  ///
  /// In en, this message translates to:
  /// **'Be found on Wassla'**
  String get optInTitle;

  /// No description provided for @optInBody.
  ///
  /// In en, this message translates to:
  /// **'Let senders and travelers find you. Only your first name, your trust badges and the routes you choose are shown.'**
  String get optInBody;

  /// No description provided for @optInPreviewLabel.
  ///
  /// In en, this message translates to:
  /// **'This is what others would see'**
  String get optInPreviewLabel;

  /// No description provided for @optInShow.
  ///
  /// In en, this message translates to:
  /// **'Show my profile'**
  String get optInShow;

  /// No description provided for @optInNotNow.
  ///
  /// In en, this message translates to:
  /// **'Not now'**
  String get optInNotNow;

  /// No description provided for @personTitle.
  ///
  /// In en, this message translates to:
  /// **'Profile'**
  String get personTitle;

  /// No description provided for @personGoneTitle.
  ///
  /// In en, this message translates to:
  /// **'Profile unavailable'**
  String get personGoneTitle;

  /// No description provided for @personUsualRoutes.
  ///
  /// In en, this message translates to:
  /// **'Usual routes'**
  String get personUsualRoutes;

  /// No description provided for @personAlertHint.
  ///
  /// In en, this message translates to:
  /// **'Turn on an alert to hear when {name} posts on a route.'**
  String personAlertHint(String name);

  /// No description provided for @personNoUsualRoutes.
  ///
  /// In en, this message translates to:
  /// **'{name} hasn\'t added usual routes.'**
  String personNoUsualRoutes(String name);

  /// No description provided for @personTrips.
  ///
  /// In en, this message translates to:
  /// **'{name}\'s trips'**
  String personTrips(String name);

  /// No description provided for @personRequests.
  ///
  /// In en, this message translates to:
  /// **'{name}\'s parcels'**
  String personRequests(String name);

  /// No description provided for @personNothingListed.
  ///
  /// In en, this message translates to:
  /// **'{name} has no live trips or open parcels right now.'**
  String personNothingListed(String name);

  /// No description provided for @publicProfileTitle.
  ///
  /// In en, this message translates to:
  /// **'Public profile'**
  String get publicProfileTitle;

  /// No description provided for @publicProfileIntro.
  ///
  /// In en, this message translates to:
  /// **'A public profile lets senders and travelers find you and follow your routes. It is off unless you turn it on, and you can turn it off at any time.'**
  String get publicProfileIntro;

  /// No description provided for @publicShownTitle.
  ///
  /// In en, this message translates to:
  /// **'What others see'**
  String get publicShownTitle;

  /// No description provided for @publicShownFirstName.
  ///
  /// In en, this message translates to:
  /// **'Your first name'**
  String get publicShownFirstName;

  /// No description provided for @publicShownTrust.
  ///
  /// In en, this message translates to:
  /// **'Whether your identity is verified, your rating and your completed deliveries'**
  String get publicShownTrust;

  /// No description provided for @publicShownMemberSince.
  ///
  /// In en, this message translates to:
  /// **'The month and year you joined'**
  String get publicShownMemberSince;

  /// No description provided for @publicShownRoutes.
  ///
  /// In en, this message translates to:
  /// **'The usual routes you choose'**
  String get publicShownRoutes;

  /// No description provided for @publicNeverTitle.
  ///
  /// In en, this message translates to:
  /// **'Never shown'**
  String get publicNeverTitle;

  /// No description provided for @publicNeverContact.
  ///
  /// In en, this message translates to:
  /// **'Your last name, email or phone number'**
  String get publicNeverContact;

  /// No description provided for @publicNeverPlaces.
  ///
  /// In en, this message translates to:
  /// **'An exact address or position'**
  String get publicNeverPlaces;

  /// No description provided for @publicShowSwitch.
  ///
  /// In en, this message translates to:
  /// **'Show my public profile'**
  String get publicShowSwitch;

  /// No description provided for @publicSwitchOn.
  ///
  /// In en, this message translates to:
  /// **'Others can find you.'**
  String get publicSwitchOn;

  /// No description provided for @publicSwitchOff.
  ///
  /// In en, this message translates to:
  /// **'Others can\'t find you.'**
  String get publicSwitchOff;

  /// No description provided for @publicProfileOn.
  ///
  /// In en, this message translates to:
  /// **'Your public profile is on'**
  String get publicProfileOn;

  /// No description provided for @publicHiddenNotice.
  ///
  /// In en, this message translates to:
  /// **'Your profile is not currently visible to others.'**
  String get publicHiddenNotice;

  /// No description provided for @publicRoutesTitle.
  ///
  /// In en, this message translates to:
  /// **'Usual routes'**
  String get publicRoutesTitle;

  /// No description provided for @publicRoutesHint.
  ///
  /// In en, this message translates to:
  /// **'Up to three routes you often travel or send on.'**
  String get publicRoutesHint;

  /// No description provided for @publicRoutesLimit.
  ///
  /// In en, this message translates to:
  /// **'You\'ve added the maximum of three routes.'**
  String get publicRoutesLimit;

  /// No description provided for @publicRouteAdd.
  ///
  /// In en, this message translates to:
  /// **'Add a usual route'**
  String get publicRouteAdd;

  /// No description provided for @publicRouteFrom.
  ///
  /// In en, this message translates to:
  /// **'Usual route: from'**
  String get publicRouteFrom;

  /// No description provided for @publicRouteTo.
  ///
  /// In en, this message translates to:
  /// **'Usual route: to'**
  String get publicRouteTo;

  /// No description provided for @publicRouteRemove.
  ///
  /// In en, this message translates to:
  /// **'Remove {route}'**
  String publicRouteRemove(String route);

  /// No description provided for @publicRouteDuplicate.
  ///
  /// In en, this message translates to:
  /// **'That route is already on your profile.'**
  String get publicRouteDuplicate;

  /// No description provided for @publicPreviewTitle.
  ///
  /// In en, this message translates to:
  /// **'Your public card'**
  String get publicPreviewTitle;

  /// No description provided for @publicPreviewVisible.
  ///
  /// In en, this message translates to:
  /// **'This is what others see right now.'**
  String get publicPreviewVisible;

  /// No description provided for @publicPreviewHidden.
  ///
  /// In en, this message translates to:
  /// **'This is what others would see if you turn it on.'**
  String get publicPreviewHidden;

  /// No description provided for @notificationRouteAlert.
  ///
  /// In en, this message translates to:
  /// **'New on a route you follow'**
  String get notificationRouteAlert;

  /// No description provided for @notificationTravelerInterested.
  ///
  /// In en, this message translates to:
  /// **'A traveler can carry your parcel'**
  String get notificationTravelerInterested;

  /// No description provided for @journeyModeSea.
  ///
  /// In en, this message translates to:
  /// **'Ferry'**
  String get journeyModeSea;

  /// No description provided for @routeSeaMode.
  ///
  /// In en, this message translates to:
  /// **'Ferry'**
  String get routeSeaMode;

  /// No description provided for @routeSeaSwitchedOff.
  ///
  /// In en, this message translates to:
  /// **'Ferry legs are switched off for now.'**
  String get routeSeaSwitchedOff;

  /// No description provided for @routeSeaTicketNote.
  ///
  /// In en, this message translates to:
  /// **'A ferry leg needs your ticket checked before the journey can go live. You add it after saving.'**
  String get routeSeaTicketNote;

  /// No description provided for @routeSeaRefusedSwitchedOff.
  ///
  /// In en, this message translates to:
  /// **'Ferry legs are switched off right now. Choose another way to travel this part.'**
  String get routeSeaRefusedSwitchedOff;

  /// No description provided for @routeSeaRefusedNoCrossing.
  ///
  /// In en, this message translates to:
  /// **'No ferry line runs between these two cities in this direction right now.'**
  String get routeSeaRefusedNoCrossing;

  /// No description provided for @routeSeaRefusedNotPort.
  ///
  /// In en, this message translates to:
  /// **'A ferry runs between port cities. Choose the city, not an airport, for each end of this part.'**
  String get routeSeaRefusedNotPort;

  /// No description provided for @routeSeaLinesFailedTitle.
  ///
  /// In en, this message translates to:
  /// **'Ferry lines didn\'t load'**
  String get routeSeaLinesFailedTitle;

  /// No description provided for @routeSeaLinesFailedBody.
  ///
  /// In en, this message translates to:
  /// **'Flights and road legs work as usual. Try again to add a ferry leg.'**
  String get routeSeaLinesFailedBody;

  /// No description provided for @routeErrorSeaRefused.
  ///
  /// In en, this message translates to:
  /// **'A ferry leg on your route can\'t be used right now. The reason is shown on that leg.'**
  String get routeErrorSeaRefused;

  /// No description provided for @journeyErrorStopInvalid.
  ///
  /// In en, this message translates to:
  /// **'One of your stops has handover options we can\'t use. Check the options on each stop.'**
  String get journeyErrorStopInvalid;

  /// No description provided for @routeCapacityMore.
  ///
  /// In en, this message translates to:
  /// **'More capacity options'**
  String get routeCapacityMore;

  /// No description provided for @routeCapacityMoreHelp.
  ///
  /// In en, this message translates to:
  /// **'Optional. Leave a box empty to set no limit.'**
  String get routeCapacityMoreHelp;

  /// No description provided for @routeVolumeLabel.
  ///
  /// In en, this message translates to:
  /// **'Volume (litres)'**
  String get routeVolumeLabel;

  /// No description provided for @routeParcelsLabel.
  ///
  /// In en, this message translates to:
  /// **'Number of parcels'**
  String get routeParcelsLabel;

  /// No description provided for @routeVolumeInvalid.
  ///
  /// In en, this message translates to:
  /// **'Enter a whole number of litres from 1 to 200,000.'**
  String get routeVolumeInvalid;

  /// No description provided for @routeParcelsInvalid.
  ///
  /// In en, this message translates to:
  /// **'Enter a whole number of parcels from 1 to 10,000.'**
  String get routeParcelsInvalid;

  /// No description provided for @routeHandoverAction.
  ///
  /// In en, this message translates to:
  /// **'Handover options'**
  String get routeHandoverAction;

  /// No description provided for @routeHandoverBoth.
  ///
  /// In en, this message translates to:
  /// **'Takes pickups and drop-offs'**
  String get routeHandoverBoth;

  /// No description provided for @routeHandoverPickups.
  ///
  /// In en, this message translates to:
  /// **'Pickups only'**
  String get routeHandoverPickups;

  /// No description provided for @routeHandoverDropoffs.
  ///
  /// In en, this message translates to:
  /// **'Drop-offs only'**
  String get routeHandoverDropoffs;

  /// No description provided for @routeHandoverNone.
  ///
  /// In en, this message translates to:
  /// **'No handovers here'**
  String get routeHandoverNone;

  /// Title of the sheet for one stop's handover options.
  ///
  /// In en, this message translates to:
  /// **'Handover at {stop}'**
  String routeHandoverSheetTitle(String stop);

  /// No description provided for @routeHandoverPickupLabel.
  ///
  /// In en, this message translates to:
  /// **'Accept pickups here'**
  String get routeHandoverPickupLabel;

  /// No description provided for @routeHandoverPickupHelp.
  ///
  /// In en, this message translates to:
  /// **'A sender can hand you a parcel at this stop.'**
  String get routeHandoverPickupHelp;

  /// No description provided for @routeHandoverDropoffLabel.
  ///
  /// In en, this message translates to:
  /// **'Accept drop-offs here'**
  String get routeHandoverDropoffLabel;

  /// No description provided for @routeHandoverDropoffHelp.
  ///
  /// In en, this message translates to:
  /// **'You can hand a parcel to its recipient at this stop.'**
  String get routeHandoverDropoffHelp;

  /// No description provided for @routeHandoverWindowTitle.
  ///
  /// In en, this message translates to:
  /// **'Time window'**
  String get routeHandoverWindowTitle;

  /// No description provided for @routeHandoverWindowHelp.
  ///
  /// In en, this message translates to:
  /// **'Optional. When you can meet at this stop.'**
  String get routeHandoverWindowHelp;

  /// No description provided for @routeHandoverWindowFrom.
  ///
  /// In en, this message translates to:
  /// **'From'**
  String get routeHandoverWindowFrom;

  /// No description provided for @routeHandoverWindowTo.
  ///
  /// In en, this message translates to:
  /// **'Until'**
  String get routeHandoverWindowTo;

  /// No description provided for @routeHandoverWindowClear.
  ///
  /// In en, this message translates to:
  /// **'Remove time window'**
  String get routeHandoverWindowClear;

  /// No description provided for @routeHandoverNoteLabel.
  ///
  /// In en, this message translates to:
  /// **'Note'**
  String get routeHandoverNoteLabel;

  /// No description provided for @routeHandoverNoteHint.
  ///
  /// In en, this message translates to:
  /// **'For example: meet at the café by the ferry terminal.'**
  String get routeHandoverNoteHint;

  /// No description provided for @routeHandoverNoteSeen.
  ///
  /// In en, this message translates to:
  /// **'Only you see this until a delivery that uses this stop is paid for. Then the sender of that delivery sees it too.'**
  String get routeHandoverNoteSeen;

  /// No description provided for @routeWindowIncomplete.
  ///
  /// In en, this message translates to:
  /// **'Set both a start and an end, or remove the window.'**
  String get routeWindowIncomplete;

  /// No description provided for @routeWindowOrder.
  ///
  /// In en, this message translates to:
  /// **'The window has to end after it starts.'**
  String get routeWindowOrder;

  /// No description provided for @routeWindowOutside.
  ///
  /// In en, this message translates to:
  /// **'The window has to fall between arriving at this stop and leaving it.'**
  String get routeWindowOutside;

  /// No description provided for @routeCarryTitle.
  ///
  /// In en, this message translates to:
  /// **'What you carry'**
  String get routeCarryTitle;

  /// No description provided for @routeCarryHelp.
  ///
  /// In en, this message translates to:
  /// **'Switch off anything you won\'t take. Senders only find you for parcels you accept.'**
  String get routeCarryHelp;

  /// No description provided for @routeCarryFragile.
  ///
  /// In en, this message translates to:
  /// **'Fragile items'**
  String get routeCarryFragile;

  /// No description provided for @routeCarryLastOne.
  ///
  /// In en, this message translates to:
  /// **'At least one kind of item has to stay on.'**
  String get routeCarryLastOne;

  /// No description provided for @journeyPauseAction.
  ///
  /// In en, this message translates to:
  /// **'Pause journey'**
  String get journeyPauseAction;

  /// No description provided for @journeyPauseConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Pause this journey?'**
  String get journeyPauseConfirmTitle;

  /// No description provided for @journeyPauseConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'Senders stop finding it and nobody can start a new offer on it. Deliveries already paid for carry on, and an offer already pending can\'t be accepted until you resume.'**
  String get journeyPauseConfirmBody;

  /// No description provided for @journeyPaused.
  ///
  /// In en, this message translates to:
  /// **'Journey paused.'**
  String get journeyPaused;

  /// No description provided for @journeyResumeAction.
  ///
  /// In en, this message translates to:
  /// **'Resume journey'**
  String get journeyResumeAction;

  /// No description provided for @journeyResumed.
  ///
  /// In en, this message translates to:
  /// **'Journey resumed.'**
  String get journeyResumed;

  /// No description provided for @journeyPausedBannerTitle.
  ///
  /// In en, this message translates to:
  /// **'This journey is paused'**
  String get journeyPausedBannerTitle;

  /// No description provided for @journeyPausedBannerBody.
  ///
  /// In en, this message translates to:
  /// **'Senders can\'t find it and offers on it can\'t be accepted. Deliveries already paid for carry on as normal.'**
  String get journeyPausedBannerBody;

  /// No description provided for @journeyPausedStaffBody.
  ///
  /// In en, this message translates to:
  /// **'Wassla paused this journey. Contact support to have it resumed.'**
  String get journeyPausedStaffBody;

  /// No description provided for @journeyErrorNotPausable.
  ///
  /// In en, this message translates to:
  /// **'This journey can\'t be paused in its current state.'**
  String get journeyErrorNotPausable;

  /// No description provided for @journeyErrorPausedByStaff.
  ///
  /// In en, this message translates to:
  /// **'Wassla paused this journey, so only support can resume it.'**
  String get journeyErrorPausedByStaff;

  /// A leg's optional volume limit.
  ///
  /// In en, this message translates to:
  /// **'{litres} L'**
  String journeyCapacityVolumeValue(int litres);

  /// No description provided for @journeyCapacityParcelsValue.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 parcel} other{{count} parcels}}'**
  String journeyCapacityParcelsValue(int count);

  /// No description provided for @journeyHandoverTitle.
  ///
  /// In en, this message translates to:
  /// **'Handover at your stops'**
  String get journeyHandoverTitle;

  /// A stop's meeting window.
  ///
  /// In en, this message translates to:
  /// **'Between {from} and {to}'**
  String journeyHandoverWindow(String from, String to);

  /// No description provided for @journeyCarryTitle.
  ///
  /// In en, this message translates to:
  /// **'What you carry'**
  String get journeyCarryTitle;

  /// No description provided for @journeyCarryAll.
  ///
  /// In en, this message translates to:
  /// **'Takes every kind of item'**
  String get journeyCarryAll;

  /// The item kinds the traveler declines.
  ///
  /// In en, this message translates to:
  /// **'Won\'t take: {items}'**
  String journeyCarryRefuses(String items);

  /// No description provided for @journeyCarryNoFragile.
  ///
  /// In en, this message translates to:
  /// **'No fragile items'**
  String get journeyCarryNoFragile;

  /// No description provided for @proofExplainerSea.
  ///
  /// In en, this message translates to:
  /// **'Upload your ferry ticket or booking confirmation. We check it before your journey can match parcels.'**
  String get proofExplainerSea;

  /// No description provided for @proofChecklistTitle.
  ///
  /// In en, this message translates to:
  /// **'A good photo shows'**
  String get proofChecklistTitle;

  /// No description provided for @proofChecklistFlight.
  ///
  /// In en, this message translates to:
  /// **'Your name, the flight number, the date and both airports.'**
  String get proofChecklistFlight;

  /// No description provided for @proofChecklistSea.
  ///
  /// In en, this message translates to:
  /// **'Your name, the ferry company, the date and both ports.'**
  String get proofChecklistSea;

  /// No description provided for @rejectSea.
  ///
  /// In en, this message translates to:
  /// **'A ferry line on this trip isn\'t available right now.'**
  String get rejectSea;

  /// No description provided for @rejectPaused.
  ///
  /// In en, this message translates to:
  /// **'The traveler has paused this trip.'**
  String get rejectPaused;

  /// No description provided for @rejectHandover.
  ///
  /// In en, this message translates to:
  /// **'The traveler doesn\'t take handovers at the places you need.'**
  String get rejectHandover;

  /// No description provided for @rejectNotAccepted.
  ///
  /// In en, this message translates to:
  /// **'The traveler doesn\'t take this kind of item.'**
  String get rejectNotAccepted;

  /// No description provided for @rejectVolume.
  ///
  /// In en, this message translates to:
  /// **'There isn\'t enough room left for this parcel\'s size.'**
  String get rejectVolume;

  /// No description provided for @rejectParcelSlots.
  ///
  /// In en, this message translates to:
  /// **'The traveler has no parcel places left.'**
  String get rejectParcelSlots;

  /// No description provided for @findTravelersSeaProofApproved.
  ///
  /// In en, this message translates to:
  /// **'Ferry ticket verified'**
  String get findTravelersSeaProofApproved;

  /// No description provided for @findTravelersCaveatVolume.
  ///
  /// In en, this message translates to:
  /// **'This traveler limits volume and your request has no size, so we couldn\'t check that your parcel fits. They decide when they accept.'**
  String get findTravelersCaveatVolume;

  /// No description provided for @staleJourneyPaused.
  ///
  /// In en, this message translates to:
  /// **'This journey is paused, so nothing on it can be accepted until it resumes.'**
  String get staleJourneyPaused;

  /// No description provided for @dealHandoverTitle.
  ///
  /// In en, this message translates to:
  /// **'Where and when to meet'**
  String get dealHandoverTitle;

  /// No description provided for @dealHandoverPickup.
  ///
  /// In en, this message translates to:
  /// **'Pickup'**
  String get dealHandoverPickup;

  /// No description provided for @dealHandoverDropoff.
  ///
  /// In en, this message translates to:
  /// **'Drop-off'**
  String get dealHandoverDropoff;

  /// No description provided for @journeyPriceTitle.
  ///
  /// In en, this message translates to:
  /// **'Your price'**
  String get journeyPriceTitle;

  /// No description provided for @journeyPriceOptional.
  ///
  /// In en, this message translates to:
  /// **'Optional'**
  String get journeyPriceOptional;

  /// No description provided for @journeyPriceNote.
  ///
  /// In en, this message translates to:
  /// **'Senders see your price plus Wassla\'s fee. Wassla\'s minimum for each parcel still applies.'**
  String get journeyPriceNote;

  /// No description provided for @journeyPricePerKgLabel.
  ///
  /// In en, this message translates to:
  /// **'Price per kg'**
  String get journeyPricePerKgLabel;

  /// No description provided for @journeyPriceMinimumLabel.
  ///
  /// In en, this message translates to:
  /// **'Minimum per parcel'**
  String get journeyPriceMinimumLabel;

  /// No description provided for @journeyPriceErrorBoth.
  ///
  /// In en, this message translates to:
  /// **'Fill in both amounts, or leave both empty.'**
  String get journeyPriceErrorBoth;

  /// No description provided for @journeyPriceErrorMaximum.
  ///
  /// In en, this message translates to:
  /// **'At most {amount}.'**
  String journeyPriceErrorMaximum(String amount);

  /// No description provided for @journeyPriceErrorTooHigh.
  ///
  /// In en, this message translates to:
  /// **'That amount is higher than Wassla allows.'**
  String get journeyPriceErrorTooHigh;

  /// No description provided for @journeyPriceDisabled.
  ///
  /// In en, this message translates to:
  /// **'Setting a price is not available right now.'**
  String get journeyPriceDisabled;

  /// No description provided for @journeyPriceNotEditable.
  ///
  /// In en, this message translates to:
  /// **'The price can no longer be changed on this journey.'**
  String get journeyPriceNotEditable;

  /// No description provided for @journeyPriceNone.
  ///
  /// In en, this message translates to:
  /// **'No price set. Senders propose their own amount.'**
  String get journeyPriceNone;

  /// No description provided for @journeyPriceSet.
  ///
  /// In en, this message translates to:
  /// **'Set a price'**
  String get journeyPriceSet;

  /// No description provided for @journeyPriceChange.
  ///
  /// In en, this message translates to:
  /// **'Change'**
  String get journeyPriceChange;

  /// No description provided for @journeyPriceSave.
  ///
  /// In en, this message translates to:
  /// **'Save price'**
  String get journeyPriceSave;

  /// No description provided for @journeyPriceRemove.
  ///
  /// In en, this message translates to:
  /// **'Remove price'**
  String get journeyPriceRemove;

  /// No description provided for @journeyPriceSaved.
  ///
  /// In en, this message translates to:
  /// **'Price saved.'**
  String get journeyPriceSaved;

  /// No description provided for @journeyPriceCleared.
  ///
  /// In en, this message translates to:
  /// **'Price removed.'**
  String get journeyPriceCleared;

  /// No description provided for @journeyPriceAppliesToNew.
  ///
  /// In en, this message translates to:
  /// **'A new price applies to offers made from now on. Offers and deals already made keep theirs.'**
  String get journeyPriceAppliesToNew;

  /// No description provided for @journeyPricePerKgValue.
  ///
  /// In en, this message translates to:
  /// **'{amount} per kg'**
  String journeyPricePerKgValue(String amount);

  /// No description provided for @journeyPriceMinimumValue.
  ///
  /// In en, this message translates to:
  /// **'Minimum {amount} per parcel'**
  String journeyPriceMinimumValue(String amount);

  /// No description provided for @tripPriceFrom.
  ///
  /// In en, this message translates to:
  /// **'from {perKg} per kg, minimum {minimum}'**
  String tripPriceFrom(String perKg, String minimum);

  /// No description provided for @findTravelersSortPrice.
  ///
  /// In en, this message translates to:
  /// **'Lowest price'**
  String get findTravelersSortPrice;

  /// No description provided for @findTravelersListedPrice.
  ///
  /// In en, this message translates to:
  /// **'{amount} for this parcel'**
  String findTravelersListedPrice(String amount);

  /// No description provided for @offerListedLabel.
  ///
  /// In en, this message translates to:
  /// **'Their price for this parcel'**
  String get offerListedLabel;

  /// No description provided for @offerSendListed.
  ///
  /// In en, this message translates to:
  /// **'Offer {amount}'**
  String offerSendListed(String amount);

  /// No description provided for @offerDifferentAmount.
  ///
  /// In en, this message translates to:
  /// **'Offer a different amount'**
  String get offerDifferentAmount;

  /// No description provided for @offerBelowListedNote.
  ///
  /// In en, this message translates to:
  /// **'That is below their price, so they may decline or counter.'**
  String get offerBelowListedNote;

  /// No description provided for @offerUseListed.
  ///
  /// In en, this message translates to:
  /// **'Use their price'**
  String get offerUseListed;

  /// No description provided for @tripPrice.
  ///
  /// In en, this message translates to:
  /// **'Price'**
  String get tripPrice;

  /// No description provided for @trackingNumberLabel.
  ///
  /// In en, this message translates to:
  /// **'Tracking number'**
  String get trackingNumberLabel;

  /// No description provided for @trackingNumberCopy.
  ///
  /// In en, this message translates to:
  /// **'Copy tracking number'**
  String get trackingNumberCopy;

  /// No description provided for @trackingNumberCopied.
  ///
  /// In en, this message translates to:
  /// **'Tracking number copied'**
  String get trackingNumberCopied;

  /// No description provided for @progressTitle.
  ///
  /// In en, this message translates to:
  /// **'Trip progress'**
  String get progressTitle;

  /// No description provided for @progressIntro.
  ///
  /// In en, this message translates to:
  /// **'Tell senders how your trip is going. They see your update marked as reported by you. It never moves a payment.'**
  String get progressIntro;

  /// No description provided for @progressActionAtPort.
  ///
  /// In en, this message translates to:
  /// **'I\'m at the port'**
  String get progressActionAtPort;

  /// No description provided for @progressActionDeparted.
  ///
  /// In en, this message translates to:
  /// **'I\'ve departed'**
  String get progressActionDeparted;

  /// No description provided for @progressActionArrived.
  ///
  /// In en, this message translates to:
  /// **'I\'ve arrived'**
  String get progressActionArrived;

  /// No description provided for @progressReportedAtPort.
  ///
  /// In en, this message translates to:
  /// **'At the port'**
  String get progressReportedAtPort;

  /// No description provided for @progressReportedDeparted.
  ///
  /// In en, this message translates to:
  /// **'Departed'**
  String get progressReportedDeparted;

  /// No description provided for @progressReportedArrived.
  ///
  /// In en, this message translates to:
  /// **'Arrived'**
  String get progressReportedArrived;

  /// When the report opens.
  ///
  /// In en, this message translates to:
  /// **'You can report this from {time}.'**
  String progressAvailableFrom(String time);

  /// No description provided for @progressNeedsNetwork.
  ///
  /// In en, this message translates to:
  /// **'Needs a connection. Nothing is saved for later.'**
  String get progressNeedsNetwork;

  /// No description provided for @progressUndo.
  ///
  /// In en, this message translates to:
  /// **'Undo'**
  String get progressUndo;

  /// No description provided for @progressUndoHint.
  ///
  /// In en, this message translates to:
  /// **'You can undo an update for 10 minutes.'**
  String get progressUndoHint;

  /// No description provided for @progressSent.
  ///
  /// In en, this message translates to:
  /// **'Update shared with the senders.'**
  String get progressSent;

  /// No description provided for @progressUndone.
  ///
  /// In en, this message translates to:
  /// **'Update removed.'**
  String get progressUndone;

  /// No description provided for @progressErrorOffline.
  ///
  /// In en, this message translates to:
  /// **'No connection, so your update was not sent. Try again when you are back online.'**
  String get progressErrorOffline;

  /// No description provided for @progressErrorTooEarly.
  ///
  /// In en, this message translates to:
  /// **'It is too early to report this. Reports open 24 hours before the planned time.'**
  String get progressErrorTooEarly;

  /// No description provided for @progressErrorOutOfOrder.
  ///
  /// In en, this message translates to:
  /// **'That step does not come next. Pull down to refresh.'**
  String get progressErrorOutOfOrder;

  /// No description provided for @progressErrorNotReportable.
  ///
  /// In en, this message translates to:
  /// **'This journey cannot take updates right now.'**
  String get progressErrorNotReportable;

  /// No description provided for @progressErrorUndoClosed.
  ///
  /// In en, this message translates to:
  /// **'The 10 minutes to undo this update have passed.'**
  String get progressErrorUndoClosed;

  /// No description provided for @progressErrorHasFollowup.
  ///
  /// In en, this message translates to:
  /// **'A later update depends on this one, so it cannot be undone.'**
  String get progressErrorHasFollowup;

  /// Asks if the traveler has left a place.
  ///
  /// In en, this message translates to:
  /// **'Did you depart from {place}?'**
  String progressQuestionDeparted(String place);

  /// No description provided for @progressQuestionDepartedBare.
  ///
  /// In en, this message translates to:
  /// **'Did you depart?'**
  String get progressQuestionDepartedBare;

  /// Asks if the traveler has reached a place.
  ///
  /// In en, this message translates to:
  /// **'Did you arrive in {place}?'**
  String progressQuestionArrived(String place);

  /// No description provided for @progressQuestionArrivedBare.
  ///
  /// In en, this message translates to:
  /// **'Did you arrive?'**
  String get progressQuestionArrivedBare;

  /// Asks if the traveler is at a port.
  ///
  /// In en, this message translates to:
  /// **'Are you at the port in {place}?'**
  String progressQuestionAtPort(String place);

  /// No description provided for @progressQuestionAtPortBare.
  ///
  /// In en, this message translates to:
  /// **'Are you at the port?'**
  String get progressQuestionAtPortBare;

  /// No description provided for @progressYesDeparted.
  ///
  /// In en, this message translates to:
  /// **'Yes, departed'**
  String get progressYesDeparted;

  /// No description provided for @progressYesArrived.
  ///
  /// In en, this message translates to:
  /// **'Yes, arrived'**
  String get progressYesArrived;

  /// No description provided for @progressYesAtPort.
  ///
  /// In en, this message translates to:
  /// **'Yes, I\'m here'**
  String get progressYesAtPort;

  /// No description provided for @progressNotYet.
  ///
  /// In en, this message translates to:
  /// **'Not yet'**
  String get progressNotYet;

  /// No description provided for @progressQuestionBody.
  ///
  /// In en, this message translates to:
  /// **'Senders with a parcel on this leg will see your answer, marked as reported by you.'**
  String get progressQuestionBody;

  /// No description provided for @dealProgressAtPort.
  ///
  /// In en, this message translates to:
  /// **'Your traveler is at the port'**
  String get dealProgressAtPort;

  /// No description provided for @dealProgressDeparted.
  ///
  /// In en, this message translates to:
  /// **'Your traveler has departed'**
  String get dealProgressDeparted;

  /// No description provided for @dealProgressArrived.
  ///
  /// In en, this message translates to:
  /// **'Your traveler has arrived'**
  String get dealProgressArrived;

  /// No description provided for @dealProgressReportedBy.
  ///
  /// In en, this message translates to:
  /// **'Reported by the traveler'**
  String get dealProgressReportedBy;

  /// No description provided for @notificationProgressReported.
  ///
  /// In en, this message translates to:
  /// **'Update from your traveler'**
  String get notificationProgressReported;

  /// No description provided for @notificationLegReminder.
  ///
  /// In en, this message translates to:
  /// **'How is your trip going?'**
  String get notificationLegReminder;

  /// No description provided for @problemsTitle.
  ///
  /// In en, this message translates to:
  /// **'Problems reported'**
  String get problemsTitle;

  /// No description provided for @problemReportAction.
  ///
  /// In en, this message translates to:
  /// **'Report a problem'**
  String get problemReportAction;

  /// No description provided for @problemSheetTitle.
  ///
  /// In en, this message translates to:
  /// **'Report a problem'**
  String get problemSheetTitle;

  /// No description provided for @problemSheetIntro.
  ///
  /// In en, this message translates to:
  /// **'What went wrong with this delivery?'**
  String get problemSheetIntro;

  /// No description provided for @problemKindSenderUnavailable.
  ///
  /// In en, this message translates to:
  /// **'The sender did not come'**
  String get problemKindSenderUnavailable;

  /// No description provided for @problemKindTravelerNoShow.
  ///
  /// In en, this message translates to:
  /// **'The traveler did not come'**
  String get problemKindTravelerNoShow;

  /// No description provided for @problemKindRecipientUnavailable.
  ///
  /// In en, this message translates to:
  /// **'The recipient is not available'**
  String get problemKindRecipientUnavailable;

  /// No description provided for @problemKindParcelMismatch.
  ///
  /// In en, this message translates to:
  /// **'The parcel is not what was described'**
  String get problemKindParcelMismatch;

  /// No description provided for @problemKindParcelDamaged.
  ///
  /// In en, this message translates to:
  /// **'The parcel is damaged'**
  String get problemKindParcelDamaged;

  /// No description provided for @problemKindTripDisrupted.
  ///
  /// In en, this message translates to:
  /// **'The trip is cancelled or delayed'**
  String get problemKindTripDisrupted;

  /// No description provided for @problemKindCustomsDelay.
  ///
  /// In en, this message translates to:
  /// **'Held up at customs'**
  String get problemKindCustomsDelay;

  /// No description provided for @problemKindOther.
  ///
  /// In en, this message translates to:
  /// **'Something else'**
  String get problemKindOther;

  /// No description provided for @problemNoteLabel.
  ///
  /// In en, this message translates to:
  /// **'Note (optional)'**
  String get problemNoteLabel;

  /// No description provided for @problemNoteHint.
  ///
  /// In en, this message translates to:
  /// **'Add anything that helps, such as where you are.'**
  String get problemNoteHint;

  /// No description provided for @problemNextBody.
  ///
  /// In en, this message translates to:
  /// **'The other person is told. Wassla staff look at damage and mismatches right away. Reporting does not cancel or refund anything.'**
  String get problemNextBody;

  /// No description provided for @problemSendAction.
  ///
  /// In en, this message translates to:
  /// **'Send report'**
  String get problemSendAction;

  /// No description provided for @problemSent.
  ///
  /// In en, this message translates to:
  /// **'Report sent. The other person has been told.'**
  String get problemSent;

  /// No description provided for @problemReportedByYou.
  ///
  /// In en, this message translates to:
  /// **'Reported by you'**
  String get problemReportedByYou;

  /// No description provided for @problemReportedByOther.
  ///
  /// In en, this message translates to:
  /// **'Reported by the other person'**
  String get problemReportedByOther;

  /// No description provided for @problemStatusOpen.
  ///
  /// In en, this message translates to:
  /// **'Sent'**
  String get problemStatusOpen;

  /// No description provided for @problemStatusEscalated.
  ///
  /// In en, this message translates to:
  /// **'With Wassla staff'**
  String get problemStatusEscalated;

  /// No description provided for @problemStatusAcknowledged.
  ///
  /// In en, this message translates to:
  /// **'Being looked at'**
  String get problemStatusAcknowledged;

  /// No description provided for @problemStatusClosed.
  ///
  /// In en, this message translates to:
  /// **'Closed'**
  String get problemStatusClosed;

  /// No description provided for @problemErrorOffline.
  ///
  /// In en, this message translates to:
  /// **'No connection. Nothing was sent. Try again when you are online.'**
  String get problemErrorOffline;

  /// No description provided for @problemErrorNoShowClosed.
  ///
  /// In en, this message translates to:
  /// **'This can’t be reported right now. The pickup time may not have come yet, or the parcel may already be collected.'**
  String get problemErrorNoShowClosed;

  /// No description provided for @problemErrorNotAllowed.
  ///
  /// In en, this message translates to:
  /// **'This delivery can’t take a report right now.'**
  String get problemErrorNotAllowed;

  /// No description provided for @problemErrorNoteTooLong.
  ///
  /// In en, this message translates to:
  /// **'The note is too long. Keep it under 1,000 characters.'**
  String get problemErrorNoteTooLong;

  /// No description provided for @noShowActionSender.
  ///
  /// In en, this message translates to:
  /// **'The sender did not come'**
  String get noShowActionSender;

  /// No description provided for @noShowActionTraveler.
  ///
  /// In en, this message translates to:
  /// **'The traveler did not come'**
  String get noShowActionTraveler;

  /// No description provided for @noShowSheetIntro.
  ///
  /// In en, this message translates to:
  /// **'Tell us if the other person has not shown up for the handover.'**
  String get noShowSheetIntro;

  /// No description provided for @noShowNextBody.
  ///
  /// In en, this message translates to:
  /// **'Wassla staff will look at it. Nothing is cancelled or refunded yet.'**
  String get noShowNextBody;

  /// No description provided for @noShowSendAction.
  ///
  /// In en, this message translates to:
  /// **'Send to Wassla'**
  String get noShowSendAction;

  /// No description provided for @noShowReportedSender.
  ///
  /// In en, this message translates to:
  /// **'You reported that the sender did not come'**
  String get noShowReportedSender;

  /// No description provided for @noShowReportedTraveler.
  ///
  /// In en, this message translates to:
  /// **'You reported that the traveler did not come'**
  String get noShowReportedTraveler;

  /// No description provided for @noShowMessageInChat.
  ///
  /// In en, this message translates to:
  /// **'Message in chat'**
  String get noShowMessageInChat;

  /// No description provided for @noShowReplyInChat.
  ///
  /// In en, this message translates to:
  /// **'Reply in chat'**
  String get noShowReplyInChat;

  /// No description provided for @noShowAgainstSenderTitle.
  ///
  /// In en, this message translates to:
  /// **'The traveler says you did not come'**
  String get noShowAgainstSenderTitle;

  /// No description provided for @noShowAgainstSenderBody.
  ///
  /// In en, this message translates to:
  /// **'If there is a mix-up, tell them in chat. Wassla staff will look at it. Nothing is cancelled or refunded yet.'**
  String get noShowAgainstSenderBody;

  /// No description provided for @noShowAgainstTravelerTitle.
  ///
  /// In en, this message translates to:
  /// **'The sender says you did not come'**
  String get noShowAgainstTravelerTitle;

  /// No description provided for @noShowAgainstTravelerBody.
  ///
  /// In en, this message translates to:
  /// **'If there is a mix-up, tell them in chat. Wassla staff will look at it. Nothing is cancelled or refunded yet.'**
  String get noShowAgainstTravelerBody;

  /// No description provided for @notificationProblemReported.
  ///
  /// In en, this message translates to:
  /// **'A problem was reported on a delivery'**
  String get notificationProblemReported;

  /// No description provided for @notificationScheduleChangeProposed.
  ///
  /// In en, this message translates to:
  /// **'New times need your answer'**
  String get notificationScheduleChangeProposed;

  /// No description provided for @notificationScheduleChangeAnswered.
  ///
  /// In en, this message translates to:
  /// **'A sender answered your new times'**
  String get notificationScheduleChangeAnswered;

  /// No description provided for @notificationScheduleChangeApplied.
  ///
  /// In en, this message translates to:
  /// **'The times of a trip changed'**
  String get notificationScheduleChangeApplied;

  /// No description provided for @notificationScheduleChangeWithdrawn.
  ///
  /// In en, this message translates to:
  /// **'New times were withdrawn'**
  String get notificationScheduleChangeWithdrawn;

  /// No description provided for @scheduleDeparture.
  ///
  /// In en, this message translates to:
  /// **'Departure'**
  String get scheduleDeparture;

  /// No description provided for @scheduleArrival.
  ///
  /// In en, this message translates to:
  /// **'Arrival'**
  String get scheduleArrival;

  /// No description provided for @schedulePickup.
  ///
  /// In en, this message translates to:
  /// **'Pickup'**
  String get schedulePickup;

  /// No description provided for @scheduleParcelFallback.
  ///
  /// In en, this message translates to:
  /// **'A parcel'**
  String get scheduleParcelFallback;

  /// No description provided for @scheduleReasonDeadline.
  ///
  /// In en, this message translates to:
  /// **'The new arrival is after your deadline.'**
  String get scheduleReasonDeadline;

  /// No description provided for @scheduleReasonShift.
  ///
  /// In en, this message translates to:
  /// **'The arrival moves by more than the allowed margin.'**
  String get scheduleReasonShift;

  /// No description provided for @scheduleReasonPickup.
  ///
  /// In en, this message translates to:
  /// **'The pickup time moves.'**
  String get scheduleReasonPickup;

  /// No description provided for @scheduleSectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Trip times'**
  String get scheduleSectionTitle;

  /// No description provided for @scheduleSectionIntro.
  ///
  /// In en, this message translates to:
  /// **'Plans changed? Update your times. Senders whose parcel is affected are told, and some may need to agree.'**
  String get scheduleSectionIntro;

  /// No description provided for @scheduleChangeAction.
  ///
  /// In en, this message translates to:
  /// **'Change times'**
  String get scheduleChangeAction;

  /// No description provided for @scheduleWaitingPill.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{Waiting for 1 sender} other{Waiting for {count} senders}}'**
  String scheduleWaitingPill(int count);

  /// No description provided for @scheduleWaitingBody.
  ///
  /// In en, this message translates to:
  /// **'Your trip keeps its current times until every sender who must agree has answered.'**
  String get scheduleWaitingBody;

  /// No description provided for @scheduleSendersTitle.
  ///
  /// In en, this message translates to:
  /// **'Senders asked'**
  String get scheduleSendersTitle;

  /// No description provided for @scheduleConsentPending.
  ///
  /// In en, this message translates to:
  /// **'Waiting'**
  String get scheduleConsentPending;

  /// No description provided for @scheduleConsentAccepted.
  ///
  /// In en, this message translates to:
  /// **'Agreed'**
  String get scheduleConsentAccepted;

  /// No description provided for @scheduleConsentDeclined.
  ///
  /// In en, this message translates to:
  /// **'Declined'**
  String get scheduleConsentDeclined;

  /// No description provided for @scheduleWithdrawAction.
  ///
  /// In en, this message translates to:
  /// **'Withdraw the new times'**
  String get scheduleWithdrawAction;

  /// No description provided for @scheduleWithdrawn.
  ///
  /// In en, this message translates to:
  /// **'The new times were withdrawn.'**
  String get scheduleWithdrawn;

  /// No description provided for @scheduleWithdrawnByYou.
  ///
  /// In en, this message translates to:
  /// **'You withdrew the last new times. Your trip keeps its earlier times.'**
  String get scheduleWithdrawnByYou;

  /// No description provided for @scheduleWithdrawnNoLongerValid.
  ///
  /// In en, this message translates to:
  /// **'The last new times were dropped because the trip had moved on. Your trip keeps its current times.'**
  String get scheduleWithdrawnNoLongerValid;

  /// No description provided for @scheduleChangeTitle.
  ///
  /// In en, this message translates to:
  /// **'Change times'**
  String get scheduleChangeTitle;

  /// No description provided for @scheduleChangeIntro.
  ///
  /// In en, this message translates to:
  /// **'Pick the new departure and arrival for the legs that changed. You will see who is affected before anything is sent.'**
  String get scheduleChangeIntro;

  /// No description provided for @scheduleStopsNote.
  ///
  /// In en, this message translates to:
  /// **'Only times can change on a live trip. To add or remove a stop, cancel the trip and create a new one.'**
  String get scheduleStopsNote;

  /// No description provided for @scheduleReviewAction.
  ///
  /// In en, this message translates to:
  /// **'Review the changes'**
  String get scheduleReviewAction;

  /// No description provided for @scheduleReviewTitle.
  ///
  /// In en, this message translates to:
  /// **'Review new times'**
  String get scheduleReviewTitle;

  /// No description provided for @scheduleEditTimes.
  ///
  /// In en, this message translates to:
  /// **'Edit times'**
  String get scheduleEditTimes;

  /// No description provided for @scheduleSendAction.
  ///
  /// In en, this message translates to:
  /// **'Send new times'**
  String get scheduleSendAction;

  /// No description provided for @scheduleApplyAction.
  ///
  /// In en, this message translates to:
  /// **'Apply new times'**
  String get scheduleApplyAction;

  /// No description provided for @scheduleAppliesAtOnceTitle.
  ///
  /// In en, this message translates to:
  /// **'No sender needs to agree'**
  String get scheduleAppliesAtOnceTitle;

  /// No description provided for @scheduleAppliesAtOnceBody.
  ///
  /// In en, this message translates to:
  /// **'These times apply as soon as you send them. Affected senders are told.'**
  String get scheduleAppliesAtOnceBody;

  /// No description provided for @scheduleWaitsTitle.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 sender must agree first} other{{count} senders must agree first}}'**
  String scheduleWaitsTitle(int count);

  /// No description provided for @scheduleWaitsBody.
  ///
  /// In en, this message translates to:
  /// **'The new times apply once they all agree. Until then your trip keeps its current times. A sender who declines can cancel, and that cancellation is counted as yours.'**
  String get scheduleWaitsBody;

  /// No description provided for @scheduleNewTimesTitle.
  ///
  /// In en, this message translates to:
  /// **'New times'**
  String get scheduleNewTimesTitle;

  /// No description provided for @scheduleAffectedTitle.
  ///
  /// In en, this message translates to:
  /// **'Parcels affected'**
  String get scheduleAffectedTitle;

  /// No description provided for @scheduleNoParcelsAffected.
  ///
  /// In en, this message translates to:
  /// **'No parcel is affected by these times.'**
  String get scheduleNoParcelsAffected;

  /// No description provided for @scheduleMustAgreeTitle.
  ///
  /// In en, this message translates to:
  /// **'Senders who must agree'**
  String get scheduleMustAgreeTitle;

  /// No description provided for @scheduleToldTitle.
  ///
  /// In en, this message translates to:
  /// **'Senders who will be told'**
  String get scheduleToldTitle;

  /// No description provided for @scheduleReasonLabel.
  ///
  /// In en, this message translates to:
  /// **'Note to senders (optional)'**
  String get scheduleReasonLabel;

  /// No description provided for @scheduleReasonHint.
  ///
  /// In en, this message translates to:
  /// **'For example: the flight was moved by the airline.'**
  String get scheduleReasonHint;

  /// No description provided for @scheduleReasonHelper.
  ///
  /// In en, this message translates to:
  /// **'Senders who are asked will read this.'**
  String get scheduleReasonHelper;

  /// No description provided for @scheduleSentToSenders.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{Sent. Waiting for 1 sender.} other{Sent. Waiting for {count} senders.}}'**
  String scheduleSentToSenders(int count);

  /// No description provided for @scheduleApplied.
  ///
  /// In en, this message translates to:
  /// **'New times saved. Affected senders have been told.'**
  String get scheduleApplied;

  /// No description provided for @scheduleErrorOffline.
  ///
  /// In en, this message translates to:
  /// **'No connection. Nothing was changed. Try again when you are online.'**
  String get scheduleErrorOffline;

  /// No description provided for @scheduleErrorNotReschedulable.
  ///
  /// In en, this message translates to:
  /// **'Times can only change on a trip that is live and not finished.'**
  String get scheduleErrorNotReschedulable;

  /// No description provided for @scheduleErrorEmpty.
  ///
  /// In en, this message translates to:
  /// **'These are the times already in force. Change at least one.'**
  String get scheduleErrorEmpty;

  /// No description provided for @scheduleErrorPending.
  ///
  /// In en, this message translates to:
  /// **'New times are already waiting for senders. Withdraw them first to send others.'**
  String get scheduleErrorPending;

  /// No description provided for @scheduleErrorLegArrived.
  ///
  /// In en, this message translates to:
  /// **'A leg that has already arrived can’t change.'**
  String get scheduleErrorLegArrived;

  /// No description provided for @scheduleErrorLegDeparted.
  ///
  /// In en, this message translates to:
  /// **'A leg that has already departed keeps its departure. Only its arrival can move.'**
  String get scheduleErrorLegDeparted;

  /// No description provided for @scheduleErrorDepartureInPast.
  ///
  /// In en, this message translates to:
  /// **'A departure can’t be in the past.'**
  String get scheduleErrorDepartureInPast;

  /// No description provided for @scheduleErrorNotWaiting.
  ///
  /// In en, this message translates to:
  /// **'These new times are no longer waiting. The screen has been refreshed.'**
  String get scheduleErrorNotWaiting;

  /// No description provided for @scheduleAnswerTitle.
  ///
  /// In en, this message translates to:
  /// **'New times'**
  String get scheduleAnswerTitle;

  /// No description provided for @scheduleNoneTitle.
  ///
  /// In en, this message translates to:
  /// **'No change to the times'**
  String get scheduleNoneTitle;

  /// No description provided for @scheduleNoneBody.
  ///
  /// In en, this message translates to:
  /// **'The traveler has not changed the times of this delivery.'**
  String get scheduleNoneBody;

  /// No description provided for @scheduleAskedHeadline.
  ///
  /// In en, this message translates to:
  /// **'The traveler changed the times'**
  String get scheduleAskedHeadline;

  /// No description provided for @scheduleAskedBody.
  ///
  /// In en, this message translates to:
  /// **'Your delivery is affected. Check the new times and tell us if they work for you.'**
  String get scheduleAskedBody;

  /// No description provided for @scheduleYouAcceptedHeadline.
  ///
  /// In en, this message translates to:
  /// **'You agreed to the new times'**
  String get scheduleYouAcceptedHeadline;

  /// No description provided for @scheduleYouDeclinedHeadline.
  ///
  /// In en, this message translates to:
  /// **'You declined the new times'**
  String get scheduleYouDeclinedHeadline;

  /// No description provided for @scheduleAppliedHeadline.
  ///
  /// In en, this message translates to:
  /// **'The new times are in force'**
  String get scheduleAppliedHeadline;

  /// No description provided for @scheduleAppliedBody.
  ///
  /// In en, this message translates to:
  /// **'The traveler’s trip now runs on the times below.'**
  String get scheduleAppliedBody;

  /// No description provided for @scheduleWithdrawnHeadline.
  ///
  /// In en, this message translates to:
  /// **'The new times were withdrawn'**
  String get scheduleWithdrawnHeadline;

  /// No description provided for @scheduleWithdrawnBody.
  ///
  /// In en, this message translates to:
  /// **'Nothing changes for your delivery. The earlier times still stand.'**
  String get scheduleWithdrawnBody;

  /// No description provided for @scheduleInformedHeadline.
  ///
  /// In en, this message translates to:
  /// **'The traveler’s times changed'**
  String get scheduleInformedHeadline;

  /// No description provided for @scheduleInformedBody.
  ///
  /// In en, this message translates to:
  /// **'Your parcel has already been collected, so you are not asked to agree. The arrival you agreed to when you paid still protects you. If something is wrong, you can report a problem or open a dispute.'**
  String get scheduleInformedBody;

  /// No description provided for @scheduleCompareTitle.
  ///
  /// In en, this message translates to:
  /// **'Old and new times'**
  String get scheduleCompareTitle;

  /// No description provided for @scheduleYourDeadline.
  ///
  /// In en, this message translates to:
  /// **'Your deadline: {date}'**
  String scheduleYourDeadline(String date);

  /// No description provided for @scheduleWhyTitle.
  ///
  /// In en, this message translates to:
  /// **'Why we are asking'**
  String get scheduleWhyTitle;

  /// No description provided for @scheduleTravelerNote.
  ///
  /// In en, this message translates to:
  /// **'Note from the traveler'**
  String get scheduleTravelerNote;

  /// No description provided for @scheduleLegsTitle.
  ///
  /// In en, this message translates to:
  /// **'Changed legs'**
  String get scheduleLegsTitle;

  /// No description provided for @scheduleAcceptAction.
  ///
  /// In en, this message translates to:
  /// **'Accept the new times'**
  String get scheduleAcceptAction;

  /// No description provided for @scheduleAcceptInstead.
  ///
  /// In en, this message translates to:
  /// **'Accept the new times instead'**
  String get scheduleAcceptInstead;

  /// No description provided for @scheduleDeclineAction.
  ///
  /// In en, this message translates to:
  /// **'Decline'**
  String get scheduleDeclineAction;

  /// No description provided for @scheduleDeclineInstead.
  ///
  /// In en, this message translates to:
  /// **'Decline instead'**
  String get scheduleDeclineInstead;

  /// No description provided for @scheduleDeclineKeep.
  ///
  /// In en, this message translates to:
  /// **'Go back'**
  String get scheduleDeclineKeep;

  /// No description provided for @scheduleDeclineConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Decline the new times?'**
  String get scheduleDeclineConfirmTitle;

  /// No description provided for @scheduleDeclineConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'Nothing is cancelled. You will then be able to cancel this delivery, and because the traveler changed the times, that cancellation is not counted as yours. You can still change your mind until the traveler decides.'**
  String get scheduleDeclineConfirmBody;

  /// No description provided for @scheduleAcceptedSnack.
  ///
  /// In en, this message translates to:
  /// **'You agreed to the new times.'**
  String get scheduleAcceptedSnack;

  /// No description provided for @scheduleDeclinedSnack.
  ///
  /// In en, this message translates to:
  /// **'You declined the new times.'**
  String get scheduleDeclinedSnack;

  /// No description provided for @scheduleIfYouCancelTitle.
  ///
  /// In en, this message translates to:
  /// **'If you cancel now'**
  String get scheduleIfYouCancelTitle;

  /// No description provided for @scheduleCancelCountsAsTraveler.
  ///
  /// In en, this message translates to:
  /// **'Counted as the traveler’s cancellation, because they changed the times.'**
  String get scheduleCancelCountsAsTraveler;

  /// No description provided for @scheduleCancelNotAvailable.
  ///
  /// In en, this message translates to:
  /// **'This delivery can’t be cancelled right now.'**
  String get scheduleCancelNotAvailable;

  /// No description provided for @scheduleInformedActionsTitle.
  ///
  /// In en, this message translates to:
  /// **'If something is wrong'**
  String get scheduleInformedActionsTitle;

  /// No description provided for @scheduleErrorNoAnswerNeeded.
  ///
  /// In en, this message translates to:
  /// **'No answer is needed for this delivery.'**
  String get scheduleErrorNoAnswerNeeded;

  /// No description provided for @scheduleViewAction.
  ///
  /// In en, this message translates to:
  /// **'View'**
  String get scheduleViewAction;

  /// No description provided for @scheduleDealAskedBody.
  ///
  /// In en, this message translates to:
  /// **'Check the new times and tell us if they work for you.'**
  String get scheduleDealAskedBody;

  /// No description provided for @scheduleDealDeclinedBody.
  ///
  /// In en, this message translates to:
  /// **'You can cancel this delivery, and it won’t be counted as yours.'**
  String get scheduleDealDeclinedBody;

  /// No description provided for @scheduleDealAcceptedBody.
  ///
  /// In en, this message translates to:
  /// **'You agreed to the new times. We are waiting for the other senders.'**
  String get scheduleDealAcceptedBody;

  /// No description provided for @scheduleDealInformedBody.
  ///
  /// In en, this message translates to:
  /// **'The traveler’s times changed after pickup. See the old and new times.'**
  String get scheduleDealInformedBody;

  /// No description provided for @offerAnswerBy.
  ///
  /// In en, this message translates to:
  /// **'Answer by {when}'**
  String offerAnswerBy(String when);

  /// No description provided for @offerWaitingUntil.
  ///
  /// In en, this message translates to:
  /// **'Waiting for an answer until {when}'**
  String offerWaitingUntil(String when);

  /// No description provided for @offerAnswerWithin.
  ///
  /// In en, this message translates to:
  /// **'Answer within {time}'**
  String offerAnswerWithin(String time);

  /// No description provided for @offerWaitingWithin.
  ///
  /// In en, this message translates to:
  /// **'Waiting for an answer, {time} left'**
  String offerWaitingWithin(String time);

  /// No description provided for @offerMinutesLeft.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =0{less than a minute} =1{1 minute} other{{count} minutes}}'**
  String offerMinutesLeft(int count);

  /// No description provided for @offerDeadlinePassed.
  ///
  /// In en, this message translates to:
  /// **'The time to answer has passed'**
  String get offerDeadlinePassed;

  /// No description provided for @offerExpiredOn.
  ///
  /// In en, this message translates to:
  /// **'Expired {when}'**
  String offerExpiredOn(String when);

  /// No description provided for @offerExpiredTitle.
  ///
  /// In en, this message translates to:
  /// **'This proposal expired'**
  String get offerExpiredTitle;

  /// No description provided for @offerExpiredBodySender.
  ///
  /// In en, this message translates to:
  /// **'No answer came in time. Nothing was reserved or charged, and your parcel is still open for other travelers.'**
  String get offerExpiredBodySender;

  /// No description provided for @offerExpiredBodyTraveler.
  ///
  /// In en, this message translates to:
  /// **'No answer came in time. Nothing was reserved or charged. Other parcels may fit your trip.'**
  String get offerExpiredBodyTraveler;

  /// No description provided for @offerExpiredActionSender.
  ///
  /// In en, this message translates to:
  /// **'Propose to another traveler'**
  String get offerExpiredActionSender;

  /// No description provided for @offerExpiredActionTraveler.
  ///
  /// In en, this message translates to:
  /// **'Browse parcels'**
  String get offerExpiredActionTraveler;

  /// No description provided for @notificationOfferReminder.
  ///
  /// In en, this message translates to:
  /// **'A proposal is about to expire'**
  String get notificationOfferReminder;

  /// No description provided for @notificationFitsTrip.
  ///
  /// In en, this message translates to:
  /// **'A parcel fits your trip'**
  String get notificationFitsTrip;

  /// No description provided for @requestFitsTripHint.
  ///
  /// In en, this message translates to:
  /// **'Suggested for your trip {route}'**
  String requestFitsTripHint(String route);

  /// No description provided for @discoveryFocusGoneRequestTitle.
  ///
  /// In en, this message translates to:
  /// **'This parcel is no longer open'**
  String get discoveryFocusGoneRequestTitle;

  /// No description provided for @discoveryFocusGoneRequestBody.
  ///
  /// In en, this message translates to:
  /// **'It may have been taken or withdrawn. Here are the parcels that are open now.'**
  String get discoveryFocusGoneRequestBody;

  /// No description provided for @discoveryFocusGoneTripTitle.
  ///
  /// In en, this message translates to:
  /// **'This trip is no longer listed'**
  String get discoveryFocusGoneTripTitle;

  /// No description provided for @discoveryFocusGoneTripBody.
  ///
  /// In en, this message translates to:
  /// **'Here are the trips that are listed now.'**
  String get discoveryFocusGoneTripBody;

  /// No description provided for @reviewsTitle.
  ///
  /// In en, this message translates to:
  /// **'Reviews'**
  String get reviewsTitle;

  /// No description provided for @reviewsCount.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 review} other{{count} reviews}}'**
  String reviewsCount(int count);

  /// No description provided for @reviewsOpenHint.
  ///
  /// In en, this message translates to:
  /// **'See reviews'**
  String get reviewsOpenHint;

  /// No description provided for @reviewsRatingA11y.
  ///
  /// In en, this message translates to:
  /// **'Rated {rating} out of 5, {count, plural, =1{1 review} other{{count} reviews}}. Opens the reviews.'**
  String reviewsRatingA11y(String rating, int count);

  /// No description provided for @reviewsNewSummary.
  ///
  /// In en, this message translates to:
  /// **'No reviews yet'**
  String get reviewsNewSummary;

  /// No description provided for @reviewsEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No reviews yet'**
  String get reviewsEmptyTitle;

  /// No description provided for @reviewsEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'A review shows here once a delivery has been rated and the review is open to both sides.'**
  String get reviewsEmptyBody;

  /// No description provided for @reviewsOffTitle.
  ///
  /// In en, this message translates to:
  /// **'Reviews are not available'**
  String get reviewsOffTitle;

  /// No description provided for @reviewsOffBody.
  ///
  /// In en, this message translates to:
  /// **'Reviews are switched off for now. Please check back later.'**
  String get reviewsOffBody;

  /// No description provided for @reviewsGoneTitle.
  ///
  /// In en, this message translates to:
  /// **'This is not available any more'**
  String get reviewsGoneTitle;

  /// No description provided for @reviewsGoneBody.
  ///
  /// In en, this message translates to:
  /// **'The person or trip is no longer listed, so its reviews cannot be shown.'**
  String get reviewsGoneBody;

  /// No description provided for @reviewsFromSender.
  ///
  /// In en, this message translates to:
  /// **'From a sender'**
  String get reviewsFromSender;

  /// No description provided for @reviewsFromTraveler.
  ///
  /// In en, this message translates to:
  /// **'From a traveler'**
  String get reviewsFromTraveler;

  /// No description provided for @reviewsCommentRemoved.
  ///
  /// In en, this message translates to:
  /// **'Comment removed by Wassla'**
  String get reviewsCommentRemoved;

  /// No description provided for @reviewsMenuLabel.
  ///
  /// In en, this message translates to:
  /// **'Review options'**
  String get reviewsMenuLabel;

  /// No description provided for @reviewsReportAction.
  ///
  /// In en, this message translates to:
  /// **'Report'**
  String get reviewsReportAction;

  /// No description provided for @reviewsReportReceived.
  ///
  /// In en, this message translates to:
  /// **'You reported this. We have received it.'**
  String get reviewsReportReceived;

  /// No description provided for @reviewsReportReviewed.
  ///
  /// In en, this message translates to:
  /// **'You reported this. We have reviewed it.'**
  String get reviewsReportReviewed;

  /// No description provided for @reviewReportSheetTitle.
  ///
  /// In en, this message translates to:
  /// **'Report this review'**
  String get reviewReportSheetTitle;

  /// No description provided for @reviewReportSheetIntro.
  ///
  /// In en, this message translates to:
  /// **'Tell us what is wrong. We will look at it, and the person is not told that you reported it.'**
  String get reviewReportSheetIntro;

  /// No description provided for @reviewReasonOffensive.
  ///
  /// In en, this message translates to:
  /// **'Offensive or abusive'**
  String get reviewReasonOffensive;

  /// No description provided for @reviewReasonPersonalInformation.
  ///
  /// In en, this message translates to:
  /// **'Shares personal information'**
  String get reviewReasonPersonalInformation;

  /// No description provided for @reviewReasonUnrelated.
  ///
  /// In en, this message translates to:
  /// **'Not about the delivery'**
  String get reviewReasonUnrelated;

  /// No description provided for @reviewReasonUntrue.
  ///
  /// In en, this message translates to:
  /// **'Not true'**
  String get reviewReasonUntrue;

  /// No description provided for @reviewReasonOther.
  ///
  /// In en, this message translates to:
  /// **'Something else'**
  String get reviewReasonOther;

  /// No description provided for @reviewReportNoteLabel.
  ///
  /// In en, this message translates to:
  /// **'Note (optional)'**
  String get reviewReportNoteLabel;

  /// No description provided for @reviewReportNoteHint.
  ///
  /// In en, this message translates to:
  /// **'Anything that helps us understand'**
  String get reviewReportNoteHint;

  /// No description provided for @reviewReportSend.
  ///
  /// In en, this message translates to:
  /// **'Send report'**
  String get reviewReportSend;

  /// No description provided for @reviewReportThanks.
  ///
  /// In en, this message translates to:
  /// **'Thanks, we will review it'**
  String get reviewReportThanks;

  /// No description provided for @reviewReportOwn.
  ///
  /// In en, this message translates to:
  /// **'You cannot report your own review.'**
  String get reviewReportOwn;

  /// No description provided for @reviewReportRemoved.
  ///
  /// In en, this message translates to:
  /// **'Wassla has already removed this review.'**
  String get reviewReportRemoved;

  /// No description provided for @reviewReportGone.
  ///
  /// In en, this message translates to:
  /// **'This review is not available any more.'**
  String get reviewReportGone;

  /// No description provided for @ratingRemovedByWassla.
  ///
  /// In en, this message translates to:
  /// **'Removed by Wassla, not counted'**
  String get ratingRemovedByWassla;

  /// No description provided for @ratingCommentHiddenByWassla.
  ///
  /// In en, this message translates to:
  /// **'Wassla hid the comment from others. The score still counts.'**
  String get ratingCommentHiddenByWassla;

  /// No description provided for @supportEmailSubject.
  ///
  /// In en, this message translates to:
  /// **'Help with Wassla'**
  String get supportEmailSubject;

  /// No description provided for @supportEmailSubjectDelivery.
  ///
  /// In en, this message translates to:
  /// **'Help with Wassla delivery {tracking}'**
  String supportEmailSubjectDelivery(String tracking);

  /// No description provided for @supportEmailFailed.
  ///
  /// In en, this message translates to:
  /// **'No email app opened. Write to {email}.'**
  String supportEmailFailed(String email);

  /// No description provided for @journeyPausedStaffBodyNoContact.
  ///
  /// In en, this message translates to:
  /// **'Wassla paused this journey.'**
  String get journeyPausedStaffBodyNoContact;

  /// No description provided for @authVerifyResent.
  ///
  /// In en, this message translates to:
  /// **'We sent a new code. Use the code in the newest email.'**
  String get authVerifyResent;

  /// No description provided for @authVerifyResend.
  ///
  /// In en, this message translates to:
  /// **'Send the code again'**
  String get authVerifyResend;

  /// No description provided for @profileVerifyEmail.
  ///
  /// In en, this message translates to:
  /// **'Verify email'**
  String get profileVerifyEmail;

  /// No description provided for @profileRating.
  ///
  /// In en, this message translates to:
  /// **'Rating'**
  String get profileRating;

  /// No description provided for @accountGateStamp.
  ///
  /// In en, this message translates to:
  /// **'Your Wassla account'**
  String get accountGateStamp;

  /// No description provided for @accountGateEmail.
  ///
  /// In en, this message translates to:
  /// **'Continue with email'**
  String get accountGateEmail;

  /// No description provided for @accountGateHaveAccount.
  ///
  /// In en, this message translates to:
  /// **'I already have an account'**
  String get accountGateHaveAccount;

  /// No description provided for @accountReasonPostRequestTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto send your parcel.'**
  String get accountReasonPostRequestTitle;

  /// No description provided for @accountReasonPostRequestBody.
  ///
  /// In en, this message translates to:
  /// **'Travelers see who is sending. Your payment is held, and the traveler is paid 48 hours after delivery.'**
  String get accountReasonPostRequestBody;

  /// No description provided for @accountReasonPostTripTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto post your trip.'**
  String get accountReasonPostTripTitle;

  /// No description provided for @accountReasonPostTripBody.
  ///
  /// In en, this message translates to:
  /// **'Senders choose travelers they can trust: your account holds your ID check and your reviews.'**
  String get accountReasonPostTripBody;

  /// No description provided for @accountReasonCarryTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto carry this parcel.'**
  String get accountReasonCarryTitle;

  /// No description provided for @accountReasonCarryBody.
  ///
  /// In en, this message translates to:
  /// **'The sender sees who offers to carry it. You are paid into your account 48 hours after delivery.'**
  String get accountReasonCarryBody;

  /// No description provided for @accountReasonAlertTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto get route alerts.'**
  String get accountReasonAlertTitle;

  /// No description provided for @accountReasonAlertBody.
  ///
  /// In en, this message translates to:
  /// **'We tell you when a trip or a parcel matches this route.'**
  String get accountReasonAlertBody;

  /// No description provided for @accountReasonReportTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto report a review.'**
  String get accountReasonReportTitle;

  /// No description provided for @accountReasonReportBody.
  ///
  /// In en, this message translates to:
  /// **'Reports come from members, so we can look into them with you.'**
  String get accountReasonReportBody;

  /// No description provided for @accountReasonDeliveriesTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto follow deliveries.'**
  String get accountReasonDeliveriesTitle;

  /// No description provided for @accountReasonDeliveriesBody.
  ///
  /// In en, this message translates to:
  /// **'The parcels you send and the ones you carry all appear in one place.'**
  String get accountReasonDeliveriesBody;

  /// No description provided for @accountReasonChatTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto chat.'**
  String get accountReasonChatTitle;

  /// No description provided for @accountReasonChatBody.
  ///
  /// In en, this message translates to:
  /// **'Chat opens between a sender and a traveler once a delivery is paid for.'**
  String get accountReasonChatBody;

  /// No description provided for @accountReasonNotificationsTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto get notifications.'**
  String get accountReasonNotificationsTitle;

  /// No description provided for @accountReasonNotificationsBody.
  ///
  /// In en, this message translates to:
  /// **'Offers, messages and delivery updates reach you here.'**
  String get accountReasonNotificationsBody;

  /// No description provided for @accountReasonGenericTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account\nto get started.'**
  String get accountReasonGenericTitle;

  /// No description provided for @accountReasonGenericBody.
  ///
  /// In en, this message translates to:
  /// **'Send a parcel, or carry one on a trip you are already making.'**
  String get accountReasonGenericBody;

  /// No description provided for @guestSignedOutNotice.
  ///
  /// In en, this message translates to:
  /// **'You were signed out. Sign in again.'**
  String get guestSignedOutNotice;

  /// No description provided for @guestNoticeDismiss.
  ///
  /// In en, this message translates to:
  /// **'Dismiss'**
  String get guestNoticeDismiss;

  /// No description provided for @guestWelcomeTitle.
  ///
  /// In en, this message translates to:
  /// **'Send it with someone already making the trip.'**
  String get guestWelcomeTitle;

  /// No description provided for @guestWelcomeBody.
  ///
  /// In en, this message translates to:
  /// **'Look around: these are real trips and parcels. You need an account only to post, carry, set alerts or report a review.'**
  String get guestWelcomeBody;

  /// No description provided for @guestHowItWorks.
  ///
  /// In en, this message translates to:
  /// **'How Wassla works'**
  String get guestHowItWorks;

  /// No description provided for @guestAccountAction.
  ///
  /// In en, this message translates to:
  /// **'Sign in or create an account'**
  String get guestAccountAction;

  /// No description provided for @guestDeliveriesTitle.
  ///
  /// In en, this message translates to:
  /// **'Your deliveries appear here'**
  String get guestDeliveriesTitle;

  /// No description provided for @guestDeliveriesBody.
  ///
  /// In en, this message translates to:
  /// **'Sign in to follow the parcels you send and the ones you carry.'**
  String get guestDeliveriesBody;

  /// No description provided for @guestChatTitle.
  ///
  /// In en, this message translates to:
  /// **'Your conversations appear here'**
  String get guestChatTitle;

  /// No description provided for @guestChatBody.
  ///
  /// In en, this message translates to:
  /// **'Chat opens between a sender and a traveler once a delivery is paid for.'**
  String get guestChatBody;

  /// No description provided for @guestProfileTitle.
  ///
  /// In en, this message translates to:
  /// **'You are looking around as a guest'**
  String get guestProfileTitle;

  /// No description provided for @guestProfileBody.
  ///
  /// In en, this message translates to:
  /// **'Create an account to send a parcel or to carry one. It takes two minutes.'**
  String get guestProfileBody;

  /// No description provided for @guestSettings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get guestSettings;

  /// No description provided for @socialContinueWithApple.
  ///
  /// In en, this message translates to:
  /// **'Continue with Apple'**
  String get socialContinueWithApple;

  /// No description provided for @socialContinueWithGoogle.
  ///
  /// In en, this message translates to:
  /// **'Continue with Google'**
  String get socialContinueWithGoogle;

  /// No description provided for @socialOr.
  ///
  /// In en, this message translates to:
  /// **'or'**
  String get socialOr;

  /// No description provided for @socialGoogleFailed.
  ///
  /// In en, this message translates to:
  /// **'We couldn’t sign you in with Google. Try again.'**
  String get socialGoogleFailed;

  /// No description provided for @socialAppleFailed.
  ///
  /// In en, this message translates to:
  /// **'We couldn’t sign you in with Apple. Try again.'**
  String get socialAppleFailed;

  /// No description provided for @socialGoogleUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Sign in with Google is not available right now.'**
  String get socialGoogleUnavailable;

  /// No description provided for @socialAppleUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Sign in with Apple is not available right now.'**
  String get socialAppleUnavailable;

  /// No description provided for @socialAccountDisabled.
  ///
  /// In en, this message translates to:
  /// **'This account is disabled. Contact support if you think this is a mistake.'**
  String get socialAccountDisabled;

  /// No description provided for @accountNameStamp.
  ///
  /// In en, this message translates to:
  /// **'Almost there'**
  String get accountNameStamp;

  /// No description provided for @accountNameTitle.
  ///
  /// In en, this message translates to:
  /// **'What should we call you?'**
  String get accountNameTitle;

  /// No description provided for @accountNameBody.
  ///
  /// In en, this message translates to:
  /// **'Your account has no name yet. The people you send or carry with see it on your offers and deliveries.'**
  String get accountNameBody;

  /// No description provided for @accountNameLabel.
  ///
  /// In en, this message translates to:
  /// **'Your name'**
  String get accountNameLabel;

  /// No description provided for @chatSafetyTitle.
  ///
  /// In en, this message translates to:
  /// **'Safety'**
  String get chatSafetyTitle;

  /// No description provided for @chatSafetySubtitle.
  ///
  /// In en, this message translates to:
  /// **'To report a message, press and hold it.'**
  String get chatSafetySubtitle;

  /// No description provided for @chatBlockAction.
  ///
  /// In en, this message translates to:
  /// **'Block'**
  String get chatBlockAction;

  /// No description provided for @chatBlockActionDetail.
  ///
  /// In en, this message translates to:
  /// **'Stop messages and new deliveries between you.'**
  String get chatBlockActionDetail;

  /// No description provided for @chatUnblockAction.
  ///
  /// In en, this message translates to:
  /// **'Unblock'**
  String get chatUnblockAction;

  /// No description provided for @chatUnblockActionDetail.
  ///
  /// In en, this message translates to:
  /// **'You can message each other again.'**
  String get chatUnblockActionDetail;

  /// No description provided for @chatBlockConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Block this member?'**
  String get chatBlockConfirmTitle;

  /// No description provided for @chatBlockConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'Neither of you will be able to send messages here, and neither of you can start a new delivery with the other. A delivery that is already paid goes on as agreed. You can unblock them from Profile at any time.'**
  String get chatBlockConfirmBody;

  /// No description provided for @chatBlockDone.
  ///
  /// In en, this message translates to:
  /// **'You blocked this member.'**
  String get chatBlockDone;

  /// No description provided for @chatUnblockDone.
  ///
  /// In en, this message translates to:
  /// **'You unblocked this member.'**
  String get chatUnblockDone;

  /// No description provided for @chatBlockedByMeTitle.
  ///
  /// In en, this message translates to:
  /// **'You blocked this member'**
  String get chatBlockedByMeTitle;

  /// No description provided for @chatBlockedByMeBody.
  ///
  /// In en, this message translates to:
  /// **'Neither of you can send messages here. A delivery that is already paid goes on as agreed.'**
  String get chatBlockedByMeBody;

  /// No description provided for @chatBlockedTitle.
  ///
  /// In en, this message translates to:
  /// **'Messaging is off'**
  String get chatBlockedTitle;

  /// No description provided for @chatBlockedBody.
  ///
  /// In en, this message translates to:
  /// **'You can no longer send messages in this conversation. A delivery that is already paid goes on as agreed.'**
  String get chatBlockedBody;

  /// No description provided for @chatBlockedPill.
  ///
  /// In en, this message translates to:
  /// **'Blocked'**
  String get chatBlockedPill;

  /// No description provided for @chatReportTitle.
  ///
  /// In en, this message translates to:
  /// **'Report this message'**
  String get chatReportTitle;

  /// No description provided for @chatReportSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Wassla’s team reviews every report within a day. The sender is not told who reported it.'**
  String get chatReportSubtitle;

  /// No description provided for @chatReportReasonLabel.
  ///
  /// In en, this message translates to:
  /// **'What’s wrong with it?'**
  String get chatReportReasonLabel;

  /// No description provided for @chatReportReasonSpam.
  ///
  /// In en, this message translates to:
  /// **'Spam or advertising'**
  String get chatReportReasonSpam;

  /// No description provided for @chatReportReasonHarassment.
  ///
  /// In en, this message translates to:
  /// **'Harassment or threats'**
  String get chatReportReasonHarassment;

  /// No description provided for @chatReportReasonScam.
  ///
  /// In en, this message translates to:
  /// **'A scam, or a request to pay outside Wassla'**
  String get chatReportReasonScam;

  /// No description provided for @chatReportReasonInappropriate.
  ///
  /// In en, this message translates to:
  /// **'Offensive or inappropriate'**
  String get chatReportReasonInappropriate;

  /// No description provided for @chatReportReasonOther.
  ///
  /// In en, this message translates to:
  /// **'Something else'**
  String get chatReportReasonOther;

  /// No description provided for @chatReportChooseReason.
  ///
  /// In en, this message translates to:
  /// **'Choose a reason.'**
  String get chatReportChooseReason;

  /// No description provided for @chatReportNoteLabel.
  ///
  /// In en, this message translates to:
  /// **'Anything to add? (optional)'**
  String get chatReportNoteLabel;

  /// No description provided for @chatReportAlsoBlock.
  ///
  /// In en, this message translates to:
  /// **'Also block this member'**
  String get chatReportAlsoBlock;

  /// No description provided for @chatReportAlsoBlockDetail.
  ///
  /// In en, this message translates to:
  /// **'Neither of you can send messages here any more.'**
  String get chatReportAlsoBlockDetail;

  /// No description provided for @chatReportSend.
  ///
  /// In en, this message translates to:
  /// **'Send report'**
  String get chatReportSend;

  /// No description provided for @chatReportSent.
  ///
  /// In en, this message translates to:
  /// **'Thanks. Wassla’s team will review it.'**
  String get chatReportSent;

  /// No description provided for @chatMessageRemoved.
  ///
  /// In en, this message translates to:
  /// **'Removed by Wassla'**
  String get chatMessageRemoved;

  /// No description provided for @chatDeletedAccount.
  ///
  /// In en, this message translates to:
  /// **'Deleted account'**
  String get chatDeletedAccount;

  /// No description provided for @partyBlockedTitle.
  ///
  /// In en, this message translates to:
  /// **'Not possible with this member'**
  String get partyBlockedTitle;

  /// No description provided for @partyBlockedBody.
  ///
  /// In en, this message translates to:
  /// **'One of you blocked the other, so neither of you can start a delivery with the other. You can see the people you block in Profile.'**
  String get partyBlockedBody;

  /// No description provided for @blockedPeopleTitle.
  ///
  /// In en, this message translates to:
  /// **'Blocked people'**
  String get blockedPeopleTitle;

  /// No description provided for @blockedPeopleBody.
  ///
  /// In en, this message translates to:
  /// **'You and these people can’t message each other or start a new delivery together. Unblocking lets you do both again.'**
  String get blockedPeopleBody;

  /// No description provided for @blockedPeopleEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'You haven’t blocked anyone'**
  String get blockedPeopleEmptyTitle;

  /// No description provided for @blockedPeopleEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'When you block someone from a chat, they appear here.'**
  String get blockedPeopleEmptyBody;

  /// No description provided for @blockedPeopleSince.
  ///
  /// In en, this message translates to:
  /// **'Blocked on {date}'**
  String blockedPeopleSince(String date);

  /// No description provided for @profileDeleteAccount.
  ///
  /// In en, this message translates to:
  /// **'Delete account'**
  String get profileDeleteAccount;

  /// No description provided for @deleteAccountTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete your account'**
  String get deleteAccountTitle;

  /// No description provided for @deleteAccountIntro.
  ///
  /// In en, this message translates to:
  /// **'Deleting your account is permanent. You can’t sign in to it again, and we erase your name, email, phone number, sign-in methods, notifications, alerts and public profile.'**
  String get deleteAccountIntro;

  /// No description provided for @deleteAccountKeptTitle.
  ///
  /// In en, this message translates to:
  /// **'What we keep'**
  String get deleteAccountKeptTitle;

  /// No description provided for @deleteAccountKeptBody.
  ///
  /// In en, this message translates to:
  /// **'The records other people and the law rely on stay, without your contact details: past deliveries, payments, payouts, ID check decisions, reviews, disputes and chat messages.'**
  String get deleteAccountKeptBody;

  /// No description provided for @deleteAccountBlockedTitle.
  ///
  /// In en, this message translates to:
  /// **'Finish these first'**
  String get deleteAccountBlockedTitle;

  /// No description provided for @deleteAccountBlockedBody.
  ///
  /// In en, this message translates to:
  /// **'Your account can be deleted once nothing is still open.'**
  String get deleteAccountBlockedBody;

  /// No description provided for @deleteAccountBlockerDeliveries.
  ///
  /// In en, this message translates to:
  /// **'A delivery that hasn’t finished'**
  String get deleteAccountBlockerDeliveries;

  /// No description provided for @deleteAccountBlockerDisputes.
  ///
  /// In en, this message translates to:
  /// **'A dispute that is still open'**
  String get deleteAccountBlockerDisputes;

  /// No description provided for @deleteAccountBlockerPayouts.
  ///
  /// In en, this message translates to:
  /// **'A payout that hasn’t reached you yet'**
  String get deleteAccountBlockerPayouts;

  /// No description provided for @deleteAccountBlockerRefunds.
  ///
  /// In en, this message translates to:
  /// **'A refund that hasn’t reached you yet'**
  String get deleteAccountBlockerRefunds;

  /// No description provided for @deleteAccountBlockerRequests.
  ///
  /// In en, this message translates to:
  /// **'A parcel request that is still open. Cancel it from Deliveries.'**
  String get deleteAccountBlockerRequests;

  /// No description provided for @deleteAccountBlockerJourneys.
  ///
  /// In en, this message translates to:
  /// **'A trip that is published or under way. Cancel or finish it from Deliveries.'**
  String get deleteAccountBlockerJourneys;

  /// No description provided for @deleteAccountBlockerOther.
  ///
  /// In en, this message translates to:
  /// **'Something still open on your account'**
  String get deleteAccountBlockerOther;

  /// No description provided for @deleteAccountOpenDeliveries.
  ///
  /// In en, this message translates to:
  /// **'Open Deliveries'**
  String get deleteAccountOpenDeliveries;

  /// No description provided for @deleteAccountCheckAgain.
  ///
  /// In en, this message translates to:
  /// **'Check again'**
  String get deleteAccountCheckAgain;

  /// No description provided for @deleteAccountAppleNote.
  ///
  /// In en, this message translates to:
  /// **'You use Sign in with Apple. Apple asks you to confirm, then Wassla stops using your Apple ID.'**
  String get deleteAccountAppleNote;

  /// No description provided for @deleteAccountAppleElsewhereTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete it from an iPhone'**
  String get deleteAccountAppleElsewhereTitle;

  /// No description provided for @deleteAccountAppleElsewhereBody.
  ///
  /// In en, this message translates to:
  /// **'Your account uses Sign in with Apple, and only Apple can confirm its deletion. Open Wassla on an iPhone or iPad to delete it, or write to support.'**
  String get deleteAccountAppleElsewhereBody;

  /// No description provided for @deleteAccountPasswordLabel.
  ///
  /// In en, this message translates to:
  /// **'Your password'**
  String get deleteAccountPasswordLabel;

  /// No description provided for @deleteAccountPasswordHelp.
  ///
  /// In en, this message translates to:
  /// **'To confirm it’s you.'**
  String get deleteAccountPasswordHelp;

  /// No description provided for @deleteAccountPasswordMissing.
  ///
  /// In en, this message translates to:
  /// **'Enter your password.'**
  String get deleteAccountPasswordMissing;

  /// No description provided for @deleteAccountPasswordIncorrect.
  ///
  /// In en, this message translates to:
  /// **'That password isn’t right.'**
  String get deleteAccountPasswordIncorrect;

  /// No description provided for @deleteAccountAction.
  ///
  /// In en, this message translates to:
  /// **'Delete my account'**
  String get deleteAccountAction;

  /// No description provided for @deleteAccountConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete your account?'**
  String get deleteAccountConfirmTitle;

  /// No description provided for @deleteAccountConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'This can’t be undone. You will be signed out on every device.'**
  String get deleteAccountConfirmBody;

  /// No description provided for @deleteAccountConfirm.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get deleteAccountConfirm;

  /// No description provided for @deleteAccountChanged.
  ///
  /// In en, this message translates to:
  /// **'Something changed on your account. Check the list again.'**
  String get deleteAccountChanged;

  /// No description provided for @deleteAccountAppleRefused.
  ///
  /// In en, this message translates to:
  /// **'Apple didn’t confirm. Nothing was deleted. Try again.'**
  String get deleteAccountAppleRefused;

  /// No description provided for @deleteAccountAppleUnavailable.
  ///
  /// In en, this message translates to:
  /// **'We couldn’t reach Apple. Nothing was deleted. Try again in a few minutes.'**
  String get deleteAccountAppleUnavailable;

  /// No description provided for @deleteAccountStaff.
  ///
  /// In en, this message translates to:
  /// **'A staff account is closed by a Super Admin, not from the app.'**
  String get deleteAccountStaff;

  /// No description provided for @deleteAccountDone.
  ///
  /// In en, this message translates to:
  /// **'Your account is deleted.'**
  String get deleteAccountDone;

  /// No description provided for @notificationFlightTicketApproved.
  ///
  /// In en, this message translates to:
  /// **'Flight ticket approved'**
  String get notificationFlightTicketApproved;

  /// No description provided for @notificationFlightTicketRejected.
  ///
  /// In en, this message translates to:
  /// **'Flight ticket needs attention'**
  String get notificationFlightTicketRejected;

  /// No description provided for @notificationFlightTicketResubmit.
  ///
  /// In en, this message translates to:
  /// **'We need a new flight ticket'**
  String get notificationFlightTicketResubmit;

  /// No description provided for @notificationFerryTicketApproved.
  ///
  /// In en, this message translates to:
  /// **'Ferry ticket approved'**
  String get notificationFerryTicketApproved;

  /// No description provided for @notificationFerryTicketRejected.
  ///
  /// In en, this message translates to:
  /// **'Ferry ticket needs attention'**
  String get notificationFerryTicketRejected;

  /// No description provided for @notificationFerryTicketResubmit.
  ///
  /// In en, this message translates to:
  /// **'We need a new ferry ticket'**
  String get notificationFerryTicketResubmit;
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
