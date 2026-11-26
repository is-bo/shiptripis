package eu.wassla.app

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PickLaunchGateTest {
    @After
    fun closeTheGate() = PickLaunchGate.reset()

    @Test
    fun aRestoredPickerResultIsDroppedWhenNoPickOfThisProcessIsOpen() {
        PickLaunchGate.reset()
        for (code in PickLaunchGate.PICKER_REQUEST_CODES) {
            assertFalse("request $code", PickLaunchGate.shouldForward(code))
        }
    }

    @Test
    fun aResultIsForwardedWhileAPickOpenedByThisProcessWaits() {
        PickLaunchGate.opened()
        for (code in PickLaunchGate.PICKER_REQUEST_CODES) {
            assertTrue("request $code", PickLaunchGate.shouldForward(code))
        }
    }

    @Test
    fun aResultAfterThePickAnsweredIsDropped() {
        PickLaunchGate.opened()
        PickLaunchGate.closed()
        assertFalse(PickLaunchGate.shouldForward(2342))
    }

    @Test
    fun aNewEngineKnowsOfNoOpenPick() {
        PickLaunchGate.opened()
        PickLaunchGate.reset()
        assertFalse(PickLaunchGate.shouldForward(2343))
    }

    @Test
    fun otherPluginsActivityResultsAreNeverHeld() {
        PickLaunchGate.reset()
        for (code in listOf(0, 1, 9001, 40000, 2344, 2345, 2355)) {
            assertTrue("request $code", PickLaunchGate.shouldForward(code))
        }
    }

    @Test
    fun theCodesAreTheSevenOfThePlugin() {
        assertEquals(7, PickLaunchGate.PICKER_REQUEST_CODES.size)
    }
}
