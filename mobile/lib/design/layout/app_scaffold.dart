/// The one scaffold every ShipTrip screen uses, and the single answer to the
/// bottom-navigation overlap bug.
///
/// ## Why this file exists
///
/// The previous build floated a pill-shaped navigation bar over a Scaffold
/// with `extendBody: true`. That construction makes the framework report a
/// viewport that is taller than the visible one, so every screen underneath
/// had to guess how much space the bar was stealing — which is how the
/// codebase ended up sprinkled with hand-tuned bottom paddings that were
/// wrong on a different phone, wrong with the keyboard up, and wrong in
/// landscape.
///
/// The fix is structural, not per-screen:
///
/// 1. The navigation bar is a **real docked `bottomNavigationBar`**, so the
///    framework subtracts its height from the branch viewport and strips the
///    system bottom padding from it. Content physically cannot be laid out
///    underneath the bar.
/// 2. Every screen composes with [AppScaffold], which pins its footer in a
///    [Column] above the body rather than stacking it. A sticky call to
///    action therefore sits above the navigation bar inside a tab, and above
///    the home indicator outside one, with no screen-level arithmetic.
/// 3. `resizeToAvoidBottomInset` stays on, so the whole column — footer
///    included — lifts above the keyboard.
/// 4. Scroll roots take their trailing gutter from [AppScrollPadding], which
///    reads the real inset rather than a literal.
///
/// [NavigationInsetScope] publishes the bar's measured height for the few
/// widgets that genuinely need the number — a map's floating controls, a
/// scroll-to-top affordance, a snackbar margin. Nothing else should read it,
/// and no screen should ever hard-code it.
library;

import 'package:flutter/material.dart';

import '../tokens.dart';

// ---------------------------------------------------------------------------
// Inset scope
// ---------------------------------------------------------------------------

/// Publishes how much vertical space the app shell's navigation bar occupies,
/// including the system gesture inset beneath it.
///
/// Returns `0` when absent, which is the correct answer for a full-screen
/// route pushed above the shell — there is no bar there to avoid.
class NavigationInsetScope extends InheritedWidget {
  const NavigationInsetScope({
    required this.inset,
    required this.barIsVisible,
    required super.child,
    super.key,
  });

  /// Total occupied height, in logical pixels.
  final double inset;

  /// False while the bar is hidden — currently whenever the keyboard is up.
  /// A floating control should stay put rather than animate down and back.
  final bool barIsVisible;

  static NavigationInsetScope? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<NavigationInsetScope>();

  static double of(BuildContext context) => maybeOf(context)?.inset ?? 0;

  @override
  bool updateShouldNotify(NavigationInsetScope old) =>
      old.inset != inset || old.barIsVisible != barIsVisible;
}

// ---------------------------------------------------------------------------
// Scaffold
// ---------------------------------------------------------------------------

/// The standard screen container.
///
/// Prefer this over a bare [Scaffold] everywhere. It guarantees the footer,
/// keyboard and system-inset behaviour described at the top of this file, and
/// it is what the `no_bottom_overlap_test` suite asserts against.
class AppScaffold extends StatelessWidget {
  const AppScaffold({
    required this.body,
    this.topBar,
    this.footer,
    this.background,
    this.floating,
    this.padBodyHorizontally = false,
    this.extendBodyBehindTopBar = false,
    super.key,
  });

  /// Screen content. Usually a scroll view; see [AppScrollPadding].
  final Widget body;

  /// Header. Use `AppTopBar`, which already supplies the right height and
  /// leading/back semantics.
  final PreferredSizeWidget? topBar;

  /// Pinned action area. Rendered above the body, above the navigation bar,
  /// and above the keyboard — never over the content it acts on.
  final Widget? footer;

  final Color? background;

  /// Rendered over the body, inset from the footer and navigation bar. For
  /// map controls and similar affordances that must float.
  final Widget? floating;

  /// Applies the standard page gutter to the body. Leave false for screens
  /// whose scroll view needs to bleed to the edges (lists with full-width
  /// separators, maps, image galleries).
  final bool padBodyHorizontally;

  /// For a top bar drawn over imagery. The body then receives the top inset
  /// itself instead of being pushed below the bar.
  final bool extendBodyBehindTopBar;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;

    Widget content = body;
    if (padBodyHorizontally) {
      content = Padding(
        padding: const EdgeInsetsDirectional.symmetric(
          horizontal: AppSpace.gutter,
        ),
        child: content,
      );
    }

