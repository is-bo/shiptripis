#!/usr/bin/env bash
# Runs the plain-JVM tests of the Android photo code (PhotoGeometry, JpegMetadata)
# with kotlinc and JUnit, with no Android SDK or Gradle needed: those two files
# use no Android type. Set KOTLINC to a kotlinc binary and JUNIT_DIR to a folder
# holding junit-4.13.2.jar and hamcrest-core-1.3.jar to skip the downloads.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
app="$root/mobile/android/app/src"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if [ -z "${KOTLINC:-}" ]; then
  curl -fsSL -o "$work/kotlin.zip" \
    https://github.com/JetBrains/kotlin/releases/download/v2.1.0/kotlin-compiler-2.1.0.zip
  unzip -q "$work/kotlin.zip" -d "$work"
  KOTLINC="$work/kotlinc/bin/kotlinc"
fi
if [ -z "${JUNIT_DIR:-}" ]; then
  JUNIT_DIR="$work"
  curl -fsSL -o "$work/junit-4.13.2.jar" \
    https://repo1.maven.org/maven2/junit/junit/4.13.2/junit-4.13.2.jar
  curl -fsSL -o "$work/hamcrest-core-1.3.jar" \
    https://repo1.maven.org/maven2/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar
fi
classpath="$JUNIT_DIR/junit-4.13.2.jar:$JUNIT_DIR/hamcrest-core-1.3.jar"

"$KOTLINC" -cp "$classpath" -d "$work/out" \
  "$app/main/kotlin/eu/wassla/app/PhotoGeometry.kt" \
  "$app/main/kotlin/eu/wassla/app/JpegMetadata.kt" \
  "$app/main/kotlin/eu/wassla/app/PickLaunchGate.kt" \
  "$app/test/kotlin/eu/wassla/app/PhotoGeometryTest.kt" \
  "$app/test/kotlin/eu/wassla/app/JpegMetadataTest.kt" \
  "$app/test/kotlin/eu/wassla/app/PickLaunchGateTest.kt"
stdlib="$(dirname "$KOTLINC")/../lib/kotlin-stdlib.jar"
java -cp "$work/out:$stdlib:$classpath" org.junit.runner.JUnitCore \
  eu.wassla.app.PhotoGeometryTest eu.wassla.app.JpegMetadataTest eu.wassla.app.PickLaunchGateTest
