/// Words the chat screens share.
library;

import '../../domain/chat.dart';
import '../../l10n/app_localizations.dart';

/// The other member's name, or "Deleted account" once they deleted it.
String chatCounterpartyName(L l, ChatThread thread) =>
    thread.counterpartyDeleted ? l.chatDeletedAccount : thread.counterpartyName;

/// How the app words each report reason.
String chatReportReasonLabel(L l, ChatReportReason reason) => switch (reason) {
  ChatReportReason.spam => l.chatReportReasonSpam,
  ChatReportReason.harassment => l.chatReportReasonHarassment,
  ChatReportReason.scam => l.chatReportReasonScam,
  ChatReportReason.inappropriate => l.chatReportReasonInappropriate,
  ChatReportReason.other => l.chatReportReasonOther,
};
