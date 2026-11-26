package eu.wassla.app

/**
 * Takes the metadata out of an encoded JPEG.
 *
 * The encoder writes what it likes beside the picture: Skia puts the output
 * color space's ICC profile in an APP2 segment, even for sRGB. A prepared photo
 * must carry none of that, so every application segment after the JFIF header
 * (APP1 to APP15: EXIF, XMP, ICC, vendor data) and every comment goes, and
 * nothing else changes: the bytes from the start of the scan on are copied as
 * they are.
 */
object JpegMetadata {
    private const val MARKER = 0xFF
    private const val SOI = 0xD8
    private const val EOI = 0xD9
    private const val SOS = 0xDA
    private const val TEM = 0x01
    private const val APP1 = 0xE1
    private const val APP15 = 0xEF
    private const val COM = 0xFE

    /**
     * [jpeg] without its metadata segments, or null when it is not a JPEG this
     * can read to the start of its scan (the caller then treats the encode as
     * failed instead of uploading bytes it could not clean).
     */
    fun withoutMetadata(jpeg: ByteArray): ByteArray? {
        if (jpeg.size < 4 || unsigned(jpeg[0]) != MARKER || unsigned(jpeg[1]) != SOI) return null
        val out = java.io.ByteArrayOutputStream(jpeg.size)
        out.write(jpeg, 0, 2)
        var at = 2
        while (true) {
            // Fill bytes may come before a marker.
            while (at < jpeg.size && unsigned(jpeg[at]) == MARKER && at + 1 < jpeg.size &&
                unsigned(jpeg[at + 1]) == MARKER
            ) {
                at++
            }
            if (at + 1 >= jpeg.size || unsigned(jpeg[at]) != MARKER) return null
            val marker = unsigned(jpeg[at + 1])
            // Markers that stand alone: a restart, the start and end of the image, TEM.
            if (marker == EOI) {
                out.write(jpeg, at, jpeg.size - at)
                return out.toByteArray()
            }
            if (marker == TEM || marker in 0xD0..0xD8) {
                out.write(jpeg, at, 2)
                at += 2
                continue
            }
            if (at + 3 >= jpeg.size) return null
            val length = (unsigned(jpeg[at + 2]) shl 8) or unsigned(jpeg[at + 3])
            if (length < 2 || at + 2 + length > jpeg.size) return null
            if (marker == SOS) {
                // Entropy-coded data follows: the rest is copied unread.
                out.write(jpeg, at, jpeg.size - at)
                return out.toByteArray()
            }
            val isMetadata = marker in APP1..APP15 || marker == COM
            if (!isMetadata) out.write(jpeg, at, 2 + length)
            at += 2 + length
        }
    }

    private fun unsigned(byte: Byte): Int = byte.toInt() and 0xFF
}
