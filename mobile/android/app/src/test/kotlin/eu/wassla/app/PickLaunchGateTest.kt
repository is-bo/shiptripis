package eu.wassla.app

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PickLaunchGateTest {
    private val activity = Any()
    private val other = Any()

    @After
    fun closeTheGate() {
        PickLaunchGate.closed(activity)
        PickLaunchGate.closed(other)
    }

    @Test
    fun aRestoredPickerResultIsDroppedWhenNoPickOfThisProcessIsOpen() {
        for (code in PickLaunchGate.PICKER_REQUEST_CODES) {
            assertFalse("request $code", PickLaunchGate.shouldForward(code, activity))
        }
    }

    @Test
    fun aResultIsForwardedWhileAPickOpenedByThisActivityWaits() {
        PickLaunchGate.opened(activity)
        for (code in PickLaunchGate.PICKER_REQUEST_CODES) {
            assertTrue("request $code", PickLaunchGate.shouldForward(code, activity))
        }
    }

    @Test
    fun aResultAfterThePickAnsweredIsDropped() {
        PickLaunchGate.opened(activity)
        PickLaunchGate.closed(activity)
        assertFalse(PickLaunchGate.shouldForward(2342, activity))
    }

    @Test
    fun aResultAtAnActivityThatOpenedNoPickIsDroppedWhileAnotherHasOne() {
        PickLaunchGate.opened(activity)
        assertFalse(PickLaunchGate.shouldForward(2343, other))
        assertTrue(PickLaunchGate.shouldForward(2343, activity))
    }

    @Test
    fun anotherActivityEndingLeavesTheOpenPickAlone() {
        PickLaunchGate.opened(activity)
        PickLaunchGate.closed(other)
        assertTrue(PickLaunchGate.shouldForward(2342, activity))
    }

    @Test
    fun aPickEndsWithItsDestroyedActivity() {
        PickLaunchGate.opened(activity)
        PickLaunchGate.closed(activity)
        assertFalse(PickLaunchGate.shouldForward(2346, activity))
    }

    @Test
    fun otherPluginsActivityResultsAreNeverHeld() {
        for (code in listOf(0, 1, 9001, 40000, 2344, 2345, 2355)) {
            assertTrue("request $code", PickLaunchGate.shouldForward(code, activity))
        }
    }

    @Test
    fun theCodesAreTheSevenOfThePlugin() {
        assertEquals(7, PickLaunchGate.PICKER_REQUEST_CODES.size)
    }
}
