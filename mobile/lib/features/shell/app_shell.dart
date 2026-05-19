import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/state/role_provider.dart';
import '../../core/theme/tokens.dart';
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
          if (canSwitch && _idx == 0)
            Positioned(
              top: MediaQuery.of(context).padding.top + 12,
              right: 16,
              child: _RoleSwitchPill(role: role),
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
