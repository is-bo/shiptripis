/// "Continue with Apple" and "Continue with Google".
///
/// Shown on sign-in, sign-up and the account screen, and only for the
/// providers this build offers ([SocialSignIn.offersGoogle],
/// [SocialSignIn.offersApple]): a build without the client ids shows email
/// only. Each button follows its provider's rules: Apple's is black (white in
/// dark mode) with the Apple logo; Google's is white (dark neutral in dark
/// mode) with the four-colour "G". Both are as tall as the app's buttons.
///
/// Cancelling is silent. A failure is said under the buttons in the person's
/// language: a refused account, a provider the server does not offer yet, or
/// the generic copy. Once signed in, an account the provider left without a
/// name goes to the name step first; inside the account moment the flow then
/// completes, as the email sign-in does.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart'
    show AppleLogoPainter;

import '../../app/app_settings.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/auth/social_sign_in.dart';
import '../../core/session/session.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/communication_language.dart';
import '../../l10n/app_localizations.dart';
import 'account_gate.dart';
import 'account_name_screen.dart';

class SocialSignInButtons extends ConsumerStatefulWidget {
  const SocialSignInButtons({
    required this.flow,
    this.showOrDivider = false,
    super.key,
  });

  final AccountFlow flow;

  /// An "or" line under the buttons, where an email form follows them.
  final bool showOrDivider;

  @override
  ConsumerState<SocialSignInButtons> createState() =>
      _SocialSignInButtonsState();
}

class _SocialSignInButtonsState extends ConsumerState<SocialSignInButtons> {
  SocialProvider? _busy;
  String? _error;

  Future<void> _continueWith(SocialProvider provider) async {
    if (_busy != null) return;
    setState(() {
      _busy = provider;
      _error = null;
    });
    // The account may be new: its first email goes out in the language the
    // person is reading, as sign-up does.
    final language = CommunicationLanguage.forLanguageCode(
      ref.read(effectiveLocaleProvider).languageCode,
    );
    final auth = ref.read(socialAuthProvider);
    try {
      final signedIn = switch (provider) {
        SocialProvider.google => await auth.google(language),
        SocialProvider.apple => await auth.apple(language),
      };
      if (signedIn && mounted) _signedIn();
    } on SocialSignInFailure {
      if (mounted) setState(() => _error = _failed(provider));
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = _describe(provider, error));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  void _signedIn() {
    final account = ref.read(accountProvider);
    if (account != null && account.fullName.trim().isEmpty) {
      // Inside the account moment the name step is the flow's last screen.
      // On its own, the router takes the person on and Home asks.
      if (widget.flow.active) {
        ref.read(accountNameAskedProvider.notifier).markAsked();
        context.pushNamed(
          Routes.accountName,
          queryParameters: widget.flow.parameters,
        );
      }
      return;
    }
    // On its own, the router's redirect takes over from here.
    if (widget.flow.active) completeAccountFlow(context, widget.flow);
  }

  String _failed(SocialProvider provider) {
    final l = L.of(context);
    return switch (provider) {
      SocialProvider.google => l.socialGoogleFailed,
      SocialProvider.apple => l.socialAppleFailed,
    };
  }

  String _describe(SocialProvider provider, ApiException error) {
    final l = L.of(context);
    if (error.code == ApiErrorCode.accountDisabled) {
      return l.socialAccountDisabled;
    }
    if (error.code == ApiErrorCode.googleSignInUnavailable) {
      return l.socialGoogleUnavailable;
    }
    if (error.code == ApiErrorCode.appleSignInUnavailable) {
      return l.socialAppleUnavailable;
    }
    return switch (error.kind) {
      // The token was refused, or the request was: nothing the person can
      // fix but trying again.
      ApiFailureKind.unauthenticated ||
      ApiFailureKind.validation ||
      ApiFailureKind.forbidden => _failed(provider),
      _ => describeFailure(context, error).body,
    };
  }

  @override
  Widget build(BuildContext context) {
    final social = ref.watch(socialSignInProvider);
    if (!social.offersApple && !social.offersGoogle) {
      return const SizedBox.shrink();
    }
    final l = L.of(context);
    final busy = _busy != null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (social.offersApple) ...[
          _AppleButton(
            label: l.socialContinueWithApple,
            isLoading: _busy == SocialProvider.apple,
            onPressed: busy ? null : () => _continueWith(SocialProvider.apple),
          ),
          const SizedBox(height: AppSpace.sm),
        ],
        if (social.offersGoogle) ...[
          _GoogleButton(
            label: l.socialContinueWithGoogle,
            isLoading: _busy == SocialProvider.google,
            onPressed: busy ? null : () => _continueWith(SocialProvider.google),
          ),
          const SizedBox(height: AppSpace.sm),
        ],
        if (_error != null) ...[
          InfoNotice(
            message: _error!,
            tone: StatusTone.bad,
            icon: Icons.error_outline_rounded,
          ),
          const SizedBox(height: AppSpace.sm),
        ],
        if (widget.showOrDivider) _OrDivider(label: l.socialOr),
      ],
    );
  }
}

