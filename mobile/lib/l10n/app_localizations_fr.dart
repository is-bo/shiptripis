// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for French (`fr`).
class LFr extends L {
  LFr([String locale = 'fr']) : super(locale);

  @override
  String get payoutLegalCountryTitle => 'Pays du compte de versement';

  @override
  String get payoutLegalCountryLabel => 'Pays';

  @override
  String get payoutLegalCountryBody =>
      'Sélectionnez le pays légal de votre compte Stripe pour consentir à la configuration. Si votre pays ne figure pas dans la liste, utilisez les versements DZD.';

  @override
  String get appName => 'ShipTrip';

  @override
  String get actionContinue => 'Continuer';

  @override
  String get actionCancel => 'Annuler';

  @override
  String get actionSave => 'Enregistrer';

  @override
  String get actionRetry => 'Réessayer';

  @override
  String get actionClose => 'Fermer';

  @override
  String get actionDone => 'Terminé';

  @override
  String get actionBack => 'Retour';

  @override
  String get actionNext => 'Suivant';

  @override
  String get actionConfirm => 'Confirmer';

  @override
  String get actionEdit => 'Modifier';

  @override
  String get actionRemove => 'Retirer';

  @override
  String get actionShare => 'Partager';

  @override
  String get actionCopy => 'Copier';

  @override
  String get actionCopied => 'Copié';

  @override
  String get actionRefresh => 'Actualiser';

  @override
  String get actionSeeAll => 'Tout voir';

  @override
  String get actionLearnMore => 'En savoir plus';

  @override
  String get actionGoBack => 'Retour';

  @override
  String get actionNotNow => 'Pas maintenant';

  @override
  String get actionUnderstood => 'Compris';

  @override
  String get actionOpen => 'Ouvrir';

  @override
  String get actionAdd => 'Ajouter';

  @override
  String get actionChange => 'Changer';

  @override
  String get actionSelect => 'Sélectionner';

  @override
  String get actionSearch => 'Rechercher';

  @override
  String get actionClear => 'Effacer';

  @override
  String get actionApply => 'Appliquer';

  @override
  String get actionReport => 'Signaler un problème';

  @override
  String get actionContactSupport => 'Contacter le support';

  @override
  String get navHome => 'Accueil';

  @override
  String get navDeliveries => 'Livraisons';

  @override
  String get navChat => 'Chat';

  @override
  String get navProfile => 'Profil';

  @override
  String get navNotifications => 'Notifications';

  @override
  String navNotificationsWithCount(int count) {
    return 'Notifications, $count non lues';
  }

  @override
  String get roleSender => 'Envoi';

  @override
  String get roleTraveler => 'Voyage';

  @override
  String get roleSwitchLabel => 'Changer de rôle';

  @override
  String get roleSwitchTitle => 'Que faites-vous aujourd’hui ?';

  @override
  String get roleSenderDescription => 'Envoyer un colis avec un voyageur';

  @override
  String get roleTravelerDescription =>
      'Transporter des colis lors d’un trajet que vous faites';

  @override
  String get roleSwitchedToSender => 'Passé en mode envoi';

  @override
  String get roleSwitchedToTraveler => 'Passé en mode voyage';

  @override
  String get authSignIn => 'Se connecter';

  @override
  String get authSignUp => 'Créer un compte';

  @override
  String get authSignOut => 'Se déconnecter';

  @override
  String get authEmail => 'E-mail';

  @override
  String get authPassword => 'Mot de passe';

  @override
  String get authFullName => 'Nom complet';

  @override
  String get authForgotPassword => 'Mot de passe oublié ?';

  @override
  String get authResetPassword => 'Réinitialiser le mot de passe';

  @override
  String get authResetSent =>
      'Si cette adresse e-mail est associée à un compte, nous avons envoyé un code de réinitialisation.';

  @override
  String get authNoAccount => 'Nouveau sur ShipTrip ?';

  @override
  String get authHaveAccount => 'Vous avez déjà un compte ?';

  @override
  String get authVerifyEmailTitle => 'Confirmez votre e-mail';

  @override
  String authVerifyEmailBody(String email) {
    return 'Nous avons envoyé un lien à $email. Confirmez-le pour sécuriser votre compte.';
  }

  @override
  String get authSignOutConfirmTitle => 'Se déconnecter ?';

  @override
  String get authSignOutConfirmBody =>
      'Vous devrez vous reconnecter pour voir vos livraisons.';

  @override
  String get validationRequired => 'Ce champ est obligatoire';

  @override
  String get validationEmailInvalid => 'Saisissez une adresse e-mail valide';

  @override
  String get validationPasswordTooShort => 'Utilisez au moins 8 caractères';

  @override
  String get validationNumberInvalid => 'Saisissez un nombre';

  @override
  String get validationMustBePositive => 'Saisissez un nombre supérieur à zéro';

  @override
  String validationTooLong(int max) {
    return 'Restez sous $max caractères';
  }

  @override
  String get validationSelectOne => 'Choisissez une option';

  @override
  String get validationDateInPast => 'Choisissez une date future';

  @override
  String get validationDeadlineBeforeReady =>
      'L’échéance doit être postérieure à la date de disponibilité du colis';

  @override
  String get stateLoading => 'Chargement…';

  @override
  String get stateOfflineTitle => 'Vous êtes hors ligne';

  @override
  String get stateOfflineBody =>
      'Vérifiez votre connexion. Nous chargerons ceci dès que vous serez de retour en ligne.';

  @override
  String get stateTimeoutTitle => 'Cela a pris trop de temps';

  @override
  String get stateTimeoutBody =>
      'Le serveur n’a pas répondu à temps. Rien n’a été perdu — réessayez.';

  @override
  String get stateServerErrorTitle => 'Une erreur est survenue de notre côté';

  @override
  String get stateServerErrorBody =>
      'Ce n’est pas de votre faute. Réessayez dans un instant.';

  @override
  String get stateNotFoundTitle => 'Introuvable';

  @override
  String get stateNotFoundBody =>
      'Cela a peut-être été supprimé, ou ne vous était pas destiné.';

  @override
  String get stateForbiddenTitle => 'Vous ne pouvez pas faire cela ici';

  @override
  String get stateForbiddenBody =>
      'Votre compte n’a pas accès à cette fonctionnalité.';

  @override
  String get stateSessionExpiredTitle => 'Veuillez vous reconnecter';

  @override
  String get stateSessionExpiredBody =>
      'Votre session a expiré. Connectez-vous pour reprendre là où vous en étiez.';

  @override
  String get stateRateLimitedTitle => 'Trop de tentatives';

  @override
  String get stateRateLimitedBody => 'Attendez un instant avant de réessayer.';

  @override
  String get stateUnexpectedTitle => 'Un problème inattendu est survenu';

  @override
  String get stateUnexpectedBody =>
      'Nous n’avons pas pu terminer cette action. Réessayez, et signalez-le si cela persiste.';

  @override
  String get stateAppOutdatedTitle => 'Cette version n’est plus à jour';

  @override
  String get stateAppOutdatedBody =>
      'Mettez à jour ShipTrip pour continuer. Cette partie de l’application ne fonctionne plus sur cette version.';

  @override
  String get staleTitle => 'Ceci a changé';

  @override
  String get staleRefreshAction => 'Actualiser';

  @override
  String get staleRequestNotOpen => 'Cette demande n’est plus ouverte.';

  @override
  String get staleRequestAlreadyMatched =>
      'Cette demande a déjà été associée à un voyageur.';

  @override
  String get staleJourneyNotActive => 'Ce trajet n’est plus actif.';

  @override
  String get staleOfferNotPending => 'Cette offre a déjà reçu une réponse.';

  @override
  String get staleMatchNotPending =>
      'Cette correspondance n’attend plus de réponse.';

  @override
  String get staleCapacityExceeded =>
      'Il ne reste plus assez de place sur ce trajet.';

  @override
  String get staleCapacityExceededDetail =>
      'Quelqu’un d’autre a réservé de la place pendant que vous décidiez.';

  @override
  String get staleRewardBelowMinimum => 'La rémunération minimale a changé.';

  @override
  String staleRewardBelowMinimumDetail(String amount) {
    return 'Le minimum est désormais de $amount.';
  }

  @override
  String get staleRouteChanged =>
      'Les détails du trajet ont changé. Nous avons actualisé le prix.';

  @override
  String get staleKycInvalid =>
      'Votre vérification d’identité doit être réglée avant de pouvoir faire cela.';

  @override
  String get staleFlightProofInvalid =>
      'Votre justificatif de vol doit être réglé avant que ce trajet puisse être mis en correspondance.';

  @override
  String get staleReservationExpired => 'Votre réservation d’espace a expiré.';

  @override
  String get staleDealClosed => 'Cette livraison est clôturée.';

  @override
  String get stalePayoutProfileInvalid =>
      'Vos informations de paiement ont changé pendant que vous étiez sur cette page. Tirez vers le bas pour actualiser, puis réessayez.';

  @override
  String get stalePayoutCountryUnsupported =>
      'Les paiements en EUR ne sont pas encore disponibles dans ce pays. Choisissez un autre pays ou utilisez les paiements en DZD.';

  @override
  String get staleStripeConnectUnavailable =>
      'La configuration des paiements en EUR est momentanément indisponible. Vos informations sont inchangées — réessayez dans un instant.';

  @override
  String get staleStripeConnectProviderError =>
      'Stripe n’a pas pu traiter la demande. Rien n’a été modifié ; réessayez dans un instant.';

  @override
  String get stalePayoutSetupInvalid =>
      'Cette configuration de paiement n’a pas pu être finalisée. Vérifiez les informations et réessayez.';

  @override
  String get stalePayoutEvidenceUnavailable =>
      'Le document envoyé n’est plus disponible. Veuillez téléverser de nouveau le chèque barré.';

  @override
  String get staleOfferExpired => 'Cette offre n’est plus disponible.';

  @override
  String get moneyYouPay => 'Vous payez';

  @override
  String get moneyYouReceive => 'Vous recevez';

  @override
  String get moneyYourEarnings => 'Vos gains';

  @override
  String get moneyTotalYouReceive => 'Total que vous recevez';

  @override
  String get moneyTravelerReceives => 'Le voyageur reçoit';

  @override
  String get moneyPlatformFee => 'Frais ShipTrip';

  @override
  String get moneyMinimumReward => 'Rémunération minimale';

  @override
  String get moneyRecommendedReward => 'ShipTrip suggère';

  @override
  String get moneyYourReward => 'Votre rémunération';

  @override
  String get moneyYourOffer => 'Votre offre';

  @override
  String get moneyTotal => 'Total';

  @override
  String get moneyDepositPaid => 'Acompte déjà payé';

  @override
  String get moneyRemainingToPay => 'Reste à payer';

  @override
  String get moneyRefundToYou => 'Montant remboursé';

  @override
  String get moneyTravelerCompensation => 'Indemnité du voyageur';

  @override
  String get moneyBreakdownTitle => 'Détail du calcul';

  @override
  String get moneyRewardNotReduced =>
      'Le voyageur reçoit ce montant en totalité. Les frais ShipTrip s’ajoutent en plus, ils ne sont pas prélevés dessus.';

  @override
  String get moneyDepositNotExtra =>
      'Ce montant est crédité sur votre paiement final. Ce n’est pas un frais supplémentaire.';

  @override
  String get moneyAmountCharged => 'Vous serez débité de';

  @override
  String moneyExchangeRate(String rate) {
    return 'Taux : 1 € = $rate DA';
  }

  @override
  String get moneyChargedInDinars =>
      'Chargily facture en dinars algériens. Le prix de la livraison reste en euros.';

  @override
  String get moneyFree => 'Gratuit';

  @override
  String get homeSenderGreeting => 'Envoyez quelque chose au pays';

  @override
  String get homeTravelerGreeting =>
      'Gagnez de l’argent sur un trajet que vous faites déjà';

  @override
  String get homeCreateRequest => 'Envoyer un colis';

  @override
  String get homeCreateJourney => 'Ajouter un trajet';

  @override
  String get homeNeedsYourAction => 'Votre attention';

  @override
  String get homeInProgress => 'En cours';

  @override
  String get homeRecentActivity => 'Activité récente';

  @override
  String get homeNothingNeedsYou =>
      'Rien ne requiert votre attention pour le moment';

  @override
  String get homeEmptySenderTitle => 'Rien en cours pour le moment';

  @override
  String get homeEmptySenderBody =>
      'Publiez ce que vous voulez envoyer et les voyageurs qui vont dans cette direction le verront.';

  @override
  String get homeEmptyTravelerTitle => 'Aucun trajet pour le moment';

  @override
  String get homeEmptyTravelerBody =>
      'Ajoutez le trajet que vous faites et nous vous montrerons les colis sur votre route.';

  @override
  String get deliveriesTitle => 'Livraisons';

  @override
  String get deliveriesFilterActive => 'Actives';

  @override
  String get deliveriesFilterAwaitingYou => 'Votre attention';

  @override
  String get deliveriesFilterHistory => 'Historique';

  @override
  String get deliveriesSenderSection => 'Envois';

  @override
  String get deliveriesTravelerSection => 'Transports';

  @override
  String get deliveriesJourneysSection => 'Mes trajets';

  @override
  String get deliveriesEmptyActiveTitle => 'Rien en cours';

  @override
  String get deliveriesEmptyActiveBody =>
      'Les livraisons que vous envoyez ou transportez apparaîtront ici.';

  @override
  String get deliveriesEmptyHistoryTitle => 'Aucun historique pour le moment';

  @override
  String get deliveriesEmptyHistoryBody =>
      'Les livraisons terminées ou annulées restent ici.';

  @override
  String get deliveriesEmptyAwaitingTitle => 'Vous êtes à jour';

  @override
  String get deliveriesEmptyAwaitingBody => 'Rien n’attend votre action.';

  @override
  String get requestStatusAwaitingDeposit => 'Acompte requis';

  @override
  String get requestStatusOpen => 'Recherche d’un voyageur';

  @override
  String get requestStatusMatched => 'Associé';

  @override
  String get requestStatusInTransit => 'En chemin';

  @override
  String get requestStatusDelivered => 'Livré';

  @override
  String get requestStatusCompleted => 'Terminé';

  @override
  String get requestStatusCancelled => 'Annulé';

  @override
  String get requestStatusExpired => 'Expiré';

  @override
  String get dealStatusOfferAccepted => 'Offre acceptée';

  @override
  String get dealStatusPaymentRequired => 'Paiement requis';

  @override
  String get dealStatusPaymentProcessing => 'Confirmation du paiement';

  @override
  String get dealStatusFunded => 'Payé et protégé';

  @override
  String get dealStatusPickupReady => 'Prêt pour la remise';

  @override
  String get dealStatusPickedUp => 'Récupéré';

  @override
  String get dealStatusInTransit => 'En chemin';

  @override
  String get dealStatusDeliveryReady => 'Prêt à livrer';

  @override
  String get dealStatusDeliveryConfirmed => 'Livré';

  @override
  String get dealStatusProtection => 'Paiement protégé';

  @override
  String get dealStatusCompleted => 'Terminé';

  @override
  String get dealStatusCancelled => 'Annulé';

  @override
  String get dealStatusDisputed => 'En litige';

  @override
  String get dealStatusRefunded => 'Remboursé';

  @override
  String get dealStatusPartiallyRefunded => 'Partiellement remboursé';

  @override
  String get dealStatusPaymentFailed => 'Échec du paiement';

  @override
  String get dealStatusExpired => 'Expiré';

  @override
  String get requestCreateTitle => 'Envoyer un colis';

  @override
  String get requestStepRoute => 'Trajet';

  @override
  String get requestStepParcel => 'Colis';

  @override
  String get requestStepTiming => 'Horaires';

  @override
  String get requestStepReview => 'Vérification';

  @override
  String get requestPickupLocation => 'Remise depuis';

  @override
  String get requestDeliveryLocation => 'Livraison à';

  @override
  String get requestPickupHint => 'Où le voyageur récupère le colis';

  @override
  String get requestDeliveryHint => 'Où le colis est remis au destinataire';

  @override
  String get requestReadyFrom => 'Disponible à partir de';

  @override
  String get requestDeadline => 'Doit arriver avant le';

  @override
  String get requestTitle => 'Que voulez-vous envoyer ?';

  @override
  String get requestTitleHint => 'Documents, médicaments, vêtements…';

  @override
  String get requestDescription => 'Description';

  @override
  String get requestDescriptionHint =>
      'Décrivez-le avec précision. C’est ce que le voyageur accepte de transporter.';

  @override
  String get requestCategory => 'Catégorie';

  @override
  String get requestWeight => 'Poids';

  @override
  String get requestWeightUnit => 'kg';

  @override
  String get requestDimensions => 'Taille';

  @override
  String get requestLength => 'Longueur';

  @override
  String get requestWidth => 'Largeur';

  @override
  String get requestHeight => 'Hauteur';

  @override
  String get requestDimensionUnit => 'cm';

