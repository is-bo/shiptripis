/// One conversation.
///
/// ## Why the composer is gated on the server, not on a status
///
/// Chat opens when the deal is **funded**, and the server says so in two
/// places: `can_send` on the thread, and a `402` with `{"reason":
/// "payment_pending"}` if a send is attempted anyway. Note the field is
/// `reason`, not the `code` used everywhere else in the API, and the body
/// carries no human string at all — so the copy for that state is written
/// here, keyed off [ChatBlockReason].
///
/// `payment_pending` is the one block a user can act on, and only the sender
/// can act on it. The screen therefore turns that refusal into a route to the
/// payment screen rather than a dead composer with a shrug.
///
/// ## Report and block
///
/// A member presses and holds a message they received to report it, and may
/// block the sender in the same step. The top bar's menu blocks or unblocks
/// the other member. A block stops sending both ways and keeps the history
/// readable; the server decides, and the screen reads its answer again.
///
/// ## Full screen, no tab bar
///
/// A composer, a keyboard and a navigation bar are three fixed strips at the
/// bottom of a small phone. The tab bar earns its place least while somebody
/// is typing, so this route sits above the shell.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/chat.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import 'chat_copy.dart';
import 'chat_thread_controller.dart';

class ChatThreadScreen extends ConsumerStatefulWidget {
  const ChatThreadScreen({required this.matchId, this.dealId, super.key});

  final int matchId;
  final int? dealId;

  @override
  ConsumerState<ChatThreadScreen> createState() => _ChatThreadScreenState();
}

