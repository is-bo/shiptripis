/// Public reviews and reports (L13A contract, `docs/PHASE_L13A_REVIEWS.md`).
///
/// Everything here is a server projection. Which ratings count, which are
/// hidden or removed, and whether a viewer may read or report a review is
/// decided in Django (`apps.ratings.public`); this file only reads the keys the
/// contract names. A review never carries its author's name, a member id, the
/// deal or its tracking number, so none is parsed.
library;

import 'find_travelers.dart';
import 'json.dart';
import 'public_discovery.dart';

/// Whose reviews a Reviews screen lists.
///
/// A person's whole record (both sides, like their profile card), or one
/// trip's owner as a traveler (like the trip card). From Find Travelers the
/// sender's own open request rides along as [requestId], so the server can
/// answer a trip that public listings no longer show.
sealed class ReviewsSubject {
  const ReviewsSubject();
}

class PersonReviews extends ReviewsSubject {
  const PersonReviews(this.profileId);

  final String profileId;

  @override
  bool operator ==(Object other) =>
      other is PersonReviews && other.profileId == profileId;

  @override
  int get hashCode => Object.hash('person', profileId);
}

class TripReviews extends ReviewsSubject {
  const TripReviews(this.journeyId, {this.requestId});

  final int journeyId;
  final int? requestId;

  @override
  bool operator ==(Object other) =>
      other is TripReviews &&
      other.journeyId == journeyId &&
      other.requestId == requestId;

  @override
  int get hashCode => Object.hash('trip', journeyId, requestId);
}

/// What a report of one review has come to, as the reporter may know it.
///
/// `received` while open and `reviewed` once staff decided; the reporter is
/// never told more than that.
enum MyReport {
  received,
  reviewed;

  static MyReport? parse(Object? raw) => switch (raw) {
    'received' => received,
    'reviewed' => reviewed,
    _ => null,
  };
}

/// The five reasons a review can be reported for. The wire values are the
/// contract's; the sentence for each is the client's own copy.
enum ReviewReason {
  offensive('offensive'),
  personalInformation('personal_information'),
  unrelated('unrelated'),
  untrue('untrue'),
  other('other');

  const ReviewReason(this.wire);

  final String wire;
}

/// A staff decision on a review, as the rated person sees it on My ratings.
enum ReviewModeration {
  commentHidden,
  removed;

  static ReviewModeration? parse(Object? raw) => switch (raw) {
    'comment_hidden' => commentHidden,
    'removed' => removed,
    _ => null,
  };
}

/// One review on a Reviews screen.
class PublicReview {
  const PublicReview({
    required this.id,
    required this.score,
    required this.tags,
    required this.writtenBySender,
    this.comment,
    this.commentRemoved = false,
    this.month,
    this.myReport,
  });

  factory PublicReview.fromJson(Map<String, dynamic> json) => PublicReview(
    id: readInt(json['id']) ?? 0,
    score: readInt(json['score']) ?? 0,
    tags: readStringList(json['tags']),
    comment: readString(json['comment']),
    commentRemoved: readBool(json['comment_removed']),
    writtenBySender: readString(json['written_by']) == 'sender',
    month: _month(readString(json['month'])),
    myReport: MyReport.parse(json['my_report']),
  );

  /// The rating's id: what a report is filed against.
  final int id;
  final int score;
  final List<String> tags;
  final String? comment;

  /// Staff hid the comment. The score still counts.
  final bool commentRemoved;
  final bool writtenBySender;

  /// The month it was written, never a day.
  final DateTime? month;
  final MyReport? myReport;

  bool get hasComment => comment != null && comment!.trim().isNotEmpty;

  PublicReview withReport(MyReport report) => PublicReview(
    id: id,
    score: score,
    tags: tags,
    comment: comment,
    commentRemoved: commentRemoved,
    writtenBySender: writtenBySender,
    month: month,
    myReport: report,
  );
}

DateTime? _month(String? raw) {
  final parts = raw?.split('-');
  if (parts == null || parts.length != 2) return null;
  final year = int.tryParse(parts[0]);
  final month = int.tryParse(parts[1]);
  if (year == null || month == null || month < 1 || month > 12) return null;
  return DateTime(year, month);
}

/// One page of reviews, with the summary the server computed for the same
/// list. [rating] is `trust_signals` itself, so it is the number the card
/// showed; the client never averages. It is null while the tier is off.
class ReviewsPage extends DiscoveryPage<PublicReview> {
  const ReviewsPage({
    required super.state,
    required super.results,
    super.nextOffset,
    this.rating,
  });

  factory ReviewsPage.fromJson(Map<String, dynamic> json) => ReviewsPage(
    state: DiscoveryTierState.parse(json['state']),
    results: readObjectList(
      json['results'],
    ).map(PublicReview.fromJson).toList(growable: false),
    nextOffset: readInt(json['next_offset']),
    rating: readObject(json['rating']) == null
        ? null
        : TravelerRating.fromJson(readObject(json['rating'])),
  );

  final TravelerRating? rating;
}

/// The answer to a report: always "received" or "reviewed".
class ReportReceipt {
  const ReportReceipt({required this.ratingId, required this.state});

  factory ReportReceipt.fromJson(Map<String, dynamic> json) => ReportReceipt(
    ratingId: readInt(json['rating_id']) ?? 0,
    state: MyReport.parse(json['state']) ?? MyReport.received,
  );

  final int ratingId;
  final MyReport state;
}
