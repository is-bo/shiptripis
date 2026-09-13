import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/env/app_config.dart';

void main() {
  test('release origin must be explicitly public and HTTPS', () {
    for (final value in [
      '',
      'http://10.0.2.2:8080',
      'https://localhost',
      'https://qa.invalid',
      'https://api.example/path',
      'https://user@api.example',
      'https://api.example?query=1',
    ]) {
      expect(() => AppConfig.validateReleaseOrigin(value), throwsStateError);
    }
    expect(
      () => AppConfig.validateReleaseOrigin(
        'https://shiptrip-production-f7f7.up.railway.app',
      ),
      returnsNormally,
    );
  });
}
