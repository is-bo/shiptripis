import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/rating.dart';

import 'support/fake_api.dart';

Future<List<Rating>> _ratingsReady(ProviderContainer container) async {
  for (var attempt = 0; attempt < 20; attempt++) {
    final value = container.read(receivedRatingsProvider);
    if (value.hasValue) return value.requireValue;
    await Future<void>.delayed(Duration.zero);
  }
  throw StateError('Ratings did not load');
}

Map<String, Object?> _rating(String comment) => {
  'id': 101,
  'deal_id': 55,
  'score': 5,
  'tags': ['punctual'],
  'comment': comment,
  'created_at': '2026-09-01T10:00:00Z',
};

void main() {
  test(
    'A ratings clear on logout and B never observes A provider data',
    () async {
      var accountId = 42;
      var ratingsCalls = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          return FakeResponse(200, {...meFixture(), 'id': accountId});
        })
        ..handle('GET', '/api/users/me/ratings', (_) {
          ratingsCalls++;
          return FakeResponse(200, [
            _rating(accountId == 42 ? 'A private' : 'B private'),
          ]);
        })
        ..on('POST', '/api/auth/sign-out', const FakeResponse(200, {}));
      final container = containerFor(backend);
      addTearDown(container.dispose);
      await container.read(sessionProvider.notifier).restore();
      final subscription = container.listen(receivedRatingsProvider, (_, _) {});
      addTearDown(subscription.close);

      expect((await _ratingsReady(container)).single.comment, 'A private');
      await container.read(sessionProvider.notifier).signOut();
      expect(container.read(receivedRatingsProvider).requireValue, isEmpty);

      accountId = 99;
      await container.read(sessionProvider.notifier).restore();
      expect(container.read(accountProvider)?.id, 99);
      expect(
        container
            .read(receivedRatingsProvider)
            .value
            ?.any((rating) => rating.comment == 'A private'),
        isNot(true),
      );
      expect((await _ratingsReady(container)).single.comment, 'B private');
      expect(ratingsCalls, 2);
    },
  );

  test(
    'A logout and A login fetches changed ratings in the new session',
    () async {
      var comment = 'A old';
      var ratingsCalls = 0;
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..handle('GET', '/api/users/me/ratings', (_) {
          ratingsCalls++;
          return FakeResponse(200, [_rating(comment)]);
        })
        ..on('POST', '/api/auth/sign-out', const FakeResponse(200, {}));
      final container = containerFor(backend);
      addTearDown(container.dispose);
      await container.read(sessionProvider.notifier).restore();
      final subscription = container.listen(receivedRatingsProvider, (_, _) {});
      addTearDown(subscription.close);

      expect((await _ratingsReady(container)).single.comment, 'A old');
      await container.read(sessionProvider.notifier).signOut();
      expect(container.read(receivedRatingsProvider).requireValue, isEmpty);
      comment = 'A updated';
      await container.read(sessionProvider.notifier).restore();
      expect(
        container
            .read(receivedRatingsProvider)
            .value
            ?.any((rating) => rating.comment == 'A old'),
        isNot(true),
      );
      expect((await _ratingsReady(container)).single.comment, 'A updated');
      expect(ratingsCalls, 2);
    },
  );

  test(
    'an in-flight A rating response cannot enter B provider state',
    () async {
      var accountId = 42;
      final started = Completer<void>();
      final oldResponse = Completer<FakeResponse>();
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          return FakeResponse(200, {...meFixture(), 'id': accountId});
        })
        ..handle('GET', '/api/users/me/ratings', (_) {
          if (accountId == 42) {
            started.complete();
            return oldResponse.future;
          }
          return FakeResponse(200, [_rating('B private')]);
        })
        ..on('POST', '/api/auth/sign-out', const FakeResponse(200, {}));
      final container = containerFor(backend);
      addTearDown(container.dispose);
      await container.read(sessionProvider.notifier).restore();
      final subscription = container.listen(receivedRatingsProvider, (_, _) {});
      addTearDown(subscription.close);
      await started.future;

      await container.read(sessionProvider.notifier).signOut();
      expect(container.read(receivedRatingsProvider).requireValue, isEmpty);
      accountId = 99;
      await container.read(sessionProvider.notifier).restore();
      expect((await _ratingsReady(container)).single.comment, 'B private');

      oldResponse.complete(FakeResponse(200, [_rating('A late')]));
      await Future<void>.delayed(Duration.zero);
      expect(
        container.read(receivedRatingsProvider).requireValue.single.comment,
        'B private',
      );
    },
  );
}
