import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
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
    return Scaffold(
      backgroundColor: AppColors.parchment,
      extendBody: true,
      body: AnimatedSwitcher(
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
      bottomNavigationBar: _BottomNav(
        index: _idx,
        onChange: (i) => setState(() => _idx = i),
      ),
    );
  }
}

class _BottomNav extends ConsumerWidget {
  const _BottomNav({required this.index, required this.onChange});
  final int index;
  final ValueChanged<int> onChange;

  static const _items = [
    _NavItem(Icons.travel_explore_rounded, "Home"),
    _NavItem(Icons.chat_bubble_outline_rounded, "Chat"),
    _NavItem(Icons.notifications_none_rounded, "Inbox"),
    _NavItem(Icons.person_outline_rounded, "Me"),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
        child: Container(
          height: 68,
          decoration: BoxDecoration(
            color: AppColors.ink,
            borderRadius: BorderRadius.circular(AppRadius.pill),
            boxShadow: AppShadows.elevated,
          ),
          child: Row(
            children: List.generate(_items.length, (i) {
              final selected = i == index;
              final item = _items[i];
              return Expanded(
                child: GestureDetector(
                  onTap: () => onChange(i),
                  behavior: HitTestBehavior.opaque,
                  child: Center(
                    child: AnimatedContainer(
                      duration: AppDurations.med,
                      curve: kAppCurve,
                      padding: EdgeInsets.symmetric(
                        horizontal: selected ? 18 : 12,
                        vertical: 10,
                      ),
                      decoration: BoxDecoration(
                        color: selected ? AppColors.parchment : Colors.transparent,
                        borderRadius: BorderRadius.circular(AppRadius.pill),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            item.icon,
                            size: 20,
                            color: selected ? AppColors.ink : AppColors.parchment.withValues(alpha: 0.7),
                          ),
                          if (selected) ...[
                            const SizedBox(width: 8),
                            Text(
                              item.label,
                              style: AppType.body(12.5,
                                  color: AppColors.ink, w: FontWeight.w600),
                            ).animate().fadeIn(duration: 200.ms),
                          ],
                        ],
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

class _NavItem {
  const _NavItem(this.icon, this.label);
  final IconData icon;
  final String label;
}
