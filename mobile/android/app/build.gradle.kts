plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val releaseKeystorePath = System.getenv("ANDROID_KEYSTORE_PATH")?.takeIf { it.isNotBlank() }
val releaseKeystorePassword =
    System.getenv("ANDROID_KEYSTORE_PASSWORD")?.takeIf { it.isNotBlank() }
val releaseKeyAlias = System.getenv("ANDROID_KEY_ALIAS")?.takeIf { it.isNotBlank() }
val releaseKeyPassword = System.getenv("ANDROID_KEY_PASSWORD")?.takeIf { it.isNotBlank() }
val hasReleaseSigning =
    listOf(
        releaseKeystorePath,
        releaseKeystorePassword,
        releaseKeyAlias,
        releaseKeyPassword,
    ).all { it != null }
val requestsReleaseArtifact =
    gradle.startParameter.taskNames.any { taskName ->
        taskName.endsWith("Release", ignoreCase = true)
    }

if (requestsReleaseArtifact && !hasReleaseSigning) {
    throw GradleException(
        "Release signing is not configured. Set ANDROID_KEYSTORE_PATH, " +
            "ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS, and ANDROID_KEY_PASSWORD.",
    )
}

android {
    namespace = "eu.wassla.app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        applicationId = "eu.wassla.app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 24
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseKeystorePath!!)
                storePassword = releaseKeystorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        release {
            // Release artifacts are never signed with the debug key. CI supplies
            // all four values from GitHub Secrets and decodes the keystore into
            // the runner's temporary directory. Without them this build type is
            // refused above before Gradle can produce an unsigned artifact.
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
}

dependencies {
    // Reads the EXIF orientation of a picked photo (all eight values) in
    // PhotoPrepare.kt. Named here because it is the app's own code that uses it.
    implementation("androidx.exifinterface:exifinterface:1.3.7")

    // The plain-JVM tests of PhotoGeometry and JpegMetadata (src/test). CI runs
    // them with kotlinc (tools/test_android_pure.sh); this lets Gradle's
    // :app:testDebugUnitTest compile them too.
    testImplementation("junit:junit:4.13.2")
}

flutter {
    source = "../.."
}
