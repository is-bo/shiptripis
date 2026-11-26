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
import java.security.SecureRandom

/**
 * What went wrong, as a code the Dart side maps: `not_found` (the file is gone),
 * `unsupported` (a decoder refused the picture) or `failed` (anything else: no
 * memory, a write that did not work).
 */
class PhotoPrepareException(val code: String, message: String, cause: Throwable? = null) :
    Exception(message, cause)

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
 * that fails for memory is tried again at a larger sample (the header's sample,
 * then twice, four times and eight times it: see [PhotoGeometry.sampleLadder]).
 * Whatever the decoder produced (a wide-gamut or HDR bitmap, one with a gain map
 * or an embedded profile) is only the source: the output is always drawn into a
 * fresh sRGB ARGB_8888 bitmap of the computed size, and that bitmap is what is
 * compressed. The encoder's own metadata (Skia writes an ICC profile even for
 * sRGB) is then cut out of the JPEG ([JpegMetadata]) before the result is
 * written to a new file in [cacheDir].
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
     * out). A decode that runs out of memory is tried at each larger sample of the
     * [PhotoGeometry.sampleLadder], then fails.
     */
    private fun decodeWithBitmapFactory(source: File): Decoded? {
        val bounds = BitmapFactory.Options()
        bounds.inJustDecodeBounds = true
        BitmapFactory.decodeFile(source.path, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var outOfMemory: OutOfMemoryError? = null
        for (sample in PhotoGeometry.sampleLadder(
            PhotoGeometry.sampleSize(bounds.outWidth, bounds.outHeight)
        )) {
            try {
                val options = BitmapFactory.Options()
                options.inSampleSize = sample
                options.inPreferredConfig = Bitmap.Config.ARGB_8888
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    options.inPreferredColorSpace = ColorSpace.get(ColorSpace.Named.SRGB)
                }
                val bitmap = BitmapFactory.decodeFile(source.path, options)
                if (bitmap != null) return Decoded(bitmap, false)
                outOfMemory = null
            } catch (error: OutOfMemoryError) {
                outOfMemory = error
            }
            // Nothing came out: memory is the likely reason, so the next sample.
        }
        if (outOfMemory != null) throw PhotoPrepareException("failed", "Out of memory", outOfMemory)
        return null
    }

    /**
     * ImageDecoder applies the orientation itself, so [Decoded.orientationApplied]
     * is true and no matrix is applied again. The picture's size is read first, in
     * onHeaderDecoded, before any pixel: a picture over
     * [PhotoGeometry.MAX_SOURCE_PIXELS] is refused there (a HEIF that is not tiled
     * is decoded as one whole frame whatever sample is asked for), and the rest is
     * decoded at the [PhotoGeometry.sampleLadder] sample for this attempt, so a
     * decode that ran out of memory is tried at a sample that is really larger.
     */
    @RequiresApi(Build.VERSION_CODES.P)
    private fun decodeWithImageDecoder(source: File): Decoded {
        var attempt = 0
        while (true) {
            var ladder = emptyList<Int>()
            try {
                val bitmap =
                    ImageDecoder.decodeBitmap(ImageDecoder.createSource(source)) { decoder, info, _ ->
                        val width = info.size.width
                        val height = info.size.height
                        if (!PhotoGeometry.withinSourceLimit(width, height)) {
                            throw PhotoPrepareException("failed", "The photo is too large to prepare")
                        }
                        ladder = PhotoGeometry.sampleLadder(PhotoGeometry.sampleSize(width, height))
                        decoder.setTargetSampleSize(ladder[minOf(attempt, ladder.lastIndex)])
                        decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                        decoder.setTargetColorSpace(ColorSpace.get(ColorSpace.Named.SRGB))
                    }
                return Decoded(bitmap, true)
            } catch (error: PhotoPrepareException) {
                throw error
            } catch (error: OutOfMemoryError) {
                if (attempt + 1 >= ladder.size) {
                    throw PhotoPrepareException("failed", "Out of memory", error)
                }
                attempt += 1
            } catch (error: java.io.IOException) {
                // The decoder could not read it, or the file went away under it.
                if (!source.isFile) throw PhotoPrepareException("not_found", "The picked photo is gone", error)
                throw PhotoPrepareException("unsupported", "The photo cannot be decoded", error)
            } catch (error: Exception) {
                throw PhotoPrepareException("failed", "The photo could not be decoded", error)
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
        val encoded = java.io.ByteArrayOutputStream()
        if (!bitmap.compress(Bitmap.CompressFormat.JPEG, QUALITY, encoded)) {
            throw PhotoPrepareException("failed", "The photo could not be encoded")
        }
        val clean =
            JpegMetadata.withoutMetadata(encoded.toByteArray())
                ?: throw PhotoPrepareException("failed", "The encoded photo could not be read")
        val target = File(cacheDir, "$PREFIX${System.nanoTime()}-${random.nextInt(Int.MAX_VALUE)}.jpg")
        try {
            target.writeBytes(clean)
        } catch (error: java.io.IOException) {
            target.delete()
            throw PhotoPrepareException("failed", "The photo could not be written", error)
        }
        return target
    }

    private companion object {
        const val QUALITY = 88
        const val PREFIX = "wassla-photo-"
        val random = SecureRandom()
    }
}
