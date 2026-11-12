/// A parcel's tracking number.
///
/// One widget for every screen that refers to a parcel (plan 1.5 rule 12), so
/// the number looks, reads and copies the same everywhere. It identifies a
/// parcel and authorises nothing: no screen, link or search opens anything from
/// a typed number.
///
/// Three properties are structural rather than left to each screen:
///
/// * **Left to right, always.** `WSL-7K3M9QXD` is a machine token. In Arabic
///   text it is isolated and laid out left to right so it is read, spoken and
///   copied in the order it was issued.
/// * **Spelled out for a screen reader.** "W S L 7 K 3 M 9 Q X D", never "seven
///   K three M nine".
/// * **Absent means nothing.** A payload without a number (an older cached one,
///   or a viewer the server does not show it to) renders no row at all, not a
///   placeholder.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';

import '../../l10n/app_localizations.dart';
import '../tokens.dart';
import '../typography.dart';
import 'primitives.dart';

class TrackingNumberView extends StatefulWidget {
  const TrackingNumberView({
    required this.number,
    this.dense = false,
    super.key,
  });

  /// The server's number, or null/empty to render nothing.
  final String? number;

  /// A single quiet line for lists and cards that open a detail screen: the
  /// label and the number, with no copy button. The detail screen offers it.
  final bool dense;

  @override
  State<TrackingNumberView> createState() => _TrackingNumberViewState();
}

class _TrackingNumberViewState extends State<TrackingNumberView> {
  bool _copied = false;
  Timer? _reset;

  @override
  void dispose() {
    _reset?.cancel();
    super.dispose();
  }

  Future<void> _copy(String number) async {
    final l = L.of(context);
    final view = View.maybeOf(context);
    final direction = Directionality.of(context);
    await Clipboard.setData(ClipboardData(text: number));
    if (!mounted) return;
    HapticFeedback.selectionClick();
    setState(() => _copied = true);
    if (view != null) {
      unawaited(
        SemanticsService.sendAnnouncement(
          view,
          l.trackingNumberCopied,
          direction,
        ),
      );
    }
    _reset?.cancel();
    _reset = Timer(const Duration(seconds: 2), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final number = widget.number?.trim();
    if (number == null || number.isEmpty) return const SizedBox.shrink();

    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final spoken = number.replaceAll('-', '').split('').join(' ');

    final figure = Directionality(
      textDirection: TextDirection.ltr,
      child: Text(
        number,
        maxLines: 1,
        overflow: TextOverflow.fade,
        softWrap: false,
        style: AppTypography.code(
          color: c.textPrimary,
          size: widget.dense ? 13 : 17,
          weight: 500,
        ).copyWith(letterSpacing: widget.dense ? 0.6 : 1.2),
      ),
    );

    if (widget.dense) {
      return Semantics(
        label: '${l.trackingNumberLabel}, $spoken',
        excludeSemantics: true,
        child: Row(
          children: [
            Flexible(
              child: Text(
                l.trackingNumberLabel,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: text.bodySmall?.copyWith(color: c.textTertiary),
              ),
            ),
            const SizedBox(width: AppSpace.sm),
            Flexible(child: figure),
          ],
        ),
      );
    }

    return AppInsetGroup(
      padding: const EdgeInsetsDirectional.only(
        start: AppSpace.lg,
        end: AppSpace.sm,
        top: AppSpace.sm,
        bottom: AppSpace.sm,
      ),
      child: Row(
        children: [
          Expanded(
            child: Semantics(
              label: '${l.trackingNumberLabel}, $spoken',
              excludeSemantics: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    l.trackingNumberLabel,
                    style: text.labelMedium?.copyWith(color: c.textSecondary),
                  ),
                  const SizedBox(height: AppSpace.xs),
                  // Start-aligned in both directions, so the label and the
                  // number share one edge in Arabic.
                  Align(
                    alignment: AlignmentDirectional.centerStart,
                    child: figure,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Semantics(
            button: true,
            label: _copied ? l.actionCopied : l.trackingNumberCopy,
            onTap: () => _copy(number),
            child: ExcludeSemantics(
              child: IconButton(
                onPressed: () => _copy(number),
                tooltip: l.trackingNumberCopy,
                icon: Icon(
                  _copied ? Icons.check_rounded : Icons.copy_rounded,
                  size: 20,
                  color: _copied ? c.success : c.textSecondary,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
