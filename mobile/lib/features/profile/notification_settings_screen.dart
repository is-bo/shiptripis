library;

import 'package:app_settings/app_settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/push/push_coordinator.dart';
import '../../core/push/push_messaging.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/push.dart';
import '../../l10n/app_localizations.dart';

final pushPreferencesProvider = FutureProvider.autoDispose<PushPreferences>((
  ref,
) async {
  return ref.watch(pushRepositoryProvider).preferences();
});

class NotificationSettingsScreen extends ConsumerStatefulWidget {
  const NotificationSettingsScreen({super.key});

  @override
  ConsumerState<NotificationSettingsScreen> createState() =>
      _NotificationSettingsScreenState();
}

class _NotificationSettingsScreenState
    extends ConsumerState<NotificationSettingsScreen> {
  bool _saving = false;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final runtime = ref.watch(pushCoordinatorProvider);
    final preferences = ref.watch(pushPreferencesProvider);

    return AppScaffold(
      topBar: AppTopBar(title: l.profileNotificationSettings, showBack: true),
      body: ListView(
        padding: AppScrollPadding.page(context),
        children: [
          SectionHeader(title: l.pushPermissionHeading),
          _permissionNotice(context, runtime),
          const SizedBox(height: AppSpace.xl),
          preferences.when(
            loading: () => const SkeletonDetail(),
            error: (error, _) => InlineFailure(
              error: error,
              onRetry: () => ref.invalidate(pushPreferencesProvider),
            ),
            data: (value) => Column(
              children: [
                _PreferenceRow(
                  title: l.pushEssentialTitle,
                  body: l.pushEssentialBody,
                  value: value.essentialEnabled,
                  onChanged: null,
                ),
                _PreferenceRow(
                  title: l.pushMessagesTitle,
                  body: l.pushMessagesBody,
                  value: value.messagesEnabled,
                  onChanged: _saving
                      ? null
                      : (enabled) => _update(messagesEnabled: enabled),
                ),
                _PreferenceRow(
                  title: l.pushMarketplaceTitle,
                  body: l.pushMarketplaceBody,
                  value: value.marketplaceEnabled,
                  onChanged: _saving
                      ? null
                      : (enabled) => _update(marketplaceEnabled: enabled),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _permissionNotice(BuildContext context, PushRuntimeState runtime) {
    final l = L.of(context);
    if (!runtime.available) {
      return InfoNotice(
        message: l.pushPermissionUnavailable,
        icon: Icons.notifications_off_outlined,
      );
    }
    return switch (runtime.permission) {
      PushPermission.authorized || PushPermission.provisional => InfoNotice(
        message: l.pushPermissionEnabled,
        tone: StatusTone.good,
        icon: Icons.notifications_active_outlined,
      ),
      PushPermission.denied => InfoNotice(
        message: l.pushPermissionDenied,
        tone: StatusTone.waiting,
        icon: Icons.notifications_off_outlined,
        actionLabel: l.pushOpenSettingsAction,
        onAction: () =>
            AppSettings.openAppSettings(type: AppSettingsType.notification),
      ),
      PushPermission.notDetermined => InfoNotice(
        message: l.pushPermissionBody,
        icon: Icons.notifications_none_rounded,
        actionLabel: l.pushEnableAction,
        onAction: () =>
            ref.read(pushCoordinatorProvider.notifier).requestPermission(),
      ),
      PushPermission.unavailable => InfoNotice(
        message: l.pushPermissionBody,
        icon: Icons.notifications_none_rounded,
      ),
    };
  }

  Future<void> _update({
    bool? messagesEnabled,
    bool? marketplaceEnabled,
  }) async {
    setState(() => _saving = true);
    try {
      await ref
          .read(pushRepositoryProvider)
          .updatePreferences(
            messagesEnabled: messagesEnabled,
            marketplaceEnabled: marketplaceEnabled,
          );
      ref.invalidate(pushPreferencesProvider);
    } on Object catch (error) {
      if (mounted) AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }
}

class _PreferenceRow extends StatelessWidget {
  const _PreferenceRow({
    required this.title,
    required this.body,
    required this.value,
    required this.onChanged,
  });

  final String title;
  final String body;
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) => SwitchListTile.adaptive(
    contentPadding: EdgeInsets.zero,
    title: Text(title),
    subtitle: Padding(
      padding: const EdgeInsets.only(top: AppSpace.xs),
      child: Text(body),
    ),
    value: value,
    onChanged: onChanged,
  );
}
