import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/state/role_provider.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/ws/live_event_router.dart';
import '../chat/chat_list_screen.dart';
import '../home/home_screen.dart';
import '../notifications/notifications_screen.dart';
import '../profile/profile_screen.dart';

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});
  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  int _idx = 0;

  @override
  Widget build(BuildContext context) {
    final pages = const [
      HomeScreen(),
      ChatListScreen(),
      NotificationsScreen(),
      ProfileScreen(),
    ];
    final canSwitch = ref.watch(canSwitchRoleProvider);
    final role = ref.watch(effectiveRoleProvider);
    // Keep the live event router alive while the shell is mounted, but don't
    // rebuild the shell on every WS tick — the banner stack watches its own
    // selector. listen with an empty callback is enough to hold the provider.
    ref.listen(liveEventProvider, (_, __) {});
    return Scaffold(
      backgroundColor: AppColors.parchment,
      extendBody: true,
      body: Stack(
        children: [
          AnimatedSwitcher(
            duration: AppDurations.med,
            switchInCurve: kAppCurve,
            transitionBuilder: (child, anim) => FadeTransition(
              opacity: anim,
              child: SlideTransition(
                position: Tween<Offset>(begin: const Offset(0, 0.02), end: Offset.zero).animate(anim),
                child: child,
              ),
            ),
            child: KeyedSubtree(key: ValueKey(_idx), child: pages[_idx]),
          ),
          if (canSwitch)
            Positioned(
              top: MediaQuery.of(context).padding.top + 12,
              right: 16,
              child: _RoleSwitchPill(role: role),
            ),
          const Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: LiveBannerStack(),
          ),
        ],
      ),
      bottomNavigationBar: _BottomNav(
        index: _idx,
        onChange: (i) => setState(() => _idx = i),
      ),
    );
  }
}

class _RoleSwitchPill extends ConsumerWidget {
  const _RoleSwitchPill({required this.role});
  final AppRole role;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isSender = role == AppRole.sender;
    return Material(
      color: Colors.white,
      elevation: 2,
      shadowColor: Colors.black26,
      borderRadius: BorderRadius.circular(AppRadius.pill),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.pill),
        onTap: () => ref.read(roleProvider.notifier).toggle(),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.pill),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                isSender ? Icons.inventory_2_rounded : Icons.flight_takeoff_rounded,
                size: 16,
                color: AppColors.ink,
              ),
              const SizedBox(width: 6),
              Text(
                isSender ? 'Sender' : 'Traveler',
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: AppColors.ink,
                ),
              ),
              const SizedBox(width: 4),
              const Icon(Icons.swap_horiz_rounded, size: 14, color: AppColors.inkMute),
            ],
          ),
        ),
      ),
    );
  }
}

/// Floats over the shell. Picks up [LiveBanner]s published by the WS event
/// router and renders the newest two as tap-to-deep-link cards. Auto-dismiss
/// after 6s; tap dismisses immediately and navigates if the banner has a link.
class LiveBannerStack extends ConsumerStatefulWidget {
  const LiveBannerStack({super.key});

  @override
  ConsumerState<LiveBannerStack> createState() => _LiveBannerStackState();
}

class _LiveBannerStackState extends ConsumerState<LiveBannerStack> {
  final Map<int, _BannerTimer> _timers = {};

  @override
  void dispose() {
    for (final t in _timers.values) {
      t.cancel();
    }
    super.dispose();
  }

  void _ensureTimer(int id) {
    if (_timers.containsKey(id)) return;
    _timers[id] = _BannerTimer(() {
      if (!mounted) return;
      _timers.remove(id);
      ref.read(liveEventProvider.notifier).dismissBanner(id);
    });
  }

  void _dismiss(int id) {
    _timers.remove(id)?.cancel();
    ref.read(liveEventProvider.notifier).dismissBanner(id);
  }

