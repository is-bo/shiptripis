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
import '../../l10n/app_localizations.dart';

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

            return ListView(
              padding: AppScrollPadding.page(context),
              children: [
                _Summary(ratings: all),
                const SizedBox(height: AppSpace.xl),
                for (final rating in all) ...[
                  _RatingCard(rating: rating),
                  const SizedBox(height: AppSpace.md),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

/// The average, and how many it is based on.
///
/// Averaging received scores is arithmetic on a list the server already handed
/// over in full — it is presentation, not a business rule, and there is no
/// server field that supplies it.
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

class _RatingCard extends StatelessWidget {
  const _RatingCard({required this.rating});

  final Rating rating;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final when = rating.createdAt;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _Stars(score: rating.score),
              const Spacer(),
              if (when != null)
                Text(
                  LocaleFormats.dayMonth(locale, when),
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                ),
            ],
          ),
          if (rating.tags.isNotEmpty) ...[
            const SizedBox(height: AppSpace.md),
            Wrap(
              spacing: AppSpace.sm,
              runSpacing: AppSpace.sm,
              children: [
                for (final tag in rating.tags)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpace.md,
                      vertical: AppSpace.xs,
                    ),
                    decoration: BoxDecoration(
                      color: c.neutralSoft,
                      borderRadius: AppRadius.rPill,
                    ),
                    child: Text(
                      // Server-authored vocabulary. Rendered as given rather
                      // than mapped through a local table that would drift.
                      tag.replaceAll('_', ' '),
                      style: text.labelSmall?.copyWith(color: c.onNeutralSoft),
                    ),
                  ),
              ],
            ),
          ],
          if (rating.comment != null && rating.comment!.isNotEmpty) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              rating.comment!,
              style: text.bodyMedium?.copyWith(color: c.textSecondary),
            ),
          ],
        ],
      ),
    );
  }
}

class _Stars extends StatelessWidget {
  const _Stars({required this.score});

  final int score;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Semantics(
      label: '$score / 5',
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 1; i <= 5; i++)
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 2),
              child: Icon(
                i <= score ? Icons.star_rounded : Icons.star_outline_rounded,
                size: 18,
                color: i <= score ? c.attention : c.hairlineStrong,
              ),
            ),
        ],
      ),
    );
  }
}
