/// Form controls.
///
/// Decisions worth stating once, here, rather than re-litigating per screen:
///
/// * **Labels sit above the field, permanently.** Material's floating label
///   disappears into the border once the field has content, which is exactly
///   when a user proof-reading a payment or a recipient address needs it. A
///   static label also survives Arabic and long French strings without the
///   truncation a floating label suffers inside a 1-line border gap.
///
/// * **An error replaces nothing.** Helper text and error text occupy the same
///   reserved line, so a field that goes invalid does not shift the layout and
///   push the submit button under the user's thumb mid-tap.
///
/// * **Required is stated, not implied by an asterisk alone.** The asterisk is
///   decoration; the screen reader gets the word, via `a11yRequiredField`.
///
/// * **Server field errors land on the field.** [FieldErrorMap] carries a
///   validation failure from the API back onto the exact input that caused it
///   instead of a generic banner at the top of the form.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/api/api_exception.dart';
import '../../l10n/app_localizations.dart';
import '../tokens.dart';
import 'primitives.dart';

// ---------------------------------------------------------------------------
// Server-side field errors
// ---------------------------------------------------------------------------

/// Validation errors returned by the API, keyed by the field name the server
/// used.
///
/// Screens hold one of these next to their form state and clear it on the next
/// submit. The messages are server strings, so they are shown only when the
/// server had something field-specific to say and no local rule already
/// covers it.
@immutable
class FieldErrorMap {
  const FieldErrorMap(this._errors);

  const FieldErrorMap.empty() : _errors = const {};

  factory FieldErrorMap.from(Object? error) => error is ApiException
      ? FieldErrorMap(error.fieldErrors)
      : const FieldErrorMap.empty();

  final Map<String, List<String>> _errors;

  bool get isEmpty => _errors.isEmpty;
  bool get isNotEmpty => _errors.isNotEmpty;

  /// The first message for [field], or null.
  String? operator [](String field) {
    final list = _errors[field];
    return (list == null || list.isEmpty) ? null : list.first;
  }

  /// True when any of [fields] currently carries a server error.
  bool touchesAny(Iterable<String> fields) => fields.any(_errors.containsKey);

  /// The same map without [fields].
  ///
  /// A server error is a verdict on the value that was sent. The moment the
  /// user changes that value the verdict is about something that no longer
  /// exists, and keeping it is worse than useless: it goes on colouring the
  /// field red and — on any screen that gates its submit on the absence of
  /// server errors — goes on blocking the user from correcting anything.
  ///
  /// That was a real dead end in the request form. A rejected field kept its
  /// error, the error kept `Form.validate()` false, and `validate()` kept the
  /// Next button inert; the only escape from a four-step form was to abandon
  /// it and re-enter everything. Superseding on edit is the fix, and it is
  /// deliberately per-field: correcting a weight says nothing about a title.
  FieldErrorMap without(Iterable<String> fields) {
    final drop = fields.toSet();
    if (!drop.any(_errors.containsKey)) return this;
    return FieldErrorMap({
      for (final entry in _errors.entries)
        if (!drop.contains(entry.key)) entry.key: entry.value,
    });
  }

  /// Errors the form has no field for — `non_field_errors` and anything whose
  /// key the screen did not claim. Shown as a notice above the form so a
  /// rejection is never silent.
  List<String> unclaimed(Set<String> claimed) => [
    for (final entry in _errors.entries)
      if (!claimed.contains(entry.key)) ...entry.value,
  ];
}

// ---------------------------------------------------------------------------
// Validators
// ---------------------------------------------------------------------------

/// Local, synchronous validation.
///
/// Deliberately thin. These check shape only — that a field is present, that
/// an email looks like one, that a number is a number. Anything with a
/// business meaning (a minimum reward, a capacity, a deadline the corridor can
/// actually serve) is the server's call and is surfaced through
/// [FieldErrorMap] instead of guessed here.
class Validators {
  const Validators(this._l);

  factory Validators.of(BuildContext context) => Validators(L.of(context));

  final L _l;

  String? required(String? value) =>
      (value == null || value.trim().isEmpty) ? _l.validationRequired : null;

