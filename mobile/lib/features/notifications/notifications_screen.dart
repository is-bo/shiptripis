import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/ws/notification_envelope.dart';
import '../../core/ws/notification_ws_client.dart';
import '../../core/ws/notifications_providers.dart';

class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(notificationsNotifierProvider);
    final events = s.events;

    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, AppSpacing.x6, AppSpacing.x6, AppSpacing.x4),
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
                ],
              ),
            ),
          ),
        ),
        if (events.isEmpty)
          const SliverFillRemaining(
            hasScrollBody: false,
            child: _EmptyState(),
          )
        else
          SliverList.separated(
            itemCount: events.length,
            separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.x2),
            itemBuilder: (_, i) => Padding(
              padding: EdgeInsets.fromLTRB(
                AppSpacing.x6,
                i == 0 ? 0 : 0,
                AppSpacing.x6,
                i == events.length - 1 ? AppSpacing.x6 : 0,
              ),
              child: _EnvelopeTile(env: events[i]),
            ),
          ),
      ],
    );
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
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 6),
        Text(label,
            style: AppType.body(11, color: AppColors.inkMute, height: 1)),
      ],
    );
  }
}

class _EnvelopeTile extends StatelessWidget {
  const _EnvelopeTile({required this.env});
  final NotificationEnvelope env;

  @override
  Widget build(BuildContext context) {
    final (icon, title, subtitle) = _present(env);
    return Container(
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
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
                Text(title,
                    style: AppType.display(15, w: FontWeight.w500, height: 1.2)),
                const SizedBox(height: 2),
                Text(subtitle,
                    style: AppType.body(12,
                        color: AppColors.inkMute, height: 1.4)),
              ],
            ),
          ),
        ],
      ),
    ).animate().fadeIn(duration: 220.ms).slideY(
        begin: 0.05, end: 0, duration: 260.ms, curve: Curves.easeOutCubic);
  }

  /// Map the envelope type to (icon, title, subtitle). Covers the
  /// channels Django publishes today; falls back to a generic row so
  /// new channels don't crash the screen.
  (IconData, String, String) _present(NotificationEnvelope env) {
    final p = env.payload ?? const {};
    switch (env.type) {
      case 'offer.accepted':
        final total = p['total_dzd'];
        return (
          Icons.check_circle_outline_rounded,
          "Offer accepted",
          total != null ? "Total $total DZD" : "A traveler accepted your offer.",
        );
      case 'offer.created':
        return (
          Icons.mark_email_unread_outlined,
          "New offer",
          "A traveler applied to your parcel.",
        );
      case 'match.in_transit':
        return (
          Icons.flight_takeoff_rounded,
          "In transit",
          "Your package is on its way.",
        );
      case 'match.completed':
        return (
          Icons.task_alt_rounded,
          "Delivered",
          "The handover code was verified.",
        );
      case 'payment.captured':
        return (
          Icons.payments_outlined,
          "Payment captured",
          "Funds are now in escrow.",
        );
      case 'handover.confirmed':
        return (
          Icons.qr_code_2_rounded,
          "Handover confirmed",
          "Code verified successfully.",
        );
      default:
        return (
          Icons.notifications_active_outlined,
          env.type,
          env.eventId ?? "",
        );
    }
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
          Text("Nothing yet",
              style: AppType.display(22, w: FontWeight.w500)),
          const SizedBox(height: 6),
          SizedBox(
            width: 260,
            child: Text(
              "You'll see offers, payments, and handover events here as they happen.",
              textAlign: TextAlign.center,
              style: AppType.body(13, color: AppColors.inkMute, height: 1.45),
            ),
          ),
        ],
      ),
    );
  }
}
