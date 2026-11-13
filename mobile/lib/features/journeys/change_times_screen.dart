/// "Change times": the traveler's new times on a live journey.
///
/// Two steps on one screen. First the times are edited leg by leg. Then the
/// review: the server previews what the change would do, naming every
/// affected parcel, which senders must agree and which are only told, and
/// whether it applies at once. Nothing is written until the traveler sends it.
/// Which parcels are affected and why is the server's answer; this screen
/// measures nothing.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/journey.dart';
import '../../domain/schedule_change.dart';
import '../../l10n/app_localizations.dart';
import 'journey_labels.dart';
import 'journey_route_editor.dart' show pickJourneyDateTime;
import 'schedule_change_widgets.dart';

class ChangeTimesScreen extends ConsumerStatefulWidget {
  const ChangeTimesScreen({required this.journeyId, super.key});

  final int journeyId;

  @override
  ConsumerState<ChangeTimesScreen> createState() => _ChangeTimesScreenState();
}

class _ChangeTimesScreenState extends ConsumerState<ChangeTimesScreen> {
  static const _reasonLimit = 500;

  final _reason = TextEditingController();
  final Map<int, DateTime> _depart = {};
  final Map<int, DateTime> _arrive = {};
  bool _seeded = false;
  bool _busy = false;
  String? _error;
  SchedulePreview? _preview;

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  void _seed(Journey journey) {
    if (_seeded) return;
    _seeded = true;
    for (final leg in journey.legs) {
      if (leg.departAt != null) _depart[leg.id] = leg.departAt!;
      if (leg.arriveAt != null) _arrive[leg.id] = leg.arriveAt!;
    }
  }

  /// The legs whose picked time differs from the one in force. Minutes, not
  /// seconds: a picker has no seconds, and a stored one must not read as an
  /// edit.
  List<LegTimesInput> _changed(Journey journey) {
    bool differs(DateTime? a, DateTime? b) =>
        a == null || b == null || a.difference(b).inMinutes != 0;
    return [
      for (final leg in journey.legs)
        if (_depart[leg.id] != null &&
            _arrive[leg.id] != null &&
            (differs(_depart[leg.id], leg.departAt) ||
                differs(_arrive[leg.id], leg.arriveAt)))
          LegTimesInput(
            legId: leg.id,
            departAt: _depart[leg.id]!,
            arriveAt: _arrive[leg.id]!,
          ),
    ];
  }

  Future<void> _pick(int legId, {required bool departure}) async {
    final map = departure ? _depart : _arrive;
    final picked = await pickJourneyDateTime(context, map[legId]);
    if (picked == null || !mounted) return;
    setState(() {
      map[legId] = picked;
      _error = null;
    });
  }

