package eu.wassla.app

import android.content.Context
import java.io.IOException

/**
 * The pending-pick marker of `PickGuard` (a purpose and a nonce: nothing secret),
 * kept where a write can be known to have reached the disk.
 *
 * The marker tells the next pick that an earlier one never ended (the phone
 * ended the app while a picker was open). `flutter_secure_storage` writes
 * through `SharedPreferences.Editor.apply()`, which answers before the disk is
 * written and cannot say that it failed, so a marker kept there could be
 * "written" and still be gone after the process dies. Here every change is a
 * `commit()`, which answers whether the disk took it, and a change that did not
 * is an error the Dart side turns into "no picker opens".
 */
class PickMarkerStore(context: Context) {
    private val preferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** Makes [marker] the pending pick and answers the one it replaced (null: none). */
    @Synchronized
    fun exchange(marker: String): String? {
        val previous = preferences.getString(KEY, null)
        if (!preferences.edit().putString(KEY, marker).commit()) {
            throw IOException("The pick marker could not be written")
        }
        return previous
    }

    /** Clears the pending pick, but only while it is still [marker]. */
    @Synchronized
    fun release(marker: String) {
        if (preferences.getString(KEY, null) != marker) return
        if (!preferences.edit().remove(KEY).commit()) {
            throw IOException("The pick marker could not be cleared")
        }
    }

    /** A pick still open at sign-out names nobody: its marker becomes a bare tombstone. */
    @Synchronized
    fun closeBySignOut() {
        if (preferences.getString(KEY, null) == null) return
        if (!preferences.edit().putString(KEY, SIGNED_OUT).commit()) {
            throw IOException("The pick marker could not be closed")
        }
    }

    /** The marker as it is stored, or null. */
    @Synchronized
    fun read(): String? = preferences.getString(KEY, null)

    private companion object {
        const val FILE = "wassla_pick_marker"
        const val KEY = "pending_pick"
        const val SIGNED_OUT = "signed-out"
    }
}
