/// One delivery request, as its sender sees it.
///
/// The screen answers two questions in order: *is this actually live?* and
/// *what do I do next?* A request sitting at `awaiting_deposit` looks posted
/// but is invisible to every traveller, and that gap is the single most
/// expensive misunderstanding this surface can create — so the status leads,
/// the explanation is stated rather than implied, and the primary action is
/// whatever unblocks it.
///
/// The proposed reward is shown as an *intent*, never as a price. There is no
/// agreed number until an offer is accepted, and labelling it as one here
/// would make every later negotiation feel like a downgrade.
///
/// Actions are driven by [RequestStatus] alone. Cancellation in particular is
/// only offered where the parcel endpoint can serve it; once a Deal exists the
/// server answers `deal_cancellation_not_available`, and this screen explains
/// that rather than repeating the attempt.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/delivery_request.dart';
import '../../domain/location.dart';
import '../../domain/offer.dart';
import '../../domain/pricing.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../common/status_copy.dart';

final _requestPricingProvider =
    FutureProvider.autoDispose.family<RequestPricing, int>((ref, id) async {
  return ref.watch(requestRepositoryProvider).requestPricing(id);
});

class RequestDetailScreen extends ConsumerStatefulWidget {
  const RequestDetailScreen({required this.requestId, super.key});

  final int requestId;

  @override
  ConsumerState<RequestDetailScreen> createState() =>
      _RequestDetailScreenState();
}

class _RequestDetailScreenState extends ConsumerState<RequestDetailScreen> {
  bool _cancelling = false;

  /// A refusal that has to stay on screen. A toast is the wrong shape for
  /// "this cannot be cancelled here, and here is where it can".
  String? _blockedNotice;

  Future<void> _cancel(DeliveryRequest request) async {
    final l = L.of(context);

    final confirmed = await confirmAction(
      context,
      title: l.requestCancelConfirmTitle,
      body: l.requestCancelConfirmBody,
      confirmLabel: l.requestCancelAction,
      cancelLabel: l.actionNotNow,
      isDestructive: true,
    );
    if (!confirmed || !mounted) return;

    setState(() {
      _cancelling = true;
      _blockedNotice = null;
    });

    try {
      await ref.read(requestRepositoryProvider).cancel(request.id);
      if (!mounted) return;
      refreshVolatileState(ref);
      AppSnack.success(context, l.requestCancelled);
      context.pop();
    } on ApiException catch (error) {
      if (!mounted) return;

      // Both of these mean the request moved on while this screen was open.
      // Re-fetch so the buttons stop offering something the server refuses.
      if (error.code.impliesStaleClientState) refreshVolatileState(ref);

      final explanation = switch (error.code) {
        ApiErrorCode.dealCancellationNotAvailable => l.requestCancelViaDealBody,
        ApiErrorCode.parcelNotCancellable => l.requestCancelNotCancellableBody,
        _ => null,
      };

      if (explanation == null) {
        AppSnack.failure(context, error);
      } else {
        setState(() => _blockedNotice = explanation);
      }
    } finally {
      if (mounted) setState(() => _cancelling = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final request = ref.watch(requestDetailProvider(widget.requestId));

    return AppScaffold(
      topBar: AppTopBar(title: l.requestDetailTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async =>
            ref.invalidate(requestDetailProvider(widget.requestId)),
        child: AsyncView<DeliveryRequest>(
          value: request,
          onRetry: () =>
              ref.invalidate(requestDetailProvider(widget.requestId)),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonDetail()],
          ),
          data: (data) => _body(context, l, data),
        ),
      ),
      footer: request.value == null
          ? null
          : _footer(context, l, request.value!),
    );
  }

  Widget _body(BuildContext context, L l, DeliveryRequest request) {
    final locale = Localizations.localeOf(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final status = requestStatusCopy(context, request.status);

    final pickup = request.pickupLocation;
    final delivery = request.deliveryLocation;
    final reward = request.senderProposedReward;
    final declared = request.declaredValue;

    return ListView(
      padding: request.status.isFinished
          ? AppScrollPadding.page(context)
          : AppScrollPadding.pageWithFooter(context),
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: Text(request.title, style: text.headlineSmall)),
            const SizedBox(width: AppSpace.md),
            StatusPill(
              label: status.label,
              tone: status.tone,
              icon: status.icon,
              semanticPrefix: l.a11yStatusPrefix,
            ),
          ],
        ),
        const SizedBox(height: AppSpace.lg),

