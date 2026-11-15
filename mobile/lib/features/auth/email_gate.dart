/// One shared handler for "confirm your email first".
///
/// The server refuses posting a parcel and changing payout setup with
/// `email_verification_required` until the email is confirmed. Every screen
/// that can meet it calls [handleEmailVerificationRequired]; there is no
/// second flow. The person confirms on the existing verify-email screen (with
/// "send the code again") and comes back to the screen they were on, with
/// everything they typed still in place, because that screen is never left.
library;

import 'package:flutter/widgets.dart';
import 'package:go_router/go_router.dart';

import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';

bool isEmailVerificationRequired(Object error) =>
    error is ApiException &&
    error.code == ApiErrorCode.emailVerificationRequired;

/// Opens the verify-email screen for the signed-in person. Completes with true
/// when they confirmed, false when they backed out.
Future<bool> openVerifyEmail(BuildContext context) async =>
    await context.pushNamed<bool>(Routes.verifyEmail) ?? false;

/// If [error] is the email gate, sends the person to confirm and returns true
/// (the error is handled; do not show it). Otherwise returns false.
///
/// [onConfirmed] runs after a successful confirmation, if the screen is still
/// there, so the person can carry on (for example, post again).
Future<bool> handleEmailVerificationRequired(
  BuildContext context,
  Object error, {
  VoidCallback? onConfirmed,
}) async {
  if (!isEmailVerificationRequired(error)) return false;
  final confirmed = await openVerifyEmail(context);
  if (confirmed && context.mounted) onConfirmed?.call();
  return true;
}
