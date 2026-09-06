import 'dart:async';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/token_store.dart';
import 'package:shiptrip/data/auth_repository.dart';

import 'support/fake_api.dart';

void main() {
  test(
    'a delayed profile refresh cannot revive the previous account',
    () async {
      final delayedProfile = Completer<FakeResponse>();
      var meReads = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          meReads++;
          if (meReads == 1) return FakeResponse(200, meFixture());
          return delayedProfile.future;
        })
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
        ..on(
          'POST',
          '/api/auth/sign-in',
          FakeResponse(200, {
            'access': 'new-access',
            'refresh': 'new-refresh',
            'user': {...meFixture(), 'id': 99, 'email': 'new@example.com'},
          }),
        );
      final container = containerFor(backend);
      addTearDown(container.dispose);
      container.read(sessionProvider);
      await _waitFor(() => container.read(sessionProvider) is SessionSignedIn);

      final refresh = container.read(sessionProvider.notifier).refreshAccount();
      await _waitFor(() => meReads == 2);
      await container.read(sessionProvider.notifier).signOut();
      await container
          .read(sessionProvider.notifier)
          .signIn(email: 'new@example.com', password: 'correct horse');
      delayedProfile.complete(FakeResponse(200, meFixture()));
      await refresh;

      final session = container.read(sessionProvider);
      expect(session, isA<SessionSignedIn>());
      expect((session as SessionSignedIn).account.id, 99);
    },
  );

  test('reconnect probe uses the existing single-flight HTTP flow', () async {
    var meReads = 0;
    final backend = FakeBackend()
      ..handle('GET', '/api/me', (_) {
        meReads++;
        return meReads <= 2
            ? const FakeResponse(401)
            : FakeResponse(200, meFixture());
      })
      ..on(
        'POST',
        '/api/auth/refresh',
        const FakeResponse(200, {'access': 'rotated-access'}),
      );
    final tokens = FakeTokenStore();
    final api = apiClientFor(backend, tokens);
    addTearDown(() => api.raw.close(force: true));

    final results = await Future.wait([
      api.getObject('/api/me'),
      api.getObject('/api/me'),
    ]);

    expect(results, everyElement(meFixture()));
    expect(backend.to('POST', '/api/auth/refresh'), hasLength(1));
  });

  test('an old 401 is never replayed with the next account token', () async {
    final staleResponse = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..handle('GET', '/api/protected', (_) => staleResponse.future)
      ..on(
        'POST',
        '/api/auth/sign-in',
        FakeResponse(200, {
          'access': 'new-access',
          'refresh': 'new-refresh',
          'user': {...meFixture(), 'id': 99, 'email': 'new@example.com'},
        }),
      );
    final tokens = _MemoryTokenStore('old-access', 'old-refresh');
    final api = apiClientFor(backend, tokens);
    final auth = AuthRepository(api, tokens);
    addTearDown(() => api.raw.close(force: true));

    final oldRead = api.getObject('/api/protected');
    await _waitFor(() => backend.to('GET', '/api/protected').isNotEmpty);
    await auth.signIn(email: 'new@example.com', password: 'secret');
    staleResponse.complete(const FakeResponse(401));

    await expectLater(oldRead, throwsA(isA<Object>()));
    expect(backend.to('GET', '/api/protected'), hasLength(1));
    expect(backend.to('POST', '/api/auth/refresh'), isEmpty);
    expect(await tokens.readAccess(), 'new-access');
  });

  test(
    'a successful old-account read is discarded after login changes',
    () async {
      final staleResponse = Completer<FakeResponse>();
      final backend = FakeBackend()
        ..handle('GET', '/api/protected', (_) => staleResponse.future)
        ..on(
          'POST',
          '/api/auth/sign-in',
          FakeResponse(200, {
            'access': 'new-access',
            'refresh': 'new-refresh',
            'user': {...meFixture(), 'id': 99, 'email': 'new@example.com'},
          }),
        );
      final tokens = _MemoryTokenStore('old-access', 'old-refresh');
      final api = apiClientFor(backend, tokens);
      final auth = AuthRepository(api, tokens);
      addTearDown(() => api.raw.close(force: true));

      final oldRead = api.getObject('/api/protected');
      await _waitFor(() => backend.to('GET', '/api/protected').isNotEmpty);
      await auth.signIn(email: 'new@example.com', password: 'secret');
      staleResponse.complete(const FakeResponse(200, {'private': 'old-data'}));

      await expectLater(
        oldRead,
        throwsA(
          isA<ApiException>().having(
            (error) => error.kind,
            'kind',
            ApiFailureKind.cancelled,
          ),
        ),
      );
    },
  );

  test('an in-flight refresh cannot overwrite logout and new login', () async {
    final oldRefresh = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..on('GET', '/api/protected', const FakeResponse(401))
      ..handle('POST', '/api/auth/refresh', (_) => oldRefresh.future)
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
      ..on(
        'POST',
        '/api/auth/sign-in',
        FakeResponse(200, {
          'access': 'new-access',
          'refresh': 'new-refresh',
          'user': {...meFixture(), 'id': 99, 'email': 'new@example.com'},
        }),
      );
    final tokens = _MemoryTokenStore('old-access', 'old-refresh');
    final api = apiClientFor(backend, tokens);
    final auth = AuthRepository(api, tokens);
    addTearDown(() => api.raw.close(force: true));

    final oldRead = api.getObject('/api/protected');
    await _waitFor(() => backend.to('POST', '/api/auth/refresh').isNotEmpty);
    await auth.signOut();
    await auth.signIn(email: 'new@example.com', password: 'secret');
    oldRefresh.complete(
      const FakeResponse(200, {
        'access': 'stale-rotated-access',
        'refresh': 'stale-rotated-refresh',
      }),
    );

    await expectLater(oldRead, throwsA(isA<Object>()));
    expect(await tokens.readAccess(), 'new-access');
    expect(await tokens.readRefresh(), 'new-refresh');
    expect(backend.to('GET', '/api/protected'), hasLength(1));
  });

  for (final blockInstallation in [false, true]) {
    test(
      'logout delayed at ${blockInstallation ? 'installation' : 'refresh'} read cannot revoke the next login',
      () async {
        final tokens = _BlockingSignOutReadTokenStore(
          'old-access',
          'old-refresh',
          blockInstallation: blockInstallation,
        );
        final backend = FakeBackend()
          ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
          ..on(
            'POST',
            '/api/auth/sign-in',
            FakeResponse(200, {
              'access': 'new-access',
              'refresh': 'new-refresh',
              'user': {...meFixture(), 'id': 99},
            }),
          );
        final api = apiClientFor(backend, tokens);
        final auth = AuthRepository(api, tokens);
        addTearDown(() => api.raw.close(force: true));

        final logout = auth.signOut();
        await tokens.readStarted.future;
        await auth.signIn(email: 'next@example.com', password: 'secret');
        tokens.releaseRead.complete();
        await logout;

        expect(backend.to('POST', '/api/auth/sign-out'), isEmpty);
        expect(await tokens.readAccess(), 'new-access');
        expect(await tokens.readRefresh(), 'new-refresh');
      },
    );
  }

  test(
    'a request cannot adopt a login that changes during token read',
    () async {
      final tokens = _BlockingReadTokenStore('old-access', 'old-refresh');
      final backend = FakeBackend()
        ..on('GET', '/api/protected', const FakeResponse(200, {'ok': true}))
        ..on(
          'POST',
          '/api/auth/sign-in',
          FakeResponse(200, {
            'access': 'new-access',
            'refresh': 'new-refresh',
            'user': {...meFixture(), 'id': 99},
          }),
        );
      final api = apiClientFor(backend, tokens);
      final auth = AuthRepository(api, tokens);
      addTearDown(() => api.raw.close(force: true));

      final oldRead = api.getObject('/api/protected');
      await tokens.readStarted.future;
      await auth.signIn(email: 'next@example.com', password: 'secret');
      tokens.releaseRead.complete();

      await expectLater(oldRead, throwsA(isA<Object>()));
      expect(backend.to('GET', '/api/protected'), isEmpty);
    },
  );

  test(
    'a 401 cannot replay if identity changes during response token read',
    () async {
      final tokens = _SecondReadBlockingTokenStore('old-access', 'old-refresh');
      final backend = FakeBackend()
        ..on('GET', '/api/protected', const FakeResponse(401))
        ..on(
          'POST',
          '/api/auth/sign-in',
          FakeResponse(200, {
            'access': 'new-access',
            'refresh': 'new-refresh',
            'user': {...meFixture(), 'id': 99},
          }),
        );
      final api = apiClientFor(backend, tokens);
      final auth = AuthRepository(api, tokens);
      addTearDown(() => api.raw.close(force: true));

      final oldRead = api.getObject('/api/protected');
      await tokens.responseReadStarted.future;
      await auth.signIn(email: 'next@example.com', password: 'secret');
      tokens.releaseResponseRead.complete();

      await expectLater(oldRead, throwsA(isA<Object>()));
      expect(backend.to('GET', '/api/protected'), hasLength(1));
      expect(backend.to('POST', '/api/auth/refresh'), isEmpty);
    },
  );

  test('identity change during replay rejects the original request', () async {
    final tokens = _ReplayReadBlockingTokenStore('old-access', 'old-refresh');
    final backend = FakeBackend()
      ..on('GET', '/api/protected', const FakeResponse(401))
      ..on(
        'POST',
        '/api/auth/sign-in',
        FakeResponse(200, {
          'access': 'new-access',
          'refresh': 'new-refresh',
          'user': {...meFixture(), 'id': 99},
        }),
      );
    final api = apiClientFor(backend, tokens);
    final auth = AuthRepository(api, tokens);
    addTearDown(() => api.raw.close(force: true));

    final oldRead = api.getObject('/api/protected');
    await tokens.replayReadStarted.future;
    await auth.signIn(email: 'next@example.com', password: 'secret');
    tokens.releaseReplayRead.complete();

    await expectLater(
      oldRead.timeout(const Duration(seconds: 1)),
      throwsA(
        isA<ApiException>().having(
          (error) => error.kind,
          'kind',
          ApiFailureKind.cancelled,
        ),
      ),
    );
    expect(backend.to('GET', '/api/protected'), hasLength(1));
  });

  test(
    'terminal clear cannot expire credentials saved during its awaits',
    () async {
      final storage = _BlockingStorage()
        ..values['auth.access'] = 'old-access'
        ..values['auth.refresh'] = 'old-refresh';
      final tokens = TokenStore(storage);
      final identity = tokens.identityGeneration;

      final clearing = tokens.clearIfIdentityCurrent(identity);
      await storage.deleteStarted.future;
      final saving = tokens.save(access: 'new-access', refresh: 'new-refresh');
      storage.releaseDelete.complete();

      expect(await clearing, isFalse);
      await saving;
      expect(await tokens.readAccess(), 'new-access');
      expect(await tokens.readRefresh(), 'new-refresh');
    },
  );

  test('slower sign-in response cannot replace the newer login', () async {
    final first = Completer<FakeResponse>();
    final second = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle('POST', '/api/auth/sign-in', (request) {
        return request.body['email'] == 'first@example.com'
            ? first.future
            : second.future;
      });
    final tokens = _MemoryTokenStore('old-access', 'old-refresh');
    final container = containerFor(backend, tokens: tokens);
    addTearDown(container.dispose);
    container.read(sessionProvider);
    await _waitFor(() => container.read(sessionProvider) is SessionSignedIn);

    final firstLogin = container
        .read(sessionProvider.notifier)
        .signIn(email: 'first@example.com', password: 'secret');
    final secondLogin = container
        .read(sessionProvider.notifier)
        .signIn(email: 'second@example.com', password: 'secret');
    second.complete(
      FakeResponse(200, {
        'access': 'second-access',
        'refresh': 'second-refresh',
        'user': {...meFixture(), 'id': 202, 'email': 'second@example.com'},
      }),
    );
    await secondLogin;
    first.complete(
      FakeResponse(200, {
        'access': 'first-access',
        'refresh': 'first-refresh',
        'user': {...meFixture(), 'id': 101, 'email': 'first@example.com'},
      }),
    );
    await expectLater(
      firstLogin,
      throwsA(
        isA<ApiException>().having(
          (error) => error.kind,
          'kind',
          ApiFailureKind.cancelled,
        ),
      ),
    );

    final session = container.read(sessionProvider) as SessionSignedIn;
    expect(session.account.id, 202);
    expect(await tokens.readAccess(), 'second-access');
    expect(await tokens.readRefresh(), 'second-refresh');
  });
}

