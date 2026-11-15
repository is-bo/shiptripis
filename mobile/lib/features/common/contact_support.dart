/// Contact support: one action, one place that builds the email.
///
/// The address comes from the server (`GET /api/support`), the one the emails
/// already print. While the server has none, [supportEmailProvider] is null
/// and everything here disappears: the app never shows a "contact support"
/// label that leads nowhere.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/app_state.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../l10n/app_localizations.dart';

/// Opens a new email to support. [trackingNumber] goes in the subject when the
/// person asks from a delivery, so support can find it at once.
Future<void> openSupportEmail(
  BuildContext context,
  String email, {
  String? trackingNumber,
}) async {
  final l = L.of(context);
  final tracking = trackingNumber?.trim() ?? '';
  final subject = tracking.isEmpty
      ? l.supportEmailSubject
      : l.supportEmailSubjectDelivery(tracking);
  final uri = Uri.parse(
    'mailto:$email?subject=${Uri.encodeComponent(subject)}',
  );
  var opened = false;
  try {
    opened = await launchUrl(uri);
  } on Object {
    opened = false;
  }
  if (!opened && context.mounted) {
    AppSnack.info(context, l.supportEmailFailed(email));
  }
}

/// The support address, or null when there is none to offer (not set, still
/// loading, or unreachable).
String? supportEmailOf(WidgetRef ref) => ref.watch(supportEmailProvider).value;

/// A support action as a button; nothing at all when there is no address.
class ContactSupportButton extends ConsumerWidget {
  const ContactSupportButton({
    this.trackingNumber,
    this.variant = AppButtonVariant.tertiary,
    super.key,
  });

  final String? trackingNumber;
  final AppButtonVariant variant;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final email = supportEmailOf(ref);
    if (email == null) return const SizedBox.shrink();
    return AppButton(
      label: L.of(context).actionContactSupport,
      icon: Icons.mail_outline_rounded,
      variant: variant,
      onPressed: () =>
          openSupportEmail(context, email, trackingNumber: trackingNumber),
    );
  }
}