  String? email(String? value) {
    final v = value?.trim() ?? '';
    if (v.isEmpty) return _l.validationRequired;
    // Intentionally permissive. Deliverability is proven by the verification
    // mail, not by a regex; a strict pattern only rejects valid addresses.
    final ok = RegExp(r'^[^@\s]+@[^@\s.]+\.[^@\s]+$').hasMatch(v);
    return ok ? null : _l.validationEmailInvalid;
  }

  String? password(String? value) {
    if (value == null || value.isEmpty) return _l.validationRequired;
    return value.length < 8 ? _l.validationPasswordTooShort : null;
  }

  String? maxLength(String? value, int max) =>
      (value != null && value.characters.length > max)
      ? _l.validationTooLong(max)
      : null;

  /// A positive decimal. Accepts both `.` and `,` because a French or Arabic
  /// keyboard offers the comma and typing it should not be an error.
  String? positiveNumber(String? value, {bool allowEmpty = false}) {
    final v = value?.trim() ?? '';
    if (v.isEmpty) return allowEmpty ? null : _l.validationRequired;
    final parsed = double.tryParse(v.replaceAll(',', '.'));
    if (parsed == null) return _l.validationNumberInvalid;
    return parsed > 0 ? null : _l.validationMustBePositive;
  }
}

/// Parses a user-entered decimal, accepting a comma as the separator.
double? parseDecimalInput(String? raw) {
  final v = raw?.trim().replaceAll(',', '.');
  if (v == null || v.isEmpty) return null;
  return double.tryParse(v);
}

// ---------------------------------------------------------------------------
// Text field
// ---------------------------------------------------------------------------

class AppTextField extends StatelessWidget {
  const AppTextField({
    required this.label,
    required this.controller,
    this.hint,
    this.helper,
    this.errorText,
    this.validator,
    this.keyboardType,
    this.textInputAction,
    this.obscureText = false,
    this.enabled = true,
    this.maxLines = 1,
    this.minLines,
    this.maxLength,
    this.isRequired = false,
    this.autofillHints,
    this.prefixIcon,
    this.suffix,
    this.unit,
    this.inputFormatters,
    this.onChanged,
    this.onSubmitted,
    this.focusNode,
    this.autofocus = false,
    this.textCapitalization = TextCapitalization.none,
    super.key,
  });

  final String label;
  final TextEditingController controller;
  final String? hint;
  final String? helper;

  /// A server-supplied error for this field. Takes precedence over [validator].
  final String? errorText;

  final String? Function(String?)? validator;
  final TextInputType? keyboardType;
  final TextInputAction? textInputAction;
  final bool obscureText;
  final bool enabled;
  final int maxLines;
  final int? minLines;
  final int? maxLength;
  final bool isRequired;
  final Iterable<String>? autofillHints;
  final IconData? prefixIcon;

  /// A trailing *control* — a reveal-password button, a clear button. Lives in
  /// Material's `suffixIcon` slot, which is centred in a 48pt tap target, and
  /// that is right for something you press.
  final Widget? suffix;

  /// A trailing *unit* — `€`, `kg`, `cm`. Not a control, and emphatically not
  /// an icon: see [_FieldUnit] for why it cannot share the `suffix` slot.
  final String? unit;

  final List<TextInputFormatter>? inputFormatters;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final FocusNode? focusNode;
  final bool autofocus;
  final TextCapitalization textCapitalization;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _FieldLabel(label: label, isRequired: isRequired),
        const SizedBox(height: AppSpace.sm),
        TextFormField(
          controller: controller,
          focusNode: focusNode,
          autofocus: autofocus,
          enabled: enabled,
          obscureText: obscureText,
          keyboardType: keyboardType,
          textInputAction: textInputAction,
          textCapitalization: textCapitalization,
          maxLines: obscureText ? 1 : maxLines,
          minLines: minLines,
          maxLength: maxLength,
          autofillHints: autofillHints,
          inputFormatters: inputFormatters,
          onChanged: onChanged,
          onFieldSubmitted: onSubmitted,
          validator: (value) => errorText ?? validator?.call(value),
          style: text.bodyLarge,
          decoration: InputDecoration(
            hintText: hint,
            prefixIcon: prefixIcon == null
                ? null
                : Icon(prefixIcon, size: 19, color: c.textTertiary),
            suffixIcon: unit == null ? suffix : _FieldUnit(label: unit!),
            // A unit is text, and text has to line up with the number beside
            // it. The default 48pt minimum turns the slot into a tap target
            // whose *top edge* the label is pinned to, which is what left `€`
            // and `kg` floating above the digits. Shrink-wrapping the box lets
            // the decorator centre it on the input instead.
            suffixIconConstraints: unit == null
                ? null
                : const BoxConstraints(minWidth: 0, minHeight: 0),
            // The counter is noise on every field we have; length limits are
            // enforced silently and explained in the helper where they matter.
            counterText: '',
            errorText: errorText,
            // Reserved so an appearing error does not reflow the form.
            helperText: helper ?? ' ',
            helperMaxLines: 3,
            errorMaxLines: 3,
          ),
        ),
        // The screen reader is told the field is required as a word, not as a
        // glyph it may or may not announce.
        if (isRequired)
          ExcludeSemantics(
            excluding: false,
            child: Semantics(
              label: l.a11yRequiredField,
              child: const SizedBox.shrink(),
            ),
          ),
      ],
    );
  }
}