  @override
  String get requestDeclaredValue => 'Valeur déclarée';

  @override
  String get requestDeclaredValueHelp =>
      'Le coût de remplacement. Utilisé en cas de problème.';

  @override
  String get requestPhotos => 'Photos';

  @override
  String get requestPhotosHelp =>
      'Les photos vous protègent tous les deux en cas de litige ultérieur.';

  @override
  String get requestAddPhoto => 'Ajouter une photo';

  @override
  String get requestHandlingNotes => 'Consignes de manipulation';

  @override
  String get requestHandlingNotesHint => 'Tout ce que le voyageur doit savoir';

  @override
  String get requestFragile => 'Fragile';

  @override
  String get requestAcknowledgementsTitle => 'Avant de publier';

  @override
  String get requestAckDescriptionAccurate =>
      'Ma description de ce colis est exacte';

  @override
  String get requestAckItemLegal =>
      'Cet article est légal à envoyer et à recevoir';

  @override
  String get requestAckNoProhibited => 'Il ne contient aucun objet interdit';

  @override
  String get requestAckValueAccurate => 'La valeur déclarée est exacte';

  @override
  String get requestAckCustoms =>
      'Je comprends que je suis responsable des règles douanières ou d’importation applicables';

  @override
  String get requestProhibitedItemsLink =>
      'Voir ce qui ne peut pas être envoyé';

  @override
  String get requestSizeExplainer =>
      'La taille compte autant que le poids. Nous facturons sur la base du plus élevé des deux.';

  @override
  String get requestCreated => 'Publié';

  @override
  String get depositTitle => 'Publiez votre demande';

  @override
  String get depositExplainer =>
      'Payé maintenant pour publier votre demande. Crédité à 100 % sur votre paiement final.';

  @override
  String get depositAmount => 'Acompte';

  @override
  String get depositCreditedNote =>
      'Il est crédité sur votre paiement final lorsqu’un voyageur accepte.';

  @override
  String get depositRefundNote =>
      'Si personne ne l’accepte, ou si vous annulez avant d’accepter une offre, il vous est intégralement remboursé.';

  @override
  String get depositGuidanceTitle => 'Repères pour l’acompte';

  @override
  String get depositSuggestedTotal => 'Total suggéré par ShipTrip';

  @override
  String get depositWholeAmount => 'Votre total pour cette livraison';

  @override
  String get pricingUpdating => 'Mise à jour du prix';

  @override
  String get depositRecommended => 'Acompte recommandé';

  @override
  String get depositMinimumAllowed => 'Acompte minimum';

  @override
  String get depositGuidanceNote =>
      'ShipTrip calcule l’acompte à partir du total suggéré et applique le minimum et le maximum en vigueur. Il sera déduit du paiement final : ce n’est pas un supplément.';

  @override
  String get depositPayAction => 'Payer l’acompte et publier';

  @override
  String get depositPending => 'Confirmation de votre acompte…';

  @override
  String get depositPendingBody =>
      'Nous attendons la confirmation de votre prestataire de paiement. Cela prend généralement quelques secondes.';

  @override
  String get depositPaidTitle => 'Publié';

  @override
  String get depositPaidBody =>
      'Les voyageurs qui vont dans votre direction peuvent maintenant le voir.';

  @override
  String get journeyTitle => 'Trajet';

  @override
  String get journeyCreateTitle => 'Ajouter un trajet';

  @override
  String get journeyOverallRoute => 'Où allez-vous ?';

  @override
  String get journeyFrom => 'De';

  @override
  String get journeyTo => 'À';

  @override
  String get journeyLegs => 'Étapes';

  @override
  String get journeyAddLeg => 'Ajouter une étape';

  @override
  String journeyLegPosition(int position) {
    return 'Étape $position';
  }

  @override
  String get journeyModeFlight => 'Avion';

  @override
  String get journeyModeDrive => 'Voiture';

  @override
  String get journeyDeparts => 'Départ';

  @override
  String get journeyArrives => 'Arrivée';

  @override
  String get journeyCapacity => 'Espace que vous pouvez transporter';

  @override
  String get journeyCapacityHelp =>
      'Définissez ceci par étape. Vous pouvez transporter des quantités différentes selon les parties du trajet.';

  @override
  String get journeyFlightNumber => 'Numéro de vol';

  @override
  String get journeyFlightNumberHint => 'ex. AH1006';

  @override
  String get journeyFlightAirportsRequired =>
      'Les trajets en avion doivent commencer et se terminer dans des aéroports.';

  @override
  String get journeyPublish => 'Publier le trajet';

  @override
  String get journeyCancel => 'Annuler le trajet';

  @override
  String get journeySuggestLegTitle => 'Ajouter l’étape par la route ?';

  @override
  String journeySuggestLegBody(String arrival, String destination) {
    return 'Votre vol atterrit à $arrival, mais vous allez à $destination. Ajoutez le trajet en voiture pour que des colis puissent être associés sur tout le parcours.';
  }

  @override
  String get journeySuggestLegAccept => 'Ajouter l’étape en voiture';

  @override
  String get journeySuggestLegDecline => 'Non, je m’arrête là';

  @override
  String get journeyStatusDraft => 'Brouillon';

  @override
  String get journeyStatusPendingVerification => 'En cours de vérification';

  @override
  String get journeyStatusActive => 'En ligne';

  @override
  String get journeyStatusInProgress => 'En cours';

  @override
  String get journeyStatusCompleted => 'Terminé';

  @override
  String get journeyStatusCancelled => 'Annulé';

  @override
  String get journeyStatusExpired => 'Expiré';

  @override
  String get journeyEmptyLegsTitle => 'Ajoutez votre première étape';

  @override
  String get journeyEmptyLegsBody =>
      'Un trajet est composé d’étapes. Paris-Alger en avion, puis Alger-Jijel par la route.';

  @override
  String get journeyRouteShape => 'Votre trajet';

  @override
  String get journeyModeLabel => 'Comment vous voyagez';

  @override
  String get journeyLegStartsAt => 'Débute à';

  @override
  String get journeyLegEndsAt => 'Se termine à';

  @override
  String get journeyLegEndPlaceholder => 'Choisissez où cette étape se termine';

  @override
  String get journeyChooseDateTime => 'Choisissez la date et l’heure';

  @override
  String get journeyArriveOptionalHelp =>
      'Facultatif. Cela nous permet de vérifier que l’étape suivante part à temps.';

  @override
  String get journeyRemoveLeg => 'Retirer cette étape';

  @override
  String get journeyAddLegDestinationTitle => 'Où se termine cette étape ?';

  @override
  String get journeyMaxLegsReached =>
      'Un trajet peut contenir au maximum 20 étapes.';

  @override
  String get journeyCapacityInvalid =>
      'Saisissez au moins 0,01 kg, avec deux décimales.';

  @override
  String get journeyLegDepartRequired => 'Indiquez quand cette étape part.';

  @override
  String get journeyLegDepartNotAfterPrevious =>
      'Cette étape doit partir après l’étape précédente.';

  @override
  String get journeyLegDepartBeforePreviousArrival =>
      'Cette étape part avant que la précédente n’atterrisse.';

  @override
  String get journeyLegArriveBeforeDepart =>
      'L’arrivée doit être après le départ.';

  @override
  String get journeyNotesLabel => 'Tout ce que les expéditeurs doivent savoir';

  @override
  String get journeyNotesHint =>
      'Pas de liquides, petits colis uniquement, rendez-vous près du terminal…';

  @override
  String get journeySaveDraft => 'Enregistrer le trajet';

  @override
  String get journeyCreatedDraft =>
      'Enregistré comme brouillon. Ajoutez le justificatif de vol, puis publiez-le.';

  @override
  String get journeyDraftNextSteps =>
      'Rien n’est encore visible pour les expéditeurs. Publiez-le une fois votre justificatif de vol approuvé.';

  @override
  String get journeyLegsNeedProofTitle => 'Vols nécessitant un justificatif';

  @override
  String get journeyPublishBlockedProof =>
      'Chaque étape en avion doit avoir un justificatif approuvé avant la mise en ligne.';

  @override
  String get journeyPublished =>
      'Votre trajet est en ligne. Les expéditeurs qui vont dans votre direction peuvent le voir.';

  @override
  String get journeyErrorNotPublishable =>
      'Ce trajet ne peut pas être publié dans son état actuel.';

  @override
  String get journeyErrorNoLegs =>
      'Ce trajet n’a aucune étape, il n’y a donc rien à publier.';

  @override
  String get journeyErrorLegPositions =>
      'Les étapes sont mal numérotées. Annulez ce trajet et recréez-le.';

  @override
  String get journeyErrorEndpointsMismatch =>
      'La première et la dernière étape ne correspondent pas au départ et à la destination du trajet.';

  @override
  String get journeyErrorLegEndpoints =>
      'Une étape commence ou se termine à un endroit que le trajet ne traverse pas.';

  @override
  String get journeyErrorLegTime => 'Une étape arrive avant de partir.';

  @override
  String get journeyErrorLegsDisconnected =>
      'Les étapes ne forment pas un trajet continu.';

  @override
  String get journeyErrorLegTimeOrder =>
      'Les étapes ne sont pas dans l’ordre chronologique.';

  @override
  String get journeyErrorNotOwned =>
      'Ce trajet appartient à quelqu’un d’autre.';

  @override
  String get journeyRebuildHint =>
      'Annulez ce trajet et recréez-le avec les détails corrigés.';

  @override
  String get journeyCancelConfirmTitle => 'Annuler ce trajet ?';

  @override
  String get journeyCancelConfirmBody =>
      'Les expéditeurs ne le verront plus et tout espace réservé sera libéré. Cette action est irréversible.';

  @override
  String get journeyCancelled => 'Trajet annulé.';

