/// Money presentation.
///
/// Three rules this file exists to enforce:
///
/// 1. **Every figure is a server value.** [Money] has no arithmetic, so a
///    breakdown here is a list of amounts the API returned, not a sum computed
///    on the device. A total that the API does not provide does not get shown.
///
/// 2. **A breakdown adds up towards what the sender pays.** The traveller's
///    reward is never presented as a number with commission taken out of it,
///    because it is not — the fee is added on top. `€30 − 25%` is a different,
///    and false, statement about the same deal.
///
/// 3. **A credited deposit is a subtraction, labelled as already paid.** It
///    must never sit in a list of charges where it reads as a second fee.
library;

import 'package:flutter/material.dart';

import '../../core/money/money.dart';
import '../tokens.dart';
import '../typography.dart';
import 'primitives.dart';
import 'status.dart';

/// A single amount, locale-formatted, with tabular figures.
class MoneyText extends StatelessWidget {
  const MoneyText(
    this.amount, {
    this.style,
    this.color,
    this.size = 15,
    this.weight = 650,
    this.semanticPrefix,
    super.key,
  });

  final Money amount;
  final TextStyle? style;
  final Color? color;
  final double size;
  final double weight;

  /// Prepended for screen readers, e.g. "You pay". Without it an amount read
  /// out of context is just a number.
  final String? semanticPrefix;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context);
    final formatted = amount.format(locale);
    return Semantics(
      label: semanticPrefix == null ? formatted : '$semanticPrefix $formatted',
      excludeSemantics: true,
      child: Text(
        formatted,
        style:
            style ??
            AppTypography.money(
              context,
              color: color,
              size: size,
              weight: weight,
            ),
        // Amounts never wrap. A wrapped price is unreadable and a wrapped
        // price in a payment summary is alarming.
        maxLines: 1,
        softWrap: false,
        overflow: TextOverflow.visible,
      ),
    );
  }
}

/// The single figure a screen is about — the amount on a payment screen, the
/// reward on an offer screen. Serif, large, unmistakable.
class MoneyHero extends StatelessWidget {
  const MoneyHero({
    required this.amount,
    required this.label,
    this.caption,
    this.tone,
    super.key,
  });

  final Money amount;
  final String label;
  final String? caption;
  final StatusTone? tone;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final accent = tone == null ? null : StatusStyle.of(context, tone!).accent;

    return Semantics(
      label: '$label ${amount.format(locale)}',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: text.bodyMedium?.copyWith(color: c.textSecondary)),
          const SizedBox(height: AppSpace.xs),
          FittedBox(
            // A very large amount in a narrow column shrinks rather than
            // wrapping or clipping.
            fit: BoxFit.scaleDown,
            alignment: AlignmentDirectional.centerStart,
            child: Text(
              amount.format(locale),
              style: AppTypography.heroMoney(
                context,
                color: accent ?? c.textPrimary,
              ),
              maxLines: 1,
            ),
          ),
          if (caption != null) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              caption!,
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],
        ],
      ),
    );
  }
}

/// One line in a breakdown.
@immutable
class MoneyLine {
  const MoneyLine({
    required this.label,
    required this.amount,
    this.note,
    this.isCredit = false,
    this.isTotal = false,
  });

  /// A line that reduces what is owed — a credited deposit, a refund.
  /// Rendered with an explicit minus sign and in the success tone, so it can
  /// never be mistaken for another charge.
  const MoneyLine.credit({
    required String label,
    required Money amount,
    String? note,
  }) : this(label: label, amount: amount, note: note, isCredit: true);

  const MoneyLine.total({required String label, required Money amount})
    : this(label: label, amount: amount, isTotal: true);

  final String label;
  final Money amount;
  final String? note;
  final bool isCredit;
  final bool isTotal;
}

/// A payment breakdown.
///
/// Composed of server values only. [explainer] carries the sentence that stops
/// the most common misreading of the screen it appears on — for a sender
/// paying a traveller, that the fee is added rather than deducted; for a
/// deposit, that it is credit rather than a charge.
class MoneyBreakdown extends StatelessWidget {
  const MoneyBreakdown({
    required this.lines,
    this.title,
    this.explainer,
    this.explainerTone = StatusTone.neutral,
    super.key,
  });

