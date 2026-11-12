/// One person's public page.
///
/// What the server publishes about somebody who opted in: a first name, the
/// trust summary, the routes they chose to show, and their live trips or open
/// requests. There is no message button. A viewer's only way to follow a person
/// is a **route alert**, because chat begins inside a match and nowhere else
/// (spec 4.4).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/discovery_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../data/discovery_repository.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/public_discovery.dart';
import '../../l10n/app_localizations.dart';
import '../common/traveler_candidate_card.dart';
import 'discovery_actions.dart';
import 'discovery_widgets.dart';

class PersonScreen extends ConsumerWidget {
  const PersonScreen({required this.profileId, super.key});

  final String profileId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final lookup = ref.watch(personProvider(profileId)).ofCurrentAccount;
    final error = lookup.error;
    final gone =
        !lookup.hasValue &&
        error is ApiException &&
        error.code == ApiErrorCode.profileNotFound;

    return AppScaffold(
      topBar: AppTopBar(title: l.personTitle, showBack: true),
      body: gone
          ? AppEmptyState(
              title: l.personGoneTitle,
              body: l.discoveryProfileGone,
              icon: Icons.person_off_outlined,
            )
          : DiscoverySection<PersonLookup>(
              value: lookup,
              onRetry: () => ref.invalidate(personProvider(profileId)),
              skeleton: ListView(
                padding: AppScrollPadding.page(context),
                children: const [SkeletonDetail()],
              ),
              data: (data) => switch (data) {
                PersonDisabled() => AppEmptyState(
                  title: l.discoveryProfilesOffTitle,
                  body: l.discoveryProfilesOff,
                  icon: Icons.pause_circle_outline_rounded,
                ),
                PersonFound(:final page) => RefreshIndicator(
                  onRefresh: () async =>
                      ref.invalidate(personProvider(profileId)),
                  child: _PersonBody(profileId: profileId, page: page),
                ),
              },
            ),
    );
  }
}

class _PersonBody extends ConsumerWidget {
  const _PersonBody({required this.profileId, required this.page});

  final String profileId;
  final PersonPage page;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final profile = page.profile;
    final name = profile.person.displayName;
    // A sender follows travelers' trips, a traveler follows senders' requests.
    final watches = ref.watch(roleContextProvider) == RoleContext.sender
        ? AlertWatch.trips
        : AlertWatch.requests;

    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: AppScrollPadding.page(context),
      children: [
        _PersonHeader(card: profile),
        SectionHeader(
          title: l.personUsualRoutes,
          subtitle: profile.usualRoutes.isEmpty
              ? null
              : l.personAlertHint(name),
        ),
        if (profile.usualRoutes.isEmpty)
          Text(
            l.personNoUsualRoutes(name),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.colors.textSecondary,
            ),
          )
        else
          for (final route in profile.usualRoutes)
            _RouteAlertRow(
              route: route,
              profileId: profileId,
              personName: name,
              watches: watches,
            ),
        if (page.trips.isNotEmpty) ...[
          SectionHeader(title: l.personTrips(name)),
          for (final trip in page.trips) ...[
            TripListingCard(
              card: trip,
              onTap: () => showTripPreview(context, trip),
            ),
            const SizedBox(height: AppSpace.md),
          ],
        ],
        if (page.requests.isNotEmpty) ...[
          SectionHeader(title: l.personRequests(name)),
          for (final request in page.requests) ...[
            RequestListingCard(
              card: request,
              onTap: () => showRequestPreview(context, request),
            ),
            const SizedBox(height: AppSpace.md),
          ],
        ],
        if (page.trips.isEmpty && page.requests.isEmpty) ...[
          const SizedBox(height: AppSpace.xl),
          InfoNotice(
            message: l.personNothingListed(name),
            icon: Icons.inbox_outlined,
          ),
        ],
      ],
    );
  }
}

class _PersonHeader extends StatelessWidget {
  const _PersonHeader({required this.card});

  final ProfileCard card;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final person = card.person;
    final since = card.memberSince;

