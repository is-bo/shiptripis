/// Navigation chrome: the bottom bar and the screen header.
///
/// The bottom bar is a **docked** `bottomNavigationBar`, not a floating pill
/// over `extendBody`. That is the whole fix for the overlap bug: the framework
/// subtracts a docked bar's height from the branch viewport and strips the
/// system inset from it, so content cannot be laid out underneath it. See
/// `design/layout/app_scaffold.dart` for the full contract.
library;

import 'package:flutter/material.dart';

import '../layout/app_scaffold.dart';
import '../tokens.dart';
import 'primitives.dart';

/// One destination.
@immutable
class NavDestination {
  const NavDestination({
    required this.icon,
    required this.selectedIcon,
    required this.label,
    this.badgeCount = 0,
  });

  final IconData icon;
  final IconData selectedIcon;
  final String label;
  final int badgeCount;
}

/// Height of the bar's own content, before the system inset is added.
///
/// Generous enough that icon + label clears 48 dp of tappable height, which is
/// the Material minimum and covers iOS's 44 pt as well.
const double kNavBarContentHeight = 60;

class AppNavigationBar extends StatelessWidget {
  const AppNavigationBar({
    required this.destinations,
    required this.currentIndex,
    required this.onSelect,
    super.key,
  });

  final List<NavDestination> destinations;
  final int currentIndex;
  final ValueChanged<int> onSelect;

  /// Total height this bar occupies for a given context, including the system
  /// gesture inset or home indicator beneath it. Published through
  /// [NavigationInsetScope] for the few widgets that need the number.
  static double occupiedHeight(BuildContext context) =>
      kNavBarContentHeight + MediaQuery.viewPaddingOf(context).bottom;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;

    return DecoratedBox(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(top: BorderSide(color: c.hairline)),
      ),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: kNavBarContentHeight,
          child: Row(
            children: [
              for (var i = 0; i < destinations.length; i++)
                Expanded(
                  child: _NavItem(
                    destination: destinations[i],
                    isSelected: i == currentIndex,
                    onTap: () => onSelect(i),
                    // Screen readers announce position, so "Deliveries, tab 2
                    // of 4" rather than a bare word in a row of words.
                    position: i + 1,
                    total: destinations.length,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.destination,
    required this.isSelected,
    required this.onTap,
    required this.position,
    required this.total,
  });

  final NavDestination destination;
  final bool isSelected;
  final VoidCallback onTap;
  final int position;
  final int total;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    // Ink on sun when selected. The original ShipTrip bar marked the current
    // destination with a sun-filled lozenge under the glyph, and it is the
    // one place the accent appears on every screen — which is what made the
    // colour read as the app's rather than as one screen's.
    final tint = isSelected ? c.onAccent : c.textTertiary;

    return Semantics(
      button: true,
      selected: isSelected,
      label: destination.badgeCount > 0
          ? '${destination.label}, ${destination.badgeCount}'
          : destination.label,
      value: '$position / $total',
      child: ExcludeSemantics(
        child: InkWell(
          onTap: onTap,
          // Fills the cell so the target is the whole quarter of the bar, not
          // just the glyph.
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Stack(
                clipBehavior: Clip.none,
                children: [
                  AnimatedContainer(
                    duration: AppMotion.respecting(context, AppMotion.fast),
                    curve: AppMotion.standard,
                    padding: EdgeInsets.symmetric(
                      horizontal: isSelected ? 16 : 10,
                      vertical: 3,
                    ),
                    decoration: BoxDecoration(
                      color: isSelected ? c.accent : Colors.transparent,
                      borderRadius: AppRadius.rPill,
                      boxShadow: isSelected
                          ? [
                              BoxShadow(
                                color: c.accent.withValues(alpha: 0.35),
                                blurRadius: 12,
                                offset: const Offset(0, 4),
                              ),
                            ]
                          : null,
                    ),
                    child: Icon(
                      isSelected ? destination.selectedIcon : destination.icon,
                      size: 22,
                      color: tint,
                    ),
                  ),
                  if (destination.badgeCount > 0)
                    PositionedDirectional(
                      top: -2,
                      end: 2,
                      child: _Badge(count: destination.badgeCount),
                    ),
                ],
              ),
              const SizedBox(height: 3),
              // Labels always shown. Icon-only navigation is a guess in any
              // language and more so across three.
              Flexible(
                child: Text(
                  destination.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: text.labelSmall?.copyWith(
                    // Not `tint`: the label is on the bar, not on the sun
                    // lozenge, so it takes ink rather than the on-accent
                    // colour.
                    color: isSelected ? c.textPrimary : c.textTertiary,
                    fontWeight: isSelected ? FontWeight.w700 : FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      constraints: const BoxConstraints(minWidth: 16),
      height: 16,
      decoration: BoxDecoration(
        color: c.attention,
        borderRadius: AppRadius.rPill,
        border: Border.all(color: c.surface, width: 1.5),
      ),
      alignment: Alignment.center,
      child: Text(
        count > 9 ? '9+' : '$count',
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
          color: Colors.white,
          fontSize: 9,
          height: 1.1,
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

/// The standard screen header.
///
/// Deliberately not `AppBar` directly at call sites: this centralises the
/// notification bell, the back affordance and the title style, so a screen
/// cannot accidentally ship a header that behaves differently from every
/// other one.
class AppTopBar extends StatelessWidget implements PreferredSizeWidget {
  const AppTopBar({
    required this.title,
    this.subtitle,
    this.actions = const [],
    this.leading,
    this.showBack = false,
    this.onBack,
    this.backLabel,
    this.bottom,
    super.key,
  });

  final String title;
  final String? subtitle;
  final List<Widget> actions;
  final Widget? leading;

  /// Renders an explicit back affordance. On iOS the left-edge swipe still
  /// works regardless — this is in addition to it, never instead of it.
  final bool showBack;
  final VoidCallback? onBack;
  final String? backLabel;

  final PreferredSizeWidget? bottom;

  @override
  Size get preferredSize =>
      Size.fromHeight(56 + (bottom?.preferredSize.height ?? 0));

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    return AppBar(
      automaticallyImplyLeading: false,
      leading:
          leading ??
          (showBack
              ? AppIconButton(
                  // Directional: mirrors in Arabic, where "back" is the other
                  // way round.
                  icon: Icons.arrow_back_rounded,
                  label:
                      backLabel ??
                      MaterialLocalizations.of(context).backButtonTooltip,
                  onPressed: onBack ?? () => Navigator.of(context).maybePop(),
                )
              : null),
      titleSpacing: leading == null && !showBack ? AppSpace.gutter : 0,
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Semantics(
            header: true,
            child: Text(
              title,
              style: text.headlineSmall,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (subtitle != null)
            Text(
              subtitle!,
              style: text.bodySmall?.copyWith(color: c.textSecondary),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
        ],
      ),
      actions: [
        ...actions,
        const SizedBox(width: AppSpace.sm),
      ],
      bottom: bottom,
    );
  }
}
