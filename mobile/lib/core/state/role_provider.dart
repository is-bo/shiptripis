import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';

enum AppRole { sender, traveler }

/// User-controlled override for users whose server role is "both".
/// Pure senders / pure travelers ignore this — their role is server-locked.
class RoleNotifier extends Notifier<AppRole> {
  @override
  AppRole build() => AppRole.sender;
  void set(AppRole r) => state = r;
  void toggle() =>
      state = state == AppRole.sender ? AppRole.traveler : AppRole.sender;
}

final roleProvider = NotifierProvider<RoleNotifier, AppRole>(RoleNotifier.new);

/// Server-locked role: pure-sender users always render in sender UI; pure-traveler
/// users always render in traveler UI; "both" users fall back to the toggle.
/// Reads the current AuthUser.role from the auth notifier.
final effectiveRoleProvider = Provider<AppRole>((ref) {
  final auth = ref.watch(authNotifierProvider);
  final serverRole = (auth is AuthSignedIn) ? auth.user.role : 'sender';
  switch (serverRole) {
    case 'traveler':
      return AppRole.traveler;
    case 'sender':
      return AppRole.sender;
    default: // 'both' (or any unexpected value): defer to UI toggle.
      return ref.watch(roleProvider);
  }
});

/// True when the user can switch sides at runtime (server role == 'both').
final canSwitchRoleProvider = Provider<bool>((ref) {
  final auth = ref.watch(authNotifierProvider);
  return auth is AuthSignedIn && auth.user.role == 'both';
});
