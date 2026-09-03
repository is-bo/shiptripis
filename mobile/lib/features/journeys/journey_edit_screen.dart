/// Editing a journey that already exists.
///
/// The owner's real-device QA found a journey that, once configured, could not
/// be changed at all — the only way to fix a wrong stop was to cancel and
/// start again. This screen is the answer, and it deliberately reuses the
/// create screen's [JourneyRouteEditor] rather than growing a second route
/// form: two forms for one route is how they drift apart.
///
/// ## What it will not do
///
/// The server decides whether an edit is allowed, and this screen asks rather
/// than guesses — a draft can still be uneditable because a sender is already
/// proposing against it. When the answer is no, the screen *says why*. Hiding
/// the button would leave a traveller looking for an affordance that is
/// absent for a reason nobody told them.
///
/// ## The consequence it refuses to hide
///
/// Changing a flight leg's airports, number or times means an approved
/// boarding pass no longer proves that flight, and the server sends it back
/// for review. That moves when the journey can go live, so the confirmation
/// says so before the edit is sent and the result reports what actually
/// happened.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/journey.dart';
import '../../l10n/app_localizations.dart';
import 'journey_create_screen.dart' show journeyRouteFailure;
import 'journey_route_draft.dart';
import 'journey_route_editor.dart';

class JourneyEditScreen extends ConsumerStatefulWidget {
  const JourneyEditScreen({required this.journeyId, super.key});

  final int journeyId;

  @override
  ConsumerState<JourneyEditScreen> createState() => _JourneyEditScreenState();
}

class _JourneyEditScreenState extends ConsumerState<JourneyEditScreen> {
  final _notes = TextEditingController();

  /// Built once from the loaded journey. Rebuilding it on every provider
  /// rebuild would throw away half-typed input and reset the picker.
  JourneyRouteDraft? _draft;
  int? _seededFrom;

