/// The people the member blocks, each with the way to unblock them.
///
/// A block is made from a chat (its menu, or when reporting a message); this
/// is where it is lifted from when the chat is gone or closed.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/chat.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';

final blockedPeopleProvider = FutureProvider.autoDispose<List<BlockedPerson>>(
  (ref) => ref.watch(chatRepositoryProvider).blockedPeople(),
);

class BlockedPeopleScreen extends ConsumerStatefulWidget {
  const BlockedPeopleScreen({super.key});

  @override
  ConsumerState<BlockedPeopleScreen> createState() =>
      _BlockedPeopleScreenState();
}

class _BlockedPeopleScreenState extends ConsumerState<BlockedPeopleScreen> {
  final Set<int> _unblocking = <int>{};

  Future<void> _unblock(BlockedPerson person) async {
    final l = L.of(context);
    setState(() => _unblocking.add(person.userId));
    try {
      await ref.read(chatRepositoryProvider).unblockPerson(person.userId);
      ref
        ..invalidate(blockedPeopleProvider)
        ..invalidate(chatThreadsProvider);
      if (mounted) AppSnack.success(context, l.chatUnblockDone);
    } on Object catch (error) {
      if (mounted) AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _unblocking.remove(person.userId));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final people = ref.watch(blockedPeopleProvider);

    return AppScaffold(
      topBar: AppTopBar(title: l.blockedPeopleTitle, showBack: true),
      body: AsyncView<List<BlockedPerson>>(
        value: people,
        onRetry: () => ref.invalidate(blockedPeopleProvider),
        loading: () => const Padding(
          padding: EdgeInsets.all(AppSpace.gutter),
          child: SkeletonCardList(count: 3),
        ),
        data: (rows) {
          if (rows.isEmpty) {
            return AppEmptyState(
              title: l.blockedPeopleEmptyTitle,
              body: l.blockedPeopleEmptyBody,
              icon: Icons.block_rounded,
            );
          }
          return ListView.separated(
            padding: AppScrollPadding.page(context),
            itemCount: rows.length + 1,
            separatorBuilder: (_, index) => index == 0
                ? const SizedBox(height: AppSpace.md)
                : Divider(height: 1, color: context.colors.hairline),
            itemBuilder: (context, index) {
              if (index == 0) {
                return Text(
                  l.blockedPeopleBody,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: context.colors.textSecondary,
                  ),
                );
              }
              final person = rows[index - 1];
              return _BlockedRow(
                person: person,
                busy: _unblocking.contains(person.userId),
                onUnblock: () => _unblock(person),
              );
            },
          );
        },
      ),
    );
  }
}

class _BlockedRow extends StatelessWidget {
  const _BlockedRow({
    required this.person,
    required this.busy,
    required this.onUnblock,
  });

  final BlockedPerson person;
  final bool busy;
  final VoidCallback onUnblock;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final name = person.deleted || person.name.trim().isEmpty
        ? l.chatDeletedAccount
        : person.name;
    final since = person.blockedAt;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
      child: Row(
        children: [
          AppAvatar(initials: initialsFor(name), name: name),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: text.titleSmall,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (since != null)
                  Text(
                    l.blockedPeopleSince(LocaleFormats.fullDate(locale, since)),
                    style: text.bodySmall?.copyWith(color: c.textTertiary),
                  ),
              ],
            ),
          ),
          const SizedBox(width: AppSpace.sm),
          AppButton(
            label: l.chatUnblockAction,
            variant: AppButtonVariant.secondary,
            expand: false,
            isLoading: busy,
            onPressed: busy ? null : onUnblock,
          ),
        ],
      ),
    );
  }
}