        if (_blockedNotice != null) ...[
          InfoNotice(
            title: l.cancelNotAllowedTitle,
            message: _blockedNotice!,
            tone: StatusTone.waiting,
            icon: Icons.info_outline_rounded,
          ),
          const SizedBox(height: AppSpace.lg),
        ],

        if (request.status == RequestStatus.awaitingDeposit) ...[
          InfoNotice(
            message: l.requestAwaitingDepositNotice,
            tone: StatusTone.action,
            icon: Icons.visibility_off_outlined,
          ),
          const SizedBox(height: AppSpace.lg),
        ],

        if (request.isTargeted) ...[
          InfoNotice(
            message: l.requestTargetedNotice,
            icon: Icons.person_outline_rounded,
          ),
          const SizedBox(height: AppSpace.lg),
        ],

        SectionHeader(title: l.requestRouteSection),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (pickup != null && delivery != null)
                RouteSummary(
                  from: _placeLabel(pickup),
                  to: _placeLabel(delivery),
                  style: text.titleMedium,
                ),
              if (pickup != null && !pickup.isExact) ...[
                const SizedBox(height: AppSpace.sm),
                Text(
                  l.locationHiddenUntilFunded,
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpace.xl),

        SectionHeader(title: l.requestParcelSection),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (request.description.isNotEmpty) ...[
                Text(request.description, style: text.bodyMedium),
                const SizedBox(height: AppSpace.md),
              ],
              DetailRow(
                label: l.requestCategory,
                value: Text(_categoryLabel(l, request.category)),
              ),
              DetailRow(
                label: l.requestWeight,
                value: Text(formatWeight(context, request.actualWeightKg)),
              ),
              if (request.hasDimensions)
                DetailRow(
                  label: l.requestDimensions,
                  value: Text(
                    formatDimensions(
                      context,
                      request.lengthCm,
                      request.widthCm,
                      request.heightCm,
                    ),
                  ),
                ),
              if (declared != null)
                DetailRow(
                  label: l.requestDeclaredValue,
                  value: MoneyText(
                    declared,
                    semanticPrefix: l.requestDeclaredValue,
                  ),
                ),
              DetailRow(
                label: l.requestFragile,
                value: Text(
                  request.fragile ? l.requestFragileYes : l.requestNotFragile,
                ),
                icon: request.fragile
                    ? Icons.warning_amber_rounded
                    : Icons.inventory_2_outlined,
              ),
              if (request.handlingNotes.isNotEmpty)
                DetailRow(
                  label: l.requestHandlingNotes,
                  value: Text(request.handlingNotes),
                ),
              // The required photograph of the item, shown rather than
              // counted. Phase 8F-B made one mandatory precisely so a
              // traveller can see what they are agreeing to carry, and a
              // requirement whose answer nobody can look at is not one.
              if (request.itemPhotoMediaId != null) ...[
                const SizedBox(height: AppSpace.md),
                _ItemPhoto(
                  requestId: request.id,
                  mediaId: request.itemPhotoMediaId!,
                ),
              ],
              // Anything beyond the required one is still only counted: the
              // media list carries an id, a type and a byte count, and each
              // URL costs its own signed round trip.
              if (request.media.length > 1)
                DetailRow(
                  label: l.requestPhotos,
                  value: Text(l.requestPhotoCount(request.media.length)),
                  icon: Icons.photo_library_outlined,
                ),
            ],
          ),
        ),
        const SizedBox(height: AppSpace.xl),

        SectionHeader(title: l.requestTimingSection),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (request.readyWindowStart != null &&
                  request.readyWindowEnd != null)
                DetailRow(
                  label: l.requestReadyWindow,
                  value: Text(
                    LocaleFormats.range(
                      locale,
                      request.readyWindowStart!,
                      request.readyWindowEnd!,
                    ),
                  ),
                ),
              if (request.deadlineAt != null)
                DetailRow(
                  label: l.requestDeadline,
                  value: Text(
                    LocaleFormats.dateTime(locale, request.deadlineAt!),
                  ),
                  emphasise: request.isExpired,
                ),
            ],
          ),
        ),
        const SizedBox(height: AppSpace.xl),

        if (reward != null) ...[
          SectionHeader(title: l.requestProposedReward),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                MoneyHero(
                  amount: reward,
                  label: l.requestProposedReward,
                  caption: l.requestRewardIsIntent,
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpace.xl),
        ],

        Builder(
          builder: (context) {
            final pricing = ref.watch(_requestPricingProvider(request.id)).asData?.value;
            final boostAmount = pricing?.boost.amount ?? request.boostEur;
            final isBoosted = boostAmount != null && boostAmount.isPositive;
            final canEditBoost = pricing?.actions.canEditBoost ?? false;

            if (!isBoosted && !canEditBoost) return const SizedBox.shrink();

            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SectionHeader(title: l.boostSectionTitle),
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (isBoosted) ...[
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              l.boostCurrentActive(boostAmount.format(locale)),
                              style: text.titleMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                                color: c.brand,
                              ),
                            ),
                            StatusPill(
                              label: l.boostSectionTitle,
                              tone: StatusTone.good,
                              icon: Icons.rocket_launch_rounded,
                              compact: true,
                            ),
                          ],
                        ),
                        const SizedBox(height: AppSpace.xs),
                        Text(
                          l.boostExplainer,
                          style: text.bodySmall?.copyWith(color: c.textSecondary),
                        ),
                        const SizedBox(height: AppSpace.md),
                      ] else ...[
                        Text(
                          l.boostExplainer,
                          style: text.bodySmall?.copyWith(color: c.textSecondary),
                        ),
                        const SizedBox(height: AppSpace.md),
                      ],
                      if (canEditBoost)
                        AppButton(
                          label: isBoosted ? l.boostEditAction : l.boostSectionTitle,
                          variant: isBoosted
                              ? AppButtonVariant.secondary
                              : AppButtonVariant.primary,
                          icon: Icons.rocket_launch_outlined,
                          onPressed: () => context.pushNamed(
                            Routes.requestBoost,
                            pathParameters: {'id': '${request.id}'},
                          ),
                        )
                      else if (isBoosted)
                        Text(
                          l.boostNotEditable,
                          style: text.bodySmall?.copyWith(color: c.textTertiary),
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpace.xl),
              ],
            );
          },
        ),

        _MatchesSection(requestId: request.id),

        if (request.status.isCancellableAsRequest) ...[
          const SizedBox(height: AppSpace.xxl),
          AppButton(
            label: l.requestCancelAction,
            variant: AppButtonVariant.destructive,
            icon: Icons.cancel_outlined,
            isLoading: _cancelling,
            onPressed: () => _cancel(request),
          ),
        ],
      ],
    );
  }

  Widget? _footer(BuildContext context, L l, DeliveryRequest request) =>
      switch (request.status) {
        RequestStatus.awaitingDeposit => AppButton(
          label: l.requestPayDepositAction,
          icon: Icons.account_balance_wallet_rounded,
          onPressed: () => context.openDeposit(request.id),
        ),
        RequestStatus.open => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AppButton(
              label: l.requestFindTravelers,
              icon: Icons.travel_explore_rounded,
              onPressed: () => context.openDiscovery(request.id),
            ),
            const SizedBox(height: AppSpace.sm),
            AppButton(
              label: l.boostTitle,
              variant: AppButtonVariant.secondary,
              icon: Icons.trending_up_rounded,
              onPressed: () => context.openBoost(request.id),
            ),
          ],
        ),
        _ => null,
      };

  String _placeLabel(AppLocation place) =>
      place.isExact ? place.displayLabel : place.coarseLabel;
}

