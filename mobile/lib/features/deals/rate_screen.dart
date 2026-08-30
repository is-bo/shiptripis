/// Leave a rating.
///
/// Double-blind: neither side sees the other's review until both have written
/// one or the fourteen-day window closes. The screen states that up front,
/// because a user who thinks they are replying to a review they have already
/// read will write something different from one who knows they are going
/// first.
///
/// The tag vocabulary and the comment limit are **server policy**, delivered in
/// the rating state. Nothing here hard-codes either.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/deal.dart';
import '../../l10n/app_localizations.dart';

class RateScreen extends ConsumerStatefulWidget {
  const RateScreen({required this.dealId, super.key});

  final int dealId;

  @override
  ConsumerState<RateScreen> createState() => _RateScreenState();
}

class _RateScreenState extends ConsumerState<RateScreen> {
  final _comment = TextEditingController();
  final _tags = <String>{};

  int _score = 0;
  bool _busy = false;

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_score == 0) return;
    setState(() => _busy = true);
    final l = L.of(context);

    try {
      await ref
          .read(ratingRepositoryProvider)
          .submit(
            dealId: widget.dealId,
            score: _score,
            tags: _tags.toList(growable: false),
            comment: _comment.text.trim(),
          );
      if (!mounted) return;
      refreshVolatileState(ref);
      AppSnack.success(context, l.ratingSubmitted);
      context.pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      // `rating_already_submitted` is not really a failure — the rating exists.
      if (error.code.raw == 'rating_already_submitted') {
        refreshVolatileState(ref);
        AppSnack.info(context, l.ratingSubmitted);
        context.pop();
        return;
      }
      AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final deal = ref.watch(dealDetailProvider(widget.dealId));

    return DismissKeyboardOnTap(
      child: AppScaffold(
        topBar: AppTopBar(title: l.ratingTitle, showBack: true),
        body: AsyncView<Deal>(
          value: deal,
          onRetry: () => ref.invalidate(dealDetailProvider(widget.dealId)),
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpace.gutter),
            child: SkeletonDetail(),
          ),
          data: (data) {
            final ratings = data.ratings;
            final isSender = account != null && data.isSender(account.id);

            if (ratings == null || !ratings.windowOpen) {
              return AppEmptyState(
                title: l.ratingWindowClosed,
                body: l.ratingEmptyBody,
                icon: Icons.star_outline_rounded,
              );
            }

            if (ratings.submitted) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.ratingSubmittedTitle,
                    body: ratings.bothSidesSubmitted
                        ? l.ratingSubmitted
                        : l.ratingWaitingForOther,
                    icon: Icons.check_circle_outline_rounded,
                  ),
                ],
              );
            }

            final maxComment = ratings.maxCommentLength ?? 1000;

            return ListView(
              padding: AppScrollPadding.pageWithFooter(context),
              children: [
                Text(
                  isSender ? l.ratingSenderPrompt : l.ratingTravelerPrompt,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: AppSpace.lg),
                InfoNotice(
                  message: l.ratingBlindNote,
                  icon: Icons.visibility_off_outlined,
                ),
                const SizedBox(height: AppSpace.xl),

                _Stars(
                  score: _score,
                  onChanged: (value) => setState(() => _score = value),
                ),

                if (ratings.allowedTags.isNotEmpty) ...[
                  const SizedBox(height: AppSpace.xxl),
                  SectionHeader(title: l.ratingTagsLabel),
                  Wrap(
                    spacing: AppSpace.sm,
                    runSpacing: AppSpace.sm,
                    children: [
                      // Server-supplied vocabulary, rendered as sent. A local
                      // translation table would silently drift from policy.
                      for (final tag in ratings.allowedTags)
                        _TagChip(
                          label: tag.replaceAll('_', ' '),
                          selected: _tags.contains(tag),
                          onTap: () => setState(() {
                            if (!_tags.remove(tag)) _tags.add(tag);
                          }),
                        ),
                    ],
                  ),
                ],

                const SizedBox(height: AppSpace.xxl),
                AppTextField(
                  label: l.ratingCommentLabel,
                  controller: _comment,
                  maxLines: 5,
                  minLines: 3,
                  maxLength: maxComment,
                ),
              ],
            );
          },
        ),
        footer: AppButton(
          label: l.ratingSubmit,
          isLoading: _busy,
          onPressed: _score == 0 ? null : _submit,
        ),
      ),
    );
  }
}

class _Stars extends StatelessWidget {
  const _Stars({required this.score, required this.onChanged});

  final int score;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return Semantics(
      slider: true,
      value: score == 0 ? null : l.ratingScoreLabel(score),
      child: ExcludeSemantics(
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            for (var i = 1; i <= 5; i++)
              // A star is a small glyph; the tap target around it is not.
              InkWell(
                onTap: () => onChanged(i),
                borderRadius: AppRadius.rPill,
                child: Padding(
                  padding: const EdgeInsets.all(AppSpace.sm),
                  child: Icon(
                    i <= score
                        ? Icons.star_rounded
                        : Icons.star_outline_rounded,
                    size: 36,
                    color: i <= score ? c.attention : c.hairlineStrong,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _TagChip extends StatelessWidget {
  const _TagChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return Semantics(
      button: true,
      selected: selected,
      hint: selected ? l.a11ySelected : l.a11yNotSelected,
      label: label,
      child: ExcludeSemantics(
        child: Material(
          color: selected ? c.brandSoft : c.surfaceSunken,
          borderRadius: AppRadius.rPill,
          child: InkWell(
            onTap: onTap,
            borderRadius: AppRadius.rPill,
            child: Container(
              constraints: const BoxConstraints(minHeight: 40),
              padding: const EdgeInsets.symmetric(horizontal: AppSpace.lg),
              alignment: Alignment.center,
              child: Text(
                label,
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: selected ? c.brandStrong : c.textSecondary,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