class _ChatThreadScreenState extends ConsumerState<ChatThreadScreen> {
  final _composer = TextEditingController();
  final _scroll = ScrollController();
  bool _loadingOlderFromScroll = false;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_loadOlderAtTop);
  }

  @override
  void dispose() {
    _composer.dispose();
    _scroll.dispose();
    super.dispose();
  }

  ChatThread? _threadFrom(List<ChatThread> threads) {
    for (final thread in threads) {
      if (thread.matchId == widget.matchId) return thread;
    }
    return null;
  }

  Future<void> _send() async {
    final body = _composer.text.trim();
    final controller = ref.read(chatThreadControllerProvider(widget.matchId));
    if (body.isEmpty || controller.isSending) return;

    // Clear only once the controller has actually taken the message. It
    // silently refuses when the conversation is not (or no longer) sendable,
    // and clearing regardless threw the user's typed text away with nothing on
    // screen to show for it.
    if (!controller.canAcceptSend(body)) return;
    final result = controller.send(body);
    _composer.clear();
    _scrollToBottom();
    final error = await result;
    if (!mounted || error == null) return;
    if (!_explainedOnScreen(controller.sendBlock)) {
      AppSnack.failure(context, error);
    }
  }

  /// Refusals the notice above the composer already words.
  static bool _explainedOnScreen(ChatBlockReason reason) =>
      reason == ChatBlockReason.paymentPending ||
      reason == ChatBlockReason.blocked;

  Future<void> _retry(PendingChatMessage message) async {
    final controller = ref.read(chatThreadControllerProvider(widget.matchId));
    final error = await controller.retry(message);
    if (!mounted || error == null) return;
    if (!_explainedOnScreen(controller.sendBlock)) {
      AppSnack.failure(context, error);
    }
  }

  Future<void> _openMenu(ChatThreadController controller) async {
    final l = L.of(context);
    final blockedByMe = controller.eligibility?.blockedByMe ?? false;
    final choice = await showAppSheet<bool>(
      context,
      builder: (_) => AppChoiceSheet<bool>(
        title: l.chatSafetyTitle,
        subtitle: l.chatSafetySubtitle,
        selected: null,
        options: [
          AppSheetOption(
            value: !blockedByMe,
            label: blockedByMe ? l.chatUnblockAction : l.chatBlockAction,
            detail: blockedByMe
                ? l.chatUnblockActionDetail
                : l.chatBlockActionDetail,
            icon: blockedByMe ? Icons.lock_open_rounded : Icons.block_rounded,
          ),
        ],
      ),
    );
    if (!mounted || choice == null) return;
    if (choice) {
      await _block(controller);
    } else {
      await _unblock(controller);
    }
  }

  Future<void> _block(ChatThreadController controller) async {
    final l = L.of(context);
    final confirmed = await confirmAction(
      context,
      title: l.chatBlockConfirmTitle,
      body: l.chatBlockConfirmBody,
      confirmLabel: l.chatBlockAction,
      isDestructive: true,
    );
    if (!mounted || !confirmed) return;
    try {
      await controller.block();
      if (mounted) AppSnack.success(context, l.chatBlockDone);
    } on Object catch (error) {
      if (mounted) AppSnack.failure(context, error);
    }
  }

  Future<void> _unblock(ChatThreadController controller) async {
    final l = L.of(context);
    try {
      await controller.unblock();
      if (mounted) AppSnack.success(context, l.chatUnblockDone);
    } on Object catch (error) {
      if (mounted) AppSnack.failure(context, error);
    }
  }

  Future<void> _report(
    ChatThreadController controller,
    ChatMessage message,
  ) async {
    final l = L.of(context);
    final sent = await showAppSheet<bool>(
      context,
      builder: (_) => _ReportSheet(
        canBlock: !(controller.eligibility?.blockedByMe ?? false),
        onSubmit: (reason, note, alsoBlock) => controller.report(
          message,
          reason: reason,
          note: note,
          alsoBlock: alsoBlock,
        ),
      ),
    );
    if (mounted && sent == true) AppSnack.success(context, l.chatReportSent);
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.animateTo(
        0,
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
      );
    });
  }

  void _loadOlderAtTop() {
    if (!_scroll.hasClients || _loadingOlderFromScroll) return;
    final position = _scroll.position;
    if (position.pixels < position.maxScrollExtent - 120) return;
    final controller = ref.read(chatThreadControllerProvider(widget.matchId));
    if (!controller.hasMoreOlder || controller.isLoadingOlder) return;

    _loadingOlderFromScroll = true;
    final oldPixels = position.pixels;
    unawaited(
      controller.loadOlder().whenComplete(() {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _loadingOlderFromScroll = false;
          if (!mounted || !_scroll.hasClients) return;
          final newMaximum = _scroll.position.maxScrollExtent;
          _scroll.jumpTo(oldPixels.clamp(0, newMaximum));
        });
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    ref.listen<int?>(accountProvider.select((value) => value?.id), (
      previous,
      next,
    ) {
      if (previous != next) _composer.clear();
    });
    final threads = ref.watch(chatThreadsProvider);
    final thread = _threadFrom(threads.value ?? const <ChatThread>[]);
    final controller = ref.watch(chatThreadControllerProvider(widget.matchId));
    ref.listen<int>(
      chatThreadControllerProvider(
        widget.matchId,
      ).select((value) => value.latestMessageId),
      (previous, next) {
        if (next > (previous ?? 0) &&
            (!_scroll.hasClients || _scroll.offset <= 80)) {
          _scrollToBottom();
        }
      },
    );
    final eligibility = controller.eligibility;
    final canSend = eligibility?.eligible ?? false;
    final blocked = !canSend || controller.sendBlock != ChatBlockReason.ok;
    final dealId = widget.dealId ?? thread?.dealId;
    // Blocking someone who deleted their account changes nothing.
    final offersSafety =
        eligibility?.canReadHistory == true &&
        thread?.counterpartyDeleted != true;

    return AppScaffold(
      topBar: AppTopBar(
        title: thread == null ? l.chatTitle : chatCounterpartyName(l, thread),
        subtitle: thread?.route,
        // No avatar while the thread row is unknown: nothing to draw yet.
        titleLeading: thread == null
            ? null
            : AppAvatar(
                initials: initialsFor(chatCounterpartyName(l, thread)),
                name: chatCounterpartyName(l, thread),
                photo: chatCounterpartyPhoto(thread),
                size: 32,
              ),
        showBack: true,
        actions: [
          if (thread?.dealId != null)
            AppIconButton(
              icon: Icons.inventory_2_outlined,
              label: l.deliveriesTitle,
              onPressed: () => context.openDeal(thread!.dealId!),
            ),
          if (offersSafety)
            AppIconButton(
              icon: Icons.more_vert_rounded,
              label: l.chatSafetyTitle,
              onPressed: () => _openMenu(controller),
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: Builder(
              builder: (context) {
                if (controller.isInitialLoading) {
                  return const Padding(
                    padding: EdgeInsets.all(AppSpace.gutter),
                    child: SkeletonLines(count: 6, spacing: AppSpace.xl),
                  );
                }
                if (controller.initialError case final error?) {
                  return AppErrorState(
                    error: error,
                    onRetry: controller.reload,
                  );
                }
                if (eligibility == null) {
                  return const SizedBox.shrink();
                }
                if (!eligibility.canReadHistory) {
                  return _ChatUnavailableState(
                    reason: eligibility.reason,
                    dealId: dealId,
                  );
                }

                final messages = controller.messages;
                final pending = controller.pendingMessages;
                if (messages.isEmpty && pending.isEmpty) {
                  return AppEmptyState(
                    title: l.chatThreadEmptyTitle,
                    body: l.chatThreadEmptyBody,
                    icon: Icons.forum_outlined,
                  );
                }

                final items = <Object>[
                  ...pending.reversed,
                  ...messages.reversed,
                ];

                return ListView.builder(
                  controller: _scroll,
                  reverse: true,
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpace.gutter,
                    vertical: AppSpace.lg,
                  ),
                  itemCount:
                      items.length + 1 + (controller.isLoadingOlder ? 1 : 0),
                  itemBuilder: (context, index) {
                    if (index == items.length) return const _CodeWarning();
                    if (index > items.length) {
                      return const Padding(
                        padding: EdgeInsets.all(AppSpace.md),
                        child: Center(child: CircularProgressIndicator()),
                      );
                    }
                    final item = items[index];
                    if (item is PendingChatMessage) {
                      return _PendingBubble(
                        message: item,
                        onRetry: controller.canSend ? () => _retry(item) : null,
                      );
                    }
                    final message = item as ChatMessage;
                    final isMine =
                        account != null && message.isMine(account.id);
                    return _Bubble(
                      message: message,
                      isMine: isMine,
                      onReport: isMine || message.removed || !offersSafety
                          ? null
                          : () => _report(controller, message),
                    );
                  },
                );
              },
            ),
          ),
          if (!controller.isInitialLoading &&
              eligibility?.canReadHistory == true &&
              blocked)
            _BlockedNotice(
              reason: controller.sendBlock == ChatBlockReason.ok
                  ? eligibility!.reason
                  : controller.sendBlock,
              dealId: dealId,
              blockedByMe: eligibility?.blockedByMe ?? false,
              onUnblock: () => _unblock(controller),
            ),
        ],
      ),
      footer: blocked
          ? null
          : _Composer(
              controller: _composer,
              sending: controller.isSending,
              onSend: _send,
            ),
    );
  }
}

