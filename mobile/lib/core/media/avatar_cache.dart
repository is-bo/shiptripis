/// The disk cache behind profile photos: bytes by version, and nothing else.
///
/// A photo arrives as a short-lived signed address and an opaque version
/// (`PersonPhoto`). The picture of a version never changes, the address does on
/// every payload, and the address is a bearer credential for the file (spec
/// 21.2: it is never stored). The stock cache manager keeps the address in its
/// on-disk record (a `url` column), so this one:
///
/// * keeps the picture's bytes under the **version** and records the version in
///   that column instead: [_VersionOnlyRepository] rewrites every record it is
///   given, so the address exists in memory for the length of a request and
///   never on disk;
/// * loads once per **address**: two avatars holding the same address share a
///   request, but two avatars holding different addresses for one version each
///   make their own, so an address that has expired can never take down the load
///   of a fresh one that joined it. When one succeeds the bytes are the
///   version's and the other loads answer from them;
/// * **installs** a version's picture one response at a time: requests run
///   independently, but only one response at a time is written for a version,
///   and one that finds the picture already there is dropped unwritten. Two
///   valid addresses that answer together therefore leave one file, not two.
library;

import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';

import '../../domain/person_photo.dart';

const _tagSeparator = '|';

/// The key an avatar's picture goes by while it loads: the photo's version and a
/// short tag of its address. Flutter's image cache joins every load that has
/// the same key, so a key of the version alone would let an avatar holding a
/// fresh address join a load of an expired one and fail with it. The tag is
/// only a name in memory; [AvatarCacheManager] stores the bytes under the
/// version it carries ([versionOf]).
String avatarCacheKey(PersonPhoto photo) {
  final tag = sha256
      .convert(utf8.encode(photo.url))
      .toString()
      .substring(0, 16);
  return '${photo.version}$_tagSeparator$tag';
}

/// The version inside an [avatarCacheKey]; any other key is its own version.
String versionOf(String key) {
  final at = key.lastIndexOf(_tagSeparator);
  return at < 0 ? key : key.substring(0, at);
}

/// Where the request for [url] goes: the seam a test replaces.
typedef AvatarFileService = FileService;

class AvatarCacheManager extends CacheManager {
  AvatarCacheManager({AvatarFileService? fileService})
    : this._(
        'wassla_profile_photos',
        fileService ?? HttpFileService(),
        CacheObjectProvider(databaseName: 'wassla_profile_photos'),
        null,
      );

  /// A cache that keeps its record in [infoFile] and its pictures in
  /// [fileSystem], for a test that has no application directory and wants to
  /// read the record that reaches the disk.
  AvatarCacheManager.at({
    required CacheInfoRepository records,
    required FileSystem fileSystem,
    required AvatarFileService fileService,
  }) : this._('wassla_profile_photos', fileService, records, fileSystem);

  AvatarCacheManager._(
    String key,
    AvatarFileService fileService,
    CacheInfoRepository repo,
    FileSystem? fileSystem,
  ) : _files = fileService,
      super(
        _config(key, fileService, _VersionOnlyRepository(repo), fileSystem),
      );

  static Config _config(
    String key,
    AvatarFileService fileService,
    CacheInfoRepository repo,
    FileSystem? fileSystem,
  ) => fileSystem == null
      ? Config(key, repo: repo, fileService: fileService)
      : Config(
          key,
          repo: repo,
          fileSystem: fileSystem,
          fileService: fileService,
        );

  final AvatarFileService _files;

  /// The request in flight for each address.
  final _inFlight = <String, Future<FileInfo>>{};

  /// The last install queued for each version.
  final _installs = <String, Future<void>>{};

  /// The picture of version [key]: from disk when it is there, otherwise
  /// fetched from [url]. Nothing is revalidated: a version never changes.
  @override
  Stream<FileResponse> getFileStream(
    String url, {
    String? key,
    Map<String, String>? headers,
    bool withProgress = false,
  }) async* {
    final version = versionOf(key ?? url);
    final cached = await getFileFromCache(version);
    if (cached != null) {
      yield cached;
      return;
    }
    var load = _inFlight[url];
    if (load == null) {
      load = _fetch(url, version);
      _inFlight[url] = load;
      load.whenComplete(() {
        _inFlight.remove(url);
      }).ignore();
    }
    yield await load;
  }

  Future<FileInfo> _fetch(String url, String version) async {
    final response = await _files.get(url);
    if (!const [200, 202].contains(response.statusCode)) {
      await response.content.listen((_) {}).cancel();
      throw HttpExceptionWithStatus(
        response.statusCode,
        'Invalid statusCode: ${response.statusCode}',
        uri: Uri.tryParse(url),
      );
    }
    return _installOnce(version, () async {
      // Another address for this version may have answered first (and may
      // still have been writing when this one answered): its bytes are the
      // same picture, so this response is dropped rather than stored twice.
      final existing = await getFileFromCache(version);
      if (existing != null) {
        await response.content.listen((_) {}).cancel();
        return existing;
      }
      final extension = response.fileExtension;
      final file = await putFileStream(
        url,
        response.content,
        key: version,
        fileExtension: extension.startsWith('.')
            ? extension.substring(1)
            : extension,
      );
      return FileInfo(file, FileSource.Online, response.validTill, url);
    });
  }

  /// Runs [install] after every install queued before it for [version] has
  /// finished, whether those succeeded or not.
  Future<FileInfo> _installOnce(
    String version,
    Future<FileInfo> Function() install,
  ) {
    final before = _installs[version] ?? Future<void>.value();
    final result = before.then((_) => install());
    final tail = result.then<void>((_) {}, onError: (Object _) {});
    _installs[version] = tail;
    tail.whenComplete(() {
      if (identical(_installs[version], tail)) _installs.remove(version);
    }).ignore();
    return result;
  }
}

/// Rewrites every record on its way to storage so that its address is the key
/// (the picture's version): the address a request used is never written.
class _VersionOnlyRepository implements CacheInfoRepository {
  _VersionOnlyRepository(this._inner);

  final CacheInfoRepository _inner;

  CacheObject _scrub(CacheObject object) => object.copyWith(url: object.key);

  @override
  Future<bool> exists() => _inner.exists();

  @override
  Future<bool> open() => _inner.open();

  @override
  Future<dynamic> updateOrInsert(CacheObject cacheObject) =>
      _inner.updateOrInsert(_scrub(cacheObject));

  @override
  Future<CacheObject> insert(
    CacheObject cacheObject, {
    bool setTouchedToNow = true,
  }) => _inner.insert(_scrub(cacheObject), setTouchedToNow: setTouchedToNow);

  @override
  Future<CacheObject?> get(String key) => _inner.get(key);

  @override
  Future<int> delete(int id) => _inner.delete(id);

  @override
  Future<int> deleteAll(Iterable<int> ids) => _inner.deleteAll(ids);

  @override
  Future<int> update(CacheObject cacheObject, {bool setTouchedToNow = true}) =>
      _inner.update(_scrub(cacheObject), setTouchedToNow: setTouchedToNow);

  @override
  Future<List<CacheObject>> getAllObjects() => _inner.getAllObjects();

  @override
  Future<List<CacheObject>> getObjectsOverCapacity(int capacity) =>
      _inner.getObjectsOverCapacity(capacity);

  @override
  Future<List<CacheObject>> getOldObjects(Duration maxAge) =>
      _inner.getOldObjects(maxAge);

  @override
  Future<bool> close() => _inner.close();

  @override
  Future<void> deleteDataFile() => _inner.deleteDataFile();
}
