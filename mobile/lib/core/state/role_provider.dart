import 'package:flutter_riverpod/flutter_riverpod.dart';

enum AppRole { sender, traveler }

class RoleNotifier extends Notifier<AppRole> {
  @override
  AppRole build() => AppRole.sender;
  void set(AppRole r) => state = r;
  void toggle() => state = state == AppRole.sender ? AppRole.traveler : AppRole.sender;
}

final roleProvider = NotifierProvider<RoleNotifier, AppRole>(RoleNotifier.new);
