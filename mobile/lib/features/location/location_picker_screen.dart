/// Choosing a place.
///
/// One screen, two ways in, because the two are not alternatives — they answer
/// different questions. "Which of my addresses?" is a list; "where exactly is
/// this?" is a map. Splitting them across two routes would make the common
/// case (pick the address I already saved) cost a navigation, and the rare
/// case (add a new one) cost a dead end.
///
/// ## What the server sends back
///
/// `GET /api/locations` returns a **mixed** array: the caller's own rows carry
/// exact coordinates, the shared airports carry only the coarse public shape.
/// [AppLocation.isExact] is the only honest test for which is which, and it is
/// what the "Your places" / "Airports" split is built on — not `kind`, which
/// an own-row could also set to `airport`.
///
/// ## Why a coarse row is disabled rather than hidden
///
/// A delivery request needs a sender-owned exact location; the server refuses
/// anything else. Hiding the airports when [requireExact] is set would leave
/// a traveller who *does* use them wondering where they went, and a sender
/// with no saved address staring at an empty list with no explanation. The row
/// stays, greyed, with the reason attached.
///
/// ## What must never be sent
///
/// `public_label`, `coarse_latitude` and `coarse_longitude` are derived
/// server-side and rejected on the way in. [LocationRepository.create] already
/// omits them; nothing here adds them back.
library;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';

import '../../core/api/api_exception.dart';
import '../../core/env/app_config.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/location.dart';
import '../../l10n/app_localizations.dart';

/// The caller's saved places plus the shared airports.
///
/// Local to this screen: nothing else in the app reads the raw list, and a
/// picker that outlived its route would hand back a place the user has since
/// deleted.
final _savedPlacesProvider = FutureProvider.autoDispose<List<AppLocation>>((
  ref,
) async {
  final repo = ref.watch(locationRepositoryProvider);
  return repo.mine();
});

/// Where the map opens when the user has given us nothing to centre on.
///
/// The Algiers–Mediterranean frame, because it holds both ends of the corridor
/// this product actually serves at a zoom where either is one gesture away.
const _defaultCentre = LatLng(36.7538, 3.0588);
const _defaultZoom = 4.0;
const _minZoom = 2.0;
const _maxZoom = 18.0;

enum _Mode { saved, map }

class LocationPickerScreen extends ConsumerStatefulWidget {
  const LocationPickerScreen({
    this.title,
    this.requireExact = false,
    super.key,
  });

  /// What the caller is asking for — "Pickup address", "Where does this leg
  /// end?". Falls back to a generic title rather than being invented here.
  final String? title;

  /// True where the server needs a sender-owned exact location and will refuse
  /// a coarse one.
  final bool requireExact;

  @override
  ConsumerState<LocationPickerScreen> createState() =>
      _LocationPickerScreenState();
}

class _LocationPickerScreenState extends ConsumerState<LocationPickerScreen> {
  final _mapController = MapController();

  _Mode _mode = _Mode.saved;

  /// Mirrors the camera rather than reading it back off the controller, so the
  /// zoom buttons work before the map has ever emitted a position.
  LatLng _centre = _defaultCentre;
  double _zoom = _defaultZoom;

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  void _choose(AppLocation location) => context.pop(location);

  Future<void> _confirmPoint() async {
    final created = await showAppSheet<AppLocation>(
      context,
      builder: (sheetContext) => _SavePlaceSheet(point: _centre),
    );
    if (created == null || !mounted) return;
    _choose(created);
  }