  @override
  Widget build(BuildContext context) {
    final banners = ref.watch(liveEventProvider.select((s) => s.banners));
    final visible =
        banners.take(2).toList(growable: false); // newest first

    final liveIds = banners.map((b) => b.id).toSet();
    _timers.removeWhere((id, t) {
      if (liveIds.contains(id)) return false;
      t.cancel();
      return true;
    });
    for (final b in visible) {
      _ensureTimer(b.id);
    }

    if (visible.isEmpty) return const SizedBox.shrink();

    return SafeArea(
      bottom: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
        child: Column(
          children: [
            for (final b in visible)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _LiveBannerCard(
                  banner: b,
                  onTap: () {
                    final link = b.deepLink;
                    _dismiss(b.id);
                    if (link != null) {
                      GoRouter.of(context).push(link);
                    }
                  },
                  onDismiss: () => _dismiss(b.id),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _BannerTimer {
  _BannerTimer(VoidCallback onTick) {
    _f = Future<void>.delayed(const Duration(seconds: 6), () {
      if (_cancelled) return;
      onTick();
    });
  }
  bool _cancelled = false;
  // ignore: unused_field
  Future<void>? _f;
  void cancel() => _cancelled = true;
}

class _LiveBannerCard extends StatelessWidget {
  const _LiveBannerCard({
    required this.banner,
    required this.onTap,
    required this.onDismiss,
  });
  final LiveBanner banner;
  final VoidCallback onTap;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final (bg, accent, icon) = switch (banner.tone) {
      LiveBannerTone.success => (
        AppColors.emerald.withValues(alpha: 0.96),
        AppColors.parchmentSoft,
        Icons.check_circle_outline_rounded,
      ),
      LiveBannerTone.warning => (
        AppColors.terracotta.withValues(alpha: 0.96),
        AppColors.parchmentSoft,
        Icons.warning_amber_rounded,
      ),
      LiveBannerTone.info => (
        AppColors.ink.withValues(alpha: 0.94),
        AppColors.sun,
        Icons.notifications_active_rounded,
      ),
    };

    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.md),
        onTap: banner.deepLink != null ? onTap : onDismiss,
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(AppRadius.md),
            boxShadow: const [
              BoxShadow(
                color: Color(0x33000000),
                blurRadius: 18,
                offset: Offset(0, 8),
              ),
            ],
          ),
          child: Row(
            children: [
              Icon(icon, color: accent, size: 22),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      banner.title,
                      style: AppType.body(13.5,
                          w: FontWeight.w800,
                          color: AppColors.parchmentSoft),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      banner.body,
                      style: AppType.body(12,
                          color: AppColors.parchmentSoft
                              .withValues(alpha: 0.85)),
                    ),
                  ],
                ),
              ),
              IconButton(
                onPressed: onDismiss,
                icon: Icon(Icons.close_rounded,
                    size: 18,
                    color: AppColors.parchmentSoft.withValues(alpha: 0.75)),
                splashRadius: 18,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _BottomNav extends StatelessWidget {
  const _BottomNav({required this.index, required this.onChange});
  final int index;
  final ValueChanged<int> onChange;

  static const _icons = [
    Icons.travel_explore_rounded,
    Icons.chat_bubble_rounded,
    Icons.notifications_rounded,
    Icons.person_rounded,
  ];

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
        child: Container(
          height: 66,
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(AppRadius.pill),
            border: Border.all(color: AppColors.hairline, width: 1),
            boxShadow: const [
              BoxShadow(
                color: Color(0x140E1F2C),
                blurRadius: 20,
                offset: Offset(0, 8),
              ),
              BoxShadow(
                color: Color(0x080E1F2C),
                blurRadius: 4,
                offset: Offset(0, 2),
              ),
            ],
          ),
          child: Row(
            children: List.generate(_icons.length, (i) {
              final selected = i == index;
              return Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onChange(i),
                  child: Center(
                    child: AnimatedContainer(
                      duration: AppDurations.med,
                      curve: kAppCurve,
                      padding: EdgeInsets.symmetric(
                        horizontal: selected ? 18 : 12,
                        vertical: 10,
                      ),
                      decoration: BoxDecoration(
                        color: selected ? AppColors.sun : Colors.transparent,
                        borderRadius: BorderRadius.circular(AppRadius.pill),
                        boxShadow: selected
                            ? [
                                BoxShadow(
                                  color: AppColors.sun.withValues(alpha: 0.35),
                                  blurRadius: 12,
                                  offset: const Offset(0, 4),
                                ),
                              ]
                            : null,
                      ),
                      child: Icon(
                        _icons[i],
                        size: 22,
                        color: selected ? AppColors.ink : AppColors.inkMute,
                      ),
                    ),
                  ),
                ),
              );
            }),
          ),
        ),
      ),
    );
  }
}