/// A unit label inside a field: `€`, `kg`, `cm`.
///
/// Material has two trailing slots and they behave differently. `suffix` is
/// baseline-aligned with the input but only *appears* once the field has focus
/// or content, so a unit put there vanishes from an empty field. `suffixIcon`
/// is always visible but is laid out as an icon: centred inside a box whose
/// minimum height is 48, with a bare `Padding` child pinned to that box's top
/// edge. That is the bug the owner saw — the glyph sat well above the digits.
///
/// So the unit goes in `suffixIcon` with the minimum dropped, which
/// shrink-wraps the box to the text and lets the decorator centre it on the
/// input line. The style deliberately matches the input's own `bodyLarge`, so
/// centring the two boxes lines up their baselines rather than merely their
/// middles. It holds in RTL, where the slot moves to the leading edge, and at
/// large text sizes, where both sides scale together.
class _FieldUnit extends StatelessWidget {
  const _FieldUnit({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsetsDirectional.only(
      start: AppSpace.sm,
      end: AppSpace.lg,
    ),
    child: Text(
      label,
      textAlign: TextAlign.center,
      style: Theme.of(
        context,
      ).textTheme.bodyLarge?.copyWith(color: context.colors.textSecondary),
    ),
  );
}

class _FieldLabel extends StatelessWidget {
  const _FieldLabel({required this.label, required this.isRequired});

