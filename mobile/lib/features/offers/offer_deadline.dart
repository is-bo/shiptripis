/// How long a proposal has left, in words (spec 17).
///
/// The server sets the deadline when it writes the proposal and publishes it as
/// `expires_at`; this line only says it. Whose turn it is comes from the
/// offer's own `awaiting_user_id`, never from anything computed here.
///
/// Far from the deadline it names the moment ("Answer by Today, 18:30"), in the
/// device's time zone. In the last hour it becomes a calm countdown in whole
/// minutes. When the time runs out under the user's eyes it says so and asks
/// the screen to re-read, so the server's word ("expired", no actions) replaces
/// the countdown; it never expires anything itself.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format/locale_formats.dart';
import '../../core/time/clock.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/offer.dart';
import '../../l10n/app_localizations.dart';

/// The last hour is when the countdown replaces the clock time.
const countdownWindow = Duration(hours: 1);

class OfferDeadline extends ConsumerStatefulWidget {
  const OfferDeadline({
    required this.offer,
    required this.viewerId,
    this.onElapsed,
    this.dense = false,
    super.key,
  });

  final Offer offer;
  final int viewerId;

  /// Called once when the deadline passes while this line is on screen.
  final VoidCallback? onElapsed;

  /// A list row: small text, no icon background.
  final bool dense;

  @override
  ConsumerState<OfferDeadline> createState() => _OfferDeadlineState();
}

class _OfferDeadlineState extends ConsumerState<OfferDeadline> {
  Timer? _timer;
  bool _elapsedReported = false;

  @override
  void initState() {
    super.initState();
    _arm();
  }

  @override
  void didUpdateWidget(OfferDeadline old) {
    super.didUpdateWidget(old);
    if (old.offer.id != widget.offer.id ||
        old.offer.expiresAt != widget.offer.expiresAt) {
      _elapsedReported = false;
      _arm();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Duration? _remaining() {
    final end = widget.offer.expiresAt;
    if (end == null || !widget.offer.status.isOpen) return null;
    return end.difference(ref.read(clockProvider)());
  }

  /// One timer, re-armed on every tick: a minute apart while the deadline is
  /// far, a few seconds apart in the last hour, and exactly at the deadline.
  void _arm() {
    _timer?.cancel();
    final left = _remaining();
    if (left == null || left <= Duration.zero) return;
    final step = left > countdownWindow
        ? const Duration(minutes: 1)
        : const Duration(seconds: 15);
    _timer = Timer(left < step ? left : step, () {
      if (!mounted) return;
      setState(() {});
      _arm();
    });
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);
    final offer = widget.offer;
    final end = offer.expiresAt;

    final String label;
    final IconData icon;
    var tone = StatusTone.neutral;

    if (offer.status == OfferStatus.expired) {
      if (end == null) return const SizedBox.shrink();
      label = l.offerExpiredOn(LocaleFormats.dateTime(locale, end));
      icon = Icons.timer_off_rounded;
    } else {
      final left = _remaining();
      if (left == null || end == null) return const SizedBox.shrink();
      final mine = offer.isAwaiting(widget.viewerId);
      if (left <= Duration.zero) {
        if (!_elapsedReported) {
          _elapsedReported = true;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) widget.onElapsed?.call();
          });
        }
        label = l.offerDeadlinePassed;
        icon = Icons.timer_off_rounded;
      } else if (left <= countdownWindow) {
        // Whole minutes, rounded up; the last minute says "less than a minute".
        final time = l.offerMinutesLeft(
          left.inSeconds <= 60 ? 0 : (left.inSeconds / 60).ceil(),
        );
        label = mine ? l.offerAnswerWithin(time) : l.offerWaitingWithin(time);
        icon = Icons.hourglass_bottom_rounded;
        tone = StatusTone.waiting;
      } else {
        final when = LocaleFormats.dateTime(locale, end);
        label = mine ? l.offerAnswerBy(when) : l.offerWaitingUntil(when);
        icon = Icons.schedule_rounded;
      }
    }

    final style = StatusStyle.of(context, tone);
    final color = tone == StatusTone.neutral
        ? c.textSecondary
        : style.foreground;
    final text = Theme.of(context).textTheme;

    return Semantics(
      container: true,
      label: label,
      child: ExcludeSemantics(
        child: Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 1),
              child: Icon(
                icon,
                size: widget.dense ? 14 : 16,
                color: tone == StatusTone.neutral
                    ? c.textTertiary
                    : style.accent,
              ),
            ),
            const SizedBox(width: AppSpace.xs),
            Flexible(
              child: Text(
                label,
                style: (widget.dense ? text.bodySmall : text.bodyMedium)
                    ?.copyWith(color: color),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
