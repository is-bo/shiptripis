#!/usr/bin/env python3
"""Fail CI when the iOS configuration is unreadable, carries a sign-in value,
loses push or a store requirement, or could let the app's defines and its
native settings disagree.

`plutil -lint` needs macOS; Python's `plistlib` parses the same format, so a
broken `Info.plist`, entitlements file or privacy manifest is caught here
instead of in Xcode.

What is checked:

* `Runner/Info.plist`, both entitlements files and `Runner/PrivacyInfo.xcprivacy`
  parse as plists;
* Google's URL scheme is made from `GOOGLE_IOS_CLIENT_PREFIX`, and the plist
  lists no client id of its own (the app passes the define at run time);
* push: both entitlements files carry `aps-environment` and `Info.plist` has
  the `remote-notification` background mode, so every signed build can
  receive notifications;
* Sign in with Apple is only in `Runner/RunnerAppleSignIn.entitlements`, and
  every Runner build configuration signs with `$(RUNNER_ENTITLEMENTS)`, which
  `Flutter/SocialSignIn.xcconfig` picks from `APPLE_SIGN_IN_CAPABILITY`, so the
  capability is needed only once Ismail sets it;
* `Flutter/SocialSignIn.xcconfig` defines the settings, leaves
  `GOOGLE_IOS_CLIENT_PREFIX` empty and `APPLE_SIGN_IN_CAPABILITY` at NO in Git,
  and `Debug.xcconfig` and `Release.xcconfig` include it;
* App Store requirements: the encryption answer, the camera and photo-library
  purpose strings in English, French and Arabic (`<lang>.lproj/InfoPlist.strings`,
  a localized group in the Runner's resources), the app's languages, and a
  privacy manifest without tracking, in the Runner's resources;
* the Runner target runs `scripts/check_social_sign_in.sh` before compiling,
  and that script accepts and refuses the right combinations of defines and
  settings (run here with fake environments, as Xcode would run it).
"""

from __future__ import annotations

import base64
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path


IOS = Path(__file__).resolve().parents[1] / "mobile" / "ios"
SCRIPT = IOS / "scripts" / "check_social_sign_in.sh"
PHASE_ID = "5A0C1E2D3F4B5A6C7D8E9F01"
LANGUAGES = ("en", "fr", "ar")
USAGE_KEYS = ("NSCameraUsageDescription", "NSPhotoLibraryUsageDescription")


def _defines(**values: str) -> str:
    return ",".join(
        base64.b64encode(f"{name}={value}".encode()).decode()
        for name, value in values.items()
    )


# The settings Xcode exports from SocialSignIn.xcconfig as committed.
COMMITTED = {"APPLE_SIGN_IN_CAPABILITY": "NO"}
APPLE_ON = {"APPLE_SIGN_IN_CAPABILITY": "YES"}

# (what, DART_DEFINES, build settings, expected exit status)
SCRIPT_CASES = [
    ("nothing configured", "", COMMITTED, 0),
    ("other defines only", _defines(API_BASE_URL="https://a.example"), COMMITTED, 0),
    (
        "Google define matches the prefix",
        _defines(
            API_BASE_URL="https://a.example",
            GOOGLE_IOS_CLIENT_ID="123-abc.apps.googleusercontent.com",
        ),
        {**COMMITTED, "GOOGLE_IOS_CLIENT_PREFIX": "123-abc"},
        0,
    ),
    (
        "Google define without a prefix",
        _defines(GOOGLE_IOS_CLIENT_ID="123-abc.apps.googleusercontent.com"),
        COMMITTED,
        1,
    ),
    (
        "Google define for another client",
        _defines(GOOGLE_IOS_CLIENT_ID="999-zzz.apps.googleusercontent.com"),
        {**COMMITTED, "GOOGLE_IOS_CLIENT_PREFIX": "123-abc"},
        1,
    ),
    (
        "prefix without the define (warning)",
        "",
        {**COMMITTED, "GOOGLE_IOS_CLIENT_PREFIX": "123-abc"},
        0,
    ),
    ("Apple on without the capability", _defines(APPLE_SIGN_IN_ENABLED="true"), COMMITTED, 1),
    ("Apple on with the capability", _defines(APPLE_SIGN_IN_ENABLED="true"), APPLE_ON, 0),
    ("Apple off with the capability", _defines(APPLE_SIGN_IN_ENABLED="false"), APPLE_ON, 0),
    ("capability missing", "", {}, 1),
    ("capability misspelt", "", {"APPLE_SIGN_IN_CAPABILITY": "yes"}, 1),
]