  Future<void> _review(Journey journey) async {
    final l = L.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final preview = await ref
          .read(journeyRepositoryProvider)
          .previewScheduleChange(journey.id, _changed(journey));
      if (!mounted) return;
      setState(() => _preview = preview);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(
        () => _error =
            scheduleFailureMessage(l, error) ??
            describeFailure(context, error).body,
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _send(Journey journey) async {
    final l = L.of(context);
    final preview = _preview;
    if (preview == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final change = await ref
          .read(journeyRepositoryProvider)
          .proposeScheduleChange(
            journey.id,
            _changed(journey),
            reason: _reason.text,
          );
      if (!mounted) return;
      ref
        ..invalidate(journeyDetailProvider(journey.id))
        ..invalidate(journeyScheduleChangesProvider(journey.id))
        ..invalidate(journeyProgressProvider(journey.id))
        ..invalidate(myJourneysProvider);
      AppSnack.success(
        context,
        change != null && change.isWaiting
            ? l.scheduleSentToSenders(change.waitingFor)
            : l.scheduleApplied,
      );
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      // A refusal can mean the journey moved on: the review no longer holds,
      // so go back to the times with the sentence.
      setState(() {
        _preview = null;
        _error =
            scheduleFailureMessage(l, error) ??
            describeFailure(context, error).body;
      });
      ref.invalidate(journeyDetailProvider(journey.id));
      ref.invalidate(journeyScheduleChangesProvider(journey.id));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final journey = ref.watch(journeyDetailProvider(widget.journeyId));
    final data = journey.value;
    if (data != null) _seed(data);
    final reviewing = _preview != null;

    return PopScope(
      canPop: !reviewing,
      onPopInvokedWithResult: (didPop, _) {
        // Back from the review returns to the times, not out of the screen.
        if (!didPop && reviewing) setState(() => _preview = null);
      },
      child: AppScaffold(
        topBar: AppTopBar(
          title: reviewing ? l.scheduleReviewTitle : l.scheduleChangeTitle,
          showBack: true,
        ),
        body: AsyncView<Journey>(
          value: journey,
          onRetry: () =>
              ref.invalidate(journeyDetailProvider(widget.journeyId)),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonDetail()],
          ),
          data: (j) => reviewing
              ? _Review(
                  preview: _preview!,
                  reason: _reason,
                  reasonLimit: _reasonLimit,
                  error: _error,
                  enabled: !_busy,
                )
              : _Edit(
                  journey: j,
                  depart: _depart,
                  arrive: _arrive,
                  changedLegIds: {for (final leg in _changed(j)) leg.legId},
                  error: _error,
                  onPick: _pick,
                ),
        ),
        footer: data == null
            ? null
            : reviewing
            ? Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  AppButton(
                    label: _preview!.appliesAtOnce
                        ? l.scheduleApplyAction
                        : l.scheduleSendAction,
                    isLoading: _busy,
                    onPressed: () => _send(data),
                  ),
                  const SizedBox(height: AppSpace.sm),
                  AppButton(
                    label: l.scheduleEditTimes,
                    variant: AppButtonVariant.tertiary,
                    onPressed: _busy
                        ? null
                        : () => setState(() => _preview = null),
                  ),
                ],
              )
            : AppButton(
                label: l.scheduleReviewAction,
                isLoading: _busy,
                onPressed: _changed(data).isEmpty ? null : () => _review(data),
              ),
      ),
    );
  }
}

class _Edit extends StatelessWidget {
  const _Edit({
    required this.journey,
    required this.depart,
    required this.arrive,
    required this.changedLegIds,
    required this.error,
    required this.onPick,
  });

  final Journey journey;
  final Map<int, DateTime> depart;
  final Map<int, DateTime> arrive;
  final Set<int> changedLegIds;
  final String? error;
  final Future<void> Function(int legId, {required bool departure}) onPick;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;

    return ListView(
      padding: AppScrollPadding.pageWithFooter(context),
      children: [
        Text(l.scheduleChangeIntro, style: text.bodyMedium),
        const SizedBox(height: AppSpace.lg),
        if (error != null) ...[
          InfoNotice(
            message: error!,
            tone: StatusTone.bad,
            icon: Icons.error_outline_rounded,
          ),
          const SizedBox(height: AppSpace.lg),
        ],
        for (final leg in journey.legs) ...[
          _LegEditor(
            leg: leg,
            depart: depart[leg.id],
            arrive: arrive[leg.id],
            changed: changedLegIds.contains(leg.id),
            onPickDepart: () => onPick(leg.id, departure: true),
            onPickArrive: () => onPick(leg.id, departure: false),
          ),
          const SizedBox(height: AppSpace.md),
        ],
        const SizedBox(height: AppSpace.sm),
        Text(
          l.scheduleStopsNote,
          style: text.bodySmall?.copyWith(color: context.colors.textTertiary),
        ),
      ],
    );
  }
}

class _LegEditor extends StatelessWidget {
  const _LegEditor({
    required this.leg,
    required this.depart,
    required this.arrive,
    required this.changed,
    required this.onPickDepart,
    required this.onPickArrive,
  });

  final JourneyLeg leg;
  final DateTime? depart;
  final DateTime? arrive;
  final bool changed;
  final VoidCallback onPickDepart;
  final VoidCallback onPickArrive;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    Widget row(String label, DateTime? value, VoidCallback onTap) {
      final shown = value == null ? '—' : LocaleFormats.dateTime(locale, value);
      return Semantics(
        button: true,
        label: '$label, $shown',
        onTap: onTap,
        child: ExcludeSemantics(
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(AppRadius.md),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 52),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          label,
                          style: text.labelMedium?.copyWith(
                            color: c.textTertiary,
                          ),
                        ),
                        Text(shown, style: text.bodyLarge),
                      ],
                    ),
                  ),
                  Icon(Icons.edit_calendar_outlined, color: c.textTertiary),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return AppCard(
      accent: changed ? StatusTone.action : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${legOriginLabel(leg)} → ${legDestinationLabel(leg)}',
            style: text.titleSmall,
          ),
          const SizedBox(height: AppSpace.xs),
          row(l.scheduleDeparture, depart, onPickDepart),
          Divider(height: 1, color: c.hairline),
          row(l.scheduleArrival, arrive, onPickArrive),
        ],
      ),
    );
  }
}