  bool _busy = false;
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
    _draft?.dispose();
    super.dispose();
  }

  void _seed(Journey journey) {
    if (_seededFrom == journey.id) return;
    _draft?.dispose();
    _draft = JourneyRouteDraft.fromJourney(journey);
    _notes.text = journey.notes;
    _seededFrom = journey.id;
  }

  Future<void> _save(Journey journey) async {
    final draft = _draft;
    final l = L.of(context);
    if (draft == null) return;
    if (!draft.isValid(routeCopyOf(context))) {
      setState(() => _showErrors = true);
      return;
    }

    // Warn before the write, not after it. A traveller who is about to send
    // an approved boarding pass back to the review queue should decide that
    // knowingly.
    if (_wouldInvalidateProof(journey, draft)) {
      final confirmed = await confirmAction(
        context,
        title: l.journeyEditProofWarningTitle,
        body: l.journeyEditProofWarningBody,
        confirmLabel: l.journeySaveChanges,
      );
      if (!confirmed || !mounted) return;
    }

    setState(() {
      _busy = true;
      _showErrors = true;
      _fieldErrors = const FieldErrorMap.empty();
    });

    try {
      final result = await ref
          .read(journeyRepositoryProvider)
          .update(
            id: journey.id,
            startPlaceId: draft.startPlaceId,
            destinationPlaceId: draft.destinationPlaceId,
            legs: draft.toLegDrafts(),
            notes: _notes.text.trim(),
          );

      if (!mounted) return;
      ref.invalidate(journeyDetailProvider(journey.id));
      refreshVolatileState(ref);
      final change = result.change;
      AppSnack.success(
        context,
        change.proofsResetForReview > 0
            ? l.journeyEditSavedProofReset(change.proofsResetForReview)
            : l.journeyEditSaved,
      );
      context.pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _fieldErrors = FieldErrorMap.from(error));
      AppSnack.failure(
        context,
        error,
        fallback: journeyRouteFailure(context, error),
      );
      // The world moved under the form: the journey went live, or a sender
      // proposed. Re-reading is the only honest recovery.
      if (error.isStale) ref.invalidate(journeyDetailProvider(journey.id));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Whether saving would cost the journey a reviewed proof.
  ///
  /// A conservative mirror of the server's rule, used only to decide whether
  /// to ask. The server remains the authority on what is actually
  /// invalidated, and the result reports what it did.
  bool _wouldInvalidateProof(Journey journey, JourneyRouteDraft draft) {
    final proven = {
      for (final leg in journey.legs)
        if (leg.mode.requiresProof && leg.proofs.isNotEmpty) leg.id: leg,
    };
    if (proven.isEmpty) return false;

    final kept = <int>{};
    for (var i = 0; i < draft.segments.length; i++) {
      final segment = draft.segments[i];
      final id = segment.id;
      if (id == null) continue;
      kept.add(id);
      final leg = proven[id];
      if (leg == null) continue;
      final changed =
          !segment.mode.isFlight ||
          leg.originPlace?.id != draft.stops[i].endpoint.id ||
          leg.destinationPlace?.id != draft.stops[i + 1].endpoint.id ||
          _normalisedFlightNumber(leg.flightNumber) !=
              _normalisedFlightNumber(segment.flightNumber.text) ||
          leg.departAt != segment.departAt ||
          leg.arriveAt != segment.arriveAt;
      if (changed) return true;
    }
    // A proven leg the edit drops entirely loses its proof outright.
    return proven.keys.any((id) => !kept.contains(id));
  }

  static String _normalisedFlightNumber(String value) =>
      value.replaceAll(' ', '').toUpperCase();

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final journey = ref.watch(journeyDetailProvider(widget.journeyId));

    return AppScaffold(
      topBar: AppTopBar(title: l.journeyEditTitle, showBack: true),
      body: AsyncView<Journey>(
        value: journey,
        onRetry: () => ref.invalidate(journeyDetailProvider(widget.journeyId)),
        loading: () => ListView(
          padding: AppScrollPadding.page(context),
          children: const [SkeletonDetail()],
        ),
        data: (data) {
          if (!data.canEdit) return _Blocked(journey: data);
          _seed(data);
          final draft = _draft!;
          final unclaimed = _fieldErrors.unclaimed(_claimedFields);

          return DismissKeyboardOnTap(
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

                if (data.legsNeedingProof.isNotEmpty ||
                    data.legs.any((leg) => leg.proofs.isNotEmpty)) ...[
                  InfoNotice(
                    message: l.journeyEditProofNotice,
                    icon: Icons.verified_user_outlined,
                  ),
                  const SizedBox(height: AppSpace.xl),
                ],

                SectionHeader(
                  title: l.routeStopsTitle,
                  subtitle: l.routeStopsHelp,
                ),
                JourneyRouteEditor(
                  draft: draft,
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
          );
        },
      ),
      footer: (journey.value?.canEdit ?? false)
          ? AppButton(
              label: l.journeySaveChanges,
              isLoading: _busy,
              onPressed: _busy ? null : () => _save(journey.value!),
            )
          : null,
    );
  }
}

/// Why this journey cannot be edited, in the traveller's terms.
///
/// Not a hidden button: a refusal that explains itself is the difference
/// between "the app is broken" and "I need to cancel this one".
class _Blocked extends StatelessWidget {
  const _Blocked({required this.journey});

  final Journey journey;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final body = switch (journey.editBlockedCode) {
      'journey_has_dependent_state' => l.journeyEditBlockedDependent,
      'journey_not_owned' => l.journeyErrorNotOwned,
      _ => l.journeyEditBlockedStatus,
    };

    return ListView(
      padding: AppScrollPadding.page(context),
      children: [
        AppEmptyState(
          title: l.journeyEditBlockedTitle,
          body: body,
          icon: Icons.lock_outline_rounded,
        ),
      ],
    );
  }
}
