#!/usr/bin/env python3
"""Subset the bundled ShipTrip faces into web-sized woff2 files.

The public site must set the same type as the app, and it must do so without a
runtime request to a third party: the site ships under `default-src 'self'`, so
a hosted font service is not merely undesirable, it is blocked. The audience is
also on the EU <-> Algeria corridor, where a font that arrives late is a font
that arrives after the reader has gone.

Each face is instanced first -- the non-weight axes pinned to exactly the values
`mobile/lib/design/typography.dart` asks for -- and then subset to the scripts
the pages actually set. Regenerate with:

    python tools/web/build_fonts.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "mobile" / "assets" / "fonts"
OUT = ROOT / "web" / "assets" / "fonts"
STAGE = ROOT / "build" / "fontwork"

# The operations console sets the same display and UI faces, but it is served
# by Django/WhiteNoise rather than by Caddy's `/assets` route, so it cannot
# reference the site's copy: local preview and the review dumps run without
# Caddy and would silently fall back to Georgia. The two faces the admin
# actually sets are mirrored into its own static directory instead, and this
# script is the single place that regenerates both.
ADMIN_OUT = ROOT / "backend" / "monolith" / "apps" / "core" / "static" / "shiptrip" / "fonts"
ADMIN_FACES = ("fraunces", "dmsans")

# Latin plus the punctuation the three catalogues actually use: the arrows in
# "EU <-> Algeria", the euro sign, the middot separators and the box-drawing
# rule under the fee total.
LATIN = (
    "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
    "U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2190-2199,"
    "U+2212,U+2215,U+25A0,U+25CF,U+2500-2503,U+FEFF,U+FFFD"
)
# Arabic including the presentation forms and the Arabic-Indic digits.
ARABIC = (
    "U+0600-06FF,U+0750-077F,U+0870-088E,U+0890-0891,U+0898-08E1,U+08E3-08FF,"
    "U+200C-200E,U+2010-2011,U+204F,U+2E41,U+FB50-FDFF,U+FE70-FEFF"
)
# The mono face exists on this site for one thing: the six-character handover
# code tile. Digits, capitals and a hyphen are the whole requirement.
MONO = "U+0020,U+002D,U+0030-0039,U+0041-005A,U+00B7,U+2013"

JOBS = (
    # source, output stem, pinned axes, unicode range
    ("Fraunces-Variable.ttf", "fraunces", ("SOFT=0", "WONK=1"), LATIN),
    ("DMSans-Variable.ttf", "dmsans", ("opsz=14",), LATIN),
    ("JetBrainsMono-Variable.ttf", "jetbrainsmono", (), MONO),
    ("NotoSansArabic-Variable.ttf", "notosansarabic", ("wdth=100",), ARABIC),
)

FEATURES = (
    "kern,liga,calt,rlig,mark,mkmk,ccmp,locl,"
    "init,medi,fina,isol,tnum,onum,frac,numr,dnom"
)


def run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit(f"failed: {' '.join(args)}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, stem, pins, unicodes in JOBS:
        staged = SRC / name
        if pins:
            staged = STAGE / f"{stem}-instanced.ttf"
            run([sys.executable, "-m", "fontTools.varLib.instancer",
                 str(SRC / name), *pins, "-o", str(staged)])
        target = OUT / f"{stem}.woff2"
        run([
            sys.executable, "-m", "fontTools.subset", str(staged),
            f"--unicodes={unicodes}",
            f"--layout-features={FEATURES}",
            "--flavor=woff2",
            "--name-IDs=0,1,2,3,4,5,6,7,13,14",
            "--drop-tables+=DSIG",
            f"--output-file={target}",
        ])
        size = target.stat().st_size
        total += size
        print(f"{target.relative_to(ROOT)}  {size / 1024:.1f} KiB")
        if stem in ADMIN_FACES:
            ADMIN_OUT.mkdir(parents=True, exist_ok=True)
            mirrored = ADMIN_OUT / target.name
            mirrored.write_bytes(target.read_bytes())
            print(f"{mirrored.relative_to(ROOT)}  mirrored for the admin console")
    print(f"total {total / 1024:.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
