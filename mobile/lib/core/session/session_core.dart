/// The phone's session: one stored record, one writer, one way in and one way
/// out (plan rules S-1, S-2, S-3 and S-5).
///
/// The record is one document under one key: the current sign-in (its `sid`,
/// the account snapshot, the access and refresh tokens) or none, and the
/// sign-ins whose end the server has not confirmed yet. Every change is one
/// write of that key, queued behind the one before: storage first, then the
/// copy in memory, then the answer to the caller. A write that throws changed
/// nothing.
///
/// [SessionCore] is created once, in `main()`, outside every provider
/// container, and it is the only code that reads or writes the record. Only
/// the UI isolate touches it; the push background handler does not.
library;

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../domain/account.dart';
import '../api/api_exception.dart';
import '../env/app_config.dart';

/// Why a sign-in ended. Nothing else ends one: a throttle, a refusal of one
/// action, a server error or no network keeps the member signed in.
enum EndReason {
  /// The member signed out.
  signedOut,

  /// The server refused the refresh token that is current.
  refused,

  /// The account was deleted.
  deleted,
}

/// One sign-in the server issued to this phone.
@immutable
class SignIn {
  const SignIn({
    required this.sid,
    required this.account,
    required this.access,
    required this.refresh,
  });

  /// The server's id of the sign-in, the `sid` claim of its tokens.
  final String sid;

  /// The account as last shown. Stored as its snapshot fields only.
  final Account account;
  final String access;
  final String refresh;

  SignIn copyWith({Account? account, String? access, String? refresh}) =>
      SignIn(
        sid: sid,
        account: account ?? this.account,
        access: access ?? this.access,
        refresh: refresh ?? this.refresh,
      );
}

/// A sign-in that ended on this phone and whose end the server has not
/// confirmed. Its refresh token is the whole proof the server needs.
@immutable
class EndedSignIn {
  const EndedSignIn(this.sid, this.refresh);
  final String sid;
  final String refresh;
}

/// The stored document. A state it cannot express cannot be stored: there is
/// one current sign-in or none.
@immutable
class SessionRecord {
  const SessionRecord({this.current, this.ended = const []});

  static const empty = SessionRecord();

  final SignIn? current;
  final List<EndedSignIn> ended;

  String encode() => jsonEncode({
    'current': switch (current) {
      null => null,
      final SignIn s => {
        'sid': s.sid,
        'account': s.account.toSnapshotJson(),
        'access': s.access,
        'refresh': s.refresh,
      },
    },
    'ended': [
      for (final e in ended) {'sid': e.sid, 'refresh': e.refresh},
    ],
  });

  /// Throws on anything that is not a record this build wrote.
  static SessionRecord decode(String raw) {
    final json = jsonDecode(raw) as Map<String, dynamic>;
    final current = json['current'] as Map<String, dynamic>?;
    SignIn? signIn;
    if (current != null) {
      final account = Account.fromJson(
        current['account'] as Map<String, dynamic>,
      );
      if (account.id <= 0) throw const FormatException('account');
      signIn = SignIn(
        sid: _text(current['sid']),
        account: account,
        access: _text(current['access']),
        refresh: _text(current['refresh']),
      );
    }
    return SessionRecord(
      current: signIn,
      ended: [
        for (final e in json['ended'] as List<dynamic>)
          EndedSignIn(_text(e['sid']), _text(e['refresh'])),
      ],
    );
  }

  static String _text(Object? value) => value is String && value.isNotEmpty
      ? value
      : throw const FormatException('text');
}

/// The phone could not store a change to the session, so it did not happen:
/// a sign-in that was issued but not kept, or a sign-out the member is still
/// signed in after.
class SessionNotSaved implements Exception {
  const SessionNotSaved();
}

/// The one sign-in attempt in progress. Held by whoever reserved it.
final class SignInAttempt {
  SignInAttempt._();
}

class SessionCore extends ChangeNotifier {
  SessionCore({
    FlutterSecureStorage? storage,
    Dio? http,
    Future<void> Function()? deletePushToken,
  }) : _storage = storage ?? _platformStorage,
       _http = (http ?? Dio())
         ..options = BaseOptions(
           baseUrl: AppConfig.apiBaseUrl,
           connectTimeout: AppConfig.connectTimeout,
           receiveTimeout: AppConfig.requestTimeout,
           sendTimeout: AppConfig.requestTimeout,
           headers: {'Accept': 'application/json'},
           // Every answer is data here; the sender reads the status itself.
           validateStatus: (_) => true,
         ),
       _deletePushToken = deletePushToken ?? (() async {});