/// A normal gate state, distinct from a transport failure. In particular,
/// `payment_pending` is not rendered as a raw 402/403 or as an empty white
/// screen: it names what is waiting and, when the originating Deal is known,
/// gives the sender the payment action.
class _ChatUnavailableState extends StatelessWidget {
  const _ChatUnavailableState({required this.reason, this.dealId});

  final ChatBlockReason reason;
  final int? dealId;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final paymentPending = reason == ChatBlockReason.paymentPending;
    return AppEmptyState(
      title: paymentPending ? l.chatUnavailableTitle : l.chatClosedTitle,
      body: paymentPending ? l.chatUnavailableBody : l.chatClosedBody,
      icon: paymentPending
          ? Icons.credit_card_rounded
          : Icons.lock_outline_rounded,
      actionLabel: paymentPending && dealId != null
          ? l.chatBlockedPayAction
          : null,
      onAction: paymentPending && dealId != null
          ? () => context.openDealPayment(dealId!)
          : null,
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.sending,
    required this.onSend,
  });

  final TextEditingController controller;
  final bool sending;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: TextField(
            controller: controller,
            maxLines: 5,
            minLines: 1,
            maxLength: 2000,
            textCapitalization: TextCapitalization.sentences,
            textInputAction: TextInputAction.newline,
            decoration: InputDecoration(
              hintText: l.chatComposerHint,
              counterText: '',
              helperText: null,
              isDense: true,
            ),
          ),
        ),
        const SizedBox(width: AppSpace.sm),
        AppIconButton(
          icon: Icons.send_rounded,
          label: l.chatSend,
          tone: c.brandInk,
          onPressed: sending ? null : onSend,
        ),
      ],
    );
  }
}

/// Why the composer is missing, and what to do about it.
class _BlockedNotice extends StatelessWidget {
  const _BlockedNotice({
    required this.reason,
    required this.blockedByMe,
    required this.onUnblock,
    this.dealId,
  });

  final ChatBlockReason reason;
  final int? dealId;
  final bool blockedByMe;
  final VoidCallback onUnblock;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    if (reason == ChatBlockReason.blocked) {
      return AppFooterBar(
        child: InfoNotice(
          title: blockedByMe ? l.chatBlockedByMeTitle : l.chatBlockedTitle,
          message: blockedByMe ? l.chatBlockedByMeBody : l.chatBlockedBody,
          tone: StatusTone.neutral,
          icon: Icons.block_rounded,
          actionLabel: blockedByMe ? l.chatUnblockAction : null,
          onAction: blockedByMe ? onUnblock : null,
        ),
      );
    }

