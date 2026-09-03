/// Building a journey.
///
/// A journey is a *chain*, and a chain is the part users get wrong. The first
/// version of this screen asked people to assemble it out of legs, and
/// real-device QA found what that costs: a traveller with Jijel → Paris who
/// wanted Jijel → Algiers → Paris had to delete Paris, add Algiers, and add
/// Paris again, because "add a leg" could only append.
///
/// So the noun changed. This screen asks for **stops** — where you start,
/// where you end, and anywhere you stop on the way — and derives the legs
/// between them. The chain is joined by construction rather than by
/// validation: segment *k* runs from stop *k* to stop *k+1*, so leg positions
/// are contiguous, the first leg begins where the journey does, and each leg
/// starts where the last one ended, without anyone having to check.
///
/// See [JourneyRouteDraft] for the model and [JourneyRouteEditor] for the
/// interaction. Both are shared with the edit screen, on purpose: a second,
/// subtly different route form is how the two drift apart.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';
import 'journey_route_draft.dart';
import 'journey_route_editor.dart';

class JourneyCreateScreen extends ConsumerStatefulWidget {
  const JourneyCreateScreen({super.key});

  @override
  ConsumerState<JourneyCreateScreen> createState() =>
      _JourneyCreateScreenState();
}

class _JourneyCreateScreenState extends ConsumerState<JourneyCreateScreen> {
  final _notes = TextEditingController();
  final _draft = JourneyRouteDraft();

  bool _busy = false;

  /// Errors stay hidden until the first submit. A form that turns red before
  /// it has been filled in teaches people to ignore red.
  bool _showErrors = false;

  FieldErrorMap _fieldErrors = const FieldErrorMap.empty();

  static const _claimedFields = {
    'start_place_id',
    'destination_place_id',
    'legs',
    'notes',
  };

  @override
  void dispose() {
    _notes.dispose();
    _draft.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final l = L.of(context);
    if (!_draft.isValid(routeCopyOf(context))) {
      setState(() => _showErrors = true);
      return;
    }

    setState(() {
      _busy = true;
      _showErrors = true;
      _fieldErrors = const FieldErrorMap.empty();
    });

    try {
      final journey = await ref
          .read(journeyRepositoryProvider)
          .create(
            startPlaceId: _draft.startPlaceId,
            destinationPlaceId: _draft.destinationPlaceId,
            legs: _draft.toLegDrafts(),
            notes: _notes.text.trim(),
          );

      if (!mounted) return;
      refreshVolatileState(ref);
      AppSnack.success(context, l.journeyCreatedDraft);
      // A new journey is a draft, never live. Replacing rather than pushing
      // means Back from the detail screen returns where the user started, not
      // to a form whose work is already saved.
      context.pushReplacementNamed(
        Routes.journeyDetail,
        pathParameters: {'id': '${journey.id}'},
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _fieldErrors = FieldErrorMap.from(error));
      AppSnack.failure(
        context,
        error,
        fallback: journeyRouteFailure(context, error),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final unclaimed = _fieldErrors.unclaimed(_claimedFields);

    return AppScaffold(
      topBar: AppTopBar(title: l.journeyCreateTitle, showBack: true),
      body: DismissKeyboardOnTap(
        child: ListView(
          padding: AppScrollPadding.pageWithFooter(context),
          children: [
            if (unclaimed.isNotEmpty) ...[
              InfoNotice(
                message: unclaimed.join('\n'),
                tone: StatusTone.bad,
                icon: Icons.error_outline_rounded,
              ),
              const SizedBox(height: AppSpace.xl),
            ],

            SectionHeader(title: l.routeStopsTitle, subtitle: l.routeStopsHelp),
            JourneyRouteEditor(
              draft: _draft,
              enabled: !_busy,
              showErrors: _showErrors,
            ),

            const SizedBox(height: AppSpace.xl),
            AppTextField(
              label: l.journeyNotesLabel,
              controller: _notes,
              hint: l.journeyNotesHint,
              enabled: !_busy,
              maxLines: 3,
              minLines: 2,
              maxLength: 500,
              textCapitalization: TextCapitalization.sentences,
              errorText: _fieldErrors['notes'],
            ),
          ],
        ),
      ),
      footer: AppButton(
        label: l.journeySaveDraft,
        isLoading: _busy,
        onPressed: _busy ? null : _submit,
      ),
    );
  }
}

/// Copy for the route refusals both the create and edit screens can hit.
///
/// Branching on the machine code, never on the server's English.
String? journeyRouteFailure(BuildContext context, ApiException error) {
  final l = L.of(context);
  return switch (error.code.raw) {
    'journey_leg_mode_unavailable' => l.routeErrorModeUnavailable,
    'journey_legs_disconnected' => l.journeyErrorLegsDisconnected,
    'journey_endpoints_mismatch' => l.journeyErrorEndpointsMismatch,
    'journey_leg_endpoints_invalid' => l.journeyErrorLegEndpoints,
    'journey_leg_time_order_invalid' => l.journeyErrorLegTimeOrder,
    'journey_leg_time_invalid' => l.journeyErrorLegTime,
    'journey_not_editable' => l.journeyEditBlockedStatus,
    'journey_has_dependent_state' => l.journeyEditBlockedDependent,
    'journey_not_owned' => l.journeyErrorNotOwned,
    'journey_leg_not_found' => l.journeyEditStaleRoute,
    _ => null,
  };
}
