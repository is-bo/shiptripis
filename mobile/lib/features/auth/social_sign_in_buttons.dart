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
/// the generic copy. Once signed in, the sign-in ends in [finishSignIn], as
/// every other one does.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart'
    show AppleLogoPainter;

import '../../app/app_settings.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/auth/social_sign_in.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/communication_language.dart';
import '../../l10n/app_localizations.dart';
import 'account_gate.dart';

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
      // On the account screen this sign-in is finished here, below, not by
      // the screen's own listener.
      final signedIn = await AccountGateScreen.finishingHere(
        context,
        () => switch (provider) {
          SocialProvider.google => auth.google(language),
          SocialProvider.apple => auth.apple(language),
        },
      );
      if (signedIn && mounted) finishSignIn(context, widget.flow);
    } on SocialSignInFailure {
      if (mounted) setState(() => _error = _failed(provider));
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = _describe(provider, error));
    } on Object {
      // The keystore, or a sign-in that another one overtook: nothing the
      // person can act on but trying again.
      if (mounted) setState(() => _error = _failed(provider));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
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
        disabledBackgroundColor: fill,
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

/// Google's "G", in its four colours, drawn from the official mark's paths
/// (Google's sign-in branding, on a 48 by 48 grid) and scaled to fit.
class GoogleLogoPainter extends CustomPainter {
  const GoogleLogoPainter();

  static const _grid = 48.0;

  static final _marks = <(Color, Path)>[
    (
      const Color(0xFFEA4335),
      _svgPath(
        'M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 '
        '14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z',
      ),
    ),
    (
      const Color(0xFF4285F4),
      _svgPath(
        'M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 '
        '5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z',
      ),
    ),
    (
      const Color(0xFFFBBC05),
      _svgPath(
        'M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19'
        'C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z',
      ),
    ),
    (
      const Color(0xFF34A853),
      _svgPath(
        'M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 '
        '2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z',
      ),
    ),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.shortestSide / _grid;
    canvas
      ..save()
      ..translate(
        (size.width - _grid * scale) / 2,
        (size.height - _grid * scale) / 2,
      )
      ..scale(scale);
    for (final (color, path) in _marks) {
      canvas.drawPath(path, Paint()..color = color);
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(GoogleLogoPainter oldDelegate) => false;
}

/// The SVG path commands the mark uses (M, C, S, L, H, V and Z, absolute or
/// relative), as a [Path].
Path _svgPath(String data) {
  final tokens = RegExp(
    r'[MCSLHVZmcslhvz]|-?(?:\d+\.?\d*|\.\d+)',
  ).allMatches(data).map((m) => m.group(0)!).toList();
  final path = Path();
  var at = Offset.zero;
  var lastControl = Offset.zero;
  var command = '';
  var i = 0;
  double number() => double.parse(tokens[i++]);
  Offset point(bool relative) {
    final p = Offset(number(), number());
    return relative ? at + p : p;
  }

  while (i < tokens.length) {
    if (RegExp('[A-Za-z]').hasMatch(tokens[i])) command = tokens[i++];
    final relative = command == command.toLowerCase();
    switch (command.toUpperCase()) {
      case 'M':
        at = point(relative);
        path.moveTo(at.dx, at.dy);
        // Pairs after a move are lines.
        command = relative ? 'l' : 'L';
      case 'L':
        at = point(relative);
        path.lineTo(at.dx, at.dy);
      case 'H':
        final x = number();
        at = Offset(relative ? at.dx + x : x, at.dy);
        path.lineTo(at.dx, at.dy);
      case 'V':
        final y = number();
        at = Offset(at.dx, relative ? at.dy + y : y);
        path.lineTo(at.dx, at.dy);
      case 'C' || 'S':
        final c1 = command.toUpperCase() == 'S'
            ? at * 2 - lastControl
            : point(relative);
        final c2 = point(relative);
        final end = point(relative);
        path.cubicTo(c1.dx, c1.dy, c2.dx, c2.dy, end.dx, end.dy);
        lastControl = c2;
        at = end;
        continue;
      case 'Z':
        path.close();
      default:
        throw FormatException('Unsupported path command', command);
    }
    lastControl = at;
  }
  return path;
}
