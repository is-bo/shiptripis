package eu.wassla.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorSpace
import android.graphics.ImageDecoder
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.RectF
import android.os.Build
import androidx.annotation.RequiresApi
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.io.FileOutputStream
import java.security.SecureRandom

/**
 * What went wrong, as a code the Dart side maps: `not_found` (the file is gone),
 * `unsupported` (a decoder refused the picture) or `failed` (anything else: no
 * memory, a write that did not work).
 */
class PhotoPrepareException(val code: String, message: String, cause: Throwable? = null) :
    Exception(message, cause)

/** A width and a height in pixels. */
data class PhotoSize(val width: Int, val height: Int)

/**
 * The numbers behind [PhotoPreparer], with no decoding and no Android type in
 * them: how far to sample while decoding, the size of the finished picture for
 * each EXIF orientation, and the next sample to try when a decode runs out of
 * memory. `test/p3b_photo_prepare_test.dart` holds the same arithmetic as an
 * executable specification, with the cases the review asked for.
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

    /** The sample to try after [sample] failed, or null when none is left. */
    fun nextSample(sample: Int): Int? = if (sample >= MAX_SAMPLE) null else sample * 2

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

/** The matrix that makes a picture upright for each of the eight EXIF orientations. */
object PhotoOrientation {
    /** Reflections (2, 4, 5 and 7) included. */
    fun matrix(orientation: Int): Matrix {
        val matrix = Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1f, 1f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> {
                matrix.setRotate(180f)
                matrix.postScale(-1f, 1f)
            }
            ExifInterface.ORIENTATION_TRANSPOSE -> {
                matrix.setRotate(90f)
                matrix.postScale(-1f, 1f)
            }
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90f)
            ExifInterface.ORIENTATION_TRANSVERSE -> {
                matrix.setRotate(-90f)
                matrix.postScale(-1f, 1f)
            }
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(-90f)
            else -> Unit
        }
        return matrix
    }
}

/**
 * Makes an upright JPEG of at most [PhotoGeometry.MAX_EDGE] px, with no
 * metadata, from a picked photo, without ever decoding the whole picture: the
 * decoder is asked to sample, so the pixels in memory are bounded, and a decode
 * that fails for memory is tried again at a larger sample. Whatever the decoder
 * produced (a wide-gamut or HDR bitmap, one with a gain map or an embedded
 * profile) is only the source: the output is always drawn into a fresh sRGB
 * ARGB_8888 bitmap of the computed size, and that bitmap is what is compressed.
 * The result is written to a new file in [cacheDir].
 */
class PhotoPreparer(private val cacheDir: File) {

    private class Decoded(val bitmap: Bitmap, val orientationApplied: Boolean)

    /**
     * Deletes prepared photos an earlier run left in [cacheDir]. Called once when
     * the engine starts, on the same single thread as [prepare], so it finishes
     * before this run prepares anything: a new engine owns no prepared file.
     */
    fun removeLeftovers() {
        cacheDir
            .listFiles { _, name -> name.startsWith(PREFIX) && name.endsWith(".jpg") }
            ?.forEach { it.delete() }
    }

    fun prepare(path: String): File {
        val source = File(path)
        if (!source.isFile) throw PhotoPrepareException("not_found", "The picked photo is gone")

        val decoded = decode(source)
        val orientation =
            if (decoded.orientationApplied) ExifInterface.ORIENTATION_NORMAL
            else exifOrientation(source)
        val rendered =
            try {
                render(decoded.bitmap, orientation)
            } catch (error: OutOfMemoryError) {
                throw PhotoPrepareException("failed", "Out of memory", error)
            } finally {
                decoded.bitmap.recycle()
            }
        try {
            return write(rendered)
        } finally {
            rendered.recycle()
        }
    }

    /** The picture decoded at a sample that bounds its pixels. */
    private fun decode(source: File): Decoded {
        decodeWithBitmapFactory(source)?.let { return it }
        // BitmapFactory could not read it (a HEIF file on some builds): the
        // platform decoder can, from API 28.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) return decodeWithImageDecoder(source)
        throw PhotoPrepareException("unsupported", "The photo cannot be decoded")
    }