  static const _platformStorage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(
      // Readable only after the first unlock since a restart, and never
      // copied into an iCloud backup. An iPhone can start the app before that
      // unlock, which is why a failed read waits for the foreground (`load`).
      accessibility: KeychainAccessibility.first_unlock_this_device,
    ),
  );

  /// The one key the record is stored under.
  static const recordKey = 'session.record';

  /// A keystore that never answers must not hold the app on its splash.
  static const _readBudget = Duration(seconds: 5);

  static const _signOutPath = '/api/auth/sign-out';

  final FlutterSecureStorage _storage;
  final Dio _http;
  final Future<void> Function() _deletePushToken;

  /// Null until the record has been read. Until then nothing is written.
  SessionRecord? _record;
  Future<void> _queue = Future<void>.value();
  SignInAttempt? _attempt;
  EndReason? _notice;

  bool get loaded => _record != null;

  /// The current sign-in, or null: signed out, or not read yet.
  SignIn? get current => _record?.current;

  /// True while a sign-in attempt is open. Every sign-in control reads it.
  bool get busy => _attempt != null;

  /// Why the last sign-in ended, until the member signs in again or closes
  /// the notice that says so.
  EndReason? get notice => _notice;

  /// The access token of [sid], only while [sid] is the current sign-in.
  String? accessFor(String sid) {
    final signIn = current;
    return signIn != null && signIn.sid == sid ? signIn.access : null;
  }

  /// The server's id of the sign-in [token] belongs to, or null.
  static String? sidOf(String token) {
    final parts = token.split('.');
    if (parts.length != 3) return null;
    try {
      final payload = jsonDecode(
        utf8.decode(base64Url.decode(base64Url.normalize(parts[1]))),
      );
      final sid = payload is Map ? payload['sid'] : null;
      return sid is String && sid.isNotEmpty ? sid : null;
    } on FormatException {
      return null;
    }
  }

  // ---------------------------------------------------------------------------
  // Reading
  // ---------------------------------------------------------------------------

  /// Reads the record, once. Run at launch and on every return to the
  /// foreground until a read succeeds.
  ///
  /// A read that fails with the app in the background is waited out: an
  /// iPhone keeps the store closed between a restart and the first unlock,
  /// and may start the app in that time. A read that fails with the app on
  /// screen, or a record that cannot be parsed, is lost for good: the phone
  /// stores an empty record, deletes its push token so no earlier sign-in can
  /// show a push here, and the member is signed out.
  Future<void> load() => _serial(() async {
    if (_record != null) return;
    final String? raw;
    try {
      raw = await _storage.read(key: recordKey).timeout(_readBudget);
    } on Object {
      if (WidgetsBinding.instance.lifecycleState != AppLifecycleState.resumed) {
        return;
      }
      return _lose();
    }
    final SessionRecord record;
    try {
      record = raw == null ? SessionRecord.empty : SessionRecord.decode(raw);
    } on Object {
      return _lose();
    }
    _record = record;
    notifyListeners();
    unawaited(sendEnded());
  });

  /// The app came to the foreground.
  void resumed() => loaded ? unawaited(sendEnded()) : unawaited(load());

  Future<void> _lose() async {
    try {
      await _storage.write(key: recordKey, value: SessionRecord.empty.encode());
    } on Object {
      // Signed out all the same; the next launch finds the same loss.
    }
    _record = SessionRecord.empty;
    notifyListeners();
    unawaited(_erasePushToken());
  }

  /// Retried until it succeeds, waiting twice as long each time, up to five
  /// minutes.
  Future<void> _erasePushToken() async {
    for (var wait = const Duration(seconds: 2); ; ) {
      try {
        return await _deletePushToken();
      } on Object {
        await Future<void>.delayed(wait);
        if (wait < const Duration(minutes: 5)) wait *= 2;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Signing in (S-2)
  // ---------------------------------------------------------------------------

  /// Reserves the one sign-in attempt, before the caller's first await. Null
  /// when it cannot start: someone is signed in, the record is not read yet,
  /// or another attempt is open. A second member starts from signed out.
  SignInAttempt? reserve() {
    if (_record == null || current != null || _attempt != null) return null;
    final attempt = _attempt = SignInAttempt._();
    notifyListeners();
    return attempt;
  }

  /// Ends [attempt] without a sign-in: it was answered with a refusal, an
  /// error or the HTTP timeout, or the person closed a provider's sheet.
  void release(SignInAttempt attempt) {
    if (!identical(_attempt, attempt)) return;
    _attempt = null;
    notifyListeners();
  }

  /// Stores the sign-in the server issued for [attempt]. If the phone cannot
  /// store it, that sign-in is ended on the server, once, from memory, and
  /// [SessionNotSaved] is thrown.
  Future<void> signedIn(SignInAttempt attempt, SignIn signIn) =>
      _serial(() async {
        if (!identical(_attempt, attempt)) return;
        try {
          await _commit(
            SessionRecord(current: signIn, ended: _record!.ended),
            clearNotice: true,
          );
        } on Object {
          unawaited(_confirmEnd(signIn.refresh));
          throw const SessionNotSaved();
        } finally {
          release(attempt);
        }
      });

  // ---------------------------------------------------------------------------
  // The current sign-in
  // ---------------------------------------------------------------------------

  /// Replaces the tokens of [sid] after a refresh, only while [sid] is current
  /// and still holds [sentRefresh]. False when it was not replaced.
  Future<bool> replaceTokens(
    String sid, {
    required String sentRefresh,
    required String access,
    String? refresh,
  }) => _serial(() async {
    final signIn = current;
    if (signIn == null || signIn.sid != sid || signIn.refresh != sentRefresh) {
      return false;
    }
    await _commit(
      SessionRecord(
        current: signIn.copyWith(access: access, refresh: refresh),
        ended: _record!.ended,
      ),
    );
    return true;
  });

  /// Stores the account [sid] was last shown with, while [sid] is current.
  Future<void> updateAccount(String sid, Account account) => _serial(() async {
    final signIn = current;
    if (signIn == null || signIn.sid != sid) return;
    await _commit(
      SessionRecord(
        current: signIn.copyWith(account: account),
        ended: _record!.ended,
      ),
    );
  });

  /// The one exit (S-3). Ends [sid] only while it is the current sign-in and,
  /// for a refusal, only while [refusedRefresh] is still its refresh token: a
  /// refusal of a token another refresh already replaced says nothing.
  ///
  /// One write: current becomes none and the sign-in joins the ended list
  /// with its refresh token. Then memory, then the listeners, then the sender.
  /// If the write fails on a member's sign-out, the member stays signed in
  /// and [SessionNotSaved] is thrown. If it fails for a sign-in the server
  /// refused or deleted, it ends in memory; the next launch meets the same
  /// answer and ends it again.
  Future<void> end(String sid, EndReason reason, {String? refusedRefresh}) =>
      _serial(() async {
        final record = _record;
        final signIn = record?.current;
        if (record == null || signIn == null || signIn.sid != sid) return;
        if (refusedRefresh != null && signIn.refresh != refusedRefresh) return;
        final next = SessionRecord(
          ended: [...record.ended, EndedSignIn(sid, signIn.refresh)],
        );
        try {
          await _storage.write(key: recordKey, value: next.encode());
        } on Object {
          if (reason == EndReason.signedOut) throw const SessionNotSaved();
        }
        _record = next;
        _notice = reason == EndReason.signedOut ? null : reason;
        notifyListeners();
        unawaited(sendEnded());
      });

  /// The member closed the notice that their sign-in ended.
  void dismissNotice() {
    if (_notice == null) return;
    _notice = null;
    notifyListeners();
  }

  // ---------------------------------------------------------------------------
  // The sender (S-5)
  // ---------------------------------------------------------------------------

  /// Posts every ended sign-in to the server with its own refresh token and
  /// no other credential. An entry leaves the list only when the server
  /// confirms the end; every other answer keeps it for the next send: after
  /// an end, at launch, and on every return to the foreground.
  Future<void> sendEnded() async {
    for (final entry in _record?.ended ?? const <EndedSignIn>[]) {
      if (!await _confirmEnd(entry.refresh)) continue;
      try {
        await _serial(() async {
          final record = _record!;
          await _commit(
            SessionRecord(
              current: record.current,
              ended: [
                for (final e in record.ended)
                  if (e.sid != entry.sid) e,
              ],
            ),
          );
        });
      } on Object {
        // Kept, and sent again: the server answers a repeat the same way.
      }
    }
  }

  /// True when the server says the sign-in has ended (205), or that the token
  /// can never prove one (400 `sign_out_proof_invalid`).
  Future<bool> _confirmEnd(String refresh) async {
    try {
      final response = await _http.post<dynamic>(
        _signOutPath,
        data: {'refresh': refresh},
      );
      return switch (response.statusCode) {
        205 => true,
        400 =>
          ApiException.fromResponse(response).code.raw ==
              'sign_out_proof_invalid',
        _ => false,
      };
    } on Object {
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // The one writer
  // ---------------------------------------------------------------------------

  Future<void> _commit(SessionRecord next, {bool clearNotice = false}) async {
    await _storage.write(key: recordKey, value: next.encode());
    _record = next;
    if (clearNotice) _notice = null;
    notifyListeners();
  }

  Future<T> _serial<T>(Future<T> Function() operation) {
    final result = _queue.then((_) => operation());
    _queue = result.then<void>((_) {}, onError: (Object _, StackTrace _) {});
    return result;
  }
}
