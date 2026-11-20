/// The installed build's version, as the platform reports it.
///
/// Read from the platform rather than pinned in Dart, so the profile footer
/// always names the build that is actually installed: the version and build
/// number come from `pubspec.yaml` through `--build-name` / `--build-number`.
/// Only the footer waits on it; nothing else depends on the answer.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

/// "1.2.0 (34)", or "1.2.0" on a platform that reports no build number.
///
/// Not retried: a platform that cannot name its own version will not learn
/// it a few seconds later, and the footer simply stays empty.
final appVersionProvider = FutureProvider<String>((ref) async {
  final info = await PackageInfo.fromPlatform();
  return info.buildNumber.isEmpty
      ? info.version
      : '${info.version} (${info.buildNumber})';
}, retry: (_, _) => null);
