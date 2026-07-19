import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/chat/chat_providers.dart';
import '../../core/chat/chat_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/stamp_chip.dart';

class ChatListScreen extends ConsumerWidget {
  const ChatListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(chatThreadsProvider);
    final threads = state.threads;

    return RefreshIndicator(
      onRefresh: () => ref.read(chatThreadsProvider.notifier).refresh(),
      color: AppColors.emerald,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: SafeArea(
              bottom: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.x6, AppSpacing.x6, AppSpacing.x6, AppSpacing.x4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text("Conversations", style: AppType.eyebrow()),
                        Text("Mailroom",
                            style: AppType.display(34,
                                w: FontWeight.w400, height: 1)),
                      ],
                    ),
                    const Spacer(),
                    if (state.totalUnread > 0)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 6),
                        decoration: BoxDecoration(
                          color: AppColors.terracotta,
                          borderRadius: BorderRadius.circular(AppRadius.pill),
                        ),
                        child: Text("${state.totalUnread} unread",
                            style: AppType.body(11.5,
                                color: Colors.white, w: FontWeight.w700)),
                      ),
                  ],
                ),
              ),
            ),
          ),
          if (state.loading && threads.isEmpty)
            const SliverFillRemaining(
              hasScrollBody: false,
              child: Center(
                child: CircularProgressIndicator(color: AppColors.emerald),
              ),
            )
          else if (state.error != null && threads.isEmpty)
            SliverFillRemaining(
              hasScrollBody: false,
              child: _ErrorState(
                message: state.error!,
                onRetry: () => ref.read(chatThreadsProvider.notifier).refresh(),
              ),
            )
          else if (threads.isEmpty)
            const SliverFillRemaining(
              hasScrollBody: false,
              child: _EmptyState(),
            )
          else
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, 0, AppSpacing.x6, 110),
              sliver: SliverList.separated(
                separatorBuilder: (_, _) =>
                    const SizedBox(height: AppSpacing.x3),
                itemCount: threads.length,
                itemBuilder: (_, i) => _ConvoTile(thread: threads[i])
                    .animate()
                    .fadeIn(
                        delay: Duration(milliseconds: 60 * i),
                        duration: 350.ms)
                    .moveY(begin: 10, end: 0, curve: kAppCurve),
              ),
            ),
        ],
      ),
    );
  }
}

class _ConvoTile extends StatelessWidget {
  const _ConvoTile({required this.thread});
  final ChatThread thread;

  @override
  Widget build(BuildContext context) {
    final unread = thread.unreadCount > 0;
    final snippet = thread.lastMessage?.trim().isNotEmpty == true
        ? thread.lastMessage!
        : 'Say hello — chat is open.';

    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        onTap: () => context.push('/chat/${thread.matchId}'),
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.x4),
          decoration: BoxDecoration(
            color: AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Row(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: AppColors.emerald.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(14),
                ),
                alignment: Alignment.center,
                child: Text(thread.initials,
                    style: AppType.display(15,
                        w: FontWeight.w600, color: AppColors.emerald)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            thread.counterpartyName.isEmpty
                                ? 'Traveler'
                                : thread.counterpartyName,
                            style: AppType.display(16, w: FontWeight.w500),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (thread.route.isNotEmpty) ...[
                          const SizedBox(width: 6),
                          StampChip(
                              label: thread.route,
                              color: AppColors.inkMute,
                              angle: -0.04),
                        ],
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(snippet,
                        style: AppType.body(13,
                            color: unread ? AppColors.ink : AppColors.inkMute,
                            w: unread ? FontWeight.w600 : FontWeight.w400),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(_relativeTime(thread.lastMessageAt),
                      style: AppType.mono(11, color: AppColors.inkMute)),
                  const SizedBox(height: 6),
                  if (unread)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 7, vertical: 2),
                      decoration: BoxDecoration(
                        color: AppColors.terracotta,
                        borderRadius: BorderRadius.circular(AppRadius.pill),
                      ),
                      child: Text("${thread.unreadCount}",
                          style: AppType.mono(11,
                              color: Colors.white, w: FontWeight.w700)),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Compact relative timestamp for the inbox ("now", "12m", "3h", "yesterday",
/// "Apr 24"). Deliberately terse to fit the trailing column.
String _relativeTime(DateTime? at) {
  if (at == null) return '';
  final now = DateTime.now();
  final local = at.toLocal();
  final diff = now.difference(local);
  if (diff.inMinutes < 1) return 'now';
  if (diff.inMinutes < 60) return '${diff.inMinutes}m';
  if (diff.inHours < 24 && now.day == local.day) return '${diff.inHours}h';
  if (diff.inDays < 2) return 'yesterday';
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return '${months[local.month - 1]} ${local.day}';
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.x6),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.mark_email_read_outlined,
              size: 48, color: AppColors.inkMute),
          const SizedBox(height: 16),
          Text('No conversations yet',
              style: AppType.display(18, w: FontWeight.w500)),
          const SizedBox(height: 8),
          Text(
            'Chat opens once an offer is accepted and paid. Your active '
            'deliveries will show up here.',
            textAlign: TextAlign.center,
            style: AppType.body(13, color: AppColors.inkMute),
          ),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.x6),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.cloud_off_rounded, size: 48, color: AppColors.inkMute),
          const SizedBox(height: 16),
          Text(message,
              textAlign: TextAlign.center,
              style: AppType.body(14, color: AppColors.inkSoft)),
          const SizedBox(height: 16),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
