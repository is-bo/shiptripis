/// The route motif.
///
/// A journey is an ordered line with nodes on it: Paris → Algiers by air,
/// Algiers → Jijel by road. That line is this product, so it is the one
/// graphic device the design commits to, and it appears wherever a route does
/// — the journey builder, a leg list, a match card, a delivery's progress.
///
/// It is laid out **vertically** on purpose. A vertical run of nodes reads at
/// a glance on a phone, survives long Arabic and French place names without
/// truncating, and needs no horizontal scrolling. It also mirrors correctly
/// for free: only the leading edge moves in RTL, and the sequence still reads
/// top to bottom in every language.
library;

import 'package:flutter/material.dart';

import '../tokens.dart';
import 'status.dart';

/// One stop on the line.
@immutable
class RouteStop {
  const RouteStop({
    required this.label,
    this.detail,
    this.timeLabel,
    this.isReached = false,
    this.isCurrent = false,
  });

  /// The place. Coarse or exact depending on what the API released — this
  /// widget renders what it is handed and makes no privacy decision of its
  /// own.
  final String label;

  /// A secondary line: an airport name, a meeting point, a note.
  final String? detail;

  /// Formatted departure or arrival.
  final String? timeLabel;

  final bool isReached;
  final bool isCurrent;
}

/// The connector between two stops: how you get from one to the next.
@immutable
class RouteSegment {
  const RouteSegment({
    required this.mode,
    required this.modeLabel,
    this.detail,
    this.capacityLabel,
    this.tone,
    this.isTraversed = false,
  });

  final TransportMode mode;
  final String modeLabel;

  /// Flight number, distance, duration — whatever the API gave for this leg.
  final String? detail;

  /// Remaining capacity on this leg, when the viewer is entitled to see it.
  final String? capacityLabel;

  /// Colours the connector when the leg carries a state of its own, such as a
  /// flight whose proof was rejected.
  final StatusTone? tone;

  final bool isTraversed;
}

/// The full vertical route.
///
/// [stops] must be exactly one longer than [segments]: N stops are joined by
/// N-1 connectors. An inconsistent pair renders what it can rather than
/// throwing, because a malformed journey should cost the user that card, not
/// the screen.
class RouteLine extends StatelessWidget {
  const RouteLine({
    required this.stops,
    required this.segments,
    this.compactSegments = false,
    this.trailing,
    super.key,
  });

  final List<RouteStop> stops;
  final List<RouteSegment> segments;

  /// Shrinks the connectors for a dense list card.
  final bool compactSegments;

  /// Rendered against each stop — a menu, an edit affordance.
  final Widget? Function(int stopIndex)? trailing;

  @override
  Widget build(BuildContext context) {
    if (stops.isEmpty) return const SizedBox.shrink();

    final children = <Widget>[];
    for (var i = 0; i < stops.length; i++) {
      children.add(
        _StopRow(
          stop: stops[i],
          isFirst: i == 0,
          isLast: i == stops.length - 1,
          trailing: trailing?.call(i),
        ),
      );
      if (i < segments.length && i < stops.length - 1) {
        children.add(
          _SegmentRow(segment: segments[i], compact: compactSegments),
        );
      }
    }

    return Semantics(
      container: true,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
    );
  }
}

const double _railWidth = 26;
const double _nodeSize = 12;

class _StopRow extends StatelessWidget {
  const _StopRow({
    required this.stop,
    required this.isFirst,
    required this.isLast,
    this.trailing,
  });