// ---------------------------------------------------------------------------
// Matches
// ---------------------------------------------------------------------------

/// Travellers this request has been proposed to.
///
/// Shown at every status, including finished ones: "who did I approach and
/// what came of it" is exactly the question a sender asks about a request that
/// went nowhere.
class _MatchesSection extends ConsumerWidget {
  const _MatchesSection({required this.requestId});

  final int requestId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final matches = ref.watch(matchesProvider);

    if (account == null) return const SizedBox.shrink();

    return AsyncView<List<Match>>(
      value: matches,
      onRetry: () => ref.invalidate(matchesProvider),
      loading: () => const SkeletonCardList(count: 1),
      error: (error) => InlineFailure(
        error: error,
        onRetry: () => ref.invalidate(matchesProvider),
      ),
      data: (all) {
        final mine = all
            .where((m) => m.parcelId == requestId)
            .toList(growable: false);

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(title: l.requestMatchesSection),
            if (mine.isEmpty)
              AppEmptyState(
                title: l.requestNoMatchesYet,
                body: l.discoveryEmptyTravelersBody,
                icon: Icons.handshake_outlined,
                compact: true,
              )
            else
              for (final match in mine) ...[
                _MatchRow(match: match, viewerId: account.id),
                const SizedBox(height: AppSpace.md),
              ],
          ],
        );
      },
    );
  }
}