  @override
  String journeyReleasedAllocations(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count espaces réservés ont été libérés.',
      one: '1 espace réservé a été libéré.',
      zero: 'Aucun espace réservé n’était en attente.',
    );
    return '$_temp0';
  }

  @override
  String get journeyErrorNotCancellable =>
      'Ce trajet ne peut pas être annulé dans son état actuel.';

  @override
  String get journeyErrorHasFundedDeal =>
      'Une livraison payée dépend de ce trajet. Réglez d’abord cette livraison.';

  @override
  String get journeyMatchesInfoTitle => 'Les expéditeurs font le premier pas';

  @override
  String get journeyMatchesInfoBody =>
      'Vous ne pouvez pas faire d’offre ici. Si l’un de ces expéditeurs vous choisit, son offre arrivera dans Livraisons.';

  @override
  String get journeyMatchesLoadFailed =>
      'Nous n’avons pas pu charger les colis pour ce trajet.';

  @override
  String get routeStopsTitle => 'Vos arrêts';

  @override
  String get routeStopsHelp =>
      'Indiquez votre départ, votre arrivée et vos arrêts en chemin. Nous en déduisons les tronçons.';

  @override
  String get routeStopLabel => 'Arrêt';

  @override
  String get routeAddStopHere => 'Ajouter un arrêt ici';

  @override
  String get routeAddStopTitle => 'Où vous arrêtez-vous ?';

  @override
  String get routeChangeStopTitle => 'Changer cet arrêt';

  @override
  String get routeRemoveStop => 'Supprimer cet arrêt';

  @override
  String get routeMoveStopEarlier => 'Déplacer cet arrêt plus tôt';

  @override
  String get routeMoveStopLater => 'Déplacer cet arrêt plus tard';

  @override
  String get routeStopSameAsPrevious =>
      'C\'est la même ville que l\'arrêt précédent. Choisissez-en une autre ou supprimez l\'un des deux.';

  @override
  String routeSegmentBetween(String from, String to) {
    return '$from → $to';
  }

  @override
  String get routeFlightOnlyExplainer =>
      'Il n\'existe pas de route entre ces deux pays : cette partie doit être un vol.';

  @override
  String get routeFlightAirportsRequired =>
      'Un vol part et arrive dans un aéroport. Choisissez l\'aéroport à chaque extrémité.';

  @override
  String get routeAirportNeededTitle => 'Quel aéroport ?';

  @override
  String routeAirportNeededBody(String stop) {
    return 'Vous décollez de $stop : indiquez l\'aéroport. L\'arrêt reste $stop, il nous faut seulement savoir comment vous en partez.';
  }

  @override
  String get routeChooseAirport => 'Choisir l\'aéroport';

  @override
  String get routeChooseAirportTitle => 'Quel aéroport ?';

  @override
  String get routeChangeAirport => 'Modifier';

  @override
  String routeAirportChosen(String airport) {
    return 'Vol via $airport';
  }

  @override
  String get routeErrorModeUnavailable =>
      'Cette partie du trajet ne peut pas se faire en voiture : il n\'y a pas de route entre ces deux pays, ce doit être un vol.';

  @override
  String get journeyEditTitle => 'Modifier le trajet';

  @override
  String get journeyEditAction => 'Modifier';

  @override
  String get journeySaveChanges => 'Enregistrer';

  @override
  String get journeyEditSaved => 'Trajet mis à jour.';

  @override
  String journeyEditSavedProofReset(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other:
          'Trajet mis à jour. $count justificatifs de vol repassent en vérification car ces vols ont changé.',
      one:
          'Trajet mis à jour. Un justificatif de vol repasse en vérification car ce vol a changé.',
    );
    return '$_temp0';
  }

  @override
  String get journeyEditBlockedTitle => 'Ce trajet ne peut plus être modifié';

  @override
  String get journeyEditBlockedStatus =>
      'Ce trajet ne peut plus être modifié car il est déjà publié. Annulez-le et créez-en un nouveau si l\'itinéraire a changé.';

  @override
  String get journeyEditBlockedDependent =>
      'Ce trajet ne peut plus être modifié car un expéditeur compte déjà sur cet itinéraire.';

  @override
  String get journeyEditStaleRoute =>
      'Cet itinéraire a changé pendant votre modification. Rouvrez-le et réessayez.';

  @override
  String get journeyEditProofNotice =>
      'Modifier les aéroports, le numéro ou les horaires d\'un vol rend son justificatif obsolète : nous le revérifierons.';

  @override
  String get journeyEditProofWarningTitle =>
      'Votre justificatif de vol sera revérifié';

  @override
  String get journeyEditProofWarningBody =>
      'Vous avez modifié un vol qui possède déjà un justificatif. Ce justificatif ne correspond plus à ce vol : il repasse en vérification et le trajet ne pourra être publié qu\'après une nouvelle approbation.';

  @override
  String get proofErrorStorageUnavailable =>
      'Nous n\'avons pas pu enregistrer votre fichier pour l\'instant.';

  @override
  String get proofRetryTitle => 'L\'envoi n\'a pas abouti';

  @override
  String get proofRetryFileKept => 'Votre image est toujours sélectionnée.';

  @override
  String get proofRetry => 'Réessayer';

  @override
  String get proofTitle => 'Justificatif de vol';

  @override
  String get proofExplainer =>
      'Téléversez votre carte d’embarquement ou votre confirmation de réservation. Nous la vérifions avant que votre trajet puisse être associé à des colis.';

  @override
  String get proofDriveNotRequired =>
      'Les étapes en voiture ne nécessitent aucun justificatif.';

  @override
  String get proofUpload => 'Téléverser le justificatif';

  @override
  String get proofStatusMissing => 'Non téléversé';

  @override
  String get proofStatusPending => 'En cours d’examen';

  @override
  String get proofStatusApproved => 'Approuvé';

  @override
  String get proofStatusRejected => 'Non accepté';

  @override
  String proofRejectedReason(String reason) {
    return 'Motif : $reason';
  }

  @override
  String get proofReplace => 'Téléverser un nouveau';

  @override
  String get proofKindLabel => 'Que téléversez-vous ?';

  @override
  String get proofKindTicket => 'Billet';

  @override
  String get proofKindBoardingPass => 'Carte d’embarquement';

  @override
  String get proofKindBookingConfirmation => 'Réservation';

  @override
  String get proofFormatRule =>
      'JPEG, PNG ou WebP, jusqu’à 10 Mo. Nous vérifions le fichier lui-même, renommer un fichier ne suffira donc pas.';

  @override
  String get proofFileTooLarge =>
      'Cette image dépasse 10 Mo. Choisissez-en une plus petite.';

  @override
  String get proofFileTypeNotAllowed =>
      'Seules les images JPEG, PNG et WebP sont acceptées.';

  @override
  String get proofChooseImage => 'Choisir une image';

  @override
  String get proofTakePhoto => 'Prendre une photo';

  @override
  String get proofSelectedFile => 'Prêt à téléverser';

  @override
  String get proofUploading => 'Téléversement de votre justificatif…';

  @override
  String get proofUploaded =>
      'Justificatif reçu. Nous l’examinerons prochainement.';

  @override
  String get proofExistingTitle => 'Ce que vous avez déjà envoyé';

  @override
  String get proofErrorUploadClosed =>
      'Ce trajet a dépassé le stade où un justificatif peut être ajouté.';

  @override
  String proofLegLabel(int position, String from, String to) {
    return 'Étape $position : $from à $to';
  }

  @override
  String get kycTitle => 'Vérification d’identité';

  @override
  String get kycWhyTitle => 'Pourquoi nous le demandons';

  @override
  String get kycWhyBody =>
      'Les expéditeurs confient à un inconnu quelque chose qui compte pour eux. Vérifier les voyageurs est ce qui rend cela raisonnable.';

  @override
  String get kycStatusNotStarted => 'Non commencé';

  @override
  String get kycStatusInProgress => 'En cours';

  @override
  String get kycStatusPending => 'En cours d’examen';

  @override
  String get kycStatusApproved => 'Vérifié';

  @override
  String get kycStatusRejected => 'Non approuvé';

  @override
  String get kycStatusActionRequired => 'Nécessite votre attention';

  @override
  String get kycStartAction => 'Commencer la vérification';

  @override
  String get kycResumeAction => 'Terminer la vérification';

  @override
  String get kycRetryAction => 'Réessayer';

  @override
  String get kycPendingBody =>
      'Nous examinons vos documents. Cela prend généralement moins d’une journée.';

  @override
  String get kycApprovedBody =>
      'Vous êtes vérifié. Vous pouvez publier des trajets et transporter des colis.';

  @override
  String get kycRejectedBody =>
      'Nous n’avons pas pu vérifier vos documents. Vous pouvez les soumettre à nouveau.';

  @override
  String get kycRequiredForJourney =>
      'Vous devez être vérifié avant de pouvoir publier un trajet.';

  @override
  String get kycDocumentType => 'Type de document';

  @override
  String get kycFrontImage => 'Recto du document';

  @override
  String get kycBackImage => 'Verso du document';

  @override
  String get kycSelfie => 'Selfie';

  @override
  String get discoveryTravelersTitle => 'Voyageurs pour ce colis';

  @override
  String get discoveryRequestsTitle => 'Colis sur votre trajet';

  @override
  String get discoveryEmptyTravelersTitle => 'Aucun voyageur pour le moment';

  @override
  String get discoveryEmptyTravelersBody =>
      'Personne ne va dans votre direction pour le moment. Nous vous préviendrons dès que ce sera le cas.';

  @override
  String get discoveryEmptyRequestsTitle => 'Aucun colis pour le moment';

  @override
  String get discoveryEmptyRequestsBody =>
      'Rien ne correspond à votre trajet pour le moment. Nous vous préviendrons dès que ce sera le cas.';

  @override
  String get findTravelersRouteFitExcellent => 'Itinéraire idéal';

  @override
  String get findTravelersRouteFitGood => 'Bon itinéraire';

  @override
  String get findTravelersRouteFitCompatible => 'Itinéraire compatible';

  @override
  String get findTravelersTimingComfortable => 'Arrive largement à temps';

  @override
  String get findTravelersTimingFits => 'Respecte votre délai de livraison';

  @override
  String get findTravelersNewTraveller => 'Nouveau';

  @override
  String get findTravelersViewTrip => 'Voir le trajet';

  @override
  String get findTravelersWhyThisFits => 'Pourquoi ce trajet convient';

  @override
  String get findTravelersEmptyTitle =>
      'Aucun voyageur ne va dans votre direction pour l’instant';

  @override
  String get findTravelersEmptyBody =>
      'Votre demande reste active. Nous vous préviendrons dès qu’un voyageur publiera un trajet sur votre itinéraire.';

  @override
  String get findTravelersIneligibleAwaitingDeposit =>
      'Payez le dépôt de publication pour publier cette demande.';

  @override
  String get findTravelersIneligibleAlreadyMatched =>
      'Ce colis a déjà un voyageur.';

  @override
  String get findTravelersIneligibleClosed => 'Cette demande est clôturée.';

  @override
  String get findTravelersIneligibleInProgress => 'Ce colis est déjà en route.';

  @override
  String get findTravelersTripContinues => 'Le trajet continue';

  @override
  String get findTravelersDirectLeg => 'Transporté en un seul tronçon';

  @override
  String get findTravelersWholeTripMatches =>
      'Tout ce trajet correspond à votre itinéraire';

  @override
  String get findTravelersIdentityVerified => 'Identité vérifiée';

  @override
  String get findTravelersFlightProofApproved => 'Billet d’avion vérifié';

  @override
  String get findTravelersSortBestMatch => 'Meilleure correspondance';

  @override
  String get findTravelersSortSoonest => 'Trajet le plus proche';

  @override
  String get findTravelersShowMore => 'Afficher plus de voyageurs';

  @override
  String findTravelersStop(String city, String iata) {
    return '$city · $iata';
  }

  @override
  String findTravelersTransfers(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count correspondances',
      one: '1 correspondance',
    );
    return '$_temp0';
  }

  @override
  String findTravelersPicksUpIn(String place) {
    return 'Récupération à $place';
  }

  @override
  String findTravelersArrivesIn(String place) {
    return 'Arrivée à $place';
  }

  @override
  String findTravelersArrivesBeforeDeadline(String arrival, String deadline) {
    return 'Arrive le $arrival, avant votre échéance du $deadline';
  }

  @override
  String findTravelersHasRoomFor(String weight) {
    return 'Peut prendre $weight kg';
  }

  @override
  String findTravelersDeliveries(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count livraisons',
      one: '1 livraison',
      zero: 'Aucune livraison',
    );
    return '$_temp0';
  }

  @override
  String discoveryCoveredLegs(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count étapes',
      one: '1 étape',
    );
    return 'Couvre $_temp0';
  }

  @override
  String get discoveryDetourSmall => 'Détour minime';

  @override
  String get discoveryDetourModerate => 'Petit détour';

  @override
  String get discoveryDetourLarge => 'Détour notable';

  @override
  String get discoveryVerifiedTraveler => 'Voyageur vérifié';

  @override
  String get discoveryBoosted => 'Mis en avant';

  @override
  String get discoveryBoostedExplainer =>
      'L’expéditeur a payé pour être vu par plus de voyageurs. Cela ne change pas si vous êtes compatible.';

  @override
  String discoveryRatingCount(String rating, int count) {
    return '$rating ($count)';
  }

  @override
  String get discoveryNoRatingsYet => 'Aucune évaluation pour le moment';

  @override
  String get offerProposeTitle => 'Faire une offre';

  @override
  String get offerProposeExplainer =>
      'Vous choisissez ce que le voyageur gagne. Il peut accepter, refuser, ou revenir avec un montant différent.';

  @override
  String get offerRewardLabel => 'Rémunération du voyageur';

  @override
  String get offerUseRecommended => 'Utiliser le montant suggéré';

  @override
  String get offerSend => 'Envoyer l’offre';

  @override
  String get offerSendCounter => 'Envoyer la contre-offre';

  @override
  String get offerCounter => 'Contre-offre';

  @override
  String get offerAccept => 'Accepter';

  @override
  String get offerDecline => 'Refuser';

  @override
  String get offerWithdraw => 'Retirer';

  @override
  String get offerAwaitingTraveler => 'En attente du voyageur';

  @override
  String get offerAwaitingSender => 'En attente de l’expéditeur';

  @override
  String get offerAwaitingYou => 'À vous de jouer';

  @override
  String offerYouProposed(String amount) {
    return 'Vous avez offert $amount';
  }

  @override
  String offerTheyProposed(String amount) {
    return 'Offre reçue : $amount';
  }

  @override
  String get offerHistoryTitle => 'Historique des offres';

  @override
  String get offerStatusPending => 'En attente';

  @override
  String get offerStatusAccepted => 'Acceptée';

  @override
  String get offerStatusDeclined => 'Refusée';

  @override
  String get offerStatusWithdrawn => 'Retirée';

  @override
  String get offerStatusExpired => 'Expirée';

  @override
  String get offerDeclineConfirmTitle => 'Refuser cette offre ?';

  @override
  String get offerDeclineConfirmBody =>
      'L’autre partie sera informée. Vous pourrez encore négocier ensuite.';

  @override
  String offerAcceptConfirmTitle(String amount) {
    return 'Accepter $amount ?';
  }

  @override
  String get offerAcceptTravelerBody =>
      'L’espace sur votre trajet est réservé dès que vous acceptez. L’expéditeur doit ensuite payer.';

  @override
  String get offerAcceptSenderBody =>
      'Une fois que vous acceptez, il vous sera demandé de payer pour que la livraison démarre.';

  @override
  String offerAcceptSenderConfirmTitle(String amount) {
    return 'Payer $amount pour cette livraison ?';
  }

  @override
  String offerAcceptTravelerConfirmTitle(String amount) {
    return 'Recevoir $amount pour cette livraison ?';
  }

  @override
  String get offerCounterTravelerExplainer =>
      'Choisissez le montant que vous recevrez pour cette livraison. L’expéditeur peut accepter, refuser ou faire une nouvelle contre-offre.';

  @override
  String get offerYourOfferTitle => 'Votre offre';

  @override
  String get offerTravelerCounterTitle => 'Contre-offre du voyageur';

  @override
  String get offerYourCounterTitle => 'Votre contre-offre';

  @override
  String get offerSenderOfferTitle => 'Offre de l’expéditeur';

  @override
  String offerYouWouldPay(String amount) {
    return 'Vous paieriez $amount';
  }

  @override
  String offerTravelerAsks(String amount) {
    return 'Le voyageur demande $amount';
  }

  @override
  String offerYouWouldReceive(String amount) {
    return 'Vous recevriez $amount';
  }

  @override
  String offerSenderOffers(String amount) {
    return 'L’expéditeur propose $amount';
  }

  @override
  String offerBelowMinimum(String amount) {
    return 'Offrez au moins $amount';
  }

  @override
  String get offerEmptyTitle => 'Aucune offre pour le moment';

  @override
  String get offerEmptyBody => 'Lorsqu’une offre est faite, elle apparaît ici.';

  @override
  String get paymentTitle => 'Paiement';

  @override
  String get paymentChooseProvider => 'Comment souhaitez-vous payer ?';

  @override
  String get paymentProviderStripe => 'Stripe';

  @override
  String get paymentProviderStripeSubtitle =>
      'Visa, Mastercard et autres cartes';

  @override
  String get paymentProviderChargily => 'Chargily';

  @override
  String get paymentProviderChargilySubtitle =>
      'Cartes algériennes — CIB et Edahabia';

  @override
  String get paymentProviderUnavailable => 'Indisponible pour le moment';

  @override
  String get paymentProviderNotConfigured => 'Pas encore disponible';

  @override
  String get paymentProviderDisabled => 'Temporairement désactivé';

  @override
  String get paymentProviderConfigurationInvalid => 'Pas encore prêt';

  @override
  String get paymentProviderAmountTooSmall =>
      'Inférieur au minimum de ce moyen de paiement';

  @override
  String get paymentCheckoutFailedTitle => 'Impossible de démarrer ce paiement';

  @override
  String get paymentCheckoutFailedBody =>
      'Le prestataire de paiement a refusé d\'ouvrir la page de paiement. Rien n\'a été débité. Essayez l\'autre moyen, ou revenez dans un instant.';

  @override
  String paymentRailEquivalent(String amount) {
    return 'Équivaut à $amount';
  }

  @override
  String paymentRailRate(String rate) {
    return '1 € = $rate DA';
  }

  @override
  String get paymentRailRateLocked =>
      'Le taux est fixé au moment où vous démarrez le paiement. Le prix de la livraison reste en euros.';

  @override
  String paymentPayWith(String amount, String provider) {
    return 'Payer $amount avec $provider';
  }

  @override
  String a11yPaymentRailCharge(String provider, String amount) {
    return '$provider, débite $amount';
  }

  @override
  String get paymentNoProvidersTitle => 'Aucun moyen de paiement disponible';

  @override
  String get paymentNoProvidersBody =>
      'Le paiement est temporairement indisponible. Rien n’a été débité et votre livraison n’est pas affectée.';

  @override
  String paymentPayAction(String amount) {
    return 'Payer $amount';
  }

  @override
  String get paymentOpeningProvider => 'Ouverture du paiement sécurisé…';

  @override
  String get paymentConfirmingTitle => 'Confirmation de votre paiement';

  @override
  String get paymentConfirmingBody =>
      'Votre banque nous a informés, et nous confirmons cela avec ShipTrip. Ne payez pas à nouveau — cela prend généralement quelques secondes.';

  @override
  String get paymentSucceededTitle => 'Payé';

  @override
  String get paymentSucceededBody =>
      'Votre argent est conservé jusqu’à la livraison du colis.';

  @override
  String get paymentFailedTitle => 'Le paiement n’a pas abouti';

  @override
  String get paymentFailedBody =>
      'Rien n’a été débité. Vous pouvez réessayer ou utiliser un autre moyen de paiement.';

  @override
  String get paymentExpiredTitle => 'La session de paiement a expiré';

  @override
  String get paymentExpiredBody =>
      'Ce lien de paiement a expiré. Recommencez quand vous êtes prêt.';

  @override
  String get paymentStatusRequired => 'Paiement requis';

  @override
  String get paymentStatusStarted => 'Paiement en cours';

  @override
  String get paymentStatusProcessing => 'Traitement en cours';

  @override
  String get paymentStatusPaid => 'Payé';

  @override
  String get paymentStatusFailed => 'Échoué';

  @override
  String get paymentStatusRefundPending => 'Remboursement en cours';

  @override
  String get paymentStatusPartiallyRefunded => 'Partiellement remboursé';

  @override
  String get paymentStatusRefunded => 'Remboursé';

  @override
  String get paymentReturnedTitle => 'Bon retour';

  @override
  String get paymentRedirectNotProof =>
      'Nous confirmons chaque paiement auprès du prestataire avant de le marquer comme payé.';

  @override
  String get guestPayTitle => 'Faire payer quelqu’un d’autre';

  @override
  String get guestPayExplainer =>
      'Partagez un lien et n’importe qui peut payer ce montant pour vous. Aucun compte ShipTrip n’est nécessaire.';

  @override
  String get guestPayCreateLink => 'Créer un lien de paiement';

  @override
  String get guestPayLinkReady => 'Lien prêt';

  @override
  String get guestPayCopyLink => 'Copier le lien';

  @override
  String get guestPayShareLink => 'Partager le lien';

  @override
  String get guestPayRevoke => 'Annuler ce lien';

  @override
  String get guestPayRevoked => 'Lien annulé';

  @override
  String guestPayExpiresAt(String when) {
    return 'Expire $when';
  }

  @override
  String get guestPayWarning =>
      'Toute personne ayant ce lien peut payer ce montant. Elle n’obtient rien d’autre — pas d’accès à votre livraison, votre messagerie, ou vos coordonnées.';

  @override
  String get guestPayPayerEmail => 'Votre e-mail pour le reçu';

  @override
  String get guestPayPayerEmailHelp =>
      'Nous l’utilisons pour votre reçu de paiement, les échecs et les remboursements. Il ne crée pas de compte ShipTrip.';

  @override
  String get guestPayAmountDue => 'Montant dû';

  @override
  String get guestPayForDelivery => 'Paiement pour une livraison ShipTrip';

  @override
  String get guestPayThanksTitle => 'Merci';

  @override
  String get guestPayThanksBody =>
      'Le paiement est confirmé. Aucune autre action n’est nécessaire de votre part.';

  @override
  String get guestPayInvalidTitle => 'Ce lien n’est pas valide';

  @override
  String get guestPayInvalidBody =>
      'Il a peut-être expiré, été annulé, ou déjà été payé.';

  @override
  String get recipientTitle => 'Qui reçoit ce colis ?';

  @override
  String get recipientExplainer =>
      'Nous envoyons le code de livraison par e-mail au destinataire. Le voyageur ne peut terminer la livraison que si le destinataire lui donne ce code.';

  @override
  String get recipientName => 'Nom du destinataire';

  @override
  String get recipientEmail => 'E-mail du destinataire';

  @override
  String get recipientEmailHelp =>
      'Le code de livraison est envoyé à cette adresse. Assurez-vous qu’elle est correcte.';

  @override
  String get recipientLanguage => 'Langue du destinataire';

  @override
  String get recipientLanguageHelp =>
      'C’est la langue que nous utiliserons pour l’e-mail de livraison du destinataire.';

  @override
  String get recipientPhone => 'Téléphone (facultatif)';

  @override
  String get recipientNote => 'Note pour le destinataire (facultatif)';

  @override
  String get recipientSave => 'Enregistrer le destinataire';

  @override
  String get recipientSaved => 'Destinataire enregistré';

  @override
  String get recipientRequiredTitle => 'Destinataire requis';

  @override
  String get recipientRequiredBody =>
      'Ajoutez le destinataire avant la remise afin que nous puissions lui envoyer le code de livraison.';

  @override
  String get recipientRecordedForTraveler =>
      'L’expéditeur a fourni les coordonnées du destinataire.';

  @override
  String get pickupSenderTitle => 'Code de remise';

  @override
  String get pickupSenderExplainer =>
      'Ne donnez ce code au voyageur qu’au moment où vous lui remettez physiquement le colis. C’est ainsi qu’il confirme l’avoir reçu.';

  @override
  String get pickupSenderReveal => 'Afficher le code de remise';

  @override
  String get pickupSenderWarning =>
      'N’envoyez pas ce code par message. Communiquez-le de vive voix, au moment de la remise.';

  @override
  String get pickupTravelerTitle => 'Confirmer la remise';

  @override
  String get pickupTravelerExplainer =>
      'Demandez à l’expéditeur son code de remise lorsqu’il vous confie le colis.';

  @override
  String get pickupCodeLabel => 'Code de remise';

  @override
  String get pickupConfirmAction => 'Confirmer la remise';

  @override
  String get pickupConfirmedTitle => 'Remise confirmée';

  @override
  String get pickupConfirmedBody => 'Vous transportez maintenant ce colis.';

  @override
  String get pickupAwaitingTitle => 'En attente de la remise';

  @override
  String get pickupAwaitingSenderBody =>
      'Le voyageur vous demandera votre code de remise lors de votre rencontre.';

  @override
  String get pickupAwaitingTravelerBody =>
      'Rencontrez l’expéditeur et demandez-lui son code de remise.';

  @override
  String get deliveryTravelerTitle => 'Confirmer la livraison';

  @override
  String get deliveryTravelerExplainer =>
      'Demandez au destinataire le code qui lui a été envoyé par e-mail.';

  @override
  String get deliveryCodeLabel => 'Code de livraison';

  @override
  String get deliveryConfirmAction => 'Confirmer la livraison';

  @override
  String get deliveryConfirmedTitle => 'Livraison confirmée';

  @override
  String get deliveryConfirmedTravelerBody =>
      'Merci. Votre versement est en cours de préparation.';

  @override
  String get deliveryConfirmedSenderBody =>
      'Votre colis est arrivé. Votre paiement reste protégé encore un peu.';

  @override
  String get deliverySenderTitle => 'Code de livraison';

  @override
  String deliveryCodeLockedTitle(String countdown) {
    return 'Disponible dans $countdown';
  }

  @override
  String get deliveryCodeLockedBody =>
      'Par sécurité, le code de livraison reste verrouillé pendant 30 minutes après la remise. Le destinataire n’a pas encore reçu d’e-mail non plus.';

  @override
  String get deliveryCodeLockedWhy => 'Pourquoi cette attente ?';

  @override
  String get deliveryCodeLockedWhyBody =>
      'Cette pause empêche qu’un code soit transmis au même moment que le colis. C’est ce qui empêche qu’une livraison soit marquée terminée avant d’avoir réellement eu lieu.';

  @override
  String get deliveryCodeReadyTitle => 'Code de livraison prêt';

  @override
  String deliveryCodeSentToRecipient(String recipient) {
    return 'Nous avons envoyé le code par e-mail à $recipient.';
  }

  @override
  String get deliveryCodeReveal => 'Afficher le code de livraison';

  @override
  String get deliveryCodeSenderWarning =>
      'Le destinataire le donne au voyageur à la porte. Partagez-le uniquement avec le destinataire.';

  @override
  String get deliveryCodeTravelerNever =>
      'Seul le destinataire possède ce code. Demandez-le-lui à votre arrivée.';

  @override
  String codeAttemptsRemaining(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count tentatives restantes',
      one: '1 tentative restante',
    );
    return '$_temp0';
  }

  @override
  String get codeIncorrect => 'Ce code n’est pas correct';

  @override
  String get codeLockedTitle => 'Trop de tentatives incorrectes';

  @override
  String codeLockedBody(String when) {
    return 'Réessayez $when. Si vous êtes bloqué, demandez un nouveau code.';
  }

  @override
  String get codeRotate => 'Obtenir un nouveau code';

  @override
  String get codeRotated => 'Nouveau code émis. L’ancien ne fonctionne plus.';

  @override
  String get codeRotateConfirmTitle => 'Émettre un nouveau code ?';

  @override
  String get codeRotateConfirmBody =>
      'Le code que vous avez déjà partagé cessera de fonctionner immédiatement.';

  @override
  String get codeNotAvailableYet => 'Ce code n’est pas encore disponible';

  @override
  String get codeCopyForReading =>
      'Lisez le code à voix haute plutôt que de l’envoyer.';

  @override
  String get protectionTitle => 'Paiement protégé';

  @override
  String protectionSenderBody(String when) {
    return 'Votre paiement est conservé jusqu’au $when. En cas de problème avec la livraison, ouvrez un litige avant cette date.';
  }

  @override
  String protectionTravelerBody(String when) {
    return 'Livré. Votre versement est débloqué après le $when, une fois la période de protection terminée.';
  }

  @override
  String protectionEndsIn(String countdown) {
    return 'Se termine dans $countdown';
  }

  @override
  String get protectionEnded => 'Période de protection terminée';

  @override
  String get protectionExplainerTitle => 'Ce que cela signifie';

  @override
  String get protectionExplainerBody =>
      'Les fonds sont conservés jusqu’à la confirmation de la livraison et pendant la période de protection de 48 heures. ShipTrip ne les débloque qu’à la fin de cette période si aucun litige n’est ouvert.';

  @override
  String get payoutTitle => 'Versement';

  @override
  String get payoutStatusNotEligible => 'Pas encore';

  @override
  String get payoutStatusEligible => 'Prêt';

  @override
  String get payoutStatusScheduled => 'Programmé';

  @override
  String get payoutStatusProcessing => 'En cours';

  @override
  String get payoutStatusPaid => 'Payé';

  @override
  String get payoutStatusFailed => 'Échoué';

  @override
  String get payoutStatusCancelled => 'Annulé';

  @override
  String get payoutStatusFrozen => 'En attente';

  @override
  String get payoutFrozenBody =>
      'Un litige est ouvert sur cette livraison, le versement est donc gelé jusqu’à sa résolution.';

  @override
  String get payoutPendingTitle => 'Versement en attente';

  @override
  String get payoutEmptyTitle => 'Aucun versement pour le moment';

  @override
  String get payoutEmptyBody =>
      'Terminez une livraison et vos gains apparaîtront ici.';

  @override
  String get disputeOpenTitle => 'Ouvrir un litige';

  @override
  String get disputeOpenExplainer =>
      'Expliquez-nous ce qui s’est passé. L’ouverture d’un litige gèle le versement du voyageur pendant que nous examinons la situation.';

  @override
  String get disputeCategory => 'Que s’est-il passé ?';

  @override
  String get disputeDescription => 'Décrivez le problème';

  @override
  String get disputeDescriptionHint =>
      'Ce que vous attendiez, et ce qui s’est réellement passé';

  @override
  String get disputeSubmit => 'Ouvrir le litige';

  @override
  String get disputeStatusOpen => 'Ouvert';

  @override
  String get disputeStatusAwaitingEvidence => 'En attente de preuves';

  @override
  String get disputeStatusUnderReview => 'En cours d’examen';

  @override
  String get disputeStatusResolved => 'Résolu';

  @override
  String get disputeStatusClosed => 'Clôturé';

  @override
  String get disputeEvidenceTitle => 'Preuves';

  @override
  String get disputeEvidenceExplainer =>
      'Les photos et vidéos nous aident à comprendre ce qui s’est passé.';

  @override
  String get disputeAddPhoto => 'Ajouter une photo';

  @override
  String get disputeAddVideo => 'Ajouter une vidéo';

  @override
  String get disputeAddNote => 'Ajouter une note';

  @override
  String disputeUploading(int percent) {
    return 'Téléversement… $percent %';
  }

  @override
  String get disputeUploadFailed => 'Échec du téléversement';

  @override
  String get disputeUploadRetry => 'Réessayer le téléversement';

  @override
  String disputeFileTooLarge(String limit) {
    return 'Ce fichier est trop volumineux. La limite est de $limit.';
  }

  @override
  String get disputeFileTypeNotAllowed =>
      'Ce type de fichier n’est pas pris en charge. Utilisez un JPEG, PNG, WebP, MP4 ou MOV.';

  @override
  String get disputeEvidenceLimitReached =>
      'Vous avez ajouté le nombre maximal d’éléments.';

  @override
  String get disputeResolutionTitle => 'Résultat';

  @override
  String get disputeResolutionRefunded => 'Remboursé à l’expéditeur';

  @override
  String get disputeResolutionTravelerPaid => 'Versé au voyageur';

  @override
  String get disputeResolutionPartial => 'Partagé entre les deux parties';

  @override
  String get disputeWindowClosedTitle => 'La période de litige est terminée';

  @override
  String get disputeWindowClosedBody =>
      'Les litiges peuvent être ouverts pendant 48 heures après la livraison. Contactez le support si vous avez encore besoin d’aide.';

  @override
  String get disputeEmptyTitle => 'Aucun litige';

  @override
  String get disputeEmptyBody => 'Rien n’est actuellement en litige.';

  @override
  String get cancelTitle => 'Annuler cette livraison';

  @override
  String get cancelConfirmAction => 'Annuler la livraison';

  @override
  String get cancelKeepAction => 'Conserver';

  @override
  String get cancelFullRefund => 'Vous serez intégralement remboursé.';

  @override
  String get cancelWithCompensation =>
      'Comme la remise est proche, le voyageur est indemnisé pour avoir réservé la place.';

  @override
  String get cancelNotAllowedTitle => 'Ceci ne peut pas être annulé ici';

  @override
  String get cancelAfterPickupBody =>
      'Le colis a déjà été récupéré. En cas de problème, ouvrez plutôt un litige.';

  @override
  String get cancelOutcomeTitle => 'Ce qui se passe';

  @override
  String get cancelCancelledTitle => 'Annulé';

  @override
  String get cancelRefundOnWay => 'Votre remboursement est en cours.';

  @override
  String get ratingTitle => 'Comment cela s’est-il passé ?';

  @override
  String get ratingSenderPrompt => 'Évaluer le voyageur';

  @override
  String get ratingTravelerPrompt => 'Évaluer l’expéditeur';

  @override
  String ratingScoreLabel(int score) {
    return '$score sur 5';
  }

  @override
  String get ratingTagsLabel => 'Qu’avez-vous retenu ?';

  @override
  String get ratingCommentLabel => 'Autre chose ? (facultatif)';

  @override
  String get ratingSubmit => 'Envoyer l’évaluation';

  @override
  String get ratingSubmitted => 'Merci pour votre évaluation';

  @override
  String get ratingWaitingForOther =>
      'Votre évaluation est enregistrée. Vous verrez la leur une fois qu’ils vous auront aussi évalué.';

  @override
  String get ratingHiddenUntilBoth =>
      'Masqué tant que vous n’avez pas tous les deux évalué';

  @override
  String get ratingWindowClosed => 'La période d’évaluation est terminée.';

  @override
  String get ratingEmptyTitle => 'Aucune évaluation pour le moment';

  @override
  String get ratingEmptyBody =>
      'Les évaluations apparaissent une fois la livraison terminée.';

  @override
  String get boostTitle => 'Booster cette demande';

  @override
  String get boostExplainer =>
      'Les voyageurs reçoivent 100 % du bonus Boost. Les demandes boostées apparaissent en tête des recherches.';

  @override
  String get boostDoesNotGuarantee =>
      'Elle ne change pas vos correspondances et ne garantit aucune livraison.';

  @override
  String get boostChoosePackage => 'Choisissez une mise en avant';

  @override
  String get boostAmountLabel => 'Montant de la mise en avant';

  @override
  String boostAmountHelper(String amount) {
    return 'Minimum $amount. Vous pouvez choisir tout montant supérieur.';
  }

  @override
  String get boostPreviewTitle => 'Vérifiez avant de payer';

  @override
  String get boostSenderPays => 'Vous payez';

  @override
  String get boostTravelerGets => 'Le voyageur reçoit si la livraison aboutit';

  @override
  String get boostPlatformKeeps => 'ShipTrip conserve';

  @override
  String get boostEarningsCondition =>
      'Le bonus du voyageur fait partie des gains protégés du Deal. Si la livraison n’aboutit pas à un gain, le paiement de la mise en avant est remboursé.';

  @override
  String get boostReviewAction => 'Vérifier la mise en avant';

  @override
  String get boostConfirmAction => 'Continuer vers le paiement';

  @override
  String get boostAmountBelowMinimum =>
      'Saisissez au moins le montant minimum de la mise en avant.';

  @override
  String get boostPreviewStale =>
      'La répartition a changé. Vérifiez les nouveaux montants avant de continuer.';

  @override
  String boostDuration(int hours) {
    String _temp0 = intl.Intl.pluralLogic(
      hours,
      locale: localeName,
      other: '$hours heures',
      one: '1 heure',
    );
    return '$_temp0';
  }

  @override
  String boostDurationDays(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days jours',
      one: '1 jour',
    );
    return '$_temp0';
  }

  @override
  String get boostActive => 'Mise en avant active';

  @override
  String boostActiveUntil(String when) {
    return 'Active jusqu’au $when';
  }

  @override
  String get boostPendingPayment => 'En attente de paiement';

  @override
  String get boostExpired => 'Mise en avant terminée';

  @override
  String boostPurchase(String amount) {
    return 'Mise en avant pour $amount';
  }

  @override
  String get boostNotEligible =>
      'Cette demande ne peut pas être mise en avant pour le moment.';

  @override
  String get chatTitle => 'Chat';

  @override
  String get chatEmptyTitle => 'Aucune conversation';

  @override
  String get chatEmptyBody => 'Le chat s’ouvre une fois la livraison payée.';

  @override
  String get chatThreadEmptyTitle => 'Dites bonjour';

  @override
  String get chatThreadEmptyBody =>
      'Convenez d’un lieu et d’une heure de rendez-vous.';

  @override
  String get chatComposerHint => 'Écrivez un message';

  @override
  String get chatSend => 'Envoyer';

  @override
  String get chatSendFailed => 'Non envoyé';

  @override
  String get chatRetrySend => 'Appuyez pour réessayer';

  @override
  String get chatSending => 'Envoi en cours…';

  @override
  String get chatClosedTitle => 'Cette conversation est close';

  @override
  String get chatClosedBody =>
      'Vous pouvez toujours la consulter, mais l’envoi de nouveaux messages n’est plus possible.';

  @override
  String get chatUnavailableTitle => 'Le chat n’est pas encore disponible';

  @override
  String get chatUnavailableBody =>
      'Le chat s’ouvre pour cette livraison une fois le paiement confirmé.';

  @override
  String get chatNeverShareCodes =>
      'N’envoyez jamais un code de remise ou de livraison dans le chat.';

  @override
  String get notificationsTitle => 'Notifications';

  @override
  String get notificationsMarkAllRead => 'Tout marquer comme lu';

  @override
  String get notificationsEmptyTitle => 'Rien de nouveau';

  @override
  String get notificationsEmptyBody =>
      'Les offres, paiements et mises à jour de livraison apparaissent ici.';

  @override
  String notificationsUnreadCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count non lues',
      one: '1 non lue',
      zero: 'Aucune non lue',
    );
    return '$_temp0';
  }

  @override
  String get profileTitle => 'Profil';

  @override
  String get profileAccount => 'Compte';

  @override
  String get profilePassportStamp => 'SHIPTRIP · MEMBRE';

  @override
  String get profileCompletedDeliveries => 'Terminées';

  @override
  String get profileRecentRating => 'Note récente';

  @override
  String get profileRoles => 'Votre activité';

  @override
  String get profileVerification => 'Vérification';

  @override
  String get profileRatings => 'Évaluations';

  @override
  String get profilePayments => 'Paiements et versements';

  @override
  String get profileNotificationSettings => 'Notifications';

  @override
  String get profileLanguage => 'Langue';

  @override
  String get profileLanguageSystem => 'Langue de l’appareil';

  @override
  String get profileAppLanguage => 'Langue de l’application';

  @override
  String get profileAppLanguageHelp =>
      'Ce que vous lisez dans ShipTrip. Enregistré sur ce téléphone.';

  @override
  String get profileEmailLanguage => 'Langue des e-mails';

  @override
  String get profileEmailLanguageHelp =>
      'La langue dans laquelle nous vous écrivons — paiements, vérification, livraisons, litiges et sécurité du compte. Enregistrée sur votre compte.';

  @override
  String get profileEmailLanguageSaved => 'Langue des e-mails mise à jour';

  @override
  String get profileSupport => 'Aide et support';

  @override
  String get profileTerms => 'Conditions d’utilisation';

  @override
  String get profilePrivacy => 'Politique de confidentialité';

  @override
  String get profileAppearance => 'Apparence';

  @override
  String get profileAppearanceSystem => 'Suivre l’appareil';

  @override
  String get profileAppearanceLight => 'Clair';

  @override
  String get profileAppearanceDark => 'Sombre';

  @override
  String get profileEmailVerified => 'E-mail vérifié';

  @override
  String get profileEmailUnverified => 'E-mail non vérifié';

  @override
  String profileMemberSince(String date) {
    return 'Sur ShipTrip depuis $date';
  }

  @override
  String profileVersion(String version) {
    return 'Version $version';
  }

  @override
  String get locationSearchTitle => 'Choisir un lieu';

  @override
  String get locationSearchHint => 'Rechercher une localité ou un aéroport';

  @override
  String get locationSelectCountry => 'Choisissez d’abord un pays';

  @override
  String get locationSearchStart =>
      'Saisissez une localité, commune ou un aéroport';

  @override
  String placeTierWilaya(String name) {
    return '$name (wilaya)';
  }

  @override
  String placeTierDepartment(String name) {
    return '$name (département)';
  }

  @override
  String placeTierRegion(String name) {
    return '$name (région)';
  }

  @override
  String placeTierProvince(String name) {
    return '$name (province)';
  }

  @override
  String placeTierAutonomousCommunity(String name) {
    return '$name (communauté autonome)';
  }

  @override
  String placeTierState(String name) {
    return '$name (Land)';
  }

  @override
  String placeTierDistrict(String name) {
    return '$name (district)';
  }

  @override
  String get locationTypeAirport => 'Aéroport';

  @override
  String locationAirportServesPlace(String place) {
    return 'Dessert $place';
  }

  @override
  String locationAirportNearPlace(String place) {
    return 'Près de $place';
  }

  @override
  String locationAirportNearbyDistance(String distance) {
    return 'Aéroport à proximité · $distance km';
  }

  @override
  String get locationTypeLocality => 'Localité';

  @override
  String get locationUseMap => 'Choisir sur la carte';

  @override
  String get locationConfirmPoint => 'Utiliser ce point';

  @override
  String get locationSaved => 'Lieux enregistrés';

  @override
  String get locationPrivacyBeforeFunding =>
      'Seule la ville est partagée tant que la livraison n’est pas payée.';

  @override
  String get locationPrivacyAfterFunding =>
      'Adresse complète partagée avec le voyageur.';

  @override
  String get locationHiddenUntilFunded =>
      'Adresse exacte disponible après paiement';

  @override
  String get locationSearchEmptyTitle => 'Aucun résultat';

  @override
  String get locationSearchEmptyBody =>
      'Essayez une autre orthographe, ou choisissez le point sur la carte.';

  @override
  String get countryNameAlgeria => 'Algérie';

  @override
  String get countryNameFrance => 'France';

  @override
  String get countryNameSpain => 'Espagne';

  @override
  String get countryNameGermany => 'Allemagne';

  @override
  String get locationCountryQuestion => 'Quel pays ?';

  @override
  String get locationChangeCountry => 'Changer';

  @override
  String get locationCountryStep => 'Pays';

  @override
  String get locationCountriesUnavailable =>
      'Aucun pays n’est disponible pour le moment.';

  @override
  String get locationSelectCountryBody =>
      'Choisissez un pays ci-dessus, puis cherchez la ville, la commune ou l’aéroport.';

  @override
  String get locationSearchReadyTitle => 'Prêt quand vous l’êtes';

  @override
  String get locationSearchHintAirports => 'Rechercher un aéroport';

  @override
  String get locationSearchStartAirports =>
      'Saisissez le nom d’un aéroport ou son code à trois lettres.';

  @override
  String get locationAirportsOnly =>
      'Ce segment se fait en avion : seuls les aéroports sont proposés.';

  @override
  String get locationCurrentSelection => 'Sélection actuelle';

  @override
  String locationSearchNoMatch(String query) {
    return 'Rien ici ne correspond à « $query ». Vérifiez l’orthographe, ou essayez la ville importante la plus proche.';
  }

  @override
  String locationSearchNoMatchAirports(String query) {
    return 'Aucun aéroport ici ne correspond à « $query ». Essayez le nom de la ville, ou le code à trois lettres.';
  }

  @override
  String locationPreferredExplainer(String place) {
    return 'Les voyageurs sont mis en relation sur $place. Un point préféré indique seulement où vous préféreriez vous retrouver à l’intérieur.';
  }

  @override
  String get locationPreferredFlexibleHint => 'Aucun point exact nécessaire';

  @override
  String get locationAddPreferredPoint => 'Ajouter un point préféré';

  @override
  String get locationChangePreferredPoint => 'Changer de point';

  @override
  String get locationRemovePreferredPoint => 'Retirer le point préféré';

  @override
  String get locationPreferredRemoved => 'Point préféré retiré.';

  @override
  String get locationPreferredClearedByPlace =>
      'Point préféré retiré — il appartenait au lieu que vous venez de changer.';

  @override
  String get locationDecideLater => 'Décider plus tard';

  @override
  String get locationPointInside => 'Point à l’intérieur de';

  @override
  String locationDropPinHelpIn(String place) {
    return 'Déplacez la carte jusqu’à ce que le repère central soit au bon endroit dans $place, puis confirmez.';
  }

  @override
  String locationNoCentre(String place) {
    return 'Nous n’avons pas de centre enregistré pour $place : la carte démarre donc en vue large. Déplacez-la vers la bonne zone avant de confirmer.';
  }

  @override
  String mapAttribution(String attribution) {
    return 'Données cartographiques $attribution';
  }

  @override
  String get locationYourPlaces => 'Vos lieux';

  @override
  String get locationEmptyTitle => 'Aucun lieu enregistré pour le moment';

  @override
  String get locationEmptyBody =>
      'Placez un repère sur la carte pour enregistrer votre première adresse.';

  @override
  String get locationDropPinHelp =>
      'Déplacez la carte jusqu’à ce que le repère central soit au bon endroit, puis confirmez.';

  @override
  String get locationNamePlaceTitle => 'Nommez ce lieu';

  @override
  String get locationNamePlaceBody =>
      'Vous seul voyez ce nom. Les autres voient la ville tant qu’une livraison n’est pas payée.';

  @override
  String get locationLabelField => 'Nom';

  @override
  String get locationLabelHint => 'Maison, chez maman, le bureau';

  @override
  String get locationSavePlace => 'Enregistrer ce lieu';

  @override
  String get locationPlaceSaved => 'Lieu enregistré.';

  @override
  String get locationPreferredMeetingPoint => 'Point de rencontre préféré';

  @override
  String get locationPreferredOptional => 'Facultatif';

  @override
  String get locationChoosePreferredPoint => 'Choisir sur la carte';

  @override
  String locationFlexibleWithin(String place) {
    return 'Flexible dans $place';
  }

  @override
  String locationPreferredValidation(String place) {
    return 'Le fournisseur cartographique vérifiera que ce point appartient à $place.';
  }

  @override
  String get mapZoomIn => 'Zoomer';

  @override
  String get mapZoomOut => 'Dézoomer';

  @override
  String get timelineTitle => 'Progression';

  @override
  String get timelineWaitingOnYou => 'En attente de vous';

  @override
  String get timelineWaitingOnThem => 'En attente de l’autre partie';

  @override
  String get timelineDone => 'Terminé';

  @override
  String get timelineUpcoming => 'À venir';

  @override
  String get a11yStatusPrefix => 'Statut';

  @override
  String get a11yMoneyAmount => 'Montant';

  @override
  String get a11yRequiredField => 'Obligatoire';

  @override
  String get a11yCloseSheet => 'Fermer';

  @override
  String get a11yBack => 'Retour';

  @override
  String get a11yLoadingContent => 'Chargement du contenu';

  @override
  String get a11yImageOfParcel => 'Photo du colis';

  @override
  String get a11ySelected => 'Sélectionné';

  @override
  String get a11yNotSelected => 'Non sélectionné';

  @override
  String get a11yExpandSection => 'Développer';

  @override
  String get a11yCollapseSection => 'Réduire';

  @override
  String get disputeCategoryNotDelivered => 'Jamais arrivé';

  @override
  String get disputeCategoryDamaged => 'Arrivé endommagé';

  @override
  String get disputeCategoryWrongItem => 'Mauvais article';

  @override
  String get disputeCategoryLate => 'Arrivé trop tard';

  @override
  String get disputeCategoryNoShow => 'L’autre personne ne s’est pas présentée';

  @override
  String get disputeCategoryPayment => 'Il y a un problème avec l’argent';

  @override
  String get disputeCategoryOther => 'Autre chose';

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
    return '$value kg disponibles';
  }

  @override
  String unitDurationHm(int hours, int minutes) {
    return '$hours h $minutes min';
  }

  @override
  String unitDurationM(int minutes) {
    return '$minutes min';
  }

  @override
  String distanceUnder(String max) {
    return 'Moins de $max km';
  }

  @override
  String distanceBetween(String min, String max) {
    return '$min–$max km';
  }

  @override
  String distanceOver(String min) {
    return 'Plus de $min km';
  }

  @override
  String unitDistanceKm(String value) {
    return '$value km';
  }

  @override
  String get weightChargeableVolumetric => 'Tarifé au volume, pas au poids';

  @override
  String get weightChargeableActual => 'Tarifé au poids';

  @override
  String get homeVerifyIdentityTitle => 'Vérifiez votre identité';

  @override
  String get homeVerifyIdentityBody =>
      'Les voyageurs doivent être vérifiés avant qu’un trajet puisse être publié.';

  @override
  String get homeAttentionOfferAwaiting => 'Une offre attend votre réponse';

  @override
  String get homeAttentionFunding => 'Payez pour confirmer cette livraison';

  @override
  String get homeAttentionRecipient => 'Ajoutez le destinataire du colis';

  @override
  String get homeAttentionRevealPickup =>
      'Montrez le code de remise à votre voyageur';

  @override
  String get homeAttentionSubmitPickup => 'Saisissez le code de remise';

  @override
  String get homeAttentionRevealDelivery => 'Le code de livraison est prêt';

  @override
  String get homeAttentionSubmitDelivery => 'Saisissez le code de livraison';

  @override
  String get homeAttentionRating => 'Évaluez cette livraison';

  @override
  String get homeOpenAction => 'Ouvrir';

  @override
  String get deliveriesTabAll => 'Tout';

  @override
  String get deliveryCardSending => 'Envoi';

  @override
  String get deliveryCardCarrying => 'Transport';

  @override
  String deliveryCardWith(String name) {
    return 'avec $name';
  }

  @override
  String journeyLegCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count étapes',
      one: '1 étape',
    );
    return '$_temp0';
  }

  @override
  String journeyProofNeeded(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count vols nécessitent un justificatif',
      one: '1 vol nécessite un justificatif',
    );
    return '$_temp0';
  }

  @override
  String requestOffersCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count offres',
      one: '1 offre',
      zero: 'Aucune offre pour le moment',
    );
    return '$_temp0';
  }

  @override
  String get onboardingSendTitle => 'Envoyez quelque chose au pays';

  @override
  String get onboardingSendBody =>
      'Publiez ce que vous voulez faire livrer. Les voyageurs déjà en route peuvent le transporter, et vous fixez le prix ensemble.';

  @override
  String get onboardingCarryTitle =>
      'Gagnez de l’argent sur un trajet que vous faites déjà';

  @override
  String get onboardingCarryBody =>
      'Ajoutez votre trajet, et nous vous montrerons les colis qui correspondent à votre itinéraire et à vos kilos disponibles.';

  @override
  String get onboardingSafeTitle => 'L’argent attend jusqu’à l’arrivée';

  @override
  String get onboardingSafeBody =>
      'Nous conservons le paiement dès la réservation jusqu’à 48 heures après la confirmation de la livraison.';

  @override
  String get onboardingGetStarted => 'Créer un compte';

  @override
  String get onboardingHaveAccount => 'J’ai déjà un compte';

  @override
  String onboardingPageOf(int current, int total) {
    return 'Page $current sur $total';
  }

  @override
  String get authInvalidCredentials => 'E-mail ou mot de passe incorrect';

  @override
  String get authShowPassword => 'Afficher le mot de passe';

  @override
  String get authHidePassword => 'Masquer le mot de passe';

  @override
  String get authPhone => 'Numéro de téléphone';

  @override
  String get authWilaya => 'Wilaya';

  @override
  String get authWilayaHelp =>
      'Votre wilaya d’origine en Algérie. Choisissez celle à laquelle vous êtes rattaché si vous vivez en Europe.';

  @override
  String get authWilayaSheetTitle => 'Choisir une wilaya';

  @override
  String get authResetCodeSent =>
      'Si cette adresse est associée à un compte, nous lui avons envoyé un code à six chiffres.';

  @override
  String get authResetCodeLabel => 'Code à six chiffres';

  @override
  String get authNewPassword => 'Nouveau mot de passe';

  @override
  String get authResetDone =>
      'Mot de passe modifié. Vous pouvez maintenant vous connecter.';

  @override
  String get authSendCode => 'Envoyer le code';

  @override
  String get authResendCode => 'Envoyer un nouveau code';

  @override
  String get authVerifyDone => 'E-mail vérifié';

  @override
  String get authTermsNotice =>
      'En créant un compte, vous acceptez les Conditions d’utilisation et la Politique de confidentialité.';

  @override
  String get authVerifyNoCode =>
      'Rien reçu ? Vérifiez votre dossier spam. S’il n’y est toujours pas, contactez le support et nous réglerons cela.';

  @override
  String get kycDocIdCard => 'Carte d’identité nationale';

  @override
  String get kycDocPassport => 'Passeport';

  @override
  String get kycDocDrivingLicense => 'Permis de conduire';

  @override
  String get kycAddPhoto => 'Ajouter une photo';

  @override
  String get kycReplacePhoto => 'Remplacer';

  @override
  String get kycFileTooLarge =>
      'Cette image est trop volumineuse. Chaque photo doit faire moins de 8 Mo.';

  @override
  String get kycFileTypeNotAllowed =>
      'Seules les photos JPEG et PNG sont acceptées.';

  @override
  String get kycUploading => 'Envoi de vos documents…';

  @override
  String get kycSubmitAction => 'Soumettre pour examen';

  @override
  String get kycSubmitted =>
      'Documents reçus. Nous les examinerons prochainement.';

  @override
  String get kycBackNotNeeded => 'Un passeport ne nécessite que sa page photo.';

  @override
  String get kycSelfieHelp =>
      'Une photo nette de votre visage, prise à l’instant — elle est comparée à votre document.';

  @override
  String get kycUnavailable =>
      'La vérification est temporairement indisponible. Veuillez réessayer prochainement.';

  @override
  String get payoutEligibleIn => 'Débloqué dans';

  @override
  String get notificationOffer => 'Mise à jour d’offre';

  @override
  String get notificationMatch => 'Nouvelle correspondance';

  @override
  String get notificationPayment => 'Mise à jour de paiement';

  @override
  String get notificationChat => 'Nouveau message';

  @override
  String get notificationRequest => 'Mise à jour de demande';

  @override
  String get notificationDelivery => 'Mise à jour de livraison';

  @override
  String get notificationOther => 'Mise à jour';

  @override
  String get chatBlockedPayAction => 'Aller au paiement';

  @override
  String get chatLoadEarlier => 'Charger les messages précédents';

  @override
  String get chatToday => 'Aujourd’hui';

  @override
  String get chatYesterday => 'Hier';

  @override
  String get paymentProviderNewCheckoutsDisabled =>
      'N’accepte pas de nouveaux paiements pour le moment';

  @override
  String get paymentProviderPickAnother =>
      'Essayez un autre moyen de paiement.';

  @override
  String get paymentContinueTitle => 'Un paiement est déjà en cours';

  @override
  String get paymentContinueBody =>
      'Terminez le paiement déjà démarré plutôt que d’en ouvrir un second.';

  @override
  String get paymentContinueAction => 'Continuer votre paiement';

  @override
  String get paymentCouldNotOpen =>
      'Nous n’avons pas pu ouvrir la page de paiement. Vérifiez qu’un navigateur est installé.';

  @override
  String get paymentStillConfirmingTitle => 'Confirmation en cours';

  @override
  String get paymentStillConfirmingBody =>
      'Cela prend plus de temps que d’habitude. Rien n’est perdu, et vous n’avez pas été débité deux fois.';

  @override
  String get paymentCheckAgain => 'Vérifier à nouveau';

  @override
  String get paymentNothingOutstandingTitle => 'Plus rien à payer';

  @override
  String get paymentNothingOutstandingBody => 'Ceci a déjà été réglé.';

  @override
  String get paymentOrderClosedTitle => 'Ceci ne peut plus être payé';

  @override
  String get paymentOrderClosedBody =>
      'Ce paiement a été clôturé ou remboursé, aucun nouveau paiement ne peut donc être ouvert.';

  @override
  String get requestReadyUntil => 'Disponible jusqu’au';

  @override
  String get requestReadyWindow => 'Créneau de disponibilité';

  @override
  String get requestReadyWindowHelp =>
      'La période pendant laquelle un voyageur peut le récupérer. Indiquez un créneau, pas une minute précise.';

  @override
  String get requestDeadlineHelp =>
      'La date limite d’arrivée. Elle doit être postérieure à la fin de votre créneau de disponibilité.';

  @override
  String get requestWeightHelp => 'Entre 0,01 et 100 kg.';

  @override
  String get requestDimensionsHelp =>
      'Facultatif. Renseignez les trois, ou laissez les trois vides.';

  @override
  String get requestDimensionsPartial =>
      'Renseignez les trois mesures, ou effacez-les toutes.';

  @override
  String get requestCategoryDocuments => 'Documents';

  @override
  String get requestCategorySmallBox => 'Petit colis';

  @override
  String get requestCategoryElectronics => 'Électronique';

  @override
  String get requestCategoryClothing => 'Vêtements';

  @override
  String get requestCategoryOther => 'Autre chose';

  @override
  String get requestProposedReward => 'Ce que vous proposez de payer';

  @override
  String get requestProposedRewardHelp =>
      'Un point de départ, pas un prix fixe. Les voyageurs peuvent l’accepter ou revenir avec un montant différent.';

  @override
  String get requestRewardIsIntent =>
      'Voici ce que vous avez proposé. Le prix est fixé lorsqu’un voyageur accepte une offre.';

  @override
  String get requestReviewTitle => 'Vérifiez tout cela';

  @override
  String get requestAckAllRequired =>
      'Confirmez les cinq points avant de publier.';

  @override
  String get requestPostAction => 'Publier cette demande';

  @override
  String get requestDetailTitle => 'Votre demande';

  @override
  String get requestParcelSection => 'Le colis';

  @override
  String get requestTimingSection => 'Horaires';

  @override
  String get requestRouteSection => 'Trajet';

  @override
  String get requestMatchesSection => 'Voyageurs contactés';

  @override
  String get requestNoMatchesYet =>
      'Vous n’avez encore fait de proposition à personne.';

  @override
  String get requestAwaitingDepositNotice =>
      'Les voyageurs ne peuvent pas encore voir ceci. Payez l’acompte pour le publier.';

  @override
  String get requestFindTravelers => 'Trouver des voyageurs';

  @override
  String get requestPayDepositAction => 'Payer l’acompte';

  @override
  String get requestCancelAction => 'Annuler la demande';

  @override
  String get requestCancelConfirmTitle => 'Annuler cette demande ?';

  @override
  String get requestCancelConfirmBody =>
      'Elle ne sera plus visible pour les voyageurs. Tout acompte payé vous est remboursé.';

  @override
  String get requestCancelled => 'Demande annulée';

  @override
  String get requestCancelNotCancellableBody =>
      'Un voyageur est déjà associé à cette demande, elle ne peut donc pas être annulée ici.';

  @override
  String get requestCancelViaDealBody =>
      'Cette demande est devenue une livraison. Annulez-la depuis la livraison à la place.';

  @override
  String requestPhotoCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count photos',
      one: '1 photo',
      zero: 'Aucune photo',
    );
    return '$_temp0';
  }

  @override
  String get requestNotFragile => 'Manipulation standard';

  @override
  String get requestFragileYes => 'Fragile, à manipuler avec précaution';

  @override
  String get requestTargetedNotice =>
      'Vous avez adressé cette demande à un seul voyageur. Personne d’autre ne peut la voir.';

  @override
  String get depositNotRequiredTitle => 'Aucun acompte requis';

  @override
  String get depositNotRequiredBody =>
      'Cette demande se publie sans acompte. Il n’y a rien à payer ici.';

  @override
  String get depositClampedMin =>
      'C’est le plus petit acompte que nous acceptons.';

  @override
  String get depositClampedMax =>
      'C’est le plus grand acompte que nous acceptons, quelle que soit la valeur du colis.';

  @override
  String get discoveryMatchedDistance => 'Distance parcourue';

  @override
  String get discoveryDetourLabel => 'Détour pour le voyageur';

  @override
  String get discoveryFirstDeparture => 'Départ';

  @override
  String get discoveryProposeBlocked =>
      'Nous n’arrivons pas à déterminer quelle partie de ce trajet correspond à votre colis. Actualisez et réessayez.';

  @override
  String get discoveryVolumetricExplainer =>
      'Ce colis est plus volumineux que lourd, c’est donc sa taille qui détermine le prix.';

  @override
  String get discoveryBreakdownNote =>
      'Voici comment le montant suggéré est calculé. Proposez un montant différent et le total évoluera en conséquence.';

  @override
  String get discoveryProposalSent => 'Offre envoyée';

  @override
  String get discoveryLegRangeMoved =>
      'Le trajet de ce voyageur a changé pendant que vous consultiez la page. Nous l’avons actualisé.';

  @override
  String discoveryIncompatibleCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other:
          'Ce voyageur ne correspond plus à votre colis, pour $count raisons.',
      one: 'Ce voyageur ne correspond plus à votre colis, pour 1 raison.',
    );
    return '$_temp0';
  }

  @override
  String get boostRankingLabel => 'Visibilité';

  @override
  String get boostRankingModest => 'Plus haut dans la liste';

  @override
  String get boostRankingStrong => 'Beaucoup plus haut dans la liste';

  @override
  String get boostRankingTop => 'En tête de liste';

  @override
  String get boostDurationLabel => 'Durée';

  @override
  String get boostPriceLabel => 'Prix';

  @override
  String get boostCompatibilityNote =>
      'Seuls les voyageurs déjà compatibles avec votre colis le voient. Un Boost ne change pas qui sont ces voyageurs.';

  @override
  String get boostActivatesOnPayment =>
      'La mise en avant démarre une fois votre paiement confirmé, pas lorsque vous quittez la page de paiement.';

  @override
  String get boostBuyAction => 'Acheter cette mise en avant';

  @override
  String get boostPayAction => 'Payer cette mise en avant';

  @override
  String get boostPurchasesSection => 'Vos mises en avant';

  @override
  String get boostNoPackagesTitle => 'Aucune mise en avant disponible';

  @override
  String get boostNoPackagesBody =>
      'Aucune formule de mise en avant n’est proposée pour le moment.';

  @override
  String get boostDisabledTitle => 'Les mises en avant sont désactivées';

  @override
  String get boostDisabledBody =>
      'Personne ne peut acheter de mise en avant pour le moment. Votre demande n’est pas affectée.';

  @override
  String get boostLimitReachedTitle => 'Limite de mise en avant atteinte';

  @override
  String boostLimitReachedBody(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other:
          'Vous pouvez avoir $count mises en avant actives à la fois sur une demande.',
      one:
          'Vous pouvez avoir 1 mise en avant active à la fois sur une demande.',
    );
    return '$_temp0';
  }

  @override
  String get boostRequestExpiredBody =>
      'Cette demande a expiré, elle ne peut donc plus être mise en avant.';

  @override
  String get boostPackageUnknownBody =>
      'Cette mise en avant n’est plus proposée. Choisissez-en une autre.';

  @override
  String get boostStatusCancelled => 'Annulée';

  @override
  String get boostStatusUnusable =>
      'Remboursée — la demande n’était plus éligible à la mise en avant';

  @override
  String get boostStatusRefunded => 'Remboursée';

  @override
  String get moneyBaseReward => 'Rémunération de base';

  @override
  String get moneyBoostBonus => 'Bonus Boost';

  @override
  String get moneyBoostFee => 'Frais Boost';

  @override
  String get validationReadyWindowOrder =>
      'Le créneau de disponibilité doit se terminer après son début';

  @override
  String validationWeightRange(String min, String max) {
    return 'Saisissez un poids entre $min et $max kg';
  }

  @override
  String get dealStepAgreed => 'Conditions convenues';

  @override
  String get dealStepPaid => 'Paiement conservé';

  @override
  String get dealStepRecipient => 'Destinataire ajouté';

  @override
  String get dealStepPickedUp => 'Colis récupéré';

  @override
  String get dealStepDelivered => 'Livré';

  @override
  String get dealStepProtection => 'Paiement protégé';

  @override
  String get dealStepCompleted => 'Terminé';

  @override
  String get dealOpenChat => 'Message';

  @override
  String get dealParcelSection => 'Le colis';

  @override
  String get dealMoneySection => 'L’argent';

  @override
  String get dealActionPay => 'Payer maintenant';

  @override
  String get dealActionRecipient => 'Ajouter le destinataire';

  @override
  String get dealActionPickup => 'Remise';

  @override
  String get dealActionDelivery => 'Livraison';

  @override
  String get dealActionDispute => 'Ouvrir un litige';

  @override
  String get dealActionCancel => 'Annuler cette livraison';

  @override
  String get dealActionRate => 'Laisser une évaluation';

  @override
  String dealFundingDeadline(String time) {
    return 'Payez avant $time ou l’espace sera libéré';
  }

  @override
  String get dealLocationsHiddenUntilFunded =>
      'Les adresses exactes apparaissent une fois la livraison payée.';

  @override
  String get dealTravelerAwaitingPayment =>
      'En attente du paiement de l’expéditeur.';

  @override
  String get dealTravelerPaymentFunded =>
      'Le paiement de l’expéditeur est confirmé et protégé.';

  @override
  String get ratingBlindNote =>
      'Aucun de vous ne voit l’évaluation de l’autre tant que vous n’avez pas tous les deux évalué, ou que la période n’est pas terminée.';

  @override
  String get ratingSubmittedTitle => 'Évaluation enregistrée';

  @override
  String get ratingClosedTitle => 'Évaluation close';

  @override
  String get ratingTheirsTitle => 'Son évaluation';

  @override
  String get ratingRevealedNote =>
      'Vous vous êtes évalués tous les deux : vos évaluations sont désormais visibles.';

  @override
  String get pickupTitle => 'Remise';

  @override
  String get pickupNextTitle => 'Et ensuite ?';

  @override
  String get pickupConfirmedSenderNext =>
      'Le code de livraison est maintenant disponible pour votre destinataire. Lui seul peut le transmettre au voyageur.';

  @override
  String get pickupConfirmedTravelerNext =>
      'Transportez le colis jusqu’au destinataire. Il vous lira le code de livraison à la porte — vous ne le voyez jamais vous-même.';

  @override
  String get deliverySafetyWaitingTitle => 'Période de sécurité en cours';

  @override
  String get deliverySafetyWaitingSenderBody =>
      'La remise est confirmée. La confirmation de livraison sera disponible après la période de sécurité ; ShipTrip enverra alors le code de livraison à votre destinataire.';

  @override
  String get deliverySafetyWaitingTravelerBody =>
      'La remise est confirmée. Continuez jusqu’au destinataire. Après la période de sécurité, demandez-lui le code de livraison — ShipTrip ne vous l’affiche jamais.';

  @override
  String get pickupGoToDeliveryAction => 'Aller à la livraison';

  @override
  String get pickupNotFundedBody =>
      'Cette livraison n’est pas encore financée, il n’y a donc aucun code de remise à afficher.';

  @override
  String get pickupNotReadyBody =>
      'Cette livraison n’est pas encore prête pour la remise.';

  @override
  String get pickupAlreadyConfirmedBody =>
      'La remise est déjà confirmée sur cette livraison.';

  @override
  String get recipientRequiredTravelerBody =>
      'L’expéditeur n’a pas encore ajouté le destinataire. Demandez-lui de le faire, puis réessayez le code.';

  @override
  String get codeRequiresNewCodeBody =>
      'Ce code ne peut plus être utilisé. Un nouveau doit être émis avant que vous puissiez confirmer.';

  @override
  String codeRateLimitedBody(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Trop de tentatives. Attendez $count secondes et réessayez.',
      one: 'Trop de tentatives. Attendez une seconde et réessayez.',
    );
    return '$_temp0';
  }

  @override
  String get deliveryTitle => 'Livraison';

  @override
  String get deliverySenderExplainer =>
      'Le destinataire reçoit ce code par e-mail. Il le communique au voyageur à la porte, et c’est ce qui confirme la livraison.';

  @override
  String get deliveryCodeSentToRecipientUnknown =>
      'Nous avons envoyé le code par e-mail à votre destinataire.';

  @override
  String get deliveryCodeBufferOpenBody =>
      'Le code de livraison est encore verrouillé. Il se débloque 30 minutes après la remise.';

  @override
  String get deliveryNotInCarriageBody =>
      'Cette livraison n’est pas en cours de transport, un nouveau code ne peut donc pas être émis.';

  @override
  String get deliveryConfirmedTravelerNext =>
      'La période de protection a commencé. Votre versement est débloqué une fois celle-ci terminée — rien n’est versé avant.';

  @override
  String get deliveryAwaitingTitle => 'Pas encore';

  @override
  String get deliveryAwaitingSenderBody =>
      'Le code de livraison apparaît ici une fois le colis récupéré.';

  @override
  String get deliveryAwaitingTravelerBody =>
      'Confirmez d’abord la remise. Le code de livraison ne peut être utilisé qu’ensuite.';

  @override
  String get protectionEndsInLabel => 'Se termine dans';

  @override
  String get payoutAmountLabel => 'Montant';

  @override
  String get payoutEligibleLabel => 'Prévu';

  @override
  String get disputeViewAction => 'Voir le litige';

  @override
  String get disputeOpenAction => 'Ouvrir un litige';

  @override
  String get disputeOpened => 'Litige ouvert';

  @override
  String get disputeExistingOpenedBody =>
      'Vous avez déjà un litige ouvert sur cette livraison. Nous vous y avons redirigé.';

  @override
  String get disputeFreezesPayoutTitle => 'Le versement du voyageur est gelé';

  @override
  String get disputeFreezesPayoutBody =>
      'Rien n’est versé pendant que nous examinons la situation. Les deux parties peuvent ajouter des preuves.';

  @override
  String get disputeNotAvailableTitle =>
      'Vous ne pouvez pas encore ouvrir de litige';

  @override
  String get disputeNotAvailableBody =>
      'Un litige peut être ouvert une fois le colis récupéré. Avant cela, annulez plutôt la livraison.';

  @override
  String get disputeAlreadyResolvedTitle => 'Une décision a déjà été prise';

  @override
  String get disputeAlreadyResolvedBody =>
      'Il existe déjà un litige résolu sur cette livraison.';

  @override
  String get disputeDetailTitle => 'Litige';

  @override
  String get disputeReferenceLabel => 'Référence';

  @override
  String get disputeCategoryTitle => 'Catégorie';

  @override
  String get disputeReasonLabel => 'Ce qui a été signalé';

  @override
  String get disputeOpenedByLabel => 'Ouvert par';

  @override
  String get disputeOpenedBySender => 'L’expéditeur';

  @override
  String get disputeOpenedByTraveler => 'Le voyageur';

  @override
  String get disputeOpenedAtLabel => 'Ouvert le';

  @override
  String get disputeResolvedAtLabel => 'Décidé le';

  @override
  String get disputeProtectionEndsLabel => 'Fin de la période de protection';

  @override
  String get disputePayoutFrozenTitle => 'Versement gelé';

  @override
  String get disputePayoutSettledBody =>
      'Le versement avait déjà été effectué avant l’ouverture de ce litige.';

  @override
  String get disputeAmountsTitle => 'Comment cela a été réglé';

  @override
  String get disputeAmountsExplainer =>
      'Ces montants sont décidés par ShipTrip. Rien ici n’est calculé sur votre téléphone.';

  @override
  String get disputeCollectedTotal => 'Perçu auprès de l’expéditeur';

  @override
  String get disputeResolutionNoteLabel => 'Note de ShipTrip';

  @override
  String get disputeTimelineTitle => 'Ce qui s’est passé';

  @override
  String get disputeEventOpened => 'Litige ouvert';

  @override
  String disputeEventStatusChanged(String status) {
    return 'Statut changé en $status';
  }

  @override
  String get disputeEventEvidenceAdded => 'Preuve ajoutée';

  @override
  String get disputeEventResolved => 'Décision rendue';

  @override
  String get disputeEventClosed => 'Litige clôturé';

  @override
  String get disputeEventPayoutFrozen => 'Versement gelé';

  @override
  String get disputeEventNote => 'Note ajoutée';

  @override
  String get disputeEventOther => 'Mise à jour';

  @override
  String get disputeEvidenceNone => 'Rien ajouté pour le moment';

  @override
  String get disputeEvidenceView => 'Voir';

  @override
  String get disputeEvidenceOpenFailed =>
      'Nous n’avons pas pu ouvrir ceci. Réessayez.';

  @override
  String get disputeEvidenceKindText => 'Note';

  @override
  String get disputeEvidenceKindPhoto => 'Photo';

  @override
  String get disputeEvidenceKindVideo => 'Vidéo';

  @override
  String disputeEvidenceCount(int count, int max) {
    return '$count sur $max ajoutés';
  }

  @override
  String get disputeEvidenceNoteHint => 'Ce que vous voulez nous faire savoir';

  @override
  String get disputeEvidenceAdded => 'Preuve ajoutée';

  @override
  String get disputeEvidenceClosedBody =>
      'Ce litige est clôturé, rien ne peut plus être ajouté.';

  @override
  String get disputeEvidenceTypeMismatchBody =>
      'Ce fichier ne correspond pas au type choisi.';

  @override
  String get disputeEvidenceContentMismatchBody =>
      'Ce fichier n’est pas ce qu’il prétend être. Essayez-en un autre.';

  @override
  String get disputeEvidenceLinkNote =>
      'Les liens vers les preuves expirent après quelques minutes, nous en récupérons donc un nouveau à chaque ouverture.';

  @override
  String get disputeEvidenceTextRequiredBody =>
      'Écrivez quelque chose avant d’ajouter une note.';

  @override
  String get disputeEvidenceFileRequiredBody =>
      'Choisissez d’abord un fichier.';

  @override
  String unitFileSizeMb(String value) {
    return '$value Mo';
  }

  @override
  String get paymentPollingHint =>
      'Cela peut prendre un instant. Vous pouvez quitter cet écran — nous continuerons à vérifier.';

  @override
  String get paymentOpenProvider => 'Continuer le paiement';

  @override
  String get guestPayPoweredBy => 'Paiement sécurisé via ShipTrip';

  @override
  String get onboardingEyebrow => 'Bienvenue';

  @override
  String get onboardingHeadline =>
      'Envoyez tout,\nles voyageurs\nfont le reste.';

  @override
  String get onboardingBody =>
      'Un corridor entre l’Algérie et la France. Les voyageurs transportent, les expéditeurs économisent, et l’argent est retenu jusqu’à l’arrivée.';

  @override
  String get onboardingStamp => 'EST. 2026 · ALG ↔ FR';

  @override
  String get onboardingTrust =>
      'Identité vérifiée · Paiement retenu · Prix en euros';

  @override
  String get onboardingRouteFrom => 'ALGER';

  @override
  String get onboardingRouteTo => 'PARIS';

  @override
  String get onboardingRouteMeta => 'DIRECT · 2H 25';

  @override
  String get benefitsSkip => 'Passer';

  @override
  String benefitsIndex(int current, int total) {
    return '$current / $total';
  }

  @override
  String get benefitsChapterOneEyebrow => 'Chapitre I · La poste';

  @override
  String get benefitsChapterOneTitle => 'Envoyez partout,\npour une fraction.';

  @override
  String get benefitsChapterOneAccent =>
      'Vers la France, l’Algérie, et plus loin.';

  @override
  String get benefitsChapterOneBody =>
      'Des voyageurs transportent votre colis dans leurs bagages. Vous payez une fraction du tarif express.';

  @override
  String get benefitsChapterOneStamp => 'Par avion';

  @override
  String get benefitsChapterTwoEyebrow => 'Chapitre II · La valise';

  @override
  String get benefitsChapterTwoTitle => 'Gagnez pendant\nvos voyages.';

  @override
  String get benefitsChapterTwoAccent => 'Voyagez. Gagnez.';

  @override
  String get benefitsChapterTwoBody =>
      'Vous partez à Alger, Paris ou Oran ? Remplissez les kilos inutilisés de vos bagages.';

  @override
  String get benefitsChapterTwoStamp => 'Embarquement';

  @override
  String get benefitsChapterThreeEyebrow => 'Chapitre III · Le sceau';

  @override
  String get benefitsChapterThreeTitle => 'Conçu pour\nla confiance.';

  @override
  String get benefitsChapterThreeAccent =>
      'Rien ne repose sur la parole seule.';

  @override
  String get benefitsChapterThreeBody =>
      'Identités vérifiées, paiement retenu jusqu’à la livraison, un code à chaque remise.';

  @override
  String get benefitsChapterThreeStamp => 'Vérifié';

  @override
  String get benefitsHandoverCaption => 'REMISE · 6 CARACTÈRES';

  @override
  String get benefitsKilosFree => 'KG\nLIBRES';

  @override
  String get authWelcomeBackStamp => 'Bon retour';

  @override
  String get authSignInHeadline => 'Content de vous\nrevoir.';

  @override
  String get authSignInSubhead =>
      'Connectez-vous pour reprendre vos livraisons.';

  @override
  String get authJoinStamp => 'Rejoindre le corridor';

  @override
  String get authSignUpHeadline => 'Créez votre\npasseport.';

  @override
  String get authSignUpSubhead =>
      'Deux minutes — puis vous pouvez envoyer ou voyager.';

  @override
  String get authForgotStamp => 'Accès bloqué';

  @override
  String get authForgotHeadline => 'Reprenons\nvotre accès.';

  @override
  String get authVerifyStamp => 'Un dernier tampon';

  @override
  String stateRateLimitedWait(int seconds) {
    return 'Patientez environ $seconds secondes avant de réessayer.';
  }

  @override
  String get authForgotSubhead =>
      'Indiquez l’adresse de votre compte et nous y enverrons un code à six chiffres.';

  @override
  String get authVerifySubhead =>
      'Saisissez le code à six chiffres reçu par e-mail. C’est la dernière étape.';

  @override
  String get onboardingGetStartedShort => 'Commencer';

  @override
  String get requestItemPhoto => 'Photo de l\'objet';

  @override
  String get requestItemPhotoHelp =>
      'Ajoutez une photo nette de ce que vous envoyez. Les voyageurs décident sur cette base.';

  @override
  String get requestItemPhotoChoose => 'Choisir une photo';

  @override
  String get requestItemPhotoFromGallery => 'Depuis la galerie';

  @override
  String get requestItemPhotoTakePhoto => 'Prendre une photo';

  @override
  String get requestItemPhotoReplace => 'Remplacer';

  @override
  String get requestItemPhotoRemove => 'Retirer la photo';

  @override
  String get requestItemPhotoUploading => 'Envoi de votre photo…';

  @override
  String get requestItemPhotoReady => 'Photo ajoutée';

  @override
  String get requestItemPhotoRequired =>
      'Une photo de l\'objet est obligatoire.';

  @override
  String get requestItemPhotoFormatRule => 'JPEG, PNG ou WebP, jusqu\'à 10 Mo.';

  @override
  String get requestItemPhotoTooLarge =>
      'Cette image est trop lourde. Choisissez-en une de moins de 10 Mo.';

  @override
  String get requestItemPhotoTypeNotAllowed =>
      'Ce type de fichier n\'est pas accepté. Utilisez une image JPEG, PNG ou WebP.';

  @override
  String get requestItemPhotoUploadFailed =>
      'La photo n\'a pas été envoyée. Elle est toujours sélectionnée — réessayez.';

  @override
  String get requestItemPhotoStorageUnavailable =>
      'Le stockage des photos est indisponible. Réessayez dans un instant.';

  @override
  String get requestItemPhotoExpired =>
      'Cette photo n\'est plus disponible. Ajoutez-la de nouveau.';

  @override
  String get requestItemPhotoPrivacy =>
      'Seuls les voyageurs qui voient cette demande voient la photo.';

  @override
  String get fieldOptional => 'Facultatif';

  @override
  String get requestDimensionsOptionalHelp =>
      'Facultatif. Laissez vide si vous ne l\'avez pas mesuré — ou saisissez les trois.';

  @override
  String get requestDimensionsPartialFix =>
      'Saisissez longueur, largeur et hauteur ensemble, ou effacez les trois.';

  @override
  String get formFixBeforeContinuing =>
      'Corrigez le champ signalé avant de continuer.';

  @override
  String formFixCountBeforeContinuing(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Corrigez $count champs avant de continuer.',
      one: 'Corrigez 1 champ avant de continuer.',
    );
    return '$_temp0';
  }

  @override
  String get formServerRefusedOnStep =>
      'Le serveur a refusé cette demande. Le problème est à cette étape, signalé ci-dessous.';

  @override
  String get formStepLockedUntilValid => 'Terminez d\'abord cette étape.';

  @override
  String get pushPermissionHeading => 'Sur ce téléphone';

  @override
  String get pushPermissionBody =>
      'Recevez à temps les nouvelles concernant les offres, paiements, livraisons, messages et vérifications. ShipTrip ne demande l’autorisation que lorsque vous choisissez Activer.';

  @override
  String get pushPermissionEnabled => 'Les notifications sont activées.';

  @override
  String get pushPermissionDeniedRequestable =>
      'Les notifications sont toujours désactivées. Choisissez Activer les notifications pour les redemander à Android. La boîte de réception de l’application reste disponible dans tous les cas.';

  @override
  String get pushPermissionDenied =>
      'Les notifications sont désactivées dans le système. Vous pouvez les activer dans les réglages.';

  @override
  String get pushPermissionUnavailable =>
      'Les notifications push ne sont pas configurées dans cette version. Les notifications dans l’application restent disponibles.';

  @override
  String get pushPermissionInitializationFailed =>
      'Les notifications push n’ont pas pu démarrer sur ce téléphone. Les notifications dans l’application restent disponibles ; rouvrez ShipTrip pour réessayer.';

  @override
  String get pushEnableAction => 'Activer les notifications';

  @override
  String get pushOpenSettingsAction => 'Ouvrir les réglages de notification';

  @override
  String get pushRegistrationPending =>
      'L’autorisation système des notifications est active. ShipTrip termine la configuration sur ce téléphone.';

  @override
  String get pushRegistrationFailed =>
      'L’autorisation système des notifications est active, mais ShipTrip n’a pas pu enregistrer ce téléphone. Vérifiez votre connexion et réessayez.';

  @override
  String get pushRetryRegistrationAction => 'Réessayer la configuration';

  @override
  String get pushPreferencesHeading => 'Types de notifications';

  @override
  String get pushPreferencesBody =>
      'Ces choix contrôlent les messages et l’activité de la place de marché. Ils ne modifient pas l’autorisation système de ce téléphone, et les mises à jour essentielles de livraison et de compte restent disponibles.';

  @override
  String get pushEssentialTitle => 'Mises à jour essentielles';

  @override
  String get pushEssentialBody =>
      'Les mises à jour de paiement, livraison, litige, vérification et sécurité du compte restent activées.';

  @override
  String get pushMessagesTitle => 'Messages';

  @override
  String get pushMessagesBody => 'Nouvelle activité dans les discussions.';

  @override
  String get pushMarketplaceTitle => 'Activité de la place de marché';

  @override
  String get pushMarketplaceBody =>
      'Offres, correspondances, trajets et demandes.';

  @override
  String get notificationJourney => 'Mise à jour du trajet';

  @override
  String get notificationAccount => 'Mise à jour de la vérification';

  @override
  String get notificationDispute => 'Mise à jour du litige';

  @override
  String get notificationPayout => 'Mise à jour du versement';

  @override
  String get payoutMethodsTitle => 'Moyens de versement';

  @override
  String get profilePayoutMethods => 'Moyens de versement';

  @override
  String get profilePayoutHistory => 'Historique des versements';

  @override
  String get payoutPreferenceTitle => 'Préférence de versement';

  @override
  String get payoutPreferenceEurOnly => 'EUR uniquement';

  @override
  String get payoutPreferenceDzdOnly => 'DZD uniquement';

  @override
  String get payoutPreferenceBoth => 'Les deux';

  @override
  String get payoutPreferenceBothExplainer =>
      'Les livraisons financées par Stripe sont versées en EUR ; celles financées par Chargily en DZD.';

  @override
  String get payoutPreferenceScopeNote =>
      'Cette préférence s\'applique uniquement aux prochains versements.';

  @override
  String get payoutPreferenceRequired =>
      'Veuillez choisir votre préférence de versement.';

  @override
  String get payoutEurTitle => 'Versements en EUR (Stripe)';

  @override
  String get payoutEurNotConfiguredBody =>
      'Connectez votre compte bancaire européen pour recevoir vos versements en EUR.';

  @override
  String get payoutEurSetupRequiredBody =>
      'Complétez votre dossier sur Stripe pour activer les versements en EUR.';

  @override
  String get payoutEurPendingVerificationBody =>
      'Stripe vérifie actuellement vos informations. Vous serez notifié dès validation.';

  @override
  String get payoutEurReadyBody =>
      'Votre compte EUR est vérifié et prêt à recevoir des versements.';

  @override
  String get payoutEurNeedsAttentionBody =>
      'Votre compte Stripe nécessite une action avant de pouvoir effectuer des versements.';

  @override
  String get payoutActionSetupEur => 'Configurer les versements en EUR';

  @override
  String get payoutActionResumeEur => 'Reprendre la configuration';

  @override
  String get payoutActionManageEur => 'Gérer sur Stripe';

  @override
  String get payoutActionRefresh => 'Actualiser le statut';

  @override
  String get payoutDzdTitle => 'Versements en DZD (CCP / BaridiMob)';

  @override
  String get payoutDzdNotConfiguredBody =>
      'Renseignez votre compte CCP et votre chèque barré pour recevoir vos versements en Algérie.';

  @override
  String get payoutDzdSetupRequiredBody =>
      'Transmettez vos coordonnées CCP et votre chèque barré pour continuer.';

  @override
  String get payoutDzdPendingReviewBody =>
      'Vos coordonnées CCP et votre chèque barré sont en cours d\'examen par notre équipe.';

  @override
  String get payoutDzdReadyBody =>
      'Votre compte CCP est vérifié et prêt pour les versements en DZD.';

  @override
  String get payoutDzdNeedsAttentionBody =>
      'Votre profil de versement nécessite une vérification ou une mise à jour.';

  @override
  String get payoutDzdRejectedBody =>
      'Ce compte CCP n’a pas été accepté pour les paiements. Envoyez un autre compte à votre nom.';

  @override
  String get payoutDzdCorrectionBody =>
      'Vos coordonnées de paiement doivent être corrigées. Renvoyez-les avec une photo nette du chèque barré complet.';

  @override
  String get payoutDzdInactiveBody =>
      'Les versements en DZD sont actuellement inactifs sur votre compte.';

  @override
  String get payoutActionSetupDzd => 'Configurer les versements en DZD';

  @override
  String get payoutActionReplaceDzd => 'Mettre à jour les informations';

  @override
  String get payoutDzdCcpLabel => 'Compte CCP';

  @override
  String get payoutDzdRipLabel => 'RIP';

  @override
  String payoutDzdSubmittedAt(String date) {
    return 'Envoyé le $date';
  }

  @override
  String get payoutDzdFutureScopeNote =>
      'Ces informations s\'appliquent aux prochains versements éligibles. Les versements déjà financés conservent leur destination d\'origine.';

  @override
  String get dzdFormTitle => 'Configurer les versements en DZD';

  @override
  String get dzdFormUpdateTitle => 'Mettre à jour les informations';

  @override
  String get dzdFormScopeExplainer =>
      'Ces informations s\'appliquent aux prochains versements éligibles. Les versements déjà financés conservent leur destination d\'origine.';

  @override
  String get dzdFirstNameLabel => 'Prénom';

  @override
  String get dzdLastNameLabel => 'Nom';

  @override
  String get dzdCcpNumberLabel => 'Numéro de compte CCP';

  @override
  String get dzdCcpNumberHint => '1 à 20 chiffres';

  @override
  String get dzdCcpKeyLabel => 'Clé CCP';

  @override
  String get dzdCcpKeyHint => '2 chiffres';

  @override
  String get dzdRipLabel => 'RIP';

  @override
  String get dzdRipHint => '20 chiffres';

  @override
  String get dzdChequeProofLabel => 'Photo du chèque barré complet';

  @override
  String get dzdChequeProofHelper =>
      'Téléversez une photo claire du chèque barré complet.';

  @override
  String get dzdChequeAddPhoto => 'Choisir une photo';

  @override
  String get dzdChequeReplacePhoto => 'Changer la photo';

  @override
  String get dzdChequeRemovePhoto => 'Supprimer la photo';

  @override
  String get dzdSubmitAction => 'Enregistrer les coordonnées';

  @override
  String get dzdUpdateAction => 'Mettre à jour les coordonnées';

  @override
  String get dzdSubmitSuccess =>
      'Coordonnées de versement enregistrées avec succès.';

  @override
  String get payoutReasonSetupRequired => 'Configuration du versement requise';

  @override
  String get payoutReasonUnderReview => 'Dossier en cours d\'examen';

  @override
  String get payoutReasonNeedsAttention => 'Action requise sur votre profil';

  @override
  String get payoutReasonOnHold => 'Versement en attente';

  @override
  String get payoutReasonDisputeActive => 'Litige en cours sur cette livraison';

  @override
  String get payoutReasonFailed => 'Échec du versement';

  @override
  String get payoutReasonReturned => 'Le versement bancaire a été retourné';

  @override
  String get payoutReasonCountryUnsupported =>
      'Pays non supporté pour les versements Stripe EUR';

  @override
  String get deliveryPayoutSectionTitle => 'Statut du versement';

  @override
  String get deliveryPayoutProtectionExplainer =>
      'La période de protection de 48h est en cours. Les fonds sont retenus jusqu\'à son terme.';

  @override
  String get deliveryPayoutReadyExplainer =>
      'La livraison est terminée et le versement est maintenant éligible.';

  @override
  String get deliveryPayoutProcessingExplainer =>
      'Le traitement du versement a commencé.';

  @override
  String get deliveryPayoutSentExplainer =>
      'Le versement a été envoyé et est en cours d\'acheminement.';

  @override
  String get deliveryPayoutPaidExplainer =>
      'Le versement a été crédité sur votre compte.';

  @override
  String get deliveryPayoutReturnedExplainer =>
      'Le virement a été retourné par la banque. Veuillez vérifier votre moyen de versement.';

  @override
  String get deliveryPayoutNeedsAttentionExplainer =>
      'Ce versement nécessite une action avant de pouvoir être réglé.';

  @override
  String payoutRateLabel(String rate) {
    return 'Taux figé : 1 EUR = $rate DZD';
  }

  @override
  String get payoutHistoryTitle => 'Historique des versements';

  @override
  String get payoutDetailTitle => 'Détail du versement';

  @override
  String get payoutRailLabel => 'Méthode de versement';

  @override
  String get payoutRailStripeEur => 'Stripe EUR';

  @override
  String get payoutRailManualDzd => 'Virement CCP (DZD)';

  @override
  String get payoutRailUnavailable => 'Non disponible';

  @override
  String get payoutReferenceLabel => 'Référence du versement';

  @override
  String get payoutDeliveryLabel => 'Livraison associée';

  @override
  String get payoutEligibleAtLabel => 'Éligible le';

  @override
  String get payoutSentAtLabel => 'Envoyé le';

  @override
  String get payoutPaidAtLabel => 'Payé le';

  @override
  String get payoutProtectionEndsAtLabel => 'Fin de protection';

  @override
  String get payoutViewAction => 'Voir le versement';

  @override
  String get payoutViewHistoryAction => 'Voir l\'historique des versements';

  @override
  String get payoutOpenStripeError =>
      'Impossible d\'ouvrir le lien Stripe. Veuillez réessayer.';

  @override
  String get payoutStatusAwaitingDelivery => 'En attente de livraison';

  @override
  String get payoutStatusProtectionActive => 'Période de protection';

  @override
  String get payoutStatusReleasePending => 'En attente de déblocage';

  @override
  String get payoutStatusReady => 'Versement prêt';

  @override
  String get payoutStatusSent => 'Versement envoyé';

  @override
  String get payoutStatusReturned => 'Versement retourné';

  @override
  String get payoutStatusNeedsAttention => 'Action requise';

  @override
  String get payoutProfileReady => 'Moyen de versement prêt';

  @override
  String get payoutProfileNeedsAttention => 'Moyen de versement à vérifier';

  @override
  String get payoutReasonScheduledArrivalPending =>
      'En attente de la date d\'arrivée prévue';

  @override
  String get deliveryPayoutScheduledArrivalPendingExplainer =>
      'La protection de livraison de 48h est terminée, mais le versement reste retenu jusqu\'à la date d\'arrivée prévue convenue lors du financement.';

  @override
  String get earlyArrivalAction => 'Je suis arrivé en avance';

  @override
  String get earlyArrivalConfirmSheetTitle => 'Signaler une arrivée anticipée';

  @override
  String get earlyArrivalConfirmSheetBody =>
      'Cette action informe l\'expéditeur de votre arrivée avant l\'horaire prévu. Elle ne confirme pas la livraison du colis. L\'expéditeur doit confirmer votre arrivée et le calendrier de versement reste soumis aux règles de protection ShipTrip.';

  @override
  String get earlyArrivalWaitingSenderTitle =>
      'En attente de confirmation de l\'expéditeur';

  @override
  String get earlyArrivalWaitingSenderBody =>
      'Vous avez signalé votre arrivée anticipée. L\'expéditeur a été invité à la confirmer. La remise et la livraison restent distinctes.';

  @override
  String get earlyArrivalSenderNoticeTitle =>
      'Le voyageur indique être arrivé en avance';

  @override
  String get earlyArrivalSenderNoticeBody =>
      'Le voyageur a signalé son arrivée anticipée pour cette livraison. Confirmer l\'arrivée atteste de sa présence ; la livraison du colis et la protection du versement restent distinctes.';

  @override
  String get earlyArrivalConfirmAction => 'Confirmer l\'arrivée';

  @override
  String get earlyArrivalDeclineAction => 'Refuser';

  @override
  String get earlyArrivalConfirmedTitle => 'Arrivée confirmée';

  @override
  String get earlyArrivalConfirmedBody =>
      'L\'arrivée anticipée est confirmée. La livraison du colis et la protection de 48h ne débuteront qu\'après vérification du code de livraison.';

  @override
  String get earlyArrivalDeclinedTitle => 'Arrivée anticipée non confirmée';

  @override
  String get earlyArrivalDeclinedBody =>
      'Le signalement d\'arrivée anticipée n\'a pas été confirmé. La livraison se poursuivra selon l\'itinéraire prévu.';

  @override
  String get earlyArrivalScheduledArrivalLabel =>
      'Arrivée prévue pour cette livraison';

  @override
  String get earlyArrivalReportedTimeLabel => 'Arrivée signalée';

  @override
  String get earlyArrivalEarlyByLabel => 'En avance de';

  @override
  String get earlyArrivalPayoutFloorExplanation =>
      'Arriver en avance ne rend pas le versement disponible plus tôt que la date de protection prévue pour cette livraison.';

  @override
  String get earlyArrivalPayoutProtectedGateLabel =>
      'Versement éligible à partir du';

  @override
  String get routeTitle => 'Itinéraire';

  @override
  String get routeUnavailableFunded =>
      'L’itinéraire de voyage n’a pas été enregistré pour cette livraison.';

  @override
  String get routeUnavailableBeforeFunding =>
      'L’itinéraire de voyage apparaît ici une fois la livraison financée.';

  @override
  String get routeFlightMode => 'Vol';

  @override
  String get routeDriveMode => 'Trajet routier';

  @override
  String get routeDepartureLabel => 'Départ';

  @override
  String get routeArrivalLabel => 'Arrivée';

  @override
  String get routeCarryingLegsOnly =>
      'Itinéraire de transport pour cette livraison';

  @override
  String get notificationArrivalReported => 'Le voyageur est arrivé en avance';

  @override
  String get notificationArrivalReportedBody =>
      'Ouvrez ShipTrip pour confirmer l\'arrivée anticipée.';

  @override
  String get notificationArrivalConfirmed => 'Arrivée anticipée confirmée';

  @override
  String get notificationArrivalConfirmedBody =>
      'L\'expéditeur a confirmé votre arrivée. La livraison reste à venir.';

  @override
  String get notificationArrivalDeclined => 'Arrivée anticipée non confirmée';

  @override
  String get notificationArrivalDeclinedBody =>
      'Ouvrez ShipTrip pour consulter la livraison.';

  @override
  String get routeBasisSnapshot => 'Figé à la réservation';

  @override
  String get routeBasisLive => 'Trajet en direct';

  @override
  String get pricingMinimumLabel => 'Prix minimum';

  @override
  String get pricingRecommendedLabel => 'Prix recommandé';

  @override
  String get pricingYourOfferLabel => 'Votre offre';

  @override
  String get pricingBelowRecommended =>
      'En dessous du montant recommandé — les voyageurs peuvent mettre plus de temps à accepter.';

  @override
  String get pricingCompetitive =>
      'Offre compétitive — correspond plus rapidement avec les voyageurs.';

  @override
  String pricingBelowMinimumError(String amount) {
    return 'L\'offre doit être d\'au moins $amount';
  }

  @override
  String get pricingTravelerReceives => 'Le voyageur reçoit';

  @override
  String get pricingPlatformFee => 'Frais ShipTrip';

  @override
  String get pricingTotalSenderCost => 'Coût total expéditeur';

  @override
  String get pricingIncrement50c => 'Augmenter de 50 centimes';

  @override
  String get pricingDecrement50c => 'Diminuer de 50 centimes';

  @override
  String get depositSectionTitle => 'Acompte de publication';

  @override
  String depositPresetMin(String amount) {
    return 'Minimum ($amount)';
  }

  @override
  String depositPresetRecommended(String amount) {
    return 'Recommandé ($amount)';
  }

  @override
  String depositPresetFull(String amount) {
    return 'Payer en totalité ($amount)';
  }

  @override
  String get depositPresetCustom => 'Personnalisé';

  @override
  String get depositFullDepositNotice =>
      'Votre montant actuel est intégralement réglé. Si vous augmentez la récompense ou le Boost plus tard, un solde supplémentaire pourra être dû.';

  @override
  String get depositRemainingBalance => 'Solde restant à la livraison';

  @override
  String get depositCustomAmountLabel => 'Montant d\'acompte personnalisé';

  @override
  String get boostSectionTitle => 'Booster cette demande';

  @override
  String get boostPresetNone => 'Sans Boost (0 €)';

  @override
  String get boostPreset5 => '+5 €';

  @override
  String get boostPreset10 => '+10 €';

  @override
  String get boostPresetCustom => 'Personnalisé';

  @override
  String get boostCustomAmountLabel => 'Montant du Boost personnalisé';

  @override
  String boostCurrentActive(String amount) {
    return 'Boost actif : $amount';
  }

  @override
  String get boostEditAction => 'Modifier le Boost';

  @override
  String get boostRemoveAction => 'Supprimer le Boost';

  @override
  String get boostHistoryTitle => 'Historique du Boost';

  @override
  String boostHistoryChanged(String from, String to) {
    return 'Modifié de $from à $to';
  }

  @override
  String get boostNotEditable =>
      'Le Boost ne peut plus être modifié une fois une offre acceptée ou la demande expirée.';

  @override
  String get guestPaymentTitle => 'Faire payer par un proche';

  @override
  String get guestPaymentDescription =>
      'Partagez un lien sécurisé. Toute personne ayant le lien peut régler ce montant sans avoir besoin d\'un compte ShipTrip.';

  @override
  String get guestPaymentShareButton => 'Partager le lien de paiement';

  @override
  String get guestPaymentCopyButton => 'Copier le lien';

  @override
  String get guestPaymentCopied =>
      'Lien de paiement copié dans le presse-papiers';

  @override
  String guestPaymentExpires(String expiry) {
    return 'Le lien expire le $expiry';
  }

  @override
  String get guestPaymentRevokeAction => 'Révoquer le lien';

  @override
  String get guestPaymentRevokeConfirmTitle =>
      'Révoquer le lien de paiement invité ?';

  @override
  String get guestPaymentRevokeConfirmBody =>
      'Toute personne disposant de ce lien ne pourra plus payer. Vous pouvez générer un nouveau lien à tout moment.';

  @override
  String get guestPaymentPaidNotice => 'Payé par un tiers';

  @override
  String get paymentSuccessTitle => 'Paiement sécurisé';

  @override
  String get paymentSuccessWaxSeal => 'Sécurisé';

  @override
  String get paymentSuccessReceiptTitle => 'Reçu de paiement';

  @override
  String get paymentSuccessAmountPaid => 'Montant payé';

  @override
  String get paymentSuccessDepositCredit => 'Acompte crédité';

  @override
  String get paymentSuccessPaidBySelf => 'Payé par vous';

  @override
  String get paymentSuccessPaidByGuest => 'Payé par un tiers';

  @override
  String get paymentSuccessRemainingDue => 'Solde restant dû à la livraison';

  @override
  String get paymentSuccessNextStepsTitle => 'Que se passe-t-il ensuite ?';

  @override
  String get paymentSuccessDepositNextBody =>
      'Votre demande est active. Les voyageurs sur votre trajet peuvent désormais matcher.';

  @override
  String get paymentSuccessDealNextBody =>
      'Votre livraison est financée. Le voyageur vous retrouvera au point de rendez-vous convenu.';

  @override
  String get paymentSuccessViewRequestAction => 'Voir la demande';

  @override
  String get paymentSuccessViewDeliveryAction => 'Voir la livraison';

  @override
  String get notificationDepositPaidTitle => 'Acompte confirmé';

  @override
  String get notificationDepositPaidBody =>
      'Votre demande de livraison est maintenant active et visible pour les voyageurs.';

  @override
  String get notificationDealFundedTitle => 'Livraison financée';

  @override
  String get notificationDealFundedBody =>
      'Paiement sécurisé. Retrouvez votre voyageur au point de collecte convenu.';

  @override
  String get notificationPayoutReadyTitle => 'Versement prêt';

  @override
  String get notificationPayoutReadyBody =>
      'Vos gains pour cette livraison sont prêts pour le transfert.';

  @override
  String get notificationPayoutSentTitle => 'Versement envoyé';

  @override
  String get notificationPayoutSentBody =>
      'Votre versement a été transféré avec succès.';

  @override
  String get boostBreakdownTitle => 'Ce que coûte le Boost';

  @override
  String get boostTravelerBonusLabel => 'Ajouté à la récompense du voyageur';

  @override
  String get boostYourCostLabel => 'Vous payez pour le Boost';

  @override
  String get boostAddsOnTop =>
      'Le Boost s\'ajoute à la récompense de livraison que vous avez déjà proposée. Récompense de base + Boost, c\'est ce que le voyageur reçoit.';

  @override
  String get boostEstimateNotice =>
      'Une estimation jusqu\'à l\'enregistrement. ShipTrip confirme les montants définitifs.';

  @override
  String boostAmountAboveMaximum(String amount) {
    return 'Le Boost maximum est de $amount';
  }

  @override
  String get boostHistoryReasonSenderSet => 'Vous avez ajouté un Boost';

  @override
  String get boostHistoryReasonSenderIncreased => 'Vous avez augmenté le Boost';

  @override
  String get boostHistoryReasonSenderDecreased => 'Vous avez réduit le Boost';

  @override
  String get boostHistoryReasonSenderRemoved => 'Vous avez retiré le Boost';

  @override
  String get boostHistoryReasonFrozen =>
      'Verrouillé lors de la conclusion de la livraison';

  @override
  String get boostHistoryReasonConsumed =>
      'Inclus dans le paiement de la livraison';

  @override
  String get boostHistoryReasonReleased =>
      'Libéré lorsque l\'accord n\'a pas abouti';

  @override
  String get boostHistoryReasonRequestClosed => 'Terminé avec la demande';

  @override
  String get boostHistoryReasonOther => 'Boost mis à jour';

  @override
  String get guestPaymentAmountDue => 'Montant dû';

  @override
  String get guestPaymentLinkFailed =>
      'Impossible de créer le lien de paiement. Réessayez.';

  @override
  String get paymentSuccessPayerYou => 'Vous';

  @override
  String get paymentSuccessPayerGuest => 'Quelqu’un d’autre';

  @override
  String get paymentSuccessPaidByLabel => 'Payé par';

  @override
  String findTravelersCount(int count) {
    final intl.NumberFormat countNumberFormat = intl.NumberFormat.compact(
      locale: localeName,
    );
    final String countString = countNumberFormat.format(count);

    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$countString voyageurs',
      one: '1 voyageur',
    );
    return '$_temp0';
  }

  @override
  String get findTravelersIneligibleUnknown =>
      'Cette demande ne peut pas être mise en relation pour le moment.';

  @override
  String get findTravelersPayDeposit => 'Payer l\'acompte';

  @override
  String findTravelersDepartureLabel(String when) {
    return 'Départ $when';
  }

  @override
  String findTravelersArrivalLabel(String when) {
    return 'Arrivée $when';
  }

  @override
  String get findTravelersTrustTitle => 'Vérifications faites par ShipTrip';

  @override
  String get offerBaseRewardLabel => 'Récompense de base';

  @override
  String offerBoostAddedOnTop(String amount) {
    return 'Votre Boost de $amount vient s’ajouter à ce montant.';
  }

  @override
  String get deliveriesOpenOffersSection => 'Offres en cours';

  @override
  String get journeyPostNew => 'Publier un trajet';

  @override
  String depositBelowMinimum(String amount) {
    return 'L\'acompte minimum est de $amount';
  }

  @override
  String depositAboveMaximum(String amount) {
    return 'C\'est plus que le montant total de $amount';
  }

  @override
  String offerBoostIncludedTraveler(String amount) {
    return 'Inclut le Boost de l’expéditeur de $amount. Le total est fixé au moment où vous acceptez.';
  }

  @override
  String offerBoostIncludedSender(String amount) {
    return 'Inclut votre Boost de $amount, fixé lorsque cette offre est acceptée. Modifier votre Boost avant cela met à jour cette offre.';
  }

  @override
  String offerSenderBoostAddedOnTop(String amount) {
    return 'Le Boost de l’expéditeur de $amount vient s’ajouter à ce montant.';
  }

  @override
  String offerHistoryBaseReward(String title, String amount) {
    return '$title : rémunération de base $amount';
  }

  @override
  String get moneyTotalExcludingBoost => 'Total hors Boost';

  @override
  String get staleOfferEconomicsChanged =>
      'Les montants de cette offre ont changé. Vérifiez les nouveaux montants avant d’accepter.';

  @override
  String get offerEconomicsUpdated =>
      'Offre mise à jour. Ces montants sont les plus récents.';
}
