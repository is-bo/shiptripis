#!/usr/bin/env python3
"""Fail CI when the iOS sign-in configuration is unreadable, carries a value,
or could let the app's defines and its native settings disagree.

`plutil -lint` needs macOS; Python's `plistlib` parses the same format, so a
broken `Info.plist` or entitlements file is caught here instead of in Xcode.

What is checked:

* `Runner/Info.plist` and `Runner/Runner.entitlements` parse as plists;
* Google's URL scheme is made from `GOOGLE_IOS_CLIENT_PREFIX`, and the plist
  lists no client id of its own (the app passes the define at run time);
* the entitlements ask for Sign in with Apple, and every Runner build
  configuration signs with `$(APPLE_SIGN_IN_ENTITLEMENTS)`, so the
  capability is needed only once Ismail sets it;
* `Flutter/SocialSignIn.xcconfig` defines both settings and leaves them empty
  in Git, and `Debug.xcconfig` and `Release.xcconfig` include it;
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


def _defines(**values: str) -> str:
    return ",".join(
        base64.b64encode(f"{name}={value}".encode()).decode()
        for name, value in values.items()
    )


# (what, DART_DEFINES, build settings, expected exit status)
SCRIPT_CASES = [
    ("nothing configured", "", {}, 0),
    ("other defines only", _defines(API_BASE_URL="https://a.example"), {}, 0),
    (
        "Google define matches the prefix",
        _defines(
            API_BASE_URL="https://a.example",
            GOOGLE_IOS_CLIENT_ID="123-abc.apps.googleusercontent.com",
        ),
        {"GOOGLE_IOS_CLIENT_PREFIX": "123-abc"},
        0,
    ),
    (
        "Google define without a prefix",
        _defines(GOOGLE_IOS_CLIENT_ID="123-abc.apps.googleusercontent.com"),
        {},
        1,
    ),
    (
        "Google define for another client",
        _defines(GOOGLE_IOS_CLIENT_ID="999-zzz.apps.googleusercontent.com"),
        {"GOOGLE_IOS_CLIENT_PREFIX": "123-abc"},
        1,
    ),
    ("prefix without the define (warning)", "", {"GOOGLE_IOS_CLIENT_PREFIX": "123-abc"}, 0),
    ("Apple on without entitlements", _defines(APPLE_SIGN_IN_ENABLED="true"), {}, 1),
    (
        "Apple on with entitlements",
        _defines(APPLE_SIGN_IN_ENABLED="true"),
        {"APPLE_SIGN_IN_ENTITLEMENTS": "Runner/Runner.entitlements"},
        0,
    ),
    ("Apple off without entitlements", _defines(APPLE_SIGN_IN_ENABLED="false"), {}, 0),
]


def main() -> int:
    errors: list[str] = []

    def load(path: Path) -> dict:
        try:
            with path.open("rb") as handle:
                value = plistlib.load(handle)
        except Exception as exc:  # noqa: BLE001 - any parse failure is a failure
            errors.append(f"{path.relative_to(IOS)} does not parse: {exc}")
            return {}
        if not isinstance(value, dict):
            errors.append(f"{path.relative_to(IOS)} is not a dictionary")
            return {}
        return value

    info = load(IOS / "Runner" / "Info.plist")
    if info:
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

    entitlements = load(IOS / "Runner" / "Runner.entitlements")
    if entitlements and entitlements.get("com.apple.developer.applesignin") != [
        "Default"
    ]:
        errors.append("Runner.entitlements must ask for Sign in with Apple")

    xcconfig = (IOS / "Flutter" / "SocialSignIn.xcconfig").read_text()
    settings = dict(
        re.findall(r"^\s*([A-Z_]+)\s*=(.*)$", xcconfig, flags=re.MULTILINE)
    )
    for name in ("GOOGLE_IOS_CLIENT_PREFIX", "APPLE_SIGN_IN_ENTITLEMENTS"):
        if name not in settings:
            errors.append(f"SocialSignIn.xcconfig must define {name}")
        elif settings[name].strip():
            errors.append(f"SocialSignIn.xcconfig must leave {name} empty in Git")

    for config in ("Debug", "Release"):
        text = (IOS / "Flutter" / f"{config}.xcconfig").read_text()
        if '#include "SocialSignIn.xcconfig"' not in text:
            errors.append(f"{config}.xcconfig must include SocialSignIn.xcconfig")

    project = (IOS / "Runner.xcodeproj" / "project.pbxproj").read_text()
    runner_configs = project.count("INFOPLIST_FILE = Runner/Info.plist;")
    entitled = project.count(
        'CODE_SIGN_ENTITLEMENTS = "$(APPLE_SIGN_IN_ENTITLEMENTS)";'
    )
    if runner_configs == 0 or entitled != runner_configs:
        errors.append(
            "every Runner build configuration needs CODE_SIGN_ENTITLEMENTS = "
            f"$(APPLE_SIGN_IN_ENTITLEMENTS) ({entitled} of {runner_configs})"
        )
    if "Runner/Runner.entitlements" in project:
        errors.append("project.pbxproj must not name the entitlements file itself")
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
