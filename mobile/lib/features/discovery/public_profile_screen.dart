/// Profile → Public profile.
///
/// Public profiles are **off by default** (spec 4.3). This screen is where the
/// choice lives and where it can be changed at any time. Above the switch it
/// says in plain words what turning it on shows, and below it the member sees
/// the very card other people would see — the server's own answer, never a
/// local imitation — so consent is informed rather than assumed.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/discovery_state.dart';
import '../../app/router.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/public_discovery.dart';
import '../../l10n/app_localizations.dart';
import 'discovery_actions.dart';
import 'discovery_widgets.dart';

/// The most usual routes a profile can show. The server enforces the same
/// limit; the client uses it only to stop offering "Add" at the ceiling.
const maxUsualRoutes = 3;

class PublicProfileScreen extends ConsumerStatefulWidget {
  const PublicProfileScreen({super.key});

  @override
  ConsumerState<PublicProfileScreen> createState() =>
      _PublicProfileScreenState();
}

class _PublicProfileScreenState extends ConsumerState<PublicProfileScreen> {
  bool _busy = false;

  Future<void> _write(
    Future<void> Function(OwnProfileController c) action,
  ) async {
    setState(() => _busy = true);
    try {
      await action(ref.read(ownProfileProvider.notifier));
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

  Future<PlaceRef?> _pickCity(String title) async {
    final place = await context.pickCanonicalPlace(title: title);
    return place == null ? null : PlaceRef.fromCanonical(place);
  }

  Future<void> _addRoute(OwnProfile profile) async {
    final l = L.of(context);
    final origin = await _pickCity(l.publicRouteFrom);
    if (origin == null || !mounted) return;
    final destination = await _pickCity(l.publicRouteTo);
    if (destination == null || !mounted) return;
    await _write(
      (controller) => controller.setUsualRoutes([
        for (final route in profile.usualRoutes)
          (
            originPlaceId: route.origin.placeId,
            destinationPlaceId: route.destination.placeId,
          ),
        (
          originPlaceId: origin.placeId,
          destinationPlaceId: destination.placeId,
        ),
      ]),
    );
  }

  Future<void> _removeRoute(OwnProfile profile, int index) => _write(
    (controller) => controller.setUsualRoutes([
      for (final (i, route) in profile.usualRoutes.indexed)
        if (i != index)
          (
            originPlaceId: route.origin.placeId,
            destinationPlaceId: route.destination.placeId,
          ),
    ]),
  );

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final profile = ref.watch(ownProfileProvider);

    return AppScaffold(
      topBar: AppTopBar(title: l.publicProfileTitle, showBack: true),
      body: DiscoverySection<OwnProfile>(
        value: profile,
        onRetry: () => ref.invalidate(ownProfileProvider),
        skeleton: ListView(
          padding: AppScrollPadding.page(context),
          children: const [SkeletonDetail()],
        ),
        data: (data) => data.state == OwnProfileState.disabled
            ? AppEmptyState(
                title: l.discoveryProfilesOffTitle,
                body: l.discoveryProfilesOff,
                icon: Icons.pause_circle_outline_rounded,
              )
            : _content(context, data),
      ),
    );
  }

  Widget _content(BuildContext context, OwnProfile profile) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final hidden = profile.state == OwnProfileState.hidden;
    final visible = profile.state == OwnProfileState.visible;

    return ListView(
      padding: AppScrollPadding.page(context),
      children: [
        Text(
          l.publicProfileIntro,
          style: text.bodyMedium?.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: AppSpace.lg),
        _Visibility(
          title: l.publicShownTitle,
          icon: Icons.visibility_outlined,
          items: [
            l.publicShownFirstName,
            l.publicShownTrust,
            l.publicShownMemberSince,
            l.publicShownRoutes,
          ],
        ),
        const SizedBox(height: AppSpace.md),
        _Visibility(
          title: l.publicNeverTitle,
          icon: Icons.visibility_off_outlined,
          items: [l.publicNeverContact, l.publicNeverPlaces],
        ),
        const SizedBox(height: AppSpace.xl),
        AppCard(
          padding: const EdgeInsetsDirectional.only(
            start: AppSpace.lg,
            end: AppSpace.sm,
            top: AppSpace.xs,
            bottom: AppSpace.xs,
          ),
          // A ListTile paints on the nearest Material, and the card's own
          // decoration would hide its ink; a transparent Material gives it one.
          child: Material(
            type: MaterialType.transparency,
            child: SwitchListTile.adaptive(
              contentPadding: EdgeInsets.zero,
              title: Text(l.publicShowSwitch),
              subtitle: Text(
                profile.isDiscoverable ? l.publicSwitchOn : l.publicSwitchOff,
              ),
              value: profile.isDiscoverable,
              onChanged: _busy
                  ? null
                  : (value) => _write((ctl) => ctl.setDiscoverable(value)),
            ),
          ),
        ),
        if (hidden) ...[
          const SizedBox(height: AppSpace.md),
          InfoNotice(
            message: l.publicHiddenNotice,
            icon: Icons.info_outline_rounded,
          ),
        ],
        SectionHeader(title: l.publicRoutesTitle, subtitle: l.publicRoutesHint),
        for (final (index, route) in profile.usualRoutes.indexed)
          Padding(
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
                      padding: const EdgeInsets.symmetric(
                        vertical: AppSpace.md,
                      ),
                      child: InlineRoute(
                        stops: placeStops([route.origin, route.destination]),
                        style: text.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                  AppIconButton(
                    icon: Icons.delete_outline_rounded,
                    label: l.publicRouteRemove(
                      '${route.origin.label} → ${route.destination.label}',
                    ),
                    onPressed: _busy
                        ? null
                        : () => _removeRoute(profile, index),
                  ),
                ],
              ),
            ),
          ),
        if (profile.usualRoutes.length < maxUsualRoutes)
          AppButton(
            label: l.publicRouteAdd,
            icon: Icons.add_rounded,
            variant: AppButtonVariant.tertiary,
            isLoading: _busy,
            onPressed: _busy ? null : () => _addRoute(profile),
          )
        else
          Text(
            l.publicRoutesLimit,
            style: text.bodySmall?.copyWith(color: c.textTertiary),
          ),
        SectionHeader(
          title: l.publicPreviewTitle,
          subtitle: visible ? l.publicPreviewVisible : l.publicPreviewHidden,
        ),
        ProfileTile(card: profile.card, width: null, onTap: null),
      ],
    );
  }
}

/// A short, titled list of what a public profile shows or never shows.
class _Visibility extends StatelessWidget {
  const _Visibility({
    required this.title,
    required this.icon,
    required this.items,
  });

  final String title;
  final IconData icon;
  final List<String> items;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    return Semantics(
      container: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: c.textSecondary),
              const SizedBox(width: AppSpace.sm),
              Flexible(
                child: Text(
                  title,
                  style: text.labelLarge?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpace.xs),
          for (final item in items)
            Padding(
              padding: const EdgeInsetsDirectional.only(
                start: 26,
                top: 2,
                bottom: 2,
              ),
              child: Text(
                item,
                style: text.bodyMedium?.copyWith(color: c.textSecondary),
              ),
            ),
        ],
      ),
    );
  }
}