class _Review extends StatelessWidget {
  const _Review({
    required this.preview,
    required this.reason,
    required this.reasonLimit,
    required this.error,
    required this.enabled,
  });

  final SchedulePreview preview;
  final TextEditingController reason;
  final int reasonLimit;
  final String? error;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final mustAgree = preview.mustAgree;
    final told = preview.onlyTold;

    return ListView(
      padding: AppScrollPadding.pageWithFooter(context),
      children: [
        InfoNotice(
          title: preview.appliesAtOnce
              ? l.scheduleAppliesAtOnceTitle
              : l.scheduleWaitsTitle(mustAgree.length),
          message: preview.appliesAtOnce
              ? l.scheduleAppliesAtOnceBody
              : l.scheduleWaitsBody,
          tone: preview.appliesAtOnce ? StatusTone.good : StatusTone.waiting,
          icon: preview.appliesAtOnce
              ? Icons.event_available_outlined
              : Icons.hourglass_top_rounded,
        ),
        // The server's own words, such as "Your ticket will be checked
        // again...", shown as sent.
        for (final notice in preview.notices) ...[
          const SizedBox(height: AppSpace.md),
          InfoNotice(
            message: notice.text,
            tone: StatusTone.action,
            icon: Icons.confirmation_number_outlined,
          ),
        ],
        const SizedBox(height: AppSpace.xl),

        SectionHeader(title: l.scheduleNewTimesTitle),
        FullWidthGroup(child: LegChangeList(legs: preview.legs)),

        const SizedBox(height: AppSpace.xl),
        SectionHeader(title: l.scheduleAffectedTitle),
        if (preview.parcels.isEmpty)
          Text(l.scheduleNoParcelsAffected, style: text.bodyMedium)
        else ...[
          if (mustAgree.isNotEmpty)
            _ParcelGroup(
              title: l.scheduleMustAgreeTitle,
              parcels: mustAgree,
              showReasons: true,
            ),
          if (mustAgree.isNotEmpty && told.isNotEmpty)
            const SizedBox(height: AppSpace.md),
          if (told.isNotEmpty)
            _ParcelGroup(
              title: l.scheduleToldTitle,
              parcels: told,
              showReasons: false,
            ),
        ],

        if (mustAgree.isNotEmpty) ...[
          const SizedBox(height: AppSpace.xl),
          AppTextField(
            label: l.scheduleReasonLabel,
            hint: l.scheduleReasonHint,
            helper: l.scheduleReasonHelper,
            controller: reason,
            minLines: 2,
            maxLines: 4,
            maxLength: reasonLimit,
            enabled: enabled,
            keyboardType: TextInputType.multiline,
            textCapitalization: TextCapitalization.sentences,
          ),
        ],

        if (error != null) ...[
          const SizedBox(height: AppSpace.lg),
          InfoNotice(
            message: error!,
            tone: StatusTone.bad,
            icon: Icons.error_outline_rounded,
          ),
        ],
      ],
    );
  }
}

class _ParcelGroup extends StatelessWidget {
  const _ParcelGroup({
    required this.title,
    required this.parcels,
    required this.showReasons,
  });

  final String title;
  final List<AffectedParcel> parcels;
  final bool showReasons;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    return FullWidthGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: text.titleSmall),
          for (final parcel in parcels) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              parcel.trackingNumber ?? l.scheduleParcelFallback,
              style: text.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
            ),
            if (showReasons)
              for (final reason in parcel.reasons)
                Text(
                  changeReasonText(l, reason),
                  style: text.bodySmall?.copyWith(color: c.textSecondary),
                ),
            TimeDiffRow(
              label: l.scheduleArrival,
              before: parcel.arrivalBefore,
              after: parcel.arrivalAfter,
            ),
          ],
        ],
      ),
    );
  }
}
