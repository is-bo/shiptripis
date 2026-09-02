/// Conversations.
///
/// A thread is listed as soon as the server says its history is visible, which
/// outlives the delivery: a completed or cancelled deal stays readable. Whether
/// the composer opens is a *separate* server answer, `can_send`, and this list
/// shows both facts rather than collapsing them into one.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/chat.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../shell/app_shell.dart';

class ChatListScreen extends ConsumerWidget {
  const ChatListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final threads = ref.watch(chatThreadsProvider);

    return AppScaffold(
      topBar: AppTopBar(
        title: l.chatTitle,
        actions: const [NotificationBell()],
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(chatThreadsProvider),
        child: AsyncView<List<ChatThread>>(
          value: threads,
          onRetry: () => ref.invalidate(chatThreadsProvider),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (all) {
            if (all.isEmpty) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.chatEmptyTitle,
                    // States the actual rule: chat opens on funding.
                    body: l.chatEmptyBody,
                    icon: Icons.forum_outlined,
                  ),
                ],
              );
            }

            return ListView.separated(
              padding: AppScrollPadding.page(context),
              itemCount: all.length,
              separatorBuilder: (context, _) =>
                  Divider(height: 1, color: context.colors.hairline),
              itemBuilder: (context, index) => _ThreadRow(thread: all[index]),
            );
          },
        ),
      ),
    );
  }
}

class _ThreadRow extends StatelessWidget {
  const _ThreadRow({required this.thread});

  final ChatThread thread;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final last = thread.lastMessageAt;

    return Semantics(
      button: true,
      label: thread.hasUnread
          ? '${thread.counterpartyName}, ${thread.unreadCount}'
          : thread.counterpartyName,
      onTap: () =>
          context.openChatThread(thread.matchId, dealId: thread.dealId),
      child: ExcludeSemantics(
        child: InkWell(
          onTap: () =>
              context.openChatThread(thread.matchId, dealId: thread.dealId),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                AppAvatar(
                  initials: initialsFor(thread.counterpartyName),
                  name: thread.counterpartyName,
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              thread.counterpartyName,
                              style: text.titleSmall?.copyWith(
                                fontWeight: thread.hasUnread
                                    ? FontWeight.w700
                                    : FontWeight.w600,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          if (last != null) ...[
                            const SizedBox(width: AppSpace.sm),
                            Text(
                              LocaleFormats.dayMonth(locale, last),
                              style: text.bodySmall?.copyWith(
                                color: c.textTertiary,
                              ),
                            ),
                          ],
                        ],
                      ),
                      const SizedBox(height: AppSpace.xxs),
                      Text(
                        thread.route,
                        style: text.bodySmall?.copyWith(color: c.textTertiary),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      if (thread.lastMessage != null &&
                          thread.lastMessage!.isNotEmpty) ...[
                        const SizedBox(height: AppSpace.xs),
                        Text(
                          thread.lastMessage!,
                          style: text.bodyMedium?.copyWith(
                            color: thread.hasUnread
                                ? c.textPrimary
                                : c.textSecondary,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                      // Read-only is a real state and gets said, not implied by
                      // a greyed-out composer the user only meets after tapping.
                      if (!thread.canSend) ...[
                        const SizedBox(height: AppSpace.sm),
                        StatusPill(
                          label: l.chatClosedTitle,
                          tone: StatusTone.neutral,
                          icon: Icons.lock_outline_rounded,
                          compact: true,
                        ),
                      ],
                    ],
                  ),
                ),
                if (thread.hasUnread) ...[
                  const SizedBox(width: AppSpace.sm),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    constraints: const BoxConstraints(minWidth: 20),
                    height: 20,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: c.brand,
                      borderRadius: AppRadius.rPill,
                    ),
                    child: Text(
                      thread.unreadCount > 9 ? '9+' : '${thread.unreadCount}',
                      style: text.labelSmall?.copyWith(color: c.onBrand),
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
