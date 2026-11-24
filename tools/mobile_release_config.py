#!/usr/bin/env python3
"""Validate a mobile release build's public configuration and name its files.

Run by the manual Android and iOS release workflows before anything is built,
from the `mobile/` folder:

    python ../tools/mobile_release_config.py android|ios

It reads the workflow's inputs from the environment (INPUT_*), refuses an API
origin that is not a credential-free HTTPS origin and a Firebase client tuple
that is only partly set, says in the run log whether the build can do push
and whether it can offer Google sign-in, and writes `api_base_url`, `artifact_name` and `file_stem` to $GITHUB_OUTPUT.

Everything here is public build configuration: the Firebase values are client
identifiers that ship inside every app. No secret is read or printed.
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

FIREBASE_APP_ID = {"android": "FIREBASE_ANDROID_APP_ID", "ios": "FIREBASE_IOS_APP_ID"}


def _valid_host(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        labels = hostname.rstrip(".").split(".")
        return bool(hostname) and all(
            1 <= len(label) <= 63
            and label[0].isalnum()
            and label[-1].isalnum()
            and all(character.isalnum() or character == "-" for character in label)
            for label in labels
        )


def api_base_url() -> str:
    value = os.environ["INPUT_API_BASE_URL"].strip()
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError as exc:
        raise SystemExit("api_base_url has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or not _valid_host(parsed.hostname or "")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("api_base_url must be a credential-free HTTPS origin")
    return value.rstrip("/")


def report_firebase(platform: str) -> None:
    names = (
        "FIREBASE_API_KEY",
        "FIREBASE_PROJECT_ID",
        "FIREBASE_MESSAGING_SENDER_ID",
        FIREBASE_APP_ID[platform],
    )
    values = {name: os.environ.get(f"INPUT_{name}", "").strip() for name in names}
    configured = [name for name, value in values.items() if value]
    if configured and len(configured) != len(values):
        missing = sorted(set(values) - set(configured))
        raise SystemExit(
            "Firebase client configuration must be all-or-none; missing "
            + ", ".join(missing)
        )
    # Say, in the run log, whether this artifact can do push at all. An
    # all-absent tuple is a legitimate state (push stays unavailable and the
    # rest of the app works), and it is indistinguishable from a complete one
    # everywhere else in the job, which is how a push-dead QA build gets handed
    # to a tester as a push build.
    if configured:
        key = values["FIREBASE_API_KEY"]
        print(
            "Firebase client configuration: complete"
            f" (project {values['FIREBASE_PROJECT_ID']},"
            f" sender {values['FIREBASE_MESSAGING_SENDER_ID']},"
            f" {platform} app {values[FIREBASE_APP_ID[platform]]},"
            f" api key {key[:6]}...[{len(key)} chars])"
        )
    else:
        print("Firebase client configuration: absent - this build keeps push unavailable")


def report_google_sign_in(platform: str) -> None:
    # Say, in the run log, whether this artifact can offer Google sign-in, for
    # the same reason as the push line above. Android profile and debug builds
    # are signed with the runner's auto-generated debug key, which changes on
    # every run, so no Android OAuth client can ever list it: the app would
    # show a button that always fails. The workflow does not pass the Google
    # id to those builds, and this line says why.
    server_id = os.environ.get("INPUT_GOOGLE_SERVER_CLIENT_ID", "").strip()
    if platform == "android":
        build_type = os.environ["INPUT_BUILD_TYPE"]
        if build_type != "release":
            print(
                "Google sign-in: off - this build is signed with a key that changes"
                " on every run, which Google cannot accept; build release to test"
                " Google sign-in"
            )
        elif server_id:
            print(
                "Google sign-in: on - the release key's SHA-1 must be registered as"
                " an Android OAuth client for eu.wassla.app"
            )
        else:
            print(
                "Google sign-in: off - GOOGLE_SERVER_CLIENT_ID is not set, so the"
                " button stays hidden"
            )
        return
    ios_id = os.environ.get("INPUT_GOOGLE_IOS_CLIENT_ID", "").strip()
    if server_id and ios_id:
        print("Google sign-in: on")
    else:
        missing = [
            name
            for name, value in (
                ("GOOGLE_SERVER_CLIENT_ID", server_id),
                ("GOOGLE_IOS_CLIENT_ID", ios_id),
            )
            if not value
        ]
        print(
            "Google sign-in: off - "
            + " and ".join(missing)
            + " not set, so the button stays hidden"
        )


def file_stem(platform: str) -> str:
    pubspec = Path("pubspec.yaml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^version:\s*([^+\s]+)(?:\+([^\s]+))?\s*$", pubspec)
    if match is None:
        raise SystemExit("mobile/pubspec.yaml has no parseable version")
    version, build_number = match.groups()
    build_number = os.environ.get("INPUT_BUILD_NUMBER", "").strip() or build_number

    release_id = os.environ.get("INPUT_RELEASE_ID", "").strip()
    if not release_id:
        release_id = f"v{version}"
        if build_number:
            release_id += f"-build.{build_number}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", release_id):
        raise SystemExit(
            "release_id must be 1-64 characters using only letters, digits, dot, "
            "underscore, or hyphen"
        )

    short_sha = os.environ["GITHUB_SHA"][:7]
    if platform == "android":
        build_type = os.environ["INPUT_BUILD_TYPE"]
        apk_architecture = os.environ["INPUT_APK_ARCHITECTURE"]
        return f"shiptrip-{release_id}-{short_sha}-{build_type}-{apk_architecture}"
    return f"wassla-{release_id}-{short_sha}-ios-appstore"


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in FIREBASE_APP_ID:
        raise SystemExit("usage: mobile_release_config.py android|ios")
    platform = sys.argv[1]
    if platform == "ios":
        build_number = os.environ.get("INPUT_BUILD_NUMBER", "").strip()
        if build_number and not re.fullmatch(r"[1-9][0-9]{0,8}", build_number):
            raise SystemExit("build_number must be a positive whole number")
    origin = api_base_url()
    report_firebase(platform)
    report_google_sign_in(platform)
    stem = file_stem(platform)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as handle:
        handle.write(f"api_base_url={origin}\n")
        handle.write(f"artifact_name={stem}\n")
        handle.write(f"file_stem={stem}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
