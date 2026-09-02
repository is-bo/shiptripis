/// Choosing an optional exact point inside an already selected canonical place.
///
/// Saved points are limited to this catalogue place; the map can create a new
/// preferred point only after provider context has been checked by the server.
///
/// ## What the server sends back
///
/// `GET /api/locations` remains a mixed privacy-aware collection, but this
/// screen filters it to owner-visible exact rows whose `canonical_place` is the
/// selected place. Coarse shared rows are not preferred meeting points.
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
import '../../design/components/place.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/canonical_place.dart';
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
    required this.canonicalPlace,
    this.title,
    super.key,
  });

  final CanonicalPlace canonicalPlace;

  /// What the caller is asking for — "Pickup address", "Where does this leg
  /// end?". Falls back to a generic title rather than being invented here.
  final String? title;

  @override
  ConsumerState<LocationPickerScreen> createState() =>
      _LocationPickerScreenState();
}

class _LocationPickerScreenState extends ConsumerState<LocationPickerScreen> {
  final _mapController = MapController();

  _Mode _mode = _Mode.map;

  /// Mirrors the camera rather than reading it back off the controller, so the
  /// zoom buttons work before the map has ever emitted a position.
  LatLng _centre = _defaultCentre;
  double _zoom = _defaultZoom;

  @override
  void initState() {
    super.initState();
    final latitude = widget.canonicalPlace.latitude;
    final longitude = widget.canonicalPlace.longitude;
    if (latitude != null && longitude != null) {
      _centre = LatLng(latitude, longitude);
      _zoom = widget.canonicalPlace.isAirport ? 12 : 11;
    }
  }

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  void _choose(AppLocation location) => context.pop(location);

  Future<void> _confirmPoint() async {
    final created = await showAppSheet<AppLocation>(
      context,
      builder: (sheetContext) => _SavePlaceSheet(
        point: _centre,
        canonicalPlace: widget.canonicalPlace,
      ),
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
    final place = widget.canonicalPlace;
    final hasCentre = place.latitude != null && place.longitude != null;

    return AppScaffold(
      // Not "Choose a place": the place is already chosen. This screen only
      // narrows a point inside it, and a title that says otherwise is exactly
      // the old feeling that the map defines the city.
      topBar: AppTopBar(
        title: widget.title ?? l.locationPreferredMeetingPoint,
        showBack: true,
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpace.gutter,
              AppSpace.lg,
              AppSpace.gutter,
              AppSpace.md,
            ),
            // The selected locality, restated and kept on screen. Without it
            // the map is an unbounded world and the user cannot tell that
            // their choice is constrained — or to what.
            child: PlaceContextStrip(
              place: place,
              caption: l.locationPointInside,
            ),
          ),
          if (!hasCentre)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpace.gutter,
                0,
                AppSpace.gutter,
                AppSpace.md,
              ),
              child: InfoNotice(
                message: l.locationNoCentre(place.name),
                tone: StatusTone.waiting,
                icon: Icons.explore_off_outlined,
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpace.gutter,
              0,
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
                  canonicalPlaceId: widget.canonicalPlace.id,
                  hasFooter: onMap,
                  onPick: _choose,
                  onUseMap: () => setState(() => _mode = _Mode.map),
                ),
                _MapPane(
                  controller: _mapController,
                  initialCentre: _centre,
                  initialZoom: _zoom,
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
                  l.locationDropPinHelpIn(place.name),
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
                // An exact point is optional, so leaving without one has to be
                // an offered move rather than something the user works out
                // from the back arrow.
                AppButton(
                  label: l.locationDecideLater,
                  variant: AppButtonVariant.tertiary,
                  onPressed: () => context.pop(),
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
    required this.canonicalPlaceId,
    required this.hasFooter,
    required this.onPick,
    required this.onUseMap,
  });

  final int canonicalPlaceId;

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
        final mine = all
            .where(
              (place) =>
                  place.isExact && place.canonicalPlaceId == canonicalPlaceId,
            )
            .toList(growable: false);

        if (mine.isEmpty) {
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
              if (mine.isNotEmpty) ...[
                SectionHeader(title: l.locationYourPlaces),
                for (final place in mine) ...[
                  _PlaceRow(place: place, onTap: () => onPick(place)),
                  const SizedBox(height: AppSpace.md),
                ],
                const SizedBox(height: AppSpace.lg),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _PlaceRow extends StatelessWidget {
  const _PlaceRow({required this.place, required this.onTap});

  final AppLocation place;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final secondary = place.isExact
        ? place.coarseLabel
        : (place.airportIata ?? place.coarseLabel);

    return AppCard(
      onTap: onTap,
      semanticLabel: place.displayLabel,
      child: Row(
        children: [
          Icon(
            place.isExact ? Icons.home_outlined : Icons.flight_takeoff_rounded,
            size: 20,
            color: c.brand,
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
              ],
            ),
          ),
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
// Map
// ---------------------------------------------------------------------------

class _MapPane extends StatelessWidget {
  const _MapPane({
    required this.controller,
    required this.initialCentre,
    required this.initialZoom,
    required this.onCameraChanged,
  });

  final MapController controller;
  final LatLng initialCentre;
  final double initialZoom;
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
              initialCenter: initialCentre,
              initialZoom: initialZoom,
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
/// The label is a private note only. The server reverse-geocodes the selected
/// coordinate through the existing provider abstraction and rejects a point
/// whose country/locality context cannot be confirmed against [canonicalPlace].
class _SavePlaceSheet extends ConsumerStatefulWidget {
  const _SavePlaceSheet({required this.point, required this.canonicalPlace});

  final LatLng point;
  final CanonicalPlace canonicalPlace;

  @override
  ConsumerState<_SavePlaceSheet> createState() => _SavePlaceSheetState();
}

class _SavePlaceSheetState extends ConsumerState<_SavePlaceSheet> {
  final _formKey = GlobalKey<FormState>();
  final _label = TextEditingController();

  bool _busy = false;
  FieldErrorMap _fieldErrors = const FieldErrorMap.empty();

  static const _claimedFields = {
    'private_label',
    'normalized_label',
    'canonical_place',
    'latitude',
    'longitude',
  };

  @override
  void dispose() {
    _label.dispose();
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
            city:
                widget.canonicalPlace.matchingLocalityName ??
                widget.canonicalPlace.name,
            region: widget.canonicalPlace.parentName,
            countryCode: widget.canonicalPlace.countryCode,
            latitude: widget.point.latitude,
            longitude: widget.point.longitude,
            precision: LocationPrecision.approximate,
            canonicalPlaceId: widget.canonicalPlace.id,
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
            InfoNotice(
              message: l.locationPreferredValidation(
                widget.canonicalPlace.name,
              ),
              icon: Icons.verified_outlined,
            ),
          ],
        ),
      ),
    );
  }
}