def main() -> int:
    errors: list[str] = []

    def load(path: Path) -> dict | None:
        try:
            with path.open("rb") as handle:
                value = plistlib.load(handle)
        except Exception as exc:  # noqa: BLE001 - any parse failure is a failure
            errors.append(f"{path.relative_to(IOS)} does not parse: {exc}")
            return None
        if not isinstance(value, dict):
            errors.append(f"{path.relative_to(IOS)} is not a dictionary")
            return None
        return value

    info = load(IOS / "Runner" / "Info.plist")
    if info is not None:
        if "remote-notification" not in info.get("UIBackgroundModes", []):
            errors.append("Info.plist needs the remote-notification background mode")
        if info.get("ITSAppUsesNonExemptEncryption") is not False:
            errors.append("Info.plist must set ITSAppUsesNonExemptEncryption to false")
        if list(info.get("CFBundleLocalizations", [])) != list(LANGUAGES):
            errors.append(f"Info.plist CFBundleLocalizations must be {list(LANGUAGES)}")
        for key in USAGE_KEYS:
            if not str(info.get(key, "")).strip():
                errors.append(f"Info.plist needs {key}")
        if "GIDClientID" in info:
            errors.append("Info.plist must not list GIDClientID")
        schemes = [
            scheme
            for url_type in info.get("CFBundleURLTypes", [])
            for scheme in url_type.get("CFBundleURLSchemes", [])
        ]
        if "com.googleusercontent.apps.$(GOOGLE_IOS_CLIENT_PREFIX)" not in schemes:
            errors.append(
                "Info.plist needs the URL scheme "
                "com.googleusercontent.apps.$(GOOGLE_IOS_CLIENT_PREFIX)"
            )

    for name, apple in (
        ("Runner.entitlements", False),
        ("RunnerAppleSignIn.entitlements", True),
    ):
        entitlements = load(IOS / "Runner" / name)
        if entitlements is None:
            continue
        if entitlements.get("aps-environment") not in ("development", "production"):
            errors.append(f"{name} must carry aps-environment (push)")
        asks_apple = entitlements.get("com.apple.developer.applesignin") == ["Default"]
        if asks_apple != apple:
            errors.append(
                f"{name} must {'' if apple else 'not '}ask for Sign in with Apple"
            )

    manifest = load(IOS / "Runner" / "PrivacyInfo.xcprivacy")
    if manifest is not None:
        if manifest.get("NSPrivacyTracking") is not False:
            errors.append("PrivacyInfo.xcprivacy must set NSPrivacyTracking to false")
        if manifest.get("NSPrivacyTrackingDomains"):
            errors.append("PrivacyInfo.xcprivacy must list no tracking domains")
        for collected in manifest.get("NSPrivacyCollectedDataTypes", []):
            if collected.get("NSPrivacyCollectedDataTypeTracking") is not False:
                errors.append(
                    f"PrivacyInfo.xcprivacy: {collected.get('NSPrivacyCollectedDataType')} "
                    "must not be used for tracking"
                )
        if not manifest.get("NSPrivacyCollectedDataTypes"):
            errors.append("PrivacyInfo.xcprivacy must declare the data the app collects")

    for language in LANGUAGES:
        path = IOS / "Runner" / f"{language}.lproj" / "InfoPlist.strings"
        try:
            strings = dict(
                re.findall(r'^"(\w+)" = "((?:[^"\\]|\\.)+)";$', path.read_text(), flags=re.M)
            )
        except OSError:
            strings = {}
        for key in USAGE_KEYS:
            if not strings.get(key, "").strip():
                errors.append(f"{language}.lproj/InfoPlist.strings needs {key}")

    xcconfig = (IOS / "Flutter" / "SocialSignIn.xcconfig").read_text()
    settings = dict(
        re.findall(r"^\s*([A-Z_]+)\s*=(.*)$", xcconfig, flags=re.MULTILINE)
    )
    expected_settings = {
        "GOOGLE_IOS_CLIENT_PREFIX": "",
        "APPLE_SIGN_IN_CAPABILITY": "NO",
        "RUNNER_ENTITLEMENTS_NO": "Runner/Runner.entitlements",
        "RUNNER_ENTITLEMENTS_YES": "Runner/RunnerAppleSignIn.entitlements",
        "RUNNER_ENTITLEMENTS": "$(RUNNER_ENTITLEMENTS_$(APPLE_SIGN_IN_CAPABILITY))",
    }
    for name, value in expected_settings.items():
        if name not in settings:
            errors.append(f"SocialSignIn.xcconfig must define {name}")
        elif settings[name].strip() != value:
            errors.append(f"SocialSignIn.xcconfig must set {name} = {value} in Git")

    for config in ("Debug", "Release"):
        text = (IOS / "Flutter" / f"{config}.xcconfig").read_text()
        if '#include "SocialSignIn.xcconfig"' not in text:
            errors.append(f"{config}.xcconfig must include SocialSignIn.xcconfig")

    project = (IOS / "Runner.xcodeproj" / "project.pbxproj").read_text()
    runner_configs = project.count("INFOPLIST_FILE = Runner/Info.plist;")
    entitled = project.count('CODE_SIGN_ENTITLEMENTS = "$(RUNNER_ENTITLEMENTS)";')
    if runner_configs == 0 or entitled != runner_configs:
        errors.append(
            "every Runner build configuration needs CODE_SIGN_ENTITLEMENTS = "
            f"$(RUNNER_ENTITLEMENTS) ({entitled} of {runner_configs})"
        )
    if re.search(r"Runner/Runner(AppleSignIn)?\.entitlements", project):
        errors.append("project.pbxproj must not name an entitlements file itself")
    if project.count("{") != project.count("}") or project.count("(") != project.count(
        ")"
    ):
        errors.append("project.pbxproj braces or parentheses are unbalanced")

    phases = re.search(
        r"97C146ED1CF9000F007C117D /\* Runner \*/ = \{.*?buildPhases = \((.*?)\);",
        project,
        flags=re.DOTALL,
    )
    order = re.findall(r"([0-9A-F]{24}) /\*", phases.group(1)) if phases else []
    flutter, sources = "9740EEB61CF901F6004384FC", "97C146EA1CF9000F007C117D"
    if not (
        PHASE_ID in order
        and flutter in order
        and sources in order
        and order.index(flutter) < order.index(PHASE_ID) < order.index(sources)
    ):
        errors.append(
            "the Runner target must run the sign-in check after Flutter's build "
            "phase and before compiling"
        )
    resources = re.search(
        r"97C146EC1CF9000F007C117D /\* Resources \*/ = \{.*?files = \((.*?)\);",
        project,
        flags=re.DOTALL,
    )
    bundled = resources.group(1) if resources else ""
    for resource in ("PrivacyInfo.xcprivacy", "InfoPlist.strings"):
        if f"/* {resource} in Resources */" not in bundled:
            errors.append(f"the Runner target must bundle {resource}")
    variant = re.search(
        r"/\* InfoPlist\.strings \*/ = \{\s*isa = PBXVariantGroup;.*?children = \((.*?)\);",
        project,
        flags=re.DOTALL,
    )
    if not variant or re.findall(r"/\* (\w+) \*/", variant.group(1)) != list(LANGUAGES):
        errors.append(f"InfoPlist.strings must be localized in {list(LANGUAGES)}")
    for language in LANGUAGES:
        if f"path = {language}.lproj/InfoPlist.strings;" not in project:
            errors.append(f"project.pbxproj must reference {language}.lproj/InfoPlist.strings")
    regions = re.search(r"knownRegions = \((.*?)\);", project, flags=re.DOTALL)
    known = re.findall(r"\w+", regions.group(1)) if regions else []
    if not set(LANGUAGES) <= set(known):
        errors.append(f"knownRegions must include {list(LANGUAGES)}")

    if 'scripts/check_social_sign_in.sh' not in project:
        errors.append("the sign-in check phase must run scripts/check_social_sign_in.sh")

    for what, defines, extra, expected in SCRIPT_CASES:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DART_DEFINES": defines}
        env.update(extra)
        result = subprocess.run(
            ["sh", str(SCRIPT)], env=env, capture_output=True, text=True
        )
        if result.returncode != expected:
            errors.append(
                f"check_social_sign_in.sh, {what}: exit {result.returncode}, "
                f"expected {expected} ({result.stdout.strip()})"
            )

    for error in errors:
        print(f"ios config: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
