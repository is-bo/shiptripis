#!/usr/bin/env python3
"""Fail CI when the iOS sign-in configuration is unreadable or carries a value.

`plutil -lint` needs macOS; Python's `plistlib` parses the same format, so a
broken `Info.plist` or entitlements file is caught here instead of in Xcode.

What is checked:

* `Runner/Info.plist` and `Runner/Runner.entitlements` parse as plists;
* the plist reads Google's client id and URL scheme from build settings,
  never a literal id;
* the entitlements ask for Sign in with Apple;
* `Flutter/SocialSignIn.xcconfig` defines both Google settings and leaves
  them empty (the values are Ismail's, set outside Git), and `Debug.xcconfig`
  and `Release.xcconfig` include it;
* every Runner build configuration names the entitlements file.
"""

from __future__ import annotations

import plistlib
import re
import sys
from pathlib import Path


IOS = Path(__file__).resolve().parents[1] / "mobile" / "ios"


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
        if info.get("GIDClientID") != "$(GOOGLE_IOS_CLIENT_ID)":
            errors.append("Info.plist GIDClientID must be $(GOOGLE_IOS_CLIENT_ID)")
        schemes = [
            scheme
            for url_type in info.get("CFBundleURLTypes", [])
            for scheme in url_type.get("CFBundleURLSchemes", [])
        ]
        if "$(GOOGLE_REVERSED_CLIENT_ID)" not in schemes:
            errors.append(
                "Info.plist needs a URL type for $(GOOGLE_REVERSED_CLIENT_ID)"
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
    for name in ("GOOGLE_IOS_CLIENT_ID", "GOOGLE_REVERSED_CLIENT_ID"):
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
        "CODE_SIGN_ENTITLEMENTS = Runner/Runner.entitlements;"
    )
    if runner_configs == 0 or entitled != runner_configs:
        errors.append(
            "every Runner build configuration needs CODE_SIGN_ENTITLEMENTS "
            f"({entitled} of {runner_configs})"
        )
    if project.count("{") != project.count("}") or project.count("(") != project.count(
        ")"
    ):
        errors.append("project.pbxproj braces or parentheses are unbalanced")

    for error in errors:
        print(f"ios config: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