class _OrDivider extends StatelessWidget {
  const _OrDivider({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpace.sm, bottom: AppSpace.lg),
      child: Row(
        children: [
          Expanded(child: Divider(color: c.hairline)),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpace.md),
            child: Text(
              label,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ),
          Expanded(child: Divider(color: c.hairline)),
        ],
      ),
    );
  }
}

/// Apple's button: black on light, white on dark, the Apple logo, the
/// label in the system's weight.
class _AppleButton extends StatelessWidget {
  const _AppleButton({
    required this.label,
    required this.isLoading,
    required this.onPressed,
  });

  final String label;
  final bool isLoading;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final fill = dark ? Colors.white : Colors.black;
    final ink = dark ? Colors.black : Colors.white;
    return _ProviderButton(
      label: label,
      isLoading: isLoading,
      onPressed: onPressed,
      style: FilledButton.styleFrom(
        backgroundColor: fill,
        foregroundColor: ink,
        disabledBackgroundColor: fill.withValues(alpha: 0.6),
        disabledForegroundColor: ink,
      ),
      logo: CustomPaint(painter: AppleLogoPainter(color: ink)),
      ink: ink,
      filled: true,
    );
  }
}

/// Google's button: white with a grey outline on light, dark neutral on
/// dark, the four-colour "G".
class _GoogleButton extends StatelessWidget {
  const _GoogleButton({
    required this.label,
    required this.isLoading,
    required this.onPressed,
  });

  final String label;
  final bool isLoading;
  final VoidCallback? onPressed;

  // Google's published button colours.
  static const _lightFill = Color(0xFFFFFFFF);
  static const _lightStroke = Color(0xFF747775);
  static const _lightText = Color(0xFF1F1F1F);
  static const _darkFill = Color(0xFF131314);
  static const _darkStroke = Color(0xFF8E918F);
  static const _darkText = Color(0xFFE3E3E3);

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final fill = dark ? _darkFill : _lightFill;
    final ink = dark ? _darkText : _lightText;
    return _ProviderButton(
      label: label,
      isLoading: isLoading,
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        backgroundColor: fill,
        foregroundColor: ink,
        disabledForegroundColor: ink.withValues(alpha: 0.6),
        side: BorderSide(color: dark ? _darkStroke : _lightStroke),
      ),
      logo: const CustomPaint(painter: GoogleLogoPainter()),
      ink: ink,
      filled: false,
    );
  }
}

class _ProviderButton extends StatelessWidget {
  const _ProviderButton({
    required this.label,
    required this.isLoading,
    required this.onPressed,
    required this.style,
    required this.logo,
    required this.ink,
    required this.filled,
  });

  final String label;
  final bool isLoading;
  final VoidCallback? onPressed;
  final ButtonStyle style;
  final Widget logo;

  /// The label's colour, which the spinner takes while busy.
  final Color ink;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    final child = isLoading
        ? SizedBox.square(
            dimension: 20,
            child: CircularProgressIndicator(
              strokeWidth: 2.2,
              valueColor: AlwaysStoppedAnimation(ink),
            ),
          )
        : Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox.square(dimension: 18, child: logo),
              const SizedBox(width: AppSpace.sm),
              Flexible(child: Text(label, textAlign: TextAlign.center)),
            ],
          );
    final pressed = isLoading ? null : onPressed;
    return Semantics(
      button: true,
      enabled: pressed != null,
      liveRegion: isLoading,
      child: SizedBox(
        width: double.infinity,
        child: filled
            ? FilledButton(onPressed: pressed, style: style, child: child)
            : OutlinedButton(onPressed: pressed, style: style, child: child),
      ),
    );
  }
}

/// Google's "G", in its four colours.
class GoogleLogoPainter extends CustomPainter {
  const GoogleLogoPainter();

  static const _blue = Color(0xFF4285F4);
  static const _green = Color(0xFF34A853);
  static const _yellow = Color(0xFFFBBC05);
  static const _red = Color(0xFFEA4335);

  static double _rad(double degrees) => degrees * 3.141592653589793 / 180;

  @override
  void paint(Canvas canvas, Size size) {
    final side = size.shortestSide;
    final stroke = side * 0.2;
    final center = size.center(Offset.zero);
    final radius = (side - stroke) / 2;
    final ring = Rect.fromCircle(center: center, radius: radius);
    Paint arc(Color color) => Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke;

    // Angles run clockwise from three o'clock; the G opens at the upper
    // right, between the red arc and the blue bar.
    canvas
      ..drawArc(ring, _rad(-40), _rad(-100), false, arc(_red))
      ..drawArc(ring, _rad(-140), _rad(-90), false, arc(_yellow))
      ..drawArc(ring, _rad(130), _rad(-85), false, arc(_green))
      ..drawArc(ring, _rad(45), _rad(-45), false, arc(_blue))
      ..drawRect(
        Rect.fromLTRB(
          center.dx,
          center.dy - stroke / 2,
          center.dx + radius + stroke / 2,
          center.dy + stroke / 2,
        ),
        Paint()..color = _blue,
      );
  }

  @override
  bool shouldRepaint(GoogleLogoPainter oldDelegate) => false;
}
