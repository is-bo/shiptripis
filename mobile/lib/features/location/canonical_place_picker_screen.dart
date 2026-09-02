/// Choosing a canonical place: COUNTRY → PLACE.
///
/// The screen is deliberately two-part rather than two-screen. The country
/// strip stays pinned above the search for the whole session, so "I picked the
/// wrong country" is one tap rather than a back-navigation, and so the answer
/// to "which country am I searching?" is never off-screen. The search field is
/// pinned with it: a search box that scrolls away with its own results is the
/// single most common way a place picker stops feeling like a search.
///
/// It never downloads or caches the catalogue — every query is a bounded,
/// country-scoped request — and it ignores stale responses when typing
/// quickly, so a slow early keystroke cannot overwrite a fast late one.
///
/// What it does *not* do: explain matching. The catalogue's matching locality
/// is the server's business. A traveller choosing CDG is told it is an airport
/// near Paris; they are never told that CDG "resolves to" Paris, because that
/// is an implementation detail of compatibility, not a fact about their trip.
library;

import 'dart:async';

import 'package:country_flags/country_flags.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/place.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/canonical_place.dart';
import '../../l10n/app_localizations.dart';

/// The countries V1 serves. The catalogue can hold more; the product does not
/// offer more yet, and a country the corridor cannot service is worse than no
/// country at all.
const _launchCountries = {'DZ', 'FR', 'ES', 'DE'};

class CanonicalPlacePickerScreen extends ConsumerStatefulWidget {
  const CanonicalPlacePickerScreen({
    this.title,
    this.airportOnly = false,
    this.current,
    super.key,
  });

  final String? title;
  final bool airportOnly;

  /// What the caller already has, if they came back to change it. Preselects
  /// the country and marks the row, so re-entry resumes rather than restarts.
  final CanonicalPlace? current;

  @override
  ConsumerState<CanonicalPlacePickerScreen> createState() =>
      _CanonicalPlacePickerScreenState();
}

