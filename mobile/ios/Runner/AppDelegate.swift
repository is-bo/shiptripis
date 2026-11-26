import Flutter
import ImageIO
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  /// The UIScene lifecycle (Info.plist `UIApplicationSceneManifest`, see
  /// https://flutter.dev/to/uiscene-migration) creates the engine after launch,
  /// so plugins and the photo channel are registered when it is ready.
  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    registerPhotoPrepare(engineBridge.pluginRegistry)
  }

  /// `wassla/photo_prepare`: `prepare(path)` answers the path of a new upright
  /// JPEG of at most 1024 px with no metadata (see `PhotoPrepare`).
  private func registerPhotoPrepare(_ registry: FlutterPluginRegistry) {
    guard let registrar = registry.registrar(forPlugin: "WasslaPhotoPrepare") else { return }
    DispatchQueue.global(qos: .utility).async { PhotoPrepare.removeLeftovers() }
    let channel = FlutterMethodChannel(
      name: "wassla/photo_prepare",
      binaryMessenger: registrar.messenger()
    )
    channel.setMethodCallHandler { call, result in
      guard call.method == "prepare" else {
        result(FlutterMethodNotImplemented)
        return
      }
      guard let arguments = call.arguments as? [String: Any],
        let path = arguments["path"] as? String, !path.isEmpty
      else {
        result(FlutterError(code: "bad_arguments", message: "A path is needed", details: nil))
        return
      }
      DispatchQueue.global(qos: .userInitiated).async {
        do {
          let prepared = try PhotoPrepare.prepare(path: path)
          DispatchQueue.main.async { result(prepared) }
        } catch let error as PhotoPrepareError {
          DispatchQueue.main.async {
            result(FlutterError(code: error.code, message: error.message, details: nil))
          }
        } catch {
          DispatchQueue.main.async {
            result(FlutterError(code: "failed", message: "\(error)", details: nil))
          }
        }
      }
    }
  }
}

/// What went wrong, as a code the Dart side maps: `not_found`, `unsupported`
/// or `failed`.
enum PhotoPrepareError: Error {
  case notFound
  case unsupported
  case failed

  var code: String {
    switch self {
    case .notFound: return "not_found"
    case .unsupported: return "unsupported"
    case .failed: return "failed"
    }
  }

  var message: String {
    switch self {
    case .notFound: return "The picked photo is gone"
    case .unsupported: return "The photo cannot be decoded"
    case .failed: return "The photo could not be prepared"
    }
  }
}

/// Makes an upright JPEG of at most 1024 px, with no metadata, from a picked
/// photo. ImageIO builds the thumbnail straight from the file, decoding at the
/// reduced size, applying the orientation (mirrored ones too) and reading HEIC
/// like any other format, so the full picture is never held in memory.
enum PhotoPrepare {
  static let maxEdge = 1024
  static let quality = 0.88
  static let prefix = "wassla-photo-"

  /// Deletes prepared photos an earlier run left behind. Called once, when the
  /// engine starts: a new engine owns no prepared file, so every one that is
  /// still here belongs to a run that ended. Only files older than the call
  /// go, so one made by a photo prepared meanwhile is never taken.
  static func removeLeftovers() {
    let cutoff = Date()
    let directory = FileManager.default.temporaryDirectory
    guard
      let names = try? FileManager.default.contentsOfDirectory(atPath: directory.path)
    else { return }
    for name in names where name.hasPrefix(prefix) && name.hasSuffix(".jpg") {
      let url = directory.appendingPathComponent(name)
      let attributes = try? FileManager.default.attributesOfItem(atPath: url.path)
      guard let modified = attributes?[.modificationDate] as? Date, modified < cutoff else {
        continue
      }
      try? FileManager.default.removeItem(at: url)
    }
  }

  static func prepare(path: String) throws -> String {
    guard FileManager.default.fileExists(atPath: path) else {
      throw PhotoPrepareError.notFound
    }
    let sourceOptions: [CFString: Any] = [kCGImageSourceShouldCache: false]
    guard
      let source = CGImageSourceCreateWithURL(
        URL(fileURLWithPath: path) as CFURL, sourceOptions as CFDictionary),
      CGImageSourceGetCount(source) > 0
    else {
      throw PhotoPrepareError.unsupported
    }

    // Never enlarge a small picture: ask for the smaller of the two edges.
    let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
    let width = properties?[kCGImagePropertyPixelWidth] as? Int ?? 0
    let height = properties?[kCGImagePropertyPixelHeight] as? Int ?? 0
    let longEdge = max(width, height)
    let edge = longEdge > 0 ? min(maxEdge, longEdge) : maxEdge

    let thumbnailOptions: [CFString: Any] = [
      kCGImageSourceCreateThumbnailFromImageAlways: true,
      kCGImageSourceCreateThumbnailWithTransform: true,
      kCGImageSourceShouldCacheImmediately: true,
      kCGImageSourceThumbnailMaxPixelSize: edge,
    ]
    guard
      let thumbnail = CGImageSourceCreateThumbnailAtIndex(
        source, 0, thumbnailOptions as CFDictionary)
    else {
      throw PhotoPrepareError.unsupported
    }
    let image = try flattened(thumbnail)

    let target = FileManager.default.temporaryDirectory
      .appendingPathComponent("\(prefix)\(UUID().uuidString).jpg")
    guard
      let destination = CGImageDestinationCreateWithURL(
        target as CFURL, "public.jpeg" as CFString, 1, nil)
    else {
      throw PhotoPrepareError.failed
    }
    // No properties are passed with the image, so the JPEG carries no metadata.
    let writeOptions: [CFString: Any] = [kCGImageDestinationLossyCompressionQuality: quality]
    CGImageDestinationAddImage(destination, image, writeOptions as CFDictionary)
    guard CGImageDestinationFinalize(destination) else {
      try? FileManager.default.removeItem(at: target)
      throw PhotoPrepareError.failed
    }
    return target.path
  }

  /// A JPEG has no alpha: transparent pixels become white, as the server does.
  private static func flattened(_ image: CGImage) throws -> CGImage {
    switch image.alphaInfo {
    case .none, .noneSkipFirst, .noneSkipLast:
      return image
    default:
      break
    }
    guard
      let context = CGContext(
        data: nil,
        width: image.width,
        height: image.height,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
    else {
      throw PhotoPrepareError.failed
    }
    let rect = CGRect(x: 0, y: 0, width: image.width, height: image.height)
    context.setFillColor(UIColor.white.cgColor)
    context.fill(rect)
    context.draw(image, in: rect)
    guard let flat = context.makeImage() else {
      throw PhotoPrepareError.failed
    }
    return flat
  }
}
