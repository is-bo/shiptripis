# ShipTrip Android Build Runbook

The repository's manual **Build Android** GitHub Actions workflow is the only
release-artifact path documented here. A normal push runs validation CI but does
not publish an Android release or deploy to Google Play.

## GitHub release-signing secrets

Create these repository Actions secrets under **Settings → Secrets and
variables → Actions**:

- `ANDROID_KEYSTORE_BASE64`: the complete release keystore encoded as one
  base64 value
- `ANDROID_KEYSTORE_PASSWORD`: the keystore password
- `ANDROID_KEY_ALIAS`: the release key alias
- `ANDROID_KEY_PASSWORD`: the release key password

The keystore and passwords must not be added to the repository, workflow
inputs, Actions variables, documentation, issue text, or build artifacts. The
workflow decodes the keystore under the runner's temporary directory, passes
the signing values only through the job environment, verifies the APK and AAB
signatures, removes the temporary keystore, and lets GitHub discard the runner.

`API_BASE_URL` is a public build-time configuration value, not a secret. A
release build accepts only a credential-free HTTPS origin. The app contains no
Stripe, Chargily, SMTP, object-storage, or backend secret.

## Build a signed pre-launch release

1. Open the repository on GitHub.
2. Select **Actions → Build Android → Run workflow**.
3. Keep **build_type** set to `release`.
4. Enter the deployed public ShipTrip gateway origin in **api_base_url**. Do not
   add `/api` or another path.
5. Optionally enter an approved RC label such as `v1.0.0-rc.1`; otherwise the
   workflow derives one from the full `mobile/pubspec.yaml` version.
6. Run the workflow and require every step to pass.

The artifact name includes the version/RC label, short Git SHA, and `release`.
Its ZIP contains a signed APK for direct installation, a signed AAB for future
Google Play submission, and `SHA256SUMS.txt`.

If signing secrets are not configured yet, select `debug`. The workflow then
builds and uploads a clearly labeled debug APK only. It does not silently
substitute the debug key for a release build. Debug artifacts are for controlled
development installation, not release distribution.

## Three build types, three purposes

The workflow's `build_type` input keeps three artifacts conceptually separate.
They are not interchangeable.

| `build_type` | Purpose | Signed with | Distributable |
| --- | --- | --- | --- |
| `release` | The pre-launch and store artifact | The release keystore, from Actions secrets | Yes, once launch approval exists |
| `profile` | Private device-performance QA | The runner's local Android debug key | No |
| `debug` | Install-only fallback when nothing else builds | The runner's local Android debug key | No |

`release` is the only signed path, and it stays that way: the Gradle build
refuses any `*Release` task unless all four signing values are present, so a
debug key can never be substituted into a release artifact.

## Build a private profile APK for device performance

Debug builds are the wrong instrument for judging whether the app feels fast on
a real phone. A debug APK runs Dart under the JIT engine, ships the Vulkan
validation layer, and disables the compiler optimisations a shipped build uses;
it is slower than the product by a wide and misleading margin. Profile is
Flutter's measurement mode: the same AOT-compiled Dart as release, the same
optimised engine, with only the tracing hooks a profiler needs left in.

1. Select **Actions → Build Android → Run workflow**.
2. Set **build_type** to `profile` and **apk_architecture** to `arm64`.
3. Enter the deployed gateway origin in **api_base_url**.
4. Run the workflow.

Before uploading, the workflow proves the artifact really is profile: AOT
`libapp.so` present, and the debug-only Dart kernel blob and Vulkan validation
layer absent. Timings taken from a profile build are still marginally slower
than release, because the tracing instrumentation is real; treat it as an upper
bound on frame cost, not as the release number. A profile APK is for private
QA only and must never be distributed.

## Download and install the APK

1. Open the repository on GitHub.
2. Open **Actions**.
3. Select **Build Android**.
4. Open the latest successful run for the intended commit and build type.
5. Download the Android artifact from the **Artifacts** section.
6. Extract the ZIP GitHub downloads.
7. Transfer the `.apk` to the Android phone, or open it from the phone's browser
   or file manager.
8. When Android prompts, allow **Install unknown apps** only for that browser or
   file-manager app.
9. Install ShipTrip. Play Protect may warn because this is a sideloaded private
   pre-release; review the warning and artifact identity rather than disabling
   Android security globally.

An `.apk` installs directly on a phone. An `.aab` is the Google Play distribution
bundle and cannot be installed directly.

## Optional RC GitHub Release

After an RC build is green, create a tag on the exact reviewed commit and push
it normally:

```text
git tag -a v1.0.0-rc.1 <reviewed-commit-sha>
git push origin v1.0.0-rc.1
```

Create a **pre-release** (not a final release) for that tag in GitHub, download
the matching successful Build Android artifact, and attach its APK, AAB, and
checksum file. Verify the short SHA embedded in each filename matches the tag's
commit. Do not create a final release or submit the AAB to Google Play until the
separate launch approval is complete.