class _CanonicalPlacePickerScreenState
    extends ConsumerState<CanonicalPlacePickerScreen> {
  final _search = TextEditingController();
  final _searchFocus = FocusNode();
  Timer? _debounce;
  CancelToken? _cancelToken;
  List<GeographyCountry> _countries = const [];
  List<CanonicalPlace> _places = const [];
  String? _country;
  Object? _error;
  bool _loadingCountries = true;
  bool _loadingPlaces = false;
  int _requestGeneration = 0;

  @override
  void initState() {
    super.initState();
    // Resume where the caller left off rather than making them re-answer a
    // question they have already answered.
    _country = widget.current?.countryCode.toUpperCase();
    _loadCountries();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _cancelToken?.cancel();
    _search.dispose();
    _searchFocus.dispose();
    super.dispose();
  }

  Future<void> _loadCountries() async {
    setState(() {
      _loadingCountries = true;
      _error = null;
    });
    try {
      final rows = await ref.read(geographyRepositoryProvider).countries();
      if (!mounted) return;
      setState(() {
        _countries = rows
            .where((country) => _launchCountries.contains(country.code))
            .toList(growable: false);
        _loadingCountries = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loadingCountries = false;
        _error = error;
      });
    }
  }

  void _selectCountry(String code) {
    final changed = _country != code;
    _debounce?.cancel();
    _cancelToken?.cancel();
    if (changed) _search.clear();
    setState(() {
      _country = code;
      if (changed) {
        _places = const [];
        _error = null;
        _loadingPlaces = false;
      }
    });
    // Tapping a country is an unambiguous "now let me type". Opening the
    // keyboard here rather than on entry keeps the country strip readable on a
    // short screen until the moment it stops being the question.
    _searchFocus.requestFocus();
  }

  void _onSearchChanged(String value) {
    _debounce?.cancel();
    final country = _country;
    if (country == null) return;
    if (value.trim().isEmpty) {
      _cancelToken?.cancel();
      setState(() {
        _places = const [];
        _error = null;
        _loadingPlaces = false;
      });
      return;
    }
    setState(() {
      _loadingPlaces = true;
      _error = null;
    });
    _debounce = Timer(const Duration(milliseconds: 300), () {
      _searchPlaces(country, value.trim());
    });
  }

  Future<void> _searchPlaces(String country, String query) async {
    final generation = ++_requestGeneration;
    _cancelToken?.cancel();
    final token = CancelToken();
    _cancelToken = token;
    if (mounted) {
      setState(() {
        _loadingPlaces = true;
        _error = null;
      });
    }
    try {
      final rows = await ref
          .read(geographyRepositoryProvider)
          .searchPlaces(
            countryCode: country,
            query: query,
            airportOnly: widget.airportOnly,
            cancelToken: token,
          );
      if (!mounted || generation != _requestGeneration || token.isCancelled) {
        return;
      }
      setState(() {
        _places = rows;
        _loadingPlaces = false;
      });
    } catch (error) {
      if (!mounted || generation != _requestGeneration || token.isCancelled) {
        return;
      }
      setState(() {
        _loadingPlaces = false;
        _error = error;
      });
    }
  }

  void _retry() {
    if (_country == null) {
      _loadCountries();
    } else if (_search.text.trim().isNotEmpty) {
      _searchPlaces(_country!, _search.text.trim());
    }
  }

  /// Back to the country question. Everything downstream of a country is
  /// meaningless without it, so the query and its results go with it -- and
  /// the user is standing on the screen watching that happen, which is what
  /// makes it a visible reset rather than a silent one.
  void _clearCountry() {
    _debounce?.cancel();
    _cancelToken?.cancel();
    _search.clear();
    _searchFocus.unfocus();
    setState(() {
      _country = null;
      _places = const [];
      _error = null;
      _loadingPlaces = false;
    });
  }

  void _clearSearch() {
    _search.clear();
    _onSearchChanged('');
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return AppScaffold(
      topBar: AppTopBar(
        title: widget.title ?? l.locationSearchTitle,
        showBack: true,
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ?_header(l),
          Expanded(child: _country == null ? _countryStage(l) : _results(l)),
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Header
  // -------------------------------------------------------------------------

  /// Pinned only once a country is chosen.
  ///
  /// Four country pills do not fit one line on a mainstream phone, and a
  /// horizontally scrolled strip hides the fourth country behind a gesture
  /// nobody is told about. So the question gets the whole page while it is the
  /// question, and collapses to one compact row -- still naming the answer,
  /// still one tap from changing it -- the moment the question becomes "which
  /// place?". That row plus the search box is what has to survive a keyboard
  /// on a 320 dp phone, and it does.
  Widget? _header(L l) {
    if (_country == null) return null;

    final selected = _countries.where((c) => c.code == _country).firstOrNull;

    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpace.gutter,
        AppSpace.lg,
        AppSpace.gutter,
        AppSpace.md,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (selected != null) ...[
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: _SelectedCountryRow(
                code: selected.code,
                name: countryDisplayName(
                  l,
                  selected.code,
                  fallback: selected.name,
                ),
                onChange: _clearCountry,
              ),
            ),
            const SizedBox(height: AppSpace.md),
          ],
          TextField(
            controller: _search,
            focusNode: _searchFocus,
            onChanged: _onSearchChanged,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              hintText: widget.airportOnly
                  ? l.locationSearchHintAirports
                  : l.locationSearchHint,
              prefixIcon: const Icon(Icons.search_rounded),
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: l.actionClear,
                      onPressed: _clearSearch,
                      icon: const Icon(Icons.clear_rounded),
                    ),
            ),
          ),
          if (widget.airportOnly) ...[
            const SizedBox(height: AppSpace.sm),
            InfoNotice(
              message: l.locationAirportsOnly,
              icon: Icons.flight_rounded,
            ),
          ],
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Country stage
  // -------------------------------------------------------------------------

  Widget _countryStage(L l) {
    final padding = AppScrollPadding.page(context, top: 0);

    if (_loadingCountries) {
      return ListView(padding: padding, children: const [_CountrySkeleton()]);
    }

    if (_countries.isEmpty) {
      return ListView(
        padding: padding,
        children: [
          if (_error != null)
            AppErrorState(error: _error, onRetry: _retry)
          else
            InfoNotice(
              message: l.locationCountriesUnavailable,
              tone: StatusTone.waiting,
              icon: Icons.public_off_rounded,
            ),
        ],
      );
    }

    return ListView(
      padding: padding,
      children: [
        SectionHeader(
          title: l.locationCountryQuestion,
          subtitle: l.locationSelectCountryBody,
        ),
        // Wrapped, never scrolled sideways: every country the product serves
        // has to be visible without a gesture nobody was told about.
        Wrap(
          spacing: AppSpace.sm,
          runSpacing: AppSpace.sm,
          children: [
            for (final country in _countries)
              CountryChoiceTile(
                code: country.code,
                name: countryDisplayName(
                  l,
                  country.code,
                  fallback: country.name,
                ),
                selected: false,
                onTap: () => _selectCountry(country.code),
              ),
          ],
        ),
      ],
    );
  }

  // -------------------------------------------------------------------------
  // Results
  // -------------------------------------------------------------------------

  Widget _results(L l) {
    final padding = AppScrollPadding.page(context, top: 0);
    final query = _search.text.trim();

    if (_loadingPlaces) {
      return ListView(padding: padding, children: const [_ResultsSkeleton()]);
    }

    if (_error != null) {
      return ListView(
        padding: padding,
        children: [AppErrorState(error: _error, onRetry: _retry)],
      );
    }

    if (query.isEmpty) {
      final current = widget.current;
      return ListView(
        padding: padding,
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        children: [
          if (current != null &&
              current.countryCode.toUpperCase() == _country) ...[
            PlaceContextStrip(
              place: current,
              caption: l.locationCurrentSelection,
            ),
            const SizedBox(height: AppSpace.lg),
          ],
          AppEmptyState(
            title: l.locationSearchReadyTitle,
            body: widget.airportOnly
                ? l.locationSearchStartAirports
                : l.locationSearchStart,
            icon: Icons.travel_explore_rounded,
            compact: true,
          ),
        ],
      );
    }

    if (_places.isEmpty) {
      return ListView(
        padding: padding,
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        children: [
          AppEmptyState(
            title: l.locationSearchEmptyTitle,
            body: widget.airportOnly
                ? l.locationSearchNoMatchAirports(query)
                : l.locationSearchNoMatch(query),
            icon: Icons.search_off_rounded,
            compact: true,
          ),
        ],
      );
    }

    final currentId = widget.current?.id;
    return ListView.separated(
      padding: padding,
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      itemCount: _places.length,
      separatorBuilder: (_, _) => const SizedBox(height: AppSpace.sm),
      itemBuilder: (context, index) {
        final place = _places[index];
        return PlaceResultRow(
          place: place,
          selected: currentId != null && place.id == currentId,
          onTap: () => Navigator.of(context).pop(place),
        );
      },
    );
  }
}

/// The chosen country, restated and one tap from being reconsidered.
class _SelectedCountryRow extends StatelessWidget {
  const _SelectedCountryRow({
    required this.code,
    required this.name,
    required this.onChange,
  });

  final String code;
  final String name;
  final VoidCallback onChange;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Semantics(
      button: true,
      label: '$name, ${l.locationChangeCountry}',
      onTap: onChange,
      child: ExcludeSemantics(
        child: Material(
          color: c.surface,
          borderRadius: AppRadius.rPill,
          child: InkWell(
            onTap: onChange,
            borderRadius: AppRadius.rPill,
            child: Container(
              constraints: const BoxConstraints(
                minHeight: AppSpace.minTapTarget,
              ),
              padding: const EdgeInsetsDirectional.fromSTEB(
                AppSpace.md,
                AppSpace.sm,
                AppSpace.md,
                AppSpace.sm,
              ),
              decoration: BoxDecoration(
                borderRadius: AppRadius.rPill,
                border: Border.all(color: c.hairlineStrong),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(3),
                    child: SizedBox(
                      height: 16,
                      width: 24,
                      child: CountryFlag.fromCountryCode(code),
                    ),
                  ),
                  const SizedBox(width: AppSpace.sm),
                  Flexible(
                    child: Text(
                      name,
                      style: text.titleSmall,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  const SizedBox(width: AppSpace.md),
                  Icon(
                    Icons.swap_horiz_rounded,
                    size: 16,
                    color: c.textTertiary,
                  ),
                  const SizedBox(width: AppSpace.xs),
                  Text(
                    l.locationChangeCountry,
                    style: text.labelMedium?.copyWith(color: c.textSecondary),
                    maxLines: 1,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Loading shapes
// ---------------------------------------------------------------------------

/// Placeholder pills the width of a country name, so the answer lands where
/// the eye is already looking.
class _CountrySkeleton extends StatelessWidget {
  const _CountrySkeleton();

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return Semantics(
      label: l.a11yLoadingContent,
      liveRegion: true,
      child: const Padding(
        padding: EdgeInsets.only(top: AppSpace.xxl),
        child: Wrap(
          spacing: AppSpace.sm,
          runSpacing: AppSpace.sm,
          children: [
            _SkeletonPill(width: 116),
            _SkeletonPill(width: 104),
            _SkeletonPill(width: 96),
            _SkeletonPill(width: 118),
          ],
        ),
      ),
    );
  }
}

class _SkeletonPill extends StatelessWidget {
  const _SkeletonPill({required this.width});

  final double width;

  @override
  Widget build(BuildContext context) => SkeletonBox(
    width: width,
    height: AppSpace.minTapTarget,
    radius: AppRadius.rPill,
  );
}

/// The shape of a result row rather than a generic bar: a hairline progress
/// indicator over an empty page is a blank screen with a decoration on it.
class _ResultsSkeleton extends StatelessWidget {
  const _ResultsSkeleton();

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return Semantics(
      label: l.a11yLoadingContent,
      liveRegion: true,
      child: Column(
        children: [
          for (var i = 0; i < 4; i++) ...[
            if (i > 0) const SizedBox(height: AppSpace.sm),
            const AppCard(
              padding: EdgeInsets.all(AppSpace.md),
              child: Row(
                children: [
                  SkeletonBox(width: 38, height: 38, radius: AppRadius.rSm),
                  SizedBox(width: AppSpace.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SkeletonBox(width: 132, height: 13),
                        SizedBox(height: AppSpace.sm),
                        SkeletonBox(width: 84, height: 11),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
