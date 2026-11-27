/// P3B round four: the disk cache behind profile photos, run for real (a real
/// cache manager, a real folder, a fake network).
///
/// * What reaches the disk is the picture under its **version** and a record
///   with no signed address in it (spec 21.2).
/// * A load is named by address: two avatars with different addresses for one
///   version each make a request, an address that expired cannot fail a fresh
///   one, and the first success is the version's bytes for every later load.
library;

import 'dart:async';
import 'dart:io';

import 'package:file/file.dart' as pkg;
import 'package:file/local.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/media/avatar_cache.dart';
import 'package:shiptrip/domain/person_photo.dart';

import 'support/photo_cache.dart' show tinyPng;

class _Folder implements FileSystem {
  _Folder(this.directory);

  final Directory directory;

  @override
  Future<pkg.File> createFile(String name) async =>
      const LocalFileSystem().directory(directory.path).childFile(name);
}

class _Response implements FileServiceResponse {
  _Response(this.statusCode, [this._body]);

  @override
  final int statusCode;

  final Stream<List<int>>? _body;

  @override
  Stream<List<int>> get content => _body ?? Stream.value(tinyPng);

  @override
  int? get contentLength => tinyPng.length;

  @override
  DateTime get validTill => DateTime.now().add(const Duration(days: 1));

  @override
  String? get eTag => null;

  @override
  String get fileExtension => '.png';
}

/// The network: every address asked for is recorded, and an address with a gate
/// answers only when the test says so (with the status it chooses).
class _Network extends FileService {
  final requested = <String>[];
  final gates = <String, Completer<int>>{};

  /// An address with a body here answers at once, but its body is still
  /// arriving until the test closes it.
  final bodies = <String, StreamController<List<int>>>{};

  @override
  Future<FileServiceResponse> get(
    String url, {
    Map<String, String>? headers,
  }) async {
    requested.add(url);
    final gate = gates[url];
    return _Response(
      gate == null ? 200 : await gate.future,
      bodies[url]?.stream,
    );
  }
}

/// A record store that refuses to write, as a database that is full or broken.
class _RefusingRecords extends JsonCacheInfoRepository {
  _RefusingRecords(super.file) : super.withFile();

  @override
  Future<dynamic> updateOrInsert(CacheObject cacheObject) =>
      throw const FileSystemException('database is full');
}

class _Rig {
  _Rig._(this.directory, this.network, this.manager);

  /// [refuseRecords] makes the record store fail every write; [missingFolder]
  /// points the pictures at a folder that is not there, so a write fails.
  factory _Rig({bool refuseRecords = false, bool missingFolder = false}) {
    final directory = Directory.systemTemp.createTempSync('wassla-avatars');
    final network = _Network();
    final recordFile = File(
      '${directory.path}${Platform.pathSeparator}records.json',
    );
    final manager = AvatarCacheManager.at(
      records: refuseRecords
          ? _RefusingRecords(recordFile)
          : JsonCacheInfoRepository.withFile(recordFile),
      fileSystem: _Folder(
        missingFolder ? Directory('${directory.path}/not-there') : directory,
      ),
      fileService: network,
    );
    return _Rig._(directory, network, manager);
  }

  final Directory directory;
  final _Network network;
  final AvatarCacheManager manager;

  Future<FileResponse> load(PersonPhoto photo) =>
      manager.getFileStream(photo.url, key: avatarCacheKey(photo)).first;

  /// Lets the fire-and-forget record write finish, then closes the manager so
  /// the record is on disk.
  Future<String> record() async {
    await Future<void>.delayed(const Duration(milliseconds: 50));
    await manager.dispose();
    return File(
      '${directory.path}${Platform.pathSeparator}records.json',
    ).readAsStringSync();
  }
}

PersonPhoto _photo(String sig, {String version = 'v1'}) => PersonPhoto(
  url: 'https://media.test/photos/a.jpg?sig=$sig&Expires=999',
  version: version,
);

