import 'package:flutter/material.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';

/// A compact, in-line month calendar designed to live inside a sheet/card.
class InlineCalendar extends StatefulWidget {
  const InlineCalendar({
    super.key,
    required this.selected,
    required this.onSelect,
    this.minDate,
    this.maxDate,
  });

  final DateTime selected;
  final ValueChanged<DateTime> onSelect;
  final DateTime? minDate;
  final DateTime? maxDate;

  @override
  State<InlineCalendar> createState() => _InlineCalendarState();
}

class _InlineCalendarState extends State<InlineCalendar> {
  late DateTime _month;

  @override
  void initState() {
    super.initState();
    _month = DateTime(widget.selected.year, widget.selected.month);
  }

  static const _wd = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
  static const _months = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];

  @override
  Widget build(BuildContext context) {
    final firstWd = DateTime(_month.year, _month.month, 1).weekday; // 1 = Mon
    final daysInMonth = DateTime(_month.year, _month.month + 1, 0).day;
    final cells = <Widget>[];
    // empty leading cells
    for (int i = 1; i < firstWd; i++) {
      cells.add(const SizedBox());
    }
    final today = DateTime.now();
    for (int d = 1; d <= daysInMonth; d++) {
      final date = DateTime(_month.year, _month.month, d);
      final isSelected = _sameDay(date, widget.selected);
      final isToday = _sameDay(date, today);
      final disabled = (widget.minDate != null && date.isBefore(_atMidnight(widget.minDate!))) ||
          (widget.maxDate != null && date.isAfter(_atMidnight(widget.maxDate!)));
      cells.add(
        GestureDetector(
          onTap: disabled ? null : () => widget.onSelect(date),
          child: AnimatedContainer(
            duration: AppDurations.fast,
            margin: const EdgeInsets.all(2),
            decoration: BoxDecoration(
              color: isSelected
                  ? AppColors.ink
                  : (isToday ? AppColors.sun.withValues(alpha: 0.25) : Colors.transparent),
              borderRadius: BorderRadius.circular(AppRadius.sm),
              border: !isSelected && isToday
                  ? Border.all(color: AppColors.sun, width: 1.4)
                  : null,
            ),
            alignment: Alignment.center,
            child: Text(
              "$d",
              style: AppType.mono(
                13,
                w: FontWeight.w600,
                color: disabled
                    ? AppColors.inkMute.withValues(alpha: 0.4)
                    : (isSelected ? AppColors.parchment : AppColors.ink),
              ),
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(AppSpacing.x3),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.hairline, width: 1.2),
      ),
      child: Column(
        children: [
          Row(
            children: [
              IconButton(
                onPressed: () => setState(
                    () => _month = DateTime(_month.year, _month.month - 1)),
                icon: const Icon(Icons.chevron_left_rounded, size: 22),
                style: IconButton.styleFrom(
                    padding: const EdgeInsets.all(6),
                    backgroundColor: AppColors.parchment),
              ),
              Expanded(
                child: Center(
                  child: Text(
                    "${_months[_month.month - 1]} ${_month.year}",
                    style: AppType.display(16, w: FontWeight.w500),
                  ),
                ),
              ),
              IconButton(
                onPressed: () => setState(
                    () => _month = DateTime(_month.year, _month.month + 1)),
                icon: const Icon(Icons.chevron_right_rounded, size: 22),
                style: IconButton.styleFrom(
                    padding: const EdgeInsets.all(6),
                    backgroundColor: AppColors.parchment),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: _wd
                .map((d) => Expanded(
                      child: Center(
                        child: Text(d, style: AppType.eyebrow()),
                      ),
                    ))
                .toList(),
          ),
          const SizedBox(height: 6),
          GridView.count(
            crossAxisCount: 7,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            childAspectRatio: 1.05,
            children: cells,
          ),
        ],
      ),
    );
  }

  static bool _sameDay(DateTime a, DateTime b) =>
      a.year == b.year && a.month == b.month && a.day == b.day;
  static DateTime _atMidnight(DateTime d) => DateTime(d.year, d.month, d.day);
}

String formatDate(DateTime d) {
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
  ];
  return "${months[d.month - 1]} ${d.day.toString().padLeft(2, '0')}, ${d.year}";
}
