/// Handover codes and the timers that gate them.
///
/// ## The rule this file is built around
///
/// A handover code is the only thing standing between a parcel and the wrong
/// pair of hands. Two invariants follow, and both are structural here rather
/// than left to each screen to remember:
///
/// 1. **A code is never persisted and never logged.** [CodeDisplay] takes the
///    plaintext as a parameter, renders it, and holds no state. Nothing in
///    this file writes to storage, and nothing calls `print`/`debugPrint` with
///    a code. The traveller's screens use [CodeEntryField], which only ever
///    holds what the *recipient* dictated to them — it is never populated from
///    an API response.
///
/// 2. **Availability is the server's word, not a local clock.** [CodeCountdown]
///    counts down to a timestamp the API returned. When it reaches zero it
///    does not unlock anything; it asks the caller to re-request the code from
///    the server, which is the only party that can decide the buffer has
///    elapsed. A device clock that is wrong, or a screen left open for an
///    hour, cannot manufacture access.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/format/locale_formats.dart';
import '../../l10n/app_localizations.dart';
import '../tokens.dart';
import '../typography.dart';
import 'primitives.dart';
import 'status.dart';

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

/// Renders a revealed handover code.
///
/// Monospaced, generously tracked and grouped, because this number is read out
/// loud across a doorstep or a phone line and a misread digit is a failed
/// handover. Forced to LTR: a numeric code is not a sentence and must not
/// reorder in Arabic.
class CodeDisplay extends StatelessWidget {
  const CodeDisplay({
    required this.code,
    required this.label,
    this.formatted,
    this.caption,
    this.tone = StatusTone.good,
    this.onCopy,
    super.key,
  });

  /// The plaintext, straight from the API response and never stored. This is
  /// what gets copied and what a screen reader spells out.
  final String code;

  /// The server's own grouping, e.g. `3F7K-QP9M`. Rendered verbatim when
  /// given, because re-grouping an already-grouped string produces nonsense.
  /// [code] remains the value that is copied.
  final String? formatted;

  final String label;
  final String? caption;
  final StatusTone tone;

  /// Optional clipboard action. Off by default: a code on the clipboard
  /// outlives the screen and can be pasted anywhere, so a screen only offers
  /// it where the user genuinely has to move it into another app.
  final VoidCallback? onCopy;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final style = StatusStyle.of(context, tone);

    return AppInsetGroup(
      background: style.background,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: text.labelLarge?.copyWith(color: style.foreground),
          ),
          const SizedBox(height: AppSpace.md),
          Semantics(
            // Read out character by character. "Four seven two nine" is
            // transcribable; "four thousand seven hundred and twenty-nine"
            // is not.
            label: '$label, ${code.split('').join(' ')}',
            excludeSemantics: true,
            child: Directionality(
              // A code is a machine token. It does not mirror in Arabic, or
              // the recipient reads it out backwards.
              textDirection: TextDirection.ltr,
              child: _CodeTiles(
                text: formatted ?? _grouped(code),
                foreground: style.foreground,
              ),
            ),
          ),
          if (caption != null) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              caption!,
              style: text.bodySmall?.copyWith(color: style.foreground),
            ),
          ],
          if (onCopy != null) ...[
            const SizedBox(height: AppSpace.md),
            AppButton(
              label: l.actionCopy,
              icon: Icons.copy_rounded,
              variant: AppButtonVariant.tertiary,
              expand: false,
              onPressed: () {
                Clipboard.setData(ClipboardData(text: code));
                onCopy!();
              },
            ),
          ],
        ],
      ),
    );
  }

  /// Splits into threes for a six-digit code, pairs otherwise. Grouping is the
  /// difference between a number you can dictate and one you cannot.
  static String _grouped(String code) {
    if (code.length <= 4) return code;
    final size = code.length % 3 == 0 ? 3 : 2;
    final buffer = StringBuffer();
    for (var i = 0; i < code.length; i++) {
      if (i > 0 && i % size == 0) buffer.write(' ');
      buffer.write(code[i]);
    }
    return buffer.toString();
  }
}

