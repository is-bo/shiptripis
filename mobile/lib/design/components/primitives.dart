/// Buttons, cards, section headers and inline notices.
///
/// Everything here is sized to clear a 48 dp tap target and to survive a 200%
/// system font scale without clipping — the two failures that turn a polished
/// screenshot into an unusable screen.
library;

import 'package:flutter/material.dart';

import '../tokens.dart';
import 'status.dart';

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

enum AppButtonVariant {
  /// One per screen. The thing the screen exists for.
  primary,

  /// The sun button. Louder than [primary] and rationed far harder — the
  /// front door of the app and the last step of a funnel, and nowhere else.
  /// If two of these are visible at once, one of them is wrong.
  hero,

  /// A real alternative to the primary action.
  secondary,

  /// Low-emphasis, inline.
  tertiary,

  /// Irreversible and unpleasant: cancel a delivery, open a dispute.
  destructive,
}

class AppButton extends StatelessWidget {
  const AppButton({
    required this.label,
    required this.onPressed,
    this.variant = AppButtonVariant.primary,
    this.icon,
    this.isLoading = false,
    this.expand = true,
    this.semanticHint,
    super.key,
  });

  final String label;

  /// Null disables the button. A disabled primary action must always be
  /// accompanied by visible copy saying what would enable it — a dead button
  /// with no explanation is the single most common dead end in an app like
  /// this.
  final VoidCallback? onPressed;

  final AppButtonVariant variant;
  final IconData? icon;

  /// Shows a spinner *inside* the button and blocks re-entry, so a slow
  /// payment call cannot be submitted twice by an impatient double-tap.
  final bool isLoading;

  final bool expand;
  final String? semanticHint;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final enabled = onPressed != null && !isLoading;

    final child = _Content(label: label, icon: icon, isLoading: isLoading);

    final button = switch (variant) {
      AppButtonVariant.primary => FilledButton(
        onPressed: enabled ? onPressed : null,
        child: child,
      ),
      AppButtonVariant.hero => FilledButton(
        onPressed: enabled ? onPressed : null,
        style: FilledButton.styleFrom(
          backgroundColor: c.accent,
          // Ink on sun. White on this yellow fails contrast at every size.
          foregroundColor: c.onAccent,
        ),
        child: child,
      ),
      AppButtonVariant.secondary => OutlinedButton(
        onPressed: enabled ? onPressed : null,
        child: child,
      ),
      AppButtonVariant.tertiary => TextButton(
        onPressed: enabled ? onPressed : null,
        child: child,
      ),
      AppButtonVariant.destructive => OutlinedButton(
        onPressed: enabled ? onPressed : null,
        style: OutlinedButton.styleFrom(
          foregroundColor: c.danger,
          side: BorderSide(color: c.danger.withValues(alpha: 0.45)),
        ),
        child: child,
      ),
    };

    return Semantics(
      button: true,
      enabled: enabled,
      hint: semanticHint,
      // A spinner with no announcement is silence to a screen reader.
      liveRegion: isLoading,
      child: _PressScale(
        enabled: enabled,
        child: expand
            ? SizedBox(width: double.infinity, child: button)
            : button,
      ),
    );
  }
}

/// The original ShipTrip press feel: the button shrinks a shade under the
/// thumb and springs back.
///
/// Two percent is enough to feel and small enough that it never reads as a
/// layout shift. It listens rather than intercepts — [HitTestBehavior.deferToChild]
/// with no tap handler of its own — so the real button underneath still owns
/// the gesture, the ripple and the semantics.
class _PressScale extends StatefulWidget {
  const _PressScale({required this.child, required this.enabled});

  final Widget child;
  final bool enabled;

  @override
  State<_PressScale> createState() => _PressScaleState();
}

class _PressScaleState extends State<_PressScale> {
  bool _down = false;

  void _set(bool value) {
    if (!widget.enabled || _down == value) return;
    setState(() => _down = value);
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      onPointerDown: (_) => _set(true),
      onPointerUp: (_) => _set(false),
      onPointerCancel: (_) => _set(false),
      child: AnimatedScale(
        scale: _down ? 0.98 : 1,
        duration: AppMotion.respecting(context, AppMotion.fast),
        curve: AppMotion.enter,
        child: widget.child,
      ),
    );
  }
}

class _Content extends StatelessWidget {
  const _Content({required this.label, this.icon, this.isLoading = false});

  final String label;
  final IconData? icon;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    if (isLoading) {
      // Same height as the label so the button does not resize mid-press,
      // which would move whatever is underneath it.
      return SizedBox(
        height: 20,
        width: 20,
        child: CircularProgressIndicator(
          strokeWidth: 2.2,
          valueColor: AlwaysStoppedAnimation(
            DefaultTextStyle.of(context).style.color ?? context.colors.onBrand,
          ),
        ),
      );
    }
    if (icon == null) {
      return Text(label, textAlign: TextAlign.center);
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(icon, size: 19),
        const SizedBox(width: AppSpace.sm),
        Flexible(child: Text(label, textAlign: TextAlign.center)),
      ],
    );
  }
}