  final List<MoneyLine> lines;
  final String? title;
  final String? explainer;
  final StatusTone explainerTone;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppInsetGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (title != null) ...[
            Text(title!, style: text.titleSmall),
            const SizedBox(height: AppSpace.md),
          ],
          for (final line in lines) ...[
            if (line.isTotal)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
                child: Divider(height: 1, color: c.hairlineStrong),
              ),
            _Line(line: line),
          ],
          if (explainer != null) ...[
            const SizedBox(height: AppSpace.md),
            _Explainer(text: explainer!, tone: explainerTone),
          ],
        ],
      ),
    );
  }
}

class _Line extends StatelessWidget {
  const _Line({required this.line});

  final MoneyLine line;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final labelStyle = line.isTotal
        ? text.titleMedium
        : text.bodyMedium?.copyWith(color: c.textSecondary);

    final amountColor = line.isCredit
        ? c.success
        : (line.isTotal ? c.textPrimary : c.textPrimary);

    // The minus is part of the rendered string rather than a separate glyph so
    // it stays attached to the amount when the locale mirrors the layout.
    final rendered = line.isCredit
        ? '−${line.amount.format(locale)}'
        : line.amount.format(locale);

    return Padding(
      padding: EdgeInsets.symmetric(
        vertical: line.isTotal ? AppSpace.xs : AppSpace.sm - 2,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            label: '${line.label} ${line.isCredit ? 'minus ' : ''}$rendered',
            excludeSemantics: true,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic,
              children: [
                Expanded(child: Text(line.label, style: labelStyle)),
                const SizedBox(width: AppSpace.lg),
                Text(
                  rendered,
                  style: AppTypography.money(
                    context,
                    color: amountColor,
                    size: line.isTotal ? 19 : 15,
                    weight: line.isTotal ? 700 : 600,
                  ),
                  maxLines: 1,
                  softWrap: false,
                ),
              ],
            ),
          ),
          if (line.note != null) ...[
            const SizedBox(height: AppSpace.xxs),
            Text(
              line.note!,
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],
        ],
      ),
    );
  }
}

class _Explainer extends StatelessWidget {
  const _Explainer({required this.text, required this.tone});

  final String text;
  final StatusTone tone;

  @override
  Widget build(BuildContext context) {
    final style = StatusStyle.of(context, tone);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 1.5),
          child: Icon(
            Icons.info_outline_rounded,
            size: 15,
            color: tone == StatusTone.neutral
                ? context.colors.textTertiary
                : style.accent,
          ),
        ),
        const SizedBox(width: AppSpace.sm),
        Expanded(
          child: Text(
            text,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: context.colors.textSecondary,
            ),
          ),
        ),
      ],
    );
  }
}

/// The Chargily conversion block.
///
/// Keeps the two currencies visually separate so nobody reads the dinar figure
/// as the price of the delivery. The euro amount is the marketplace truth; the
/// dinar amount is what one particular payment rail will charge, at a rate the
/// server froze for this attempt.
class ProviderConversion extends StatelessWidget {
  const ProviderConversion({
    required this.canonical,
    required this.charged,
    required this.canonicalLabel,
    required this.chargedLabel,
    required this.rateLabel,
    required this.footnote,
    super.key,
  });

  /// The EUR amount. Always the larger, calmer of the two figures.
  final Money canonical;

  /// What the provider will actually take, in its own currency.
  final Money charged;

  final String canonicalLabel;
  final String chargedLabel;

  /// Pre-formatted `€1 = X DA`, built from the server's own rate.
  final String rateLabel;

  final String footnote;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppInsetGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Pair(label: canonicalLabel, amount: canonical, emphasis: true),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
            child: Divider(height: 1, color: c.hairline),
          ),
          _Pair(label: chargedLabel, amount: charged, emphasis: false),
          const SizedBox(height: AppSpace.sm),
          Text(
            rateLabel,
            style: text.bodySmall?.copyWith(color: c.textTertiary),
          ),
          const SizedBox(height: AppSpace.md),
          _Explainer(text: footnote, tone: StatusTone.neutral),
        ],
      ),
    );
  }
}

class _Pair extends StatelessWidget {
  const _Pair({
    required this.label,
    required this.amount,
    required this.emphasis,
  });

  final String label;
  final Money amount;
  final bool emphasis;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.baseline,
      textBaseline: TextBaseline.alphabetic,
      children: [
        Expanded(
          child: Text(
            label,
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: c.textSecondary),
          ),
        ),
        const SizedBox(width: AppSpace.lg),
        MoneyText(
          amount,
          semanticPrefix: label,
          size: emphasis ? 22 : 18,
          weight: emphasis ? 700 : 650,
          color: emphasis ? c.textPrimary : c.textSecondary,
        ),
      ],
    );
  }
}
