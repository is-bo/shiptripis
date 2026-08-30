/// Language — both of them.
///
/// Two settings live here because they are one question in a user's head
/// ("what language does this thing use?") and two different answers in the
/// system:
///
/// * **App language** is what the interface is drawn in. It is a device
///   setting, it never leaves the phone, and it is the only thing that decides
///   whether the app runs right-to-left.
/// * **Email language** is what ShipTrip *writes to you* in — payment and
///   refund receipts, verification decisions, dispute and cancellation
///   notices, account-security mail. It is stored on the account, the server
///   snapshots it onto each message it owes, and it follows the user to every
///   device.
///
/// Keeping them on one screen, one under the other, is what makes the
/// difference legible. Splitting them into two rows in Profile would have
/// produced exactly the confusing duplicate the distinction is meant to avoid.
///
/// Choosing Arabic email does **not** mirror the app. That is deliberate and
/// tested: a Francophone sender in Lyon writing to family in Algiers is a real
/// user, and flipping their interface because of it would be a bug.
///
/// Each option is written **in its own language** — a user who has landed in
/// the wrong one cannot read a list of language names rendered in that wrong
/// language, which is exactly when they need this screen.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_settings.dart';
import '../../core/api/api_exception.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/communication_language.dart';
import '../../l10n/app_localizations.dart';

class LanguageScreen extends ConsumerStatefulWidget {
  const LanguageScreen({super.key});

  @override
  ConsumerState<LanguageScreen> createState() => _LanguageScreenState();
}

class _LanguageScreenState extends ConsumerState<LanguageScreen> {
  /// The value being written, or null when nothing is in flight.
  ///
  /// Held rather than a bare bool so the row the user tapped is the row that
  /// shows the spinner, and so a second tap on a different language while the
  /// first is still saving cannot start a race.
  CommunicationLanguage? _saving;

  /// The last save that failed, kept so the notice can offer to repeat it.
  CommunicationLanguage? _failed;
  Object? _error;

  Future<void> _setEmailLanguage(CommunicationLanguage language) async {
    if (_saving != null) return;
    final l = L.of(context);

    setState(() {
      _saving = language;
      _error = null;
      _failed = null;
    });

    try {
      // The selection is not moved optimistically. This value decides what a
      // stranger reads in an email about somebody's money; showing it as
      // changed before the server has stored it would be a lie the user
      // cannot check.
      await ref
          .read(sessionProvider.notifier)
          .updatePreferredLanguage(language);
      if (!mounted) return;
      AppSnack.success(context, l.profileEmailLanguageSaved);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error;
        _failed = language;
      });
    } finally {
      if (mounted) setState(() => _saving = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final chosenLocale = ref.watch(localeProvider);
    final account = ref.watch(accountProvider);

    // A legacy account with no stored value still resolves to English through
    // `Account.preferredLanguage`, so the selector always has exactly one
    // option ticked and never renders an empty or invalid state.
    final emailLanguage = account?.preferredLanguage;

    const appOptions = <({Locale? locale, String label})>[
      (locale: null, label: 'System'),
      (locale: Locale('en'), label: 'English'),
      (locale: Locale('fr'), label: 'Français'),
      (locale: Locale('ar'), label: 'العربية'),
    ];

    return AppScaffold(
      topBar: AppTopBar(title: l.profileLanguage, showBack: true),
      body: ListView(
        padding: AppScrollPadding.page(context),
        children: [
          SectionHeader(
            title: l.profileAppLanguage,
            subtitle: l.profileAppLanguageHelp,
          ),
          for (final option in appOptions)
            _Option(
              label: option.locale == null
                  ? l.profileLanguageSystem
                  : option.label,
              selected:
                  chosenLocale?.languageCode == option.locale?.languageCode,
              // Arabic reads right to left even inside a list of options.
              isRtlLabel: option.locale?.languageCode == 'ar',
              onTap: () => ref.read(localeProvider.notifier).set(option.locale),
            ),

          SectionHeader(
            title: l.profileEmailLanguage,
            subtitle: l.profileEmailLanguageHelp,
          ),

          if (_error != null) ...[
            const SizedBox(height: AppSpace.xs),
            _SaveFailure(
              error: _error!,
              onRetry: _failed == null
                  ? null
                  : () => _setEmailLanguage(_failed!),
            ),
            const SizedBox(height: AppSpace.sm),
          ],

          if (emailLanguage == null)
            // Signed out, or the profile has not landed yet. A selector with
            // nothing ticked would be worse than an honest placeholder.
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpace.md),
              child: SkeletonBox(width: 120),
            )
          else
            for (final language in CommunicationLanguage.values)
              _Option(
                label: language.nativeLabel,
                selected: language == emailLanguage,
                isRtlLabel: language.isRtlLabel,
                isSaving: _saving == language,
                // One write at a time. The rest of the list goes inert rather
                // than queueing a second PATCH behind the first.
                onTap: _saving != null
                    ? null
                    : () => _setEmailLanguage(language),
              ),
        ],
      ),
    );
  }
}

/// A failed save, stated in place rather than only in a snackbar that has
/// already gone.
class _SaveFailure extends StatelessWidget {
  const _SaveFailure({required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final copy = describeFailure(context, error);

    return InfoNotice(
      message: copy.body,
      tone: copy.tone,
      icon: copy.icon,
      actionLabel: copy.canRetry && onRetry != null ? l.actionRetry : null,
      onAction: copy.canRetry ? onRetry : null,
    );
  }
}

class _Option extends StatelessWidget {
  const _Option({
    required this.label,
    required this.selected,
    required this.onTap,
    required this.isRtlLabel,
    this.isSaving = false,
  });

  final String label;
  final bool selected;
  final VoidCallback? onTap;
  final bool isRtlLabel;
  final bool isSaving;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    return Semantics(
      button: true,
      enabled: onTap != null,
      selected: selected,
      label: label,
      hint: selected ? l.a11ySelected : l.a11yNotSelected,
      child: ExcludeSemantics(
        child: InkWell(
          onTap: onTap,
          borderRadius: AppRadius.rSm,
          child: Container(
            constraints: const BoxConstraints(minHeight: AppSpace.minTapTarget),
            padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
            child: Row(
              children: [
                Expanded(
                  // The row aligns to the screen's leading edge; only the
                  // label's own text direction is overridden. Letting the
                  // override drive alignment too left "العربية" floating at
                  // the far edge of an otherwise left-aligned list, and
                  // "English" floating in an Arabic one.
                  //
                  // Direction is still scoped to the label: choosing Arabic
                  // mail does not turn the app around, only the
                  // app-language setting does.
                  child: Align(
                    alignment: AlignmentDirectional.centerStart,
                    child: Directionality(
                      textDirection: isRtlLabel
                          ? TextDirection.rtl
                          : TextDirection.ltr,
                      child: Text(
                        label,
                        style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                          color: onTap == null && !isSaving
                              ? c.textTertiary
                              : c.textPrimary,
                        ),
                      ),
                    ),
                  ),
                ),
                if (isSaving)
                  SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: c.brand,
                    ),
                  )
                else if (selected)
                  Icon(Icons.check_rounded, size: 20, color: c.brand)
                else
                  const SizedBox(width: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
