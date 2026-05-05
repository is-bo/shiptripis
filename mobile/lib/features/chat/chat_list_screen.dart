import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/stamp_chip.dart';

class _Convo {
  final String name;
  final String avatar;
  final String snippet;
  final String time;
  final int unread;
  final String tripCode;
  const _Convo(this.name, this.avatar, this.snippet, this.time, this.unread, this.tripCode);
}

const _convos = <_Convo>[
  _Convo("Yacine M.", "YM", "Pickup confirmed — code 4192", "12:04", 2, "ALG → CDG"),
  _Convo("Lamia B.", "LB", "Can we move pickup to 18:00?", "yesterday", 0, "ORN → MRS"),
  _Convo("Karim D.", "KD", "Delivered ✅ — leave a rating?", "Apr 24", 0, "CDG → ALG"),
  _Convo("Soraya A.", "SA", "Bonjour, j'ai 6 kg dispo.", "Apr 22", 1, "LYS → CZL"),
];

class ChatListScreen extends StatelessWidget {
  const ChatListScreen({super.key});

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
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text("Conversations", style: AppType.eyebrow()),
                      Text("Mailroom",
                          style: AppType.display(34, w: FontWeight.w400, height: 1)),
                    ],
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(
                      color: AppColors.terracotta,
                      borderRadius: BorderRadius.circular(AppRadius.pill),
                    ),
                    child: Text("3 unread",
                        style: AppType.body(11.5, color: Colors.white, w: FontWeight.w700)),
                  ),
                ],
              ),
            ),
          ),
        ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.x6, 0, AppSpacing.x6, 110),
          sliver: SliverList.separated(
            separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.x3),
            itemCount: _convos.length,
            itemBuilder: (_, i) => _ConvoTile(c: _convos[i])
                .animate()
                .fadeIn(delay: Duration(milliseconds: 60 * i), duration: 350.ms)
                .moveY(begin: 10, end: 0, curve: kAppCurve),
          ),
        ),
      ],
    );
  }
}

class _ConvoTile extends StatelessWidget {
  const _ConvoTile({required this.c});
  final _Convo c;
  @override
  Widget build(BuildContext context) {
    return Container(
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
            child: Text(c.avatar,
                style: AppType.display(15, w: FontWeight.w600, color: AppColors.emerald)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(c.name, style: AppType.display(16, w: FontWeight.w500)),
                    const SizedBox(width: 6),
                    StampChip(label: c.tripCode, color: AppColors.inkMute, angle: -0.04),
                  ],
                ),
                const SizedBox(height: 3),
                Text(c.snippet,
                    style: AppType.body(13,
                        color: c.unread > 0 ? AppColors.ink : AppColors.inkMute,
                        w: c.unread > 0 ? FontWeight.w600 : FontWeight.w400),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(c.time, style: AppType.mono(11, color: AppColors.inkMute)),
              const SizedBox(height: 6),
              if (c.unread > 0)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.terracotta,
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                  ),
                  child: Text("${c.unread}",
                      style: AppType.mono(11, color: Colors.white, w: FontWeight.w700)),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
