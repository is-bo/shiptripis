/// Light, dark, or whatever the phone is doing.
///
/// "Match device" is the default and is listed first, because it is the answer
/// for most people and the one that keeps working when they change their
/// system setting later.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_settings.dart';
import '../../design/components/navigation.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';

class AppearanceScreen extends ConsumerWidget {
  const AppearanceScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final c = context.colors;
    final mode = ref.watch(themeModeProvider);

    final options = <({ThemeMode mode, String label, IconData icon})>[
      (
        mode: ThemeMode.system,
        label: l.profileAppearanceSystem,
        icon: Icons.brightness_auto_rounded,
      ),
      (
        mode: ThemeMode.light,
        label: l.profileAppearanceLight,
        icon: Icons.light_mode_rounded,
      ),
      (
        mode: ThemeMode.dark,
        label: l.profileAppearanceDark,
        icon: Icons.dark_mode_rounded,
      ),
    ];

    return AppScaffold(
      topBar: AppTopBar(title: l.profileAppearance, showBack: true),
      body: ListView(
        padding: AppScrollPadding.page(context),
        children: [
          for (final option in options)
            Semantics(
              button: true,
              selected: option.mode == mode,
              hint: option.mode == mode ? l.a11ySelected : l.a11yNotSelected,
              child: ExcludeSemantics(
                child: InkWell(
                  onTap: () =>
                      ref.read(themeModeProvider.notifier).set(option.mode),
                  borderRadius: AppRadius.rSm,
                  child: Container(
                    constraints: const BoxConstraints(
                      minHeight: AppSpace.minTapTarget,
                    ),
                    padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
                    child: Row(
                      children: [
                        Icon(option.icon, size: 20, color: c.textTertiary),
                        const SizedBox(width: AppSpace.lg),
                        Expanded(
                          child: Text(
                            option.label,
                            style: Theme.of(context).textTheme.bodyLarge,
                          ),
                        ),
                        if (option.mode == mode)
                          Icon(Icons.check_rounded, size: 20, color: c.brand)
                        else
                          const SizedBox(width: 20),
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
