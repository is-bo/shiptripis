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
/// ## Full screen, no tab bar
///
/// A composer, a keyboard and a navigation bar are three fixed strips at the
/// bottom of a small phone. The tab bar earns its place least while somebody
/// is typing, so this route sits above the shell.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/chat.dart';
import '../../l10n/app_localizations.dart';

final _messagesProvider = FutureProvider.autoDispose
    .family<ChatMessagePage, int>((ref, matchId) async {
      final repo = ref.watch(chatRepositoryProvider);
      // Reading also marks the other party's messages read, server-side, so
      // the unread badge has to be re-read afterwards.
      final page = await repo.messages(matchId: matchId);
      ref.invalidate(chatThreadsProvider);
      return page;
    });

class ChatThreadScreen extends ConsumerStatefulWidget {
  const ChatThreadScreen({required this.matchId, super.key});

  final int matchId;

  @override
  ConsumerState<ChatThreadScreen> createState() => _ChatThreadScreenState();
}

class _ChatThreadScreenState extends ConsumerState<ChatThreadScreen> {
  final _composer = TextEditingController();
  final _scroll = ScrollController();

  /// Messages the user has written that the server has not acknowledged.
  /// Deliberately a separate list from [ChatMessage] so a pending bubble can
  /// never be mistaken for a delivered one.
  final _pending = <PendingChatMessage>[];

  bool _sending = false;
  ChatBlockReason _block = ChatBlockReason.ok;
  int _localCounter = 0;

  @override
  void dispose() {
    _composer.dispose();
    _scroll.dispose();
    super.dispose();
  }

  ChatThread? get _thread {
    final threads = ref.read(chatThreadsProvider).value ?? const <ChatThread>[];
    for (final thread in threads) {
      if (thread.matchId == widget.matchId) return thread;
    }
    return null;
  }

  Future<void> _send() async {
    final body = _composer.text.trim();
    if (body.isEmpty || _sending) return;

    final local = PendingChatMessage(
      localId: 'local-${_localCounter++}',
      body: body,
      createdAt: DateTime.now(),
    );
    setState(() {
      _pending.add(local);
      _composer.clear();
      _sending = true;
    });

    try {
      await ref
          .read(chatRepositoryProvider)
          .send(matchId: widget.matchId, body: body);
      if (!mounted) return;
      setState(() {
        _pending.removeWhere((m) => m.localId == local.localId);
        _block = ChatBlockReason.ok;
      });
      ref
        ..invalidate(_messagesProvider(widget.matchId))
        ..invalidate(chatThreadsProvider);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        final index = _pending.indexWhere((m) => m.localId == local.localId);
        if (index >= 0) _pending[index] = _pending[index].failed();
        // The 402 body's `reason` lands in extras; anything else keeps the
        // generic failure path.
        if (error.statusCode == 402) {
          _block = ChatBlockReason.parse(error.extras['reason']);
        }
      });
      if (error.statusCode != 402) AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _retry(PendingChatMessage message) {
    setState(() {
      _pending.removeWhere((m) => m.localId == message.localId);
      _composer.text = message.body;
    });
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final page = ref.watch(_messagesProvider(widget.matchId));
    final thread = _thread;

    final canSend = thread?.canSend ?? true;
    final blocked = !canSend || _block != ChatBlockReason.ok;

    return AppScaffold(
      topBar: AppTopBar(
        title: thread?.counterpartyName ?? l.chatTitle,
        subtitle: thread?.route,
        showBack: true,
        actions: [
          if (thread?.dealId != null)
            AppIconButton(
              icon: Icons.inventory_2_outlined,
              label: l.deliveriesTitle,
              onPressed: () => context.openDeal(thread!.dealId!),
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: AsyncView<ChatMessagePage>(
              value: page,
              onRetry: () => ref.invalidate(_messagesProvider(widget.matchId)),
              loading: () => const Padding(
                padding: EdgeInsets.all(AppSpace.gutter),
                child: SkeletonLines(count: 6, spacing: AppSpace.xl),
              ),
              data: (data) {
                if (data.messages.isEmpty && _pending.isEmpty) {
                  return AppEmptyState(
                    title: l.chatThreadEmptyTitle,
                    body: l.chatThreadEmptyBody,
                    icon: Icons.forum_outlined,
                  );
                }

                // Newest at the bottom, which is what a conversation is; the
                // list is reversed so it opens at the latest message and grows
                // upward without a scroll jump.
                final items = <Object>[
                  ..._pending.reversed,
                  ...data.messages.reversed,
                ];

                return ListView.builder(
                  controller: _scroll,
                  reverse: true,
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpace.gutter,
                    vertical: AppSpace.lg,
                  ),
                  itemCount: items.length + 1,
                  itemBuilder: (context, index) {
                    if (index == items.length) return const _CodeWarning();
                    final item = items[index];
                    if (item is PendingChatMessage) {
                      return _PendingBubble(
                        message: item,
                        onRetry: () => _retry(item),
                      );
                    }
                    final message = item as ChatMessage;
                    return _Bubble(
                      message: message,
                      isMine: account != null && message.isMine(account.id),
                    );
                  },
                );
              },
            ),
          ),
          if (blocked)
            _BlockedNotice(
              reason: _block == ChatBlockReason.ok
                  ? ChatBlockReason.matchClosed
                  : _block,
              dealId: thread?.dealId,
            ),
        ],
      ),
      footer: blocked
          ? null
          : _Composer(controller: _composer, sending: _sending, onSend: _send),
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
          tone: c.brand,
          onPressed: sending ? null : onSend,
        ),
      ],
    );
  }
}

/// Why the composer is missing, and what to do about it.
class _BlockedNotice extends StatelessWidget {
  const _BlockedNotice({required this.reason, this.dealId});

  final ChatBlockReason reason;
  final int? dealId;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

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
  const _Bubble({required this.message, required this.isMine});

  final ChatMessage message;
  final bool isMine;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final when = message.createdAt;

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
          child: Container(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpace.lg,
              vertical: AppSpace.md,
            ),
            decoration: BoxDecoration(
              color: isMine ? c.brand : c.surface,
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
              border: isMine ? null : Border.all(color: c.hairline),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  message.body,
                  style: text.bodyMedium?.copyWith(
                    color: isMine ? c.onBrand : c.textPrimary,
                  ),
                ),
                if (when != null) ...[
                  const SizedBox(height: AppSpace.xs),
                  Text(
                    LocaleFormats.time(locale, when),
                    style: text.labelSmall?.copyWith(
                      color: isMine
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
    );
  }
}

class _PendingBubble extends StatelessWidget {
  const _PendingBubble({required this.message, required this.onRetry});

  final PendingChatMessage message;
  final VoidCallback onRetry;

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
