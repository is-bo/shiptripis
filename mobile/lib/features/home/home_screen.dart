/// Home.
///
/// One question, asked well: **is anything waiting on me?**
///
/// Everything above the fold answers it. A user who opens this app is almost
/// never browsing — they are checking whether their parcel moved, or whether
/// the person carrying it needs something. So the first section is what needs
/// them, the second is what is already moving, and the third is the standing
/// context (their open requests, or the journeys they have posted).
///
/// Role changes emphasis, not identity. The same account can send and carry;
/// switching the role context reorders this screen and re-points the primary
/// action, and nothing else. There is no second account, no second inbox, and
/// no state that only exists in one role.
///
/// "Needs you" is assembled from server booleans — `awaiting_user_id`,
/// `can_submit_*`, `can_rate`, a deal status that needs funding. This screen
/// does not decide that something needs you; it reports that the server said
/// so.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/account.dart';
import '../../domain/deal.dart';
import '../../domain/journey.dart';
import '../../l10n/app_localizations.dart';
import '../common/delivery_card.dart';
import '../../core/format/locale_formats.dart';
import '../common/status_copy.dart';
import '../shell/app_shell.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final role = ref.watch(roleContextProvider);
    final canSwitch = ref.watch(canSwitchRoleProvider);

    if (account == null) {
      // The router guard makes this unreachable in practice; rendering a
      // skeleton rather than throwing keeps a race harmless.
      return const AppScaffold(body: SkeletonDetail());
    }

    final isSender = role == RoleContext.sender;

    return AppScaffold(
      topBar: AppTopBar(
        title: isSender ? l.homeSenderGreeting : l.homeTravelerGreeting,
        subtitle: account.fullName.isEmpty ? null : account.fullName,
        actions: const [NotificationBell()],
      ),
      body: RefreshIndicator(
        onRefresh: () async => refreshVolatileState(ref),
        child: ListView(
          padding: AppScrollPadding.pageWithFooter(context),
          children: [
            if (canSwitch) ...[
              _RoleSwitcher(role: role),
              const SizedBox(height: AppSpace.xl),
            ],

            if (!isSender && !account.isKycVerified) ...[
              _VerifyIdentityNotice(account: account),
              const SizedBox(height: AppSpace.xl),
            ],

            const _AttentionSection(),
            const SizedBox(height: AppSpace.xl),
            const _InProgressSection(),
            const SizedBox(height: AppSpace.xl),

            if (isSender)
              const _MyRequestsSection()
            else
              const _MyJourneysSection(),
          ],
        ),
      ),
      // The sun button. Home is the one authenticated screen with a single
      // unambiguous marquee action, which is exactly the ration the accent
      // was reserved for.
      footer: AppButton(
        label: isSender ? l.homeCreateRequest : l.homeCreateJourney,
        variant: AppButtonVariant.hero,
        icon: isSender ? Icons.add_rounded : Icons.flight_takeoff_rounded,
        onPressed: () => isSender
            ? context.openRequestCreate()
            : context.openJourneyCreate(),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Role
// ---------------------------------------------------------------------------

/// Switches which half of the product this account is looking at.
///
/// Presented as a two-up control rather than a hidden menu item: for an
/// account that does both, the current role changes what the primary button
/// does, and a control that changes the primary button should be visible next
/// to it.
class _RoleSwitcher extends ConsumerWidget {
  const _RoleSwitcher({required this.role});

  final RoleContext role;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Semantics(
      label: l.roleSwitchLabel,
      child: Container(
        padding: const EdgeInsets.all(4),
        decoration: BoxDecoration(
          color: c.surfaceSunken,
          borderRadius: AppRadius.rPill,
          border: Border.all(color: c.hairline),
        ),
        child: Row(
          children: [
            for (final option in RoleContext.values)
              Expanded(
                child: Semantics(
                  button: true,
                  selected: option == role,
                  label: option == RoleContext.sender
                      ? l.roleSender
                      : l.roleTraveler,
                  onTap: option == role
                      ? null
                      : () =>
                            ref.read(roleContextProvider.notifier).set(option),
                  child: ExcludeSemantics(
                    child: Material(
                      color: option == role
                          ? c.surfaceRaised
                          : Colors.transparent,
                      borderRadius: AppRadius.rPill,
                      child: InkWell(
                        borderRadius: AppRadius.rPill,
                        onTap: option == role
                            ? null
                            : () => ref
                                  .read(roleContextProvider.notifier)
                                  .set(option),
                        child: Container(
                          height: AppSpace.minTapTarget - 4,
                          alignment: Alignment.center,
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(
                                option == RoleContext.sender
                                    ? Icons.outbox_rounded
                                    : Icons.luggage_rounded,
                                size: 17,
                                color: option == role
                                    ? c.brand
                                    : c.textTertiary,
                              ),
                              const SizedBox(width: AppSpace.sm),
                              Text(
                                option == RoleContext.sender
                                    ? l.roleSender
                                    : l.roleTraveler,
                                style: text.labelLarge?.copyWith(
                                  color: option == role
                                      ? c.textPrimary
                                      : c.textSecondary,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _VerifyIdentityNotice extends StatelessWidget {
  const _VerifyIdentityNotice({required this.account});

  final Account account;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return InfoNotice(
      title: l.homeVerifyIdentityTitle,
      // `kyc_status` collapses "never submitted" and "expired" into one value,
      // so the copy says what to do rather than asserting which happened.
      message: account.kycStatus == KycStatus.pending
          ? l.kycPendingBody
          : l.homeVerifyIdentityBody,
      tone: account.kycStatus == KycStatus.pending
          ? StatusTone.waiting
          : StatusTone.action,
      icon: Icons.verified_user_outlined,
      actionLabel: account.kycStatus == KycStatus.pending
          ? null
          : l.kycStartAction,
      onAction: account.kycStatus == KycStatus.pending
          ? null
          : () => context.openKyc(),
    );
  }
}

// ---------------------------------------------------------------------------
// Needs you
// ---------------------------------------------------------------------------

class _AttentionSection extends ConsumerWidget {
  const _AttentionSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final items = ref.watch(attentionProvider);
    final deals = ref.watch(dealsProvider);

    // While the first load is in flight there is no honest answer to "does
    // anything need you", so the section shows its own shape rather than
    // claiming a calm inbox.
    if (deals.isLoading && !deals.hasValue) {
      return const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: ''),
          SkeletonCardList(count: 1),
        ],
      );
    }

    if (items.isEmpty) {
      return AppInsetGroup(
        child: Row(
          children: [
            Icon(
              Icons.check_circle_outline_rounded,
              size: 19,
              color: context.colors.success,
            ),
            const SizedBox(width: AppSpace.md),
            Expanded(
              child: Text(
                l.homeNothingNeedsYou,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
          ],
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.homeNeedsYourAction),
        for (final item in items) ...[
          _AttentionRow(item: item),
          const SizedBox(height: AppSpace.md),
        ],
      ],
    );
  }
}

class _AttentionRow extends StatelessWidget {
  const _AttentionRow({required this.item});

  final AttentionItem item;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final label = switch (item.reason) {
      AttentionReason.offerAwaitingYou => l.homeAttentionOfferAwaiting,
      AttentionReason.fundingRequired => l.homeAttentionFunding,
      AttentionReason.recipientRequired => l.homeAttentionRecipient,
      AttentionReason.revealPickupCode => l.homeAttentionRevealPickup,
      AttentionReason.submitPickupCode => l.homeAttentionSubmitPickup,
      AttentionReason.revealDeliveryCode => l.homeAttentionRevealDelivery,
      AttentionReason.submitDeliveryCode => l.homeAttentionSubmitDelivery,
      AttentionReason.ratingOpen => l.homeAttentionRating,
    };

    final icon = switch (item.reason) {
      AttentionReason.offerAwaitingYou => Icons.swap_horiz_rounded,
      AttentionReason.fundingRequired => Icons.credit_card_rounded,
      AttentionReason.recipientRequired => Icons.person_add_alt_rounded,
      AttentionReason.revealPickupCode ||
      AttentionReason.revealDeliveryCode => Icons.visibility_rounded,
      AttentionReason.submitPickupCode ||
      AttentionReason.submitDeliveryCode => Icons.dialpad_rounded,
      AttentionReason.ratingOpen => Icons.star_outline_rounded,
    };

    void open() {
      final matchId = item.matchId;
      final dealId = item.dealId;
      if (item.reason == AttentionReason.offerAwaitingYou && matchId != null) {
        context.openNegotiation(matchId);
        return;
      }
      if (dealId != null) context.openDeal(dealId);
    }

    return AppCard(
      onTap: open,
      accent: StatusTone.action,
      semanticLabel: label,
      child: Row(
        children: [
          Icon(icon, size: 20, color: c.attention),
          const SizedBox(width: AppSpace.md),
          Expanded(child: Text(label, style: text.titleSmall)),
          const SizedBox(width: AppSpace.sm),
          Icon(
            context.isRtl
                ? Icons.chevron_left_rounded
                : Icons.chevron_right_rounded,
            size: 20,
            color: c.textTertiary,
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// In progress
// ---------------------------------------------------------------------------

class _InProgressSection extends ConsumerWidget {
  const _InProgressSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final deals = ref.watch(dealsProvider);

    if (account == null) return const SizedBox.shrink();

    return AsyncView<List<Deal>>(
      value: deals,
      onRetry: () => ref.invalidate(dealsProvider),
      loading: () => const SkeletonCardList(count: 2),
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(dealsProvider),
      ),
      data: (all) {
        final active = all
            .where((d) => !d.status.isFinished)
            .toList(growable: false);
        if (active.isEmpty) return const SizedBox.shrink();

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(
              title: l.homeInProgress,
              actionLabel: active.length > 3 ? l.actionSeeAll : null,
              onAction: active.length > 3 ? () => context.goDeliveries() : null,
            ),
            for (final deal in active.take(3)) ...[
              DeliveryCard(
                deal: deal,
                viewerId: account.id,
                onTap: () => context.openDeal(deal.id),
              ),
              const SizedBox(height: AppSpace.md),
            ],
          ],
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// Standing context, per role
// ---------------------------------------------------------------------------

class _MyRequestsSection extends ConsumerWidget {
  const _MyRequestsSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final requests = ref.watch(myRequestsProvider);

    return AsyncView(
      value: requests,
      onRetry: () => ref.invalidate(myRequestsProvider),
      loading: () => const SkeletonCardList(count: 2),
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(myRequestsProvider),
      ),
      data: (all) {
        final live = all
            .where((r) => !r.status.isFinished)
            .toList(growable: false);

        if (live.isEmpty) {
          return AppEmptyState(
            title: l.homeEmptySenderTitle,
            body: l.homeEmptySenderBody,
            icon: Icons.outbox_rounded,
            compact: true,
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(
              title: l.deliveriesSenderSection,
              actionLabel: l.actionSeeAll,
              onAction: () => context.goDeliveries(),
            ),
            for (final request in live.take(3)) ...[
              _RequestRow(
                title: request.title,
                from: request.pickupLocation?.coarseLabel ?? '',
                to: request.deliveryLocation?.coarseLabel ?? '',
                status: requestStatusCopy(context, request.status),
                onTap: () => context.openRequest(request.id),
              ),
              const SizedBox(height: AppSpace.md),
            ],
          ],
        );
      },
    );
  }
}

class _RequestRow extends StatelessWidget {
  const _RequestRow({
    required this.title,
    required this.from,
    required this.to,
    required this.status,
    required this.onTap,
  });

  final String title;
  final String from;
  final String to;
  final StatusCopy status;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppCard(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: text.titleSmall,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: AppSpace.sm),
              StatusPill(
                label: status.label,
                tone: status.tone,
                icon: status.icon,
                compact: true,
              ),
            ],
          ),
          if (from.isNotEmpty && to.isNotEmpty) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              context.isRtl ? '$to ← $from' : '$from → $to',
              style: text.bodySmall?.copyWith(color: c.textSecondary),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ],
      ),
    );
  }
}

class _MyJourneysSection extends ConsumerWidget {
  const _MyJourneysSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final journeys = ref.watch(myJourneysProvider);

    return AsyncView(
      value: journeys,
      onRetry: () => ref.invalidate(myJourneysProvider),
      loading: () => const SkeletonCardList(count: 2),
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(myJourneysProvider),
      ),
      data: (all) {
        final live = all
            .where((j) => !j.status.isFinished)
            .toList(growable: false);

        if (live.isEmpty) {
          return AppEmptyState(
            title: l.homeEmptyTravelerTitle,
            body: l.homeEmptyTravelerBody,
            icon: Icons.luggage_rounded,
            compact: true,
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(
              title: l.deliveriesJourneysSection,
              actionLabel: l.actionSeeAll,
              onAction: () => context.goDeliveries(),
            ),
            for (final journey in live.take(3)) ...[
              _journeyCard(context, journey),
              const SizedBox(height: AppSpace.md),
            ],
          ],
        );
      },
    );
  }

  Widget _journeyCard(BuildContext context, Journey journey) {
    final locale = Localizations.localeOf(context);
    final departure = journey.firstDeparture;
    return JourneyCard(
      fromLabel: journey.startLocation?.coarseLabel ?? '',
      toLabel: journey.destinationLocation?.coarseLabel ?? '',
      status: journeyStatusCopy(context, journey.status),
      legCount: journey.legs.length,
      capacityKg: journey.narrowestCapacityKg,
      departureLabel: departure == null
          ? null
          : LocaleFormats.dateTime(locale, departure),
      legsNeedingProof: journey.legsNeedingProof.length,
      onTap: () => context.openJourney(journey.id),
    );
  }
}
