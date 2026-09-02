/// Sheets and dialogs.
///
/// A sheet here is always height-bounded, always safe-area aware at the
/// bottom, and always lifts above the keyboard. Those three together are what
/// stop a picker from hiding its own confirm button behind the home indicator
/// or an open keyboard — the same class of bug the navigation-bar work fixed
/// for full screens, solved once for overlays.
library;

import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import '../tokens.dart';
import 'primitives.dart';

/// Presents [builder] as a modal sheet.
///
/// [fullHeight] is for a sheet that owns the screen — a map picker, a long
/// searchable list. Everything else is content-sized and capped at 88% of the
/// viewport, so the page underneath stays visible and the sheet still reads as
/// a layer rather than a navigation.
Future<T?> showAppSheet<T>(
  BuildContext context, {
  required Widget Function(BuildContext context) builder,
  bool fullHeight = false,
  bool isDismissible = true,
  bool enableDrag = true,
}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    isDismissible: isDismissible,
    enableDrag: enableDrag,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    builder: (sheetContext) {
      final viewport = MediaQuery.sizeOf(sheetContext).height;
      return Padding(
        // Lifts the whole sheet, including its footer, clear of the keyboard.
        padding: EdgeInsets.only(
          bottom: MediaQuery.viewInsetsOf(sheetContext).bottom,
        ),
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: fullHeight ? viewport * 0.94 : viewport * 0.88,
            minHeight: fullHeight ? viewport * 0.94 : 0,
          ),
          child: Material(
            color: sheetContext.colors.surface,
            borderRadius: const BorderRadius.vertical(
              top: Radius.circular(AppRadius.xl),
            ),
            clipBehavior: Clip.antiAlias,
            child: builder(sheetContext),
          ),
        ),
      );
    },
  );
}

/// The standard sheet frame: grab handle, title row, scrollable body, pinned
/// footer.
class AppSheet extends StatelessWidget {
  const AppSheet({
    required this.title,
    required this.child,
    this.subtitle,
    this.footer,
    this.showClose = true,
    this.scrollable = true,
    super.key,
  });

  final String title;
  final String? subtitle;
  final Widget child;
  final Widget? footer;
  final bool showClose;

  /// False when the child brings its own scroll view (a long list).
  final bool scrollable;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final body = Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpace.gutter,
        0,
        AppSpace.gutter,
        AppSpace.lg,
      ),
      child: child,
    );

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // Grab handle. Decorative — the close button carries the semantics.
        ExcludeSemantics(
          child: Padding(
            padding: const EdgeInsets.only(top: AppSpace.md),
            child: Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                color: c.hairlineStrong,
                borderRadius: AppRadius.rPill,
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpace.gutter,
            AppSpace.lg,
            AppSpace.sm,
            AppSpace.lg,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Semantics(
                      header: true,
                      child: Text(title, style: text.titleLarge),
                    ),
                    if (subtitle != null) ...[
                      const SizedBox(height: AppSpace.xs),
                      Text(
                        subtitle!,
                        style: text.bodyMedium?.copyWith(
                          color: c.textSecondary,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (showClose)
                AppIconButton(
                  icon: Icons.close_rounded,
                  label: l.a11yCloseSheet,
                  onPressed: () => Navigator.of(context).maybePop(),
                ),
            ],
          ),
        ),
        Flexible(child: scrollable ? SingleChildScrollView(child: body) : body),
        if (footer != null)
          Container(
            width: double.infinity,
            decoration: BoxDecoration(
              color: c.surface,
              border: Border(top: BorderSide(color: c.hairline)),
            ),
            child: SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.all(AppSpace.gutter),
                child: footer,
              ),
            ),
          )
        else
          SafeArea(top: false, child: const SizedBox(height: AppSpace.sm)),
      ],
    );
  }
}

/// A single-select list presented as a sheet.
class AppChoiceSheet<T> extends StatelessWidget {
  const AppChoiceSheet({
    required this.title,
    required this.options,
    required this.selected,
    this.subtitle,
    super.key,
  });

  final String title;
  final String? subtitle;
  final List<AppSheetOption<T>> options;
  final T? selected;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppSheet(
      title: title,
      subtitle: subtitle,
      scrollable: false,
      child: ListView.separated(
        shrinkWrap: true,
        padding: EdgeInsets.zero,
        itemCount: options.length,
        separatorBuilder: (_, _) => Divider(height: 1, color: c.hairline),
        itemBuilder: (context, index) {
          final option = options[index];
          final isSelected = option.value == selected;
          return Semantics(
            button: true,
            enabled: option.enabled,
            selected: isSelected,
            label: option.label,
            hint: isSelected ? l.a11ySelected : l.a11yNotSelected,
            onTap: option.enabled
                ? () => Navigator.of(context).pop(option.value)
                : null,
            child: ExcludeSemantics(
              child: ListTile(
                contentPadding: EdgeInsets.zero,
                leading: option.icon == null
                    ? null
                    : Icon(
                        option.icon,
                        color: isSelected ? c.brand : c.textTertiary,
                      ),
                title: Text(option.label, style: text.bodyLarge),
                subtitle: option.detail == null
                    ? null
                    : Text(
                        option.detail!,
                        style: text.bodySmall?.copyWith(color: c.textSecondary),
                      ),
                trailing: isSelected
                    ? Icon(Icons.check_rounded, color: c.brand)
                    : null,
                enabled: option.enabled,
                onTap: option.enabled
                    ? () => Navigator.of(context).pop(option.value)
                    : null,
              ),
            ),
          );
        },
      ),
    );
  }
}

@immutable
class AppSheetOption<T> {
  const AppSheetOption({
    required this.value,
    required this.label,
    this.detail,
    this.icon,
    this.enabled = true,
  });

  final T value;
  final String label;
  final String? detail;
  final IconData? icon;
  final bool enabled;
}

/// Asks the user to confirm an action.
///
/// [consequence] is where the irreversible part goes — what the user loses,
/// what it costs, what cannot be undone. A confirm dialog whose body only
/// restates the button label is a speed bump, not informed consent.
Future<bool> confirmAction(
  BuildContext context, {
  required String title,
  required String body,
  required String confirmLabel,
  String? cancelLabel,
  Widget? consequence,
  bool isDestructive = false,
}) async {
  final l = L.of(context);
  final result = await showDialog<bool>(
    context: context,
    builder: (dialogContext) {
      final c = dialogContext.colors;
      return AlertDialog(
        title: Text(title),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(body),
            if (consequence != null) ...[
              const SizedBox(height: AppSpace.lg),
              consequence,
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(cancelLabel ?? l.actionCancel),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            style: isDestructive
                ? TextButton.styleFrom(foregroundColor: c.danger)
                : null,
            child: Text(confirmLabel),
          ),
        ],
      );
    },
  );
  return result ?? false;
}
