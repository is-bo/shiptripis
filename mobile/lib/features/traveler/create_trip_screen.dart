import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/mock/airports.dart';
import '../../shared/widgets/airport_picker.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/country_pill.dart';
import '../../shared/widgets/inline_calendar.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class CreateTripScreen extends StatefulWidget {
  const CreateTripScreen({super.key});
  @override
  State<CreateTripScreen> createState() => _CreateTripScreenState();
}

class _CreateTripScreenState extends State<CreateTripScreen> {
  Airport _origin = dzAirports.first; // ALG
  Airport _dest = frAirports.first; // CDG
  int _kg = 8;
  DateTime _date = DateTime.now().add(const Duration(days: 4));
  bool _showCalendar = false;
  final _accepted = <String>{"Documents", "Small box", "Clothing"};
  bool _ticketAdded = false;
  final _flightCtl = TextEditingController(text: "AH 1004");

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

  Future<void> _pickAirport(bool isOrigin) async {
    final country = isOrigin ? _origin.country : _dest.country;
    final picked = await showAirportPicker(
      context,
      country: country,
      currentIata: isOrigin ? _origin.iata : _dest.iata,
      onCountryChanged: (newCountry) {
        // when user toggles country in the picker, swap the relevant side
        setState(() {
          if (isOrigin) {
            _origin = airportsByCountry(newCountry).first;
            // make sure dest is the other country
            if (_dest.country == newCountry) {
              _dest = airportsByCountry(newCountry == 'DZ' ? 'FR' : 'DZ').first;
            }
          } else {
            _dest = airportsByCountry(newCountry).first;
            if (_origin.country == newCountry) {
              _origin = airportsByCountry(newCountry == 'DZ' ? 'FR' : 'DZ').first;
            }
          }
        });
      },
    );
    if (picked != null) {
      setState(() {
        if (isOrigin) {
          _origin = picked;
          if (_dest.country == picked.country) {
            _dest = airportsByCountry(picked.country == 'DZ' ? 'FR' : 'DZ').first;
          }
        } else {
          _dest = picked;
          if (_origin.country == picked.country) {
            _origin = airportsByCountry(picked.country == 'DZ' ? 'FR' : 'DZ').first;
          }
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Column(
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
                  _routeBlock(),
                  const SizedBox(height: AppSpacing.x6),
                  _dateBlock(),
                  const SizedBox(height: AppSpacing.x6),
                  _flightAndCapacity(),
                  const SizedBox(height: AppSpacing.x6),
                  _acceptedTypes(),
                  const SizedBox(height: AppSpacing.x6),
                  _ticketUpload(),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
              child: PrimaryButton(
                label: "Submit for review",
                icon: Icons.flight_takeoff_rounded,
                expand: true,
                color: AppColors.emerald,
                onTap: () => context.pop(),
              ),
            ),
          ],
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

  Widget _routeBlock() {
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
            airport: _origin,
            onTap: () => _pickAirport(true),
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
            airport: _dest,
            onTap: () => _pickAirport(false),
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
    final types = ["Documents", "Small box", "Electronics", "Clothing"]; // food removed
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
    return GestureDetector(
      onTap: () => setState(() => _ticketAdded = !_ticketAdded),
      child: AnimatedContainer(
        duration: AppDurations.med,
        padding: const EdgeInsets.all(AppSpacing.x4),
        decoration: BoxDecoration(
          color: _ticketAdded ? AppColors.emerald.withValues(alpha: 0.08) : AppColors.parchmentSoft,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(
            color: _ticketAdded ? AppColors.emerald : AppColors.hairline,
            width: 1.4,
          ),
        ),
        child: Row(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: _ticketAdded
                    ? AppColors.emerald
                    : AppColors.ink.withValues(alpha: 0.06),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                _ticketAdded ? Icons.check_rounded : Icons.upload_file_rounded,
                color: _ticketAdded ? AppColors.parchment : AppColors.ink,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _ticketAdded ? "Ticket attached" : "Upload your boarding pass",
                    style: AppType.body(14.5, w: FontWeight.w700),
                  ),
                  Text(
                    _ticketAdded
                        ? "boarding-${_flightCtl.text.replaceAll(' ', '')}.pdf · 412 KB"
                        : "Required · PDF or photo",
                    style: AppType.body(12, color: AppColors.inkMute),
                  ),
                ],
              ),
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
