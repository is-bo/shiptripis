/// The shared read model.
///
/// Every provider here is a projection of server state. None of them decides
/// anything: "needs your attention" is assembled from booleans and party ids
/// the API already published (`allowed_actions`, `awaiting_user_id`,
/// `can_submit_*`, `can_rate`), never from a rule reimplemented in Dart.
///
/// They are `autoDispose` on purpose. Capacity, money and lifecycle state go
/// stale the moment the app is backgrounded, and a provider that outlives its
/// screen is how a user ends up funding a deal against a price that moved. The
/// shell's `IndexedStack` keeps the four tabs mounted, so this costs no
/// refetch when switching tabs — only when a surface is genuinely left.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/session/session.dart';
import '../data/repositories.dart';
import '../domain/chat.dart';
import '../domain/deal.dart';
import '../domain/delivery_request.dart';
import '../domain/journey.dart';
import '../domain/offer.dart';
import '../domain/payment.dart';
import '../domain/rating.dart';

// ---------------------------------------------------------------------------
// Sender-side
// ---------------------------------------------------------------------------

final myRequestsProvider = FutureProvider.autoDispose<List<DeliveryRequest>>((
  ref,
) async {
  final repo = ref.watch(requestRepositoryProvider);
  return repo.mine();
});

final requestDetailProvider = FutureProvider.autoDispose
    .family<DeliveryRequest, int>((ref, id) async {
      final repo = ref.watch(requestRepositoryProvider);
      return repo.byId(id);
    });

final postingDepositProvider = FutureProvider.autoDispose
    .family<PostingDepositState, int>((ref, requestId) async {
      final repo = ref.watch(paymentRepositoryProvider);
      return repo.postingDeposit(requestId);
    });

// ---------------------------------------------------------------------------
// Traveller-side
// ---------------------------------------------------------------------------

final myJourneysProvider = FutureProvider.autoDispose<List<Journey>>((
  ref,
) async {
  final repo = ref.watch(journeyRepositoryProvider);
  return repo.mine();
});

final journeyDetailProvider = FutureProvider.autoDispose.family<Journey, int>((
  ref,
  id,
) async {
  final repo = ref.watch(journeyRepositoryProvider);
  return repo.byId(id);
});

/// The journeys a traveller can actually receive proposals on.
final activeJourneysProvider = Provider.autoDispose<List<Journey>>((ref) {
  final journeys = ref.watch(myJourneysProvider).value ?? const [];
  return journeys.where((j) => j.status.isLive).toList(growable: false);
});

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

final dealsProvider = FutureProvider.autoDispose<List<Deal>>((ref) async {
  final repo = ref.watch(dealRepositoryProvider);
  return repo.list();
});

final dealDetailProvider = FutureProvider.autoDispose.family<Deal, int>((
  ref,
  id,
) async {
  final repo = ref.watch(dealRepositoryProvider);
  return repo.byId(id);
});

final matchesProvider = FutureProvider.autoDispose<List<Match>>((ref) async {
  final repo = ref.watch(matchingRepositoryProvider);
  return repo.matches();
});

final matchDetailProvider = FutureProvider.autoDispose.family<Match, int>((
  ref,
  id,
) async {
  final repo = ref.watch(matchingRepositoryProvider);
  return repo.match(id);
});

final matchOffersProvider = FutureProvider.autoDispose.family<List<Offer>, int>(
  (ref, matchId) async {
    final repo = ref.watch(matchingRepositoryProvider);
    return repo.offers(matchId);
  },
);

final chatThreadsProvider = FutureProvider.autoDispose<List<ChatThread>>((
  ref,
) async {
  final repo = ref.watch(chatRepositoryProvider);
  return repo.threads();
});

final unreadNotificationsProvider = FutureProvider.autoDispose<int>((
  ref,
) async {
  final repo = ref.watch(notificationRepositoryProvider);
  return repo.unreadCount();
});

final payoutsProvider = FutureProvider.autoDispose<List<Payout>>((ref) async {
  final repo = ref.watch(paymentRepositoryProvider);
  return repo.payouts();
});

final receivedRatingsProvider = FutureProvider.autoDispose<List<Rating>>((
  ref,
) async {
  final repo = ref.watch(ratingRepositoryProvider);
  return repo.received();
});

final paymentProvidersProvider = FutureProvider.autoDispose<ProvidersView>((
  ref,
) async {
  final repo = ref.watch(paymentRepositoryProvider);
  return repo.providers();
});

// ---------------------------------------------------------------------------
// Derived: unread badges
// ---------------------------------------------------------------------------

final unreadChatCountProvider = Provider.autoDispose<int>((ref) {
  final threads = ref.watch(chatThreadsProvider).value ?? const [];
  var total = 0;
  for (final thread in threads) {
    total += thread.unreadCount;
  }
  return total;
});

// ---------------------------------------------------------------------------
// Derived: what needs this user
// ---------------------------------------------------------------------------

/// Why a delivery is sitting on this user's desk.
///
/// Each member maps to a server-published fact, named here so a screen can
/// order and explain them rather than showing an undifferentiated pile.
enum AttentionReason {
  /// An offer is waiting on this user's reply.
  offerAwaitingYou,

  /// A deal is accepted but unfunded, and this user is the sender.
  fundingRequired,

  /// The sender still has to record who receives the parcel.
  recipientRequired,

  /// The sender may reveal a code for the traveller to be given.
  revealPickupCode,

