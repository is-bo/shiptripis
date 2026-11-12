/// A traveller's price on a journey: "Price per kg" and "Minimum per parcel".
///
/// The rule lives on the server (`apps/trips/pricing.py`): both or neither,
/// each at least one cent and at most the ceiling staff set. This file mirrors
/// it only to say so before a round trip. The app does no price arithmetic and
/// shows no worked example: what a parcel would cost is the server's listed
/// price on Find Travelers.
///
/// One draft and one set of fields are used by the create screen, the edit
/// screen and the journey page's own price sheet, so the three cannot drift.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/money/money.dart';
import '../../design/components/forms.dart';
import '../../design/components/primitives.dart';
import '../../design/tokens.dart';
import '../../domain/journey.dart';
import '../../l10n/app_localizations.dart';
import '../requests/checkout_section.dart' show amountFieldText;

enum PriceIssueKind {
  incomplete,
  invalid,
  precision,
  notPositive,
  aboveMaximum,
}

class PriceIssue {
  const PriceIssue(this.kind, {this.maximumEurCents});

  final PriceIssueKind kind;

  /// The ceiling, for [PriceIssueKind.aboveMaximum].
  final int? maximumEurCents;
}

/// The two amount fields, plus what is wrong with them.
class JourneyPriceDraft extends ChangeNotifier {
  JourneyPriceDraft([JourneyPrice? initial]) {
    if (initial != null) {
      perKg.text = amountFieldText(Money.eurCents(initial.perKgEurCents));
      minimum.text = amountFieldText(Money.eurCents(initial.minimumEurCents));
    }
    perKg.addListener(_edited);
    minimum.addListener(_edited);
  }

  final perKg = TextEditingController();
  final minimum = TextEditingController();

  PriceIssue? _perKgRefusal;
  PriceIssue? _minimumRefusal;

  /// The server refused what was sent. Shown on the field it names until the
  /// traveller changes a value: a verdict on a number that no longer exists
  /// should not keep the field red.
  PriceIssue? get perKgRefusal => _perKgRefusal;
  PriceIssue? get minimumRefusal => _minimumRefusal;

  bool get isEmpty => perKg.text.trim().isEmpty && minimum.text.trim().isEmpty;

  /// The price to send: null for "no price" and for anything not yet valid.
  JourneyPrice? get price {
    final perKgCents = AppAmountField.centsOf(perKg);
    final minimumCents = AppAmountField.centsOf(minimum);
    if (perKgCents == null || minimumCents == null) return null;
    return JourneyPrice(
      perKgEurCents: perKgCents,
      minimumEurCents: minimumCents,
    );
  }

  /// What is wrong with each field, judged against the policy when it is
  /// known. Both null means the draft can be sent as it is.
  ({PriceIssue? perKg, PriceIssue? minimum}) check(
    TravelerPricingPolicy? policy,
  ) {
    if (isEmpty) return (perKg: null, minimum: null);
    return (
      perKg: _checkField(perKg, other: minimum, max: policy?.maxPerKgEurCents),
      minimum: _checkField(
        minimum,
        other: perKg,
        max: policy?.maxMinimumEurCents,
      ),
    );
  }

  bool isValid(TravelerPricingPolicy? policy) {
    final result = check(policy);
    return result.perKg == null && result.minimum == null;
  }

  static PriceIssue? _checkField(
    TextEditingController field, {
    required TextEditingController other,
    required int? max,
  }) {
    if (field.text.trim().isEmpty) {
      return const PriceIssue(PriceIssueKind.incomplete);
    }
    final cents = AppAmountField.centsOf(field);
    if (cents == null) {
      return AppAmountField.hasExcessPrecision(field)
          ? const PriceIssue(PriceIssueKind.precision)
          : const PriceIssue(PriceIssueKind.invalid);
    }
    if (cents <= 0) return const PriceIssue(PriceIssueKind.notPositive);
    if (max != null && cents > max) {
      return PriceIssue(PriceIssueKind.aboveMaximum, maximumEurCents: max);
    }
    return null;
  }

