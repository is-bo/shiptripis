#!/bin/sh
# Stops an iOS build whose sign-in build defines and native settings
# disagree. Run by the Runner target's "Check sign-in settings" phase.
#
# Google: the app offers Google on iOS from the GOOGLE_IOS_CLIENT_ID define,
# and GoogleSignIn needs the URL scheme derived from GOOGLE_IOS_CLIENT_PREFIX
# (ios/Flutter/SocialSignIn.xcconfig). A missing or different scheme crashes
# the app at the first tap, so a mismatch fails the build.
#
# Apple: APPLE_SIGN_IN_ENABLED=true without the Sign in with Apple
# entitlement fails at Apple's sheet, so it fails the build too. The switch
# that picks the entitlements file must be YES or NO: anything else would
# sign the app with no entitlements at all, push included.
#
# DART_DEFINES is Flutter's comma-separated list of base64 "NAME=value"
# entries.
set -u

decode() {
  printf '%s' "$1" | base64 -d 2>/dev/null || printf '%s' "$1" | base64 -D 2>/dev/null
}

define() {
  old_ifs=$IFS
  IFS=,
  for entry in ${DART_DEFINES:-}; do
    pair=$(decode "$entry")
    case "$pair" in
      "$1="*) IFS=$old_ifs; printf '%s' "${pair#"$1="}"; return ;;
    esac
  done
  IFS=$old_ifs
}

status=0
prefix=${GOOGLE_IOS_CLIENT_PREFIX:-}
google=$(define GOOGLE_IOS_CLIENT_ID)
apple=$(define APPLE_SIGN_IN_ENABLED)

if [ -n "$google" ]; then
  expected="$prefix.apps.googleusercontent.com"
  if [ -z "$prefix" ] || [ "$google" != "$expected" ]; then
    echo "error: GOOGLE_IOS_CLIENT_ID ($google) must be GOOGLE_IOS_CLIENT_PREFIX in ios/Flutter/SocialSignIn.xcconfig followed by .apps.googleusercontent.com (now: ${prefix:-empty})."
    status=1
  fi
elif [ -n "$prefix" ]; then
  echo "warning: GOOGLE_IOS_CLIENT_PREFIX is set but the GOOGLE_IOS_CLIENT_ID define is not: this build does not offer Google."
fi

capability=${APPLE_SIGN_IN_CAPABILITY:-}
case "$capability" in
  YES|NO) ;;
  *)
    echo "error: APPLE_SIGN_IN_CAPABILITY in ios/Flutter/SocialSignIn.xcconfig must be YES or NO (now: ${capability:-empty})."
    status=1
    ;;
esac

if [ "$apple" = "true" ] && [ "$capability" != "YES" ]; then
  echo "error: APPLE_SIGN_IN_ENABLED=true needs APPLE_SIGN_IN_CAPABILITY = YES in ios/Flutter/SocialSignIn.xcconfig."
  status=1
fi

exit $status