  void _zoomBy(double delta) {
    final next = (_zoom + delta).clamp(_minZoom, _maxZoom);
    _mapController.move(_centre, next);
    setState(() => _zoom = next);
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final onMap = _mode == _Mode.map;

    return AppScaffold(
      topBar: AppTopBar(
        title: widget.title ?? l.locationSearchTitle,
        showBack: true,
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpace.gutter,
              AppSpace.lg,
              AppSpace.gutter,
              AppSpace.lg,
            ),
            child: AppSegmentedChoice<_Mode>(
              selected: _mode,
              onSelect: (value) => setState(() => _mode = value),
              options: [
                AppChoice(
                  value: _Mode.saved,
                  label: l.locationSaved,
                  icon: Icons.bookmark_border_rounded,
                ),
                AppChoice(
                  value: _Mode.map,
                  label: l.locationUseMap,
                  icon: Icons.map_outlined,
                ),
              ],
            ),
          ),
          Expanded(
            // Both panes stay alive: a user who checks their saved places and
            // comes back should find the map where they left it, not reset to
            // the default frame.
            child: IndexedStack(
              index: onMap ? 1 : 0,
              sizing: StackFit.expand,
              children: [
                _SavedPlacesPane(
                  requireExact: widget.requireExact,
                  hasFooter: onMap,
                  onPick: _choose,
                  onUseMap: () => setState(() => _mode = _Mode.map),
                ),
                _MapPane(
                  controller: _mapController,
                  onCameraChanged: (centre, zoom) {
                    _centre = centre;
                    _zoom = zoom;
                  },
                ),
              ],
            ),
          ),
        ],
      ),
      floating: onMap
          ? _MapControls(
              onZoomIn: () => _zoomBy(1),
              onZoomOut: () => _zoomBy(-1),
            )
          : null,
      footer: onMap
          ? Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  l.locationDropPinHelp,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: context.colors.textSecondary,
                  ),
                ),
                const SizedBox(height: AppSpace.md),
                AppButton(
                  label: l.locationConfirmPoint,
                  icon: Icons.place_outlined,
                  onPressed: _confirmPoint,
                ),
              ],
            )
          : null,
    );
  }
}

// ---------------------------------------------------------------------------
// Saved places
// ---------------------------------------------------------------------------

class _SavedPlacesPane extends ConsumerWidget {
  const _SavedPlacesPane({
    required this.requireExact,
    required this.hasFooter,
    required this.onPick,
    required this.onUseMap,
  });

  final bool requireExact;

  /// The sibling pane owns the footer, so this one has to pad for it too —
  /// both panes share one scaffold.
  final bool hasFooter;

  final void Function(AppLocation) onPick;
  final VoidCallback onUseMap;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final places = ref.watch(_savedPlacesProvider);
    final padding = hasFooter
        ? AppScrollPadding.pageWithFooter(context, top: 0)
        : AppScrollPadding.page(context, top: 0);

    return AsyncView<List<AppLocation>>(
      value: places,
      onRetry: () => ref.invalidate(_savedPlacesProvider),
      loading: () => ListView(
        padding: padding,
        children: const [SkeletonCardList(count: 3)],
      ),
      data: (all) {
        final mine = all.where((p) => p.isExact).toList(growable: false);
        final shared = all.where((p) => !p.isExact).toList(growable: false);

        if (all.isEmpty) {
          return ListView(
            padding: padding,
            children: [
              AppEmptyState(
                title: l.locationEmptyTitle,
                body: l.locationEmptyBody,
                icon: Icons.place_outlined,
                actionLabel: l.locationUseMap,
                onAction: onUseMap,
              ),
            ],
          );
        }

        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(_savedPlacesProvider),
          child: ListView(
            padding: padding,
            children: [
              if (requireExact) ...[
                InfoNotice(
                  message: l.locationExactRequiredNotice,
                  icon: Icons.lock_outline_rounded,
                ),
                const SizedBox(height: AppSpace.xl),
              ],

              if (mine.isNotEmpty) ...[
                SectionHeader(title: l.locationYourPlaces),
                for (final place in mine) ...[
                  _PlaceRow(place: place, onTap: () => onPick(place)),
                  const SizedBox(height: AppSpace.md),
                ],
                const SizedBox(height: AppSpace.lg),
              ],

              if (shared.isNotEmpty) ...[
                SectionHeader(title: l.locationAirports),
                for (final place in shared) ...[
                  _PlaceRow(
                    place: place,
                    // Kept visible and explained: a hidden option is a
                    // question the user cannot answer.
                    blockedReason: requireExact
                        ? l.locationExactRequiredRow
                        : null,
                    onTap: () => onPick(place),
                  ),
                  const SizedBox(height: AppSpace.md),
                ],
              ],
            ],
          ),
        );
      },
    );
  }
}

class _PlaceRow extends StatelessWidget {
  const _PlaceRow({
    required this.place,
    required this.onTap,
    this.blockedReason,
  });

  final AppLocation place;
  final VoidCallback onTap;

  /// Non-null disables the row and says why.
  final String? blockedReason;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final blocked = blockedReason != null;

    final secondary = place.isExact
        ? place.coarseLabel
        : (place.airportIata ?? place.coarseLabel);