/// An icon-only control. Requires a label — an icon button with no semantic
/// label is invisible to a screen reader.
class AppIconButton extends StatelessWidget {
  const AppIconButton({
    required this.icon,
    required this.label,
    required this.onPressed,
    this.badgeCount,
    this.tone,
    super.key,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onPressed;

  /// Renders a count badge. Zero and null both render nothing.
  final int? badgeCount;

  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final count = badgeCount ?? 0;

    return Semantics(
      button: true,
      label: label,
      child: ExcludeSemantics(
        child: IconButton(
          onPressed: onPressed,
          tooltip: label,
          icon: Stack(
            clipBehavior: Clip.none,
            children: [
              Icon(icon, color: tone ?? c.textPrimary),
              if (count > 0)
                PositionedDirectional(
                  top: -3,
                  end: -4,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 4.5),
                    constraints: const BoxConstraints(minWidth: 17),
                    height: 17,
                    decoration: BoxDecoration(
                      color: c.attention,
                      borderRadius: AppRadius.rPill,
                      border: Border.all(color: c.canvas, width: 1.5),
                    ),
                    alignment: Alignment.center,
                    child: Text(
                      count > 9 ? '9+' : '$count',
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Colors.white,
                        fontSize: 9.5,
                        height: 1.1,
                      ),
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

// ---------------------------------------------------------------------------
// Surfaces
// ---------------------------------------------------------------------------

/// The standard content surface.
///
/// Cards do not nest. If a card seems to need a card inside it, the inner
/// thing wants [AppInsetGroup] — a sunken region — or the outer thing wants to
/// stop being a card.
class AppCard extends StatelessWidget {
  const AppCard({
    required this.child,
    this.onTap,
    this.padding = const EdgeInsets.all(AppSpace.lg),
    this.accent,
    this.semanticLabel,
    super.key,
  });

  final Widget child;
  final VoidCallback? onTap;
  final EdgeInsetsGeometry padding;

  /// A 3 dp leading edge in a status tone, for a card that needs to declare
  /// urgency in a list. Used sparingly — if every card has one, none of them
  /// reads as urgent.
  final StatusTone? accent;

  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final accentColor = accent == null
        ? null
        : StatusStyle.of(context, accent!).accent;

    Widget body = Padding(padding: padding, child: child);

    if (accentColor != null) {
      // Cards commonly live in a ListView, whose children have an
      // unbounded vertical constraint. IntrinsicHeight gives the accent rail
      // the card's natural height without asking a stretching Row to lay out
      // at infinity (which otherwise surfaces as soon as a selectable card is
      // tapped).
      body = IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(width: 3, color: accentColor),
            Expanded(child: body),
          ],
        ),
      );
    }

    final surface = DecoratedBox(
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: AppRadius.rLg,
        border: Border.all(color: c.hairline),
        boxShadow: context.elevation.card,
      ),
      child: ClipRRect(borderRadius: AppRadius.rLg, child: body),
    );

    if (onTap == null) {
      return semanticLabel == null
          ? surface
          : Semantics(label: semanticLabel, child: surface);
    }

    return Semantics(
      button: true,
      label: semanticLabel,
      child: Material(
        color: Colors.transparent,
        borderRadius: AppRadius.rLg,
        child: InkWell(
          onTap: onTap,
          borderRadius: AppRadius.rLg,
          child: surface,
        ),
      ),
    );
  }
}

/// A recessed region inside a card — a money breakdown, a code well, a
/// grouped set of read-only facts.
class AppInsetGroup extends StatelessWidget {
  const AppInsetGroup({
    required this.child,
    this.padding = const EdgeInsets.all(AppSpace.lg),
    this.background,
    super.key,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? background;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: background ?? context.colors.surfaceSunken,
      borderRadius: AppRadius.rMd,
    ),
    child: Padding(padding: padding, child: child),
  );
}

// ---------------------------------------------------------------------------
// Structure
// ---------------------------------------------------------------------------

/// A section heading, optionally with a trailing action.
///
/// There is no eyebrow, kicker or overline above it. The heading carries its
/// own weight.
class SectionHeader extends StatelessWidget {
  const SectionHeader({
    required this.title,
    this.actionLabel,
    this.onAction,
    this.subtitle,
    super.key,
  });

  final String title;
  final String? subtitle;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    return Padding(
      // More space above a heading than below it: the heading belongs to what
      // follows, not to what precedes it.
      padding: const EdgeInsets.only(top: AppSpace.xxl, bottom: AppSpace.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Semantics(
                  header: true,
                  // Fraunces, not the sans title role. Section headings were
                  // set in the display serif throughout the original app, and
                  // it is most of what makes a list of sections read as
                  // chapters rather than as form groups.
                  child: Text(title, style: text.headlineSmall),
                ),
                if (subtitle != null) ...[
                  const SizedBox(height: AppSpace.xs),
                  Text(
                    subtitle!,
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                  ),
                ],
              ],
            ),
          ),
          if (actionLabel != null && onAction != null)
            AppButton(
              label: actionLabel!,
              onPressed: onAction,
              variant: AppButtonVariant.tertiary,
              expand: false,
            ),
        ],
      ),
    );
  }
}

