/// The notification inbox, reached from the header bell.
///
/// Every row navigates from **structured data** — the dotted channel plus the
/// ids in the payload — resolved by `AppNotification.destination`. No English
/// message string is ever parsed to decide where a tap goes, which is also
/// what lets the whole inbox be translated.
///
/// Push and WebSocket delivery both reconcile back to this authoritative list.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../core/live/live_updates.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/notification.dart';
import '../../l10n/app_localizations.dart';

final _notificationsQuery = FutureProvider.autoDispose
    .family<NotificationPage, ({int? accountId, bool history})>((
      ref,
      key,
    ) async {
      final unsubscribe = ref
          .read(liveUpdatesProvider)
          .register(const LiveResource.notifications(), ref.invalidateSelf);
      ref.onDispose(unsubscribe);
      final repo = ref.watch(notificationRepositoryProvider);
      final result = await repo.page(
        bucket: key.history ? 'history' : 'active',
      );
      if (ref.read(accountProvider)?.id != key.accountId) {
        throw StateError('Discarded an inbox read from an older session.');
      }
      return result;
    });
final _notificationsProvider = Provider.autoDispose
    .family<AsyncValue<NotificationPage>, bool>((ref, history) {
      final accountId = ref.watch(
        accountProvider.select((account) => account?.id),
      );
      final query = _notificationsQuery((
        accountId: accountId,
        history: history,
      ));
      // ignore: experimental_member_use
      ref.onManualInvalidation(() => ref.invalidate(query));
      return ref.watch(query);
    });

