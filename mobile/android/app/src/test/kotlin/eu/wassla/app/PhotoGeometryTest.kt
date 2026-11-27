package eu.wassla.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Runs the arithmetic the phone runs (`PhotoGeometry` is the same object the
 * decoder asks), not a copy of it.
 */
class PhotoGeometryTest {
    @Test
    fun theSampleKeepsADecodeNearSixMegapixelsWhateverTheShape() {
        assertEquals(1, PhotoGeometry.sampleSize(1000, 1000))
        assertEquals(1, PhotoGeometry.sampleSize(1024, 768))
        assertEquals(1, PhotoGeometry.sampleSize(2448, 2448)) // 6 MP is allowed whole
        assertEquals(1, PhotoGeometry.sampleSize(3000, 2000))
        assertEquals(2, PhotoGeometry.sampleSize(4000, 3000)) // 12 MP -> 3 MP
        assertEquals(4, PhotoGeometry.sampleSize(8000, 6000)) // 48 MP -> 3 MP
        assertEquals(4, PhotoGeometry.sampleSize(32000, 1500)) // a panorama
        assertEquals(1, PhotoGeometry.sampleSize(1_000_000, 1)) // a thin strip is cheap
        assertEquals(
            PhotoGeometry.MAX_SAMPLE,
            PhotoGeometry.sampleSize(1_000_000_000, 1_000_000_000),
        )
    }

    @Test
    fun aDecodeNeverEnlargesAndNeverHoldsMoreThanTheLimit() {
        for ((width, height) in listOf(4000 to 3000, 8000 to 6000, 32000 to 1500)) {
            val sample = PhotoGeometry.sampleSize(width, height)
            assertTrue(maxOf(width, height) / sample > 1200)
            assertTrue(
                (width.toLong() / sample) * (height.toLong() / sample) <=
                    PhotoGeometry.MAX_DECODED_PIXELS
            )
        }
    }

    @Test
    fun aPanoramaIsBoundedByItsPixelsNotItsEdge() {
        val sample = PhotoGeometry.sampleSize(32000, 1500)
        assertTrue((32000L / sample) * (1500L / sample) <= PhotoGeometry.MAX_DECODED_PIXELS)
    }

    @Test
    fun aDecodeThatRunsOutOfMemoryIsTriedAtFourTimesTheHeaderSampleInTurn() {
        // The header chose 4: the attempts are 4, 8, 16 and 32, each really larger
        // than the one before it (an earlier version tried 4, 4, 4 and 8).
        assertEquals(listOf(4, 8, 16, 32), PhotoGeometry.sampleLadder(4))
        assertEquals(listOf(1, 2, 4, 8), PhotoGeometry.sampleLadder(1))
        assertEquals(listOf(2, 4, 8, 16), PhotoGeometry.sampleLadder(2))
    }

    @Test
    fun theLadderNeverPassesTheLargestSample() {
        assertEquals(listOf(256, 512, 1024), PhotoGeometry.sampleLadder(256))
        assertEquals(listOf(1024), PhotoGeometry.sampleLadder(1024))
        assertTrue(PhotoGeometry.sampleLadder(512).all { it <= PhotoGeometry.MAX_SAMPLE })
    }

    @Test
    fun aPictureOverTheSourceLimitIsRefusedBeforeItsPixelsAreDecoded() {
        assertTrue(PhotoGeometry.withinSourceLimit(8000, 6000))
        assertFalse(PhotoGeometry.withinSourceLimit(12000, 9000))
        assertFalse(PhotoGeometry.withinSourceLimit(Int.MAX_VALUE, 2))
    }

    @Test
    fun aPictureOfAtMost1024PxIsNeverEnlarged() {
        assertEquals(1f, PhotoGeometry.fitScale(1024, 700), 0f)
        assertEquals(1f, PhotoGeometry.fitScale(200, 100), 0f)
        assertEquals(0.25f, PhotoGeometry.fitScale(4096, 100), 0f)
        assertEquals(PhotoSize(1000, 700), PhotoGeometry.outputSize(1000, 700, 1))
        assertEquals(PhotoSize(500, 400), PhotoGeometry.outputSize(500, 400, 1))
    }

    @Test
    fun allEightOrientationsGiveTheUprightSize() {
        // 4000 x 3000, on its side or not: 1024 x 768 or 768 x 1024.
        for (orientation in 1..4) {
            assertEquals(PhotoSize(1024, 768), PhotoGeometry.outputSize(4000, 3000, orientation))
        }
        for (orientation in 5..8) {
            assertEquals(PhotoSize(768, 1024), PhotoGeometry.outputSize(4000, 3000, orientation))
        }
        // An unknown value is read as upright.
        assertEquals(PhotoSize(1024, 768), PhotoGeometry.outputSize(4000, 3000, 0))
        assertEquals(PhotoSize(1024, 768), PhotoGeometry.outputSize(4000, 3000, 9))
    }

    @Test
    fun aStripIsNeverZeroPixelsWide() {
        assertEquals(PhotoSize(1024, 1), PhotoGeometry.outputSize(4096, 1, 1))
        assertEquals(PhotoSize(1, 1024), PhotoGeometry.outputSize(1, 4096, 1))
        assertEquals(PhotoSize(1, 1024), PhotoGeometry.outputSize(4096, 1, 6))
        assertEquals(PhotoSize(1, 1), PhotoGeometry.outputSize(1, 1, 1))
        assertEquals(PhotoSize(1024, 1), PhotoGeometry.outputSize(32000, 1, 1))
    }

    @Test
    fun noSideIsEverBelowOnePixelOrAbove1024() {
        val widths = listOf(1, 2, 7, 100, 1023, 1024, 1025, 3000, 9999, 32000)
        val heights = listOf(1, 3, 640, 1024, 1500, 4096, 32000)
        for (width in widths) for (height in heights) for (orientation in 1..8) {
            val size = PhotoGeometry.outputSize(width, height, orientation)
            assertTrue("$width x $height", size.width in 1..1024)
            assertTrue("$width x $height", size.height in 1..1024)
        }
    }

    @Test
    fun onlyTheQuarterTurnOrientationsSwapTheAxes() {
        assertEquals((1..8).filter { PhotoGeometry.swapsAxes(it) }, listOf(5, 6, 7, 8))
    }

    @Test
    fun onlyTheFullFrameFormatsAreHeldToTheSourceLimit() {
        assertTrue(PhotoGeometry.isFullFrameFormat("image/heif"))
        assertTrue(PhotoGeometry.isFullFrameFormat("image/HEIC"))
        assertTrue(PhotoGeometry.isFullFrameFormat("image/heic-sequence"))
        assertTrue(PhotoGeometry.isFullFrameFormat("image/avif"))
        assertFalse(PhotoGeometry.isFullFrameFormat("image/jpeg"))
        assertFalse(PhotoGeometry.isFullFrameFormat("image/png"))
        assertFalse(PhotoGeometry.isFullFrameFormat(null))
    }
}
