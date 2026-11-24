# P1: the build log says whether Google sign-in is offered (2026-11-24)

Ismail's phone test of 2026-11-24 showed no "Sign in with Google" button. Nothing is deployed by this
change, and no app or server code changed.

## Cause

1. The `profile` and `debug` steps of `android-release.yml` never pass `GOOGLE_SERVER_CLIENT_ID`, so
   `AppConfig.googleServerClientId` is empty and `socialSignInOffers` hides the button on Android.
2. Those builds could not sign in anyway. Flutter's `profile` and `debug` types are signed with the
   runner's auto-generated debug key, new on every run, and Google accepts a sign-in only from a key
   whose SHA-1 is registered as an Android OAuth client for `eu.wassla.app`.
3. The `release` build does pass the id, but needs four `ANDROID_KEYSTORE_*` / `ANDROID_KEY_*`
   secrets that do not exist yet.

## Change

- `tools/mobile_release_config.py` prints a `Google sign-in:` line, next to the Firebase line:
  - Android `release`: on when `GOOGLE_SERVER_CLIENT_ID` is set, otherwise off.
  - Android `profile` and `debug`: off, with the reason and "build release to test Google sign-in".
  - iOS: on when both `GOOGLE_SERVER_CLIENT_ID` and `GOOGLE_IOS_CLIENT_ID` are set (the app's own
    condition, apart from the Apple switch); otherwise off, naming what is missing.
- `android-release.yml` and `ios-release.yml` pass the Google variables to the validation step
  (`INPUT_GOOGLE_SERVER_CLIENT_ID`, and `INPUT_GOOGLE_IOS_CLIENT_ID` on iOS). The profile step's comment
  now says why that build keeps Google off.
- Profile and debug keep Google off on purpose: a button that always fails is worse than none. There
  is no second QA key; Google is tested on `release` builds signed with the permanent key.
- `docs/ANDROID_BUILD_RUNBOOK.md`: a "Test Google sign-in on a phone" section, the build-type table
  says profile and debug never offer Google, and the profile section no longer reads as the
  phone-test path. `docs/WASSLA_SETUP_FOR_ISMAIL.md` step 4: the Android client goes into Google Cloud
  project `waa-eefab` (number `513341711450`), with Ismail's steps for the keystore and the release
  build.

## Checks

The tool has no test suite. It was run locally for every Android build type with the Google value set
and unset, and for iOS with both, one, and neither id; the outputs are in the pull request.

## Owner steps

The six steps in the setup guide and runbook (make the key, add four secrets, read the SHA-1, create
the Android client, consent screen, run a `release` build). They need no code to merge first.
