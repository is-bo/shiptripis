import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
import 'matching_repository.dart';

final matchingRepositoryProvider = Provider<MatchingRepository>((ref) {
  return MatchingRepository(ref.read(dioProvider));
});

/// Auto-disposed list of matches filtered by role + status.
/// Use `family` so the UI can hold a separate list per role-tab.
final matchListProvider = FutureProvider.autoDispose
    .family<List<MatchSummary>, MatchListParams>((ref, params) async {
  final repo = ref.read(matchingRepositoryProvider);
  return repo.list(role: params.role, status: params.status);
});

class MatchListParams {
  const MatchListParams({this.role, this.status});
  final String? role;
  final String? status;

  @override
  bool operator ==(Object other) =>
      other is MatchListParams && other.role == role && other.status == status;

  @override
  int get hashCode => Object.hash(role, status);
}

final matchDetailProvider =
    FutureProvider.autoDispose.family<MatchSummary, int>((ref, id) async {
  return ref.read(matchingRepositoryProvider).detail(id);
});

final offerListProvider =
    FutureProvider.autoDispose.family<List<Offer>, int>((ref, matchId) async {
  return ref.read(matchingRepositoryProvider).offers(matchId);
});

final chatEligibilityProvider = FutureProvider.autoDispose
    .family<ChatEligibility, int>((ref, matchId) async {
  return ref.read(matchingRepositoryProvider).chatEligibility(matchId);
});
