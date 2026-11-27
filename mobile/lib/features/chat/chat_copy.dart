/// Words the chat screens share.
library;

import '../../domain/chat.dart';
import '../../domain/person_photo.dart';
import '../../l10n/app_localizations.dart';

/// The other member's name, or "Deleted account" once they deleted it.
String chatCounterpartyName(L l, ChatThread thread) =>
    thread.counterpartyDeleted ? l.chatDeletedAccount : thread.counterpartyName;

/// The other member's photo, or none once their account is deleted: a deleted
/// account is shown by initials only, whatever the thread row still carries.
PersonPhoto? chatCounterpartyPhoto(ChatThread thread) =>
    thread.counterpartyDeleted ? null : thread.counterpartyPhoto;

/// How the app words each report reason.
String chatReportReasonLabel(L l, ChatReportReason reason) => switch (reason) {
  ChatReportReason.spam => l.chatReportReasonSpam,
  ChatReportReason.harassment => l.chatReportReasonHarassment,
  ChatReportReason.scam => l.chatReportReasonScam,
  ChatReportReason.inappropriate => l.chatReportReasonInappropriate,
  ChatReportReason.other => l.chatReportReasonOther,
};
