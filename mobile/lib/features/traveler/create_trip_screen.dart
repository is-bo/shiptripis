import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/media/media_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/trips/trips_providers.dart';
import '../../core/trips/trips_repository.dart';
import '../../shared/widgets/airport_picker.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/inline_calendar.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class CreateTripScreen extends ConsumerStatefulWidget {
  const CreateTripScreen({super.key});
  @override
  ConsumerState<CreateTripScreen> createState() => _CreateTripScreenState();
}

class _CreateTripScreenState extends ConsumerState<CreateTripScreen> {
  Airport? _origin;
  Airport? _dest;
  int _kg = 8;
  DateTime _date = DateTime.now().add(const Duration(days: 4));
  bool _showCalendar = false;
  final _accepted = <String>{"Documents", "Small box", "Clothing"};
  String? _ticketPath;
  String? _ticketName;
  int? _ticketBytes;
  final _flightCtl = TextEditingController(text: "AH 1004");
  bool _submitting = false;
  String? _error;

  Future<void> _pickTicket() async {
    final picker = ImagePicker();
    final picked = await picker.pickImage(
      source: ImageSource.gallery,
      maxWidth: 1800,
      imageQuality: 80,
    );
    if (picked == null) return;
    final f = File(picked.path);
    final size = await f.length();
    setState(() {
      _ticketPath = picked.path;
      _ticketName = picked.name;
      _ticketBytes = size;
    });
  }

  @override
  void dispose() {
    _flightCtl.dispose();
    super.dispose();
  }

  void _swapAirports() {
    setState(() {
      final tmp = _origin;
      _origin = _dest;
      _dest = tmp;
    });
  }

  Future<void> _pickAirport(bool isOrigin, List<Airport> airports) async {
    final cur = isOrigin ? _origin : _dest;
    final country = cur?.country ?? (isOrigin ? 'DZ' : 'FR');
    final picked = await showAirportPicker(
      context,
      airports: airports,
      country: country,
      currentIata: cur?.iata ?? '',
      onCountryChanged: (_) {},
    );
    if (picked == null) return;
    setState(() {
      if (isOrigin) {
        _origin = picked;
        if (_dest?.country == picked.country) _dest = null;
      } else {
        _dest = picked;
        if (_origin?.country == picked.country) _origin = null;
      }
    });
  }