void main() {
  late _Rig rig;

  setUp(() => rig = _Rig());
  tearDown(() {
    try {
      rig.directory.deleteSync(recursive: true);
    } on FileSystemException {
      // The OS reclaims it.
    }
  });

  group('what reaches the disk', () {
    test(
      'the picture is stored by version, and the record holds no address',
      () async {
        final photo = _photo('SECRETSIGNATURE');

        final response = await rig.load(photo);
        expect(response, isA<FileInfo>());
        expect((response as FileInfo).file.readAsBytesSync(), tinyPng);

        final record = await rig.record();
        expect(record, contains('"key":"v1"'));
        expect(record, isNot(contains('SECRETSIGNATURE')));
        expect(record, isNot(contains('Expires')));
        expect(record, isNot(contains('https://')));
        expect(record, isNot(contains('media.test')));
        final names = rig.directory
            .listSync()
            .map((e) => e.path.split(Platform.pathSeparator).last)
            .join(' ');
        expect(names, isNot(contains('SECRETSIGNATURE')));
      },
    );

    test('the record names the version in the address column', () async {
      await rig.load(_photo('abc'));

      final record = await rig.record();

      expect(record, contains('"url":"v1"'));
    });

    test('a refused request stores nothing', () async {
      final photo = _photo('expired');
      rig.network.gates[photo.url] = Completer<int>()..complete(403);

      await expectLater(
        rig.load(photo),
        throwsA(isA<HttpExceptionWithStatus>()),
      );

      expect(await rig.manager.getFileFromCache('v1'), isNull);
      final record = await rig.record();
      expect(record, isNot(contains('expired')));
    });
  });

  group('what is loaded, and when', () {
    test(
      'a version already on disk answers any address without the network',
      () async {
        await rig.load(_photo('one'));
        expect(rig.network.requested, hasLength(1));

        final again = await rig.load(_photo('two'));

        expect(again, isA<FileInfo>());
        expect(rig.network.requested, hasLength(1), reason: 'served from disk');
      },
    );

    test('one address is one request, however many avatars ask', () async {
      final photo = _photo('same');
      final gate = rig.network.gates[photo.url] = Completer<int>();

      final first = rig.load(photo);
      final second = rig.load(photo);
      await Future<void>.delayed(const Duration(milliseconds: 30));
      expect(rig.network.requested, [photo.url]);

      gate.complete(200);
      await Future.wait([first, second]);
      expect(rig.network.requested, [photo.url]);
    });

    test(
      'a fresh address is not joined to an expired one still in flight',
      () async {
        final expired = _photo('expired');
        final fresh = _photo('fresh');
        final expiredGate = rig.network.gates[expired.url] = Completer<int>();

        final expiredLoad = rig.load(expired);
        final expiredOutcome = expectLater(
          expiredLoad,
          throwsA(isA<HttpExceptionWithStatus>()),
        );
        await Future<void>.delayed(const Duration(milliseconds: 30));

        // The first request is held; the fresh address makes its own.
        final freshResponse = await rig.load(fresh);

        expect(rig.network.requested, [expired.url, fresh.url]);
        expect(freshResponse, isA<FileInfo>());

        // The expired address now answers 403: that load fails, and the bytes of
        // the version, from the fresh address, are untouched.
        expiredGate.complete(403);
        await expiredOutcome;
        final stored = await rig.manager.getFileFromCache('v1');
        expect(stored, isNotNull);
        expect(stored!.file.readAsBytesSync(), tinyPng);

        // Every later load of the version, whatever its address, is from disk.
        await rig.load(_photo('later'));
        expect(rig.network.requested, hasLength(2));
      },
    );

    test('when both addresses answer, the version keeps one picture', () async {
      final a = _photo('a');
      final b = _photo('b');
      final gateA = rig.network.gates[a.url] = Completer<int>();
      final gateB = rig.network.gates[b.url] = Completer<int>();

      final loadA = rig.load(a);
      final loadB = rig.load(b);
      await Future<void>.delayed(const Duration(milliseconds: 30));
      gateA.complete(200);
      await loadA;
      gateB.complete(200);
      await loadB;

      expect(rig.network.requested, [a.url, b.url]);
      await Future<void>.delayed(const Duration(milliseconds: 50));
      final files = rig.directory
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.png'))
          .toList();
      expect(files, hasLength(1), reason: 'the second response was dropped');
    });
  });

  group('installing a version', () {
    test('two addresses whose bodies overlap still leave one file', () async {
      final a = _photo('a');
      final b = _photo('b');
      final bodyA = rig.network.bodies[a.url] = StreamController<List<int>>();

      final loadA = rig.load(a);
      await Future<void>.delayed(const Duration(milliseconds: 30));
      // A has answered and its body is streaming. B answers, in full, while A's
      // body is still open: B must not write a second file for the version.
      final loadB = rig.load(b);
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(rig.network.requested, [a.url, b.url], reason: 'independent');

      bodyA
        ..add(tinyPng)
        ..close().ignore();
      final responses = await Future.wait([loadA, loadB]);

      expect(responses, everyElement(isA<FileInfo>()));
      final files = rig.directory
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.png'))
          .toList();
      expect(
        files,
        hasLength(1),
        reason: 'the losing response was not written',
      );
      final stored = await rig.manager.getFileFromCache('v1');
      expect(stored!.file.readAsBytesSync(), tinyPng);
    });

    test('a body that never finishes holds up no other address', () async {
      final a = _photo('a');
      final b = _photo('b');
      rig.network.bodies[a.url] = StreamController<List<int>>();

      final loadA = rig.load(a);
      loadA.ignore();
      await Future<void>.delayed(const Duration(milliseconds: 30));
      final loadB = rig.load(b);

      final response = await loadB.timeout(
        const Duration(seconds: 2),
        onTimeout: () => throw StateError('B waited for A\'s open body'),
      );

      expect(response, isA<FileInfo>());
      expect((response as FileInfo).file.readAsBytesSync(), tinyPng);
    });

    test('a body that fails halfway leaves no file at all', () async {
      final a = _photo('a');
      final bodyA = rig.network.bodies[a.url] = StreamController<List<int>>();

      final loadA = rig.load(a);
      final failed = expectLater(loadA, throwsA(anything));
      await Future<void>.delayed(const Duration(milliseconds: 30));
      bodyA
        ..add(tinyPng.sublist(0, 10))
        ..addError(const SocketException('connection lost'));
      await failed;

      expect(
        rig.directory.listSync().whereType<File>().where(
          (f) => f.path.endsWith('.png'),
        ),
        isEmpty,
        reason: 'no partial picture',
      );
      expect(await rig.manager.getFileFromCache('v1'), isNull);
    });

    test('a failed first install does not stop the next one', () async {
      final a = _photo('a');
      final b = _photo('b');
      final bodyA = rig.network.bodies[a.url] = StreamController<List<int>>();

      final loadA = rig.load(a);
      final failedA = expectLater(loadA, throwsA(anything));
      await Future<void>.delayed(const Duration(milliseconds: 30));
      final loadB = rig.load(b);
      await Future<void>.delayed(const Duration(milliseconds: 30));

      bodyA.addError(const SocketException('connection lost'));
      await failedA;
      final response = await loadB;

      expect(response, isA<FileInfo>());
      expect((response as FileInfo).file.readAsBytesSync(), tinyPng);
    });
  });

  group('a publication that fails leaves nothing behind', () {
    List<File> pictures() => rig.directory
        .listSync()
        .whereType<File>()
        .where((f) => f.path.endsWith('.png'))
        .toList();

    test('a record the database refuses removes the file again', () async {
      rig = _Rig(refuseRecords: true);

      await expectLater(rig.load(_photo('a')), throwsA(anything));

      expect(pictures(), isEmpty, reason: 'no file that no record names');
    });

    test(
      'a write the disk refuses is an error, and no record is made',
      () async {
        rig = _Rig(missingFolder: true);

        await expectLater(rig.load(_photo('a')), throwsA(anything));

        expect(pictures(), isEmpty);
        expect(await rig.manager.getFileFromCache('v1'), isNull);
      },
    );
  });

  group('the key an avatar load goes by', () {
    test('is the version and a tag of the address', () {
      final a = _photo('a');
      final b = _photo('b');

      expect(avatarCacheKey(a), isNot(avatarCacheKey(b)));
      expect(avatarCacheKey(a), avatarCacheKey(_photo('a')));
      expect(versionOf(avatarCacheKey(a)), 'v1');
      expect(versionOf(avatarCacheKey(b)), 'v1');
      expect(versionOf(avatarCacheKey(_photo('a', version: 'v2'))), 'v2');
    });

    test('never contains the address', () {
      final photo = _photo('SECRETSIGNATURE');

      expect(avatarCacheKey(photo), isNot(contains('SECRETSIGNATURE')));
      expect(avatarCacheKey(photo), isNot(contains('media.test')));
    });

    test('a key without a tag is its own version', () {
      expect(versionOf('karim'), 'karim');
    });
  });
}
