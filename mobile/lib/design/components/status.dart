/// Status indicators.
///
/// Every status in this app is **three signals, not one**: a word, an icon,
/// and a colour. Colour is the last of the three and never carries meaning
/// alone — a user with deuteranopia reading "paid" versus "payment failed"
/// must not be depending on the difference between emerald and rust.
///
/// The tone vocabulary is small on purpose. Five tones cover every lifecycle
/// state in the product, which is what lets a user learn the language once:
///
/// * [StatusTone.progress] — the platform is working; nobody is blocked
/// * [StatusTone.action] — **you** have something to do
/// * [StatusTone.waiting] — time is passing; the counterparty or a timer owns
///   the next move
/// * [StatusTone.good] — a terminal success
/// * [StatusTone.bad] — failed, cancelled, disputed
/// * [StatusTone.neutral] — inert: draft, history, expired, unrecognised
library;

import 'package:flutter/material.dart';

import '../tokens.dart';

enum StatusTone { progress, action, waiting, good, bad, neutral }

@immutable
class StatusStyle {
  const StatusStyle({
    required this.foreground,
    required this.background,
    required this.accent,
  });

  final Color foreground;
  final Color background;

  /// For the dot, the icon, and the timeline node — the saturated version.
  final Color accent;

  static StatusStyle of(BuildContext context, StatusTone tone) {
    final c = context.colors;
    return switch (tone) {
      StatusTone.progress => StatusStyle(
        foreground: c.onInfoSoft,
        background: c.infoSoft,
        accent: c.info,
      ),
      StatusTone.action => StatusStyle(
        foreground: c.onAttentionSoft,
        background: c.attentionSoft,
        accent: c.attention,
      ),
      StatusTone.waiting => StatusStyle(
        foreground: c.onWaitingSoft,
        background: c.waitingSoft,
        accent: c.waiting,
      ),
      StatusTone.good => StatusStyle(
        foreground: c.onSuccessSoft,
        background: c.successSoft,
        accent: c.success,
      ),
      StatusTone.bad => StatusStyle(
        foreground: c.onDangerSoft,
        background: c.dangerSoft,
        accent: c.danger,
      ),
      StatusTone.neutral => StatusStyle(
        foreground: c.onNeutralSoft,
        background: c.neutralSoft,
        accent: c.textTertiary,
      ),
    };
  }
}

/// The standard status chip.
///
/// [semanticPrefix] is spoken before the label so a screen reader announces
/// "Status, payment needed" rather than a bare noun phrase floating in a card.
class StatusPill extends StatelessWidget {
  const StatusPill({
    required this.label,
    required this.tone,
    required this.icon,
    this.semanticPrefix,
    this.compact = false,
    super.key,
  });

  final String label;
  final StatusTone tone;

  /// Required, not optional. A pill without an icon is a pill that only
  /// communicates through colour.
  final IconData icon;

  final String? semanticPrefix;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final style = StatusStyle.of(context, tone);
    final text = Theme.of(context).textTheme;

    return Semantics(
      label: semanticPrefix == null ? label : '$semanticPrefix, $label',
      excludeSemantics: true,
      child: Container(
        padding: EdgeInsetsDirectional.only(
          start: compact ? AppSpace.sm : AppSpace.md,
          end: compact ? AppSpace.md : AppSpace.lg - 2,
          top: compact ? AppSpace.xs : AppSpace.sm - 2,
          bottom: compact ? AppSpace.xs : AppSpace.sm - 2,
        ),
        decoration: BoxDecoration(
          color: style.background,
          borderRadius: AppRadius.rPill,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: compact ? 13 : 15, color: style.accent),
            SizedBox(width: compact ? AppSpace.xs : AppSpace.sm - 2),
            Flexible(
              child: Text(
                label,
                style: (compact ? text.labelSmall : text.labelMedium)?.copyWith(
                  color: style.foreground,
                ),
                overflow: TextOverflow.ellipsis,
                maxLines: 1,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A bare tone dot, for dense rows where a full pill would not fit.
///
/// Always paired with adjacent text that says the same thing — it is a
/// reinforcement of a label, never a replacement for one.
class StatusDot extends StatelessWidget {
  const StatusDot({required this.tone, this.size = 8, super.key});

  final StatusTone tone;
  final double size;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: StatusStyle.of(context, tone).accent,
        shape: BoxShape.circle,
      ),
    ),
  );
}

/// Transport mode. Flight and drive are distinguished by icon and word first;
/// the colour difference is a third signal.
enum TransportMode {
  flight,
  drive,
  unknown;

  static TransportMode parse(Object? raw) {
    // The API sends these uppercase, unlike every other enum in the domain.
    final text = raw is String ? raw.toUpperCase() : '';
    return switch (text) {
      'FLIGHT' => TransportMode.flight,
      'DRIVE' => TransportMode.drive,
      _ => TransportMode.unknown,
    };
  }

  IconData get icon => switch (this) {
    TransportMode.flight => Icons.flight_takeoff_rounded,
    TransportMode.drive => Icons.directions_car_filled_rounded,
    TransportMode.unknown => Icons.more_horiz_rounded,
  };
}

class ModeChip extends StatelessWidget {
  const ModeChip({required this.mode, required this.label, super.key});

  final TransportMode mode;
  final String label;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final accent = switch (mode) {
      TransportMode.flight => c.modeFlight,
      TransportMode.drive => c.modeDrive,
      TransportMode.unknown => c.textTertiary,
    };

    return Semantics(
      label: label,
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(mode.icon, size: 15, color: accent),
          const SizedBox(width: AppSpace.xs + 2),
          Text(
            label,
            style: Theme.of(
              context,
            ).textTheme.labelMedium?.copyWith(color: c.textSecondary),
          ),
        ],
      ),
    );
  }
}
