/// "Your price" on the journey page, and the sheet that changes it.
///
/// The route can be locked by a pending offer or a deal, but the price never
/// is: it has its own endpoint, so a traveller can change it for as long as
/// the journey can still be offered on. A change affects only offers created
/// afterwards, and the sheet says so.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/money/money.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/tokens.dart';
import '../../domain/journey.dart';
import '../../l10n/app_localizations.dart';
import 'journey_price.dart';

class JourneyPriceCard extends ConsumerWidget {
  const JourneyPriceCard({required this.journey, super.key});

  final Journey journey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final policy = ref.watch(travelerPricingPolicyProvider).value;
    final price = journey.price;
    final canChange = policy?.enabled == true && !journey.status.isFinished;
    // Nothing to show and nothing to do: no card rather than an empty one.
    if (price == null && !canChange) return const SizedBox.shrink();

    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(child: SectionHeader(title: l.journeyPriceTitle)),
            if (canChange)
              AppButton(
                label: price == null ? l.journeyPriceSet : l.journeyPriceChange,
                icon: Icons.edit_outlined,
                variant: AppButtonVariant.tertiary,
                expand: false,
                onPressed: () => _open(context, ref, policy!),
              ),
          ],
        ),
        AppInsetGroup(
          child: price == null
              ? Text(
                  l.journeyPriceNone,
                  style: text.bodyMedium?.copyWith(color: c.textSecondary),
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      l.journeyPricePerKgValue(
                        Money.eurCents(price.perKgEurCents).format(locale),
                      ),
                      style: text.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: AppSpace.xxs),
                    Text(
                      l.journeyPriceMinimumValue(
                        Money.eurCents(price.minimumEurCents).format(locale),
                      ),
                      style: text.bodyMedium?.copyWith(color: c.textSecondary),
                    ),
                    const SizedBox(height: AppSpace.sm),
                    Text(
                      l.journeyPriceNote,
                      style: text.bodySmall?.copyWith(color: c.textTertiary),
                    ),
                  ],
                ),
        ),
      ],
    );
  }

  Future<void> _open(
    BuildContext context,
    WidgetRef ref,
    TravelerPricingPolicy policy,
  ) async {
    final saved = await showAppSheet<String>(
      context,
      builder: (_) => _PriceSheet(journey: journey, policy: policy),
    );
    if (saved == null || !context.mounted) return;
    ref.invalidate(journeyDetailProvider(journey.id));
    refreshVolatileState(ref);
    AppSnack.success(context, saved);
  }
}

class _PriceSheet extends ConsumerStatefulWidget {
  const _PriceSheet({required this.journey, required this.policy});

  final Journey journey;
  final TravelerPricingPolicy policy;

  @override
  ConsumerState<_PriceSheet> createState() => _PriceSheetState();
}

class _PriceSheetState extends ConsumerState<_PriceSheet> {
  late final _draft = JourneyPriceDraft(widget.journey.price);
  bool _busy = false;
  bool _showErrors = false;

  @override
  void dispose() {
    _draft.dispose();
    super.dispose();
  }

  /// Saving empty fields is removing the price, which is what the second
  /// button is for; so "Save price" needs both values.
  Future<void> _save() async {
    if (_draft.isEmpty || !_draft.isValid(widget.policy)) {
      setState(() => _showErrors = true);
      return;
    }
    await _send(_draft.price, L.of(context).journeyPriceSaved);
  }

  Future<void> _clear() => _send(null, L.of(context).journeyPriceCleared);

  Future<void> _send(JourneyPrice? price, String success) async {
    setState(() => _busy = true);
    try {
      await ref
          .read(journeyRepositoryProvider)
          .setPrice(widget.journey.id, price);
      if (!mounted) return;
      Navigator.of(context).pop(success);
    } on ApiException catch (error) {
      if (!mounted) return;
      if (!_draft.showRefusal(error)) {
        final l = L.of(context);
        AppSnack.failure(
          context,
          error,
          fallback: switch (error.code.raw) {
            'traveler_pricing_disabled' => l.journeyPriceDisabled,
            'journey_price_not_editable' => l.journeyPriceNotEditable,
            'journey_not_owned' => l.journeyErrorNotOwned,
            _ => null,
          },
        );
        // The world moved: switched off, or the journey finished.
        if (error.isStale ||
            error.code.raw == 'traveler_pricing_disabled' ||
            error.code.raw == 'journey_price_not_editable') {
          Navigator.of(context).pop();
          ref.invalidate(journeyDetailProvider(widget.journey.id));
        }
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final hasPrice = widget.journey.price != null;

    return AppSheet(
      title: l.journeyPriceTitle,
      footer: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          AppButton(
            label: l.journeyPriceSave,
            isLoading: _busy,
            onPressed: _busy ? null : _save,
          ),
          if (hasPrice) ...[
            const SizedBox(height: AppSpace.sm),
            AppButton(
              label: l.journeyPriceRemove,
              variant: AppButtonVariant.tertiary,
              onPressed: _busy ? null : _clear,
            ),
          ],
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          JourneyPriceFields(
            draft: _draft,
            policy: widget.policy,
            enabled: !_busy,
            showErrors: _showErrors,
          ),
          const SizedBox(height: AppSpace.md),
          Text(
            l.journeyPriceAppliesToNew,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: context.colors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}