class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key, this.history = false});
  final bool history;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final page = ref.watch(_notificationsProvider(history));
    // "Mark all read" is about unread rows, not about the bell total: the
    // badge counts live actions, so gating on it offered the button when
    // everything had already been read and pressing it changed nothing.
    final unreadActive =
        ref.watch(unreadActiveNotificationsProvider).value ?? 0;

    return AppScaffold(
      topBar: AppTopBar(
        title: history ? l.deliveriesFilterHistory : l.notificationsTitle,
        showBack: true,
        actions: [
          if (!history)
            IconButton(
              icon: const Icon(Icons.history),
              tooltip: l.deliveriesFilterHistory,
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const NotificationsScreen(history: true),
                ),
              ),
            ),
          if (!history && unreadActive > 0)
            TextButton(
              onPressed: () => _markAllRead(context, ref),
              child: Text(l.notificationsMarkAllRead),
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref
            ..invalidate(_notificationsProvider)
            ..invalidate(unreadNotificationsProvider)
            ..invalidate(unreadActiveNotificationsProvider);
        },
        child: AsyncView<NotificationPage>(
          value: page,
          onRetry: () => ref.invalidate(_notificationsProvider),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (data) {
            if (data.items.isEmpty) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.notificationsEmptyTitle,
                    body: l.notificationsEmptyBody,
                    icon: Icons.notifications_none_rounded,
                  ),
                ],
              );
            }

            return ListView.separated(
              padding: AppScrollPadding.page(context),
              itemCount: data.items.length,
              separatorBuilder: (context, _) =>
                  Divider(height: 1, color: context.colors.hairline),
              itemBuilder: (context, index) => _Row(
                notification: data.items[index],
                onTap: () => _open(context, ref, data.items[index]),
              ),
            );
          },
        ),
      ),
    );
  }

  Future<void> _markAllRead(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(notificationRepositoryProvider).markAllRead();
    } on Object catch (error) {
      if (!context.mounted) return;
      AppSnack.failure(context, error);
      return;
    }
    if (!context.mounted) return;
    ref
      ..invalidate(_notificationsProvider)
      ..invalidate(unreadNotificationsProvider)
      ..invalidate(unreadActiveNotificationsProvider);
  }

  Future<void> _open(
    BuildContext context,
    WidgetRef ref,
    AppNotification notification,
  ) async {
    final destination = notification.destination;

    // Marking read is a side effect of opening, not a reason to block on the
    // network: the navigation happens either way.
    if (notification.isUnread) _markReadInBackground(ref, notification.id);

    if (destination == null || !context.mounted) return;
    switch (destination) {
      case OpenChat(:final matchId):
        context.openChatThread(matchId);
      case OpenMatch(:final matchId):
        context.openNegotiation(matchId);
      case OpenDeal(:final dealId):
        ref.invalidate(dealDetailProvider(dealId));
        context.openDeal(dealId);
      case OpenRequest(:final requestId):
        context.openRequest(requestId);
      case OpenPayments():
        context.pushNamed(Routes.profilePayouts);
      case OpenPayoutDetail(:final reference):
        context.openPayoutDetail(reference);
      case OpenPayoutMethods():
        context.openPayoutMethods();
      case OpenJourney(:final journeyId):
        context.pushNamed(
          Routes.journeyDetail,
          pathParameters: {'id': '$journeyId'},
        );
      case OpenDispute(:final disputeId):
        context.pushNamed(
          Routes.disputeDetail,
          pathParameters: {'id': '$disputeId'},
        );
      case OpenKyc():
        context.pushNamed(Routes.kyc);
    }
  }

  /// Fire and forget. A failed read-marker is not worth blocking navigation
  /// for, and the badge simply stays until the next refresh.
  void _markReadInBackground(WidgetRef ref, int id) {
    ref
        .read(notificationRepositoryProvider)
        .markRead(id)
        .then((_) {
          // Reading can resolve the underlying action, which moves the row out
          // of Active and into History. Refreshing only the badge left the list
          // showing a row the server no longer counts as active, styled unread.
          ref
            ..invalidate(unreadNotificationsProvider)
            ..invalidate(unreadActiveNotificationsProvider)
            ..invalidate(_notificationsProvider);
        })
        .catchError((Object _) {});
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.notification, required this.onTap});

  final AppNotification notification;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final when = notification.createdAt;
    final navigable = notification.destination != null;

    final (title, icon) = _describe(context, notification.channel);

    return Semantics(
      button: navigable,
      label: title,
      onTap: navigable ? onTap : null,
      child: ExcludeSemantics(
        child: InkWell(
          onTap: navigable ? onTap : null,
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: AppSpace.lg),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: notification.isUnread
                        ? c.brandSoft
                        : c.surfaceSunken,
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    icon,
                    size: 18,
                    color: notification.isUnread ? c.brand : c.textTertiary,
                  ),
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: text.titleSmall?.copyWith(
                          fontWeight: notification.isUnread
                              ? FontWeight.w700
                              : FontWeight.w500,
                        ),
                      ),
                      if (when != null) ...[
                        const SizedBox(height: AppSpace.xs),
                        Text(
                          LocaleFormats.dateTime(locale, when),
                          style: text.bodySmall?.copyWith(
                            color: c.textTertiary,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                if (navigable)
                  Icon(
                    Icons.chevron_right_rounded,
                    size: 20,
                    color: c.textTertiary,
                  )
                else
                  // An unrecognised channel is listed but not tappable, rather
                  // than being dropped or leading nowhere.
                  Text(
                    l.stateUnexpectedTitle,
                    style: text.labelSmall?.copyWith(color: c.textTertiary),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Copy chosen from the channel, never from the server's message text.
  (String, IconData) _describe(
    BuildContext context,
    NotificationChannel channel,
  ) {
    final l = L.of(context);
    return switch (channel) {
      NotificationChannel.offerCreated ||
      NotificationChannel.offerUpdated ||
      NotificationChannel.offerEconomicsChanged ||
      NotificationChannel.offerAccepted => (
        l.notificationOffer,
        Icons.swap_horiz_rounded,
      ),
      NotificationChannel.matchCreated => (
        l.notificationMatch,
        Icons.handshake_rounded,
      ),
      NotificationChannel.paymentCaptured ||
      NotificationChannel.paymentRefunded ||
      NotificationChannel.paymentFailed => (
        l.notificationPayment,
        Icons.credit_card_rounded,
      ),
      NotificationChannel.payoutStatusChanged => (
        l.notificationPayout,
        Icons.account_balance_wallet_outlined,
      ),
      NotificationChannel.chatMessage => (
        l.notificationChat,
        Icons.forum_rounded,
      ),
      NotificationChannel.parcelCreated ||
      NotificationChannel.parcelCancelled => (
        l.notificationRequest,
        Icons.inventory_2_rounded,
      ),
      NotificationChannel.matchInTransit ||
      NotificationChannel.matchCompleted => (
        l.notificationDelivery,
        Icons.local_shipping_rounded,
      ),
      NotificationChannel.handoverConfirmed ||
      NotificationChannel.deliveryCodeAvailable ||
      NotificationChannel.deliveryConfirmed ||
      NotificationChannel.dealUpdated ||
      NotificationChannel.dealCancelled => (
        l.notificationDelivery,
        Icons.local_shipping_rounded,
      ),
      NotificationChannel.dealArrivalReported => (
        l.notificationArrivalReported,
        Icons.flight_land_rounded,
      ),
      NotificationChannel.dealArrivalConfirmed => (
        l.notificationArrivalConfirmed,
        Icons.check_circle_outline_rounded,
      ),
      NotificationChannel.dealArrivalDeclined => (
        l.notificationArrivalDeclined,
        Icons.info_outline_rounded,
      ),
      NotificationChannel.tripCreated ||
      NotificationChannel.tripUpdated ||
      NotificationChannel.tripCancelled => (
        l.notificationJourney,
        Icons.flight_takeoff_rounded,
      ),
      NotificationChannel.kycStatusChanged ||
      NotificationChannel.flightProofStatusChanged => (
        l.notificationAccount,
        Icons.verified_user_outlined,
      ),
      NotificationChannel.disputeOpened ||
      NotificationChannel.disputeResolved => (
        l.notificationDispute,
        Icons.gavel_outlined,
      ),
      NotificationChannel.unknown => (
        l.notificationOther,
        Icons.notifications_none_rounded,
      ),
    };
  }
}
