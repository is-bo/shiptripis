/// Tests for B2: handover-code plaintext must survive an app restart, so the
/// user is never pushed into regenerating (which invalidates the code the
/// counterparty may already hold).
library;

import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/verification/handover_code_store.dart';

/// In-memory stand-in for the platform keystore. The real one needs a
/// MethodChannel, which isn't available in a unit test.
class _FakeSecureStorage extends FlutterSecureStorage {
  const _FakeSecureStorage(this._backing);
  final Map<String, String> _backing;

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async =>
      _backing[key];

  @override
  Future<void> write({
    required String key,
    required String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (value == null) {
      _backing.remove(key);
    } else {
      _backing[key] = value;
    }
  }

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    _backing.remove(key);
  }
}

StoredHandoverCode _code(int mid, String kind, String digits) =>
    StoredHandoverCode(
      matchId: mid,
      kind: kind,
      code: digits,
      issuedAt: DateTime.utc(2026, 7, 30, 12),
    );

void main() {
  late Map<String, String> backing;
  late HandoverCodeStore store;

  setUp(() {
    backing = {};
    store = HandoverCodeStore(_FakeSecureStorage(backing));
  });

  test('a saved code is readable again (survives a restart)', () async {
    await store.save(_code(7, 'pickup', '123456'));

    // A fresh store over the same backing == relaunching the app.
    final reopened = HandoverCodeStore(_FakeSecureStorage(backing));
    final all = await reopened.readAll();

    expect(all[HandoverCodeStore.keyFor(7, 'pickup')]?.code, '123456');
  });

  test('pickup and delivery codes for one match coexist', () async {
    await store.save(_code(7, 'pickup', '111111'));
    await store.save(_code(7, 'delivery', '222222'));

    final all = await store.readAll();
    expect(all[HandoverCodeStore.keyFor(7, 'pickup')]?.code, '111111');
    expect(all[HandoverCodeStore.keyFor(7, 'delivery')]?.code, '222222');
  });

  test('re-saving the same match+kind supersedes the old code', () async {
    await store.save(_code(7, 'pickup', '111111'));
    await store.save(_code(7, 'pickup', '999999'));

    final all = await store.readAll();
    expect(all.length, 1);
    expect(all[HandoverCodeStore.keyFor(7, 'pickup')]?.code, '999999');
  });

  test('remove drops only the targeted code', () async {
    await store.save(_code(7, 'pickup', '111111'));
    await store.save(_code(8, 'pickup', '222222'));

    await store.remove(7, 'pickup');

    final all = await store.readAll();
    expect(all.containsKey(HandoverCodeStore.keyFor(7, 'pickup')), isFalse);
    expect(all[HandoverCodeStore.keyFor(8, 'pickup')]?.code, '222222');
  });

  test('clear wipes everything (sign-out)', () async {
    await store.save(_code(7, 'pickup', '111111'));
    await store.save(_code(8, 'delivery', '222222'));

    await store.clear();

    expect(await store.readAll(), isEmpty);
  });

  test('a corrupt blob degrades to empty instead of throwing', () async {
    backing['handover.codes'] = 'not json at all{{{';
    expect(await store.readAll(), isEmpty);
  });

  test('entries missing required fields are skipped, good ones kept',
      () async {
    backing['handover.codes'] = jsonEncode({
      '7:pickup': {'match_id': 7, 'kind': 'pickup'}, // no code / issued_at
      '8:pickup': {
        'match_id': 8,
        'kind': 'pickup',
        'code': '222222',
        'issued_at': '2026-07-30T12:00:00.000Z',
      },
    });

    final all = await store.readAll();
    expect(all.containsKey('7:pickup'), isFalse);
    expect(all['8:pickup']?.code, '222222');
  });

  test('reading an empty store returns empty, not null', () async {
    expect(await store.readAll(), isEmpty);
  });
}
