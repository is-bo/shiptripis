package eu.wassla.app

import java.util.concurrent.atomic.AtomicBoolean

/**
 * Lets an `image_picker` result through to the plugin only when a pick that the
 * Dart side opened **in this process** is waiting for it.
 *
 * The plugin cannot say which launch a result belongs to. When the phone ends
 * the app while the camera or library is open, Android brings it back and hands
 * the plugin the old picker's result; the plugin copies the chosen file on a
 * worker and, if a later pick is waiting by the time the copy finishes, gives
 * that pick the old file. A copy of an identity document could be delivered as a
 * profile photo, however long after the restore the copy ends.
 *
 * Here the restore is cut at the source: the Dart side tells this gate when it
 * is about to open a picker ([opened]) and when the picker has answered
 * ([closed]), and a result for any of the plugin's request codes that arrives
 * while no such pick is open is dropped, so the plugin never starts a copy for
 * it. A new engine knows of no pick ([reset]): the pick that was open in the old
 * engine has no one waiting for it. The Dart side keeps its own tainted-pick
 * rules as a second line.
 *
 * [PICKER_REQUEST_CODES] are the request codes of `image_picker_android`
 * 0.8.13+21; `test/p3b_photo_round6_test.dart` fails if the pinned plugin's
 * codes differ.
 */
object PickLaunchGate {
    val PICKER_REQUEST_CODES: Set<Int> = setOf(2342, 2343, 2346, 2347, 2348, 2352, 2353)

    private val open = AtomicBoolean(false)

    /** A pick of this process is about to open its picker. */
    fun opened() = open.set(true)

    /** The pick's picker answered, or never opened. */
    fun closed() = open.set(false)

    /** A new engine: nothing is waiting for a result. */
    fun reset() = open.set(false)

    /** Whether the plugin may be given the result of [requestCode]. */
    fun shouldForward(requestCode: Int): Boolean =
        requestCode !in PICKER_REQUEST_CODES || open.get()
}
