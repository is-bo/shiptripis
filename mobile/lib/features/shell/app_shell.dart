/// The tabbed shell.
///
/// Holds the four permanent destinations and the one docked navigation bar
/// that every screen inside them lays out above. Two behaviours are decided
/// here rather than per tab:
///
/// * **The bar hides while the keyboard is up.** With `resizeToAvoidBottomInset`
///   on, a docked bar would otherwise ride the top of the keyboard, eating
///   sixty points of an already-short viewport to offer navigation nobody
///   wants mid-sentence. Hiding it is not a layout hack — the bar's height
///   leaves the viewport with it, and [NavigationInsetScope] reports zero, so
///   anything reading the inset stays correct.
///
/// * **Re-tapping the current tab pops it to its root.** The expected gesture
///   in every tabbed app, and the cheapest way out of a stack the user has
///   wandered down.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/layout/app_scaffold.dart';
import '../../l10n/app_localizations.dart';

class AppShell extends ConsumerWidget {
  const AppShell({required this.navigationShell, super.key});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final unreadChats = ref.watch(unreadChatCountProvider);

    final keyboardIsUp = MediaQuery.viewInsetsOf(context).bottom > 0;
    final barHeight = keyboardIsUp
        ? 0.0
        : AppNavigationBar.occupiedHeight(context);

    final destinations = [
      NavDestination(
        icon: Icons.home_outlined,
        selectedIcon: Icons.home_rounded,
        label: l.navHome,
      ),
      NavDestination(
        icon: Icons.inventory_2_outlined,
        selectedIcon: Icons.inventory_2_rounded,
        label: l.navDeliveries,
      ),
      NavDestination(
        icon: Icons.forum_outlined,
        selectedIcon: Icons.forum_rounded,
        label: l.navChat,
        badgeCount: unreadChats,
      ),
      NavDestination(
        icon: Icons.person_outline_rounded,
        selectedIcon: Icons.person_rounded,
        label: l.navProfile,
      ),
    ];

    return NavigationInsetScope(
      inset: barHeight,
      barIsVisible: !keyboardIsUp,
      child: Scaffold(
        // The branch content brings its own AppScaffold; this one exists only
        // to dock the bar and own the resize behaviour.
        body: navigationShell,
        resizeToAvoidBottomInset: true,
        bottomNavigationBar: keyboardIsUp
            ? null
            : AppNavigationBar(
                destinations: destinations,
                currentIndex: navigationShell.currentIndex,
                onSelect: (index) => navigationShell.goBranch(
                  index,
                  // Tapping the tab you are already on returns to its root.
                  initialLocation: index == navigationShell.currentIndex,
                ),
              ),
      ),
    );
  }
}

/// The bell, with its unread count, for a screen's top bar.
///
/// Lives here rather than in the design system because it reads app state.
/// Every tab header uses it, which is what makes "notifications are in the
/// header" a real rule rather than an aspiration.
class NotificationBell extends ConsumerWidget {
  const NotificationBell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final count = ref.watch(unreadNotificationsProvider).value ?? 0;

    return AppIconButton(
      icon: count > 0
          ? Icons.notifications_rounded
          : Icons.notifications_none_rounded,
      label: count > 0
          ? l.navNotificationsWithCount(count)
          : l.navNotifications,
      badgeCount: count,
      onPressed: () => context.pushNamed('notifications'),
    );
  }
}
