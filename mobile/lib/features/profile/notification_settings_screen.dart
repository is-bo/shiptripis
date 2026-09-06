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
  bool _requesting = false;

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
          SectionHeader(title: l.pushPreferencesHeading),
          Text(
            l.pushPreferencesBody,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.colors.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpace.md),
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
        message:
            runtime.availability == PushAvailability.configurationIncomplete
            ? l.pushPermissionUnavailable
            : l.pushPermissionInitializationFailed,
        icon: Icons.notifications_off_outlined,
      );
    }
    return switch (runtime.permission) {
      PushPermission.authorized ||
      PushPermission.provisional => _grantedNotice(runtime),
      PushPermission.deniedRequestable => _permissionAction(
        message: l.pushPermissionDeniedRequestable,
        label: l.pushEnableAction,
        onPressed: _requestPermission,
      ),
      PushPermission.settingsRequired => _permissionAction(
        message: l.pushPermissionDenied,
        label: l.pushOpenSettingsAction,
        onPressed: _openSettings,
        secondary: true,
      ),
      PushPermission.notDetermined => _permissionAction(
        message: l.pushPermissionBody,
        label: l.pushEnableAction,
        onPressed: _requestPermission,
      ),
      PushPermission.unavailable => InfoNotice(
        message: l.pushPermissionBody,
        icon: Icons.notifications_none_rounded,
      ),
    };
  }

  Widget _permissionAction({
    required String message,
    required String label,
    required VoidCallback onPressed,
    bool secondary = false,
  }) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      InfoNotice(message: message, icon: Icons.notifications_none_rounded),
      const SizedBox(height: AppSpace.md),
      AppButton(
        label: label,
        icon: secondary ? Icons.settings_outlined : Icons.notifications_active,
        variant: secondary
            ? AppButtonVariant.secondary
            : AppButtonVariant.primary,
        isLoading: _requesting,
        onPressed: _requesting ? null : onPressed,
      ),
    ],
  );

  Widget _grantedNotice(PushRuntimeState runtime) {
    final l = L.of(context);
    return switch (runtime.registration) {
      PushRegistrationState.registered => InfoNotice(
        message: l.pushPermissionEnabled,
        tone: StatusTone.good,
        icon: Icons.notifications_active_outlined,
      ),
      PushRegistrationState.failed => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InfoNotice(
            message: l.pushRegistrationFailed,
            tone: StatusTone.waiting,
            icon: Icons.sync_problem_rounded,
          ),
          const SizedBox(height: AppSpace.md),
          AppButton(
            label: l.pushRetryRegistrationAction,
            variant: AppButtonVariant.secondary,
            icon: Icons.refresh_rounded,
            onPressed: () =>
                ref.read(pushCoordinatorProvider.notifier).retryRegistration(),
          ),
        ],
      ),
      PushRegistrationState.idle || PushRegistrationState.pending => InfoNotice(
        message: l.pushRegistrationPending,
        tone: StatusTone.progress,
        icon: Icons.sync_rounded,
      ),
    };
  }

  Future<void> _requestPermission() async {
    if (_requesting) return;
    setState(() => _requesting = true);
    try {
      await ref.read(pushCoordinatorProvider.notifier).requestPermission();
    } on Object catch (error) {
      if (mounted) AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _requesting = false);
    }
  }

  Future<void> _openSettings() async {
    if (_requesting) return;
    setState(() => _requesting = true);
    try {
      await AppSettings.openAppSettings(type: AppSettingsType.notification);
      if (mounted) {
        await ref.read(pushCoordinatorProvider.notifier).refreshPermission();
      }
    } on Object catch (error) {
      if (mounted) AppSnack.failure(context, error);
    } finally {
      if (mounted) setState(() => _requesting = false);
    }
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
