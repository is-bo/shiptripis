package eu.wassla.app

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class JpegMetadataTest {
    private fun segment(marker: Int, payload: ByteArray): ByteArray {
        val length = payload.size + 2
        return byteArrayOf(0xFF.toByte(), marker.toByte(), (length shr 8).toByte(), length.toByte()) + payload
    }

    private val soi = byteArrayOf(0xFF.toByte(), 0xD8.toByte())
    private val eoi = byteArrayOf(0xFF.toByte(), 0xD9.toByte())
    private val jfif = segment(0xE0, "JFIF\u0000\u0001\u0001\u0000\u0000\u0001\u0000\u0001\u0000\u0000".toByteArray(Charsets.ISO_8859_1))
    private val icc = segment(0xE2, "ICC_PROFILE\u0000\u0001\u0001".toByteArray(Charsets.ISO_8859_1) + ByteArray(400) { 7 })
    private val exif = segment(0xE1, "Exif\u0000\u0000".toByteArray(Charsets.ISO_8859_1) + ByteArray(30) { 3 })
    private val comment = segment(0xFE, "made by a phone".toByteArray())
    private val tables = segment(0xDB, ByteArray(65) { 1 })
    // Entropy-coded data holds stuffed bytes and restart markers that look like segments.
    private val scan = segment(0xDA, byteArrayOf(1, 1, 0, 0, 63, 0)) +
        byteArrayOf(0x12, 0xFF.toByte(), 0x00, 0xFF.toByte(), 0xD0.toByte(), 0xFF.toByte(), 0xE2.toByte(), 0x00, 0x05)

    private fun jpeg(vararg parts: ByteArray) = parts.fold(soi) { all, part -> all + part } + eoi

    @Test
    fun theColorProfileTheEncoderWroteIsRemoved() {
        val cleaned = JpegMetadata.withoutMetadata(jpeg(jfif, icc, tables, scan))!!
        assertArrayEquals(jpeg(jfif, tables, scan), cleaned)
        assertTrue(String(cleaned, Charsets.ISO_8859_1).indexOf("ICC_PROFILE") < 0)
    }

    @Test
    fun exifAndCommentsGoToo() {
        val cleaned = JpegMetadata.withoutMetadata(jpeg(jfif, exif, comment, icc, tables, scan))!!
        assertArrayEquals(jpeg(jfif, tables, scan), cleaned)
    }

    @Test
    fun theScanIsCopiedUnreadEvenWhenItLooksLikeASegment() {
        val cleaned = JpegMetadata.withoutMetadata(jpeg(icc, tables, scan))!!
        assertArrayEquals(jpeg(tables, scan), cleaned)
        assertEquals(scan.size, cleaned.size - (soi.size + tables.size + eoi.size))
    }

    @Test
    fun aPictureWithNoMetadataIsUnchanged() {
        val plain = jpeg(jfif, tables, scan)
        assertArrayEquals(plain, JpegMetadata.withoutMetadata(plain))
    }

    @Test
    fun whatIsNotAJpegOrIsCutShortIsRefused() {
        assertNull(JpegMetadata.withoutMetadata(byteArrayOf(1, 2, 3, 4)))
        assertNull(JpegMetadata.withoutMetadata(ByteArray(0)))
        val cut = jpeg(jfif, icc, tables, scan)
        assertNull(JpegMetadata.withoutMetadata(cut.copyOf(soi.size + jfif.size + 40)))
    }
}