  final String label;
  final bool isRequired;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    return Row(
      children: [
        Flexible(
          child: Text(
            label,
            style: text.labelLarge?.copyWith(color: c.textSecondary),
          ),
        ),
        if (isRequired)
          Padding(
            padding: const EdgeInsetsDirectional.only(start: 3),
            child: ExcludeSemantics(
              child: Text(
                '*',
                style: text.labelLarge?.copyWith(color: c.danger),
              ),
            ),
          ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Selection field
// ---------------------------------------------------------------------------

/// A field whose value is chosen elsewhere — from a sheet, a map, a picker.
///
/// Looks like a text field so a form reads as one rhythm, but behaves like a
/// button. Renders [placeholder] in the hint tone when empty so an unfilled
/// requirement is visible at a glance.
class AppSelectField extends StatelessWidget {
  const AppSelectField({
    required this.label,
    required this.placeholder,
    required this.onTap,
    this.value,
    this.secondary,
    this.helper,
    this.errorText,
    this.isRequired = false,
    this.enabled = true,
    this.icon,
    this.trailingIcon = Icons.expand_more_rounded,
    super.key,
  });

  final String label;
  final String placeholder;
  final VoidCallback onTap;
  final String? value;
  final String? secondary;
  final String? helper;
  final String? errorText;
  final bool isRequired;
  final bool enabled;
  final IconData? icon;
  final IconData trailingIcon;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final hasValue = value != null && value!.isNotEmpty;
    final hasError = errorText != null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _FieldLabel(label: label, isRequired: isRequired),
        const SizedBox(height: AppSpace.sm),
        Semantics(
          button: true,
          enabled: enabled,
          label: label,
          value: hasValue ? value : placeholder,
          // Re-declared: `ExcludeSemantics` below drops the InkWell's tap
          // action along with the duplicated inner text, and a labelled button
          // that cannot be activated is worse than an unlabelled one.
          onTap: enabled ? onTap : null,
          child: ExcludeSemantics(
            child: Material(
              color: enabled ? c.surface : c.surfaceSunken,
              borderRadius: AppRadius.rMd,
              child: InkWell(
                onTap: enabled ? onTap : null,
                borderRadius: AppRadius.rMd,
                child: Container(
                  constraints: const BoxConstraints(
                    minHeight: AppSpace.minTapTarget + 4,
                  ),
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpace.lg,
                    vertical: AppSpace.md,
                  ),
                  decoration: BoxDecoration(
                    borderRadius: AppRadius.rMd,
                    border: Border.all(
                      color: hasError ? c.danger : c.hairlineStrong,
                    ),
                  ),
                  child: Row(
                    children: [
                      if (icon != null) ...[
                        Icon(icon, size: 19, color: c.textTertiary),
                        const SizedBox(width: AppSpace.md),
                      ],
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              hasValue ? value! : placeholder,
                              style: text.bodyLarge?.copyWith(
                                color: hasValue
                                    ? c.textPrimary
                                    : c.textTertiary,
                              ),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                            if (secondary != null && hasValue)
                              Padding(
                                padding: const EdgeInsets.only(
                                  top: AppSpace.xxs,
                                ),
                                child: Text(
                                  secondary!,
                                  style: text.bodySmall?.copyWith(
                                    color: c.textSecondary,
                                  ),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                          ],
                        ),
                      ),
                      const SizedBox(width: AppSpace.sm),
                      Icon(trailingIcon, size: 20, color: c.textTertiary),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
        _FieldFootnote(helper: helper, errorText: errorText),
      ],
    );
  }
}

class _FieldFootnote extends StatelessWidget {
  const _FieldFootnote({this.helper, this.errorText});

  final String? helper;
  final String? errorText;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final message = errorText ?? helper;

    return Padding(
      padding: const EdgeInsets.only(top: AppSpace.xs, bottom: AppSpace.sm),
      child: Text(
        message ?? ' ',
        style: text.bodySmall?.copyWith(
          color: errorText != null ? c.danger : c.textTertiary,
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Choice controls
// ---------------------------------------------------------------------------

/// A row of mutually exclusive options, for two or three short choices.
///
/// Keeps both options visible instead of hiding one behind a dropdown, which
/// matters for the choices this product makes users take: flight or drive,
/// city or exact address.
class AppSegmentedChoice<T> extends StatelessWidget {
  const AppSegmentedChoice({
    required this.options,
    required this.selected,
    required this.onSelect,
    this.label,
    this.helper,
    this.errorText,
    this.enabled = true,
    super.key,
  });

  final List<AppChoice<T>> options;
  final T? selected;
  final ValueChanged<T> onSelect;
  final String? label;

  /// The same reserved footnote line every other field in this file uses, so a
  /// choice sitting between two text fields keeps the form's vertical rhythm
  /// instead of collapsing the gap under it.
  final String? helper;
  final String? errorText;

  /// Read-only rather than absent. A form the server has locked still has to
  /// show what was chosen; hiding the control would leave the user guessing.
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (label != null) ...[
          _FieldLabel(label: label!, isRequired: false),
          const SizedBox(height: AppSpace.sm),
        ],
        Container(
          padding: const EdgeInsets.all(3),
          decoration: BoxDecoration(
            color: c.surfaceSunken,
            borderRadius: AppRadius.rMd,
          ),
          child: Row(
            children: [
              for (final option in options)
                Expanded(
                  child: Semantics(
                    button: true,
                    enabled: enabled,
                    selected: option.value == selected,
                    label: option.label,
                    onTap: enabled ? () => onSelect(option.value) : null,
                    child: ExcludeSemantics(
                      child: Material(
                        color: option.value == selected
                            ? c.surface
                            : Colors.transparent,
                        borderRadius: AppRadius.rSm,
                        child: InkWell(
                          onTap: enabled ? () => onSelect(option.value) : null,
                          borderRadius: AppRadius.rSm,
                          child: Container(
                            height: AppSpace.minTapTarget - 4,
                            alignment: Alignment.center,
                            padding: const EdgeInsets.symmetric(
                              horizontal: AppSpace.sm,
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                if (option.icon != null) ...[
                                  Icon(
                                    option.icon,
                                    size: 17,
                                    color: !enabled
                                        ? c.textTertiary
                                        : option.value == selected
                                        ? c.brand
                                        : c.textTertiary,
                                  ),
                                  const SizedBox(width: AppSpace.sm),
                                ],
                                Flexible(
                                  // Shrink-to-fit rather than ellipsise.
                                  // These labels are the choice itself, and a
                                  // language picker that offers "França..."
                                  // at large text scale has failed at the one
                                  // thing it exists to do. `scaleDown` never
                                  // enlarges, so nothing changes at 1x.
                                  child: FittedBox(
                                    fit: BoxFit.scaleDown,
                                    child: Text(
                                      option.label,
                                      maxLines: 1,
                                      style: text.labelLarge?.copyWith(
                                        color: !enabled
                                            ? c.textTertiary
                                            : option.value == selected
                                            ? c.textPrimary
                                            : c.textSecondary,
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
        if (helper != null || errorText != null)
          _FieldFootnote(helper: helper, errorText: errorText),
      ],
    );
  }
}

@immutable
class AppChoice<T> {
  const AppChoice({
    required this.value,
    required this.label,
    this.detail,
    this.icon,
  });

  final T value;
  final String label;
  final String? detail;
  final IconData? icon;
}

/// A tick-box with its statement beside it, sized so the whole row is the
/// target.
///
/// Used for the acknowledgements a sender must make before publishing. Each
/// one is a separate, separately-recorded statement rather than a single
/// "I agree to everything" — they are distinct claims about a physical parcel.
class AppCheckTile extends StatelessWidget {
  const AppCheckTile({
    required this.value,
    required this.onChanged,
    required this.title,
    this.subtitle,
    this.errorText,
    this.linkLabel,
    this.onLink,
    super.key,
  });

  final bool value;
  final ValueChanged<bool> onChanged;
  final String title;
  final String? subtitle;
  final String? errorText;
  final String? linkLabel;
  final VoidCallback? onLink;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Semantics(
      checked: value,
      label: title,
      onTap: () => onChanged(!value),
      child: ExcludeSemantics(
        child: InkWell(
          onTap: () => onChanged(!value),
          borderRadius: AppRadius.rSm,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpace.sm),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 26,
                  height: 26,
                  child: Checkbox(
                    value: value,
                    onChanged: (v) => onChanged(v ?? false),
                    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    visualDensity: VisualDensity.compact,
                  ),
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: text.bodyMedium),
                      if (subtitle != null)
                        Padding(
                          padding: const EdgeInsets.only(top: AppSpace.xxs),
                          child: Text(
                            subtitle!,
                            style: text.bodySmall?.copyWith(
                              color: c.textSecondary,
                            ),
                          ),
                        ),
                      if (linkLabel != null && onLink != null)
                        Padding(
                          padding: const EdgeInsets.only(top: AppSpace.xs),
                          child: GestureDetector(
                            onTap: onLink,
                            child: Text(
                              linkLabel!,
                              style: text.labelMedium?.copyWith(
                                color: c.brand,
                                decoration: TextDecoration.underline,
                                decorationColor: c.brand,
                              ),
                            ),
                          ),
                        ),
                      if (errorText != null)
                        Padding(
                          padding: const EdgeInsets.only(top: AppSpace.xs),
                          child: Text(
                            errorText!,
                            style: text.bodySmall?.copyWith(color: c.danger),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Amount field
// ---------------------------------------------------------------------------

/// A field for entering a euro amount.
///
/// Returns whole euros as an integer count of cents through [onCents]; it does
/// no other arithmetic. What the user offers is an input to the server, which
/// decides whether it clears the minimum and what the sender's total becomes.
class AppAmountField extends StatelessWidget {
  const AppAmountField({
    required this.label,
    required this.controller,
    this.helper,
    this.errorText,
    this.isRequired = true,
    this.enabled = true,
    this.onChanged,
    this.focusNode,
    super.key,
  });

  final String label;
  final TextEditingController controller;
  final String? helper;
  final String? errorText;
  final bool isRequired;
  final bool enabled;
  final ValueChanged<String>? onChanged;

  /// Held by the screen when it needs to put the cursor on this field — a
  /// multi-step form that refuses to advance has to say *where*, and moving
  /// focus is half of saying it.
  final FocusNode? focusNode;

  /// Cents currently in the field, or null if it is not a usable amount.
  static int? centsOf(TextEditingController controller) {
    final value = parseDecimalInput(controller.text);
    if (value == null || value < 0) return null;
    return (value * 100).round();
  }

  @override
  Widget build(BuildContext context) {
    return AppTextField(
      label: label,
      controller: controller,
      helper: helper,
      errorText: errorText,
      isRequired: isRequired,
      enabled: enabled,
      onChanged: onChanged,
      focusNode: focusNode,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      textInputAction: TextInputAction.done,
      inputFormatters: [
        FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
        LengthLimitingTextInputFormatter(9),
      ],
      prefixIcon: null,
      unit: '€',
    );
  }
}

// ---------------------------------------------------------------------------
// Amount stepper
// ---------------------------------------------------------------------------

/// A euro amount with a decrement and an increment control: `− [ 30.00 € ] +`.
///
/// ## Why this is one widget and not three (Phase J7A)
///
/// The request form built this control by hand — two `IconButton.outlined`s in
/// a `Row` either side of an [AppAmountField], each nudged down by a hard-coded
/// `EdgeInsets.only(top: 8)`. That row aligned on `CrossAxisAlignment.start`,
/// and the amount field carries its own label above the input box. So the
/// buttons started 8 points below the top of the *label* while the input box
/// started below the whole label line: on a phone the two circles sat visibly
/// higher than the digits they changed, and the gap grew with the text scale,
/// because the label grows and the magic 8 does not.
///
/// There is no padding constant that fixes that, because the mismatch is a
/// function of the label's rendered height. So the three controls become one
/// component: a single bordered box, one label above the whole thing, and the
/// buttons stretched to exactly the input's height by [IntrinsicHeight]. They
/// cannot drift, at any text scale, in any language, because nothing positions
/// them independently any more.
///
/// ## What it does not do
///
/// No arithmetic. [onDecrement] and [onIncrement] are callbacks; the step size,
/// the floor and the ceiling belong to the screen, which gets them from the
/// server. In Arabic the box mirrors as a whole — `−` moves to the right — but
/// the meaning does not: minus still decreases. Arithmetic is not a direction.
class AppAmountStepper extends StatefulWidget {
  const AppAmountStepper({
    required this.label,
    required this.controller,
    required this.onDecrement,
    required this.onIncrement,
    required this.decrementLabel,
    required this.incrementLabel,
    this.helper,
    this.errorText,
    this.enabled = true,
    this.labelVisible = true,
    this.onChanged,
    this.focusNode,
    super.key,
  });

  final String label;
  final TextEditingController controller;

  /// Draws [label] above the control.
  ///
  /// Set false where a section heading directly above already says the same
  /// words — "Your offer" twice in four lines is not two pieces of
  /// information. The label is still attached to the input for a screen
  /// reader, which has no heading in view to borrow from.
  final bool labelVisible;

  /// Accessible names for the two controls. They say what changes and by how
  /// much ("Decrease by 50 cents"), because "minus" is not an answer to "what
  /// does this button do".
  final String decrementLabel;
  final String incrementLabel;

  final VoidCallback? onDecrement;
  final VoidCallback? onIncrement;
  final String? helper;
  final String? errorText;
  final bool enabled;
  final ValueChanged<String>? onChanged;
  final FocusNode? focusNode;

  @override
  State<AppAmountStepper> createState() => _AppAmountStepperState();
}

class _AppAmountStepperState extends State<AppAmountStepper> {
  FocusNode? _owned;
  late FocusNode _node;

  @override
  void initState() {
    super.initState();
    _node = widget.focusNode ?? (_owned = FocusNode());
    _node.addListener(_onFocusChanged);
  }

  @override
  void didUpdateWidget(AppAmountStepper old) {
    super.didUpdateWidget(old);
    if (widget.focusNode != old.focusNode) {
      _node.removeListener(_onFocusChanged);
      _owned?.dispose();
      _owned = null;
      _node = widget.focusNode ?? (_owned = FocusNode());
      _node.addListener(_onFocusChanged);
    }
  }

  @override
  void dispose() {
    _node.removeListener(_onFocusChanged);
    _owned?.dispose();
    super.dispose();
  }

  void _onFocusChanged() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final hasError = widget.errorText != null;

    final border = hasError
        ? BorderSide(color: c.danger, width: _node.hasFocus ? 2 : 1)
        : _node.hasFocus
        ? BorderSide(color: c.textPrimary, width: 1.6)
        : BorderSide(color: c.hairline);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (widget.labelVisible) ...[
          _FieldLabel(label: widget.label, isRequired: true),
          const SizedBox(height: AppSpace.sm),
        ],
        DecoratedBox(
          decoration: BoxDecoration(
            color: widget.enabled ? c.surfaceRaised : c.surfaceSunken,
            borderRadius: AppRadius.rMd,
            border: Border.fromBorderSide(border),
          ),
          // The whole point of the component. Every child is stretched to the
          // row's intrinsic height, which is the input's height — so the two
          // buttons are exactly as tall as the field between them and share
          // its vertical centre by construction rather than by arithmetic.
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _StepControl(
                  icon: Icons.remove_rounded,
                  label: widget.decrementLabel,
                  onPressed: widget.enabled ? widget.onDecrement : null,
                  side: _StepSide.start,
                ),
                _StepperRule(color: c.hairline),
                Expanded(
                  child: Center(
                    // The label is attached here rather than only drawn above,
                    // so hiding it is a visual decision and never an
                    // accessibility one: the input announces itself either way.
                    child: Semantics(
                      label: widget.label,
                      child: TextField(
                        controller: widget.controller,
                        focusNode: _node,
                        enabled: widget.enabled,
                        onChanged: widget.onChanged,
                        style: text.bodyLarge,
                        keyboardType: const TextInputType.numberWithOptions(
                          decimal: true,
                        ),
                        textInputAction: TextInputAction.done,
                        inputFormatters: [
                          FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
                          LengthLimitingTextInputFormatter(9),
                        ],
                        decoration: InputDecoration(
                          // The box around the whole control already draws the
                          // border and the fill; a second one inside it would be
                          // a field inside a field.
                          filled: false,
                          border: InputBorder.none,
                          enabledBorder: InputBorder.none,
                          focusedBorder: InputBorder.none,
                          errorBorder: InputBorder.none,
                          focusedErrorBorder: InputBorder.none,
                          disabledBorder: InputBorder.none,
                          isDense: true,
                          counterText: '',
                          helperText: null,
                          errorText: null,
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: AppSpace.md,
                            vertical: AppSpace.lg,
                          ),
                          suffixIcon: const _FieldUnit(label: '€'),
                          suffixIconConstraints: const BoxConstraints(
                            minWidth: 0,
                            minHeight: 0,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                _StepperRule(color: c.hairline),
                _StepControl(
                  icon: Icons.add_rounded,
                  label: widget.incrementLabel,
                  onPressed: widget.enabled ? widget.onIncrement : null,
                  side: _StepSide.end,
                ),
              ],
            ),
          ),
        ),
        _FieldFootnote(helper: widget.helper, errorText: widget.errorText),
        ExcludeSemantics(
          excluding: false,
          child: Semantics(
            label: l.a11yRequiredField,
            child: const SizedBox.shrink(),
          ),
        ),
      ],
    );
  }
}

enum _StepSide { start, end }

/// A hairline between a stepper control and the input, full height.
class _StepperRule extends StatelessWidget {
  const _StepperRule({required this.color});

  final Color color;

  @override
  Widget build(BuildContext context) =>
      SizedBox(width: 1, child: ColoredBox(color: color));
}

/// One end of [AppAmountStepper].
///
/// Square-ish and at least [AppSpace.minTapTarget] wide, so the tap area is
/// the whole end of the control rather than a 24-point glyph. It has no border
/// of its own: the enclosing box draws one, and the rule beside it is what
/// separates the two.
class _StepControl extends StatelessWidget {
  const _StepControl({
    required this.icon,
    required this.label,
    required this.onPressed,
    required this.side,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onPressed;
  final _StepSide side;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final radius = side == _StepSide.start
        ? const BorderRadiusDirectional.horizontal(
            start: Radius.circular(AppRadius.md),
          )
        : const BorderRadiusDirectional.horizontal(
            end: Radius.circular(AppRadius.md),
          );

    return Semantics(
      button: true,
      enabled: onPressed != null,
      label: label,
      onTap: onPressed,
      child: ExcludeSemantics(
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            onTap: onPressed,
            borderRadius: radius.resolve(Directionality.of(context)),
            child: ConstrainedBox(
              constraints: const BoxConstraints(
                minWidth: AppSpace.minTapTarget,
                minHeight: AppSpace.minTapTarget,
              ),
              child: Center(
                widthFactor: 1,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppSpace.md),
                  child: Icon(
                    icon,
                    // The glyph grows with the text it sits beside, but only
                    // so far: the button is already as tall as the input, and
                    // a 35-point minus inside it reads as a banner rather than
                    // a control.
                    size: MediaQuery.textScalerOf(
                      context,
                    ).scale(22).clamp(22.0, 29.0),
                    color: onPressed == null ? c.textTertiary : c.textPrimary,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

/// Progress through a multi-step form.
///
/// Numbered and named, not a bare bar: a sender publishing their first request
/// should be able to see that "Parcel" comes after "Route" and how much is
/// left. Compresses to numbers only when the labels cannot fit.
class AppStepIndicator extends StatelessWidget {
  const AppStepIndicator({
    required this.steps,
    required this.currentIndex,
    this.onStepTapped,
    super.key,
  });

  final List<String> steps;
  final int currentIndex;

  /// Allows going back to a completed step. Forward navigation stays with the
  /// form's own validation.
  final ValueChanged<int>? onStepTapped;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Semantics(
      container: true,
      label: '${currentIndex + 1} / ${steps.length}',
      value: steps[currentIndex.clamp(0, steps.length - 1)],
      child: LayoutBuilder(
        builder: (context, constraints) {
          final showLabels = constraints.maxWidth / steps.length >= 78;
          return Row(
            children: [
              for (var i = 0; i < steps.length; i++)
                Expanded(
                  // Only a completed step can be returned to, so only a
                  // completed step gets an identity of its own. Wrapping the
                  // whole row in `ExcludeSemantics` announced the progress
                  // correctly and threw the back-navigation away with it.
                  child: Semantics(
                    button: i < currentIndex && onStepTapped != null,
                    label: i < currentIndex && onStepTapped != null
                        ? steps[i]
                        : null,
                    onTap: i < currentIndex && onStepTapped != null
                        ? () => onStepTapped!.call(i)
                        : null,
                    child: ExcludeSemantics(
                      child: GestureDetector(
                        onTap: i < currentIndex
                            ? () => onStepTapped?.call(i)
                            : null,
                        behavior: HitTestBehavior.opaque,
                        child: Padding(
                          padding: EdgeInsetsDirectional.only(
                            end: i == steps.length - 1 ? 0 : AppSpace.sm,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Container(
                                height: 3,
                                decoration: BoxDecoration(
                                  color: i <= currentIndex
                                      ? c.brand
                                      : c.hairlineStrong,
                                  borderRadius: AppRadius.rPill,
                                ),
                              ),
                              if (showLabels) ...[
                                const SizedBox(height: AppSpace.sm),
                                Text(
                                  steps[i],
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: text.labelSmall?.copyWith(
                                    color: i == currentIndex
                                        ? c.textPrimary
                                        : c.textTertiary,
                                    fontWeight: i == currentIndex
                                        ? FontWeight.w700
                                        : FontWeight.w500,
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Form section
// ---------------------------------------------------------------------------

/// A titled group of fields, with the section's own server errors surfaced at
/// its head rather than at the top of a long scroll.
class FormSection extends StatelessWidget {
  const FormSection({
    required this.title,
    required this.children,
    this.subtitle,
    this.errors = const [],
    super.key,
  });

  final String title;
  final String? subtitle;
  final List<Widget> children;
  final List<String> errors;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      SectionHeader(title: title, subtitle: subtitle),
      if (errors.isNotEmpty) ...[
        InfoNotice(message: errors.join('\n')),
        const SizedBox(height: AppSpace.md),
      ],
      ...children,
    ],
  );
}
