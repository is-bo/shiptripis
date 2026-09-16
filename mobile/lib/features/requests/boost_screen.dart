/// J2 Additive Boost Screen.
///
/// Under Phase J2, a Boost is an extra reward added to the request to attract
/// travelers. It goes 100% to the traveler, with ShipTrip's platform fee added
/// on top. It does not create an immediate payment order; it is settled as part
/// of the Deal balance.
///
/// Editability is strictly server-authoritative (`can_edit`).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/money/money.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/boost.dart';
import '../../l10n/app_localizations.dart';

final _boostStateProvider = FutureProvider.autoDispose.family<BoostState, int>((
  ref,
  requestId,
) async {
  final repo = ref.watch(boostRepositoryProvider);
  return repo.forRequest(requestId);
});

class BoostScreen extends ConsumerStatefulWidget {
  const BoostScreen({required this.requestId, super.key});

  final int requestId;

  @override
  ConsumerState<BoostScreen> createState() => _BoostScreenState();
}

class _BoostScreenState extends ConsumerState<BoostScreen> {
  final _amountController = TextEditingController();
  int? _chosenCents;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _amountController.dispose();
    super.dispose();
  }

  void _syncInitial(BoostState state) {
    if (_chosenCents == null) {
      _chosenCents = state.boostEur.minorUnits;
      if (_chosenCents! > 0) {
        _amountController.text = (_chosenCents! / 100.0).toStringAsFixed(2);
      }
    }
  }

  Future<void> _saveBoost(BoostState state) async {
    final cents = _chosenCents ?? 0;
    final maximum = state.policy?.maximumBoost;
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    if (cents < 0) return;
    // Only refuse locally against a bound the server actually published. With
    // no policy there is no ceiling to quote, and inventing one - the old code
    // named a euro amount in every language - is worse than letting the server
    // answer.
    if (maximum != null && cents > maximum.minorUnits) {
      setState(() {
        _error = l.boostAmountAboveMaximum(maximum.format(locale));
      });
      return;
    }

    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      await ref
          .read(boostRepositoryProvider)
          .setBoost(requestId: widget.requestId, amountEurCents: cents);
      if (!mounted) return;
      ref.invalidate(_boostStateProvider(widget.requestId));
      refreshVolatileState(ref);
      AppSnack.success(context, l.actionDone);
    } on ApiException catch (e) {
      if (!mounted) return;
      AppSnack.failure(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final boostState = ref.watch(_boostStateProvider(widget.requestId));

    return AppScaffold(
      topBar: AppTopBar(title: l.boostSectionTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(_boostStateProvider(widget.requestId));
        },
        child: AsyncView<BoostState>(
          value: boostState,
          onRetry: () => ref.invalidate(_boostStateProvider(widget.requestId)),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (state) {
            _syncInitial(state);
            final currentCents = _chosenCents ?? state.boostEur.minorUnits;
            final canEdit = state.canEdit;
            // Money is the server's. `economics` is the authoritative split for
            // the Boost that is actually saved, so it is used verbatim whenever
            // the sender has not moved the amount. While they are still
            // choosing, the fee is projected from the rate the server
            // published - never from a rate invented here - and the card says
            // out loud that it is an estimate until it is saved.
            final economics = state.economics;
            final commissionBps = state.policy?.boostCommissionRateBps;
            final isSaved =
                currentCents == state.boostEur.minorUnits && economics != null;

            final int? feeCents;
            final int? totalCents;
            if (isSaved) {
              feeCents = economics.platformFee.minorUnits;
              totalCents = economics.senderCost.minorUnits;
            } else if (commissionBps != null) {
              final projected =
                  ((currentCents * commissionBps) + 9999) ~/ 10000;
              feeCents = projected;
              totalCents = currentCents + projected;
            } else {
              feeCents = null;
              totalCents = null;
            }

            return ListView(
              padding: AppScrollPadding.pageWithFooter(context),
              children: [
                // Explainer Banner
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        l.boostSectionTitle,
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: AppSpace.xs),
                      Text(
                        l.boostExplainer,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: context.colors.textSecondary,
                        ),
                      ),
                      const SizedBox(height: AppSpace.sm),
                      Row(
                        children: [
                          Icon(
                            Icons.verified_outlined,
                            size: 16,
                            color: context.colors.success,
                          ),
                          const SizedBox(width: AppSpace.xs),
                          Expanded(
                            child: Text(
                              l.boostCompatibilityNote,
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(
                                    color: context.colors.textSecondary,
                                  ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpace.md),

                if (!canEdit) ...[
                  InfoNotice(
                    message: l.boostNotEditable,
                    tone: StatusTone.waiting,
                    icon: Icons.lock_outline_rounded,
                  ),
                  const SizedBox(height: AppSpace.md),
                ],

                // Preset selector. No third "Boost this request" header here:
                // the top bar and the explainer card have already said it.
                const SizedBox(height: AppSpace.sm),
                Wrap(
                  spacing: AppSpace.sm,
                  children: [
                    ChoiceChip(
                      label: Text(l.boostPresetNone),
                      selected: currentCents == 0,
                      onSelected: canEdit
                          ? (selected) {
                              if (selected) {
                                setState(() {
                                  _chosenCents = 0;
                                  _amountController.clear();
                                });
                              }
                            }
                          : null,
                    ),
                    ChoiceChip(
                      label: Text(l.boostPreset5),
                      selected: currentCents == 500,
                      onSelected: canEdit
                          ? (selected) {
                              if (selected) {
                                setState(() {
                                  _chosenCents = 500;
                                  _amountController.text = '5.00';
                                });
                              }
                            }
                          : null,
                    ),
                    ChoiceChip(
                      label: Text(l.boostPreset10),
                      selected: currentCents == 1000,
                      onSelected: canEdit
                          ? (selected) {
                              if (selected) {
                                setState(() {
                                  _chosenCents = 1000;
                                  _amountController.text = '10.00';
                                });
                              }
                            }
                          : null,
                    ),
                  ],
                ),
                const SizedBox(height: AppSpace.md),

                AppAmountField(
                  label: l.boostCustomAmountLabel,
                  controller: _amountController,
                  enabled: canEdit,
                  onChanged: (text) {
                    final cents =
                        AppAmountField.centsOf(_amountController) ?? 0;
                    setState(() => _chosenCents = cents);
                  },
                ),
                const SizedBox(height: AppSpace.md),

                // What the Boost costs. Every label here names the Boost and
                // only the Boost: these figures are not the delivery reward,
                // not the sender's total for the delivery, and not a balance.
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        l.boostBreakdownTitle,
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: AppSpace.sm),
                      DetailRow(
                        label: l.boostTravelerBonusLabel,
                        value: Text(
                          Money.eurCents(currentCents).format(locale),
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ),
                      if (feeCents != null)
                        DetailRow(
                          label: l.moneyBoostFee,
                          value: Text(
                            Money.eurCents(feeCents).format(locale),
                            style: TextStyle(
                              color: context.colors.textSecondary,
                            ),
                          ),
                        ),
                      if (totalCents != null) ...[
                        const Divider(),
                        DetailRow(
                          label: l.boostYourCostLabel,
                          value: Text(
                            Money.eurCents(totalCents).format(locale),
                            style: Theme.of(context).textTheme.titleSmall
                                ?.copyWith(
                                  fontWeight: FontWeight.bold,
                                  color: context.colors.brand,
                                ),
                          ),
                        ),
                      ],
                      const SizedBox(height: AppSpace.sm),
                      Text(
                        l.boostAddsOnTop,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: context.colors.textSecondary,
                        ),
                      ),
                      if (!isSaved && totalCents != null) ...[
                        const SizedBox(height: AppSpace.xxs),
                        Text(
                          l.boostEstimateNotice,
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(color: context.colors.textTertiary),
                        ),
                      ],
                    ],
                  ),
                ),

                if (_error != null) ...[
                  const SizedBox(height: AppSpace.md),
                  InfoNotice(
                    message: _error!,
                    tone: StatusTone.bad,
                    icon: Icons.error_outline_rounded,
                  ),
                ],

                if (state.history.isNotEmpty) ...[
                  const SizedBox(height: AppSpace.xl),
                  SectionHeader(title: l.boostHistoryTitle),
                  for (final ev in state.history) ...[
                    AppCard(
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  _historyReason(l, ev.reason),
                                  style: Theme.of(context).textTheme.bodyMedium,
                                ),
                                const SizedBox(height: AppSpace.xxs),
                                Text(
                                  MaterialLocalizations.of(
                                    context,
                                  ).formatFullDate(ev.createdAt),
                                  style: Theme.of(context).textTheme.bodySmall
                                      ?.copyWith(
                                        color: context.colors.textTertiary,
                                      ),
                                ),
                              ],
                            ),
                          ),
                          Text(
                            ev.amount.format(locale),
                            style: Theme.of(context).textTheme.titleSmall
                                ?.copyWith(fontWeight: FontWeight.w600),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: AppSpace.xs),
                  ],
                ],
              ],
            );
          },
        ),
      ),
      footer: boostState.hasValue && (boostState.value?.canEdit ?? false)
          ? Builder(
              builder: (context) {
                final state = boostState.value!;
                final isZero = (_chosenCents ?? 0) == 0;
                return AppButton(
                  label: isZero ? l.boostRemoveAction : l.actionSave,
                  isLoading: _busy,
                  onPressed: () => _saveBoost(state),
                );
              },
            )
          : null,
    );
  }
}

/// A `BoostIntentHistoryEvent.reason` as a sentence.
///
/// The wire carries `sender_increased`, `frozen_into_deal` and friends, and the
/// screen used to print those verbatim. An unrecognised future code degrades to
/// "Boost updated" rather than leaking the enum onto a sender's screen.
String _historyReason(L l, String reason) => switch (reason) {
  'sender_set' => l.boostHistoryReasonSenderSet,
  'sender_increased' => l.boostHistoryReasonSenderIncreased,
  'sender_decreased' => l.boostHistoryReasonSenderDecreased,
  'sender_removed' => l.boostHistoryReasonSenderRemoved,
  'frozen_into_deal' => l.boostHistoryReasonFrozen,
  'consumed_by_funding' => l.boostHistoryReasonConsumed,
  'released_with_reservation' => l.boostHistoryReasonReleased,
  'request_closed' => l.boostHistoryReasonRequestClosed,
  _ => l.boostHistoryReasonOther,
};