    final (title, body, action) = switch (reason) {
      // The only one a user can fix, and only the sender can fix it.
      ChatBlockReason.paymentPending => (
        l.chatUnavailableTitle,
        l.chatUnavailableBody,
        dealId == null ? null : l.chatBlockedPayAction,
      ),
      ChatBlockReason.noAcceptedOffer => (
        l.chatUnavailableTitle,
        l.chatUnavailableBody,
        null,
      ),
      ChatBlockReason.matchClosed => (
        l.chatClosedTitle,
        l.chatClosedBody,
        null,
      ),
      ChatBlockReason.notAParty ||
      ChatBlockReason.blocked ||
      ChatBlockReason.productRequestRetired ||
      ChatBlockReason.unknown ||
      ChatBlockReason.ok => (l.chatClosedTitle, l.chatClosedBody, null),
    };

    return AppFooterBar(
      child: InfoNotice(
        title: title,
        message: body,
        tone: reason == ChatBlockReason.paymentPending
            ? StatusTone.action
            : StatusTone.neutral,
        icon: reason == ChatBlockReason.paymentPending
            ? Icons.credit_card_rounded
            : Icons.lock_outline_rounded,
        actionLabel: action,
        onAction: action == null || dealId == null
            ? null
            : () => context.openDealPayment(dealId!),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message, required this.isMine, this.onReport});

  final ChatMessage message;
  final bool isMine;

  /// Pressing and holding a received message reports it. Null for the
  /// viewer's own messages and for removed ones.
  final VoidCallback? onReport;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final when = message.createdAt;
    final removed = message.removed;
    final ink = removed
        ? c.textTertiary
        : isMine
        ? c.onBrand
        : c.textPrimary;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.md),
      child: Align(
        alignment: isMine
            ? AlignmentDirectional.centerEnd
            : AlignmentDirectional.centerStart,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.sizeOf(context).width * 0.76,
          ),
          child: _Reportable(
            onReport: onReport,
            child: Container(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpace.lg,
                vertical: AppSpace.md,
              ),
              decoration: BoxDecoration(
                color: removed
                    ? c.surfaceSunken
                    : isMine
                    ? c.brand
                    : c.surface,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(AppRadius.lg),
                  topRight: const Radius.circular(AppRadius.lg),
                  bottomLeft: Radius.circular(
                    isMine ? AppRadius.lg : AppRadius.xs,
                  ),
                  bottomRight: Radius.circular(
                    isMine ? AppRadius.xs : AppRadius.lg,
                  ),
                ),
                border: isMine && !removed
                    ? null
                    : Border.all(color: c.hairline),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (removed)
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.block_rounded, size: 16, color: ink),
                        const SizedBox(width: AppSpace.xs),
                        Flexible(
                          child: Text(
                            l.chatMessageRemoved,
                            style: text.bodyMedium?.copyWith(
                              color: ink,
                              fontStyle: FontStyle.italic,
                            ),
                          ),
                        ),
                      ],
                    )
                  else
                    Text(
                      message.body,
                      style: text.bodyMedium?.copyWith(color: ink),
                    ),
                  if (when != null) ...[
                    const SizedBox(height: AppSpace.xs),
                    Text(
                      LocaleFormats.time(locale, when),
                      style: text.labelSmall?.copyWith(
                        color: isMine && !removed
                            ? c.onBrand.withValues(alpha: 0.75)
                            : c.textTertiary,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Makes a received message reportable by pressing and holding it, for touch
/// and for screen readers alike.
class _Reportable extends StatelessWidget {
  const _Reportable({required this.onReport, required this.child});

  final VoidCallback? onReport;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (onReport == null) return child;
    return Semantics(
      onLongPressHint: L.of(context).chatReportTitle,
      child: GestureDetector(onLongPress: onReport, child: child),
    );
  }
}

class _PendingBubble extends StatelessWidget {
  const _PendingBubble({required this.message, required this.onRetry});

  final PendingChatMessage message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.md),
      child: Align(
        alignment: AlignmentDirectional.centerEnd,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.sizeOf(context).width * 0.76,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpace.lg,
                  vertical: AppSpace.md,
                ),
                decoration: BoxDecoration(
                  // Visibly not yet delivered: a lighter fill, so an unsent
                  // message never looks like a sent one.
                  color: message.hasFailed ? c.dangerSoft : c.brandSoft,
                  borderRadius: const BorderRadius.all(
                    Radius.circular(AppRadius.lg),
                  ),
                ),
                child: Text(
                  message.body,
                  style: text.bodyMedium?.copyWith(
                    color: message.hasFailed ? c.onDangerSoft : c.textPrimary,
                  ),
                ),
              ),
              const SizedBox(height: AppSpace.xs),
              if (message.hasFailed)
                TextButton(onPressed: onRetry, child: Text(l.chatRetrySend))
              else
                Text(
                  l.chatSending,
                  style: text.labelSmall?.copyWith(color: c.textTertiary),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// A standing reminder at the top of every thread.
///
/// A handover code read out in chat defeats the whole point of it, and chat is
/// exactly where somebody would think to put one.
class _CodeWarning extends StatelessWidget {
  const _CodeWarning();

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: AppSpace.xl),
    child: InfoNotice(
      message: L.of(context).chatNeverShareCodes,
      tone: StatusTone.waiting,
      icon: Icons.shield_outlined,
    ),
  );
}