    return Opacity(
      opacity: blocked ? 0.55 : 1,
      child: AppCard(
        onTap: blocked ? null : onTap,
        semanticLabel: blocked
            ? '${place.displayLabel}, $blockedReason'
            : place.displayLabel,
        child: Row(
          children: [
            Icon(
              place.isExact
                  ? Icons.home_outlined
                  : Icons.flight_takeoff_rounded,
              size: 20,
              color: blocked ? c.textTertiary : c.brand,
            ),
            const SizedBox(width: AppSpace.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    place.displayLabel,
                    style: text.titleSmall,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (secondary.isNotEmpty &&
                      secondary != place.displayLabel) ...[
                    const SizedBox(height: AppSpace.xxs),
                    Text(
                      secondary,
                      style: text.bodySmall?.copyWith(color: c.textSecondary),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                  if (blocked) ...[
                    const SizedBox(height: AppSpace.sm),
                    Text(
                      blockedReason!,
                      style: text.bodySmall?.copyWith(color: c.danger),
                    ),
                  ] else if (!place.isExact) ...[
                    const SizedBox(height: AppSpace.sm),
                    Text(
                      l.locationCityOnly,
                      style: text.bodySmall?.copyWith(color: c.textTertiary),
                    ),
                  ],
                ],
              ),
            ),
            if (!blocked) ...[
              const SizedBox(width: AppSpace.sm),
              Icon(
                context.isRtl
                    ? Icons.chevron_left_rounded
                    : Icons.chevron_right_rounded,
                size: 20,
                color: c.textTertiary,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------

class _MapPane extends StatelessWidget {
  const _MapPane({required this.controller, required this.onCameraChanged});

  final MapController controller;
  final void Function(LatLng centre, double zoom) onCameraChanged;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return Stack(
      children: [
        Positioned.fill(
          child: FlutterMap(
            mapController: controller,
            options: MapOptions(
              initialCenter: _defaultCentre,
              initialZoom: _defaultZoom,
              minZoom: _minZoom,
              maxZoom: _maxZoom,
              backgroundColor: c.surfaceSunken,
              // Rotation is off: a rotated map makes "the crosshair is on my
              // building" harder to judge, and buys nothing here.
              interactionOptions: const InteractionOptions(
                flags: InteractiveFlag.drag | InteractiveFlag.pinchZoom,
              ),
              onPositionChanged: (camera, _) =>
                  onCameraChanged(camera.center, camera.zoom),
            ),
            children: [
              // The tile source is a build-time define. OpenStreetMap's public
              // tiles keep V1 buildable without a credential, and swapping
              // MAP_TILE_URL / MAP_ATTRIBUTION at release is the same class of
              // step as swapping the payment keys — no code change here.
              TileLayer(
                urlTemplate: AppConfig.mapTileUrl,
                userAgentPackageName: AppConfig.mapUserAgent,
              ),
            ],
          ),
        ),

        // The crosshair, not a tap target. Asking for a precise tap on a phone
        // means asking for a precise tap under a thumb; moving the map under a
        // fixed reticle is both more accurate and reversible.
        Positioned.fill(
          child: IgnorePointer(
            child: Center(
              child: Semantics(
                label: l.locationConfirmPoint,
                child: const _Crosshair(),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _Crosshair extends StatelessWidget {
  const _Crosshair();

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return SizedBox(
      width: 34,
      height: 34,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: c.brand, width: 2),
              color: c.surface.withValues(alpha: 0.35),
            ),
          ),
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(shape: BoxShape.circle, color: c.brand),
          ),
        ],
      ),
    );
  }
}

/// Zoom controls and the tile attribution.
///
/// Attribution is a licensing obligation, so it is set in the same body style
/// as the rest of the app on an opaque chip, not shrunk into a watermark. It
/// lives in `AppScaffold(floating:)` with the buttons because that is the one
/// place that already clears the footer and the navigation inset.
class _MapControls extends StatelessWidget {
  const _MapControls({required this.onZoomIn, required this.onZoomOut});

  final VoidCallback onZoomIn;
  final VoidCallback onZoomOut;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        DecoratedBox(
          decoration: BoxDecoration(
            color: c.surface,
            borderRadius: AppRadius.rMd,
            border: Border.all(color: c.hairline),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AppIconButton(
                icon: Icons.add_rounded,
                label: l.mapZoomIn,
                onPressed: onZoomIn,
              ),
              Container(width: AppSpace.xxl, height: 1, color: c.hairline),
              AppIconButton(
                icon: Icons.remove_rounded,
                label: l.mapZoomOut,
                onPressed: onZoomOut,
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpace.md),
        DecoratedBox(
          decoration: BoxDecoration(
            color: c.surface,
            borderRadius: AppRadius.rSm,
            border: Border.all(color: c.hairline),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpace.sm,
              vertical: AppSpace.xs,
            ),
            child: Text(
              l.mapAttribution(AppConfig.mapAttribution),
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: c.textSecondary),
            ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Saving a dropped pin
// ---------------------------------------------------------------------------

/// Names the point the user chose and creates the Location.
///
/// The label the user types is sent as both `private_label` and
/// `normalized_label`: V1 has no geocoder, so there is no canonical form to
/// derive, and inventing one client-side would be a claim the app cannot back.
/// Normalisation stays a server concern for when geocoding lands.
class _SavePlaceSheet extends ConsumerStatefulWidget {
  const _SavePlaceSheet({required this.point});

  final LatLng point;

  @override
  ConsumerState<_SavePlaceSheet> createState() => _SavePlaceSheetState();
}

class _SavePlaceSheetState extends ConsumerState<_SavePlaceSheet> {
  final _formKey = GlobalKey<FormState>();
  final _label = TextEditingController();
  final _city = TextEditingController();
  final _country = TextEditingController();

  bool _busy = false;
  FieldErrorMap _fieldErrors = const FieldErrorMap.empty();

  static const _claimedFields = {
    'private_label',
    'normalized_label',
    'city',
    'country_code',
    'latitude',
    'longitude',
  };

  @override
  void dispose() {
    _label.dispose();
    _city.dispose();
    _country.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final l = L.of(context);
    setState(() {
      _busy = true;
      _fieldErrors = const FieldErrorMap.empty();
    });

    try {
      final label = _label.text.trim();
      final created = await ref
          .read(locationRepositoryProvider)
          .create(
            kind: LocationKind.mapPoint,
            normalizedLabel: label,
            privateLabel: label,
            city: _city.text.trim(),
            countryCode: _country.text.trim(),
            latitude: widget.point.latitude,
            longitude: widget.point.longitude,
            precision: LocationPrecision.approximate,
          );
      if (!mounted) return;
      ref.invalidate(_savedPlacesProvider);
      AppSnack.success(context, l.locationPlaceSaved);
      Navigator.of(context).pop(created);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _fieldErrors = FieldErrorMap.from(error));
      AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final validators = Validators.of(context);
    final unclaimed = _fieldErrors.unclaimed(_claimedFields);

    return AppSheet(
      title: l.locationNamePlaceTitle,
      subtitle: l.locationNamePlaceBody,
      footer: AppButton(
        label: l.locationSavePlace,
        isLoading: _busy,
        onPressed: _save,
      ),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (unclaimed.isNotEmpty) ...[
              InfoNotice(
                message: unclaimed.join('\n'),
                tone: StatusTone.bad,
                icon: Icons.error_outline_rounded,
              ),
              const SizedBox(height: AppSpace.lg),
            ],
            AppTextField(
              label: l.locationLabelField,
              controller: _label,
              hint: l.locationLabelHint,
              isRequired: true,
              enabled: !_busy,
              autofocus: true,
              textCapitalization: TextCapitalization.sentences,
              textInputAction: TextInputAction.next,
              validator: validators.required,
              errorText: _fieldErrors['private_label'],
            ),
            AppTextField(
              label: l.locationCityField,
              controller: _city,
              isRequired: true,
              enabled: !_busy,
              textCapitalization: TextCapitalization.words,
              textInputAction: TextInputAction.next,
              validator: validators.required,
              errorText: _fieldErrors['city'],
            ),
            AppTextField(
              label: l.locationCountryField,
              controller: _country,
              hint: l.locationCountryHint,
              isRequired: true,
              enabled: !_busy,
              maxLength: 2,
              textCapitalization: TextCapitalization.characters,
              textInputAction: TextInputAction.done,
              validator: (value) {
                final v = value?.trim() ?? '';
                if (v.isEmpty) return l.validationRequired;
                return v.length == 2 ? null : l.locationCountryInvalid;
              },
              errorText: _fieldErrors['country_code'],
              onSubmitted: (_) => _save(),
            ),
          ],
        ),
      ),
    );
  }
}