/// A labelled fact — the workhorse of every detail screen.
class DetailRow extends StatelessWidget {
  const DetailRow({
    required this.label,
    required this.value,
    this.icon,
    this.valueStyle,
    this.emphasise = false,
    super.key,
  });

  final String label;
  final Widget value;
  final IconData? icon;
  final TextStyle? valueStyle;
  final bool emphasise;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpace.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (icon != null) ...[
            Padding(
              padding: const EdgeInsets.only(top: 1),
              child: Icon(icon, size: 17, color: c.textTertiary),
            ),
            const SizedBox(width: AppSpace.md),
          ],
          Expanded(
            child: Text(
              label,
              style: text.bodyMedium?.copyWith(color: c.textSecondary),
            ),
          ),
          const SizedBox(width: AppSpace.lg),
          Flexible(
            child: DefaultTextStyle.merge(
              style:
                  valueStyle ??
                  (emphasise ? text.titleSmall : text.bodyMedium)?.copyWith(
                    color: c.textPrimary,
                  ),
              textAlign: TextAlign.end,
              child: value,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Inline notices
// ---------------------------------------------------------------------------

/// An in-page notice. Used where a snackbar would be wrong because the message
/// must persist — a stale-state explanation, a KYC prompt, a safety warning.
class InfoNotice extends StatelessWidget {
  const InfoNotice({
    required this.message,
    this.tone = StatusTone.neutral,
    this.icon = Icons.info_outline_rounded,
    this.title,
    this.actionLabel,
    this.onAction,
    super.key,
  });

  final String message;
  final String? title;
  final StatusTone tone;
  final IconData icon;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final style = StatusStyle.of(context, tone);
    final text = Theme.of(context).textTheme;

    return Semantics(
      // Announced when it appears — a warning nobody hears is not a warning.
      liveRegion: true,
      container: true,
      child: Container(
        padding: const EdgeInsets.all(AppSpace.lg),
        decoration: BoxDecoration(
          color: style.background,
          borderRadius: AppRadius.rMd,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 1),
              child: Icon(icon, size: 19, color: style.accent),
            ),
            const SizedBox(width: AppSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (title != null) ...[
                    Text(
                      title!,
                      style: text.titleSmall?.copyWith(color: style.foreground),
                    ),
                    const SizedBox(height: AppSpace.xs),
                  ],
                  Text(
                    message,
                    style: text.bodySmall?.copyWith(color: style.foreground),
                  ),
                  if (actionLabel != null && onAction != null) ...[
                    const SizedBox(height: AppSpace.sm),
                    _NoticeAction(
                      label: actionLabel!,
                      onPressed: onAction!,
                      color: style.foreground,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NoticeAction extends StatelessWidget {
  const _NoticeAction({
    required this.label,
    required this.onPressed,
    required this.color,
  });

  final String label;
  final VoidCallback onPressed;
  final Color color;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    child: InkWell(
      onTap: onPressed,
      borderRadius: AppRadius.rXs,
      child: Padding(
        // Keeps the 48 dp target without making the notice look like a form.
        padding: const EdgeInsets.symmetric(
          vertical: AppSpace.md,
          horizontal: AppSpace.xs,
        ),
        child: Text(
          label,
          style: Theme.of(context).textTheme.labelMedium?.copyWith(
            color: color,
            decoration: TextDecoration.underline,
            decorationColor: color.withValues(alpha: 0.5),
          ),
        ),
      ),
    ),
  );
}

/// A user's avatar. Initials rather than a generic silhouette — a silhouette
/// says "no person here", which is the opposite of what a marketplace built on
/// trusting a named individual should say.
class AppAvatar extends StatelessWidget {
  const AppAvatar({
    required this.initials,
    required this.name,
    this.size = 40,
    this.isVerified = false,
    super.key,
  });

  final String initials;
  final String name;
  final double size;
  final bool isVerified;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Semantics(
      label: name,
      excludeSemantics: true,
      child: SizedBox(
        width: size,
        height: size,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Container(
              width: size,
              height: size,
              decoration: BoxDecoration(
                color: c.brandSoft,
                shape: BoxShape.circle,
                border: Border.all(color: c.hairline),
              ),
              alignment: Alignment.center,
              child: Text(
                initials,
                // Textual, so it scales with the system font setting like
                // everything else.
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: c.brandStrong,
                  fontSize: size * 0.36,
                ),
              ),
            ),
            if (isVerified)
              PositionedDirectional(
                bottom: -1,
                end: -1,
                child: Container(
                  padding: const EdgeInsets.all(1.5),
                  decoration: BoxDecoration(
                    color: c.canvas,
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    Icons.verified_rounded,
                    size: size * 0.32,
                    color: c.success,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
