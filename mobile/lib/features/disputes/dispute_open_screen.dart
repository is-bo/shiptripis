/// Open a dispute.
///
/// A dispute freezes the traveller's payout. That is the single most important
/// thing a person opening one should understand before they tap, so it is
/// stated on the screen rather than buried in terms — both because it is fair
/// to the traveller and because it stops the feature being used as a nudge.
///
/// The window is server-owned: from pickup confirmation until the protection
/// window closes. Both refusals carry their own code and their own next step,
/// and neither is a generic failure.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/deal.dart';
import '../../domain/dispute.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';

class DisputeOpenScreen extends ConsumerStatefulWidget {
  const DisputeOpenScreen({required this.dealId, super.key});

  final int dealId;

  @override
  ConsumerState<DisputeOpenScreen> createState() => _DisputeOpenScreenState();
}

class _DisputeOpenScreenState extends ConsumerState<DisputeOpenScreen> {
  final _reason = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  DisputeCategory? _category;
  bool _busy = false;
  bool _categoryTouched = false;

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<void> _pickCategory() async {
    final chosen = await showAppSheet<DisputeCategory>(
      context,
      builder: (sheetContext) => AppChoiceSheet<DisputeCategory>(
        title: L.of(sheetContext).disputeCategory,
        selected: _category,
        options: [
          for (final category in DisputeCategory.selectable)
            AppSheetOption(
              value: category,
              label: disputeCategoryLabel(sheetContext, category),
            ),
        ],
      ),
    );
    if (chosen != null) setState(() => _category = chosen);
  }

  Future<void> _submit() async {
    setState(() => _categoryTouched = true);
    final formOk = _formKey.currentState?.validate() ?? false;
    if (!formOk || _category == null) return;

    setState(() => _busy = true);
    final l = L.of(context);

    try {
      final dispute = await ref
          .read(disputeRepositoryProvider)
          .open(
            dealId: widget.dealId,
            category: _category!,
            reasonText: _reason.text.trim(),
          );
      if (!mounted) return;
      refreshVolatileState(ref);
      AppSnack.success(context, l.disputeOpened);
      context
        ..pop()
        ..openDispute(dispute.id);
    } on ApiException catch (error) {
      if (!mounted) return;

      // An existing dispute is not a failure — the server hands the same row
      // back. Anything that carries a `dispute_id` is somewhere to go.
      final existingId = error.intExtra('dispute_id');
      if (existingId != null) {
        AppSnack.info(context, l.disputeExistingOpenedBody);
        context
          ..pop()
          ..openDispute(existingId);
        return;
      }

      AppSnack.failure(
        context,
        error,
        fallback: switch (error.code.raw) {
          'dispute_not_available' => l.disputeNotAvailableBody,
          'dispute_window_closed' => l.disputeWindowClosedBody,
          'dispute_already_resolved' => l.disputeAlreadyResolvedBody,
          _ => null,
        },
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final validators = Validators.of(context);
    final deal = ref.watch(dealDetailProvider(widget.dealId));

    return DismissKeyboardOnTap(
      child: AppScaffold(
        topBar: AppTopBar(title: l.disputeOpenTitle, showBack: true),
        body: AsyncView<Deal>(
          value: deal,
          onRetry: () => ref.invalidate(dealDetailProvider(widget.dealId)),
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpace.gutter),
            child: SkeletonDetail(),
          ),
          data: (data) {
            // The server decides whether a new dispute may be opened: it owns
            // the party check, the window and the prior-dispute rule together.
            // Re-deriving any of that here was wrong in both directions — a
            // *resolved* dispute passed the old `isActive` check, so the user
            // wrote a paragraph and only then learned it could not be filed,
            // and a client clock disagreed with the server about the deadline.
            if (!data.availableActions.contains('open_dispute')) {
              final existing = data.dispute;
              if (existing != null) {
                return AppEmptyState(
                  title: disputeStatusCopy(context, existing.status).label,
                  body: l.disputeExistingOpenedBody,
                  icon: Icons.gavel_rounded,
                  actionLabel: l.disputeViewAction,
                  onAction: () => context.openDispute(existing.id),
                );
              }
              if (data.pickupConfirmedAt == null) {
                return AppEmptyState(
                  title: l.disputeNotAvailableTitle,
                  body: l.disputeNotAvailableBody,
                  icon: Icons.schedule_rounded,
                );
              }
              return AppEmptyState(
                title: l.disputeWindowClosedTitle,
                body: l.disputeWindowClosedBody,
                icon: Icons.lock_clock_rounded,
                actionLabel: l.actionContactSupport,
              );
            }

            // Informational only: the deadline is shown, never used to decide
            // whether the form may be filed.
            final endsAt = data.protectionEndsAt;

            return Form(
              key: _formKey,
              child: ListView(
                padding: AppScrollPadding.pageWithFooter(context),
                children: [
                  InfoNotice(
                    message: l.disputeOpenExplainer,
                    icon: Icons.info_outline_rounded,
                  ),
                  const SizedBox(height: AppSpace.md),

                  // Said plainly, before the form, because it is a real
                  // consequence for the other person.
                  InfoNotice(
                    title: l.disputeFreezesPayoutTitle,
                    message: l.disputeFreezesPayoutBody,
                    tone: StatusTone.waiting,
                    icon: Icons.ac_unit_rounded,
                  ),

                  if (endsAt != null) ...[
                    const SizedBox(height: AppSpace.md),
                    Text(
                      '${l.disputeProtectionEndsLabel}: '
                      '${LocaleFormats.dateTime(locale, endsAt)}',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: context.colors.textTertiary,
                      ),
                    ),
                  ],

                  const SizedBox(height: AppSpace.xl),
                  AppSelectField(
                    label: l.disputeCategory,
                    placeholder: l.actionSelect,
                    isRequired: true,
                    value: _category == null
                        ? null
                        : disputeCategoryLabel(context, _category!),
                    errorText: _categoryTouched && _category == null
                        ? l.validationSelectOne
                        : null,
                    icon: Icons.report_outlined,
                    onTap: _pickCategory,
                  ),

                  AppTextField(
                    label: l.disputeDescription,
                    controller: _reason,
                    hint: l.disputeDescriptionHint,
                    isRequired: true,
                    maxLines: 6,
                    minLines: 4,
                    maxLength: 2000,
                    validator: validators.required,
                  ),
                ],
              ),
            );
          },
        ),
        footer: deal.hasValue
            ? AppButton(
                label: l.disputeSubmit,
                isLoading: _busy,
                onPressed: _submit,
              )
            : null,
      ),
    );
  }
}