/// The code, set one character to a tile.
///
/// This is the ShipTrip handover moment, and the original app gave it the
/// split-flap treatment: each character in its own framed well with a hard
/// stamped shadow and a hairline across the middle, so it reads as something
/// mechanical and official rather than as a line of text.
///
/// It replaced a `SelectableText`, which is a small security improvement as
/// well as a visual one: a handover code on the clipboard outlives the screen
/// and can be pasted anywhere, and screens that genuinely need to move it
/// still offer an explicit copy action. The screen-reader label above spells
/// the code out character by character either way.
class _CodeTiles extends StatelessWidget {
  const _CodeTiles({required this.text, required this.foreground});

  final String text;
  final Color foreground;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    // Scales down rather than wrapping: a code split across two lines is a
    // code that gets read out wrong.
    return FittedBox(
      fit: BoxFit.scaleDown,
      alignment: AlignmentDirectional.centerStart,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (final char in text.split(''))
            if (char == ' ' || char == '-')
              // The server's own grouping, kept as a gap rather than as a
              // tile — the separator is not part of the code.
              const SizedBox(width: AppSpace.md)
            else
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: Container(
                  width: 38,
                  height: 52,
                  decoration: BoxDecoration(
                    color: c.canvas,
                    border: Border.all(color: foreground, width: 1.4),
                    borderRadius: AppRadius.rXs,
                    boxShadow: context.elevation.stamped,
                  ),
                  alignment: Alignment.center,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      Positioned(
                        left: 0,
                        right: 0,
                        top: 25,
                        child: Container(height: 1, color: c.hairline),
                      ),
                      Text(
                        char,
                        style: AppTypography.code(
                          color: foreground,
                          size: 26,
                        ).copyWith(letterSpacing: 0),
                      ),
                    ],
                  ),
                ),
              ),
        ],
      ),
    );
  }
}

/// The locked state of a code that the server has not released yet.
///
/// Shows *why* it is locked and *when* it opens, both from server data. The
/// "why" is not decoration: a sender staring at a hidden code with no
/// explanation assumes the app is broken rather than that the delay is
/// protecting them.
class LockedCodePanel extends StatelessWidget {
  const LockedCodePanel({
    required this.title,
    required this.body,
    this.availableAt,
    this.onAvailable,
    this.explainerTitle,
    this.explainerBody,
    super.key,
  });

  final String title;
  final String body;

  /// Server-issued instant at which the code becomes retrievable. Null when
  /// the server has not armed it yet — the panel then shows no countdown
  /// rather than inventing one.
  final DateTime? availableAt;

  /// Fired once when the countdown crosses zero, so the caller can re-ask the
  /// server. It is the server's answer, not this callback, that unlocks
  /// anything.
  final VoidCallback? onAvailable;

  final String? explainerTitle;
  final String? explainerBody;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppInsetGroup(
      background: c.surfaceSunken,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.lock_clock_rounded, size: 19, color: c.waiting),
              const SizedBox(width: AppSpace.sm),
              Expanded(child: Text(title, style: text.titleSmall)),
            ],
          ),
          const SizedBox(height: AppSpace.sm),
          Text(body, style: text.bodyMedium?.copyWith(color: c.textSecondary)),
          if (availableAt != null) ...[
            const SizedBox(height: AppSpace.lg),
            CodeCountdown(target: availableAt!, onElapsed: onAvailable),
          ],
          if (explainerTitle != null && explainerBody != null) ...[
            const SizedBox(height: AppSpace.lg),
            _WhyDisclosure(title: explainerTitle!, body: explainerBody!),
          ],
        ],
      ),
    );
  }
}

/// A collapsed "why is this locked?" explanation.
class _WhyDisclosure extends StatefulWidget {
  const _WhyDisclosure({required this.title, required this.body});

  final String title;
  final String body;

  @override
  State<_WhyDisclosure> createState() => _WhyDisclosureState();
}