Future<void> _waitFor(bool Function() condition) async {
  for (var attempt = 0; attempt < 100; attempt++) {
    if (condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  throw TimeoutException('Condition was not reached.');
}

class _MemoryTokenStore extends FakeTokenStore {
  _MemoryTokenStore(this._access, this._refresh) : super(refresh: null);

  String? _access;
  String? _refresh;

  @override
  Future<String?> readAccess() async => _access;

  @override
  Future<String?> readRefresh() async => _refresh;

  @override
  Future<void> save({required String access, required String refresh}) async {
    invalidateIdentity();
    _access = access;
    _refresh = refresh;
  }

  @override
  Future<bool> saveRefreshedIfCurrent({
    required int expectedIdentityGeneration,
    required String expectedRefresh,
    required String access,
    String? refresh,
  }) async {
    if (identityGeneration != expectedIdentityGeneration ||
        _refresh != expectedRefresh) {
      return false;
    }
    _access = access;
    if (refresh != null) _refresh = refresh;
    return identityGeneration == expectedIdentityGeneration;
  }

  @override
  Future<bool> saveAuthenticationIfCurrent({
    required int expectedIdentityGeneration,
    required String access,
    required String refresh,
  }) async {
    if (identityGeneration != expectedIdentityGeneration) return false;
    _access = access;
    _refresh = refresh;
    return identityGeneration == expectedIdentityGeneration;
  }

  @override
  Future<bool> clearIfIdentityCurrent(int expectedIdentityGeneration) async {
    if (identityGeneration != expectedIdentityGeneration) return false;
    invalidateIdentity();
    _access = null;
    _refresh = null;
    return true;
  }

  @override
  Future<void> clear() async {
    invalidateIdentity();
    _access = null;
    _refresh = null;
  }

  @override
  Future<String> readOrCreateInstallationId() async => 'installation';
}

class _BlockingReadTokenStore extends _MemoryTokenStore {
  _BlockingReadTokenStore(super._access, super._refresh);

  final readStarted = Completer<void>();
  final releaseRead = Completer<void>();
  bool _blocked = false;

  @override
  Future<String?> readAccess() async {
    if (!_blocked) {
      _blocked = true;
      readStarted.complete();
      await releaseRead.future;
    }
    return super.readAccess();
  }
}

class _SecondReadBlockingTokenStore extends _MemoryTokenStore {
  _SecondReadBlockingTokenStore(super._access, super._refresh);

  final responseReadStarted = Completer<void>();
  final releaseResponseRead = Completer<void>();
  int _reads = 0;

  @override
  Future<String?> readAccess() async {
    _reads++;
    if (_reads == 2) {
      responseReadStarted.complete();
      await releaseResponseRead.future;
    }
    return super.readAccess();
  }
}

class _BlockingSignOutReadTokenStore extends _MemoryTokenStore {
  _BlockingSignOutReadTokenStore(
    super._access,
    super._refresh, {
    this.blockInstallation = false,
  });

  final bool blockInstallation;
  final readStarted = Completer<void>();
  final releaseRead = Completer<void>();
  bool _blocked = false;

  @override
  Future<String?> readRefresh() async {
    if (!blockInstallation) await _blockOnce();
    return super.readRefresh();
  }

  @override
  Future<String> readOrCreateInstallationId() async {
    if (blockInstallation) await _blockOnce();
    return super.readOrCreateInstallationId();
  }

  Future<void> _blockOnce() async {
    if (!_blocked) {
      _blocked = true;
      readStarted.complete();
      await releaseRead.future;
    }
  }
}

class _ReplayReadBlockingTokenStore extends _MemoryTokenStore {
  _ReplayReadBlockingTokenStore(super._access, super._refresh);

  final replayReadStarted = Completer<void>();
  final releaseReplayRead = Completer<void>();
  int _reads = 0;

  @override
  Future<String?> readAccess() async {
    _reads++;
    if (_reads == 2) return 'rotated-old-access';
    if (_reads == 3) {
      replayReadStarted.complete();
      await releaseReplayRead.future;
    }
    return super.readAccess();
  }
}

class _BlockingStorage extends FlutterSecureStorage {
  _BlockingStorage();

  final values = <String, String>{};
  final deleteStarted = Completer<void>();
  final releaseDelete = Completer<void>();
  bool _blocked = false;

  @override
  Future<String?> read({
    required String key,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => values[key];

  @override
  Future<void> write({
    required String key,
    required String? value,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }

  @override
  Future<void> delete({
    required String key,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (!_blocked && key == 'auth.access') {
      _blocked = true;
      deleteStarted.complete();
      await releaseDelete.future;
    }
    values.remove(key);
  }
}
