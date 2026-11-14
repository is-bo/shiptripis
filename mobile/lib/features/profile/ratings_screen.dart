/// Ratings this account has received.
///
/// Only revealed ones reach the client at all — an unrevealed rating is simply
/// absent from the payload, not hidden behind a flag — so this list needs no
/// blurring or masking of its own. What it shows is what the server has
/// already decided both parties may see.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/format/locale_formats.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/rating.dart';
import '../../domain/reviews.dart';
import '../../l10n/app_localizations.dart';
import '../reviews/report_review_sheet.dart';
import '../reviews/review_widgets.dart';

class RatingsScreen extends ConsumerWidget {
  const RatingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final ratings = ref.watch(receivedRatingsProvider);

    return AppScaffold(
      topBar: AppTopBar(title: l.profileRatings, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(receivedRatingsProvider),
        child: AsyncView<List<Rating>>(
          value: ratings,
          onRetry: () => ref.invalidate(receivedRatingsProvider),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (all) {
            if (all.isEmpty) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.ratingEmptyTitle,
                    body: l.ratingEmptyBody,
                    icon: Icons.star_outline_rounded,
                  ),
                ],
              );
            }

            // Built lazily: ratings accumulate with every completed Deal. A
            // removed rating is listed, as such, but is not counted.
            final counted = all
                .where((rating) => !rating.isRemoved)
                .toList(growable: false);
            return ListView.builder(
              padding: AppScrollPadding.page(context),
              itemCount: all.length + 1,
              itemBuilder: (context, index) {
                if (index == 0) {
                  return counted.isEmpty
                      ? const SizedBox.shrink()
                      : Padding(
                          padding: const EdgeInsets.only(bottom: AppSpace.xl),
                          child: _Summary(ratings: counted),
                        );
                }
                return Padding(
                  padding: const EdgeInsets.only(bottom: AppSpace.md),
                  child: _RatingCard(rating: all[index - 1]),
                );
              },
            );
          },
        ),
      ),
    );
  }
}

/// The average, and how many it is based on.
///
/// Averaging the counted scores is arithmetic on a list the server already
/// handed over in full; which ratings count (not the removed ones) is the
/// server's mark on each row, and there is no server field that supplies the
/// average here.
class _Summary extends StatelessWidget {
  const _Summary({required this.ratings});

  final List<Rating> ratings;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    var total = 0;
    for (final rating in ratings) {
      total += rating.score;
    }
    final average = total / ratings.length;

    return AppInsetGroup(
      child: Row(
        children: [
          Icon(Icons.star_rounded, size: 26, color: c.attention),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: Text(
              l.discoveryRatingCount(
                average.toStringAsFixed(1),
                ratings.length,
              ),
              style: text.titleMedium,
            ),
          ),
        ],
      ),
    );
  }
}

class _RatingCard extends ConsumerWidget {
  const _RatingCard({required this.rating});

  final Rating rating;

  Future<void> _report(BuildContext context, WidgetRef ref) async {
    final reported = await showReportReviewSheet(
      context,
      ratingId: rating.id,
      onStale: () => ref.invalidate(receivedRatingsProvider),
    );
    if (reported != null) ref.invalidate(receivedRatingsProvider);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final when = rating.createdAt;
    final removed = rating.isRemoved;
    final reported = rating.myReport;
    final canReport = !removed && reported == null;

    return AppCard(
      padding: const EdgeInsetsDirectional.fromSTEB(
        AppSpace.lg,
        AppSpace.md,
        AppSpace.xs,
        AppSpace.md,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ReviewStars(score: rating.score),
              const Spacer(),
              if (when != null)
                Text(
                  LocaleFormats.dayMonth(locale, when),
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                ),
              if (canReport)
                PopupMenuButton<void>(
                  tooltip: l.reviewsMenuLabel,
                  icon: Icon(Icons.more_vert_rounded, color: c.textSecondary),
                  itemBuilder: (_) => [
                    PopupMenuItem<void>(
                      onTap: () => _report(context, ref),
                      child: Row(
                        children: [
                          Icon(
                            Icons.flag_outlined,
                            size: 20,
                            color: c.textSecondary,
                          ),
                          const SizedBox(width: AppSpace.md),
                          Text(l.reviewsReportAction),
                        ],
                      ),
                    ),
                  ],
                )
              else
                const SizedBox(width: AppSpace.md),
            ],
          ),
          Padding(
            padding: const EdgeInsetsDirectional.only(end: AppSpace.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (removed) ...[
                  const SizedBox(height: AppSpace.sm),
                  _Note(
                    icon: Icons.block_rounded,
                    text: l.ratingRemovedByWassla,
                    color: c.danger,
                  ),
                ] else if (rating.moderation ==
                    ReviewModeration.commentHidden) ...[
                  const SizedBox(height: AppSpace.sm),
                  _Note(
                    icon: Icons.visibility_off_outlined,
                    text: l.ratingCommentHiddenByWassla,
                    color: c.textTertiary,
                  ),
                ],
                if (rating.tags.isNotEmpty) ...[
                  const SizedBox(height: AppSpace.md),
                  ReviewTags(tags: rating.tags),
                ],
                if (rating.comment != null && rating.comment!.isNotEmpty) ...[
                  const SizedBox(height: AppSpace.md),
                  Text(
                    rating.comment!,
                    style: text.bodyMedium?.copyWith(
                      color: removed ? c.textTertiary : c.textSecondary,
                    ),
                  ),
                ],
                if (reported != null) ...[
                  const SizedBox(height: AppSpace.md),
                  _Note(
                    icon: Icons.flag_rounded,
                    text: reported == MyReport.reviewed
                        ? l.reviewsReportReviewed
                        : l.reviewsReportReceived,
                    color: c.textTertiary,
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Note extends StatelessWidget {
  const _Note({required this.icon, required this.text, required this.color});

  final IconData icon;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(icon, size: 16, color: color),
      const SizedBox(width: AppSpace.sm),
      Expanded(
        child: Text(
          text,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: color),
        ),
      ),
    ],
  );
}