class _MatchRow extends StatelessWidget {
  const _MatchRow({required this.match, required this.viewerId});

  final Match match;
  final int viewerId;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final offer = match.latestOffer;
    final awaitsMe = match.awaitsViewer(viewerId);
    final copy = offer == null ? null : offerStatusCopy(context, offer.status);

    return AppCard(
      onTap: () => context.openNegotiation(match.id),
      accent: awaitsMe ? StatusTone.action : null,
      semanticLabel: match.counterpartyName(viewerId),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  match.counterpartyName(viewerId),
                  style: text.titleSmall,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (offer?.senderTotal != null) ...[
                  const SizedBox(height: AppSpace.xs),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          l.moneyYouPay,
                          style: text.bodySmall?.copyWith(
                            color: c.textSecondary,
                          ),
                        ),
                      ),
                      const SizedBox(width: AppSpace.md),
                      MoneyText(
                        offer!.senderTotal!,
                        semanticPrefix: l.moneyYouPay,
                        size: 14,
                        color: c.textSecondary,
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: AppSpace.sm),
          if (awaitsMe)
            StatusPill(
              label: l.offerAwaitingYou,
              tone: StatusTone.action,
              icon: Icons.reply_rounded,
              compact: true,
            )
          else if (copy != null)
            StatusPill(
              label: copy.label,
              tone: copy.tone,
              icon: copy.icon,
              compact: true,
            ),
        ],
      ),
    );
  }
}

String _categoryLabel(L l, ItemCategory category) => switch (category) {
  ItemCategory.documents => l.requestCategoryDocuments,
  ItemCategory.smallBox => l.requestCategorySmallBox,
  ItemCategory.electronics => l.requestCategoryElectronics,
  ItemCategory.clothing => l.requestCategoryClothing,
  ItemCategory.other || ItemCategory.unknown => l.requestCategoryOther,
};

/// The item photograph, fetched through a signed URL that expires in minutes.
///
/// The URL is asked for when the image is about to be drawn rather than
/// carried on the request payload, because a link that outlives the screen is
/// a link that has stopped working by the time anyone follows it.
class _ItemPhoto extends ConsumerWidget {
  const _ItemPhoto({required this.requestId, required this.mediaId});

  final int requestId;
  final int mediaId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final c = context.colors;
    final url = ref.watch(
      parcelPhotoUrlProvider((requestId: requestId, mediaId: mediaId)),
    );

    return Semantics(
      image: true,
      label: l.requestItemPhoto,
      child: ExcludeSemantics(
        child: ClipRRect(
          borderRadius: AppRadius.rMd,
          child: Container(
            height: 200,
            width: double.infinity,
            color: c.surfaceSunken,
            child: url.when(
              loading: () => const Center(
                child: SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
              // A photo that will not load is a fact worth stating plainly.
              // Retrying is one tap, because the usual cause is a signed URL
              // that expired while the screen sat open.
              error: (_, _) => Center(
                child: AppButton(
                  label: l.actionRetry,
                  variant: AppButtonVariant.tertiary,
                  icon: Icons.refresh_rounded,
                  expand: false,
                  onPressed: () => ref.invalidate(
                    parcelPhotoUrlProvider((
                      requestId: requestId,
                      mediaId: mediaId,
                    )),
                  ),
                ),
              ),
              data: (value) => Image.network(
                value,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => Center(
                  child: Icon(
                    Icons.image_not_supported_outlined,
                    color: c.textTertiary,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
