package eu.wassla.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    /** Photo preparation decodes a picture: off the main thread, one at a time. */
    private val photoExecutor: ExecutorService = Executors.newSingleThreadExecutor()

    /** Marker changes wait for the disk, so they never queue behind a photo. */
    private val markerExecutor: ExecutorService = Executors.newSingleThreadExecutor()

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        configurePhotoPrepare(flutterEngine)
        configurePickMarker(flutterEngine)
        configurePickLaunch(flutterEngine)
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "eu.wassla.app/notification_permission",
        ).setMethodCallHandler { call, result ->
            if (call.method == "runtimePermissionSupported") {
                result.success(Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            } else {
                result.notImplemented()
            }
        }
    }

    /**
     * `wassla/photo_prepare`: `prepare(path)` answers the path of a new upright
     * JPEG of at most 1024 px with no metadata (see [PhotoPreparer]).
     */
    private fun configurePhotoPrepare(flutterEngine: FlutterEngine) {
        // First on the single thread, so before any photo of this run is prepared.
        photoExecutor.execute { PhotoPreparer(cacheDir).removeLeftovers() }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "wassla/photo_prepare")
            .setMethodCallHandler { call, result ->
                if (call.method != "prepare") {
                    result.notImplemented()
                    return@setMethodCallHandler
                }
                val path = call.argument<String>("path")
                if (path.isNullOrEmpty()) {
                    result.error("bad_arguments", "A path is needed", null)
                    return@setMethodCallHandler
                }
                photoExecutor.execute {
                    try {
                        val prepared = PhotoPreparer(cacheDir).prepare(path)
                        runOnUiThread { result.success(prepared.path) }
                    } catch (error: PhotoPrepareException) {
                        runOnUiThread { result.error(error.code, error.message, null) }
                    } catch (error: Throwable) {
                        runOnUiThread { result.error("failed", error.message, null) }
                    }
                }
            }
    }

    /**
     * `wassla/pick_marker`: the pending-pick marker, written with `commit()` so a
     * write that did not reach the disk is an error (see [PickMarkerStore]). Off
     * the main thread: a commit waits for the disk.
     */
    private fun configurePickMarker(flutterEngine: FlutterEngine) {
        val store = PickMarkerStore(this)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "wassla/pick_marker")
            .setMethodCallHandler { call, result ->
                val marker = call.argument<String>("marker")
                markerExecutor.execute {
                    try {
                        val answer: Any? =
                            when (call.method) {
                                "exchange" -> store.exchange(requireNotNull(marker))
                                "release" -> {
                                    store.release(requireNotNull(marker))
                                    null
                                }
                                "closeBySignOut" -> {
                                    store.closeBySignOut()
                                    null
                                }
                                "read" -> store.read()
                                else -> {
                                    runOnUiThread { result.notImplemented() }
                                    return@execute
                                }
                            }
                        runOnUiThread { result.success(answer) }
                    } catch (error: Throwable) {
                        runOnUiThread { result.error("storage", error.message, null) }
                    }
                }
            }
    }

    /**
     * `wassla/pick_launch`: the Dart side says when a pick opens its picker and
     * when it has answered (see [PickLaunchGate]). A new engine starts with no
     * pick open.
     */
    private fun configurePickLaunch(flutterEngine: FlutterEngine) {
        PickLaunchGate.reset()
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "wassla/pick_launch")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "opened" -> PickLaunchGate.opened()
                    "closed" -> PickLaunchGate.closed()
                    else -> {
                        result.notImplemented()
                        return@setMethodCallHandler
                    }
                }
                result.success(null)
            }
    }

    /**
     * A picker result is handed to the plugin only if a pick opened by this
     * process is waiting for it; one restored after the phone ended the app is
     * dropped before the plugin can copy its file (see [PickLaunchGate]).
     */
    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (!PickLaunchGate.shouldForward(requestCode)) return
        @Suppress("DEPRECATION") super.onActivityResult(requestCode, resultCode, data)
    }

    override fun onDestroy() {
        photoExecutor.shutdown()
        markerExecutor.shutdown()
        super.onDestroy()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannels(
            listOf(
                channel("messages", R.string.notification_channel_messages),
                channel("deliveries", R.string.notification_channel_deliveries),
                channel("account", R.string.notification_channel_account),
                channel("payments", R.string.notification_channel_payments),
            ),
        )
    }

    private fun channel(id: String, name: Int) = NotificationChannel(
        id,
        getString(name),
        NotificationManager.IMPORTANCE_DEFAULT,
    )
}
