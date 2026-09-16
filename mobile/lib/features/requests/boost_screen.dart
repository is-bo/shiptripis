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
    final maxCents = state.policy?.maximumBoost.minorUnits ?? 10000;
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    if (cents < 0) return;
    if (cents > maxCents) {
      setState(() {
        _error = l.pricingBelowMinimumError(
          state.policy?.maximumBoost.format(locale) ?? '€100.00',
        );
      });
      return;
    }

    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      await ref.read(boostRepositoryProvider).setBoost(
            requestId: widget.requestId,
            amountEurCents: cents,
          );
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
            final commissionBps = state.policy?.boostCommissionRateBps ?? 2500;
            // Fee on top: ceiling integer cents
            final feeCents = ((currentCents * commissionBps) + 9999) ~/ 10000;
            final totalCents = currentCents + feeCents;

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
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(color: context.colors.textSecondary),
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
                    title: l.boostNotEditable,
                    message: l.boostNotEditable,
                    tone: StatusTone.waiting,
                    icon: Icons.lock_outline_rounded,
                  ),
                  const SizedBox(height: AppSpace.md),
                ],

                // Preset selector
                SectionHeader(title: l.boostSectionTitle),
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
                    final cents = AppAmountField.centsOf(_amountController) ?? 0;
                    setState(() => _chosenCents = cents);
                  },
                ),
                const SizedBox(height: AppSpace.md),

                // Live Breakdown
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        l.depositRemainingBalance,
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.bold,
                            ),
                      ),
                      const SizedBox(height: AppSpace.sm),
                      DetailRow(
                        label: l.pricingTravelerReceives,
                        value: Text(
                          Money.eurCents(currentCents).format(locale),
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ),
                      DetailRow(
                        label: l.pricingPlatformFee,
                        value: Text(
                          Money.eurCents(feeCents).format(locale),
                          style: TextStyle(color: context.colors.textSecondary),
                        ),
                      ),
                      const Divider(),
                      DetailRow(
                        label: l.pricingTotalSenderCost,
                        value: Text(
                          Money.eurCents(totalCents).format(locale),
                          style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                fontWeight: FontWeight.bold,
                                color: context.colors.brand,
                              ),
                        ),
                      ),
                      const SizedBox(height: AppSpace.xs),
                      Text(
                        l.depositFullDepositNotice,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: context.colors.textTertiary,
                            ),
                      ),
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
                                  ev.reason.isEmpty ? l.actionDone : ev.reason,
                                  style: Theme.of(context).textTheme.bodyMedium,
                                ),
                                const SizedBox(height: AppSpace.xxs),
                                Text(
                                  MaterialLocalizations.of(context)
                                      .formatFullDate(ev.createdAt),
                                  style: Theme.of(context)
                                      .textTheme
                                      .bodySmall
                                      ?.copyWith(color: context.colors.textTertiary),
                                ),
                              ],
                            ),
                          ),
                          Text(
                            ev.amount.format(locale),
                            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                  fontWeight: FontWeight.w600,
                                ),
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
