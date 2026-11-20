/// What the tabs show a guest, and the notice a guest sees after their
/// session ended.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../l10n/app_localizations.dart';
import 'account_gate.dart';

/// "You were signed out. Sign in again." on guest Home and guest Profile,
/// once a session has ended, until the guest signs in or closes it. Nothing
/// at all otherwise.
class SignedOutNotice extends ConsumerWidget {
  const SignedOutNotice({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    if (session is! SessionSignedOut ||
        !(session.becauseExpired || session.becauseDeleted)) {
      return const SizedBox.shrink();
    }
    final deleted = session.becauseDeleted;
    final l = L.of(context);
    final style = StatusStyle.of(context, StatusTone.waiting);
    final text = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.lg),
      child: Semantics(
        liveRegion: true,
        container: true,
        child: Container(
          padding: const EdgeInsetsDirectional.fromSTEB(
            AppSpace.lg,
            AppSpace.xs,
            AppSpace.xs,
            AppSpace.xs,
          ),
          decoration: BoxDecoration(
            color: style.background,
            borderRadius: AppRadius.rMd,
          ),
          child: Row(
            children: [
              Icon(
                deleted
                    ? Icons.check_circle_outline_rounded
                    : Icons.logout_rounded,
                size: 19,
                color: style.accent,
              ),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: AppSpace.sm),
                  child: Wrap(
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: AppSpace.xs,
                    children: [
                      Text(
                        deleted ? l.deleteAccountDone : l.guestSignedOutNotice,
                        style: text.bodySmall?.copyWith(
                          color: style.foreground,
                        ),
                      ),
                      if (!deleted)
                        TextButton(
                          onPressed: () => openSignIn(context),
                          child: Text(l.authSignIn),
                        ),
                    ],
                  ),
                ),
              ),
              AppIconButton(
                icon: Icons.close_rounded,
                label: l.guestNoticeDismiss,
                tone: style.foreground,
                onPressed: () =>
                    ref.read(sessionProvider.notifier).dismissSignedOutNotice(),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Deliveries or Chat for a guest: what will be here, and the way in. It
/// reads nothing.
class GuestTabScreen extends StatelessWidget {
  const GuestTabScreen({
    required this.title,
    required this.headline,
    required this.body,
    required this.icon,
    required this.reason,
    super.key,
  });

  final String title;
  final String headline;
  final String body;
  final IconData icon;
  final AccountReason reason;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return AppScaffold(
      topBar: AppTopBar(title: title),
      body: ListView(
        padding: AppScrollPadding.page(context),
        children: [
          AppEmptyState(
            title: headline,
            body: body,
            icon: icon,
            actionLabel: l.guestAccountAction,
            onAction: () => ensureAccount(context, reason),
          ),
        ],
      ),
    );
  }
}
