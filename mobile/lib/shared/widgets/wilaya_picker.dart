import 'package:flutter/material.dart';

import '../../core/constants/wilayas.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';

Future<Wilaya?> showWilayaPicker(BuildContext context, {Wilaya? selected}) {
  return showModalBottomSheet<Wilaya>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.parchment,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.xl)),
    ),
    builder: (_) => _WilayaSheet(selected: selected),
  );
}

class _WilayaSheet extends StatefulWidget {
  const _WilayaSheet({this.selected});
  final Wilaya? selected;

  @override
  State<_WilayaSheet> createState() => _WilayaSheetState();
}

class _WilayaSheetState extends State<_WilayaSheet> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final filtered = _q.isEmpty
        ? kWilayas
        : kWilayas
            .where((w) =>
                w.name.toLowerCase().contains(_q.toLowerCase()) ||
                w.code.contains(_q))
            .toList();

    return DraggableScrollableSheet(
      initialChildSize: 0.85,
      minChildSize: 0.5,
      maxChildSize: 0.95,
      expand: false,
      builder: (_, ctrl) => Padding(
        padding: EdgeInsets.only(
          left: AppSpacing.x6,
          right: AppSpacing.x6,
          top: AppSpacing.x4,
          bottom: MediaQuery.of(context).viewInsets.bottom + AppSpacing.x4,
        ),
        child: Column(
          children: [
            Container(
              width: 40,
              height: 4,
              margin: const EdgeInsets.only(bottom: AppSpacing.x4),
              decoration: BoxDecoration(
                color: AppColors.hairline,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            Text("Choose your wilaya",
                style: AppType.display(22, w: FontWeight.w500)),
            const SizedBox(height: AppSpacing.x4),
            TextField(
              autofocus: false,
              onChanged: (v) => setState(() => _q = v),
              decoration: InputDecoration(
                hintText: 'Search by name or code',
                hintStyle: AppType.body(14, color: AppColors.inkMute),
                prefixIcon:
                    const Icon(Icons.search_rounded, color: AppColors.inkMute),
                filled: true,
                fillColor: AppColors.parchmentSoft,
                contentPadding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide:
                      const BorderSide(color: AppColors.hairline, width: 1.2),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide:
                      const BorderSide(color: AppColors.ink, width: 1.4),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.x3),
            Expanded(
              child: ListView.separated(
                controller: ctrl,
                itemCount: filtered.length,
                separatorBuilder: (_, __) => const SizedBox(height: 4),
                itemBuilder: (_, i) {
                  final w = filtered[i];
                  final isSel = widget.selected?.code == w.code;
                  return InkWell(
                    onTap: () => Navigator.of(context).pop(w),
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 14, vertical: 14),
                      decoration: BoxDecoration(
                        color: isSel
                            ? AppColors.parchmentSoft
                            : Colors.transparent,
                        borderRadius: BorderRadius.circular(AppRadius.md),
                        border: Border.all(
                          color: isSel ? AppColors.ink : AppColors.hairline,
                          width: isSel ? 1.4 : 1.0,
                        ),
                      ),
                      child: Row(
                        children: [
                          Container(
                            width: 36,
                            height: 36,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              color: AppColors.ink,
                              borderRadius:
                                  BorderRadius.circular(AppRadius.sm),
                            ),
                            child: Text(w.code,
                                style: AppType.mono(12,
                                    color: AppColors.parchment,
                                    w: FontWeight.w700)),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(w.name,
                                style: AppType.body(15, w: FontWeight.w600)),
                          ),
                          if (isSel)
                            const Icon(Icons.check_rounded,
                                color: AppColors.ink, size: 20),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
