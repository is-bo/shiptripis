package eu.wassla.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ImageDecoder
import android.graphics.Matrix
import android.os.Build
import androidx.annotation.RequiresApi
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.io.FileOutputStream
import java.security.SecureRandom

/** What went wrong, as a code the Dart side maps: `not_found`, `unsupported` or `failed`. */
class PhotoPrepareException(val code: String, message: String, cause: Throwable? = null) :
    Exception(message, cause)

/**
 * The numbers behind [PhotoPreparer], with no decoding in them: how far to
 * sample while decoding, how far to scale afterwards, and which matrix undoes
 * an EXIF orientation.
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

    private const val MAX_SAMPLE = 1024

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

    /** The factor (never above 1) that brings the longer side to [MAX_EDGE]. */
    fun fitScale(width: Int, height: Int): Float {
        val longEdge = maxOf(width, height)
        return if (longEdge <= MAX_EDGE) 1f else MAX_EDGE.toFloat() / longEdge
    }

    /**
     * The matrix that makes a picture upright for each of the eight EXIF
     * orientations, reflections (2, 4, 5 and 7) included.
     */
    fun orientationMatrix(orientation: Int): Matrix {
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
 * decoder is asked to sample, so the pixels in memory are bounded. The result
 * is written to a new file in [cacheDir].
 */
class PhotoPreparer(private val cacheDir: File) {

    private class Decoded(val bitmap: Bitmap, val orientationApplied: Boolean)

    fun prepare(path: String): File {
        val source = File(path)
        if (!source.isFile) throw PhotoPrepareException("not_found", "The picked photo is gone")

        val decoded = decode(source)
        var current = decoded.bitmap
        try {
            val matrix =
                if (decoded.orientationApplied) Matrix()
                else PhotoGeometry.orientationMatrix(exifOrientation(source))
            val scale = PhotoGeometry.fitScale(current.width, current.height)
            if (scale < 1f) matrix.postScale(scale, scale)
            if (!matrix.isIdentity) {
                val transformed =
                    Bitmap.createBitmap(current, 0, 0, current.width, current.height, matrix, true)
                if (transformed !== current) current.recycle()
                current = transformed
            }
            if (current.hasAlpha()) {
                val flat = flatten(current)
                current.recycle()
                current = flat
            }
            return write(current)
        } catch (error: OutOfMemoryError) {
            throw PhotoPrepareException("failed", "Out of memory", error)
        } finally {
            current.recycle()
        }
    }

    /** The picture decoded at a sample that bounds its pixels. */
    private fun decode(source: File): Decoded {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(source.path, bounds)
        if (bounds.outWidth > 0 && bounds.outHeight > 0) {
            var sample = PhotoGeometry.sampleSize(bounds.outWidth, bounds.outHeight)
            var attempts = 0
            while (true) {
                try {
                    val options =
                        BitmapFactory.Options().apply {
                            inSampleSize = sample
                            inPreferredConfig = Bitmap.Config.ARGB_8888
                        }
                    val bitmap = BitmapFactory.decodeFile(source.path, options)
                    if (bitmap != null) return Decoded(bitmap, false)
                    break
                } catch (error: OutOfMemoryError) {
                    attempts += 1
                    if (attempts > 3) throw PhotoPrepareException("failed", "Out of memory", error)
                    sample *= 2
                }
            }
        }
        // BitmapFactory could not read it (a HEIF file on some builds): the
        // platform decoder can, from API 28.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) return decodeWithImageDecoder(source)
        throw PhotoPrepareException("unsupported", "The photo cannot be decoded")
    }

    /**
     * ImageDecoder applies the orientation itself, so [Decoded.orientationApplied]
     * is true and no matrix is applied again.
     */
    @RequiresApi(Build.VERSION_CODES.P)
    private fun decodeWithImageDecoder(source: File): Decoded {
        try {
            val bitmap =
                ImageDecoder.decodeBitmap(ImageDecoder.createSource(source)) { decoder, info, _ ->
                    decoder.setTargetSampleSize(
                        PhotoGeometry.sampleSize(info.size.width, info.size.height)
                    )
                    decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                }
            return Decoded(bitmap, true)
        } catch (error: OutOfMemoryError) {
            throw PhotoPrepareException("failed", "Out of memory", error)
        } catch (error: Exception) {
            throw PhotoPrepareException("unsupported", "The photo cannot be decoded", error)
        }
    }

    private fun exifOrientation(source: File): Int =
        try {
            ExifInterface(source.path)
                .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        } catch (error: Exception) {
            ExifInterface.ORIENTATION_NORMAL
        }

    /** A JPEG has no alpha: transparent pixels become white, as the server does. */
    private fun flatten(source: Bitmap): Bitmap {
        val flat = Bitmap.createBitmap(source.width, source.height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(flat)
        canvas.drawColor(Color.WHITE)
        canvas.drawBitmap(source, 0f, 0f, null)
        return flat
    }

    private fun write(bitmap: Bitmap): File {
        val target = File(cacheDir, "wassla-photo-${System.nanoTime()}-${random.nextInt(Int.MAX_VALUE)}.jpg")
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
        val random = SecureRandom()
    }
}