  Future<void> _submit() async {
    if (_origin == null || _dest == null) {
      setState(() => _error = 'Choose origin and destination.');
      return;
    }
    if (_origin!.iata == _dest!.iata) {
      setState(() => _error = 'Origin and destination must differ.');
      return;
    }
    if (!_date.isAfter(DateTime.now())) {
      setState(() => _error = 'Departure must be in the future.');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final trip = await ref.read(myTripsProvider.notifier).create(
            originIata: _origin!.iata,
            destinationIata: _dest!.iata,
            departureAt: _date,
            capacityKg: _kg,
            flightNumber: _flightCtl.text.trim(),
          );
      if (_ticketPath != null) {
        try {
          await ref.read(mediaRepositoryProvider).uploadTripPhoto(
                tripId: trip.id,
                filePath: _ticketPath!,
                filename: _ticketName ?? 'ticket.jpg',
              );
        } on MediaFailure catch (e) {
          // Trip is created; surface but don't roll back.
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Trip saved. Photo: ${e.message}')),
            );
          }
        }
      }
      if (!mounted) return;
      context.pop();
    } on TripsFailure catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Network error. Check your connection.');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final airportsAsync = ref.watch(airportsProvider(null));
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: airportsAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.x6),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.cloud_off_rounded, size: 36, color: AppColors.inkMute),
                  const SizedBox(height: 12),
                  Text("Couldn't load airports.", style: AppType.body(14)),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: () => ref.invalidate(airportsProvider(null)),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
          ),
          data: (airports) {
            _origin ??= airports.firstWhere(
              (a) => a.country == 'DZ',
              orElse: () => airports.first,
            );
            _dest ??= airports.firstWhere(
              (a) => a.country == 'FR',
              orElse: () => airports.last,
            );
            return Column(
              children: [
                _topBar(),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(
                        AppSpacing.x6, AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
                    children: [
                      Text("New trip", style: AppType.eyebrow()),
                      const SizedBox(height: 6),
                      Text("List your\nnext flight.",
                          style: AppType.display(34, w: FontWeight.w400, height: 1)),
                      const SizedBox(height: AppSpacing.x6),
                      _routeBlock(airports),
                      const SizedBox(height: AppSpacing.x6),
                      _dateBlock(),
                      const SizedBox(height: AppSpacing.x6),
                      _flightAndCapacity(),
                      const SizedBox(height: AppSpacing.x6),
                      _acceptedTypes(),
                      const SizedBox(height: AppSpacing.x6),
                      _ticketUpload(),
                      if (_error != null) ...[
                        const SizedBox(height: AppSpacing.x4),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: AppColors.terracotta.withValues(alpha: 0.08),
                            borderRadius: BorderRadius.circular(AppRadius.md),
                            border: Border.all(color: AppColors.terracotta),
                          ),
                          child: Row(
                            children: [
                              const Icon(Icons.error_outline_rounded,
                                  color: AppColors.terracotta, size: 18),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(_error!,
                                    style: AppType.body(13,
                                        color: AppColors.terracottaDeep,
                                        w: FontWeight.w600)),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(
                      AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
                  child: PrimaryButton(
                    label: _submitting ? "Submitting…" : "Submit for review",
                    icon: Icons.flight_takeoff_rounded,
                    expand: true,
                    color: AppColors.emerald,
                    onTap: _submitting ? null : _submit,
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _topBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x4, AppSpacing.x4, AppSpacing.x4, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => context.pop(),
            icon: const Icon(Icons.arrow_back_rounded),
            style: IconButton.styleFrom(
              backgroundColor: AppColors.parchmentSoft,
              shape: const CircleBorder(),
            ),
          ),
          const Spacer(),
          const StampChip(label: "ADMIN APPROVAL · ~24H", color: AppColors.gold, angle: 0.04),
        ],
      ),
    );
  }

  Widget _routeBlock(List<Airport> airports) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text("ROUTE", style: AppType.eyebrow()),
          const SizedBox(height: 12),
          _AirportTile(
            label: "FROM",
            airport: _origin!,
            onTap: () => _pickAirport(true, airports),
          ),
          const SizedBox(height: 8),
          Center(
            child: GestureDetector(
              onTap: _swapAirports,
              child: Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: AppColors.ink,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
                child: const Icon(Icons.swap_vert_rounded,
                    color: AppColors.parchment, size: 20),
              ),
            ),
          ),
          const SizedBox(height: 8),
          _AirportTile(
            label: "TO",
            airport: _dest!,
            onTap: () => _pickAirport(false, airports),
          ),
        ],
      ),
    );
  }

  Widget _dateBlock() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("DEPARTURE DATE", style: AppType.eyebrow()),
        const SizedBox(height: 10),
        GestureDetector(
          onTap: () => setState(() => _showCalendar = !_showCalendar),
          child: Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
            decoration: BoxDecoration(
              color: AppColors.parchmentSoft,
              borderRadius: BorderRadius.circular(AppRadius.md),
              border: Border.all(color: AppColors.hairline, width: 1.2),
            ),
            child: Row(
              children: [
                const Icon(Icons.calendar_today_rounded,
                    size: 18, color: AppColors.ink),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(formatDate(_date),
                      style: AppType.mono(15, w: FontWeight.w700)),
                ),
                AnimatedRotation(
                  duration: AppDurations.fast,
                  turns: _showCalendar ? 0.5 : 0,
                  child: const Icon(Icons.expand_more_rounded,
                      color: AppColors.inkMute),
                ),
              ],
            ),
          ),
        ),
        AnimatedSize(
          duration: AppDurations.med,
          curve: kAppCurve,
          child: _showCalendar
              ? Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: InlineCalendar(
                    selected: _date,
                    onSelect: (d) => setState(() {
                      _date = d;
                      _showCalendar = false;
                    }),
                    minDate: DateTime.now(),
                    maxDate: DateTime.now().add(const Duration(days: 365)),
                  ),
                )
              : const SizedBox.shrink(),
        ),
      ],
    );
  }

  Widget _flightAndCapacity() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          flex: 5,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text("FLIGHT NUMBER", style: AppType.eyebrow()),
              const SizedBox(height: 8),
              AppInput(
                controller: _flightCtl,
                hint: "e.g. AH 1004",
                icon: Icons.confirmation_num_outlined,
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          flex: 6,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text("CAPACITY", style: AppType.eyebrow()),
              const SizedBox(height: 8),
              NumberStepper(
                value: _kg,
                onChanged: (v) => setState(() => _kg = v),
                min: 1,
                max: 25,
                unit: "kg",
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _acceptedTypes() {
    final types = ["Documents", "Small box", "Electronics", "Clothing"];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("ACCEPTED ITEMS", style: AppType.eyebrow()),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: types.map((t) {
            final selected = _accepted.contains(t);
            return GestureDetector(
              onTap: () => setState(() {
                selected ? _accepted.remove(t) : _accepted.add(t);
              }),
              child: AnimatedContainer(
                duration: AppDurations.fast,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: selected ? AppColors.emerald : AppColors.parchmentSoft,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                  border: Border.all(
                    color: selected ? AppColors.emerald : AppColors.hairline,
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      selected ? Icons.check_rounded : Icons.add_rounded,
                      size: 14,
                      color: selected ? AppColors.parchment : AppColors.inkMute,
                    ),
                    const SizedBox(width: 6),
                    Text(t,
                        style: AppType.body(12.5,
                            color: selected ? AppColors.parchment : AppColors.ink,
                            w: FontWeight.w600)),
                  ],
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }

  Widget _ticketUpload() {
    final attached = _ticketPath != null;
    final sub = attached
        ? '${_ticketName ?? "ticket"} · ${((_ticketBytes ?? 0) / 1024).toStringAsFixed(0)} KB'
        : 'Optional · photo (JPEG / PNG)';
    return GestureDetector(
      onTap: _pickTicket,
      child: AnimatedContainer(
        duration: AppDurations.med,
        padding: const EdgeInsets.all(AppSpacing.x4),
        decoration: BoxDecoration(
          color: attached ? AppColors.emerald.withValues(alpha: 0.08) : AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(
            color: attached ? AppColors.emerald : AppColors.hairline,
            width: 1.4,
          ),
        ),
        child: Row(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: attached
                    ? AppColors.emerald
                    : AppColors.ink.withValues(alpha: 0.06),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                attached ? Icons.check_rounded : Icons.upload_file_rounded,
                color: attached ? AppColors.parchment : AppColors.ink,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    attached ? 'Ticket attached' : 'Upload your boarding pass',
                    style: AppType.body(14.5, w: FontWeight.w700),
                  ),
                  Text(
                    sub,
                    style: AppType.body(12, color: AppColors.inkMute),
                  ),
                ],
              ),
            ),
            if (attached)
              IconButton(
                tooltip: 'Remove',
                onPressed: () => setState(() {
                  _ticketPath = null;
                  _ticketName = null;
                  _ticketBytes = null;
                }),
                icon: const Icon(Icons.close_rounded,
                    color: AppColors.inkMute),
              ),
          ],
        ),
      ),
    );
  }
}

class _AirportTile extends StatelessWidget {
  const _AirportTile({required this.label, required this.airport, required this.onTap});
  final String label;
  final Airport airport;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
        decoration: BoxDecoration(
          color: AppColors.parchment,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: AppColors.hairline, width: 1.2),
        ),
        child: Row(
          children: [
            CountryPill(code: airport.country, label: airport.country, dense: true),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(label, style: AppType.eyebrow()),
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                          color: AppColors.ink,
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(airport.iata,
                            style: AppType.mono(10,
                                color: AppColors.parchment, w: FontWeight.w700)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text("${airport.city} · ${airport.name}",
                      style: AppType.body(13, w: FontWeight.w600),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis),
                ],
              ),
            ),
            const Icon(Icons.unfold_more_rounded, color: AppColors.inkMute),
          ],
        ),
      ),
    );
  }
}
