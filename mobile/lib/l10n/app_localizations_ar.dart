// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Arabic (`ar`).
class LAr extends L {
  LAr([String locale = 'ar']) : super(locale);

  @override
  String get payoutLegalCountryTitle => 'بلد حساب تحويل الأرباح';

  @override
  String get payoutLegalCountryLabel => 'البلد';

  @override
  String get payoutLegalCountryBody =>
      'اختر البلد المسجّل لحسابك لدى Stripe للموافقة على إعداد تحويل الأرباح. إذا لم تجد بلدك، استخدم تحويل الأرباح بالدينار الجزائري.';

  @override
  String get appName => 'Wassla';

  @override
  String get actionContinue => 'متابعة';

  @override
  String get actionCancel => 'إلغاء';

  @override
  String get actionSave => 'حفظ';

  @override
  String get actionRetry => 'إعادة المحاولة';

  @override
  String get actionDone => 'تم';

  @override
  String get actionBack => 'رجوع';

  @override
  String get actionNext => 'التالي';

  @override
  String get actionConfirm => 'تأكيد';

  @override
  String get actionEdit => 'تعديل';

  @override
  String get actionCopy => 'نسخ';

  @override
  String get actionCopied => 'تم النسخ';

  @override
  String get actionRefresh => 'تحديث';

  @override
  String get actionSeeAll => 'عرض الكل';

  @override
  String get actionGoBack => 'العودة';

  @override
  String get actionNotNow => 'ليس الآن';

  @override
  String get actionOpen => 'فتح';

  @override
  String get actionAdd => 'إضافة';

  @override
  String get actionSelect => 'اختيار';

  @override
  String get actionClear => 'مسح';

  @override
  String get actionContactSupport => 'التواصل مع الدعم';

  @override
  String get navHome => 'الرئيسية';

  @override
  String get navDeliveries => 'التوصيلات';

  @override
  String get navChat => 'المحادثة';

  @override
  String get navProfile => 'الحساب';

  @override
  String get navNotifications => 'الإشعارات';

  @override
  String navNotificationsWithCount(int count) {
    return 'الإشعارات، $count غير مقروءة';
  }

  @override
  String get roleSender => 'الإرسال';

  @override
  String get roleTraveler => 'السفر';

  @override
  String get roleSwitchLabel => 'تبديل الدور';

  @override
  String get authSignIn => 'تسجيل الدخول';

  @override
  String get authSignUp => 'إنشاء حساب';

  @override
  String get authSignOut => 'تسجيل الخروج';

  @override
  String get authEmail => 'البريد الإلكتروني';

  @override
  String get authPassword => 'كلمة المرور';

  @override
  String get authFullName => 'الاسم الكامل';

  @override
  String get authForgotPassword => 'نسيت كلمة المرور؟';

  @override
  String get authNoAccount => 'جديد على Wassla؟';

  @override
  String get authHaveAccount => 'لديك حساب بالفعل؟';

  @override
  String get authVerifyEmailTitle => 'أكّد بريدك الإلكتروني';

  @override
  String authVerifyEmailBody(String email) {
    return 'أرسلنا رابطًا إلى $email. أكّده للحفاظ على أمان حسابك.';
  }

  @override
  String get authSignOutConfirmTitle => 'تسجيل الخروج؟';

  @override
  String get authSignOutConfirmBody =>
      'ستحتاج إلى تسجيل الدخول مرة أخرى لرؤية توصيلاتك.';

  @override
  String get validationRequired => 'هذا الحقل مطلوب';

  @override
  String get validationCodeSixDigits => 'يجب أن يتكون الرمز من 6 أرقام';

  @override
  String get validationCcpNumberDigits =>
      'يجب أن يحتوي رقم حساب CCP على رقم واحد إلى 20 رقمًا';

  @override
  String get validationCcpKeyDigits => 'يجب أن يتكون مفتاح CCP من رقمين بالضبط';

  @override
  String get validationRipDigits => 'يجب أن يتكون RIP من 20 رقمًا بالضبط';

  @override
  String get validationEmailInvalid => 'أدخل عنوان بريد إلكتروني صالحًا';

  @override
  String get validationPasswordTooShort => 'استخدم 8 أحرف على الأقل';

  @override
  String get validationNumberInvalid => 'أدخل رقمًا';

  @override
  String get validationMoneyPrecision => 'استخدم منزلتين عشريتين كحد أقصى';

  @override
  String get validationMustBePositive => 'أدخل رقمًا أكبر من صفر';

  @override
  String validationTooLong(int max) {
    return '$max حرفًا على الأكثر';
  }

  @override
  String get validationSelectOne => 'اختر واحدًا';

  @override
  String get validationDateInPast => 'اختر تاريخًا في المستقبل';

  @override
  String get validationDeadlineBeforeReady =>
      'يجب أن يكون الموعد النهائي بعد جاهزية الطرد';

  @override
  String get stateOfflineTitle => 'أنت غير متصل بالإنترنت';

  @override
  String get stateOfflineBody => 'تحقق من اتصالك. سنُحمّل هذا فور عودتك.';

  @override
  String get stateTimeoutTitle => 'استغرق هذا وقتًا طويلاً';

  @override
  String get stateTimeoutBody =>
      'لم يستجب الخادم في الوقت المحدد. لم يُفقد أي شيء — أعد المحاولة.';

  @override
  String get stateServerErrorTitle => 'حدث خطأ من جانبنا';

  @override
  String get stateServerErrorBody => 'هذا ليس خطأك. أعد المحاولة بعد قليل.';

  @override
  String get stateNotFoundTitle => 'غير موجود';

  @override
  String get stateNotFoundBody =>
      'ربما تمت إزالة هذا، أو أنه لم يكن مخصصًا لك أصلاً.';

  @override
  String get stateForbiddenTitle => 'لا يمكنك فعل ذلك هنا';

  @override
  String get stateForbiddenBody => 'لا يملك حسابك صلاحية الوصول إلى هذا.';

  @override
  String get stateSessionExpiredTitle => 'يُرجى تسجيل الدخول مرة أخرى';

  @override
  String get stateSessionExpiredBody =>
      'انتهت جلستك. سجّل الدخول لمتابعة ما كنت تفعله.';

  @override
  String get stateRateLimitedTitle => 'عدد كبير جدًا من المحاولات';

  @override
  String get stateRateLimitedBody => 'انتظر قليلاً قبل إعادة المحاولة.';

  @override
  String get stateUnexpectedTitle => 'حدث أمر غير متوقع';

  @override
  String get stateUnexpectedBody =>
      'لم نتمكن من إتمام ذلك. أعد المحاولة، وأخبرنا إذا استمر حدوث هذا.';

  @override
  String get stateAppOutdatedTitle => 'هذا الإصدار قديم';

  @override
  String get stateAppOutdatedBody =>
      'حدّث Wassla للمتابعة. لم يعد هذا الجزء من التطبيق يعمل مع هذا الإصدار.';

  @override
  String get staleTitle => 'تغيّر هذا';

  @override
  String get staleRefreshAction => 'تحديث';

  @override
  String get staleRequestNotOpen => 'لم يعد هذا الطلب مفتوحًا.';

  @override
  String get staleRequestAlreadyMatched =>
      'تمت مطابقة هذا الطلب بالفعل مع مسافر.';

  @override
  String get staleJourneyNotActive => 'لم تعد هذه الرحلة نشطة.';

  @override
  String get staleOfferNotPending => 'تمت الإجابة على هذا العرض بالفعل.';

  @override
  String get staleMatchNotPending => 'لم تعد هذه المطابقة بانتظار أحد.';

  @override
  String get staleCapacityExceeded => 'لم تعد هناك مساحة كافية في هذه الرحلة.';

  @override
  String get staleRewardBelowMinimum => 'تغيّر الحد الأدنى للمكافأة.';

  @override
  String get staleRouteChanged => 'تغيّرت تفاصيل المسار. لقد حدّثنا السعر.';

  @override
  String get staleKycInvalid =>
      'يحتاج التحقق من هويتك إلى الانتباه قبل أن تتمكن من فعل هذا.';

  @override
  String get staleTicketInvalid =>
      'تحتاج تذكرة في هذه الرحلة إلى الانتباه قبل أن تتمكن من المطابقة.';

  @override
  String get staleReservationExpired => 'انتهت صلاحية المساحة المحجوزة لك.';

  @override
  String get staleDealClosed => 'أُغلقت هذه الصفقة.';

  @override
  String get stalePayoutProfileInvalid =>
      'تغيّرت بيانات تحويل أرباحك أثناء وجودك في هذه الصفحة. اسحب إلى الأسفل للتحديث، ثم أعد المحاولة.';

  @override
  String get stalePayoutCountryUnsupported =>
      'تحويل الأرباح باليورو غير متاح في هذا البلد بعد. اختر بلدًا آخر أو استخدم التحويل بالدينار الجزائري.';

  @override
  String get staleStripeConnectUnavailable =>
      'إعداد تحويل الأرباح باليورو غير متاح مؤقتًا. بياناتك محفوظة. حاول مجددًا بعد قليل.';

  @override
  String get staleStripeConnectProviderError =>
      'تعذّر على Stripe إتمام الطلب. لم يتم تغيير أي شيء؛ حاول مجددًا بعد قليل.';

  @override
  String get stalePayoutSetupInvalid =>
      'تعذّر إعداد تحويل الأرباح. تحقّق من البيانات وأعد المحاولة.';

  @override
  String get stalePayoutEvidenceUnavailable =>
      'المستند المُرسل لم يعد متاحًا. يرجى رفع الشيك المسطّر من جديد.';

  @override
  String get staleOfferExpired => 'لم يعد هذا العرض متاحًا.';

  @override
  String get moneyYouPay => 'المبلغ الذي تدفعه';

  @override
  String get moneyYouReceive => 'تحصل على';

  @override
  String get moneyYourEarnings => 'أرباحك';

  @override
  String get moneyTotalYouReceive => 'إجمالي ما تحصل عليه';

  @override
  String get moneyTravelerReceives => 'يحصل المسافر على';

  @override
  String get moneyPlatformFee => 'رسوم Wassla';

  @override
  String get moneyMinimumReward => 'الحد الأدنى للمكافأة';

  @override
  String get moneyTotal => 'الإجمالي';

  @override
  String get moneyDepositPaid => 'العربون مدفوع بالفعل';

  @override
  String get moneyRemainingToPay => 'المتبقي للدفع';

  @override
  String get moneyRefundToYou => 'المبلغ المسترد لك';

  @override
  String get moneyTravelerCompensation => 'تعويض المسافر';

  @override
  String get moneyBreakdownTitle => 'كيف يُحسب هذا المبلغ';

  @override
  String get moneyRewardNotReduced =>
      'يحصل المسافر على هذا المبلغ كاملاً. تُضاف رسوم Wassla فوقه، ولا تُخصم منه.';

  @override
  String get moneyDepositNotExtra =>
      'يُخصم هذا من دفعتك النهائية. إنه ليس رسمًا إضافيًا.';

  @override
  String get moneyAmountCharged => 'سيتم خصم';

  @override
  String moneyExchangeRate(String rate) {
    return 'سعر الصرف: 1€ = $rate دج';
  }

  @override
  String get moneyChargedInDinars =>
      'تفرض Chargily الرسوم بالدينار الجزائري. يبقى سعر التوصيل باليورو.';

  @override
  String get homeSenderGreeting => 'أرسل شيئًا إلى الوطن';

  @override
  String get homeTravelerGreeting => 'اربح من رحلة تقوم بها أصلاً';

  @override
  String get homeCreateRequest => 'أرسل طردًا';

  @override
  String get homeCreateJourney => 'أضف رحلة';

  @override
  String get homeNeedsYourAction => 'يحتاج انتباهك';

  @override
  String get homeInProgress => 'قيد التنفيذ';

  @override
  String get homeNothingNeedsYou => 'لا شيء يحتاج انتباهك الآن';

  @override
  String get homeEmptySenderTitle => 'لا شيء في الطريق بعد';

  @override
  String get homeEmptySenderBody =>
      'انشر ما تريد إرساله وسيراه المسافرون المتجهون إلى تلك الوجهة.';

  @override
  String get homeEmptyTravelerTitle => 'لا توجد رحلات بعد';

  @override
  String get homeEmptyTravelerBody =>
      'أضف الرحلة التي تقوم بها وسنعرض عليك الطرود الموجودة على مسارك.';

  @override
  String get deliveriesTitle => 'التوصيلات';

  @override
  String get dealUnavailableTitle => 'الصفقة غير متاحة';

  @override
  String get dealUnavailableBody =>
      'هذه الصفقة غير متاحة لهذا الحساب. ربما تغيّرت أو انتهت صلاحية الرابط.';

  @override
  String get deliveriesFilterActive => 'نشطة';

  @override
  String get deliveriesFilterAwaitingYou => 'يحتاج انتباهك';

  @override
  String get deliveriesFilterHistory => 'السجل';

  @override
  String get deliveriesSenderSection => 'الإرسال';

  @override
  String get deliveriesJourneysSection => 'رحلاتي';

  @override
  String get deliveriesEmptyActiveTitle => 'لا شيء نشط';

  @override
  String get deliveriesEmptyActiveBody =>
      'ستظهر هنا التوصيلات التي ترسلها أو تحملها.';

  @override
  String get deliveriesEmptyHistoryTitle => 'لا يوجد سجل بعد';

  @override
  String get deliveriesEmptyHistoryBody =>
      'تبقى هنا التوصيلات المكتملة والملغاة.';

  @override
  String get deliveriesEmptyAwaitingTitle => 'أنت على اطلاع بكل شيء';

  @override
  String get deliveriesEmptyAwaitingBody => 'لا شيء بانتظارك.';

  @override
  String get requestStatusAwaitingDeposit => 'العربون مطلوب';

  @override
  String get requestStatusOpen => 'جارٍ البحث عن مسافر';

  @override
  String get requestStatusMatched => 'تمت المطابقة';

  @override
  String get requestStatusInTransit => 'في الطريق';

  @override
  String get requestStatusDelivered => 'تم التوصيل';

  @override
  String get requestStatusCompleted => 'مكتمل';

  @override
  String get requestStatusCancelled => 'ملغى';

  @override
  String get requestStatusExpired => 'منتهي الصلاحية';

  @override
  String get dealStatusOfferAccepted => 'تم قبول العرض';

  @override
  String get dealStatusPaymentRequired => 'الدفع مطلوب';

  @override
  String get dealStatusFunded => 'مدفوع ومحمي';

  @override
  String get dealStatusPickupReady => 'جاهز للاستلام';

  @override
  String get dealStatusPickedUp => 'تم الاستلام';

  @override
  String get dealStatusInTransit => 'في الطريق';

  @override
  String get dealStatusDeliveryReady => 'جاهز للتوصيل';

  @override
  String get dealStatusDeliveryConfirmed => 'تم التوصيل';

  @override
  String get dealStatusProtection => 'الدفع محمي';

  @override
  String get dealStatusCompleted => 'مكتمل';

  @override
  String get dealStatusCancelled => 'ملغى';

  @override
  String get dealStatusDisputed => 'قيد النزاع';

  @override
  String get dealStatusRefunded => 'تم الاسترداد';

  @override
  String get dealStatusPartiallyRefunded => 'استرداد جزئي';

  @override
  String get dealStatusPaymentFailed => 'فشل الدفع';

  @override
  String get dealStatusExpired => 'منتهي الصلاحية';

  @override
  String get requestCreateTitle => 'أرسل طردًا';

  @override
  String get requestStepRoute => 'المسار';

  @override
  String get requestStepParcel => 'الطرد';

  @override
  String get requestStepTiming => 'التوقيت';

  @override
  String get requestStepReview => 'المراجعة';

  @override
  String get requestPickupLocation => 'الاستلام من';

  @override
  String get requestDeliveryLocation => 'التوصيل إلى';

  @override
  String get requestPickupHint => 'المكان الذي يستلم منه المسافر الطرد';

  @override
  String get requestDeliveryHint =>
      'المكان الذي يُسلَّم فيه الطرد إلى المستلِم';

  @override
  String get requestReadyFrom => 'جاهز ابتداءً من';

  @override
  String get requestDeadline => 'يجب أن يصل قبل';

  @override
  String get requestTitle => 'ماذا ترسل؟';

  @override
  String get requestTitleHint => 'وثائق، أدوية، ملابس…';

  @override
  String get requestDescription => 'الوصف';

  @override
  String get requestDescriptionHint =>
      'صِفه بدقة. هذا ما يوافق المسافر على حمله.';

  @override
  String get requestCategory => 'الفئة';

  @override
  String get requestWeight => 'الوزن';

  @override
  String get requestWeightUnit => 'كغ';

  @override
  String get requestDimensions => 'الحجم';

  @override
  String get requestLength => 'الطول';

  @override
  String get requestWidth => 'العرض';

  @override
  String get requestHeight => 'الارتفاع';

  @override
  String get requestDimensionUnit => 'سم';

  @override
  String get requestDeclaredValue => 'القيمة المصرح بها';

  @override
  String get requestDeclaredValueHelp =>
      'التكلفة التي يتطلبها استبداله. تُستخدم في حال حدوث خطأ ما.';

  @override
  String get requestPhotos => 'الصور';

  @override
  String get requestHandlingNotes => 'ملاحظات التعامل';

  @override
  String get requestHandlingNotesHint => 'أي شيء يجب أن يعرفه المسافر';

  @override
  String get requestFragile => 'قابل للكسر';

  @override
  String get requestAcknowledgementsTitle => 'قبل نشر هذا';

  @override
  String get requestAckDescriptionAccurate => 'وصفي لهذا الطرد دقيق';

  @override
  String get requestAckItemLegal => 'هذا الغرض قانوني للإرسال والاستلام';

  @override
  String get requestAckNoProhibited => 'لا يحتوي على أي سلع محظورة';

  @override
  String get requestAckValueAccurate => 'القيمة المصرح بها دقيقة';

  @override
  String get requestAckCustoms =>
      'أفهم أنني مسؤول عن أي قواعد جمركية أو قواعد استيراد سارية';

  @override
  String get requestProhibitedItemsLink => 'اطّلع على ما لا يمكن إرساله';

  @override
  String get requestSizeExplainer =>
      'الحجم لا يقل أهمية عن الوزن. نحتسب الرسوم على أساس الأكبر منهما.';

  @override
  String get requestCreated => 'تم النشر';

  @override
  String get depositTitle => 'انشر طلبك';

  @override
  String get depositExplainer =>
      'ادفع العربون لنشر طلبك. يُخصم كامل مبلغ العربون من الدفعة النهائية للتوصيل.';

  @override
  String get depositAmount => 'العربون';

  @override
  String get depositCreditedNote =>
      'يُخصم من دفعتك النهائية عند قبول مسافر للعرض.';

  @override
  String get depositRefundNote =>
      'إذا لم يقبله أحد، أو ألغيت الطلب قبل قبول أي عرض، فسيُرد إليك بالكامل.';

  @override
  String get depositGuidanceTitle => 'تفاصيل العربون';

  @override
  String get depositSuggestedTotal => 'الإجمالي المقترح من Wassla';

  @override
  String get depositWholeAmount => 'إجمالي ما تدفعه لهذا التوصيل';

  @override
  String get pricingUpdating => 'جارٍ تحديث السعر';

  @override
  String get depositRecommended => 'العربون الموصى به';

  @override
  String get depositMinimumAllowed => 'الحد الأدنى للعربون';

  @override
  String get depositGuidanceNote =>
      'تحسب Wassla العربون من الإجمالي المقترح وتطبق الحدين الأدنى والأقصى الحاليين. يُحتسب هذا المبلغ من الدفعة النهائية وليس رسماً إضافياً.';

  @override
  String get depositPayAction => 'ادفع العربون وانشر';

  @override
  String get journeyTitle => 'الرحلة';

  @override
  String get journeyCreateTitle => 'أضف رحلة';

  @override
  String get journeyFrom => 'من';

  @override
  String get journeyTo => 'إلى';

  @override
  String get journeyLegs => 'المراحل';

  @override
  String get journeyModeFlight => 'طيران';

  @override
  String get journeyModeDrive => 'قيادة';

  @override
  String get journeyDeparts => 'المغادرة';

  @override
  String get journeyArrives => 'الوصول';

  @override
  String get journeyCapacity => 'المساحة التي يمكنك حملها';

  @override
  String get journeyFlightNumber => 'رقم الرحلة الجوية';

  @override
  String get journeyFlightNumberHint => 'مثال: AH1006';

  @override
  String get journeyPublish => 'نشر الرحلة';

  @override
  String get journeyCancel => 'إلغاء الرحلة';

  @override
  String get journeyStatusDraft => 'مسودة';

  @override
  String get journeyStatusPendingVerification => 'قيد التحقق';

  @override
  String get journeyStatusActive => 'منشورة';

  @override
  String get journeyStatusInProgress => 'جارية';

  @override
  String get journeyStatusCompleted => 'مكتملة';

  @override
  String get journeyStatusCancelled => 'ملغاة';

  @override
  String get journeyStatusExpired => 'منتهية الصلاحية';

  @override
  String get journeyEmptyLegsTitle => 'أضف مرحلتك الأولى';

  @override
  String get journeyEmptyLegsBody =>
      'تتكون الرحلة من مراحل. من باريس إلى الجزائر العاصمة بالطائرة، ثم من الجزائر العاصمة إلى جيجل بالطريق البري.';

  @override
  String get journeyRouteShape => 'مسارك';

  @override
  String get journeyModeLabel => 'طريقة سفرك';

  @override
  String get journeyChooseDateTime => 'اختر التاريخ والوقت';

  @override
  String get journeyArriveHelp =>
      'مطلوب لمطابقتك مع المُرسِلين، إذ يُقارَن موعدهم النهائي بهذا الوقت.';

  @override
  String get journeyMaxLegsReached =>
      'يمكن أن تحتوي الرحلة على 20 مرحلة كحد أقصى.';

  @override
  String get journeyCapacityInvalid =>
      'أدخل قيمة بين 0.01 و200 كغ، بدقة رقمين عشريين.';

  @override
  String get journeyLegDepartRequired => 'حدّد وقت مغادرة هذه المرحلة.';

  @override
  String get journeyLegDepartNotAfterPrevious =>
      'يجب أن تنطلق هذه المرحلة بعد المرحلة التي تسبقها.';

  @override
  String get journeyLegDepartBeforePreviousArrival =>
      'تنطلق هذه المرحلة قبل وصول المرحلة السابقة.';

  @override
  String get journeyLegArriveRequired => 'أضف وقت وصول هذه المرحلة.';

  @override
  String get journeyLegArriveBeforeDepart => 'يجب أن يكون الوصول بعد المغادرة.';

  @override
  String get journeyNotesLabel => 'أي شيء يجب أن يعرفه المُرسِلون';

  @override
  String get journeyNotesHint => 'لا سوائل، طرود صغيرة فقط، اللقاء قرب المطار…';

  @override
  String get journeySaveDraft => 'حفظ الرحلة';

  @override
  String get journeyCreatedDraft =>
      'تم الحفظ كمسودة. أضف إثبات الرحلة الجوية، ثم انشرها.';

  @override
  String get journeyDraftNextSteps =>
      'لا شيء مرئي للمُرسِلين بعد. انشرها عند الموافقة على إثبات رحلتك الجوية.';

  @override
  String get journeyLegsNeedProofTitle => 'تذاكر تحتاج إلى التحقق';

  @override
  String get journeyPublishBlockedProof =>
      'تحتاج كل مرحلة بالطائرة أو الباخرة إلى تذكرة معتمدة قبل النشر.';

  @override
  String get journeyPublished =>
      'رحلتك منشورة الآن. يمكن للمُرسِلين المتجهين إلى وجهتك رؤيتها.';

  @override
  String get journeyErrorNotPublishable =>
      'لا يمكن نشر هذه الرحلة من حالتها الحالية.';

  @override
  String get journeyErrorNoLegs =>
      'لا تحتوي هذه الرحلة على أي مراحل، فلا يوجد ما يمكن نشره.';

  @override
  String get journeyErrorLegPositions =>
      'تم ترقيم المراحل بشكل خاطئ. ألغِ هذه الرحلة وأنشئها من جديد.';

  @override
  String get journeyErrorEndpointsMismatch =>
      'لا تتطابق المرحلتان الأولى والأخيرة مع نقطتي انطلاق الرحلة ووجهتها.';

  @override
  String get journeyErrorLegEndpoints =>
      'تبدأ إحدى المراحل أو تنتهي في مكان لا يمر به المسار.';