class _WhyDisclosureState extends State<_WhyDisclosure> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          button: true,
          expanded: _open,
          hint: _open ? l.a11yCollapseSection : l.a11yExpandSection,
          child: InkWell(
            onTap: () => setState(() => _open = !_open),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpace.xs),
              child: Row(
                children: [
                  Flexible(
                    child: Text(
                      widget.title,
                      style: text.labelLarge?.copyWith(color: c.brand),
                    ),
                  ),
                  Icon(
                    _open
                        ? Icons.expand_less_rounded
                        : Icons.expand_more_rounded,
                    size: 18,
                    color: c.brand,
                  ),
                ],
              ),
            ),
          ),
        ),
        AnimatedSize(
          duration: AppMotion.respecting(context, AppMotion.fast),
          alignment: Alignment.topCenter,
          child: _open
              ? Padding(
                  padding: const EdgeInsets.only(top: AppSpace.sm),
                  child: Text(
                    widget.body,
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                  ),
                )
              : const SizedBox(width: double.infinity),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Countdown
// ---------------------------------------------------------------------------

/// Counts down to a server-issued instant.
///
/// The tick interval adapts through [CountdownParts.tickInterval] — seconds
/// only in the final hour, minutes above that, daily beyond a day. A 48-hour
/// protection window does not need a timer waking the device every second, and
/// a 30-minute buffer with a minute-granularity clock feels broken.
class CodeCountdown extends StatefulWidget {
  const CodeCountdown({
    required this.target,
    this.onElapsed,
    this.label,
    this.compact = false,
    super.key,
  });

  final DateTime target;
  final VoidCallback? onElapsed;
  final String? label;
  final bool compact;

  @override
  State<CodeCountdown> createState() => _CodeCountdownState();
}

class _CodeCountdownState extends State<CodeCountdown> {
  Timer? _timer;
  late CountdownParts _parts;
  bool _notified = false;

  @override
  void initState() {
    super.initState();
    _parts = CountdownParts.until(widget.target);
    _schedule();
  }

  @override
  void didUpdateWidget(CodeCountdown old) {
    super.didUpdateWidget(old);
    if (old.target != widget.target) {
      _notified = false;
      _parts = CountdownParts.until(widget.target);
      _schedule();
    }
  }

  void _schedule() {
    _timer?.cancel();
    if (_parts.hasElapsed) {
      _fireElapsed();
      return;
    }
    _timer = Timer(_parts.tickInterval, _tick);
  }

  void _tick() {
    if (!mounted) return;
    setState(() => _parts = CountdownParts.until(widget.target));
    _schedule();
  }

  void _fireElapsed() {
    if (_notified) return;
    _notified = true;
    // Out of the build/layout phase: the caller almost always reacts by
    // refetching, which mutates a provider.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) widget.onElapsed?.call();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final rendered = formatCountdown(context, _parts);

    return Semantics(
      liveRegion: true,
      label: widget.label == null ? rendered : '${widget.label} $rendered',
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.schedule_rounded,
            size: widget.compact ? 15 : 18,
            color: c.textSecondary,
          ),
          const SizedBox(width: AppSpace.sm),
          if (widget.label != null) ...[
            Text(
              widget.label!,
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
            const SizedBox(width: AppSpace.sm),
          ],
          // Tabular figures: the digits must not jitter as they change.
          Directionality(
            textDirection: TextDirection.ltr,
            child: Text(
              rendered,
              style: AppTypography.timer(
                context,
                color: c.textPrimary,
                size: widget.compact ? 14 : 17,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// `1d 04h`, `04:12`, `12:03` — chosen by magnitude, never zero-padded past
/// what the magnitude needs.
String formatCountdown(BuildContext context, CountdownParts parts) {
  if (parts.hasElapsed) return '00:00';
  String two(int v) => v.toString().padLeft(2, '0');
  if (parts.days > 0) return '${parts.days}d ${two(parts.hours)}h';
  if (parts.hours > 0) return '${two(parts.hours)}:${two(parts.minutes)}';
  return '${two(parts.minutes)}:${two(parts.seconds)}';
}

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

/// The field a traveller types a handover code into.
///
/// Deliberately a single text field with a numeric keypad rather than a row of
/// per-digit boxes: split boxes fight autofill, fight paste, break under RTL
/// and are hostile to a screen reader, all to look like a security product.
/// The field is forced to LTR so digits stay in dictation order in Arabic.
///
/// Two alphabets, one field. The email and password-reset codes are six
/// digits and get a numeric keypad, which is why [allowLetters] defaults to
/// false — handing those a full keyboard would be a regression. Handover
/// codes are eight alphanumeric characters (`3F7KQP9M`), so they opt in and
/// are upper-cased as the user types, because the code was dictated aloud and
/// nobody says "lowercase f".
class CodeEntryField extends StatelessWidget {
  const CodeEntryField({
    required this.controller,
    required this.label,
    required this.length,
    this.errorText,
    this.attemptsRemaining,
    this.allowLetters = false,
    this.enabled = true,
    this.onSubmitted,
    this.autofocus = true,
    super.key,
  });

  final TextEditingController controller;
  final String label;

  /// Expected character count, from the server's own contract.
  final int length;

  final String? errorText;

  /// Server-reported remaining attempts. Shown only once the server has
  /// started counting — a fresh field should not open with a threat.
  final int? attemptsRemaining;

  /// Accept A–Z alongside 0–9 and open a text keyboard. Handover codes only.
  final bool allowLetters;

  final bool enabled;
  final ValueChanged<String>? onSubmitted;
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: text.labelLarge?.copyWith(color: c.textSecondary)),
        const SizedBox(height: AppSpace.sm),
        Directionality(
          textDirection: TextDirection.ltr,
          child: TextField(
            controller: controller,
            enabled: enabled,
            autofocus: autofocus,
            // `visiblePassword` rather than `text`: it is the ASCII-capable
            // keyboard on both platforms, so an Arabic-locale user is not
            // handed a keyboard that cannot type the code they were given.
            keyboardType: allowLetters
                ? TextInputType.visiblePassword
                : const TextInputType.numberWithOptions(signed: false),
            textCapitalization: allowLetters
                ? TextCapitalization.characters
                : TextCapitalization.none,
            textInputAction: TextInputAction.done,
            onSubmitted: onSubmitted,
            textAlign: TextAlign.center,
            maxLength: length,
            // No autofill, no suggestions, no autocorrect. A handover code is
            // not something the OS should learn or offer to complete.
            autofillHints: const [],
            enableSuggestions: false,
            autocorrect: false,
            // The server normalises case, spaces and dashes, so the field
            // accepts whatever the user heard and only strips what could never
            // be part of a code.
            inputFormatters: [
              if (allowLetters) ...[
                FilteringTextInputFormatter.allow(RegExp('[A-Za-z0-9]')),
                _upperCase,
              ] else
                FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(length),
            ],
            style: AppTypography.code(color: c.textPrimary, size: 26),
            decoration: InputDecoration(
              counterText: '',
              errorText: errorText,
              errorMaxLines: 3,
              hintText: '•' * length,
              hintStyle: AppTypography.code(color: c.textTertiary, size: 26),
            ),
          ),
        ),
        if (attemptsRemaining != null) ...[
          const SizedBox(height: AppSpace.sm),
          Semantics(
            liveRegion: true,
            child: Row(
              children: [
                Icon(
                  Icons.info_outline_rounded,
                  size: 15,
                  color: attemptsRemaining! <= 1 ? c.danger : c.textTertiary,
                ),
                const SizedBox(width: AppSpace.sm),
                Expanded(
                  child: Text(
                    l.codeAttemptsRemaining(attemptsRemaining!),
                    style: text.bodySmall?.copyWith(
                      color: attemptsRemaining! <= 1
                          ? c.danger
                          : c.textTertiary,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}

/// Upper-cases as the user types. Length is unchanged, so the caret and any
/// selection survive untouched.
final TextInputFormatter _upperCase = TextInputFormatter.withFunction(
  (_, next) => next.copyWith(text: next.text.toUpperCase()),
);
