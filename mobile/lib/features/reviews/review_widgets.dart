/// The small pieces every review surface shares: stars, tag chips, and the
/// tappable rating that opens the Reviews screen.
library;

import 'package:flutter/material.dart';

import '../../design/tokens.dart';
import '../../domain/find_travelers.dart';
import '../../l10n/app_localizations.dart';

/// Five stars for a score. Read as one label, never as five icons.
class ReviewStars extends StatelessWidget {
  const ReviewStars({required this.score, super.key});

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

/// The tags of a review, as the server wrote them. The vocabulary is server
/// policy, so it is shown as given rather than mapped through a local table
/// that would drift.
class ReviewTags extends StatelessWidget {
  const ReviewTags({required this.tags, super.key});

  final List<String> tags;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    return Wrap(
      spacing: AppSpace.sm,
      runSpacing: AppSpace.sm,
      children: [
        for (final tag in tags)
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
              tag.replaceAll('_', ' '),
              style: text.labelSmall?.copyWith(color: c.onNeutralSoft),
            ),
          ),
      ],
    );
  }
}

/// "★ 4.8 · 24 reviews ›": the rating the card showed, as the way into the
/// reviews behind it. Only a rated person has reviews to open, so an unrated
/// one gets no link (the card's own "New" says it).
class ReviewsLink extends StatelessWidget {
  const ReviewsLink({required this.rating, required this.onTap, super.key});

  final TravelerRating rating;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final value = rating.average!.toStringAsFixed(1);

    return Semantics(
      button: true,
      label: l.reviewsRatingA11y(value, rating.count),
      excludeSemantics: true,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppRadius.rSm,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 44),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.star_rounded, size: 18, color: c.attention),
              const SizedBox(width: AppSpace.xs),
              Flexible(
                child: Text(
                  '$value · ${l.reviewsCount(rating.count)}',
                  style: text.labelLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: c.brandInk,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Icon(
                Directionality.of(context) == TextDirection.rtl
                    ? Icons.chevron_left_rounded
                    : Icons.chevron_right_rounded,
                size: 20,
                color: c.brandInk,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