  final RouteStop stop;
  final bool isFirst;
  final bool isLast;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final nodeColour = stop.isCurrent
        ? c.attention
        : (stop.isReached ? c.brand : c.textTertiary);

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: _railWidth,
            child: Column(
              children: [
                // Half-height rail above, so the node sits on a continuous
                // line rather than floating between two stubs.
                SizedBox(
                  height: 7,
                  child: isFirst
                      ? null
                      : Center(child: _Rail(colour: c.hairlineStrong)),
                ),
                _Node(colour: nodeColour, isCurrent: stop.isCurrent),
                Expanded(
                  child: isLast
                      ? const SizedBox.shrink()
                      : Center(child: _Rail(colour: c.hairlineStrong)),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: AppSpace.xs),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    stop.label,
                    style: text.titleSmall?.copyWith(
                      color: stop.isCurrent ? c.textPrimary : null,
                    ),
                  ),
                  if (stop.detail != null)
                    Padding(
                      padding: const EdgeInsets.only(top: AppSpace.xxs),
                      child: Text(
                        stop.detail!,
                        style: text.bodySmall?.copyWith(color: c.textSecondary),
                      ),
                    ),
                  if (stop.timeLabel != null)
                    Padding(
                      padding: const EdgeInsets.only(top: AppSpace.xxs),
                      child: Text(
                        stop.timeLabel!,
                        style: text.bodySmall?.copyWith(color: c.textTertiary),
                      ),
                    ),
                ],
              ),
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class _SegmentRow extends StatelessWidget {
  const _SegmentRow({required this.segment, required this.compact});

  final RouteSegment segment;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final accent = segment.tone != null
        ? StatusStyle.of(context, segment.tone!).accent
        : switch (segment.mode) {
            TransportMode.flight => c.modeFlight,
            TransportMode.drive => c.modeDrive,
            TransportMode.unknown => c.textTertiary,
          };

    final details = <String>[
      segment.modeLabel,
      if (segment.detail != null) segment.detail!,
      if (segment.capacityLabel != null) segment.capacityLabel!,
    ];

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: _railWidth,
            child: Stack(
              alignment: Alignment.center,
              children: [
                Positioned.fill(
                  child: Center(child: _Rail(colour: c.hairlineStrong)),
                ),
                // The mode badge breaks the rail rather than sitting beside
                // it, so the eye reads "this is how you cross this gap".
                Container(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  color: c.surface,
                  child: Icon(segment.mode.icon, size: 15, color: accent),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: Padding(
              padding: EdgeInsets.symmetric(
                vertical: compact ? AppSpace.sm : AppSpace.md,
              ),
              child: Text(
                details.join(' · '),
                style: text.bodySmall?.copyWith(color: c.textSecondary),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Rail extends StatelessWidget {
  const _Rail({required this.colour});

  final Color colour;

  @override
  Widget build(BuildContext context) =>
      Container(width: 1.5, color: colour, height: double.infinity);
}

class _Node extends StatelessWidget {
  const _Node({required this.colour, required this.isCurrent});

  final Color colour;
  final bool isCurrent;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Container(
      width: _nodeSize,
      height: _nodeSize,
      decoration: BoxDecoration(
        color: isCurrent ? colour : c.surface,
        shape: BoxShape.circle,
        border: Border.all(color: colour, width: 2),
      ),
    );
  }
}

/// The one-line form, for list cards where the full line would be too much.
///
/// The arrow is a directional glyph, so it points the way the text runs —
/// mirroring in Arabic instead of pointing back at the origin.
class RouteSummary extends StatelessWidget {
  const RouteSummary({
    required this.from,
    required this.to,
    this.mode,
    this.style,
    super.key,
  });

  final String from;
  final String to;
  final TransportMode? mode;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final effective = style ?? Theme.of(context).textTheme.titleSmall;
    final isRtl = context.isRtl;

    return Semantics(
      label: '$from to $to',
      excludeSemantics: true,
      child: Row(
        children: [
          if (mode != null) ...[
            Icon(mode!.icon, size: 16, color: c.textTertiary),
            const SizedBox(width: AppSpace.sm),
          ],
          Flexible(
            child: Text(
              from,
              style: effective,
              overflow: TextOverflow.ellipsis,
              maxLines: 1,
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpace.sm),
            child: Icon(
              isRtl ? Icons.arrow_back_rounded : Icons.arrow_forward_rounded,
              size: 15,
              color: c.textTertiary,
            ),
          ),
          Flexible(
            child: Text(
              to,
              style: effective,
              overflow: TextOverflow.ellipsis,
              maxLines: 1,
            ),
          ),
        ],
      ),
    );
  }
}
