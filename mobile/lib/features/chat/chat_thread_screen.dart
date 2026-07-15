/// Live 1:1 chat thread for a Match. Seeds history from Django, stays live
/// over `/ws/chat`, sends through the payment-gated Django write endpoint.
///
/// Reached via `/chat/:matchId`. Chat is payment-gated server-side; if the
/// deal isn't paid yet the send endpoint returns a stable reason the composer
/// surfaces (and the input is disabled to avoid a dead-end tap).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_notifier.dart';
import '../../core/chat/chat_providers.dart';
import '../../core/chat/chat_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/util/safe_back.dart';

class ChatThreadScreen extends ConsumerStatefulWidget {
  const ChatThreadScreen({super.key, required this.matchId});
  final int matchId;

  @override
  ConsumerState<ChatThreadScreen> createState() => _ChatThreadScreenState();
}

class _ChatThreadScreenState extends ConsumerState<ChatThreadScreen> {
  final _ctl = TextEditingController();
  final _scroll = ScrollController();

  @override
  void dispose() {
    _ctl.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _ctl.text.trim();
    if (text.isEmpty) return;
    final ok = await ref.read(chatThreadProvider(widget.matchId).notifier).send(text);
    if (ok) {
      _ctl.clear();
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 240),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(chatThreadProvider(widget.matchId));
    final authState = ref.watch(authNotifierProvider);
    final myId = authState is AuthSignedIn ? authState.user.id : null;

    // Auto-scroll when a new message arrives (WS or send).
    ref.listen(chatThreadProvider(widget.matchId).select((s) => s.messages.length),
        (_, _) => _scrollToBottom());

    return Scaffold(
      backgroundColor: AppColors.parchment,
      appBar: AppBar(
        backgroundColor: AppColors.parchment,
        foregroundColor: AppColors.ink,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () => safeBack(context),
        ),
        title: Text('Chat', style: AppType.display(18)),
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(child: _body(state, myId)),
            _Composer(
              controller: _ctl,
              sending: state.sending,
              onSend: _send,
            ),
          ],
        ),
      ),
    );
  }

  Widget _body(ChatThreadState state, int? myId) {
    if (state.loading && state.messages.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (state.messages.isEmpty) {
      return RefreshIndicator(
        color: AppColors.ink,
        onRefresh: () =>
            ref.read(chatThreadProvider(widget.matchId).notifier).refresh(),
        child: ListView(
          children: [
            const SizedBox(height: 120),
            Icon(Icons.forum_outlined,
                size: 48, color: AppColors.inkMute.withValues(alpha: 0.6)),
            const SizedBox(height: 12),
            Text('No messages yet',
                textAlign: TextAlign.center,
                style: AppType.body(14, color: AppColors.inkMute)),
            const SizedBox(height: 4),
            Text('Say hello to coordinate the pickup.',
                textAlign: TextAlign.center,
                style: AppType.body(12.5, color: AppColors.inkMute)),
          ],
        ),
      );
    }
    return RefreshIndicator(
      color: AppColors.ink,
      onRefresh: () =>
          ref.read(chatThreadProvider(widget.matchId).notifier).refresh(),
      child: ListView.builder(
        controller: _scroll,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
        itemCount: state.messages.length,
        itemBuilder: (_, i) {
          final m = state.messages[i];
          return _Bubble(message: m, mine: myId != null && m.senderId == myId);
        },
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message, required this.mine});
  final ChatMessage message;
  final bool mine;

  @override
  Widget build(BuildContext context) {
    final bg = mine ? AppColors.emerald : Colors.white;
    final fg = mine ? AppColors.parchmentSoft : AppColors.ink;
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.76,
        ),
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(AppRadius.md),
            topRight: const Radius.circular(AppRadius.md),
            bottomLeft: Radius.circular(mine ? AppRadius.md : 4),
            bottomRight: Radius.circular(mine ? 4 : AppRadius.md),
          ),
          border: mine ? null : Border.all(color: AppColors.hairline),
        ),
        child: Column(
          crossAxisAlignment:
              mine ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            Text(message.body, style: AppType.body(14, color: fg, height: 1.35)),
            const SizedBox(height: 3),
            Text(
              _hhmm(message.createdAt.toLocal()),
              style: AppType.body(10,
                  color: mine
                      ? AppColors.parchmentSoft.withValues(alpha: 0.7)
                      : AppColors.inkMute),
            ),
          ],
        ),
      ),
    );
  }

  static String _hhmm(DateTime dt) {
    final h = dt.hour.toString().padLeft(2, '0');
    final m = dt.minute.toString().padLeft(2, '0');
    return '$h:$m';
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
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: const BoxDecoration(
        color: AppColors.parchment,
        border: Border(top: BorderSide(color: AppColors.hairline)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(AppRadius.lg),
                border: Border.all(color: AppColors.hairline),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: TextField(
                controller: controller,
                minLines: 1,
                maxLines: 4,
                maxLength: 2000,
                textInputAction: TextInputAction.newline,
                style: AppType.body(14, color: AppColors.ink),
                decoration: const InputDecoration(
                  hintText: 'Message…',
                  border: InputBorder.none,
                  counterText: '',
                  isDense: true,
                  contentPadding: EdgeInsets.symmetric(vertical: 12),
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          _SendButton(sending: sending, onTap: onSend),
        ],
      ),
    );
  }
}

class _SendButton extends StatelessWidget {
  const _SendButton({required this.sending, required this.onTap});
  final bool sending;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.sun,
      shape: const CircleBorder(),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: sending ? null : onTap,
        child: SizedBox(
          width: 46,
          height: 46,
          child: sending
              ? const Padding(
                  padding: EdgeInsets.all(13),
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: AppColors.ink),
                )
              : const Icon(Icons.send_rounded, size: 20, color: AppColors.ink),
        ),
      ),
    );
  }
}
