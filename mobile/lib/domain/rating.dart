/// Ratings.
///
/// **Double-blind.** Neither party sees the other's review until both have
/// submitted, or until the 14-day window closes — whichever comes first. That
/// is enforced on the server: an unrevealed rating is simply absent from the
/// payload. The client's job is to make the wait legible rather than to hide
/// something it was given, which is why [RatingState.counterpartySubmitted]
/// exists: a content-free boolean that lets the UI say "they have rated you,
/// you will both see it when you rate them".
///
/// The tag vocabulary is server policy, not a Dart constant. It arrives in
/// [RatingState.allowedTags] and the picker renders exactly that list.
library;

import 'json.dart';

class Rating {
  const Rating({
    required this.id,
    required this.dealId,
    required this.score,
    required this.tags,
    required this.isRevealed,
    this.raterId,
    this.rateeId,
    this.raterRole,
    this.comment,
    this.reviewWindowEndsAt,
    this.revealedAt,
    this.createdAt,
    this.isMine = false,
  });

  factory Rating.fromJson(Map<String, dynamic> json) => Rating(
    id: readInt(json['id']) ?? 0,
    dealId: readInt(json['deal_id']) ?? 0,
    raterId: readInt(json['rater_id']),
    rateeId: readInt(json['ratee_id']),
    raterRole: readString(json['rater_role']),
    score: readInt(json['score']) ?? 0,
    tags: readStringList(json['tags']),
    comment: readString(json['comment']),
    reviewWindowEndsAt: readDate(json['review_window_ends_at']),
    revealedAt: readDate(json['revealed_at']),
    isRevealed: readBool(json['is_revealed']),
    createdAt: readDate(json['created_at']),
    // Present only on the per-deal state projection.
    isMine: readBool(json['is_mine']),
  );

  final int id;
  final int dealId;
  final int? raterId;
  final int? rateeId;

  /// `sender` or `traveler`.
  final String? raterRole;

  final int score;
  final List<String> tags;
  final String? comment;
  final DateTime? reviewWindowEndsAt;
  final DateTime? revealedAt;

  /// Server-computed, not the raw `revealed_at` stamp.
  final bool isRevealed;

  final DateTime? createdAt;

  /// True when the viewer wrote this one. Only meaningful on the per-deal
  /// state; the "ratings I received" list omits the field entirely.
  final bool isMine;
}

/// The server's authoritative rating lifecycle for one viewer.
///
/// J1 made this explicit because the booleans could not express it: `expired`
/// and `unavailable` both read as "window closed", and `revealed` had no
/// representation at all, so a fully-revealed rating rendered an empty panel.
/// An older deployment that omits the field parses as [unknown], and callers
/// fall back to the booleans rather than losing the section.
enum RatingLifecycleState {
  available,
  submittedWaiting,
  revealed,
  expired,
  unavailable,
  unknown;

  static RatingLifecycleState parse(String? raw) => switch (raw) {
    'available' => available,
    'submitted_waiting' => submittedWaiting,
    'revealed' => revealed,
    'expired' => expired,
    'unavailable' => unavailable,
    _ => unknown,
  };
}

/// `GET /api/deals/<id>/ratings`, and the `ratings` block on a Deal.
class RatingState {
  const RatingState({
    required this.state,
    required this.dealId,
    required this.windowOpen,
    required this.canRate,
    required this.submitted,
    required this.counterpartySubmitted,
    required this.bothSidesSubmitted,
    required this.allowedTags,
    required this.ratings,
    this.dealStatusRaw,
    this.viewerRole,
    this.reviewWindowEndsAt,
    this.maxCommentLength,
  });

  static RatingState? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return RatingState(
      state: RatingLifecycleState.parse(readString(json['state'])),
      dealId: readInt(json['deal_id']) ?? 0,
      dealStatusRaw: readString(json['deal_status']),
      viewerRole: readString(json['viewer_role']),
      reviewWindowEndsAt: readDate(json['review_window_ends_at']),
      windowOpen: readBool(json['window_open']),
      canRate: readBool(json['can_rate']),
      submitted: readBool(json['submitted']),
      counterpartySubmitted: readBool(json['counterparty_submitted']),
      bothSidesSubmitted: readBool(json['both_sides_submitted']),
      allowedTags: readStringList(json['allowed_tags']),
      maxCommentLength: readInt(json['max_comment_length']),
      ratings: readObjectList(
        json['ratings'],
      ).map(Rating.fromJson).toList(growable: false),
    );
  }

  /// The server's lifecycle state. [RatingLifecycleState.unknown] means the
  /// deployment predates the field; use the boolean fallbacks below.
  final RatingLifecycleState state;

  final int dealId;
  final String? dealStatusRaw;

  /// `sender` or `traveler`.
  final String? viewerRole;

  final DateTime? reviewWindowEndsAt;
  final bool windowOpen;
  final bool canRate;

  /// Whether this viewer has already rated.
  final bool submitted;

  /// Content-free: the other side has rated, but you cannot see it yet.
  final bool counterpartySubmitted;

  final bool bothSidesSubmitted;

  /// Server policy. The tag picker renders exactly this.
  final List<String> allowedTags;

  final int? maxCommentLength;

  /// Only what the viewer is entitled to see: their own always, plus any
  /// revealed one.
  final List<Rating> ratings;

  Rating? get mine {
    for (final rating in ratings) {
      if (rating.isMine) return rating;
    }
    return null;
  }

  Rating? get theirs {
    for (final rating in ratings) {
      if (!rating.isMine) return rating;
    }
    return null;
  }

  /// The waiting state: you rated, they have not, so nothing is visible yet.
  bool get awaitingCounterparty =>
      submitted && !counterpartySubmitted && theirs == null;

  /// They rated first. Prompting is now worth doing — it unlocks both.
  bool get counterpartyIsWaiting =>
      !submitted && counterpartySubmitted && canRate;

  /// The viewer still owes a rating and may leave one.
  bool get isActionable => switch (state) {
    RatingLifecycleState.available => true,
    RatingLifecycleState.unknown => windowOpen && canRate && !submitted,
    _ => false,
  };

  /// The viewer has rated and is waiting on the counterpart.
  bool get isAwaitingCounterparty => switch (state) {
    RatingLifecycleState.submittedWaiting => true,
    RatingLifecycleState.unknown => awaitingCounterparty,
    _ => false,
  };

  /// Both ratings are open. Only in this state may the counterpart's rating be
  /// shown — the blind period is a product rule, not a presentation detail.
  bool get isRevealed => switch (state) {
    RatingLifecycleState.revealed => true,
    RatingLifecycleState.unknown => submitted && bothSidesSubmitted,
    _ => false,
  };

  /// The window closed without the viewer rating.
  bool get isExpired => switch (state) {
    RatingLifecycleState.expired => true,
    RatingLifecycleState.unknown => !windowOpen && !submitted,
    _ => false,
  };

  /// Nothing to say: not a party, or no rating was ever possible.
  bool get isUnavailable => state == RatingLifecycleState.unavailable;

  /// The counterpart's rating, and only once the server says it is revealed.
  Rating? get revealedCounterpartRating {
    if (!isRevealed) return null;
    final rating = theirs;
    if (rating == null || !rating.isRevealed) return null;
    return rating;
  }
}
