/// Runs before every test file in this folder (Flutter's test-config hook).
///
/// The test platform answers for the installed build the way a phone does, so
/// no screen in any test depends on a platform channel failing.
library;

import 'dart:async';

import 'package:package_info_plus/package_info_plus.dart';

/// The build every test runs as. A test that checks the version reads these.
const testAppVersion = '1.4.2';
const testBuildNumber = '57';

Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  PackageInfo.setMockInitialValues(
    appName: 'Wassla',
    packageName: 'eu.wassla.app',
    version: testAppVersion,
    buildNumber: testBuildNumber,
    buildSignature: '',
  );
  await testMain();
}
