/// The reviews of one person or one trip.
///
/// Opened from the rating on a person's page, a trip's preview and a Find
/// Travelers candidate. The summary above the list is the server's own number
/// (the one the card showed), the list is countable reviews only and pages on
/// the server's cursor, and nothing here names an author or a delivery.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/discovery_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/find_travelers.dart';
import '../../domain/reviews.dart';
import '../../l10n/app_localizations.dart';
import '../auth/account_gate.dart';
import '../discovery/discovery_widgets.dart';
import 'report_review_sheet.dart';
import 'review_widgets.dart';

class ReviewsScreen extends ConsumerWidget {
  const ReviewsScreen({required this.subject, super.key});

  final ReviewsSubject subject;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final provider = reviewsFeedProvider(subject);
    final feed = ref.watch(provider).ofCurrentAccount;
    final error = feed.error;
    final gone =
        !feed.hasValue &&
        error is ApiException &&
        (error.code == ApiErrorCode.tripNotFound ||
            error.code == ApiErrorCode.profileNotFound);

    return AppScaffold(
      topBar: AppTopBar(title: l.reviewsTitle, showBack: true),
      body: gone
          ? AppEmptyState(
              title: l.reviewsGoneTitle,
              body: l.reviewsGoneBody,
              icon: Icons.search_off_rounded,
            )
          : DiscoverySection<DiscoveryFeed<PublicReview>>(
              value: feed,
              onRetry: () => ref.invalidate(provider),
              skeleton: ListView(
                padding: AppScrollPadding.page(context),
                children: const [SkeletonCardList()],
              ),
              data: (data) => RefreshIndicator(
                onRefresh: () async => ref.invalidate(provider),
                child: _Body(subject: subject, feed: data),
              ),
            ),
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.subject, required this.feed});

  final ReviewsSubject subject;
  final DiscoveryFeed<PublicReview> feed;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final provider = reviewsFeedProvider(subject);
    final controller = ref.read(provider.notifier);

    if (feed.disabled) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: AppScrollPadding.page(context),
        children: [
          AppEmptyState(
            title: l.reviewsOffTitle,
            body: l.reviewsOffBody,
            icon: Icons.pause_circle_outline_rounded,
          ),
        ],
      );
    }
    if (feed.items.isEmpty) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: AppScrollPadding.page(context),
        children: [
          AppEmptyState(
            title: l.reviewsEmptyTitle,
            body: l.reviewsEmptyBody,
            icon: Icons.star_outline_rounded,
          ),
        ],
      );
    }

    final rating = controller.rating;
    return PagedFeedList<PublicReview>(
      feed: feed,
      onLoadMore: controller.loadMore,
      header: rating == null || !rating.hasScore
          ? null
          : Padding(
              padding: const EdgeInsets.only(bottom: AppSpace.lg),
              child: _Summary(rating: rating),
            ),
      itemBuilder: (context, review) => _ReviewCard(
        review: review,
        onReport: () => _report(context, ref, review),
      ),
    );
  }

  Future<void> _report(
    BuildContext context,
    WidgetRef ref,
    PublicReview review,
  ) async {
    final provider = reviewsFeedProvider(subject);
    final wasGuest = ref.read(isGuestProvider);
    if (!await ensureAccount(context, AccountReason.report) ||
        !context.mounted) {
      return;
    }
    if (wasGuest) {
      // Signed in just now: the list is read again for this member, who may
      // have reported this review already.
      final feed = await ref.read(provider.future);
      final fresh = feed.items.where((r) => r.id == review.id).firstOrNull;
      if (fresh == null || fresh.myReport != null || !context.mounted) return;
    }
    // From Find Travelers the sender's request rides along, so a review the
    // listings switch no longer shows can still be reported under the same
    // rule that lets them read it.
    final trip = subject is TripReviews ? subject as TripReviews : null;
    final request = trip?.requestId;
    final reported = await showReportReviewSheet(
      context,
      ratingId: review.id,
      journeyId: request == null ? null : trip?.journeyId,
      requestId: request,
      onStale: () => ref.invalidate(provider),
    );
    if (reported != null) {
      ref.read(provider.notifier).markReported(review.id, reported);
    }
  }
}

/// The server's average and count, for the same list.
class _Summary extends StatelessWidget {
  const _Summary({required this.rating});

  final TravelerRating rating;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppInsetGroup(
      child: Semantics(
        container: true,
        label: l.reviewsRatingA11y(
          rating.average!.toStringAsFixed(1),
          rating.count,
        ),
        excludeSemantics: true,
        child: Row(
          children: [
            Icon(Icons.star_rounded, size: 28, color: c.attention),
            const SizedBox(width: AppSpace.md),
            Text(
              rating.average!.toStringAsFixed(1),
              style: text.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(width: AppSpace.md),
            Expanded(
              child: Text(
                l.reviewsCount(rating.count),
                style: text.bodyMedium?.copyWith(color: c.textSecondary),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ReviewCard extends StatelessWidget {
  const _ReviewCard({required this.review, required this.onReport});

  final PublicReview review;
  final VoidCallback onReport;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final month = review.month;
    final reported = review.myReport;

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
              ReviewStars(score: review.score),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: Text(
                  [
                    review.writtenBySender
                        ? l.reviewsFromSender
                        : l.reviewsFromTraveler,
                    if (month != null) LocaleFormats.monthYear(locale, month),
                  ].join(' · '),
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              // A review already reported offers nothing more.
              if (reported == null)
                PopupMenuButton<void>(
                  tooltip: l.reviewsMenuLabel,
                  icon: Icon(Icons.more_vert_rounded, color: c.textSecondary),
                  itemBuilder: (_) => [
                    PopupMenuItem<void>(
                      onTap: onReport,
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
                if (review.tags.isNotEmpty) ...[
                  const SizedBox(height: AppSpace.sm),
                  ReviewTags(tags: review.tags),
                ],
                if (review.commentRemoved) ...[
                  const SizedBox(height: AppSpace.md),
                  Row(
                    children: [
                      Icon(
                        Icons.visibility_off_outlined,
                        size: 16,
                        color: c.textTertiary,
                      ),
                      const SizedBox(width: AppSpace.sm),
                      Expanded(
                        child: Text(
                          l.reviewsCommentRemoved,
                          style: text.bodyMedium?.copyWith(
                            color: c.textTertiary,
                            fontStyle: FontStyle.italic,
                          ),
                        ),
                      ),
                    ],
                  ),
                ] else if (review.hasComment) ...[
                  const SizedBox(height: AppSpace.md),
                  Text(
                    review.comment!,
                    style: text.bodyMedium?.copyWith(color: c.textSecondary),
                  ),
                ],
                if (reported != null) ...[
                  const SizedBox(height: AppSpace.md),
                  Row(
                    children: [
                      Icon(Icons.flag_rounded, size: 16, color: c.textTertiary),
                      const SizedBox(width: AppSpace.sm),
                      Expanded(
                        child: Text(
                          reported == MyReport.reviewed
                              ? l.reviewsReportReviewed
                              : l.reviewsReportReceived,
                          style: text.bodySmall?.copyWith(
                            color: c.textTertiary,
                          ),
                        ),
                      ),
                    ],
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