    // Horizontal-only safe area. Vertical insets are handled deliberately:
    // the top by the app bar, the bottom by the footer and the shell's
    // navigation bar. Consuming them here as well would double-pad.
    content = SafeArea(
      top: false,
      bottom: false,
      child: content,
    );

    if (floating != null) {
      content = Stack(
        children: [
          Positioned.fill(child: content),
          Positioned.directional(
            textDirection: Directionality.of(context),
            end: AppSpace.gutter,
            bottom: AppSpace.gutter,
            child: SafeArea(
              top: false,
              child: floating!,
            ),
          ),
        ],
      );
    }

    return Scaffold(
      backgroundColor: background ?? colors.canvas,
      appBar: topBar,
      extendBodyBehindAppBar: extendBodyBehindTopBar,

      // On. This is what lifts the entire column — footer included — clear of
      // the keyboard. Turning it off is how a "Continue" button ends up
      // underneath the very field the user is typing into.
      resizeToAvoidBottomInset: true,

      body: Column(
        children: [
          Expanded(child: content),
          if (footer != null) AppFooterBar(child: footer!),
        ],
      ),
    );
  }
}

/// The pinned action area at the bottom of a screen.
///
/// Adds the system bottom inset itself. Inside a tab the shell's navigation
/// bar has already consumed that inset, so this contributes nothing extra and
/// the footer lands flush on the bar; outside a tab it clears the iPhone home
/// indicator and the Android gesture pill.
class AppFooterBar extends StatelessWidget {
  const AppFooterBar({
    required this.child,
    this.background,
    this.showDivider = true,
    super.key,
  });

  final Widget child;
  final Color? background;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: background ?? colors.surface,
        border: showDivider
            ? Border(top: BorderSide(color: colors.hairline))
            : null,
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpace.gutter,
            AppSpace.md,
            AppSpace.gutter,
            AppSpace.md,
          ),
          child: child,
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Scroll padding
// ---------------------------------------------------------------------------

/// Trailing padding for a scroll root.
///
/// Overlap is already prevented structurally; this is the breathing room that
/// keeps the last row from sitting flush against whatever is below it. It
/// reads the real navigation inset and the real system inset rather than a
/// guessed literal, so it stays correct on a gesture-navigation Android
/// phone, on an iPhone with a home indicator, and in landscape.
abstract final class AppScrollPadding {
  /// Bottom padding for a scroll view whose screen has **no** footer.
  static double bottomOf(BuildContext context) {
    final mq = MediaQuery.of(context);
    return AppSpace.x3l + mq.padding.bottom + NavigationInsetScope.of(context);
  }

  /// Bottom padding for a scroll view whose screen **has** a footer. The
  /// footer already occupies that space, so only the gutter is added.
  static double bottomBelowFooter(BuildContext context) => AppSpace.xxl;

  /// Standard page insets for a scrolling screen with no footer.
  static EdgeInsets page(BuildContext context, {double top = AppSpace.lg}) =>
      EdgeInsets.fromLTRB(
        AppSpace.gutter,
        top,
        AppSpace.gutter,
        bottomOf(context),
      );

  /// Standard page insets for a scrolling screen that has a footer.
  static EdgeInsets pageWithFooter(
    BuildContext context, {
    double top = AppSpace.lg,
  }) => const EdgeInsets.fromLTRB(
    AppSpace.gutter,
    AppSpace.lg,
    AppSpace.gutter,
    AppSpace.xxl,
  ).copyWith(top: top);
}

// ---------------------------------------------------------------------------
// Keyboard helper
// ---------------------------------------------------------------------------

/// Whether a software keyboard is currently covering part of the screen.
///
/// Read from `viewInsets`, which is the only source that stays truthful when
/// an outer route has already consumed the padding.
bool isKeyboardVisible(BuildContext context) =>
    MediaQuery.viewInsetsOf(context).bottom > 0;

/// Dismisses the keyboard when the user taps outside a field.
///
/// Wraps forms rather than individual fields. Uses [HitTestBehavior.opaque] on
/// a bare gesture detector so it never swallows taps meant for a control.
class DismissKeyboardOnTap extends StatelessWidget {
  const DismissKeyboardOnTap({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) => GestureDetector(
    behavior: HitTestBehavior.translucent,
    onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
    child: child,
  );
}