    /**
     * Null when BitmapFactory cannot read the picture (no bounds, or nothing came
     * out). A decode that runs out of memory is tried at a larger sample, up to
     * [PhotoGeometry.MAX_RETRIES] times, then fails.
     */
    private fun decodeWithBitmapFactory(source: File): Decoded? {
        val bounds = BitmapFactory.Options()
        bounds.inJustDecodeBounds = true
        BitmapFactory.decodeFile(source.path, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = PhotoGeometry.sampleSize(bounds.outWidth, bounds.outHeight)
        var retries = 0
        while (true) {
            var outOfMemory: OutOfMemoryError? = null
            try {
                val options = BitmapFactory.Options()
                options.inSampleSize = sample
                options.inPreferredConfig = Bitmap.Config.ARGB_8888
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    options.inPreferredColorSpace = ColorSpace.get(ColorSpace.Named.SRGB)
                }
                val bitmap = BitmapFactory.decodeFile(source.path, options)
                if (bitmap != null) return Decoded(bitmap, false)
            } catch (error: OutOfMemoryError) {
                outOfMemory = error
            }
            // Nothing came out: memory is the likely reason, so a larger sample.
            val next = PhotoGeometry.nextSample(sample)
            if (next == null || retries >= PhotoGeometry.MAX_RETRIES) {
                if (outOfMemory != null) {
                    throw PhotoPrepareException("failed", "Out of memory", outOfMemory)
                }
                return null
            }
            retries += 1
            sample = next
        }
    }

    /**
     * ImageDecoder applies the orientation itself, so [Decoded.orientationApplied]
     * is true and no matrix is applied again. The sample is chosen in
     * onHeaderDecoded from the picture's own size, so a large HEIF is never
     * decoded whole, and a failure for memory is tried again at a larger sample.
     */
    @RequiresApi(Build.VERSION_CODES.P)
    private fun decodeWithImageDecoder(source: File): Decoded {
        var floor = 1
        var retries = 0
        while (true) {
            val atLeast = floor
            try {
                val bitmap =
                    ImageDecoder.decodeBitmap(ImageDecoder.createSource(source)) { decoder, info, _ ->
                        decoder.setTargetSampleSize(
                            maxOf(atLeast, PhotoGeometry.sampleSize(info.size.width, info.size.height))
                        )
                        decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                        decoder.setTargetColorSpace(ColorSpace.get(ColorSpace.Named.SRGB))
                    }
                return Decoded(bitmap, true)
            } catch (error: OutOfMemoryError) {
                val next = PhotoGeometry.nextSample(atLeast)
                if (next == null || retries >= PhotoGeometry.MAX_RETRIES) {
                    throw PhotoPrepareException("failed", "Out of memory", error)
                }
                retries += 1
                floor = next
            } catch (error: Exception) {
                throw PhotoPrepareException("unsupported", "The photo cannot be decoded", error)
            }
        }
    }

    private fun exifOrientation(source: File): Int =
        try {
            ExifInterface(source.path)
                .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        } catch (error: Exception) {
            ExifInterface.ORIENTATION_NORMAL
        }

    /**
     * Draws [source], upright and scaled, into a new ARGB_8888 bitmap (sRGB, the
     * default) of [PhotoGeometry.outputSize]. White goes down first: a JPEG has no
     * alpha, so transparent pixels become white, as the server does.
     */
    private fun render(source: Bitmap, orientation: Int): Bitmap {
        val size = PhotoGeometry.outputSize(source.width, source.height, orientation)
        val matrix = PhotoOrientation.matrix(orientation)
        val upright = RectF(0f, 0f, source.width.toFloat(), source.height.toFloat())
        matrix.mapRect(upright)
        matrix.postTranslate(-upright.left, -upright.top)
        matrix.postScale(size.width / upright.width(), size.height / upright.height())

        val output = Bitmap.createBitmap(size.width, size.height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(output)
        canvas.drawColor(Color.WHITE)
        canvas.drawBitmap(source, matrix, Paint(Paint.FILTER_BITMAP_FLAG))
        return output
    }

    private fun write(bitmap: Bitmap): File {
        val target = File(cacheDir, "$PREFIX${System.nanoTime()}-${random.nextInt(Int.MAX_VALUE)}.jpg")
        val written =
            try {
                FileOutputStream(target).use { bitmap.compress(Bitmap.CompressFormat.JPEG, QUALITY, it) }
            } catch (error: java.io.IOException) {
                target.delete()
                throw PhotoPrepareException("failed", "The photo could not be written", error)
            }
        if (!written) {
            target.delete()
            throw PhotoPrepareException("failed", "The photo could not be encoded")
        }
        return target
    }

    private companion object {
        const val QUALITY = 88
        const val PREFIX = "wassla-photo-"
        val random = SecureRandom()
    }
}
