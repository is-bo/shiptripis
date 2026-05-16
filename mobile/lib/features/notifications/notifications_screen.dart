import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';

class NotificationsScreen extends StatelessWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context) {
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
                  Text("Inbox", style: AppType.eyebrow()),
                  Text("Stamps & seals",
                      style: AppType.display(34, w: FontWeight.w400, height: 1)),
                ],
              ),
            ),
          ),
        ),
        const SliverFillRemaining(
          hasScrollBody: false,
          child: _EmptyState(),
        ),
      ],
    );
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