    return AppCard(
      padding: const EdgeInsets.all(AppSpace.lg),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppAvatar(
            initials: travelerInitial(person.displayName),
            name: person.displayName,
            size: 56,
            isVerified: person.identityVerified,
          ),
          const SizedBox(width: AppSpace.lg),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  person.displayName,
                  style: text.titleLarge?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: AppSpace.xs),
                RatingOrNew(person: person, l: l),
                if (person.identityVerified) ...[
                  const SizedBox(height: AppSpace.sm),
                  Row(
                    children: [
                      Icon(Icons.verified_rounded, size: 16, color: c.success),
                      const SizedBox(width: AppSpace.xs),
                      Flexible(
                        child: Text(
                          l.findTravelersIdentityVerified,
                          style: text.labelMedium,
                        ),
                      ),
                    ],
                  ),
                ],
                if (person.completedDeliveries > 0) ...[
                  const SizedBox(height: AppSpace.xs),
                  Text(
                    l.findTravelersDeliveries(person.completedDeliveries),
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                  ),
                ],
                if (since != null) ...[
                  const SizedBox(height: AppSpace.xs),
                  Text(
                    l.profileMemberSince(
                      LocaleFormats.monthYear(locale, since),
                    ),
                    style: text.bodySmall?.copyWith(color: c.textTertiary),
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

/// A usual route with its alert switch. The switch reads the member's own
/// alerts, so it is on exactly when the server holds that alert.
class _RouteAlertRow extends ConsumerStatefulWidget {
  const _RouteAlertRow({
    required this.route,
    required this.profileId,
    required this.personName,
    required this.watches,
  });

  final UsualRoute route;
  final String profileId;
  final String personName;
  final AlertWatch watches;

  @override
  ConsumerState<_RouteAlertRow> createState() => _RouteAlertRowState();
}

class _RouteAlertRowState extends ConsumerState<_RouteAlertRow> {
  bool _busy = false;

  RouteAlert? _existing(List<RouteAlert> alerts) {
    final route = widget.route;
    return alerts
        .where(
          (a) =>
              a.subjectProfileId == widget.profileId &&
              a.watches == widget.watches &&
              a.origin.placeId == route.origin.placeId &&
              a.destination.placeId == route.destination.placeId,
        )
        .firstOrNull;
  }

  Future<void> _toggle(bool on, RouteAlert? existing) async {
    final l = L.of(context);
    setState(() => _busy = true);
    try {
      final repo = ref.read(discoveryRepositoryProvider);
      if (on) {
        await repo.createAlert(
          watches: widget.watches,
          originPlaceId: widget.route.origin.placeId,
          destinationPlaceId: widget.route.destination.placeId,
          subjectProfileId: widget.profileId,
        );
      } else if (existing != null) {
        await repo.deleteAlert(existing.id);
      }
      ref.invalidate(routeAlertsProvider);
      await ref.read(routeAlertsProvider.future);
      if (!mounted) return;
      AppSnack.success(context, on ? l.alertTurnedOn : l.alertTurnedOff);
    } on Object catch (error) {
      if (!mounted) return;
      AppSnack.failure(
        context,
        error,
        fallback: discoveryFailureMessage(context, error),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final alerts = ref.watch(routeAlertsProvider).ofCurrentAccount;
    final existing = alerts.hasValue ? _existing(alerts.requireValue) : null;
    final stops = placeStops([widget.route.origin, widget.route.destination]);

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.sm),
      child: AppCard(
        padding: const EdgeInsetsDirectional.only(
          start: AppSpace.md,
          end: AppSpace.xs,
        ),
        child: Row(
          children: [
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    InlineRoute(
                      stops: stops,
                      style: text.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: AppSpace.xs),
                    Text(
                      l.alertSwitchLabel,
                      style: text.bodySmall?.copyWith(color: c.textSecondary),
                    ),
                  ],
                ),
              ),
            ),
            if (alerts.hasError && !alerts.hasValue)
              TextButton(
                onPressed: () => ref.invalidate(routeAlertsProvider),
                child: Text(l.actionRetry),
              )
            else
              Semantics(
                label:
                    '${l.alertSwitchLabel}: '
                    '${routeSemanticLabel(stops: stops, locale: Localizations.localeOf(context))}',
                toggled: existing != null,
                child: Switch.adaptive(
                  value: existing != null,
                  onChanged: _busy || !alerts.hasValue
                      ? null
                      : (on) => _toggle(on, existing),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