  /// Reads a refusal of the price out of a route write or of the price
  /// endpoint. Returns true when the error was about the price, so the caller
  /// can skip its generic message.
  bool showRefusal(ApiException error) {
    switch (error.code.raw) {
      case 'journey_price_invalid':
        switch (error.stringExtra('reason')) {
          case 'price_per_kg_above_maximum':
            _perKgRefusal = PriceIssue(
              PriceIssueKind.aboveMaximum,
              maximumEurCents: error.intExtra('max_price_per_kg_eur_cents'),
            );
          case 'min_price_above_maximum':
            _minimumRefusal = PriceIssue(
              PriceIssueKind.aboveMaximum,
              maximumEurCents: error.intExtra('max_min_price_eur_cents'),
            );
          default:
            _perKgRefusal = const PriceIssue(PriceIssueKind.incomplete);
            _minimumRefusal = const PriceIssue(PriceIssueKind.incomplete);
        }
      default:
        return false;
    }
    notifyListeners();
    return true;
  }

  void _edited() {
    _perKgRefusal = null;
    _minimumRefusal = null;
    notifyListeners();
  }

  @override
  void dispose() {
    perKg.dispose();
    minimum.dispose();
    super.dispose();
  }
}

/// The words for one issue, in the traveller's language.
String? priceIssueText(BuildContext context, PriceIssue? issue) {
  if (issue == null) return null;
  final l = L.of(context);
  return switch (issue.kind) {
    PriceIssueKind.incomplete => l.journeyPriceErrorBoth,
    PriceIssueKind.invalid => l.validationNumberInvalid,
    PriceIssueKind.precision => l.validationMoneyPrecision,
    PriceIssueKind.notPositive => l.validationMustBePositive,
    PriceIssueKind.aboveMaximum =>
      issue.maximumEurCents == null
          ? l.journeyPriceErrorTooHigh
          : l.journeyPriceErrorMaximum(
              Money.eurCents(
                issue.maximumEurCents!,
              ).format(Localizations.localeOf(context)),
            ),
  };
}

/// The two fields and the line that says what senders will see.
class JourneyPriceFields extends StatelessWidget {
  const JourneyPriceFields({
    required this.draft,
    required this.policy,
    required this.enabled,
    required this.showErrors,
    super.key,
  });

  final JourneyPriceDraft draft;
  final TravelerPricingPolicy? policy;
  final bool enabled;

  /// Local errors stay hidden until the first submit; a server refusal shows
  /// at once.
  final bool showErrors;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    return ListenableBuilder(
      listenable: draft,
      builder: (context, _) {
        final local = draft.check(policy);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l.journeyPriceNote,
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
            const SizedBox(height: AppSpace.md),
            AppAmountField(
              label: l.journeyPricePerKgLabel,
              controller: draft.perKg,
              isRequired: false,
              enabled: enabled,
              errorText: priceIssueText(
                context,
                draft.perKgRefusal ?? (showErrors ? local.perKg : null),
              ),
            ),
            const SizedBox(height: AppSpace.md),
            AppAmountField(
              label: l.journeyPriceMinimumLabel,
              controller: draft.minimum,
              isRequired: false,
              enabled: enabled,
              errorText: priceIssueText(
                context,
                draft.minimumRefusal ?? (showErrors ? local.minimum : null),
              ),
            ),
          ],
        );
      },
    );
  }
}

/// "Your price" on the create and edit screens. Absent while the server says
/// travellers may not set a price (or has not said yet): a held price is
/// still sent back unchanged by the screen, because a route edit that left it
/// out would clear it.
class JourneyPriceSection extends ConsumerWidget {
  const JourneyPriceSection({
    required this.draft,
    required this.enabled,
    required this.showErrors,
    super.key,
  });

  final JourneyPriceDraft draft;
  final bool enabled;
  final bool showErrors;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final policy = ref.watch(travelerPricingPolicyProvider).value;
    if (policy == null || !policy.enabled) return const SizedBox.shrink();
    final l = L.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(
          title: l.journeyPriceTitle,
          subtitle: l.journeyPriceOptional,
        ),
        JourneyPriceFields(
          draft: draft,
          policy: policy,
          enabled: enabled,
          showErrors: showErrors,
        ),
      ],
    );
  }
}