/// Reporting one received message: a reason, an optional note, and whether
/// to block the sender in the same step. Pops `true` once the server took it.
class _ReportSheet extends StatefulWidget {
  const _ReportSheet({required this.canBlock, required this.onSubmit});

  /// False when the viewer already blocks the sender.
  final bool canBlock;
  final Future<void> Function(
    ChatReportReason reason,
    String note,
    bool alsoBlock,
  )
  onSubmit;

  @override
  State<_ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends State<_ReportSheet> {
  final _note = TextEditingController();
  ChatReportReason? _reason;
  bool _alsoBlock = false;
  bool _busy = false;
  bool _missingReason = false;
  Object? _error;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final reason = _reason;
    if (reason == null) {
      setState(() => _missingReason = true);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.onSubmit(reason, _note.text, widget.canBlock && _alsoBlock);
      if (mounted) Navigator.of(context).pop(true);
    } on Object catch (error) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = error;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppSheet(
      title: l.chatReportTitle,
      subtitle: l.chatReportSubtitle,
      footer: AppButton(
        label: l.chatReportSend,
        onPressed: _busy ? null : _submit,
        isLoading: _busy,
        expand: true,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l.chatReportReasonLabel, style: text.titleSmall),
          const SizedBox(height: AppSpace.sm),
          for (final reason in ChatReportReason.values)
            _ReasonRow(
              label: chatReportReasonLabel(l, reason),
              selected: reason == _reason,
              onTap: _busy
                  ? null
                  : () => setState(() {
                      _reason = reason;
                      _missingReason = false;
                    }),
            ),
          if (_missingReason)
            Padding(
              padding: const EdgeInsets.only(top: AppSpace.xs),
              child: Text(
                l.chatReportChooseReason,
                style: text.bodySmall?.copyWith(color: c.danger),
              ),
            ),
          const SizedBox(height: AppSpace.lg),
          AppTextField(
            label: l.chatReportNoteLabel,
            controller: _note,
            maxLines: 4,
            minLines: 2,
            maxLength: 500,
            enabled: !_busy,
            textCapitalization: TextCapitalization.sentences,
          ),
          if (widget.canBlock) ...[
            const SizedBox(height: AppSpace.sm),
            AppCheckTile(
              value: _alsoBlock,
              onChanged: (value) {
                if (!_busy) setState(() => _alsoBlock = value);
              },
              title: l.chatReportAlsoBlock,
              subtitle: l.chatReportAlsoBlockDetail,
            ),
          ],
          if (_error case final error?) ...[
            const SizedBox(height: AppSpace.md),
            InlineFailure(error: error),
          ],
        ],
      ),
    );
  }
}

class _ReasonRow extends StatelessWidget {
  const _ReasonRow({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    return Semantics(
      inMutuallyExclusiveGroup: true,
      checked: selected,
      button: true,
      label: label,
      onTap: onTap,
      child: ExcludeSemantics(
        child: InkWell(
          onTap: onTap,
          borderRadius: AppRadius.rSm,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: AppSpace.minTapTarget),
            child: Row(
              children: [
                Icon(
                  selected
                      ? Icons.radio_button_checked_rounded
                      : Icons.radio_button_unchecked_rounded,
                  color: selected ? c.brandInk : c.textTertiary,
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(child: Text(label, style: text.bodyLarge)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
