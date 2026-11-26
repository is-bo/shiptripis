package eu.wassla.app

/** A width and a height in pixels. */
data class PhotoSize(val width: Int, val height: Int)

/**
 * The numbers behind [PhotoPreparer], with no decoding and no Android type in
 * them (so a plain JVM test runs the code the phone runs): how far to sample
 * while decoding, the sizes a decode is tried at when it runs out of memory, and
 * the size of the finished picture for each EXIF orientation.
 * `android/app/src/test` holds the tests; `tools/test_android_pure.sh` runs them.
 */
object PhotoGeometry {
    /** The longest edge of the prepared photo; the server keeps a 512 px square. */
    const val MAX_EDGE = 1024

    /**
     * The most pixels a decode may hold: about 6 megapixels, 24 MB as ARGB_8888,
     * whatever the picture's shape. A 48 MP photo and a 32000 x 1500 panorama
     * both decode at about 3 MP.
     */
    const val MAX_DECODED_PIXELS = 6_000_000L

    /**
     * The most pixels a picture may have for the platform decoder (HEIF) to be
     * asked for it at all. A HEIF file that is not tiled is decoded as one frame
     * whatever sample is requested, so its memory is the picture's own; a
     * 48 MP photo (the largest a phone camera makes) is within this, and what is
     * larger is refused before any pixel is decoded.
     */
    const val MAX_SOURCE_PIXELS = 64_000_000L

    /** The largest sample a decode may be asked for. */
    const val MAX_SAMPLE = 1024

    /** How many times a decode that ran out of memory is tried again, larger each time. */
    const val MAX_RETRIES = 3

    /**
     * The smallest power of two that brings the decoded pixel count within
     * [MAX_DECODED_PIXELS]. Because it is the smallest, the long edge stays above
     * 1200 px afterwards, so the scale to [MAX_EDGE] never has to enlarge.
     */
    fun sampleSize(width: Int, height: Int): Int {
        var sample = 1
        while (sample < MAX_SAMPLE &&
            (width.toLong() / sample) * (height.toLong() / sample) > MAX_DECODED_PIXELS
        ) {
            sample *= 2
        }
        return sample
    }

    /**
     * The samples a picture is decoded at, in order: [firstSample] (what
     * [sampleSize] chose from the picture's own size), then twice it, four times
     * it and so on, up to [MAX_RETRIES] retries and never above [MAX_SAMPLE].
     * A header sample of 4 gives 4, 8, 16, 32.
     */
    fun sampleLadder(firstSample: Int): List<Int> {
        val ladder = mutableListOf(firstSample.coerceIn(1, MAX_SAMPLE))
        while (ladder.size <= MAX_RETRIES && ladder.last() < MAX_SAMPLE) {
            ladder.add(minOf(ladder.last() * 2, MAX_SAMPLE))
        }
        return ladder
    }

    /** Whether a picture of [width] x [height] may be handed to the platform decoder. */
    fun withinSourceLimit(width: Int, height: Int): Boolean =
        width.toLong() * height.toLong() <= MAX_SOURCE_PIXELS

    /** The factor (never above 1) that brings the longer side to [MAX_EDGE]. */
    fun fitScale(width: Int, height: Int): Float {
        val longEdge = maxOf(width, height)
        return if (longEdge <= MAX_EDGE) 1f else MAX_EDGE.toFloat() / longEdge
    }

    /** Whether an EXIF orientation turns the picture a quarter turn (5, 6, 7 and 8). */
    fun swapsAxes(orientation: Int): Boolean = orientation in 5..8

    /** The size of a [width] x [height] picture once it is upright. */
    fun orientedSize(width: Int, height: Int, orientation: Int): PhotoSize =
        if (swapsAxes(orientation)) PhotoSize(height, width) else PhotoSize(width, height)

    /**
     * The size of the finished picture: upright, the longer side brought down to
     * [MAX_EDGE], neither side below one pixel. A 4096 x 1 strip is 1024 x 1,
     * not 1024 x 0.
     */
    fun outputSize(width: Int, height: Int, orientation: Int): PhotoSize {
        val upright = orientedSize(width, height, orientation)
        val scale = fitScale(upright.width, upright.height)
        return PhotoSize(
            Math.round(upright.width * scale).coerceIn(1, MAX_EDGE),
            Math.round(upright.height * scale).coerceIn(1, MAX_EDGE),
        )
    }
}
