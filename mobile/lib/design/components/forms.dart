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
import '../typography.dart';
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
  final Widget? suffix;
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
            suffixIcon: suffix,
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
    super.key,
  });

  final String label;
  final TextEditingController controller;
  final String? helper;
  final String? errorText;
  final bool isRequired;
  final bool enabled;
  final ValueChanged<String>? onChanged;

  /// Cents currently in the field, or null if it is not a usable amount.
  static int? centsOf(TextEditingController controller) {
    final value = parseDecimalInput(controller.text);
    if (value == null || value < 0) return null;
    return (value * 100).round();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return AppTextField(
      label: label,
      controller: controller,
      helper: helper,
      errorText: errorText,
      isRequired: isRequired,
      enabled: enabled,
      onChanged: onChanged,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      textInputAction: TextInputAction.done,
      inputFormatters: [
        FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
        LengthLimitingTextInputFormatter(9),
      ],
      prefixIcon: null,
      suffix: Padding(
        padding: const EdgeInsetsDirectional.only(end: AppSpace.lg),
        child: Text(
          '€',
          style: AppTypography.money(context, color: c.textSecondary, size: 17),
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
      label: '${currentIndex + 1} / ${steps.length}',
      value: steps[currentIndex.clamp(0, steps.length - 1)],
      child: ExcludeSemantics(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final showLabels = constraints.maxWidth / steps.length >= 78;
            return Row(
              children: [
                for (var i = 0; i < steps.length; i++)
                  Expanded(
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
              ],
            );
          },
        ),
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
