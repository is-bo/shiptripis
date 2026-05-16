import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/state/role_provider.dart';
import 'sender_home.dart';
import 'traveler_home.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final role = ref.watch(effectiveRoleProvider);
    return role == AppRole.sender ? const SenderHome() : const TravelerHome();
  }
}
