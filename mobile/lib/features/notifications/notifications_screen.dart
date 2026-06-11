import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth_notifier.dart';
import '../../core/notifications/notifications_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/ws/notification_ws_client.dart';
import '../../core/ws/notifications_providers.dart';

class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(notificationsNotifierProvider);
    final notifier = ref.read(notificationsNotifierProvider.notifier);
    final items = s.items;

    return RefreshIndicator(
      onRefresh: notifier.refresh,
      color: AppColors.ink,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: SafeArea(
              bottom: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(AppSpacing.x6,
                    AppSpacing.x6, AppSpacing.x6, AppSpacing.x4),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text("Inbox", style: AppType.eyebrow()),
                        const Spacer(),
                        _ConnectionDot(connection: s.connection),
                      ],
                    ),
                    Text("Stamps & seals",
                        style: AppType.display(34,
                            w: FontWeight.w400, height: 1)),
                    if (s.unreadCount > 0) ...[
                      const SizedBox(height: AppSpacing.x3),
                      Row(
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 10, vertical: 4),
                            decoration: BoxDecoration(
                              color: AppColors.terracotta.withValues(alpha: 0.12),
                              borderRadius: BorderRadius.circular(999),
                            ),
                            child: Text(
                              "${s.unreadCount} unread",
                              style: AppType.body(11,
                                  color: AppColors.terracotta,
                                  height: 1,
                                  w: FontWeight.w600),
                            ),
                          ),
                          const Spacer(),
                          TextButton(
                            onPressed: notifier.markAllRead,
                            style: TextButton.styleFrom(
                              foregroundColor: AppColors.ink,
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 12, vertical: 6),
                              minimumSize: Size.zero,
                              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                            ),
                            child: Text("Mark all read",
                                style: AppType.body(12,
                                    w: FontWeight.w600, height: 1)),
                          ),
                        ],
                      ),
                    ],
                    if (s.error != null) ...[
                      const SizedBox(height: AppSpacing.x3),
                      Text(s.error!,
                          style: AppType.body(12,
                              color: AppColors.terracotta, height: 1.4)),
                    ],
                  ],
                ),
              ),
            ),
          ),
          if (s.loading && items.isEmpty)
            const SliverFillRemaining(
              hasScrollBody: false,
              child: Center(
                child: Padding(
                  padding: EdgeInsets.all(AppSpacing.x10),
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            )
          else if (items.isEmpty)
            const SliverFillRemaining(
              hasScrollBody: false,
              child: _EmptyState(),
            )
          else
            SliverList.separated(
              itemCount: items.length,
              separatorBuilder: (_, _) =>
                  const SizedBox(height: AppSpacing.x2),
              itemBuilder: (_, i) => Padding(
                padding: EdgeInsets.fromLTRB(
                  AppSpacing.x6,
                  0,
                  AppSpacing.x6,
                  i == items.length - 1 ? AppSpacing.x6 : 0,
                ),
                child: _InboxTile(
                  item: items[i],
                  onTap: () => _handleTap(context, ref, items[i]),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _handleTap(
      BuildContext context, WidgetRef ref, InboxItem item) async {
    final notifier = ref.read(notificationsNotifierProvider.notifier);
    if (item.unread) {
      // Don't await — let the navigation race UI feel snappy.
      unawaited(notifier.markRead(item.id));
    }
    final dest = _deepLinkFor(ref, item);
    if (dest != null && context.mounted) {
      context.push(dest);
    }
  }

  String? _deepLinkFor(WidgetRef ref, InboxItem item) {
    final p = item.payload;
    final matchId = (p['match_id'] as num?)?.toInt();
    final parcelId = (p['parcel_id'] as num?)?.toInt();
    final auth = ref.read(authNotifierProvider);
    final viewerId = auth is AuthSignedIn ? auth.user.id : null;
    final senderId = (p['sender_id'] as num?)?.toInt();
    final travelerId = (p['traveler_id'] as num?)?.toInt();
    final isSender = viewerId != null && viewerId == senderId;
    switch (item.channel) {
      case 'handover.code_issued':
        if (matchId == null) return null;
        final kind = (p['kind'] as String?) ?? 'pickup';
        return '/handover/code/$matchId?kind=$kind';
      case 'match.in_transit':
        if (viewerId != null && viewerId == travelerId) {
          if (matchId == null) return null;
          return '/handover/verify/$matchId?kind=delivery';
        }
        if (isSender && parcelId != null) return '/sender/requests/$parcelId';
        if (matchId != null) return '/tracking/$matchId';
        return null;
      case 'match.completed':
      case 'match.created':
        if (isSender && parcelId != null) return '/sender/requests/$parcelId';
        if (matchId != null) return '/match/$matchId';
        return null;
      case 'offer.created':
      case 'offer.accepted':
      case 'offer.updated':
        if (matchId == null) return null;
        return '/match/$matchId';
      case 'payment.captured':
        if (matchId == null) return null;
        return '/match/$matchId';
      case 'parcel.created':
      case 'parcel.cancelled':
        if (parcelId != null) return '/sender/requests/$parcelId';
        return '/sender/requests';
      // The traveler's posted trips live on the home shell (no dedicated
      // trips route), so trip lifecycle notifications land there.
      case 'trip.created':
      case 'trip.cancelled':
        return '/app';
      default:
        return null;
    }
  }
}

class _ConnectionDot extends StatelessWidget {
  const _ConnectionDot({required this.connection});
  final WsConnectionState connection;

  @override
  Widget build(BuildContext context) {
    final (color, label) = switch (connection) {
      WsConnectionState.connected => (const Color(0xFF2E7D32), "live"),
      WsConnectionState.connecting ||
      WsConnectionState.reconnecting =>
        (const Color(0xFFFBBC04), "syncing"),
      WsConnectionState.idle => (AppColors.inkMute, "offline"),
      WsConnectionState.closed => (AppColors.inkMute, "offline"),
    };
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 6),
        Text(label,
            style: AppType.body(11, color: AppColors.inkMute, height: 1)),
      ],
    );
  }
}

class _InboxTile extends StatelessWidget {
  const _InboxTile({required this.item, required this.onTap});
  final InboxItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final (icon, title, subtitle) = _present(item);
    final unread = item.unread;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        child: Container(
          decoration: BoxDecoration(
            color: unread
                ? AppColors.sun.withValues(alpha: 0.10)
                : AppColors.parchmentSoft,
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(
              color: unread
                  ? AppColors.sun.withValues(alpha: 0.55)
                  : AppColors.hairline,
            ),
          ),
          padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.x4, vertical: AppSpacing.x3),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  border: Border.all(color: AppColors.hairline),
                ),
                alignment: Alignment.center,
                child: Icon(icon, size: 18, color: AppColors.ink),
              ),
              const SizedBox(width: AppSpacing.x3),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(title,
                              style: AppType.display(15,
                                  w: FontWeight.w500, height: 1.2)),
                        ),
                        if (unread)
                          Container(
                            width: 8,
                            height: 8,
                            margin: const EdgeInsets.only(left: 6, top: 4),
                            decoration: const BoxDecoration(
                              color: AppColors.terracotta,
                              shape: BoxShape.circle,
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(subtitle,
                        style: AppType.body(12,
                            color: AppColors.inkMute, height: 1.4)),
                    const SizedBox(height: 4),
                    Text(_relative(item.createdAt),
                        style: AppType.body(10,
                            color: AppColors.inkMute, height: 1)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    ).animate().fadeIn(duration: 220.ms).slideY(
        begin: 0.04, end: 0, duration: 260.ms, curve: Curves.easeOutCubic);
  }

  (IconData, String, String) _present(InboxItem i) {
    final p = i.payload;
    switch (i.channel) {
      case 'offer.accepted':
        final total = p['total_dzd'];
        return (
          Icons.check_circle_outline_rounded,
          "Offer accepted",
          total != null
              ? "Total $total DZD — your match is confirmed."
              : "A traveler accepted your offer.",
        );
      case 'offer.created':
        return (
          Icons.mark_email_unread_outlined,
          "New offer",
          "A traveler applied to your parcel.",
        );
      case 'offer.updated':
        return (
          Icons.edit_note_rounded,
          "Offer updated",
          "Pricing or terms changed on a match.",
        );
      case 'match.in_transit':
        return (
          Icons.flight_takeoff_rounded,
          "In transit",
          "Pickup confirmed. The package is on its way.",
        );
      case 'match.completed':
        return (
          Icons.task_alt_rounded,
          "Delivered",
          "The handover was completed.",
        );
      case 'payment.captured':
        return (
          Icons.payments_outlined,
          "Payment captured",
          "Funds are locked in escrow.",
        );
      case 'handover.code_issued':
        final kind = (p['kind'] as String?) ?? 'pickup';
        return (
          Icons.qr_code_2_rounded,
          kind == 'delivery'
              ? "Delivery code ready"
              : "Pickup code ready",
          "Tap to view your code.",
        );
      case 'handover.confirmed':
        return (
          Icons.verified_rounded,
          "Handover confirmed",
          "Code verified successfully.",
        );
      case 'parcel.created':
        return (
          Icons.inventory_2_outlined,
          "Request posted",
          "Travelers can now make offers.",
        );
      case 'trip.created':
        return (
          Icons.flight_class_outlined,
          "Trip posted",
          "Senders can now request you.",
        );
      default:
        return (
          Icons.notifications_active_outlined,
          i.channel,
          i.eventId,
        );
    }
  }

  String _relative(DateTime t) {
    final d = DateTime.now().difference(t);
    if (d.inSeconds < 45) return "just now";
    if (d.inMinutes < 60) return "${d.inMinutes}m ago";
    if (d.inHours < 24) return "${d.inHours}h ago";
    if (d.inDays < 7) return "${d.inDays}d ago";
    return "${t.year}-${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')}";
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x6, AppSpacing.x10, AppSpacing.x6, AppSpacing.x10),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 84,
            height: 84,
            decoration: BoxDecoration(
              color: AppColors.parchmentSoft,
              borderRadius: BorderRadius.circular(AppRadius.xl),
              border: Border.all(color: AppColors.hairline),
            ),
            alignment: Alignment.center,
            child: const Icon(Icons.notifications_none_rounded,
                size: 38, color: AppColors.inkMute),
          ).animate().fadeIn(duration: 350.ms).scale(
              begin: const Offset(0.9, 0.9),
              end: const Offset(1, 1),
              duration: 350.ms,
              curve: Curves.easeOutBack),
          const SizedBox(height: AppSpacing.x4),
          Text("Nothing yet", style: AppType.display(22, w: FontWeight.w500)),
          const SizedBox(height: 6),
          SizedBox(
            width: 260,
            child: Text(
              "Offers, payments, and handover events land here as they happen — pull down to refresh.",
              textAlign: TextAlign.center,
              style: AppType.body(13, color: AppColors.inkMute, height: 1.45),
            ),
          ),
        ],
      ),
    );
  }
}