  /// The traveller may enter the pickup code.
  submitPickupCode,

  /// The delivery code is out of its buffer and the sender may reveal it.
  revealDeliveryCode,

  /// The traveller may enter the delivery code the recipient read to them.
  submitDeliveryCode,

  /// The rating window is open and this user has not rated.
  ratingOpen,
}

@immutable
class AttentionItem {
  const AttentionItem({
    required this.reason,
    required this.dealId,
    this.matchId,
    this.requestId,
  });

  final AttentionReason reason;
  final int? dealId;
  final int? matchId;
  final int? requestId;
}

/// Everything currently waiting on this user, assembled from server booleans.
///
/// Reads the deal **list**, which carries no `handover` block, plus whatever
/// detail is already in cache. It therefore surfaces the reasons it can see
/// and never invents the rest; a deal screen shows the full picture.
final attentionProvider = Provider.autoDispose<List<AttentionItem>>((ref) {
  final account = ref.watch(accountProvider);
  if (account == null) return const [];

  final items = <AttentionItem>[];

  for (final match in ref.watch(matchesProvider).value ?? const []) {
    if (match.awaitsViewer(account.id)) {
      items.add(
        AttentionItem(
          reason: AttentionReason.offerAwaitingYou,
          dealId: match.dealId,
          matchId: match.id,
          requestId: match.parcelId,
        ),
      );
    }
  }

  for (final deal in ref.watch(dealsProvider).value ?? const []) {
    final isSender = deal.isSender(account.id);

    if (deal.status.needsFunding && isSender) {
      items.add(
        AttentionItem(
          reason: AttentionReason.fundingRequired,
          dealId: deal.id,
          matchId: deal.matchId,
          requestId: deal.deliveryRequestId,
        ),
      );
      continue;
    }

    // The detail projection is richer; use it when this deal happens to be
    // loaded. Nothing here fabricates a permission the server did not send.
    final detail = ref.watch(dealDetailProvider(deal.id)).value;
    final handover = detail?.handover;
    if (handover != null) {
      if (handover.canRevealDeliveryCode) {
        items.add(
          AttentionItem(
            reason: AttentionReason.revealDeliveryCode,
            dealId: deal.id,
          ),
        );
      } else if (handover.canSubmitDeliveryCode) {
        items.add(
          AttentionItem(
            reason: AttentionReason.submitDeliveryCode,
            dealId: deal.id,
          ),
        );
      } else if (handover.canSubmitPickupCode) {
        items.add(
          AttentionItem(
            reason: AttentionReason.submitPickupCode,
            dealId: deal.id,
          ),
        );
      } else if (handover.canRevealPickupCode) {
        items.add(
          AttentionItem(
            reason: AttentionReason.revealPickupCode,
            dealId: deal.id,
          ),
        );
      }
    }

    final ratings = detail?.ratings;
    if (ratings != null && ratings.canRate && !ratings.submitted) {
      items.add(
        AttentionItem(reason: AttentionReason.ratingOpen, dealId: deal.id),
      );
    }
  }

  return items;
});

// ---------------------------------------------------------------------------
// Refresh on resume
// ---------------------------------------------------------------------------

/// Invalidates the volatile read model whenever the app comes back to the
/// foreground.
///
/// Mounted once, above the router. Deliberately blunt: the alternative is each
/// screen remembering to re-fetch, which is the kind of thing that is right in
/// eight places and wrong in the ninth — and the ninth is a delivery-code
/// countdown.
class ResumeRefresher extends ConsumerStatefulWidget {
  const ResumeRefresher({required this.child, super.key});

  final Widget child;

  @override
  ConsumerState<ResumeRefresher> createState() => _ResumeRefresherState();
}

class _ResumeRefresherState extends ConsumerState<ResumeRefresher>
    with WidgetsBindingObserver {
  /// A provider redirect leaves and returns within seconds and still needs
  /// fresh state, so the only absence worth ignoring is one with no gap at
  /// all — a transient `inactive` flicker rather than a real departure.
  static const _ignoreShorterThan = Duration(seconds: 1);

  DateTime? _leftAt;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
        _leftAt = DateTime.now();
      case AppLifecycleState.resumed:
        _onResumed();
      case AppLifecycleState.inactive:
      case AppLifecycleState.detached:
        break;
    }
  }

  void _onResumed() {
    final away = _leftAt;
    _leftAt = null;

    if (away != null && DateTime.now().difference(away) < _ignoreShorterThan) {
      return;
    }

    refreshVolatileState(ref);
    unawaited(ref.read(sessionProvider.notifier).refreshAccount());
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// Drops every cached projection of server state.
///
/// Also called after any mutation that can move a deal — funding, a handover
/// submission, a cancellation — so the next read is authoritative rather than
/// optimistic.
void refreshVolatileState(WidgetRef ref) {
  ref
    ..invalidate(dealsProvider)
    ..invalidate(dealDetailProvider)
    ..invalidate(matchesProvider)
    ..invalidate(matchDetailProvider)
    ..invalidate(matchOffersProvider)
    ..invalidate(myRequestsProvider)
    ..invalidate(requestDetailProvider)
    ..invalidate(myJourneysProvider)
    ..invalidate(journeyDetailProvider)
    ..invalidate(chatThreadsProvider)
    ..invalidate(unreadNotificationsProvider)
    ..invalidate(postingDepositProvider)
    ..invalidate(payoutsProvider);
}