  @override
  String get journeyErrorLegTime => 'تصل إحدى المراحل قبل أن تنطلق.';

  @override
  String get journeyErrorLegArrivalRequired =>
      'يجب أن يكون لكل مرحلة وقت وصول قبل النشر. بدونه لا يمكن مطابقة أي مُرسِل مع هذه الرحلة.';

  @override
  String get journeyErrorLegsDisconnected =>
      'لا تتصل المراحل ببعضها لتشكّل مسارًا واحدًا.';

  @override
  String get journeyErrorLegTimeOrder => 'المراحل ليست مرتبة زمنيًا.';

  @override
  String get journeyErrorNotOwned => 'هذه الرحلة تخص شخصًا آخر.';

  @override
  String get journeyCancelConfirmTitle => 'إلغاء هذه الرحلة؟';

  @override
  String get journeyCancelConfirmBody =>
      'لن يراها المُرسِلون بعد الآن، وستُحرَّر أي مساحة كانوا يحجزونها. لا يمكن التراجع عن هذا.';

  @override
  String get journeyCancelled => 'تم إلغاء الرحلة.';

  @override
  String journeyReleasedAllocations(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'تم تحرير $count مساحة محجوزة',
      many: 'تم تحرير $count مساحة محجوزة',
      few: 'تم تحرير $count مساحات محجوزة',
      two: 'تم تحرير مساحتين محجوزتين',
      one: 'تم تحرير مساحة محجوزة واحدة',
      zero: 'لم تكن هناك أي مساحة محجوزة',
    );
    return '$_temp0';
  }

  @override
  String get journeyErrorNotCancellable =>
      'لا يمكن إلغاء هذه الرحلة من حالتها الحالية.';

  @override
  String get journeyErrorHasFundedDeal =>
      'هناك صفقة مدفوعة تعتمد على هذه الرحلة. عالج تلك الصفقة أولًا.';

  @override
  String get journeyMatchesInfoTitle => 'المُرسِلون يبادرون أولاً';

  @override
  String get journeyMatchesInfoBody =>
      'لا يمكنك تقديم عرض على هؤلاء. إذا اختارك أحد هؤلاء المُرسِلين، سيصلك عرضه في التوصيلات.';

  @override
  String get routeStopsTitle => 'محطاتك';

  @override
  String get routeStopsHelp =>
      'أضف نقطة الانطلاق والوصول وأي محطة في الطريق. نحن نستنتج المراحل بينها.';

  @override
  String get routeStopLabel => 'محطة';

  @override
  String get routeAddStopHere => 'أضف محطة هنا';

  @override
  String get routeAddStopTitle => 'أين تتوقف؟';

  @override
  String get routeChangeStopTitle => 'تغيير هذه المحطة';

  @override
  String get routeRemoveStop => 'حذف هذه المحطة';

  @override
  String get routeMoveStopEarlier => 'نقل المحطة إلى الأمام';

  @override
  String get routeMoveStopLater => 'نقل المحطة إلى الخلف';

  @override
  String get routeStopSameAsPrevious =>
      'هذه نفس مدينة المحطة السابقة. اختر مدينة أخرى أو احذف إحداهما.';

  @override
  String routeSegmentBetween(String from, String to) {
    return '$from ← $to';
  }

  @override
  String get routeFlightOnlyExplainer =>
      'لا يوجد طريق بري بين هذين البلدين، لذا يجب أن يكون هذا الجزء رحلة جوية.';

  @override
  String get routeFlightAirportsRequired =>
      'الرحلة الجوية تبدأ وتنتهي في مطار. اختر المطار لكل طرف من هذا الجزء.';

  @override
  String get routeAirportNeededTitle => 'أي مطار؟';

  @override
  String routeAirportNeededBody(String stop) {
    return 'أنت تسافر جواً من $stop، لذا نحتاج إلى المطار. تبقى المحطة $stop، نحتاج فقط معرفة كيف تغادرها.';
  }

  @override
  String get routeChooseAirport => 'اختر المطار';

  @override
  String get routeChooseAirportTitle => 'أي مطار؟';

  @override
  String get routeChangeAirport => 'تغيير';

  @override
  String routeAirportChosen(String airport) {
    return 'عبر $airport';
  }

  @override
  String get routeErrorModeUnavailable =>
      'لا يمكن قطع هذا الجزء بالسيارة. لا يوجد طريق بري بين هذين البلدين، لذا يجب أن يكون رحلة جوية.';

  @override
  String get journeyEditTitle => 'تعديل الرحلة';

  @override
  String get journeyEditAction => 'تعديل';

  @override
  String get journeySaveChanges => 'حفظ التغييرات';

  @override
  String get journeyEditSaved => 'تم تحديث الرحلة.';

  @override
  String journeyEditSavedProofReset(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'تم تحديث الرحلة. أُعيد $count إثبات إلى المراجعة.',
      many: 'تم تحديث الرحلة. أُعيد $count إثباتاً إلى المراجعة.',
      few: 'تم تحديث الرحلة. أُعيدت $count إثباتات إلى المراجعة.',
      two: 'تم تحديث الرحلة. أُعيد إثباتا رحلتين إلى المراجعة.',
      one:
          'تم تحديث الرحلة. أُعيد إثبات رحلة واحدة إلى المراجعة لأن الرحلة تغيّرت.',
      zero: 'تم تحديث الرحلة.',
    );
    return '$_temp0';
  }

  @override
  String get journeyEditBlockedTitle => 'لا يمكن تعديل هذه الرحلة';

  @override
  String get journeyEditBlockedStatus =>
      'لا يمكن تعديل هذه الرحلة لأنها منشورة بالفعل. ألغِها وأنشئ رحلة جديدة إذا تغيّر المسار.';

  @override
  String get journeyEditBlockedDependent =>
      'لا يمكن تعديل هذه الرحلة لأن مُرسِلاً يعتمد بالفعل على هذا المسار.';

  @override
  String get journeyEditStaleRoute =>
      'تغيّر هذا المسار أثناء تعديله. أعد فتحه وحاول مرة أخرى.';

  @override
  String get journeyEditProofNotice =>
      'تغيير أماكن أو رقم أو مواعيد مرحلة بالطائرة أو الباخرة يعني أن تذكرتها لم تعد تثبت تلك الرحلة، لذلك سنراجعها من جديد.';

  @override
  String get journeyEditProofWarningTitle => 'ستُراجَع تذكرتك من جديد';

  @override
  String get journeyEditProofWarningBody =>
      'غيّرت مرحلة لها تذكرة بالفعل. لم تعد التذكرة تثبت هذه الرحلة، فتعود للمراجعة ولا يمكن نشر الرحلة قبل اعتمادها من جديد.';

  @override
  String get proofErrorStorageUnavailable =>
      'لم نتمكن من حفظ ملفك في الوقت الحالي.';

  @override
  String get proofRetryTitle => 'لم يكتمل الرفع';

  @override
  String get proofRetryFileKept => 'لا تزال صورتك محددة.';

  @override
  String get proofRetry => 'أعد المحاولة';

  @override
  String get proofTitle => 'إثبات التذكرة';

  @override
  String get proofExplainerFlight =>
      'ارفع بطاقة الصعود إلى الطائرة أو تأكيد الحجز. نتحقق منها قبل أن تتمكن رحلتك من مطابقة الطرود.';

  @override
  String get proofDriveNotRequired => 'لا تحتاج مراحل القيادة إلى أي إثبات.';

  @override
  String get proofUpload => 'رفع الإثبات';

  @override
  String get proofStatusMissing => 'لم يُرفع';

  @override
  String get proofStatusPending => 'قيد المراجعة';

  @override
  String get proofStatusApproved => 'معتمد';

  @override
  String get proofStatusRejected => 'غير مقبول';

  @override
  String proofRejectedReason(String reason) {
    return 'السبب: $reason';
  }

  @override
  String get proofKindLabel => 'ماذا ترفع؟';

  @override
  String get proofKindTicket => 'تذكرة';

  @override
  String get proofKindBoardingPass => 'بطاقة صعود الطائرة';

  @override
  String get proofKindBookingConfirmation => 'تأكيد الحجز';

  @override
  String get proofFormatRule =>
      'JPEG أو PNG أو WebP، بحجم أقصى 10 ميغابايت. نتحقق من الملف نفسه، لذا لن تفيد إعادة تسميته.';

  @override
  String get proofFileTooLarge =>
      'حجم هذه الصورة يتجاوز 10 ميغابايت. اختر صورة أصغر.';

  @override
  String get proofFileTypeNotAllowed => 'لا تُقبل إلا صور JPEG وPNG وWebP.';

  @override
  String get proofChooseImage => 'اختر صورة';

  @override
  String get proofTakePhoto => 'التقط صورة';

  @override
  String get proofSelectedFile => 'جاهز للرفع';

  @override
  String get proofUploading => 'جارٍ رفع إثباتك…';

  @override
  String get proofUploaded => 'تم استلام الإثبات. سنراجعه قريبًا.';

  @override
  String get proofExistingTitle => 'ما أرسلته سابقًا';

  @override
  String get proofErrorUploadClosed =>
      'تجاوزت هذه الرحلة المرحلة التي يمكن فيها إضافة إثبات.';

  @override
  String proofLegLabel(int position, String from, String to) {
    return 'المرحلة $position: من $from إلى $to';
  }

  @override
  String get kycTitle => 'التحقق من الهوية';

  @override
  String get kycWhyTitle => 'لماذا نطلب هذا';

  @override
  String get kycWhyBody =>
      'يسلّم المُرسِلون شيئًا يهمهم إلى شخص غريب. التحقق من المسافرين هو ما يجعل ذلك أمرًا معقولاً.';

  @override
  String get kycStatusNotStarted => 'لم يبدأ';

  @override
  String get kycStatusPending => 'قيد المراجعة';

  @override
  String get kycStatusApproved => 'تم التحقق';

  @override
  String get kycStatusRejected => 'غير معتمد';

  @override
  String get kycStartAction => 'ابدأ التحقق من الهوية';

  @override
  String get kycRetryAction => 'إعادة المحاولة';

  @override
  String get kycPendingBody => 'نراجع مستنداتك. يستغرق هذا عادةً أقل من يوم.';

  @override
  String get kycApprovedBody =>
      'تم التحقق من هويتك. يمكنك نشر الرحلات وحمل الطرود.';

  @override
  String get kycRejectedBody =>
      'تعذّر علينا التحقق من مستنداتك. يمكنك إعادة الإرسال.';

  @override
  String get kycRequiredForJourney =>
      'يجب أن يتم التحقق من هويتك قبل أن تتمكن من نشر رحلة.';

  @override
  String get kycDocumentType => 'نوع المستند';

  @override
  String get kycFrontImage => 'الوجه الأمامي للمستند';

  @override
  String get kycBackImage => 'الوجه الخلفي للمستند';

  @override
  String get kycSelfie => 'صورة شخصية';

  @override
  String get discoveryTravelersTitle => 'المسافرون المناسبون لهذا الطرد';

  @override
  String get discoveryRequestsTitle => 'الطرود على مسارك';

  @override
  String get discoveryEmptyTravelersBody =>
      'لا أحد متجه إلى وجهتك الآن. سنُعلمك عندما يتوفر أحد.';

  @override
  String get discoveryEmptyRequestsTitle => 'لا توجد طرود بعد';

  @override
  String get discoveryEmptyRequestsBody =>
      'لا شيء يطابق رحلتك الآن. سنُعلمك عندما يتوفر شيء.';

  @override
  String get findTravelersRouteFitExcellent => 'مسار مطابق ممتاز';

  @override
  String get findTravelersRouteFitGood => 'مسار مطابق جيد';

  @override
  String get findTravelersRouteFitCompatible => 'مسار متوافق';

  @override
  String get findTravelersTimingComfortable => 'يصل قبل الموعد بوقت كافٍ';

  @override
  String get findTravelersTimingFits => 'يناسب مهلة التسليم';

  @override
  String get findTravelersNewTraveller => 'جديد';

  @override
  String get findTravelersViewTrip => 'عرض الرحلة';

  @override
  String get findTravelersWhyThisFits => 'لماذا تناسب هذه الرحلة';

  @override
  String get findTravelersEmptyTitle => 'لا يوجد مسافرون في اتجاهك بعد';

  @override
  String get findTravelersEmptyBody =>
      'طلبك لا يزال نشطًا. سنُعلمك فور نشر أحدهم رحلة على مسارك.';

  @override
  String get findTravelersIneligibleAwaitingDeposit =>
      'ادفع عربون النشر لنشر هذا الطلب.';

  @override
  String get findTravelersIneligibleAlreadyMatched =>
      'هذا الطرد لديه مسافر بالفعل.';

  @override
  String get findTravelersIneligibleClosed => 'هذا الطلب مغلق.';

  @override
  String get findTravelersIneligibleInProgress => 'هذا الطرد في الطريق بالفعل.';

  @override
  String get findTravelersDirectLeg => 'يُنقل في مرحلة واحدة';

  @override
  String get findTravelersWholeTripMatches => 'كامل هذه الرحلة هو مسارك';

  @override
  String get findTravelersIdentityVerified => 'الهوية موثّقة';

  @override
  String get findTravelersFlightProofApproved => 'تذكرة الطيران موثّقة';

  @override
  String get findTravelersSortBestMatch => 'أفضل تطابق';

  @override
  String get findTravelersSortSoonest => 'أقرب رحلة';

  @override
  String get findTravelersShowMore => 'عرض مسافرين آخرين';

  @override
  String findTravelersStop(String city, String iata) {
    return '$city · $iata';
  }

  @override
  String findTravelersTransfers(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count تبديلات',
      two: 'تبديلان',
      one: 'تبديل واحد',
    );
    return '$_temp0';
  }

  @override
  String findTravelersPicksUpIn(String place) {
    return 'الاستلام في $place';
  }

  @override
  String findTravelersArrivesIn(String place) {
    return 'الوصول إلى $place';
  }

  @override
  String findTravelersArrivesBeforeDeadline(String arrival, String deadline) {
    return 'يصل $arrival، قبل موعدك $deadline';
  }

  @override
  String findTravelersHasRoomFor(String weight) {
    return 'يتسع لـ $weight كغ';
  }

  @override
  String findTravelersDeliveries(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count توصيلات',
      two: 'توصيلتان',
      one: 'توصيلة واحدة',
      zero: 'لا توجد توصيلات بعد',
    );
    return '$_temp0';
  }

  @override
  String get discoveryDetourSmall => 'انحراف طفيف جدًا عن المسار';

  @override
  String get discoveryDetourModerate => 'انحراف بسيط عن المسار';

  @override
  String get discoveryDetourLarge => 'انحراف ملحوظ عن المسار';

  @override
  String discoveryRatingCount(String rating, int count) {
    return '$rating ($count)';
  }

  @override
  String get discoveryNoRatingsYet => 'لا توجد تقييمات بعد';

  @override
  String get offerProposeTitle => 'قدّم عرضًا';

  @override
  String get offerProposeExplainer =>
      'أنت تحدد ما سيربحه المسافر. يمكنه القبول أو الرفض أو الرد بمبلغ مختلف.';

  @override
  String get offerRewardLabel => 'مكافأة المسافر';

  @override
  String get offerUseRecommended => 'استخدم المقترح';

  @override
  String get offerSend => 'إرسال العرض';

  @override
  String get offerSendCounter => 'إرسال العرض المقابل';

  @override
  String get offerCounter => 'عرض مقابل';

  @override
  String get offerAccept => 'قبول';

  @override
  String get offerDecline => 'رفض';

  @override
  String get offerWithdraw => 'سحب';

  @override
  String get offerAwaitingTraveler => 'بانتظار المسافر';

  @override
  String get offerAwaitingSender => 'بانتظار المُرسِل';

  @override
  String get offerAwaitingYou => 'دورك';

  @override
  String offerYouProposed(String amount) {
    return 'عرضت $amount';
  }

  @override
  String get offerHistoryTitle => 'سجل العروض';

  @override
  String get offerStatusPending => 'بانتظار الرد';

  @override
  String get offerStatusAccepted => 'مقبول';

  @override
  String get offerStatusDeclined => 'مرفوض';

  @override
  String get offerStatusWithdrawn => 'مسحوب';

  @override
  String get offerStatusExpired => 'منتهي الصلاحية';

  @override
  String get offerDeclineConfirmTitle => 'رفض هذا العرض؟';

  @override
  String get offerDeclineConfirmBody =>
      'سيتم إعلام الطرف الآخر. لا يزال بإمكانكما التفاوض بعد ذلك.';

  @override
  String get offerAcceptTravelerBody =>
      'تُحجز المساحة في رحلتك فور موافقتك. بعدها يتعين على المُرسِل الدفع.';

  @override
  String get offerAcceptSenderBody =>
      'بمجرد موافقتك، سيُطلب منك الدفع لبدء التوصيل.';

  @override
  String offerAcceptSenderConfirmTitle(String amount) {
    return 'هل تدفع $amount مقابل هذا التوصيل؟';
  }

  @override
  String offerAcceptTravelerConfirmTitle(String amount) {
    return 'هل تحصل على $amount مقابل هذا التوصيل؟';
  }

  @override
  String get offerCounterTravelerExplainer =>
      'اختر المبلغ الذي ستحصل عليه مقابل هذا التوصيل. يمكن للمُرسِل القبول أو الرفض أو تقديم عرض مقابل آخر.';

  @override
  String get offerYourOfferTitle => 'عرضك';

  @override
  String get offerTravelerCounterTitle => 'العرض المقابل للمسافر';

  @override
  String get offerYourCounterTitle => 'عرضك المقابل';

  @override
  String get offerSenderOfferTitle => 'عرض المُرسِل';

  @override
  String offerYouWouldPay(String amount) {
    return 'ستدفع $amount';
  }

  @override
  String offerTravelerAsks(String amount) {
    return 'يطلب المسافر $amount';
  }

  @override
  String offerYouWouldReceive(String amount) {
    return 'ستحصل على $amount';
  }

  @override
  String offerSenderOffers(String amount) {
    return 'يعرض المُرسِل $amount';
  }

  @override
  String offerBelowMinimum(String amount) {
    return 'اعرض $amount على الأقل';
  }

  @override
  String get offerEmptyTitle => 'لا توجد عروض بعد';

  @override
  String get offerEmptyBody => 'عندما يقدم أحدهم عرضًا، سيظهر هنا.';

  @override
  String get paymentTitle => 'الدفع';

  @override
  String get paymentChooseProvider => 'كيف تريد الدفع؟';

  @override
  String get paymentProviderStripe => 'Stripe';

  @override
  String get paymentProviderStripeSubtitle => 'فيزا وماستركارد وبطاقات أخرى';

  @override
  String get paymentProviderChargily => 'Chargily';

  @override
  String get paymentProviderChargilySubtitle =>
      'البطاقات الجزائرية — CIB وذهبية';

  @override
  String get paymentProviderUnavailable => 'غير متاح حاليًا';

  @override
  String get paymentProviderNotConfigured => 'غير متاح بعد';

  @override
  String get paymentProviderDisabled => 'معطّل مؤقتًا';

  @override
  String get paymentProviderConfigurationInvalid => 'غير جاهز بعد';

  @override
  String get paymentProviderAmountTooSmall =>
      'أقل من الحد الأدنى لطريقة الدفع هذه';

  @override
  String get paymentCheckoutFailedTitle => 'تعذّر بدء هذه الدفعة';

  @override
  String get paymentCheckoutFailedBody =>
      'رفض مزوّد الدفع فتح صفحة الدفع. لم يتم خصم أي مبلغ. جرّب الطريقة الأخرى أو عد بعد قليل.';

  @override
  String paymentRailEquivalent(String amount) {
    return 'ما يعادل $amount';
  }

  @override
  String paymentRailRate(String rate) {
    return '1 يورو = $rate دج';
  }

  @override
  String get paymentRailRateLocked =>
      'يُثبَّت سعر الصرف عند بدء الدفع. يبقى سعر التوصيل باليورو.';

  @override
  String paymentPayWith(String amount, String provider) {
    return 'ادفع $amount عبر $provider';
  }

  @override
  String a11yPaymentRailCharge(String provider, String amount) {
    return '$provider، يخصم $amount';
  }

  @override
  String get paymentNoProvidersTitle => 'لا توجد وسيلة دفع متاحة';

  @override
  String get paymentNoProvidersBody =>
      'الدفع غير متاح مؤقتًا. لم يتم خصم أي مبلغ ولم يتأثر توصيلك.';

  @override
  String paymentPayAction(String amount) {
    return 'ادفع $amount';
  }

  @override
  String get paymentOpeningProvider => 'جارٍ فتح صفحة الدفع الآمنة…';

  @override
  String get paymentFailedTitle => 'لم تكتمل عملية الدفع';

  @override
  String get paymentFailedBody =>
      'لم يُخصم أي مبلغ. يمكنك إعادة المحاولة أو استخدام وسيلة أخرى.';

  @override
  String get paymentStatusRequired => 'الدفع مطلوب';

  @override
  String get paymentStatusPaid => 'مدفوع';

  @override
  String get paymentStatusRefundPending => 'الاسترداد في الطريق';

  @override
  String get paymentStatusPartiallyRefunded => 'استرداد جزئي';

  @override
  String get paymentStatusRefunded => 'تم الاسترداد';

  @override
  String get paymentRedirectNotProof =>
      'نؤكد كل عملية دفع مع مزود الخدمة قبل اعتبارها مدفوعة.';

  @override
  String get guestPayTitle => 'طلب دفع';

  @override
  String get guestPayExplainer =>
      'الشخص الذي أرسل إليك هذا الرابط يطلب منك دفع هذا المبلغ مقابل توصيله عبر Wassla. لا حاجة إلى حساب.';

  @override
  String guestPayExpiresAt(String when) {
    return 'تنتهي صلاحيته $when';
  }

  @override
  String get guestPayWarning =>
      'يتيح لك هذا الرابط دفع هذا المبلغ فقط، ولا يمنح أي اطلاع على التوصيل أو على بيانات أي شخص.';

  @override
  String get guestPayPayerEmail => 'بريدك الإلكتروني لاستلام الإيصال';

  @override
  String get guestPayPayerEmailHelp =>
      'سنرسل إليه إيصال الدفع، ونبلغك إن استحق لك أي استرداد. لن يُنشأ لك أي حساب.';

  @override
  String get guestPayInvalidTitle => 'هذا الرابط غير صالح';

  @override
  String get guestPayInvalidBody =>
      'ربما انتهت صلاحيته، أو تم إلغاؤه، أو تم دفعه بالفعل.';

  @override
  String get recipientTitle => 'من سيستلم هذا؟';

  @override
  String get recipientExplainer =>
      'نرسل رمز التسليم بالبريد الإلكتروني إلى المستلِم. لا يمكن للمسافر إتمام التوصيل إلا إذا أعطاه المستلِم ذلك الرمز.';

  @override
  String get recipientName => 'اسم المستلِم';

  @override
  String get recipientEmail => 'البريد الإلكتروني للمستلِم';

  @override
  String get recipientEmailHelp =>
      'يُرسل رمز التسليم إلى هذا العنوان. تأكد من صحته.';

  @override
  String get recipientLanguage => 'لغة المستلِم';

  @override
  String get recipientLanguageHelp =>
      'هذه هي اللغة التي سنستخدمها في رسالة التوصيل إلى المستلِم.';

  @override
  String get recipientPhone => 'الهاتف (اختياري)';

  @override
  String get recipientNote => 'ملاحظة للمستلِم (اختياري)';

  @override
  String get recipientSave => 'حفظ المستلِم';

  @override
  String get recipientSaved => 'تم حفظ المستلِم';

  @override
  String get recipientRequiredBody =>
      'أضف المستلِم قبل الاستلام حتى نتمكن من إرسال رمز التسليم إليه.';

  @override
  String get recipientRecordedForTraveler => 'قدّم المُرسِل بيانات المستلِم.';

  @override
  String get pickupSenderTitle => 'رمز الاستلام';

  @override
  String get pickupSenderExplainer =>
      'أعطِ هذا الرمز للمسافر فقط عند تسليمه الطرد فعليًا. بهذا يؤكد أنه استلمه.';

  @override
  String get pickupSenderReveal => 'إظهار رمز الاستلام';

  @override
  String get pickupSenderWarning =>
      'لا ترسل هذا الرمز في رسالة. قله شفهيًا عند التسليم.';

  @override
  String get pickupTravelerTitle => 'تأكيد الاستلام';

  @override
  String get pickupTravelerExplainer =>
      'اطلب من المُرسِل رمز الاستلام عند تسليمه الطرد لك.';

  @override
  String get pickupCodeLabel => 'رمز الاستلام';

  @override
  String get pickupConfirmAction => 'تأكيد الاستلام';

  @override
  String get pickupConfirmedTitle => 'تم تأكيد الاستلام';

  @override
  String get pickupConfirmedBody => 'أنت تحمل هذا الطرد الآن.';

  @override
  String get pickupAwaitingTitle => 'بانتظار الاستلام';

  @override
  String get pickupAwaitingSenderBody =>
      'سيطلب منك المسافر رمز الاستلام عند اللقاء.';

  @override
  String get pickupAwaitingTravelerBody =>
      'قابل المُرسِل واطلب منه رمز الاستلام.';

  @override
  String get deliveryTravelerTitle => 'تأكيد التوصيل';

  @override
  String get deliveryTravelerExplainer =>
      'اطلب من المستلِم الرمز الذي أُرسل إليه بالبريد الإلكتروني.';

  @override
  String get deliveryCodeLabel => 'رمز التسليم';

  @override
  String get deliveryConfirmAction => 'تأكيد التوصيل';

  @override
  String get deliveryConfirmedTitle => 'تم تأكيد التوصيل';

  @override
  String get deliveryConfirmedTravelerBody =>
      'شكرًا لك. يجري تجهيز تحويل أرباحك.';

  @override
  String get deliveryConfirmedSenderBody =>
      'وصل طردك. تبقى دفعتك محمية لفترة قصيرة إضافية.';

  @override
  String get deliverySenderTitle => 'رمز التسليم';

  @override
  String deliveryCodeLockedTitle(String countdown) {
    return 'متاح خلال $countdown';
  }

  @override
  String get deliveryCodeLockedBody =>
      'لأسباب أمنية، يبقى رمز التسليم مقفلاً لمدة 30 دقيقة بعد الاستلام. كما لم يُرسل بعد بالبريد الإلكتروني إلى المستلِم.';

  @override
  String get deliveryCodeLockedWhy => 'لماذا هذا الانتظار؟';

  @override
  String get deliveryCodeLockedWhyBody =>
      'يعني هذا التوقف أنه لا يمكن تسليم الرمز في نفس لحظة تسليم الطرد. هذا ما يمنع تسجيل التوصيل كمكتمل قبل أن يحدث فعلاً.';

  @override
  String get deliveryCodeReadyTitle => 'رمز التسليم جاهز';

  @override
  String deliveryCodeSentToRecipient(String recipient) {
    return 'أرسلنا الرمز بالبريد الإلكتروني إلى $recipient.';
  }

  @override
  String get deliveryCodeReveal => 'إظهار رمز التسليم';

  @override
  String get deliveryCodeSenderWarning =>
      'يعطي المستلِم هذا الرمز للمسافر عند الباب. شاركه فقط مع المستلِم.';

  @override
  String get deliveryCodeTravelerNever =>
      'المستلِم وحده يملك هذا الرمز. اطلبه منه عند وصولك.';

  @override
  String codeAttemptsRemaining(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count محاولة متبقية',
      many: '$count محاولة متبقية',
      few: '$count محاولات متبقية',
      two: 'محاولتان متبقيتان',
      one: 'محاولة واحدة متبقية',
      zero: 'لا محاولات متبقية',
    );
    return '$_temp0';
  }

  @override
  String get codeIncorrect => 'هذا الرمز غير صحيح';

  @override
  String get codeLockedTitle => 'عدد كبير جدًا من المحاولات الخاطئة';

  @override
  String codeLockedBody(String when) {
    return 'أعد المحاولة $when. إذا تعثرت، اطلب رمزًا جديدًا.';
  }

  @override
  String get codeRotate => 'احصل على رمز جديد';

  @override
  String get codeRotated => 'تم إصدار رمز جديد. لم يعد الرمز القديم صالحًا.';

  @override
  String get codeRotateConfirmTitle => 'إصدار رمز جديد؟';

  @override
  String get codeRotateConfirmBody =>
      'سيتوقف الرمز الذي شاركته بالفعل عن العمل فورًا.';

  @override
  String get codeNotAvailableYet => 'هذا الرمز غير متاح بعد';

  @override
  String get codeCopyForReading => 'اقرأ الرمز بصوت مسموع بدلاً من إرساله.';

  @override
  String get protectionTitle => 'الدفع محمي';

  @override
  String protectionSenderBody(String when) {
    return 'يُحتفظ بدفعتك حتى $when. إذا كان هناك خطأ في التوصيل، افتح نزاعًا قبل ذلك.';
  }

  @override
  String protectionTravelerBody(String when) {
    return 'تم التسليم. تُحوَّل أرباحك بعد $when، عند انتهاء فترة الحماية.';
  }

  @override
  String get protectionEnded => 'أُغلقت فترة الحماية';

  @override
  String get protectionExplainerTitle => 'ماذا يعني هذا';

  @override
  String get protectionExplainerBody =>
      'تُحتفظ الأموال حتى تأكيد التوصيل وخلال فترة الحماية البالغة 48 ساعة. لا يحررها Wassla إلا بعد انتهاء هذه الفترة إذا لم يكن هناك نزاع مفتوح.';

  @override
  String get payoutTitle => 'تحويل الأرباح';

  @override
  String get payoutStatusNotEligible => 'ليس بعد';

  @override
  String get payoutStatusEligible => 'جاهزة';

  @override
  String get payoutStatusScheduled => 'مجدولة';

  @override
  String get payoutStatusProcessing => 'في الطريق';

  @override
  String get payoutStatusPaid => 'مدفوعة';

  @override
  String get payoutStatusFailed => 'فشلت';

  @override
  String get payoutStatusCancelled => 'ملغاة';

  @override
  String get payoutStatusFrozen => 'معلّقة';

  @override
  String get payoutFrozenBody =>
      'هناك نزاع مفتوح بشأن هذا التوصيل. يبقى تحويل الأرباح معلّقًا حتى حلّ النزاع.';

  @override
  String get payoutEmptyTitle => 'لا توجد تحويلات أرباح بعد';

  @override
  String get payoutEmptyBody => 'أكمل توصيلاً وستظهر أرباحك هنا.';

  @override
  String get disputeOpenTitle => 'فتح نزاع';

  @override
  String get disputeOpenExplainer =>
      'أخبرنا بالمشكلة. عند فتح نزاع، يتوقّف تحويل أرباح المسافر إلى حين مراجعة النزاع.';

  @override
  String get disputeCategory => 'ماذا حدث؟';

  @override
  String get disputeDescription => 'صِف المشكلة';

  @override
  String get disputeDescriptionHint => 'ما كنت تتوقعه، وما حدث فعلاً';

  @override
  String get disputeSubmit => 'فتح النزاع';

  @override
  String get disputeStatusOpen => 'مفتوح';

  @override
  String get disputeStatusAwaitingEvidence => 'بانتظار الأدلة';

  @override
  String get disputeStatusUnderReview => 'قيد المراجعة';

  @override
  String get disputeStatusResolved => 'تمت التسوية';

  @override
  String get disputeStatusClosed => 'مغلق';

  @override
  String get disputeEvidenceTitle => 'الأدلة';

  @override
  String get disputeEvidenceExplainer =>
      'تساعدنا الصور ومقاطع الفيديو على فهم ما حدث.';

  @override
  String get disputeAddPhoto => 'إضافة صورة';

  @override
  String get disputeAddVideo => 'إضافة فيديو';

  @override
  String get disputeAddNote => 'إضافة ملاحظة';

  @override
  String disputeUploading(int percent) {
    return 'جارٍ الرفع… $percent%';
  }

  @override
  String disputeFileTooLarge(String limit) {
    return 'هذا الملف كبير جدًا. الحد الأقصى هو $limit.';
  }

  @override
  String get disputeFileTypeNotAllowed =>
      'نوع هذا الملف غير مدعوم. استخدم JPEG أو PNG أو WebP أو MP4 أو MOV.';

  @override
  String get disputeEvidenceLimitReached => 'لقد أضفت الحد الأقصى من العناصر.';

  @override
  String get disputeResolutionTitle => 'النتيجة';

  @override
  String get disputeResolutionRefunded => 'تم الاسترداد للمُرسِل';

  @override
  String get disputeResolutionTravelerPaid => 'تم الدفع للمسافر';

  @override
  String get disputeResolutionPartial => 'تم التقسيم بين الطرفين';

  @override
  String get disputeWindowClosedTitle => 'أُغلقت فترة النزاع';

  @override
  String get disputeWindowClosedBody =>
      'يمكن فتح النزاعات خلال 48 ساعة بعد التوصيل.';

  @override
  String get cancelTitle => 'إلغاء هذا التوصيل';

  @override
  String get cancelConfirmAction => 'إلغاء التوصيل';

  @override
  String get cancelKeepAction => 'الإبقاء عليه';

  @override
  String get cancelFullRefund => 'سيُسترجع لك المبلغ كاملاً.';

  @override
  String get cancelWithCompensation =>
      'لأن الوقت اقترب من الاستلام، يُعوَّض المسافر عن حجزه للمساحة.';

  @override
  String get cancelNotAllowedTitle => 'لا يمكن إلغاء هذا هنا';

  @override
  String get cancelAfterPickupBody =>
      'تم استلام الطرد بالفعل. إذا كان هناك خطأ ما، افتح نزاعًا بدلاً من ذلك.';

  @override
  String get cancelOutcomeTitle => 'ماذا سيحدث';

  @override
  String get cancelCancelledTitle => 'ملغى';

  @override
  String get cancelRefundOnWay => 'استردادك في الطريق.';

  @override
  String get ratingTitle => 'كيف سارت الأمور؟';

  @override
  String get ratingSenderPrompt => 'قيّم المسافر';

  @override
  String get ratingTravelerPrompt => 'قيّم المُرسِل';

  @override
  String ratingScoreLabel(int score) {
    return '$score من 5';
  }

  @override
  String get ratingTagsLabel => 'ما الذي لفت انتباهك؟';

  @override
  String get ratingCommentLabel => 'أي شيء آخر؟ (اختياري)';

  @override
  String get ratingSubmit => 'إرسال التقييم';

  @override
  String get ratingSubmitted => 'شكرًا على تقييمك';

  @override
  String get ratingWaitingForOther =>
      'تم حفظ تقييمك. ستراه بمجرد أن يقيّمك الطرف الآخر أيضًا.';

  @override
  String get ratingHiddenUntilBoth => 'مخفي حتى تقيّما كلاكما';

  @override
  String get ratingWindowClosed => 'أُغلقت فترة التقييم.';

  @override
  String get ratingEmptyTitle => 'لا توجد تقييمات بعد';

  @override
  String get ratingEmptyBody => 'تظهر التقييمات بعد اكتمال التوصيل.';

  @override
  String get boostTitle => 'عزّز هذا الطلب';

  @override
  String get boostExplainer =>
      'يحصل المسافر على 100% من مكافأة التعزيز. تظهر الطلبات المعززة في مقدمة نتائج البحث.';

  @override
  String boostDurationDays(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days يوم',
      many: '$days يومًا',
      few: '$days أيام',
      two: 'يومان',
      one: 'يوم واحد',
      zero: 'لا أيام',
    );
    return '$_temp0';
  }

  @override
  String get chatTitle => 'المحادثة';

  @override
  String get chatEmptyTitle => 'لا توجد محادثات';

  @override
  String get chatEmptyBody => 'تُفتح المحادثة بمجرد دفع التوصيل.';

  @override
  String get chatThreadEmptyTitle => 'ابدأ بالسلام';

  @override
  String get chatThreadEmptyBody => 'اتفقا على مكان اللقاء ووقته.';

  @override
  String get chatComposerHint => 'اكتب رسالة';

  @override
  String get chatSend => 'إرسال';

  @override
  String get chatRetrySend => 'اضغط لإعادة المحاولة';

  @override
  String get chatSending => 'جارٍ الإرسال…';

  @override
  String get chatClosedTitle => 'هذه المحادثة مغلقة';

  @override
  String get chatClosedBody =>
      'لا يزال بإمكانك قراءتها، لكن لا يمكن إرسال رسائل جديدة.';

  @override
  String get chatUnavailableTitle => 'المحادثة غير متاحة بعد';

  @override
  String get chatUnavailableBody =>
      'تُفتح المحادثة لهذا التوصيل بمجرد تأكيد الدفع.';

  @override
  String get chatNeverShareCodes =>
      'لا تشارك رمز الاستلام أو رمز التسليم في المحادثة أبدًا.';

  @override
  String get notificationsTitle => 'الإشعارات';

  @override
  String get notificationsMarkAllRead => 'تعليم الكل كمقروء';

  @override
  String get notificationsEmptyTitle => 'لا شيء جديد';

  @override
  String get notificationsEmptyBody =>
      'تظهر هنا العروض والمدفوعات وتحديثات التوصيل.';

  @override
  String get profileTitle => 'الحساب';

  @override
  String get profileAccount => 'الحساب';

  @override
  String get profilePassportStamp => 'Wassla · عضو';

  @override
  String get profileCompletedDeliveries => 'مكتملة';

  @override
  String get profileRoles => 'ما تقوم به';

  @override
  String get profileVerification => 'التحقق';

  @override
  String get profileRatings => 'التقييمات';

  @override
  String get profilePayments => 'المدفوعات وتحويلات الأرباح';

  @override
  String get profileNotificationSettings => 'الإشعارات';

  @override
  String get profileLanguage => 'اللغة';

  @override
  String get profileLanguageSystem => 'لغة الجهاز';

  @override
  String get profileAppLanguage => 'لغة التطبيق';

  @override
  String get profileAppLanguageHelp =>
      'ما تقرأه داخل Wassla. محفوظ على هذا الهاتف.';

  @override
  String get profileEmailLanguage => 'لغة الرسائل';

  @override
  String get profileEmailLanguageHelp =>
      'اللغة التي نراسلك بها — المدفوعات والتحقق والتوصيل والنزاعات وأمان الحساب. محفوظة في حسابك.';

  @override
  String get profileEmailLanguageSaved => 'تم تحديث لغة الرسائل';

  @override
  String get profileSupport => 'المساعدة والدعم';

  @override
  String get profileTerms => 'شروط الخدمة';

  @override
  String get profilePrivacy => 'سياسة الخصوصية';

  @override
  String get profileLinkOpenFailed =>
      'تعذّر علينا فتح هذه الصفحة. تأكد من تثبيت متصفح.';

  @override
  String get profileAppearance => 'المظهر';

  @override
  String get profileAppearanceSystem => 'مطابقة الجهاز';

  @override
  String get profileAppearanceLight => 'فاتح';

  @override
  String get profileAppearanceDark => 'داكن';

  @override
  String get profileEmailVerified => 'تم التحقق من البريد الإلكتروني';

  @override
  String get profileEmailUnverified => 'لم يتم التحقق من البريد الإلكتروني';

  @override
  String profileMemberSince(String date) {
    return 'مع Wassla منذ $date';
  }

  @override
  String profileVersion(String version) {
    return 'الإصدار $version';
  }

  @override
  String get locationSearchTitle => 'اختر مكانًا';

  @override
  String get locationSearchHint => 'ابحث عن بلدية أو مطار';

  @override
  String get locationSearchStart => 'اكتب اسم بلدية أو مدينة أو مطار';

  @override
  String placeTierWilaya(String name) {
    return 'ولاية $name';
  }

  @override
  String placeTierDepartment(String name) {
    return 'مقاطعة $name';
  }

  @override
  String placeTierRegion(String name) {
    return 'منطقة $name';
  }

  @override
  String placeTierProvince(String name) {
    return 'إقليم $name';
  }

  @override
  String placeTierAutonomousCommunity(String name) {
    return 'منطقة $name ذاتية الحكم';
  }

  @override
  String placeTierState(String name) {
    return 'ولاية $name';
  }

  @override
  String placeTierDistrict(String name) {
    return 'دائرة $name';
  }

  @override
  String get locationTypeAirport => 'مطار';

  @override
  String locationAirportServesPlace(String place) {
    return 'يخدم $place';
  }

  @override
  String locationAirportNearPlace(String place) {
    return 'بالقرب من $place';
  }

  @override
  String locationAirportNearbyDistance(String distance) {
    return 'مطار قريب · $distance كم';
  }

  @override
  String get locationUseMap => 'اختر من الخريطة';

  @override
  String get locationConfirmPoint => 'استخدم هذه النقطة';

  @override
  String get locationSaved => 'الأماكن المحفوظة';

  @override
  String get locationPrivacyBeforeFunding =>
      'لا تُشارَك سوى المدينة إلى أن يُدفع ثمن التوصيل.';

  @override
  String get locationHiddenUntilFunded => 'العنوان الدقيق متاح بعد الدفع';

  @override
  String get locationSearchEmptyTitle => 'لا توجد نتائج';

  @override
  String get countryNameAlgeria => 'الجزائر';

  @override
  String get countryNameFrance => 'فرنسا';

  @override
  String get countryNameSpain => 'إسبانيا';

  @override
  String get countryNameGermany => 'ألمانيا';

  @override
  String get locationCountryQuestion => 'أي بلد؟';

  @override
  String get locationChangeCountry => 'تغيير';

  @override
  String get locationCountriesUnavailable =>
      'لا تتوفر أي بلدان في الوقت الحالي.';

  @override
  String get locationSelectCountryBody =>
      'اختر بلدًا في الأعلى، ثم ابحث عن المدينة أو البلدية أو المطار.';

  @override
  String get locationSearchReadyTitle => 'جاهز متى شئت';

  @override
  String get locationSearchHintAirports => 'ابحث عن مطار';

  @override
  String get locationSearchStartAirports =>
      'اكتب اسم المطار أو رمزه المكوّن من ثلاثة أحرف.';

  @override
  String get locationAirportsOnly =>
      'هذه المرحلة بالطائرة، لذا تُعرض المطارات فقط.';

  @override
  String get locationCurrentSelection => 'المحدَّد حاليًا';

  @override
  String locationSearchNoMatch(String query) {
    return 'لا شيء هنا يطابق «$query». تحقّق من الإملاء، أو جرّب أقرب مدينة كبيرة.';
  }

  @override
  String locationSearchNoMatchAirports(String query) {
    return 'لا يوجد مطار هنا يطابق «$query». جرّب اسم المدينة، أو الرمز المكوّن من ثلاثة أحرف.';
  }

  @override
  String locationPreferredExplainer(String place) {
    return 'تتم مطابقة المسافرين على $place. أما النقطة المفضلة فتحدد فقط المكان الذي تفضّل اللقاء فيه داخلها.';
  }

  @override
  String get locationPreferredFlexibleHint => 'لا حاجة إلى نقطة دقيقة';

  @override
  String get locationAddPreferredPoint => 'أضف نقطة مفضلة';

  @override
  String get locationChangePreferredPoint => 'غيّر النقطة';

  @override
  String get locationRemovePreferredPoint => 'أزل النقطة المفضلة';

  @override
  String get locationPreferredRemoved => 'أُزيلت النقطة المفضلة.';

  @override
  String get locationPreferredClearedByPlace =>
      'أُزيلت النقطة المفضلة — كانت تابعة للمكان الذي غيّرته للتو.';

  @override
  String get locationDecideLater => 'قرّر لاحقًا';

  @override
  String get locationPointInside => 'نقطة داخل';

  @override
  String locationDropPinHelpIn(String place) {
    return 'حرّك الخريطة حتى تستقر علامة التصويب في المكان المقصود داخل $place، ثم أكّد.';
  }

  @override
  String locationNoCentre(String place) {
    return 'لا يوجد لدينا مركز مسجَّل لـ $place، لذا تبدأ الخريطة بعرض واسع. حرّكها إلى المنطقة الصحيحة قبل التأكيد.';
  }

  @override
  String mapAttribution(String attribution) {
    return 'بيانات الخريطة $attribution';
  }

  @override
  String get locationYourPlaces => 'أماكنك';

  @override
  String get locationEmptyTitle => 'لا توجد أماكن محفوظة بعد';

  @override
  String get locationEmptyBody => 'ضع دبوسًا على الخريطة لحفظ عنوانك الأول.';

  @override
  String get locationNamePlaceTitle => 'سمِّ هذا المكان';

  @override
  String get locationNamePlaceBody =>
      'أنت فقط من يرى هذا الاسم. يرى الآخرون المدينة فقط إلى حين دفع ثمن التوصيل.';

  @override
  String get locationLabelField => 'الاسم';

  @override
  String get locationLabelHint => 'المنزل، بيت الوالدة، المكتب';

  @override
  String get locationSavePlace => 'احفظ هذا المكان';

  @override
  String get locationPlaceSaved => 'تم حفظ المكان.';

  @override
  String get locationPreferredMeetingPoint => 'نقطة اللقاء المفضلة';

  @override
  String get locationPreferredOptional => 'اختياري';

  @override
  String locationFlexibleWithin(String place) {
    return 'مرن داخل $place';
  }

  @override
  String locationPreferredValidation(String place) {
    return 'سيتحقق مزود الخرائط من أن هذه النقطة تقع ضمن $place.';
  }

  @override
  String get mapZoomIn => 'تكبير';

  @override
  String get mapZoomOut => 'تصغير';

  @override
  String get timelineTitle => 'التقدّم';

  @override
  String get timelineDone => 'تم';

  @override
  String get a11yStatusPrefix => 'الحالة';

  @override
  String get a11yMoneyAmount => 'المبلغ';

  @override
  String get a11yRequiredField => 'مطلوب';

  @override
  String get a11yCloseSheet => 'إغلاق';

  @override
  String get a11yLoadingContent => 'جارٍ تحميل المحتوى';

  @override
  String get a11ySelected => 'محدد';

  @override
  String get a11yNotSelected => 'غير محدد';

  @override
  String get a11yExpandSection => 'توسيع';

  @override
  String get a11yCollapseSection => 'طيّ';

  @override
  String get disputeCategoryNotDelivered => 'لم يصل أبدًا';

  @override
  String get disputeCategoryDamaged => 'وصل تالفًا';

  @override
  String get disputeCategoryWrongItem => 'غرض خاطئ';

  @override
  String get disputeCategoryLate => 'وصل متأخرًا جدًا';

  @override
  String get disputeCategoryNoShow => 'لم يحضر الطرف الآخر';

  @override
  String get disputeCategoryPayment => 'هناك خطأ ما يتعلق بالمال';

  @override
  String get disputeCategoryOther => 'شيء آخر';

  @override
  String unitWeightKg(String value) {
    return '$value كغ';
  }

  @override
  String unitDimensions(String length, String width, String height) {
    return '$length × $width × $height سم';
  }

  @override
  String unitCapacityKg(String value) {
    return '$value كغ متاحة';
  }

  @override
  String unitDurationHm(int hours, int minutes) {
    return '$hours س $minutes د';
  }

  @override
  String unitDurationM(int minutes) {
    return '$minutes د';
  }

  @override
  String distanceUnder(String max) {
    return 'أقل من $max كم';
  }

  @override
  String distanceBetween(String min, String max) {
    return '$min–$max كم';
  }

  @override
  String distanceOver(String min) {
    return 'أكثر من $min كم';
  }

  @override
  String get homeVerifyIdentityTitle => 'تحقق من هويتك';

  @override
  String get homeVerifyIdentityBody =>
      'يجب التحقق من هوية المسافرين قبل أن تصبح الرحلة منشورة.';

  @override
  String get homeAttentionOfferAwaiting => 'هناك عرض بانتظار ردك';

  @override
  String get homeAttentionFunding => 'ادفع لتأكيد هذا التوصيل';

  @override
  String get homeAttentionRecipient => 'أضف من سيستلم الطرد';

  @override
  String get homeAttentionRevealPickup => 'أظهر رمز الاستلام لمسافرك';

  @override
  String get homeAttentionSubmitPickup => 'أدخل رمز الاستلام';

  @override
  String get homeAttentionRevealDelivery => 'رمز التسليم جاهز';

  @override
  String get homeAttentionSubmitDelivery => 'أدخل رمز التسليم';

  @override
  String get homeAttentionRating => 'قيّم هذا التوصيل';

  @override
  String get deliveryCardSending => 'إرسال';

  @override
  String get deliveryCardCarrying => 'حمل';

  @override
  String deliveryCardWith(String name) {
    return 'مع $name';
  }

  @override
  String journeyLegCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count مرحلة',
      many: '$count مرحلة',
      few: '$count مراحل',
      two: 'مرحلتان',
      one: 'مرحلة واحدة',
      zero: 'لا مراحل',
    );
    return '$_temp0';
  }

  @override
  String journeyProofNeeded(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count تذكرة تحتاج إلى التحقق',
      many: '$count تذكرة تحتاج إلى التحقق',
      few: '$count تذاكر تحتاج إلى التحقق',
      two: 'تذكرتان تحتاجان إلى التحقق',
      one: 'تذكرة واحدة تحتاج إلى التحقق',
      zero: 'لا تذاكر تحتاج إلى التحقق',
    );
    return '$_temp0';
  }

  @override
  String get onboardingGetStarted => 'إنشاء حساب';

  @override
  String onboardingPageOf(int current, int total) {
    return 'الصفحة $current من $total';
  }

  @override
  String get authInvalidCredentials =>
      'البريد الإلكتروني أو كلمة المرور غير صحيحة';

  @override
  String get authShowPassword => 'إظهار كلمة المرور';

  @override
  String get authHidePassword => 'إخفاء كلمة المرور';

  @override
  String get authPhone => 'رقم الهاتف';

  @override
  String get authResetCodeSent =>
      'إذا كان هذا العنوان مرتبطًا بحساب، فقد أرسلنا إليه رمزًا مكونًا من ستة أرقام.';

  @override
  String get authResetCodeLabel => 'رمز من ستة أرقام';

  @override
  String get authNewPassword => 'كلمة المرور الجديدة';

  @override
  String get authResetDone =>
      'تم تغيير كلمة المرور. تم تسجيل خروجك من كل مكان. سجّل الدخول بكلمة المرور الجديدة.';

  @override
  String get authSendCode => 'إرسال الرمز';

  @override
  String get authResendCode => 'إرسال رمز جديد';

  @override
  String get authVerifyDone => 'تم التحقق من البريد الإلكتروني';

  @override
  String get authTermsNotice =>
      'بإنشائك حسابًا، فإنك توافق على شروط الخدمة وسياسة الخصوصية.';

  @override
  String get authVerifyNoCode =>
      'لم يصلك شيء؟ تحقق من مجلد الرسائل غير المرغوب فيها، ثم اطلب رمزًا جديدًا. الرمز في أحدث رسالة فقط هو الذي يعمل.';

  @override
  String get kycDocIdCard => 'بطاقة التعريف الوطنية';

  @override
  String get kycDocPassport => 'جواز السفر';

  @override
  String get kycDocDrivingLicense => 'رخصة القيادة';

  @override
  String get kycAddPhoto => 'إضافة صورة';

  @override
  String get kycReplacePhoto => 'استبدال';

  @override
  String get kycFileTooLarge =>
      'هذه الصورة كبيرة جدًا. يجب ألا يتجاوز حجم كل صورة 8 ميغابايت.';

  @override
  String get kycFileTypeNotAllowed => 'لا تُقبل إلا صور JPEG وPNG.';

  @override
  String get kycUploading => 'جارٍ إرسال مستنداتك…';

  @override
  String get kycSubmitAction => 'إرسال للمراجعة';

  @override
  String get kycSubmitted => 'تم استلام المستندات. سنراجعها قريبًا.';

  @override
  String get kycBackNotNeeded => 'لا يحتاج جواز السفر إلا إلى صفحة الصورة.';

  @override
  String get kycSelfieHelp => 'صورة واضحة لوجهك، تُلتقط الآن — تُقارن بمستندك.';

  @override
  String get kycUnavailable =>
      'التحقق غير متاح مؤقتًا. يُرجى إعادة المحاولة قريبًا.';

  @override
  String get notificationOffer => 'تحديث العرض';

  @override
  String get notificationPayment => 'تحديث الدفع';

  @override
  String get notificationChat => 'رسالة جديدة';

  @override
  String get notificationRequest => 'تحديث الطلب';

  @override
  String get notificationDelivery => 'تحديث التوصيل';

  @override
  String get notificationOther => 'تحديث';

  @override
  String get chatBlockedPayAction => 'الذهاب إلى الدفع';

  @override
  String get paymentProviderNewCheckoutsDisabled =>
      'لا يتم قبول مدفوعات جديدة حاليًا';

  @override
  String get paymentProviderPickAnother => 'جرّب وسيلة دفع أخرى.';

  @override
  String get paymentContinueTitle => 'هناك عملية دفع مفتوحة بالفعل';

  @override
  String get paymentContinueBody =>
      'أكمل عملية الدفع التي بدأتها بدلاً من فتح عملية ثانية.';

  @override
  String get paymentContinueAction => 'متابعة دفعتك';

  @override
  String get paymentCouldNotOpen =>
      'تعذّر علينا فتح صفحة الدفع. تأكد من وجود متصفح مثبّت لديك.';

  @override
  String get paymentCheckAgain => 'تحقق مرة أخرى';

  @override
  String get paymentNothingOutstandingTitle => 'لا يوجد ما يجب دفعه';

  @override
  String get paymentNothingOutstandingBody => 'تمت تسوية هذا بالفعل.';

  @override
  String get paymentOrderClosedTitle => 'لا يمكن دفع هذا الآن';

  @override
  String get paymentOrderClosedBody =>
      'تم إغلاق هذا الدفع أو استرداده، لذا لا يمكن فتح عملية دفع جديدة.';

  @override
  String get requestReadyUntil => 'جاهز حتى';

  @override
  String get requestReadyWindow => 'فترة الجاهزية';

  @override
  String get requestReadyWindowHelp =>
      'الفترة الزمنية التي يمكن للمسافر خلالها استلامه. حدد فترة، لا لحظة واحدة.';

  @override
  String get requestDeadlineHelp =>
      'أقصى موعد يمكن أن يصل فيه. يجب أن يكون بعد إغلاق فترة الجاهزية.';

  @override
  String get requestWeightHelp => 'بين 0.01 و100 كغ.';

  @override
  String get requestCategoryDocuments => 'وثائق';

  @override
  String get requestCategorySmallBox => 'صندوق صغير';

  @override
  String get requestCategoryElectronics => 'إلكترونيات';

  @override
  String get requestCategoryClothing => 'ملابس';

  @override
  String get requestCategoryOther => 'شيء آخر';

  @override
  String get requestProposedReward => 'ما تقترح دفعه';

  @override
  String get requestProposedRewardHelp =>
      'نقطة انطلاق، لا سعر نهائي. يمكن للمسافرين قبوله أو الرد بمبلغ مختلف.';

  @override
  String get requestRewardIsIntent =>
      'هذا ما اقترحته. يُحدد السعر النهائي عند قبول مسافر لعرض.';

  @override
  String get requestReviewTitle => 'راجع هذا';

  @override
  String get requestAckAllRequired => 'أكّد جميع النقاط الخمس قبل النشر.';

  @override
  String get requestPostAction => 'انشر هذا الطلب';

  @override
  String get requestDetailTitle => 'طلبك';

  @override
  String get requestParcelSection => 'الطرد';

  @override
  String get requestTimingSection => 'التوقيت';

  @override
  String get requestRouteSection => 'المسار';

  @override
  String get requestRouteNotRecorded => 'لم يُسجَّل المسار';

  @override
  String get requestMatchesSection => 'المسافرون الذين تواصلت معهم';

  @override
  String get requestNoMatchesYet => 'لم تقترح على أحد بعد.';

  @override
  String get requestAwaitingDepositNotice =>
      'لا يمكن للمسافرين رؤية هذا بعد. ادفع العربون لنشره.';

  @override
  String get requestFindTravelers => 'ابحث عن مسافرين';

  @override
  String get requestPayDepositAction => 'ادفع العربون';

  @override
  String get requestCancelAction => 'إلغاء الطلب';

  @override
  String get requestCancelConfirmTitle => 'إلغاء هذا الطلب؟';

  @override
  String get requestCancelConfirmBody =>
      'لن يكون مرئيًا للمسافرين بعد الآن. سيُسترجع لك أي عربون دفعته.';

  @override
  String get requestCancelled => 'تم إلغاء الطلب';

  @override
  String get requestCancelNotCancellableBody =>
      'تمت مطابقة مسافر مع هذا الطلب بالفعل، لذا لا يمكن إلغاؤه هنا.';

  @override
  String get requestCancelViaDealBody =>
      'أصبح هذا الطلب توصيلاً. ألغِه من صفحة التوصيل بدلاً من ذلك.';

  @override
  String requestPhotoCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count صورة',
      many: '$count صورة',
      few: '$count صور',
      two: 'صورتان',
      one: 'صورة واحدة',
      zero: 'لا صور',
    );
    return '$_temp0';
  }

  @override
  String get requestNotFragile => 'تعامل عادي';

  @override
  String get requestFragileYes => 'يُتعامل معه بحذر';

  @override
  String get requestTargetedNotice =>
      'لقد وجّهت هذا الطلب إلى مسافر واحد. لا يمكن لأي شخص آخر رؤيته.';

  @override
  String get depositNotRequiredTitle => 'لا حاجة إلى عربون';

  @override
  String get depositNotRequiredBody =>
      'يُنشر هذا الطلب دون عربون. لا يوجد ما يجب دفعه هنا.';

  @override
  String get depositClampedMin => 'هذا أصغر عربون نقبله.';

  @override
  String get depositClampedMax => 'هذا أكبر عربون نقبله، مهما كانت قيمة الطرد.';

  @override
  String get discoveryProposeBlocked =>
      'تعذّر علينا تحديد أي جزء من هذه الرحلة يناسب طردك. حدّث الصفحة وأعد المحاولة.';

  @override
  String get discoveryBreakdownNote =>
      'هكذا يُحسب المبلغ المقترح. اعرض مبلغًا مختلفًا وسيتغير الإجمالي تبعًا لذلك.';

  @override
  String get discoveryProposalSent => 'تم إرسال العرض';

  @override
  String get discoveryLegRangeMoved =>
      'تغيّر مسار هذا المسافر بينما كنت تتصفح. لقد حدّثناه.';

  @override
  String discoveryIncompatibleCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'لم يعد هذا المسافر يناسب طردك، لـ$count سبب.',
      many: 'لم يعد هذا المسافر يناسب طردك، لـ$count سببًا.',
      few: 'لم يعد هذا المسافر يناسب طردك، لـ$count أسباب.',
      two: 'لم يعد هذا المسافر يناسب طردك، لسببين.',
      one: 'لم يعد هذا المسافر يناسب طردك، لسبب واحد.',
    );
    return '$_temp0';
  }

  @override
  String get boostCompatibilityNote =>
      'لا يراه إلا المسافرون المطابقون لطردك بالفعل. التعزيز لا يغيّر هوية هؤلاء المسافرين.';

  @override
  String get moneyBaseReward => 'مكافأة التوصيل الأساسية';

  @override
  String get moneyBoostBonus => 'مكافأة التعزيز';

  @override
  String get moneyBoostFee => 'رسوم التعزيز';

  @override
  String get validationReadyWindowOrder =>
      'يجب أن تنتهي فترة الجاهزية بعد بدايتها';

  @override
  String validationWeightRange(String min, String max) {
    return 'أدخل وزنًا بين $min و$max كغ';
  }

  @override
  String get dealStepAgreed => 'تم الاتفاق على الشروط';

  @override
  String get dealStepPaid => 'تم الاحتفاظ بالدفعة';

  @override
  String get dealStepRecipient => 'تمت إضافة المستلِم';

  @override
  String get dealStepPickedUp => 'تم استلام الطرد';

  @override
  String get dealStepDelivered => 'تم التوصيل';

  @override
  String get dealStepProtection => 'دفعة محمية';

  @override
  String get dealStepCompleted => 'مكتمل';

  @override
  String get dealOpenChat => 'مراسلة';

  @override
  String get dealMoneySection => 'المال';

  @override
  String get dealActionPay => 'ادفع الآن';

  @override
  String get dealActionRecipient => 'إضافة مستلِم';

  @override
  String get dealActionPickup => 'الاستلام';

  @override
  String get dealActionDelivery => 'التوصيل';

  @override
  String get dealActionDispute => 'فتح نزاع';

  @override
  String get dealActionCancel => 'إلغاء هذا التوصيل';

  @override
  String get dealActionRate => 'إضافة تقييم';

  @override
  String dealFundingDeadline(String time) {
    return 'ادفع قبل $time وإلا سيتم تحرير المساحة';
  }

  @override
  String get dealTravelerAwaitingPayment => 'بانتظار دفع المُرسِل.';

  @override
  String get dealTravelerPaymentFunded => 'تم تأكيد دفعة المُرسِل وهي محمية.';

  @override
  String get ratingBlindNote =>
      'لن يرى أي منكما تقييم الآخر حتى تتركا كلاكما تقييمًا، أو تُغلق الفترة.';

  @override
  String get ratingSubmittedTitle => 'تم حفظ التقييم';

  @override
  String get ratingClosedTitle => 'انتهت مدة التقييم';

  @override
  String get ratingTheirsTitle => 'تقييم الطرف الآخر';

  @override
  String get ratingRevealedNote =>
      'لقد قيّمتما بعضكما، لذلك أصبح التقييمان ظاهرين لكليكما.';

  @override
  String get pickupTitle => 'الاستلام';

  @override
  String get pickupNextTitle => 'ماذا سيحدث بعد ذلك';

  @override
  String get pickupConfirmedSenderNext =>
      'أصبح رمز التسليم متاحًا الآن للمستلِم، وهو وحده من يمكنه إعطاؤه للمسافر.';

  @override
  String get pickupConfirmedTravelerNext =>
      'احمل الطرد إلى المستلِم. سيقرأ لك رمز التسليم عند الباب — لن يُعرض عليك هذا الرمز أبدًا.';

  @override
  String get deliverySafetyWaitingTitle => 'فترة الأمان قيد الانتظار';

  @override
  String get deliverySafetyWaitingSenderBody =>
      'تم تأكيد الاستلام. يصبح تأكيد التوصيل متاحًا بعد فترة الأمان؛ وعندها يرسل Wassla رمز التسليم إلى المستلِم عبر البريد الإلكتروني.';

  @override
  String get deliverySafetyWaitingTravelerBody =>
      'تم تأكيد الاستلام. واصل الطريق إلى المستلِم. بعد فترة الأمان، اطلب منه رمز التسليم — لن يعرضه Wassla لك مطلقًا.';

  @override
  String get pickupGoToDeliveryAction => 'الانتقال إلى التوصيل';

  @override
  String get pickupNotFundedBody =>
      'لم يُموَّل هذا التوصيل بعد، لذا لا يوجد رمز استلام لعرضه.';

  @override
  String get pickupNotReadyBody => 'هذا التوصيل ليس جاهزًا للاستلام بعد.';

  @override
  String get pickupAlreadyConfirmedBody =>
      'تم تأكيد الاستلام بالفعل على هذا التوصيل.';

  @override
  String get recipientRequiredTravelerBody =>
      'لم يضف المُرسِل المستلِم بعد. اطلب منه فعل ذلك، ثم جرّب الرمز مرة أخرى.';

  @override
  String get codeRequiresNewCodeBody =>
      'لا يمكن استخدام هذا الرمز مرة أخرى. يجب إصدار رمز جديد قبل أن تتمكن من التأكيد.';

  @override
  String codeRateLimitedBody(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'عدد كبير جدًا من المحاولات. انتظر $count ثانية وأعد المحاولة.',
      many: 'عدد كبير جدًا من المحاولات. انتظر $count ثانية وأعد المحاولة.',
      few: 'عدد كبير جدًا من المحاولات. انتظر $count ثوانٍ وأعد المحاولة.',
      two: 'عدد كبير جدًا من المحاولات. انتظر ثانيتين وأعد المحاولة.',
      one: 'عدد كبير جدًا من المحاولات. انتظر ثانية وأعد المحاولة.',
    );
    return '$_temp0';
  }

  @override
  String get deliveryTitle => 'التوصيل';

  @override
  String get deliverySenderExplainer =>
      'يستلم المستلِم هذا الرمز بالبريد الإلكتروني. يقرأه للمسافر عند الباب، وهذا ما يؤكد التوصيل.';

  @override
  String get deliveryCodeSentToRecipientUnknown =>
      'أرسلنا الرمز بالبريد الإلكتروني إلى المستلِم.';

  @override
  String get deliveryCodeBufferOpenBody =>
      'لا يزال رمز التسليم مقفلاً. يُفتح قفله بعد 30 دقيقة من الاستلام.';

  @override
  String get deliveryNotInCarriageBody =>
      'هذا التوصيل ليس في الطريق، لذا لا يمكن إصدار رمز جديد.';

  @override
  String get deliveryConfirmedTravelerNext =>
      'بدأت فترة الحماية. تُحوَّل أرباحك عند انتهائها.';

  @override
  String get deliveryAwaitingTitle => 'ليس بعد';

  @override
  String get deliveryAwaitingSenderBody =>
      'يظهر رمز التسليم هنا بمجرد استلام الطرد.';

  @override
  String get deliveryAwaitingTravelerBody =>
      'أكّد الاستلام أولاً. لا يمكن استخدام رمز التسليم إلا بعد ذلك.';

  @override
  String get protectionEndsInLabel => 'تنتهي خلال';

  @override
  String get payoutAmountLabel => 'المبلغ';

  @override
  String get payoutEligibleLabel => 'متوقعة';

  @override
  String get disputeViewAction => 'عرض النزاع';

  @override
  String get disputeOpened => 'تم فتح النزاع';

  @override
  String get disputeExistingOpenedBody =>
      'لديك بالفعل نزاع مفتوح على هذا التوصيل. لقد أخذناك إليه.';

  @override
  String get disputeFreezesPayoutTitle => 'يُعلَّق تحويل أرباح المسافر';

  @override
  String get disputeFreezesPayoutBody =>
      'لا يُدفع شيء ريثما ننظر في الأمر. يمكن لكلا الطرفين إضافة أدلة.';

  @override
  String get disputeNotAvailableTitle => 'لا يمكنك فتح نزاع بعد';

  @override
  String get disputeNotAvailableBody =>
      'يمكن فتح نزاع بمجرد استلام الطرد. قبل ذلك، ألغِ التوصيل بدلاً من ذلك.';

  @override
  String get disputeAlreadyResolvedBody =>
      'توجد بالفعل تسوية نزاع على هذا التوصيل.';

  @override
  String get disputeDetailTitle => 'النزاع';

  @override
  String get disputeReasonLabel => 'ما تم الإبلاغ عنه';

  @override
  String get disputeOpenedByLabel => 'فتحه';

  @override
  String get disputeOpenedBySender => 'المُرسِل';

  @override
  String get disputeOpenedByTraveler => 'المسافر';

  @override
  String get disputeOpenedAtLabel => 'تاريخ الفتح';

  @override
  String get disputeProtectionEndsLabel => 'تنتهي فترة الحماية';

  @override
  String get disputePayoutFrozenTitle => 'تحويل الأرباح معلّق';

  @override
  String get disputePayoutSettledBody => 'حُوِّلت الأرباح قبل فتح هذا النزاع.';

  @override
  String get disputeAmountsTitle => 'كيف تمت التسوية';

  @override
  String get disputeAmountsExplainer =>
      'هذه المبالغ هي قرار Wassla. لا شيء هنا يُحسب على هاتفك.';

  @override
  String get disputeCollectedTotal => 'المحصَّل من المُرسِل';

  @override
  String get disputeResolutionNoteLabel => 'ملاحظة من Wassla';

  @override
  String get disputeTimelineTitle => 'ماذا حدث';

  @override
  String get disputeEventOpened => 'تم فتح النزاع';

  @override
  String disputeEventStatusChanged(String status) {
    return 'تغيّرت الحالة إلى $status';
  }

  @override
  String get disputeEventEvidenceAdded => 'تمت إضافة دليل';

  @override
  String get disputeEventResolved => 'تم اتخاذ القرار';

  @override
  String get disputeEventClosed => 'تم إغلاق النزاع';

  @override
  String get disputeEventPayoutFrozen => 'تم تعليق تحويل الأرباح';

  @override
  String get disputeEventNote => 'تمت إضافة ملاحظة';

  @override
  String get disputeEventOther => 'تحديث';

  @override
  String get disputeEvidenceNone => 'لم تُضف أي أدلة بعد';

  @override
  String get disputeEvidenceView => 'عرض';

  @override
  String get disputeEvidenceOpenFailed => 'تعذّر علينا فتح ذلك. أعد المحاولة.';

  @override
  String get disputeEvidenceKindText => 'ملاحظة';

  @override
  String get disputeEvidenceKindPhoto => 'صورة';

  @override
  String get disputeEvidenceKindVideo => 'فيديو';

  @override
  String disputeEvidenceCount(int count, int max) {
    return 'تمت إضافة $count من $max';
  }

  @override
  String get disputeEvidenceNoteHint => 'ما تريد أن نعرفه';

  @override
  String get disputeEvidenceAdded => 'تمت إضافة دليل';

  @override
  String get disputeEvidenceClosedBody =>
      'هذا النزاع مغلق، لذا لا يمكن إضافة المزيد.';

  @override
  String get disputeEvidenceTypeMismatchBody =>
      'لا يطابق هذا الملف النوع الذي اخترته.';

  @override
  String get disputeEvidenceContentMismatchBody =>
      'هذا الملف ليس كما يدّعي. جرّب ملفًا آخر.';

  @override
  String get disputeEvidenceLinkNote =>
      'تنتهي صلاحية روابط الأدلة بعد دقائق قليلة، لذا نجلب رابطًا جديدًا في كل مرة تفتح فيها شيئًا.';

  @override
  String get disputeEvidenceTextRequiredBody => 'اكتب شيئًا قبل إضافة ملاحظة.';

  @override
  String get disputeEvidenceFileRequiredBody => 'اختر ملفًا أولاً.';

  @override
  String get onboardingStamp => 'منذ 2026 · الجزائر ↔ فرنسا';

  @override
  String benefitsIndex(int current, int total) {
    return '$current / $total';
  }

  @override
  String get benefitsChapterOneEyebrow => 'الفصل الأول · البريد';

  @override
  String get benefitsChapterOneTitle => 'أرسل إلى أي مكان،\nبجزء من التكلفة.';

  @override
  String get benefitsChapterOneAccent => 'إلى فرنسا والجزائر وأبعد.';

  @override
  String get benefitsChapterOneBody =>
      'يحمل المسافرون طردك ضمن أمتعتهم، فتدفع جزءاً بسيطاً من تكلفة الشحن السريع.';

  @override
  String get benefitsChapterOneStamp => 'بريد جوي';

  @override
  String get benefitsChapterTwoEyebrow => 'الفصل الثاني · الحقيبة';

  @override
  String get benefitsChapterTwoTitle => 'اربح وأنت\nمسافر.';

  @override
  String get benefitsChapterTwoAccent => 'سافر. اربح.';

  @override
  String get benefitsChapterTwoBody =>
      'متوجّه إلى الجزائر أو باريس أو وهران؟ املأ الكيلوغرامات غير المستعملة في حقيبتك.';

  @override
  String get benefitsChapterTwoStamp => 'الصعود';

  @override
  String get benefitsChapterThreeEyebrow => 'الفصل الثالث · الختم';

  @override
  String get benefitsChapterThreeTitle => 'مبنيّ على\nالثقة.';

  @override
  String get benefitsChapterThreeAccent => 'لا شيء يمضي بالكلام وحده.';

  @override
  String get benefitsChapterThreeBody =>
      'هويات موثّقة، ومبلغ محجوز حتى التسليم، ورمز عند كل تسليم.';

  @override
  String get benefitsChapterThreeStamp => 'موثّق';

  @override
  String get benefitsHandoverCaption => 'رمز التسليم';

  @override
  String get benefitsKilosFree => 'كغ\nمتاح';

  @override
  String get authWelcomeBackStamp => 'أهلاً بعودتك';

  @override
  String get authSignInHeadline => 'سعداء برؤيتك\nمن جديد.';

  @override
  String get authSignInSubhead => 'سجّل الدخول لمتابعة شحناتك من حيث توقّفت.';

  @override
  String get authJoinStamp => 'انضمّ إلى الممر';

  @override
  String get authSignUpHeadline => 'أنشئ جواز\nسفرك.';

  @override
  String get authSignUpSubhead => 'دقيقتان — ثم يمكنك الإرسال أو السفر.';

  @override
  String get authForgotStamp => 'تعذّر الدخول';

  @override
  String get authForgotHeadline => 'لنُعِد لك\nالدخول.';

  @override
  String get authVerifyStamp => 'ختم أخير';

  @override
  String stateRateLimitedWait(int seconds) {
    return 'انتظر نحو $seconds ثانية قبل المحاولة مجدداً.';
  }

  @override
  String get authForgotSubhead =>
      'أدخل البريد المرتبط بحسابك وسنرسل إليه رمزاً من ستة أرقام.';

  @override
  String get authVerifySubhead =>
      'أدخل الرمز المكوّن من ستة أرقام الذي أرسلناه إليك. هذه الخطوة الأخيرة.';

  @override
  String get requestItemPhoto => 'صورة الغرض';

  @override
  String get requestItemPhotoHelp =>
      'أضف صورة واضحة لما ترسله. يقرّر المسافرون بناءً عليها.';

  @override
  String get requestItemPhotoChoose => 'اختر صورة';

  @override
  String get requestItemPhotoFromGallery => 'من المعرض';

  @override
  String get requestItemPhotoTakePhoto => 'التقاط صورة';

  @override
  String get requestItemPhotoReplace => 'استبدال';

  @override
  String get requestItemPhotoRemove => 'إزالة الصورة';

  @override
  String get requestItemPhotoUploading => 'جارٍ رفع صورتك…';

  @override
  String get requestItemPhotoReady => 'تمت إضافة الصورة';

  @override
  String get requestItemPhotoRequired => 'صورة الغرض مطلوبة.';

  @override
  String get requestItemPhotoFormatRule =>
      'JPEG أو PNG أو WebP، حتى 10 ميغابايت.';

  @override
  String get requestItemPhotoTooLarge =>
      'هذه الصورة كبيرة جداً. اختر صورة أقل من 10 ميغابايت.';

  @override
  String get requestItemPhotoTypeNotAllowed =>
      'نوع الملف غير مقبول. استخدم صورة JPEG أو PNG أو WebP.';

  @override
  String get requestItemPhotoUploadFailed =>
      'لم يتم رفع الصورة. ما زالت محدّدة — أعد المحاولة.';

  @override
  String get requestItemPhotoStorageUnavailable =>
      'تخزين الصور غير متاح حالياً. أعد المحاولة بعد قليل.';

  @override
  String get requestItemPhotoPrivacy =>
      'لا يرى الصورة إلا المسافرون الذين يمكنهم رؤية هذا الطلب.';

  @override
  String get fieldOptional => 'اختياري';

  @override
  String get requestDimensionsOptionalHelp =>
      'اختياري. اتركه فارغاً إن لم تقس الطرد — أو أدخل الأبعاد الثلاثة.';

  @override
  String get requestDimensionsPartialFix =>
      'أدخل الطول والعرض والارتفاع معاً، أو امسح الثلاثة.';

  @override
  String get formFixBeforeContinuing => 'صحّح الحقل المحدّد قبل المتابعة.';

  @override
  String formFixCountBeforeContinuing(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'صحّح $count حقول قبل المتابعة.',
      one: 'صحّح حقلاً واحداً قبل المتابعة.',
    );
    return '$_temp0';
  }

  @override
  String get formServerRefusedOnStep =>
      'رفض الخادم هذا الطلب. المشكلة في هذه الخطوة، وهي موضّحة أدناه.';

  @override
  String get pushPermissionHeading => 'على هذا الهاتف';

  @override
  String get pushPermissionBody =>
      'احصل على تحديثات في وقتها حول العروض والمدفوعات والتسليم والرسائل والتحقق. لا يطلب Wassla الإذن إلا عندما تختار التفعيل.';

  @override
  String get pushPermissionEnabled => 'الإشعارات مفعّلة.';

  @override
  String get pushPermissionDeniedRequestable =>
      'لا تزال الإشعارات متوقفة. اختر تفعيل الإشعارات ليطلبها Android مرة أخرى. يبقى صندوق الإشعارات داخل التطبيق متاحًا في كل الأحوال.';

  @override
  String get pushPermissionDenied =>
      'الإشعارات متوقفة على مستوى النظام. يمكنك تفعيلها من الإعدادات.';

  @override
  String get pushPermissionUnavailable =>
      'الإشعارات الفورية غير مضبوطة في هذا الإصدار. تظل إشعارات التطبيق متاحة.';

  @override
  String get pushPermissionInitializationFailed =>
      'تعذّر تشغيل الإشعارات الفورية على هذا الهاتف. تبقى إشعارات التطبيق متاحة؛ أعد فتح Wassla للمحاولة مرة أخرى.';

  @override
  String get pushEnableAction => 'تفعيل الإشعارات';

  @override
  String get pushOpenSettingsAction => 'فتح إعدادات الإشعارات';

  @override
  String get pushRegistrationPending =>
      'إذن إشعارات النظام مفعّل. يُكمل Wassla إعداد الإشعارات على هذا الهاتف.';

  @override
  String get pushRegistrationFailed =>
      'إذن إشعارات النظام مفعّل، لكن تعذّر على Wassla تسجيل هذا الهاتف. تحقق من اتصالك وحاول مرة أخرى.';

  @override
  String get pushRetryRegistrationAction => 'إعادة محاولة إعداد الإشعارات';

  @override
  String get pushPreferencesHeading => 'أنواع الإشعارات';

  @override
  String get pushPreferencesBody =>
      'تتحكم هذه الخيارات في الرسائل ونشاط السوق، ولا تغيّر إذن النظام على هذا الهاتف. تبقى تحديثات التوصيل والحساب الأساسية متاحة.';

  @override
  String get pushEssentialTitle => 'التحديثات الأساسية';

  @override
  String get pushEssentialBody =>
      'تبقى تحديثات الدفع والتسليم والنزاعات والتحقق وأمان الحساب مفعّلة.';

  @override
  String get pushMessagesTitle => 'الرسائل';

  @override
  String get pushMessagesBody => 'نشاط جديد في المحادثات.';

  @override
  String get pushMarketplaceTitle => 'نشاط السوق';

  @override
  String get pushMarketplaceBody => 'العروض والمطابقات والرحلات والطلبات.';

  @override
  String get notificationAccount => 'تحديث التحقق';

  @override
  String get notificationDispute => 'تحديث النزاع';

  @override
  String get notificationPayout => 'تحديث تحويل الأرباح';

  @override
  String get payoutMethodsTitle => 'وسائل تحويل الأرباح';

  @override
  String get profilePayoutMethods => 'وسائل تحويل الأرباح';

  @override
  String get payoutPreferenceTitle => 'تفضيل تحويل الأرباح';

  @override
  String get payoutPreferenceEurOnly => 'باليورو فقط';

  @override
  String get payoutPreferenceDzdOnly => 'بالدينار الجزائري فقط';

  @override
  String get payoutPreferenceBoth => 'كلاهما';

  @override
  String get payoutPreferenceBothExplainer =>
      'تُحوَّل أرباح الطلبات المدفوعة عبر Stripe باليورو، وأرباح الطلبات المدفوعة عبر Chargily بالدينار الجزائري.';

  @override
  String get payoutPreferenceScopeNote =>
      'يسري هذا التفضيل على تحويلات الأرباح المستقبلية فقط.';

  @override
  String get payoutEurTitle => 'تحويل الأرباح باليورو (Stripe)';

  @override
  String get payoutEurNotConfiguredBody =>
      'اربط حسابك المصرفي الأوروبي لتلقّي أرباحك باليورو.';

  @override
  String get payoutEurSetupRequiredBody =>
      'أكمل إعداد حسابك لدى Stripe لتفعيل تحويل الأرباح باليورو.';

  @override
  String get payoutEurPendingVerificationBody =>
      'تقوم Stripe حالياً بالتحقق من بيانات حسابك. سيتم إشعارك فور اعتمادها.';

  @override
  String get payoutEurReadyBody => 'حسابك باليورو معتمد وجاهز لتلقّي الأرباح.';

  @override
  String get payoutEurNeedsAttentionBody =>
      'يتطلب حسابك لدى Stripe مراجعة قبل تحويل الأرباح.';

  @override
  String get payoutActionSetupEur => 'إعداد تحويل الأرباح باليورو';

  @override
  String get payoutActionResumeEur => 'متابعة الإعداد';

  @override
  String get payoutActionManageEur => 'إدارة الحساب على Stripe';

  @override
  String get payoutActionRefresh => 'تحديث الحالة';

  @override
  String get payoutDzdTitle => 'تحويل الأرباح بالدينار (CCP / بريدي موب)';

  @override
  String get payoutDzdNotConfiguredBody =>
      'أضف حساب CCP وشيكًا مُسطَّرًا لتلقّي أرباحك في الجزائر.';

  @override
  String get payoutDzdSetupRequiredBody =>
      'أرسل بيانات CCP والشيك المُسطَّر للمتابعة.';

  @override
  String get payoutDzdPendingReviewBody =>
      'بيانات CCP والشيك المُسطَّر قيد المراجعة لدى فريقنا.';

  @override
  String get payoutDzdReadyBody =>
      'حساب CCP معتمد وجاهز لتلقّي أرباحك بالدينار.';

  @override
  String get payoutDzdNeedsAttentionBody =>
      'يلزم التحقق من بيانات تحويل الأرباح أو تحديثها.';

  @override
  String get payoutDzdRejectedBody =>
      'لم يُقبل حساب CCP هذا لتحويل الأرباح. أرسل بيانات حساب آخر باسمك.';

  @override
  String get payoutDzdCorrectionBody =>
      'تحتاج بيانات تحويل الأرباح إلى تصحيح. أعد إرسالها مع صورة واضحة للشيك المُسطَّر كاملًا.';

  @override
  String get payoutDzdInactiveBody =>
      'تحويل الأرباح بالدينار غير مفعّل حاليًا لحسابك.';

  @override
  String get payoutActionSetupDzd => 'إعداد تحويل الأرباح بالدينار الجزائري';

  @override
  String get payoutActionReplaceDzd => 'تحديث بيانات تحويل الأرباح';

  @override
  String get payoutDzdCcpLabel => 'حساب CCP';

  @override
  String get payoutDzdRipLabel => 'RIP';

  @override
  String get dzdFormTitle => 'إعداد تحويل الأرباح بالدينار الجزائري';

  @override
  String get dzdFormScopeExplainer =>
      'تُستخدم هذه البيانات في تحويلات الأرباح المستقبلية المؤهلة. تبقى وجهة التحويلات المموّلة مسبقًا كما هي.';

  @override
  String get dzdFirstNameLabel => 'الاسم';

  @override
  String get dzdLastNameLabel => 'اللقب';

  @override
  String get dzdCcpNumberLabel => 'رقم حساب CCP';

  @override
  String get dzdCcpNumberHint => 'من 1 إلى 20 رقماً';

  @override
  String get dzdCcpKeyLabel => 'مفتاح CCP';

  @override
  String get dzdCcpKeyHint => 'رقمان';

  @override
  String get dzdRipLabel => 'رقم الحساب البريدي الجاري (RIP)';

  @override
  String get dzdRipHint => '20 رقماً';

  @override
  String get dzdChequeProofLabel => 'صورة كاملة لشيك مُسطَّر';

  @override
  String get dzdChequeProofHelper => 'حمّل صورة واضحة وكاملة للشيك المُسطَّر.';

  @override
  String get dzdChequeAddPhoto => 'اختيار صورة';

  @override
  String get dzdChequeReplacePhoto => 'تغيير الصورة';

  @override
  String get dzdSubmitAction => 'حفظ بيانات تحويل الأرباح';

  @override
  String get dzdSubmitSuccess => 'تم حفظ بيانات تحويل الأرباح.';

  @override
  String get payoutReasonSetupRequired => 'يلزم إعداد وسيلة تحويل الأرباح';

  @override
  String get payoutReasonUnderReview => 'الملف قيد المراجعة';

  @override
  String get payoutReasonNeedsAttention => 'يلزم التحقق من الملف';

  @override
  String get payoutReasonOnHold => 'تحويل الأرباح معلّق مؤقتًا';

  @override
  String get payoutReasonDisputeActive => 'يوجد نزاع مفتوح على هذا الطلب';

  @override
  String get payoutReasonFailed => 'تعذّر تحويل الأرباح';

  @override
  String get payoutReasonReturned => 'أعاد المصرف مبلغ تحويل الأرباح';

  @override
  String get payoutReasonCountryUnsupported =>
      'Stripe لا يدعم تحويل الأرباح باليورو في هذا البلد';

  @override
  String payoutRateLabel(String rate) {
    return 'سعر الصرف المعتمد: 1 EUR = $rate DZD';
  }

  @override
  String get payoutHistoryTitle => 'سجل تحويلات الأرباح';

  @override
  String get payoutDetailTitle => 'تفاصيل تحويل الأرباح';

  @override
  String get payoutRailLabel => 'قناة تحويل الأرباح';

  @override
  String get payoutRailStripeEur => 'Stripe (يورو)';

  @override
  String get payoutRailManualDzd => 'تحويل CCP (دينار)';

  @override
  String get payoutRailUnavailable => 'غير متاح';

  @override
  String get payoutReferenceLabel => 'مرجع التحويل';

  @override
  String get payoutDeliveryLabel => 'الطلب المرتبط';

  @override
  String get payoutEligibleAtLabel => 'تاريخ الاستحقاق';

  @override
  String get payoutSentAtLabel => 'تاريخ الإرسال';

  @override
  String get payoutPaidAtLabel => 'تاريخ الدفع';

  @override
  String get payoutProtectionEndsAtLabel => 'نهاية فترة الحماية';

  @override
  String get payoutViewAction => 'عرض تفاصيل تحويل الأرباح';

  @override
  String get payoutViewHistoryAction => 'عرض سجل تحويلات الأرباح';

  @override
  String get payoutOpenStripeError =>
      'تعذّر فتح رابط إعداد Stripe. يرجى المحاولة مجدداً.';

  @override
  String get payoutStatusAwaitingDelivery => 'بانتظار التسليم';

  @override
  String get payoutStatusProtectionActive => 'فترة الحماية';

  @override
  String get payoutStatusReleasePending => 'بانتظار إتاحة تحويل الأرباح';

  @override
  String get payoutStatusReady => 'تحويل الأرباح جاهز';

  @override
  String get payoutStatusSent => 'أُرسل تحويل الأرباح';

  @override
  String get payoutStatusNeedsAttention => 'يلزم اتخاذ إجراء';

  @override
  String get payoutProfileReady => 'وسيلة تحويل الأرباح جاهزة';

  @override
  String get payoutProfileNeedsAttention =>
      'يلزم التحقق من وسيلة تحويل الأرباح';

  @override
  String get earlyArrivalAction => 'وصلتُ مبكراً';

  @override
  String get earlyArrivalConfirmSheetTitle => 'إبلاغ عن وصول مبكر';

  @override
  String get earlyArrivalConfirmSheetBody =>
      'سنُبلغ المُرسِل بوصولك قبل الموعد المحدد. عليه تأكيد وصولك. يبقى تسليم الطرد خطوة منفصلة، ويخضع موعد تحويل الأرباح لقواعد الحماية في Wassla.';

  @override
  String get earlyArrivalWaitingSenderTitle => 'بانتظار تأكيد المُرسِل';

  @override
  String get earlyArrivalWaitingSenderBody =>
      'أبلغتَ عن وصولك المبكر. تم إخطار المُرسِل لتأكيد الوصول. يبقى تسليم الطرد إجراءً منفصلاً.';

  @override
  String get earlyArrivalSenderNoticeTitle => 'أفاد المسافر بأنه وصل مبكراً';

  @override
  String get earlyArrivalSenderNoticeBody =>
      'أبلغ المسافر بوصوله مبكرًا. أكّد وصوله فقط. يبقى تسليم الطرد وفترة حماية الدفع خطوتين منفصلتين.';

  @override
  String get earlyArrivalConfirmAction => 'تأكيد الوصول';

  @override
  String get earlyArrivalDeclineAction => 'رفض';

  @override
  String get earlyArrivalConfirmedTitle => 'تم تأكيد الوصول';

  @override
  String get earlyArrivalConfirmedBody =>
      'تم تأكيد الوصول المبكر. يُؤكَّد تسليم الطرد وتبدأ فترة الحماية (48 ساعة) بعد التحقق من رمز التسليم.';

  @override
  String get earlyArrivalDeclinedTitle => 'لم يتم تأكيد الوصول المبكر';

  @override
  String get earlyArrivalDeclinedBody =>
      'لم يتم تأكيد تقرير الوصول المبكر. سيستمر التسليم وفق المسار المجدول.';

  @override
  String get earlyArrivalScheduledArrivalLabel =>
      'موعد الوصول المحدد لهذا التوصيل';

  @override
  String get earlyArrivalPayoutFloorExplanation =>
      'يبقى تحويل الأرباح مرتبطًا بنهاية فترة الحماية المحددة لهذا التوصيل حتى عند الوصول مبكرًا.';

  @override
  String get earlyArrivalPayoutProtectedGateLabel =>
      'تحويل الأرباح متاح ابتداءً من';

  @override
  String get routeTitle => 'المسار';

  @override
  String get routeUnavailableFunded => 'لم يُسجَّل مسار الرحلة لهذا التوصيل.';

  @override
  String get routeUnavailableBeforeFunding =>
      'يظهر مسار الرحلة هنا بعد دفع تكلفة التوصيل.';

  @override
  String get routeFlightMode => 'رحلة طيران';

  @override
  String get routeDriveMode => 'مسار بري';

  @override
  String get notificationArrivalReported => 'وصل المسافر مبكراً';

  @override
  String get notificationArrivalConfirmed => 'تم تأكيد الوصول المبكر';

  @override
  String get notificationArrivalDeclined => 'لم يتم تأكيد الوصول المبكر';

  @override
  String get routeBasisSnapshot => 'المسار المحجوز';

  @override
  String get routeBasisLive => 'المسار المباشر';

  @override
  String get pricingMinimumLabel => 'الحد الأدنى للسعر';

  @override
  String get pricingRecommendedLabel => 'السعر الموصى به';

  @override
  String get pricingYourOfferLabel => 'عرضك';

  @override
  String get pricingBelowRecommended =>
      'أقل من الموصى به — قد يستغرق قبول المسافرين وقتاً أطول.';

  @override
  String get pricingCompetitive => 'عرض منافس — يتطابق بشكل أسرع مع المسافرين.';

  @override
  String pricingBelowMinimumError(String amount) {
    return 'يجب أن يكون العرض $amount على الأقل';
  }

  @override
  String get pricingTravelerReceives => 'يستلم المسافر';

  @override
  String get pricingPlatformFee => 'رسوم Wassla';

  @override
  String get pricingTotalSenderCost => 'إجمالي تكلفة المُرسِل';

  @override
  String get pricingIncrement50c => 'زيادة 50 سنتاً';

  @override
  String get pricingDecrement50c => 'إنقاص 50 سنتاً';

  @override
  String get depositSectionTitle => 'عربون النشر';

  @override
  String depositPresetMin(String amount) {
    return 'الحد الأدنى ($amount)';
  }

  @override
  String depositPresetRecommended(String amount) {
    return 'الموصى به ($amount)';
  }

  @override
  String depositPresetFull(String amount) {
    return 'دفع كامل المبلغ ($amount)';
  }

  @override
  String get depositPresetCustom => 'مخصص';

  @override
  String get depositFullDepositNotice =>
      'تم دفع المبلغ الحالي بالكامل. إذا قمت بزيادة المكافأة أو التعزيز لاحقاً، فقد يُطلب رصيد إضافي.';

  @override
  String get depositRemainingBalance => 'الرصيد المتبقي عند التسليم';

  @override
  String get depositCustomAmountLabel => 'مبلغ عربون مخصص';

  @override
  String get boostSectionTitle => 'تعزيز هذا الطلب';

  @override
  String get boostPresetNone => 'بدون تعزيز (0 €)';

  @override
  String get boostPreset5 => '+5 €';

  @override
  String get boostPreset10 => '+10 €';

  @override
  String get boostPresetCustom => 'مخصص';

  @override
  String get boostCustomAmountLabel => 'مبلغ تعزيز مخصص';

  @override
  String boostCurrentActive(String amount) {
    return 'التعزيز الحالي: $amount';
  }

  @override
  String get boostEditAction => 'تعديل التعزيز';

  @override
  String get boostAddAction => 'أضف تعزيزًا';

  @override
  String get boostPostPublicationOnly =>
      'يمكنك إضافة تعزيز الآن بعد نشر هذا الطلب. يحصل المسافرون عليه بالكامل.';

  @override
  String get boostRemoveAction => 'إزالة التعزيز';

  @override
  String get boostHistoryTitle => 'سجل التعزيز';

  @override
  String get boostNotEditable =>
      'لا يمكن تعديل التعزيز بعد قبول العرض أو انتهاء صلاحية الطلب.';

  @override
  String get guestPaymentTitle => 'اطلب من شخص آخر أن يدفع';

  @override
  String get guestCreateAction => 'إنشاء رابط الدفع';

  @override
  String get guestShareLead =>
      'شارك رابط الدفع الآمن هذا مع شخص تثق به، ويمكنه الدفع دون حساب في Wassla.';

  @override
  String get guestShareAction => 'مشاركة الرابط';

  @override
  String get guestCopyAction => 'نسخ الرابط';

  @override
  String get guestCopiedAction => 'تم النسخ';

  @override
  String get guestLinkCopied => 'تم نسخ الرابط';

  @override
  String get guestShareSubject => 'طلب دفع عبر Wassla';

  @override
  String guestShareMessage(String amount, String link) {
    return 'هل يمكنك دفع $amount مقابل توصيلي عبر Wassla؟ هذا هو الرابط الآمن: $link';
  }

  @override
  String get guestLinkLabel => 'رابط الدفع';

  @override
  String get guestStatusReady => 'رابط الدفع جاهز';

  @override
  String guestStatusExpiresOn(String when) {
    return 'ينتهي في $when';
  }

  @override
  String get guestStatusPaying => 'هناك من يدفع الآن';

  @override
  String get guestStatusPayingBody =>
      'ستتحدّث هذه الصفحة تلقائيًا فور إتمام الدفع.';

  @override
  String get guestStatusExpired => 'انتهت صلاحية رابط الدفع هذا';

  @override
  String get guestStatusRevoked => 'رابط الدفع هذا لم يعد فعّالًا';

  @override
  String get guestStatusNewLinkBody =>
      'أنشئ رابطًا جديدًا إن كان على شخص آخر أن يدفع.';

  @override
  String get guestStatusHidden => 'رابطك السابق لا يزال يعمل';

  @override
  String get guestStatusHiddenBody =>
      'لأسباب أمنية لا يمكن عرضه مرة أخرى. أنشئ رابطًا جديدًا لمشاركته، وسيتوقف الرابط السابق عندها عن العمل.';

  @override
  String get guestStatusClosed => 'لم يعد بالإمكان دفع هذا المبلغ عبر رابط.';

  @override
  String get guestCreateNewAction => 'إنشاء رابط دفع جديد';

  @override
  String get guestMoreActions => 'خيارات إضافية';

  @override
  String get guestRevokeAction => 'إلغاء الرابط';

  @override
  String get guestRevokeConfirmTitle => 'إلغاء رابط الدفع هذا؟';

  @override
  String get guestRevokeConfirmBody =>
      'لن يتمكن أي شخص لديه هذا الرابط من الدفع به. يمكنك إنشاء رابط جديد لاحقًا.';

  @override
  String get guestRevokeKeep => 'الإبقاء على الرابط';

  @override
  String get guestRevokedDone => 'تم إلغاء الرابط';

  @override
  String get guestPaidTitle => 'تم استلام الدفع';

  @override
  String guestPaidBody(String amount) {
    return 'تمّ دفع $amount.';
  }

  @override
  String get guestPaidBodyPlain => 'تمّ استلام الدفع.';

  @override
  String get guestErrorLoad =>
      'تعذّر تحميل رابط الدفع. تحقّق من اتصالك وأعد المحاولة.';

  @override
  String get guestErrorBusy =>
      'هناك من يدفع برابطك الحالي الآن. أعد المحاولة بعد أن ينتهي.';

  @override
  String get guestErrorRevokeBusy =>
      'هناك من يدفع بهذا الرابط الآن، لذا لا يمكن إلغاؤه.';

  @override
  String get guestErrorRevoke => 'تعذّر إلغاء الرابط. أعد المحاولة.';

  @override
  String get guestErrorShare =>
      'المشاركة غير متاحة حاليًا. انسخ الرابط بدلًا من ذلك.';

  @override
  String get guestPurposeDeposit => 'عربون طلبك';

  @override
  String get guestPurposeRemaining => 'المبلغ المتبقي للتوصيل';

  @override
  String get guestPurposeDelivery => 'دفع التوصيل';

  @override
  String get guestPurposeBoost => 'دفع التعزيز';

  @override
  String get guestPurposeOther => 'دفعة عبر Wassla';

  @override
  String get guestPayingNowTitle => 'شخص آخر يدفع هذا المبلغ الآن';

  @override
  String get guestPayingNowBody =>
      'فتح هذا الشخص رابط الدفع الخاص بك. ستتحدّث الصفحة فور إتمام الدفع.';

  @override
  String get guestPayPurposeDeposit => 'عربون لطلب توصيل';

  @override
  String get guestPayPurposeDelivery => 'دفع مقابل توصيل';

  @override
  String get guestPayPurposeBoost => 'مكافأة إضافية لتوصيل';

  @override
  String get guestPayHandoff =>
      'ستُكمل الدفع على الصفحة الآمنة لشريك الدفع لدينا. لا تطّلع Wassla على بيانات بطاقتك أبدًا.';

  @override
  String get paymentSuccessAmountPaid => 'المبلغ المدفوع';

  @override
  String get paymentSuccessViewRequestAction => 'عرض الطلب';

  @override
  String get paymentSuccessViewDeliveryAction => 'عرض التوصيل';

  @override
  String get boostBreakdownTitle => 'تكلفة التعزيز';

  @override
  String get boostTravelerBonusLabel => 'يُضاف إلى مكافأة المسافر';

  @override
  String get boostYourCostLabel => 'تدفع مقابل التعزيز';

  @override
  String get boostAddsOnTop =>
      'يُضاف التعزيز فوق مكافأة التوصيل التي عرضتها بالفعل. مكافأة أساسية + تعزيز هو ما يستلمه المسافر.';

  @override
  String get boostEstimateNotice =>
      'تقدير حتى تحفظ. تؤكّد Wassla المبالغ النهائية.';

  @override
  String boostAmountAboveMaximum(String amount) {
    return 'أقصى تعزيز ممكن هو $amount';
  }

  @override
  String get boostHistoryReasonSenderSet => 'أضفت تعزيزًا';

  @override
  String get boostHistoryReasonSenderIncreased => 'رفعت قيمة التعزيز';

  @override
  String get boostHistoryReasonSenderDecreased => 'خفّضت قيمة التعزيز';

  @override
  String get boostHistoryReasonSenderRemoved => 'أزلت التعزيز';

  @override
  String get boostHistoryReasonFrozen => 'تم تثبيته عند الاتفاق على التوصيل';

  @override
  String get boostHistoryReasonConsumed => 'مُدرج في دفعة التوصيل';

  @override
  String get boostHistoryReasonReleased => 'أُعيد عندما لم تكتمل المطابقة';

  @override
  String get boostHistoryReasonRequestClosed => 'انتهى بانتهاء الطلب';

  @override
  String get boostHistoryReasonOther => 'تم تحديث التعزيز';

  @override
  String get guestPaymentLinkFailed => 'تعذّر إنشاء رابط الدفع. حاول مرة أخرى.';

  @override
  String findTravelersCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count مسافر',
      many: '$count مسافرًا',
      few: '$count مسافرين',
      two: 'مسافران',
      one: 'مسافر واحد',
      zero: 'لا مسافرين',
    );
    return '$_temp0';
  }

  @override
  String get findTravelersIneligibleUnknown =>
      'لا يمكن مطابقة هذا الطلب في الوقت الحالي.';

  @override
  String get findTravelersPayDeposit => 'ادفع العربون';

  @override
  String findTravelersDepartureLabel(String when) {
    return 'المغادرة $when';
  }

  @override
  String findTravelersArrivalLabel(String when) {
    return 'الوصول $when';
  }

  @override
  String get findTravelersTrustTitle => 'عمليات تحقق أجرتها Wassla';

  @override
  String get offerBaseRewardLabel => 'مكافأة التوصيل الأساسية';

  @override
  String offerBoostAddedOnTop(String amount) {
    return 'يُضاف تعزيزك البالغ $amount فوق هذا المبلغ.';
  }

  @override
  String get deliveriesOpenOffersSection => 'العروض الجارية';

  @override
  String get journeyPostNew => 'انشر رحلة';

  @override
  String depositBelowMinimum(String amount) {
    return 'أقل عربون هو $amount';
  }

  @override
  String depositAboveMaximum(String amount) {
    return 'هذا أكثر من المبلغ الكامل البالغ $amount';
  }

  @override
  String offerBoostIncludedTraveler(String amount) {
    return 'يشمل تعزيز المُرسِل البالغ $amount. يُثبَّت المجموع عند قبولك.';
  }

  @override
  String offerBoostIncludedSender(String amount) {
    return 'يشمل تعزيزك البالغ $amount، ويُثبَّت عند قبول هذا العرض. تعديل التعزيز قبل ذلك يُحدِّث هذا العرض.';
  }

  @override
  String offerSenderBoostAddedOnTop(String amount) {
    return 'يُضاف تعزيز المُرسِل البالغ $amount فوق هذا المبلغ.';
  }

  @override
  String offerHistoryBaseReward(String title, String amount) {
    return '$title: المكافأة الأساسية $amount';
  }

  @override
  String get moneyTotalExcludingBoost => 'المجموع قبل أي تعزيز';

  @override
  String get staleOfferEconomicsChanged =>
      'تغيّرت مبالغ هذا العرض. راجع المبالغ الجديدة قبل القبول.';

  @override
  String get offerEconomicsUpdated => 'تم تحديث العرض. هذه أحدث المبالغ.';

  @override
  String get payResultAlreadyCompleteTitle => 'هذا الدفع مكتمل بالفعل';

  @override
  String get payResultCheckingTitle => 'نتحقّق من دفعك';

  @override
  String get payResultCheckingBody =>
      'إن أكملت الدفع فسيظهر هنا خلال لحظات. لا داعي للدفع مرة أخرى.';

  @override
  String get payResultStillCheckingTitle => 'ما زلنا نتحقّق من دفعك';

  @override
  String get payResultStillCheckingBody =>
      'يستغرق الأمر وقتًا أطول من المعتاد. إن تمّ الدفع فسيظهر هنا، ولن يُقتطع المبلغ مرتين.';

  @override
  String get payResultBackToPayment => 'العودة إلى الدفع';

  @override
  String get payResultCancelledTitle => 'أُلغي الدفع';

  @override
  String get payResultCancelledBody =>
      'لم يُسجَّل أي دفع مكتمل. يمكنك إعادة المحاولة متى شئت.';

  @override
  String payResultSomeoneElsePaid(String amount) {
    return 'دفع شخص آخر $amount عن هذا الدفع.';
  }

  @override
  String get payResultRequestPublished => 'طلبك منشور الآن';

  @override
  String get payResultDepositNext => 'ابحث عن مسافر في طريقك وأرسل إليه عرضًا.';

  @override
  String get payResultPaidInFull => 'مدفوع بالكامل';

  @override
  String get payResultDepositCoversTotal =>
      'يغطي هذا إجمالي التوصيل الحالي. إن أضفت لاحقًا تعزيزًا أو رفعت المكافأة، فلن يُطلب منك سوى الفرق.';

  @override
  String get payResultPaidNow => 'المدفوع الآن';

  @override
  String get payResultDeliveryTotal => 'إجمالي التوصيل';

  @override
  String get payResultRemaining => 'المتبقّي';

  @override
  String payResultRemainingNote(String amount) {
    return 'ادفع المبلغ المتبقّي $amount لتأكيد التوصيل. لا يمكن للمسافر استلام الطرد قبل ذلك.';
  }

  @override
  String get payResultDealNext =>
      'تُحتجز الأموال إلى حين التسليم. اتّبع خطوات التوصيل للمتابعة.';

  @override
  String get payResultNextTitle => 'الخطوة التالية';

  @override
  String get payResultBackHome => 'العودة إلى الرئيسية';

  @override
  String payResultPayRemaining(String amount) {
    return 'ادفع المتبقّي $amount';
  }

  @override
  String a11yPaymentResultAmount(String label, String amount, String purpose) {
    return '$label: $amount. $purpose';
  }

  @override
  String get guestPayHandoffTitle => 'أكمل الدفع على صفحة الدفع';

  @override
  String get guestPayHandoffBody =>
      'أكمل الدفع على الصفحة الآمنة لشريك الدفع لدينا. ستُظهر لك تلك الصفحة النتيجة، وسيراها الشخص الذي طلب منك الدفع في Wassla.';

  @override
  String get payResultDepositCredited =>
      'يُحتسب هذا العربون من إجمالي التوصيل عند قبول مسافر.';

  @override
  String get alertsTitle => 'تنبيهات المسارات';

  @override
  String get alertsIntro =>
      'نرسل إشعارًا واحدًا على الأكثر لكل تنبيه كل بضع ساعات.';

  @override
  String get alertsEmptyTitle => 'لا توجد تنبيهات بعد';

  @override
  String get alertsEmptyBody =>
      'احصل على إشعار عند ظهور رحلة أو طرد على مسار يهمّك.';

  @override
  String get alertAdd => 'إضافة تنبيه';

  @override
  String get alertAddTitle => 'تنبيه مسار جديد';

  @override
  String get alertAddSubtitle => 'سنُشعرك عند ظهور جديد على هذا المسار.';

  @override
  String get alertCreate => 'إنشاء التنبيه';

  @override
  String get alertPickCity => 'اختر مدينة';

  @override
  String get alertWatchLabel => 'تابع';

  @override
  String get alertWatchesTrips => 'رحلات جديدة';

  @override
  String get alertWatchesRequests => 'طرود جديدة';

  @override
  String alertFollowing(String name) {
    return 'متابعة $name';
  }

  @override
  String alertRemoveA11y(String route) {
    return 'حذف التنبيه الخاص بـ $route';
  }

  @override
  String get alertRemoved => 'تم حذف التنبيه';

  @override
  String get alertSwitchLabel => 'نبّهني بخصوص هذا المسار';

  @override
  String get alertTurnedOn => 'تم تفعيل التنبيه';

  @override
  String get alertTurnedOff => 'تم إيقاف التنبيه';

  @override
  String get alertLimitReached =>
      'وصلت إلى الحد الأقصى من التنبيهات النشطة. احذف تنبيهًا لإضافة آخر.';

  @override
  String get alertSameCity => 'اختر مدينتين مختلفتين.';

  @override
  String get alertSelf => 'لا يمكنك متابعة نفسك.';

  @override
  String get browseTripsTitle => 'رحلات تنطلق قريبًا';

  @override
  String get browseRequestsTitle => 'طرود تبحث عن مسافر';

  @override
  String get browseTripsEmptyTitle => 'لا توجد رحلات حاليًا';

  @override
  String get browseTripsEmptyBody =>
      'تظهر الرحلات هنا بمجرد نشرها من المسافرين.';

  @override
  String get browseTripsEmptyAction => 'أرسل طردًا';

  @override
  String get browseRequestsEmptyTitle => 'لا توجد طرود مفتوحة حاليًا';

  @override
  String get browseRequestsEmptyBody =>
      'تظهر الطرود هنا بمجرد نشرها من المُرسِلين.';

  @override
  String get browseRequestsEmptyAction => 'أضف رحلة';

  @override
  String get browseNoMatchTitle => 'لا توجد نتائج';

  @override
  String get browseNoMatchBody =>
      'لا شيء يطابق عوامل التصفية. جرّب مدنًا أخرى أو تاريخًا آخر.';

  @override
  String get browseClearFilters => 'مسح عوامل التصفية';

  @override
  String browseClearFilter(String label) {
    return 'مسح $label';
  }

  @override
  String get browseFilterFrom => 'من';

  @override
  String get browseFilterTo => 'إلى';

  @override
  String get browseFilterDate => 'ابتداءً من';

  @override
  String get countryAlgeria => 'الجزائر';

  @override
  String get countryFrance => 'فرنسا';

  @override
  String get countrySpain => 'إسبانيا';

  @override
  String get countryGermany => 'ألمانيا';

  @override
  String get corridorAll => 'كل المسارات';

  @override
  String corridorA11y(String from, String to) {
    return 'من $from إلى $to';
  }

  @override
  String get discoveryListingsOffTitle => 'غير متاح حاليًا';

  @override
  String get discoveryListingsOff =>
      'تصفّح الرحلات والطرود متوقف مؤقتًا. تفقّد لاحقًا.';

  @override
  String get discoveryProfilesOffTitle => 'غير متاح حاليًا';

  @override
  String get discoveryProfilesOff =>
      'الملفات العامة متوقفة مؤقتًا. تفقّد لاحقًا.';

  @override
  String get discoveryProfileGone => 'هذا الملف لم يعد متاحًا.';

  @override
  String get discoveryShowingEarlier => 'نعرض ما حمّلناه سابقًا';

  @override
  String get requestCarryAction => 'يمكنني حمله';

  @override
  String get carryExplain =>
      'أخبر المُرسِل أنك تستطيع حمل الطرد. إبداء الاستعداد لا يحدّد سعرًا ولا يحجز الطرد. يقرّر المُرسِل الخطوة التالية.';

  @override
  String get carryChooseTrip => 'أي رحلة؟';

  @override
  String get carryChooseTripHint => 'اختر الرحلة التي ستحمله عليها.';

  @override
  String get carryPublishTrip => 'أضف رحلة لحمله';

  @override
  String get carrySentTitle => 'تم إشعار المُرسِل';

  @override
  String get carryAlreadySentTitle => 'أُرسل مسبقًا';

  @override
  String get carrySentBody =>
      'أرسلنا إلى المُرسِل إشعارًا واحدًا بأنك تستطيع حمل الطرد. يمكنه الاطلاع على رحلتك وتقديم عرض للتوصيل. لم يُحجز شيء.';

  @override
  String get carryIncompatible => 'هذا الطرد لا يناسب تلك الرحلة:';

  @override
  String get carryDailyCap => 'بلغت الحد اليومي لـ «يمكنني حمله». حاول غدًا.';

  @override
  String get carryRequestGone => 'هذا الطرد لم يعد مفتوحًا.';

  @override
  String get carryJourneyGone => 'هذه الرحلة لم تعد متاحة.';

  @override
  String get rejectCapacity => 'لا توجد مساحة كافية على كل مرحلة.';

  @override
  String get rejectDeadline => 'سيصل بعد الموعد النهائي.';

  @override
  String get rejectTiming => 'التواريخ غير متوافقة.';

  @override
  String get rejectRoute => 'الالتفاف عن المسار كبير جدًا.';

  @override
  String get rejectClosed => 'أحدهما لم يعد مفتوحًا.';

  @override
  String get rejectVerification => 'لم يكتمل توثيق المسافر.';

  @override
  String get rejectItem => 'لا يمكن نقل هذا الغرض في هذه الرحلة.';

  @override
  String get rejectGeneric => 'الرحلة والطرد غير متطابقين.';

  @override
  String get focusTripMissingTitle => 'هذه الرحلة لا تناسب هذا الطرد';

  @override
  String get focusTripMissingBody =>
      'هذه الرحلة غير موجودة في قائمة المسافرين المناسبين.';

  @override
  String tripLeaves(String date) {
    return 'تنطلق في $date';
  }

  @override
  String get tripArrives => 'الوصول';

  @override
  String get tripSpace => 'المساحة المتاحة';

  @override
  String get tripCapacityUnder5 => 'أقل من 5 كغ متاحة';

  @override
  String get tripCapacity5to10 => 'من 5 إلى 10 كغ متاحة';

  @override
  String get tripCapacity10to20 => 'من 10 إلى 20 كغ متاحة';

  @override
  String get tripCapacity20Plus => '20 كغ أو أكثر متاحة';

  @override
  String get tripPreviewSubtitle => 'أنت من يقترح أولًا. لا يُحجز شيء من هنا.';

  @override
  String get tripChooseParcel => 'اختر أحد طرودك';

  @override
  String get tripPostForRoute => 'انشر طردًا لهذا المسار';

  @override
  String requestCardDeadline(String date) {
    return 'قبل $date';
  }

  @override
  String requestCardFrom(String name) {
    return 'من $name';
  }

  @override
  String get requestOfferedReward => 'المكافأة المعروضة';

  @override
  String publicRatingA11y(String rating) {
    return 'التقييم $rating من 5';
  }

  @override
  String get profileNoUsualRoutes => 'لا توجد مسارات معتادة';

  @override
  String get homeMatchesTitle => 'مطابقات لك';

  @override
  String get homeMatchesEmptyTitle => 'لا توجد مطابقات بعد';

  @override
  String get homeMatchesSenderNone =>
      'انشر طردًا وسيظهر هنا المسافرون المناسبون له.';

  @override
  String get homeMatchesSenderWaiting =>
      'لا يوجد مسافر مناسب لطرودك المفتوحة بعد. سيظهر هنا فور وجوده.';

  @override
  String get homeMatchesTravelerNone =>
      'أضف رحلة وستظهر هنا الطرود المناسبة لها.';

  @override
  String get homeMatchesTravelerWaiting =>
      'لا يوجد طرد مناسب لرحلاتك بعد. سيظهر هنا فور وجوده.';

  @override
  String get homeTripsTitle => 'رحلات تنطلق قريبًا';

  @override
  String get homeTripsEmptyBody => 'ستظهر هنا الرحلات التي توشك على الانطلاق.';

  @override
  String get homeRequestsTitle => 'طرود تبحث عن مسافر';

  @override
  String get homeRequestsEmptyBody => 'ستظهر هنا الطرود التي تبحث عن مسافر.';

  @override
  String get homeListingsEmptyTitle => 'لا شيء معروضًا بعد';

  @override
  String get homeListingsEmptyRouteTitle => 'لا شيء على هذا المسار بعد';

  @override
  String get homePeopleSenderTitle => 'مسافرون على Wassla';

  @override
  String get homePeopleTravelerTitle => 'مرسلون على Wassla';

  @override
  String get homePeopleEmptyTitle => 'لا توجد ملفات عامة بعد';

  @override
  String get homePeopleEmptyBody =>
      'سيظهر هنا الأشخاص الذين يختارون عرض ملف عام.';

  @override
  String get optInTitle => 'كن ظاهرًا على Wassla';

  @override
  String get optInBody =>
      'اسمح للمرسلين والمسافرين بالعثور عليك. يظهر فقط اسمك الأول وشارات الثقة والمسارات التي تختارها.';

  @override
  String get optInPreviewLabel => 'هذا ما سيراه الآخرون';

  @override
  String get optInShow => 'إظهار ملفي';

  @override
  String get optInNotNow => 'ليس الآن';

  @override
  String get personTitle => 'الملف';

  @override
  String get personGoneTitle => 'الملف غير متاح';

  @override
  String get personUsualRoutes => 'المسارات المعتادة';

  @override
  String personAlertHint(String name) {
    return 'فعّل تنبيهًا لتعرف عندما ينشر $name على مسار.';
  }

  @override
  String personNoUsualRoutes(String name) {
    return 'لم يضف $name مسارات معتادة.';
  }

  @override
  String personTrips(String name) {
    return 'رحلات $name';
  }

  @override
  String personRequests(String name) {
    return 'طرود $name';
  }

  @override
  String personNothingListed(String name) {
    return 'ليس لدى $name رحلات قائمة أو طرود مفتوحة حاليًا.';
  }

  @override
  String get publicProfileTitle => 'الملف العام';

  @override
  String get publicProfileIntro =>
      'يتيح الملف العام للمرسلين والمسافرين العثور عليك ومتابعة مساراتك. وهو متوقف ما لم تفعّله، ويمكنك إيقافه في أي وقت.';

  @override
  String get publicShownTitle => 'ما يراه الآخرون';

  @override
  String get publicShownFirstName => 'اسمك الأول';

  @override
  String get publicShownTrust => 'هل هويتك موثّقة، وتقييمك، وتوصيلاتك المكتملة';

  @override
  String get publicShownMemberSince => 'شهر وسنة انضمامك';

  @override
  String get publicShownRoutes => 'المسارات المعتادة التي تختارها';

  @override
  String get publicNeverTitle => 'لا يظهر أبدًا';

  @override
  String get publicNeverContact =>
      'اسم العائلة أو البريد الإلكتروني أو رقم الهاتف';

  @override
  String get publicNeverPlaces => 'عنوان أو موقع دقيق';

  @override
  String get publicShowSwitch => 'إظهار ملفي العام';

  @override
  String get publicSwitchOn => 'يمكن للآخرين العثور عليك.';

  @override
  String get publicSwitchOff => 'لا يستطيع الآخرون العثور عليك.';

  @override
  String get publicProfileOn => 'تم تفعيل ملفك العام';

  @override
  String get publicHiddenNotice => 'ملفك غير ظاهر للآخرين حاليًا.';

  @override
  String get publicRoutesTitle => 'المسارات المعتادة';

  @override
  String get publicRoutesHint =>
      'حتى ثلاثة مسارات تسلكها أو ترسل عليها كثيرًا.';

  @override
  String get publicRoutesLimit => 'أضفت الحد الأقصى وهو ثلاثة مسارات.';

  @override
  String get publicRouteAdd => 'إضافة مسار معتاد';

  @override
  String get publicRouteFrom => 'المسار المعتاد: من';

  @override
  String get publicRouteTo => 'المسار المعتاد: إلى';

  @override
  String publicRouteRemove(String route) {
    return 'حذف $route';
  }

  @override
  String get publicRouteDuplicate => 'هذا المسار موجود بالفعل في ملفك.';

  @override
  String get publicPreviewTitle => 'بطاقتك العامة';

  @override
  String get publicPreviewVisible => 'هذا ما يراه الآخرون الآن.';

  @override
  String get publicPreviewHidden => 'هذا ما سيراه الآخرون إن فعّلته.';

  @override
  String get notificationRouteAlert => 'جديد على مسار تتابعه';

  @override
  String get notificationTravelerInterested => 'مسافر يستطيع حمل طردك';

  @override
  String get journeyModeSea => 'باخرة';

  @override
  String get routeSeaMode => 'باخرة';

  @override
  String get routeSeaSwitchedOff => 'رحلات الباخرة متوقفة حاليًا.';

  @override
  String get routeSeaTicketNote =>
      'تحتاج رحلة الباخرة إلى التحقق من تذكرتك قبل نشر الرحلة. تضيف التذكرة بعد الحفظ.';

  @override
  String get routeSeaRefusedSwitchedOff =>
      'رحلات الباخرة متوقفة الآن. اختر وسيلة أخرى لهذا الجزء.';

  @override
  String get routeSeaRefusedNoCrossing =>
      'لا يوجد خط باخرة بين هاتين المدينتين في هذا الاتجاه حاليًا.';

  @override
  String get routeSeaRefusedNotPort =>
      'تربط الباخرة بين مدن الموانئ. اختر المدينة لا المطار عند كل طرف من هذا الجزء.';

  @override
  String get routeSeaLinesFailedTitle => 'تعذّر تحميل خطوط الباخرة';

  @override
  String get routeSeaLinesFailedBody =>
      'الرحلات الجوية والبرية تعمل كالمعتاد. أعد المحاولة لإضافة رحلة باخرة.';

  @override
  String get routeErrorSeaRefused =>
      'لا يمكن استخدام رحلة باخرة على مسارك الآن. السبب موضح عند ذلك الجزء.';

  @override
  String get journeyErrorStopInvalid =>
      'خيارات التسليم في إحدى محطاتك غير صالحة. راجع خيارات كل محطة.';

  @override
  String get routeCapacityMore => 'خيارات سعة إضافية';

  @override
  String get routeCapacityMoreHelp => 'اختياري. اترك الحقل فارغًا لعدم وضع حد.';

  @override
  String get routeVolumeLabel => 'الحجم (لتر)';

  @override
  String get routeParcelsLabel => 'عدد الطرود';

  @override
  String get routeVolumeInvalid =>
      'أدخل عددًا صحيحًا من اللترات بين 1 و200,000.';

  @override
  String get routeParcelsInvalid =>
      'أدخل عددًا صحيحًا من الطرود بين 1 و10,000.';

  @override
  String get routeHandoverAction => 'خيارات التسليم';

  @override
  String get routeHandoverBoth => 'استلام وتسليم الطرود';

  @override
  String get routeHandoverPickups => 'استلام الطرود فقط';

  @override
  String get routeHandoverDropoffs => 'تسليم الطرود فقط';

  @override
  String get routeHandoverNone => 'لا تسليم هنا';

  @override
  String routeHandoverSheetTitle(String stop) {
    return 'التسليم في $stop';
  }

  @override
  String get routeHandoverPickupLabel => 'قبول الاستلام هنا';

  @override
  String get routeHandoverPickupHelp =>
      'يمكن للمرسل تسليمك طردًا في هذه المحطة.';

  @override
  String get routeHandoverDropoffLabel => 'قبول التسليم هنا';

  @override
  String get routeHandoverDropoffHelp =>
      'يمكنك تسليم الطرد لمستلمه في هذه المحطة.';

  @override
  String get routeHandoverWindowTitle => 'فترة زمنية';

  @override
  String get routeHandoverWindowHelp =>
      'اختياري. متى يمكنك اللقاء في هذه المحطة.';

  @override
  String get routeHandoverWindowFrom => 'من';

  @override
  String get routeHandoverWindowTo => 'حتى';

  @override
  String get routeHandoverWindowClear => 'إزالة الفترة الزمنية';

  @override
  String get routeHandoverNoteLabel => 'ملاحظة';

  @override
  String get routeHandoverNoteHint => 'مثال: نلتقي في المقهى قرب محطة الباخرة.';

  @override
  String get routeHandoverNoteSeen =>
      'لا يرى هذه الملاحظة سواك إلى أن تُدفع تكلفة توصيل يمر بهذه المحطة. عندها يراها مُرسِل الطرد أيضًا.';

  @override
  String get routeWindowIncomplete =>
      'حدّد البداية والنهاية معًا أو أزل الفترة.';

  @override
  String get routeWindowOrder => 'يجب أن تنتهي الفترة بعد بدايتها.';

  @override
  String get routeWindowOutside =>
      'يجب أن تقع الفترة بين وصولك إلى هذه المحطة ومغادرتك لها.';

  @override
  String get routeCarryTitle => 'ما تحمله';

  @override
  String get routeCarryHelp =>
      'أوقف ما لن تحمله. لا يجدك المُرسِلون إلا للطرود التي تقبلها.';

  @override
  String get routeCarryFragile => 'الأشياء القابلة للكسر';

  @override
  String get routeCarryLastOne => 'يجب أن يبقى نوع واحد على الأقل مفعّلًا.';

  @override
  String get journeyPauseAction => 'إيقاف الرحلة مؤقتًا';

  @override
  String get journeyPauseConfirmTitle => 'هل تريد إيقاف هذه الرحلة مؤقتًا؟';

  @override
  String get journeyPauseConfirmBody =>
      'يتوقف المُرسِلون عن العثور عليها ولا يمكن لأحد تقديم عرض جديد عليها. تستمر التوصيلات المدفوعة، ولا يمكن قبول عرض معلّق قبل الاستئناف.';

  @override
  String get journeyPaused => 'تم إيقاف الرحلة مؤقتًا.';

  @override
  String get journeyResumeAction => 'استئناف الرحلة';

  @override
  String get journeyResumed => 'تم استئناف الرحلة.';

  @override
  String get journeyPausedBannerTitle => 'هذه الرحلة متوقفة مؤقتًا';

  @override
  String get journeyPausedBannerBody =>
      'لا يجده المُرسِلون ولا يمكن قبول العروض عليه. تستمر التوصيلات المدفوعة كالمعتاد.';

  @override
  String get journeyPausedStaffBody =>
      'أوقفت Wassla هذه الرحلة مؤقتًا. تواصل مع الدعم لاستئنافها.';

  @override
  String get journeyErrorNotPausable =>
      'لا يمكن إيقاف هذه الرحلة مؤقتًا في حالتها الحالية.';

  @override
  String get journeyErrorPausedByStaff =>
      'أوقفت Wassla هذه الرحلة، لذلك لا يستطيع استئنافها إلا الدعم.';

  @override
  String journeyCapacityVolumeValue(int litres) {
    return '$litres لتر';
  }

  @override
  String journeyCapacityParcelsValue(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count طرد',
      many: '$count طردًا',
      few: '$count طرود',
      two: 'طردان',
      one: 'طرد واحد',
      zero: 'لا طرود',
    );
    return '$_temp0';
  }

  @override
  String get journeyHandoverTitle => 'التسليم في محطاتك';

  @override
  String journeyHandoverWindow(String from, String to) {
    return 'بين $from و$to';
  }

  @override
  String get journeyCarryTitle => 'ما تحمله';

  @override
  String get journeyCarryAll => 'يقبل كل أنواع الأشياء';

  @override
  String journeyCarryRefuses(String items) {
    return 'لا يحمل: $items';
  }

  @override
  String get journeyCarryNoFragile => 'لا أشياء قابلة للكسر';

  @override
  String get proofExplainerSea =>
      'ارفع تذكرة الباخرة أو تأكيد الحجز. نتحقق منها قبل أن تتمكن رحلتك من استقبال الطرود.';

  @override
  String get proofChecklistTitle => 'الصورة الجيدة تُظهر';

  @override
  String get proofChecklistFlight => 'اسمك ورقم الرحلة والتاريخ والمطارين.';

  @override
  String get proofChecklistSea => 'اسمك وشركة الباخرة والتاريخ والميناءين.';

  @override
  String get rejectSea => 'خط باخرة في هذه الرحلة غير متاح حاليًا.';

  @override
  String get rejectPaused => 'أوقف المسافر هذه الرحلة مؤقتًا.';

  @override
  String get rejectHandover =>
      'لا يسلّم المسافر الطرود في الأماكن التي تحتاجها.';

  @override
  String get rejectNotAccepted => 'لا يقبل المسافر هذا النوع من الأشياء.';

  @override
  String get rejectVolume => 'لا توجد مساحة كافية لحجم هذا الطرد.';

  @override
  String get rejectParcelSlots => 'لم يتبقَّ للمسافر مكان لطرد آخر.';

  @override
  String get findTravelersSeaProofApproved => 'تم التحقق من تذكرة الباخرة';

  @override
  String get findTravelersCaveatVolume =>
      'يحدّد هذا المسافر الحجم وطلبك بلا أبعاد، فلم نستطع التحقق من أن طردك يتسع. هو من يقرر عند القبول.';

  @override
  String get staleJourneyPaused =>
      'هذه الرحلة متوقفة مؤقتًا، فلا يمكن قبول أي شيء عليها قبل استئنافها.';

  @override
  String get dealHandoverTitle => 'أين ومتى تلتقيان';

  @override
  String get dealHandoverPickup => 'الاستلام';

  @override
  String get dealHandoverDropoff => 'التسليم';

  @override
  String get journeyPriceTitle => 'سعرك';

  @override
  String get journeyPriceOptional => 'اختياري';

  @override
  String get journeyPriceNote =>
      'يرى المُرسِلون سعرك مضافًا إليه رسوم Wassla. ويبقى الحد الأدنى لـ Wassla لكل طرد ساريًا.';

  @override
  String get journeyPricePerKgLabel => 'السعر لكل كغ';

  @override
  String get journeyPriceMinimumLabel => 'الحد الأدنى لكل طرد';

  @override
  String get journeyPriceErrorBoth => 'أدخل المبلغين معًا أو اتركهما فارغين.';

  @override
  String journeyPriceErrorMaximum(String amount) {
    return 'الحد الأقصى $amount.';
  }

  @override
  String get journeyPriceErrorTooHigh => 'هذا المبلغ أعلى مما تسمح به Wassla.';

  @override
  String get journeyPriceDisabled => 'تحديد السعر غير متاح حاليًا.';

  @override
  String get journeyPriceNotEditable =>
      'لم يعد بالإمكان تغيير السعر في هذه الرحلة.';

  @override
  String get journeyPriceNone =>
      'لم يُحدَّد سعر. يقترح المُرسِلون مبلغهم بأنفسهم.';

  @override
  String get journeyPriceSet => 'حدّد سعرًا';

  @override
  String get journeyPriceChange => 'تغيير';

  @override
  String get journeyPriceSave => 'احفظ السعر';

  @override
  String get journeyPriceRemove => 'إزالة السعر';

  @override
  String get journeyPriceSaved => 'تم حفظ السعر.';

  @override
  String get journeyPriceCleared => 'تمت إزالة السعر.';

  @override
  String get journeyPriceAppliesToNew =>
      'يسري السعر الجديد على العروض المقدَّمة من الآن فصاعدًا. وتحتفظ العروض والصفقات القائمة بسعرها.';

  @override
  String journeyPricePerKgValue(String amount) {
    return '$amount لكل كغ';
  }

  @override
  String journeyPriceMinimumValue(String amount) {
    return 'الحد الأدنى $amount لكل طرد';
  }

  @override
  String tripPriceFrom(String perKg, String minimum) {
    return 'ابتداءً من $perKg لكل كغ، والحد الأدنى $minimum';
  }

  @override
  String get findTravelersSortPrice => 'الأقل سعرًا';

  @override
  String findTravelersListedPrice(String amount) {
    return '$amount لهذا الطرد';
  }

  @override
  String get offerListedLabel => 'سعره لهذا الطرد';

  @override
  String offerSendListed(String amount) {
    return 'اعرض $amount';
  }

  @override
  String get offerDifferentAmount => 'اعرض مبلغًا آخر';

  @override
  String get offerBelowListedNote =>
      'هذا أقل من سعره، لذا قد يرفض المسافر أو يقدّم عرضًا مقابلًا.';

  @override
  String get offerUseListed => 'استخدم سعره';

  @override
  String get tripPrice => 'السعر';

  @override
  String get trackingNumberLabel => 'رقم التتبع';

  @override
  String get trackingNumberCopy => 'نسخ رقم التتبع';

  @override
  String get trackingNumberCopied => 'تم نسخ رقم التتبع';

  @override
  String get progressTitle => 'تقدّم الرحلة';

  @override
  String get progressIntro =>
      'أخبر المُرسِلين كيف تسير رحلتك. يظهر لهم أنك أرسلت التحديث، ولا يؤثر في أي دفعة.';

  @override
  String get progressActionAtPort => 'أنا في الميناء';

  @override
  String get progressActionDeparted => 'لقد انطلقتُ';

  @override
  String get progressActionArrived => 'لقد وصلتُ';

  @override
  String get progressReportedAtPort => 'في الميناء';

  @override
  String get progressReportedDeparted => 'انطلقتَ';

  @override
  String get progressReportedArrived => 'وصلتَ';

  @override
  String progressAvailableFrom(String time) {
    return 'يمكنك الإبلاغ عن هذا ابتداءً من $time.';
  }

  @override
  String get progressNeedsNetwork =>
      'يتطلب اتصالًا بالإنترنت. لا يُحفظ شيء لوقت لاحق.';

  @override
  String get progressUndo => 'تراجع';

  @override
  String get progressUndoHint => 'يمكنك التراجع عن التحديث خلال 10 دقائق.';

  @override
  String get progressSent => 'تمت مشاركة التحديث مع المُرسِلين.';

  @override
  String get progressUndone => 'تمت إزالة التحديث.';

  @override
  String get progressErrorOffline =>
      'لا يوجد اتصال، لذلك لم يُرسل تحديثك. حاول مرة أخرى عند عودة الاتصال.';

  @override
  String get progressErrorTooEarly =>
      'الوقت مبكر جدًا للإبلاغ عن هذا. يفتح الإبلاغ قبل الموعد المخطط بـ 24 ساعة.';

  @override
  String get progressErrorOutOfOrder =>
      'هذه الخطوة ليست التالية. اسحب للأسفل للتحديث.';

  @override
  String get progressErrorNotReportable =>
      'لا يمكن لهذه الرحلة استقبال تحديثات الآن.';

  @override
  String get progressErrorUndoClosed =>
      'انتهت الدقائق العشر المتاحة للتراجع عن هذا التحديث.';

  @override
  String get progressErrorHasFollowup =>
      'يعتمد عليه تحديث لاحق، لذلك لا يمكن التراجع عنه.';

  @override
  String progressQuestionDeparted(String place) {
    return 'هل انطلقت من $place؟';
  }

  @override
  String get progressQuestionDepartedBare => 'هل انطلقت؟';

  @override
  String progressQuestionArrived(String place) {
    return 'هل وصلت إلى $place؟';
  }

  @override
  String get progressQuestionArrivedBare => 'هل وصلت؟';

  @override
  String progressQuestionAtPort(String place) {
    return 'هل أنت في ميناء $place؟';
  }

  @override
  String get progressQuestionAtPortBare => 'هل أنت في الميناء؟';

  @override
  String get progressYesDeparted => 'نعم، انطلقتُ';

  @override
  String get progressYesArrived => 'نعم، وصلتُ';

  @override
  String get progressYesAtPort => 'نعم، أنا هنا';

  @override
  String get progressNotYet => 'ليس بعد';

  @override
  String get progressQuestionBody =>
      'المُرسِلون الذين لديهم طرد على هذه المرحلة سيرون إجابتك مع إشارة إلى أنك أبلغتَ بها.';

  @override
  String get dealProgressAtPort => 'المسافر في الميناء';

  @override
  String get dealProgressDeparted => 'المسافر انطلق';

  @override
  String get dealProgressArrived => 'المسافر وصل';

  @override
  String get dealProgressReportedBy => 'أبلغ به المسافر';

  @override
  String get notificationProgressReported => 'تحديث من المسافر';

  @override
  String get notificationLegReminder => 'كيف تسير رحلتك؟';

  @override
  String get problemsTitle => 'المشكلات المبلَّغ عنها';

  @override
  String get problemReportAction => 'الإبلاغ عن مشكلة';

  @override
  String get problemSheetTitle => 'الإبلاغ عن مشكلة';

  @override
  String get problemSheetIntro => 'ما الذي حدث في هذا التوصيل؟';

  @override
  String get problemKindSenderUnavailable => 'المُرسِل لم يحضر';

  @override
  String get problemKindTravelerNoShow => 'المسافر لم يحضر';

  @override
  String get problemKindRecipientUnavailable => 'المستلم غير متاح';

  @override
  String get problemKindParcelMismatch => 'الطرد لا يطابق الوصف';

  @override
  String get problemKindParcelDamaged => 'الطرد تالف';

  @override
  String get problemKindTripDisrupted => 'الرحلة أُلغيت أو تأخرت';

  @override
  String get problemKindCustomsDelay => 'الطرد محتجز في الجمارك';

  @override
  String get problemKindOther => 'شيء آخر';

  @override
  String get problemNoteLabel => 'ملاحظة (اختياري)';

  @override
  String get problemNoteHint => 'أضف ما قد يفيد، مثل مكان وجودك.';

  @override
  String get problemNextBody =>
      'يُبلَّغ الطرف الآخر. يراجع فريق Wassla حالات التلف وعدم المطابقة فورًا. الإبلاغ لا يلغي شيئًا ولا يسترد أي مبلغ.';

  @override
  String get problemSendAction => 'إرسال البلاغ';

  @override
  String get problemSent => 'تم إرسال البلاغ وإبلاغ الطرف الآخر.';

  @override
  String get problemReportedByYou => 'أبلغتَ عنها';

  @override
  String get problemReportedByOther => 'أبلغ عنها الطرف الآخر';

  @override
  String get problemStatusOpen => 'أُرسل';

  @override
  String get problemStatusEscalated => 'لدى فريق Wassla';

  @override
  String get problemStatusAcknowledged => 'قيد المراجعة';

  @override
  String get problemStatusClosed => 'مغلق';

  @override
  String get problemErrorOffline =>
      'لا يوجد اتصال. لم يُرسل شيء. حاول مرة أخرى عند عودة الاتصال.';

  @override
  String get problemErrorNoShowClosed =>
      'لا يمكن الإبلاغ الآن. قد لا يكون وقت التسليم قد حان، أو أن الطرد استُلم بالفعل.';

  @override
  String get problemErrorNotAllowed =>
      'لا يمكن تقديم بلاغ عن هذا التوصيل الآن.';

  @override
  String get problemErrorNoteTooLong =>
      'الملاحظة طويلة جدًا. اجعلها أقل من 1000 حرف.';

  @override
  String get noShowActionSender => 'المُرسِل لم يحضر';

  @override
  String get noShowActionTraveler => 'المسافر لم يحضر';

  @override
  String get noShowSheetIntro => 'أخبرنا إذا لم يحضر الطرف الآخر للتسليم.';

  @override
  String get noShowNextBody =>
      'سيراجع فريق Wassla البلاغ. لم يُلغَ أو يُسترد أي شيء حتى الآن.';

  @override
  String get noShowSendAction => 'إرسال إلى Wassla';

  @override
  String get noShowReportedSender => 'أبلغتَ بأن المُرسِل لم يحضر';

  @override
  String get noShowReportedTraveler => 'أبلغتَ بأن المسافر لم يحضر';

  @override
  String get noShowMessageInChat => 'مراسلة في المحادثة';

  @override
  String get noShowReplyInChat => 'الرد في المحادثة';

  @override
  String get noShowAgainstSenderTitle => 'المسافر يقول إنك لم تحضر';

  @override
  String get noShowAgainstSenderBody =>
      'إذا كان هناك سوء فهم، أخبره في المحادثة. سيراجع فريق Wassla الأمر. لم يُلغَ أو يُسترد أي شيء حتى الآن.';

  @override
  String get noShowAgainstTravelerTitle => 'المُرسِل يقول إنك لم تحضر';

  @override
  String get noShowAgainstTravelerBody =>
      'إذا كان هناك سوء فهم، أخبره في المحادثة. سيراجع فريق Wassla الأمر. لم يُلغَ أو يُسترد أي شيء حتى الآن.';

  @override
  String get notificationProblemReported =>
      'تم الإبلاغ عن مشكلة في أحد التوصيلات';

  @override
  String get notificationScheduleChangeProposed => 'مواعيد جديدة تنتظر ردك';

  @override
  String get notificationScheduleChangeAnswered =>
      'ردّ أحد المُرسِلين على مواعيدك الجديدة';

  @override
  String get notificationScheduleChangeApplied => 'تغيّرت مواعيد إحدى الرحلات';

  @override
  String get notificationScheduleChangeWithdrawn => 'تم سحب المواعيد الجديدة';

  @override
  String get scheduleDeparture => 'المغادرة';

  @override
  String get scheduleArrival => 'الوصول';

  @override
  String get schedulePickup => 'استلام الطرد';

  @override
  String get scheduleParcelFallback => 'طرد';

  @override
  String get scheduleReasonDeadline => 'الوصول الجديد بعد موعدك النهائي.';

  @override
  String get scheduleReasonShift => 'يتغير وقت الوصول بأكثر من الحد المسموح.';

  @override
  String get scheduleReasonPickup => 'يتغير وقت استلام الطرد.';

  @override
  String get scheduleSectionTitle => 'مواعيد الرحلة';

  @override
  String get scheduleSectionIntro =>
      'تغيّرت خططك؟ حدّث مواعيدك. يُبلَّغ المُرسِلون المتأثرون، وقد يحتاج بعضهم إلى الموافقة.';

  @override
  String get scheduleChangeAction => 'تغيير المواعيد';

  @override
  String scheduleWaitingPill(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'بانتظار $count مُرسِل',
      many: 'بانتظار $count مُرسِلًا',
      few: 'بانتظار $count مُرسِلين',
      two: 'بانتظار مُرسِلَين',
      one: 'بانتظار مُرسِل واحد',
      zero: 'لا أحد بانتظار الموافقة',
    );
    return '$_temp0';
  }

  @override
  String get scheduleWaitingBody =>
      'تبقى مواعيد رحلتك كما هي إلى أن يرد كل مُرسِل مطلوب موافقته.';

  @override
  String get scheduleSendersTitle => 'المُرسِلون المطلوب ردهم';

  @override
  String get scheduleConsentPending => 'بالانتظار';

  @override
  String get scheduleConsentAccepted => 'وافق';

  @override
  String get scheduleConsentDeclined => 'رفض';

  @override
  String get scheduleWithdrawAction => 'سحب المواعيد الجديدة';

  @override
  String get scheduleWithdrawn => 'تم سحب المواعيد الجديدة.';

  @override
  String get scheduleWithdrawnByYou =>
      'سحبتَ آخر مواعيد جديدة. تبقى رحلتك بمواعيدها السابقة.';

  @override
  String get scheduleWithdrawnNoLongerValid =>
      'أُلغيت آخر مواعيد جديدة لأن الرحلة تقدمت. تبقى رحلتك بمواعيدها الحالية.';

  @override
  String get scheduleChangeTitle => 'تغيير المواعيد';

  @override
  String get scheduleChangeIntro =>
      'اختر المغادرة والوصول الجدیدين للمراحل التي تغيّرت. سترى من يتأثر قبل إرسال أي شيء.';

  @override
  String get scheduleStopsNote =>
      'يمكن تغيير المواعيد فقط في رحلة قائمة. لإضافة محطة أو إزالتها، ألغِ الرحلة وأنشئ رحلة جديدة.';

  @override
  String get scheduleReviewAction => 'مراجعة التغييرات';

  @override
  String get scheduleReviewTitle => 'مراجعة المواعيد الجديدة';

  @override
  String get scheduleEditTimes => 'تعديل المواعيد';

  @override
  String get scheduleSendAction => 'إرسال المواعيد الجديدة';

  @override
  String get scheduleApplyAction => 'تطبيق المواعيد الجديدة';

  @override
  String get scheduleAppliesAtOnceTitle => 'لا يحتاج أي مُرسِل إلى الموافقة';

  @override
  String get scheduleAppliesAtOnceBody =>
      'تُطبَّق هذه المواعيد فور إرسالها. يُبلَّغ المُرسِلون المتأثرون.';

  @override
  String scheduleWaitsTitle(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'يجب أن يوافق $count مُرسِل أولًا',
      many: 'يجب أن يوافق $count مُرسِلًا أولًا',
      few: 'يجب أن يوافق $count مُرسِلين أولًا',
      two: 'يجب أن يوافق مُرسِلان أولًا',
      one: 'يجب أن يوافق مُرسِل واحد أولًا',
      zero: 'لا تلزم موافقة أحد',
    );
    return '$_temp0';
  }

  @override
  String get scheduleWaitsBody =>
      'تُطبَّق المواعيد الجديدة عندما يوافقون جميعًا. حتى ذلك الحين تبقى مواعيد رحلتك كما هي. المُرسِل الذي يرفض يمكنه الإلغاء، ويُحتسب الإلغاء عليك.';

  @override
  String get scheduleNewTimesTitle => 'المواعيد الجديدة';

  @override
  String get scheduleAffectedTitle => 'الطرود المتأثرة';

  @override
  String get scheduleNoParcelsAffected => 'لا يتأثر أي طرد بهذه المواعيد.';

  @override
  String get scheduleMustAgreeTitle => 'المُرسِلون المطلوب موافقتهم';

  @override
  String get scheduleToldTitle => 'المُرسِلون الذين سيُبلَّغون';

  @override
  String get scheduleReasonLabel => 'ملاحظة للمرسلين (اختياري)';

  @override
  String get scheduleReasonHint => 'مثال: غيّرت شركة الطيران موعد الرحلة.';

  @override
  String get scheduleReasonHelper =>
      'سيقرأ المُرسِلون المطلوب ردهم هذه الملاحظة.';

  @override
  String scheduleSentToSenders(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'تم الإرسال. بانتظار $count مُرسِل.',
      many: 'تم الإرسال. بانتظار $count مُرسِلًا.',
      few: 'تم الإرسال. بانتظار $count مُرسِلين.',
      two: 'تم الإرسال. بانتظار مُرسِلَين.',
      one: 'تم الإرسال. بانتظار مُرسِل واحد.',
      zero: 'تم الإرسال.',
    );
    return '$_temp0';
  }

  @override
  String get scheduleApplied =>
      'تم حفظ المواعيد الجديدة وإبلاغ المُرسِلين المتأثرين.';

  @override
  String get scheduleErrorOffline =>
      'لا يوجد اتصال. لم يتغير شيء. حاول مرة أخرى عند عودة الاتصال.';

  @override
  String get scheduleErrorNotReschedulable =>
      'لا يمكن تغيير المواعيد إلا في رحلة منشورة وغير منتهية.';

  @override
  String get scheduleErrorEmpty =>
      'هذه هي المواعيد الحالية. غيّر موعدًا واحدًا على الأقل.';

  @override
  String get scheduleErrorPending =>
      'هناك مواعيد جديدة بانتظار المُرسِلين. اسحبها أولًا لإرسال غيرها.';

  @override
  String get scheduleErrorLegArrived => 'لا يمكن تغيير مرحلة وصلت بالفعل.';

  @override
  String get scheduleErrorLegDeparted =>
      'المرحلة التي غادرت بالفعل تحتفظ بموعد مغادرتها. يمكن تغيير وصولها فقط.';

  @override
  String get scheduleErrorDepartureInPast =>
      'لا يمكن أن يكون موعد المغادرة في الماضي.';

  @override
  String get scheduleErrorNotWaiting =>
      'لم تعد هذه المواعيد بالانتظار. تم تحديث الشاشة.';

  @override
  String get scheduleAnswerTitle => 'مواعيد جديدة';

  @override
  String get scheduleNoneTitle => 'لا تغيير في المواعيد';

  @override
  String get scheduleNoneBody => 'لم يغيّر المسافر مواعيد هذا التوصيل.';

  @override
  String get scheduleAskedHeadline => 'غيّر المسافر المواعيد';

  @override
  String get scheduleAskedBody =>
      'توصيلك متأثر. راجع المواعيد الجديدة وأخبرنا إن كانت مناسبة لك.';

  @override
  String get scheduleYouAcceptedHeadline => 'وافقتَ على المواعيد الجديدة';

  @override
  String get scheduleYouDeclinedHeadline => 'رفضتَ المواعيد الجديدة';

  @override
  String get scheduleAppliedHeadline => 'المواعيد الجديدة سارية';

  @override
  String get scheduleAppliedBody =>
      'تسير رحلة المسافر الآن وفق المواعيد أدناه.';

  @override
  String get scheduleWithdrawnHeadline => 'تم سحب المواعيد الجديدة';

  @override
  String get scheduleWithdrawnBody =>
      'لا يتغير شيء في توصيلك. تبقى المواعيد السابقة سارية.';

  @override
  String get scheduleInformedHeadline => 'تغيّرت مواعيد المسافر';

  @override
  String get scheduleInformedBody =>
      'تم استلام طردك بالفعل، لذا لا يُطلب موافقتك. يبقى موعد الوصول الذي اتفقتَ عليه عند الدفع يحميك. إذا حدث خطأ يمكنك الإبلاغ عن مشكلة أو فتح نزاع.';

  @override
  String get scheduleCompareTitle => 'المواعيد القديمة والجديدة';

  @override
  String scheduleYourDeadline(String date) {
    return 'موعدك النهائي: $date';
  }

  @override
  String get scheduleWhyTitle => 'لماذا نسألك';

  @override
  String get scheduleTravelerNote => 'ملاحظة من المسافر';

  @override
  String get scheduleLegsTitle => 'المراحل المتغيّرة';

  @override
  String get scheduleAcceptAction => 'قبول المواعيد الجديدة';

  @override
  String get scheduleAcceptInstead => 'قبول المواعيد الجديدة بدلًا من ذلك';

  @override
  String get scheduleDeclineAction => 'رفض';

  @override
  String get scheduleDeclineInstead => 'رفض بدلًا من ذلك';

  @override
  String get scheduleDeclineKeep => 'رجوع';

  @override
  String get scheduleDeclineConfirmTitle => 'رفض المواعيد الجديدة؟';

  @override
  String get scheduleDeclineConfirmBody =>
      'لن يُلغى شيء. بعدها يمكنك إلغاء هذا التوصيل، ولأن المسافر هو من غيّر المواعيد لا يُحتسب الإلغاء عليك. يمكنك تغيير رأيك ما دام المسافر لم يقرر بعد.';

  @override
  String get scheduleAcceptedSnack => 'وافقتَ على المواعيد الجديدة.';

  @override
  String get scheduleDeclinedSnack => 'رفضتَ المواعيد الجديدة.';

  @override
  String get scheduleIfYouCancelTitle => 'إذا ألغيتَ الآن';

  @override
  String get scheduleCancelCountsAsTraveler =>
      'يُحتسب كإلغاء من المسافر لأنه هو من غيّر المواعيد.';

  @override
  String get scheduleCancelNotAvailable => 'لا يمكن إلغاء هذا التوصيل الآن.';

  @override
  String get scheduleInformedActionsTitle => 'إذا حدث خطأ';

  @override
  String get scheduleErrorNoAnswerNeeded => 'لا حاجة إلى ردّ لهذا التوصيل.';

  @override
  String get scheduleViewAction => 'عرض';

  @override
  String get scheduleDealAskedBody =>
      'راجع المواعيد الجديدة وأخبرنا إن كانت مناسبة لك.';

  @override
  String get scheduleDealDeclinedBody =>
      'يمكنك إلغاء هذا التوصيل ولن يُحتسب عليك.';

  @override
  String get scheduleDealAcceptedBody =>
      'وافقتَ على المواعيد الجديدة. بانتظار المُرسِلين الآخرين.';

  @override
  String get scheduleDealInformedBody =>
      'تغيّرت مواعيد المسافر بعد استلام الطرد. اطّلع على المواعيد القديمة والجديدة.';

  @override
  String offerAnswerBy(String when) {
    return 'أجب قبل $when';
  }

  @override
  String offerWaitingUntil(String when) {
    return 'بانتظار الرد حتى $when';
  }

  @override
  String offerAnswerWithin(String time) {
    return 'أجب خلال $time';
  }

  @override
  String offerWaitingWithin(String time) {
    return 'بانتظار الرد، تبقّى $time';
  }

  @override
  String offerMinutesLeft(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count دقيقة',
      many: '$count دقيقة',
      few: '$count دقائق',
      two: 'دقيقتين',
      one: 'دقيقة واحدة',
      zero: 'أقل من دقيقة',
    );
    return '$_temp0';
  }

  @override
  String get offerDeadlinePassed => 'انتهت مهلة الرد';

  @override
  String offerExpiredOn(String when) {
    return 'انتهت الصلاحية في $when';
  }

  @override
  String get offerExpiredTitle => 'انتهت صلاحية هذا العرض';

  @override
  String get offerExpiredBodySender =>
      'لم يصل رد في الوقت المناسب. لم يُحجز أو يُخصم شيء، وطردك ما زال متاحًا لمسافرين آخرين.';

  @override
  String get offerExpiredBodyTraveler =>
      'لم يصل رد في الوقت المناسب. لم يُحجز أو يُخصم شيء. قد تناسب رحلتك طرود أخرى.';

  @override
  String get offerExpiredActionSender => 'اقترح على مسافر آخر';

  @override
  String get offerExpiredActionTraveler => 'تصفّح الطرود';

  @override
  String get notificationOfferReminder => 'عرض على وشك أن تنتهي صلاحيته';

  @override
  String get notificationFitsTrip => 'طرد يناسب رحلتك';

  @override
  String requestFitsTripHint(String route) {
    return 'مقترح لرحلتك $route';
  }

  @override
  String get discoveryFocusGoneRequestTitle => 'هذا الطرد لم يعد متاحًا';

  @override
  String get discoveryFocusGoneRequestBody =>
      'ربما تم قبوله أو سحبه. هذه هي الطرود المتاحة الآن.';

  @override
  String get discoveryFocusGoneTripTitle => 'هذه الرحلة لم تعد معروضة';

  @override
  String get discoveryFocusGoneTripBody => 'هذه هي الرحلات المعروضة الآن.';

  @override
  String get reviewsTitle => 'التقييمات';

  @override
  String reviewsCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count تقييم',
      many: '$count تقييمًا',
      few: '$count تقييمات',
      two: 'تقييمان',
      one: 'تقييم واحد',
    );
    return '$_temp0';
  }

  @override
  String get reviewsOpenHint => 'عرض التقييمات';

  @override
  String reviewsRatingA11y(String rating, int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count تقييم',
      many: '$count تقييمًا',
      few: '$count تقييمات',
      two: 'تقييمان',
      one: 'تقييم واحد',
    );
    return 'التقييم $rating من 5، $_temp0. يفتح التقييمات.';
  }

  @override
  String get reviewsNewSummary => 'لا توجد تقييمات بعد';

  @override
  String get reviewsEmptyTitle => 'لا توجد تقييمات بعد';

  @override
  String get reviewsEmptyBody =>
      'يظهر التقييم هنا بعد تقييم التوصيل وفتح التقييم للطرفين.';

  @override
  String get reviewsOffTitle => 'التقييمات غير متاحة';

  @override
  String get reviewsOffBody => 'التقييمات متوقفة حاليًا. يُرجى العودة لاحقًا.';

  @override
  String get reviewsGoneTitle => 'لم يعد هذا متاحًا';

  @override
  String get reviewsGoneBody =>
      'لم يعد هذا الشخص أو الرحلة معروضًا، لذا لا يمكن عرض تقييماته.';

  @override
  String get reviewsFromSender => 'من مُرسِل';

  @override
  String get reviewsFromTraveler => 'من مسافر';

  @override
  String get reviewsCommentRemoved => 'أزالت Wassla التعليق';

  @override
  String get reviewsMenuLabel => 'خيارات التقييم';

  @override
  String get reviewsReportAction => 'إبلاغ';

  @override
  String get reviewsReportReceived => 'لقد أبلغتَ عن هذا التقييم. وصلنا بلاغك.';

  @override
  String get reviewsReportReviewed => 'لقد أبلغتَ عن هذا التقييم. راجعناه.';

  @override
  String get reviewReportSheetTitle => 'الإبلاغ عن هذا التقييم';

  @override
  String get reviewReportSheetIntro =>
      'أخبرنا بما هو خاطئ. سنراجعه، ولن يُبلَّغ الشخص بأنك أبلغت عنه.';

  @override
  String get reviewReasonOffensive => 'مسيء أو مهين';

  @override
  String get reviewReasonPersonalInformation => 'يكشف معلومات شخصية';

  @override
  String get reviewReasonUnrelated => 'لا علاقة له بالتوصيل';

  @override
  String get reviewReasonUntrue => 'غير صحيح';

  @override
  String get reviewReasonOther => 'سبب آخر';

  @override
  String get reviewReportNoteLabel => 'ملاحظة (اختيارية)';

  @override
  String get reviewReportNoteHint => 'أي شيء يساعدنا على الفهم';

  @override
  String get reviewReportSend => 'إرسال البلاغ';

  @override
  String get reviewReportThanks => 'شكرًا، سنراجعه';

  @override
  String get reviewReportOwn => 'لا يمكنك الإبلاغ عن تقييمك.';

  @override
  String get reviewReportRemoved => 'أزالت Wassla هذا التقييم بالفعل.';

  @override
  String get reviewReportGone => 'لم يعد هذا التقييم متاحًا.';

  @override
  String get ratingRemovedByWassla => 'أزالته Wassla، ولا يُحتسب';

  @override
  String get ratingCommentHiddenByWassla =>
      'أخفت Wassla التعليق عن الآخرين. ما زالت الدرجة محتسبة.';

  @override
  String get supportEmailSubject => 'مساعدة بخصوص Wassla';

  @override
  String supportEmailSubjectDelivery(String tracking) {
    return 'مساعدة بخصوص توصيل Wassla $tracking';
  }

  @override
  String supportEmailFailed(String email) {
    return 'لم يُفتح أي تطبيق بريد. اكتب إلى $email.';
  }

  @override
  String get journeyPausedStaffBodyNoContact =>
      'أوقفت Wassla هذه الرحلة مؤقتًا.';

  @override
  String get authVerifyResent =>
      'أرسلنا رمزًا جديدًا. استخدم الرمز في أحدث رسالة.';

  @override
  String get authVerifyResend => 'إرسال الرمز مرة أخرى';

  @override
  String get profileVerifyEmail => 'تأكيد البريد الإلكتروني';

  @override
  String get profileRating => 'التقييم';

  @override
  String get accountGateStamp => 'حسابك في Wassla';

  @override
  String get accountGateEmail => 'المتابعة بالبريد الإلكتروني';

  @override
  String get accountGateHaveAccount => 'لدي حساب بالفعل';

  @override
  String get accountReasonPostRequestTitle => 'أنشئ حسابك\nلإرسال طردك.';

  @override
  String get accountReasonPostRequestBody =>
      'يرى المسافرون مَن يرسل الطرد. يبقى مبلغ الدفع محجوزًا، وتُحوَّل أرباح المسافر بعد 48 ساعة من التسليم.';

  @override
  String get accountReasonPostTripTitle => 'أنشئ حسابك\nلنشر رحلتك.';

  @override
  String get accountReasonPostTripBody =>
      'يختار المُرسِلون مسافرين يثقون بهم. يعرض حسابك حالة التحقق من هويتك وتقييماتك.';

  @override
  String get accountReasonCarryTitle => 'أنشئ حسابك\nلحمل هذا الطرد.';

  @override
  String get accountReasonCarryBody =>
      'يرى المُرسِل مَن أبدى استعداده لحمل الطرد. تُحوَّل أرباحك إلى حسابك بعد 48 ساعة من التسليم.';

  @override
  String get accountReasonAlertTitle => 'أنشئ حسابك\nلتلقّي تنبيهات المسار.';

  @override
  String get accountReasonAlertBody =>
      'نُعلمك عندما تتوافق رحلة أو طرد مع هذا المسار.';

  @override
  String get accountReasonReportTitle => 'أنشئ حسابك\nللإبلاغ عن تقييم.';

  @override
  String get accountReasonReportBody =>
      'يُرسل الأعضاء البلاغات كي نتمكن من مراجعتها معهم.';

  @override
  String get accountReasonDeliveriesTitle => 'أنشئ حسابك\nلمتابعة التوصيلات.';

  @override
  String get accountReasonDeliveriesBody =>
      'تظهر الطرود التي ترسلها وتحملها كلها في مكان واحد.';

  @override
  String get accountReasonChatTitle => 'أنشئ حسابك\nلبدء المحادثة.';

  @override
  String get accountReasonChatBody =>
      'تُتاح المحادثة بين المُرسِل والمسافر بعد دفع تكلفة التوصيل.';

  @override
  String get accountReasonNotificationsTitle => 'أنشئ حسابك\nلتلقّي الإشعارات.';

  @override
  String get accountReasonNotificationsBody =>
      'تظهر هنا العروض والرسائل وتحديثات التوصيل.';

  @override
  String get accountReasonGenericTitle => 'أنشئ حسابك\nلتبدأ.';

  @override
  String get accountReasonGenericBody =>
      'أرسل طردًا، أو احمل طردًا في رحلة تخطط لها بالفعل.';

  @override
  String get guestSignedOutNotice => 'تم تسجيل خروجك. سجّل الدخول مجددًا.';

  @override
  String get guestNoticeDismiss => 'إغلاق';

  @override
  String get guestWelcomeTitle => 'أرسل طردك مع مسافر يسلك الطريق نفسه.';

  @override
  String get guestWelcomeBody =>
      'تصفّح رحلات وطرودًا حقيقية. يلزمك حساب فقط للنشر أو حمل طرد أو تفعيل التنبيهات أو الإبلاغ عن تقييم.';

  @override
  String get guestHowItWorks => 'كيف تعمل Wassla؟';

  @override
  String get guestAccountAction => 'سجّل الدخول أو أنشئ حسابًا';

  @override
  String get guestDeliveriesTitle => 'تظهر توصيلاتك هنا';

  @override
  String get guestDeliveriesBody =>
      'سجّل الدخول لمتابعة الطرود التي ترسلها وتحملها.';

  @override
  String get guestChatTitle => 'تظهر محادثاتك هنا';

  @override
  String get guestChatBody =>
      'تُتاح المحادثة بين المُرسِل والمسافر بعد دفع تكلفة التوصيل.';

  @override
  String get guestProfileTitle => 'أنت تتصفّح بصفتك ضيفًا';

  @override
  String get guestProfileBody =>
      'أنشئ حسابًا لإرسال طرد أو حمله. يستغرق ذلك دقيقتين.';

  @override
  String get guestSettings => 'الإعدادات';

  @override
  String get socialContinueWithApple => 'المتابعة باستخدام Apple';

  @override
  String get socialContinueWithGoogle => 'المتابعة باستخدام Google';

  @override
  String get socialOr => 'أو';

  @override
  String get socialGoogleFailed =>
      'تعذّر تسجيل دخولك عبر Google. أعد المحاولة.';

  @override
  String get socialAppleFailed => 'تعذّر تسجيل دخولك عبر Apple. أعد المحاولة.';

  @override
  String get socialGoogleUnavailable =>
      'تسجيل الدخول عبر Google غير متاح حاليًا.';

  @override
  String get socialAppleUnavailable =>
      'تسجيل الدخول عبر Apple غير متاح حاليًا.';

  @override
  String get socialAccountDisabled =>
      'هذا الحساب موقوف. تواصل مع الدعم إذا كنت تعتقد أن هناك خطأ.';

  @override
  String get accountNameStamp => 'أوشكت على الانتهاء';

  @override
  String get accountNameTitle => 'بأي اسم نناديك؟';

  @override
  String get accountNameBody =>
      'لم تُضف اسمًا إلى حسابك بعد. يظهر اسمك في عروضك وتوصيلاتك للأشخاص الذين ترسل الطرود أو تحملها معهم.';

  @override
  String get accountNameLabel => 'اسمك';

  @override
  String get chatSafetyTitle => 'الأمان';

  @override
  String get chatSafetySubtitle => 'للإبلاغ عن رسالة، اضغط عليها مطوّلًا.';

  @override
  String get chatBlockAction => 'حظر';

  @override
  String get chatBlockActionDetail =>
      'لا رسائل ولا توصيلات جديدة بينكما بعد الآن.';

  @override
  String get chatUnblockAction => 'إلغاء الحظر';

  @override
  String get chatUnblockActionDetail => 'يمكنكما تبادل الرسائل من جديد.';

  @override
  String get chatBlockConfirmTitle => 'حظر هذا العضو؟';

  @override
  String get chatBlockConfirmBody =>
      'لن يتمكن أيّ منكما من إرسال رسائل هنا، ولا من بدء توصيل جديد مع الآخر. يستمر التوصيل المدفوع مسبقًا كما اتُّفق عليه. يمكنك إلغاء الحظر في أي وقت من الملف الشخصي.';

  @override
  String get chatBlockDone => 'حظرت هذا العضو.';

  @override
  String get chatUnblockDone => 'ألغيت حظر هذا العضو.';

  @override
  String get chatBlockedByMeTitle => 'حظرت هذا العضو';

  @override
  String get chatBlockedByMeBody =>
      'لا يمكن لأيّ منكما إرسال رسائل هنا. يستمر التوصيل المدفوع مسبقًا كما اتُّفق عليه.';

  @override
  String get chatBlockedTitle => 'المراسلة متوقفة';

  @override
  String get chatBlockedBody =>
      'لم يعد بإمكانك إرسال رسائل في هذه المحادثة. يستمر التوصيل المدفوع مسبقًا كما اتُّفق عليه.';

  @override
  String get chatBlockedPill => 'محظور';

  @override
  String get chatReportTitle => 'الإبلاغ عن هذه الرسالة';

  @override
  String get chatReportSubtitle =>
      'يراجع فريق Wassla كل بلاغ خلال يوم واحد. لا يُخبَر صاحب الرسالة بمن أبلغ عنها.';

  @override
  String get chatReportReasonLabel => 'ما المشكلة فيها؟';

  @override
  String get chatReportReasonSpam => 'رسائل مزعجة أو إعلانات';

  @override
  String get chatReportReasonHarassment => 'تحرّش أو تهديد';

  @override
  String get chatReportReasonScam => 'احتيال، أو طلب الدفع خارج Wassla';

  @override
  String get chatReportReasonInappropriate => 'مسيء أو غير لائق';

  @override
  String get chatReportReasonOther => 'شيء آخر';

  @override
  String get chatReportChooseReason => 'اختر سببًا.';

  @override
  String get chatReportNoteLabel => 'هل تريد إضافة شيء؟ (اختياري)';

  @override
  String get chatReportAlsoBlock => 'حظر هذا العضو أيضًا';

  @override
  String get chatReportAlsoBlockDetail =>
      'لن يتمكن أيّ منكما من إرسال رسائل هنا بعد الآن.';

  @override
  String get chatReportSend => 'إرسال البلاغ';

  @override
  String get chatReportSent => 'شكرًا. سيراجعه فريق Wassla.';

  @override
  String get chatMessageRemoved => 'أزالتها Wassla';

  @override
  String get chatDeletedAccount => 'حساب محذوف';

  @override
  String get partyBlockedTitle => 'غير ممكن مع هذا العضو';

  @override
  String get partyBlockedBody =>
      'حظر أحدكما الآخر، لذا لا يمكن لأيّ منكما بدء توصيل مع الآخر. تجد الأشخاص الذين تحظرهم في الملف الشخصي.';

  @override
  String get blockedPeopleTitle => 'الأشخاص المحظورون';

  @override
  String get blockedPeopleBody =>
      'لا يمكنك أنت وهؤلاء الأشخاص تبادل الرسائل ولا بدء توصيل جديد معًا. إلغاء الحظر يعيد الأمرين.';

  @override
  String get blockedPeopleEmptyTitle => 'لم تحظر أحدًا';

  @override
  String get blockedPeopleEmptyBody => 'عندما تحظر شخصًا من محادثة، يظهر هنا.';

  @override
  String blockedPeopleSince(String date) {
    return 'محظور منذ $date';
  }

  @override
  String get profileDeleteAccount => 'حذف الحساب';

  @override
  String get deleteAccountTitle => 'حذف حسابك';

  @override
  String get deleteAccountIntro =>
      'حذف حسابك نهائي. لن تتمكن من تسجيل الدخول إليه مجددًا، ونمحو اسمك وبريدك الإلكتروني ورقم هاتفك وطرق تسجيل الدخول والإشعارات والتنبيهات وملفك العام.';

  @override
  String get deleteAccountKeptTitle => 'ما نحتفظ به';

  @override
  String get deleteAccountKeptBody =>
      'تبقى السجلات التي يحتاجها الآخرون ويفرضها القانون، دون بيانات التواصل الخاصة بك: التوصيلات السابقة والمدفوعات وتحويلات الأرباح وقرارات التحقق من الهوية والتقييمات والنزاعات ورسائل المحادثة.';

  @override
  String get deleteAccountBlockedTitle => 'أنهِ هذه أولًا';

  @override
  String get deleteAccountBlockedBody =>
      'يمكن حذف حسابك عندما لا يبقى شيء مفتوح.';

  @override
  String get deleteAccountBlockerDeliveries => 'توصيل لم ينتهِ بعد';

  @override
  String get deleteAccountBlockerDisputes => 'نزاع لا يزال مفتوحًا';

  @override
  String get deleteAccountBlockerPayouts => 'تحويل أرباح لم يصلك بعد';

  @override
  String get deleteAccountBlockerRefunds => 'استرداد لم يصلك بعد';

  @override
  String get deleteAccountBlockerRequests =>
      'طلب إرسال طرد لا يزال مفتوحًا. ألغِه من التوصيلات.';

  @override
  String get deleteAccountBlockerJourneys =>
      'رحلة منشورة أو جارية. ألغِها أو أنهِها من التوصيلات.';

  @override
  String get deleteAccountBlockerOther => 'شيء لا يزال مفتوحًا في حسابك';

  @override
  String get deleteAccountOpenDeliveries => 'فتح التوصيلات';

  @override
  String get deleteAccountCheckAgain => 'التحقق من جديد';

  @override
  String get deleteAccountAppleNote =>
      'تستخدم تسجيل الدخول عبر Apple. ستطلب Apple تأكيدك، ثم تتوقف Wassla عن استخدام معرّف Apple الخاص بك.';

  @override
  String get deleteAccountAppleElsewhereTitle => 'احذفه من جهاز iPhone';

  @override
  String get deleteAccountAppleElsewhereBody =>
      'يستخدم حسابك تسجيل الدخول عبر Apple، ولا يمكن تأكيد حذفه إلا عبر Apple. افتح Wassla على iPhone أو iPad لحذفه، أو راسل الدعم.';

  @override
  String get deleteAccountPasswordLabel => 'كلمة المرور';

  @override
  String get deleteAccountPasswordHelp => 'للتأكد من أنك صاحب الحساب.';

  @override
  String get deleteAccountPasswordMissing => 'أدخل كلمة المرور.';

  @override
  String get deleteAccountPasswordIncorrect => 'كلمة المرور غير صحيحة.';

  @override
  String get deleteAccountAction => 'حذف حسابي';

  @override
  String get deleteAccountConfirmTitle => 'حذف حسابك؟';

  @override
  String get deleteAccountConfirmBody =>
      'لا يمكن التراجع عن ذلك. سيُسجَّل خروجك من كل أجهزتك.';

  @override
  String get deleteAccountConfirm => 'حذف';

  @override
  String get deleteAccountChanged =>
      'تغيّر شيء في حسابك. راجع القائمة من جديد.';

  @override
  String get deleteAccountAppleRefused =>
      'لم تؤكد Apple. لم يُحذف شيء. حاول مجددًا.';

  @override
  String get deleteAccountAppleUnavailable =>
      'تعذّر الوصول إلى Apple. لم يُحذف شيء. حاول مجددًا بعد بضع دقائق.';

  @override
  String get deleteAccountStaff =>
      'يُغلق حساب الفريق من قِبل المشرف العام، لا من التطبيق.';

  @override
  String get deleteAccountDone => 'حُذف حسابك.';
}
