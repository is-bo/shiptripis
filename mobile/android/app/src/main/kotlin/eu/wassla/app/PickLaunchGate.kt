package eu.wassla.app

import java.util.concurrent.atomic.AtomicReference

/**
 * Lets an `image_picker` result through to the plugin only when a pick that the
 * Dart side opened **in this process, from this activity** is waiting for it.
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
 * it. The gate names the activity that opened the pick (its [owner]), so another
 * activity's start-up, closing or results leave a pick that is open alone, and a
 * result arriving at an activity that did not open one is never forwarded. A
 * pick whose activity is destroyed ends with it ([closed]): nobody is waiting
 * for it any more. The Dart side keeps its own tainted-pick rules as a second
 * line.
 *
 * [PICKER_REQUEST_CODES] are the request codes of `image_picker_android`
 * 0.8.13+21; `test/p3b_photo_round6_test.dart` fails if the pinned plugin's
 * codes differ.
 */
object PickLaunchGate {
    val PICKER_REQUEST_CODES: Set<Int> = setOf(2342, 2343, 2346, 2347, 2348, 2352, 2353)

    private val openFor = AtomicReference<Any?>(null)

    /** A pick of [owner] is about to open its picker. */
    fun opened(owner: Any) = openFor.set(owner)

    /**
     * [owner]'s pick answered, never opened, or its activity is gone. Another
     * owner's open pick is left alone.
     */
    fun closed(owner: Any) {
        openFor.compareAndSet(owner, null)
    }

    /** Whether the plugin of [owner] may be given the result of [requestCode]. */
    fun shouldForward(requestCode: Int, owner: Any): Boolean =
        requestCode !in PICKER_REQUEST_CODES || openFor.get() === owner
}
