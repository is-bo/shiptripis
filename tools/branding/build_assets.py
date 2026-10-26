"""Copy supplied Wassla vectors and rasterize platform sizes without redrawing.

Run from any directory with CairoSVG and Pillow installed. The untouched source
package lives in branding/wassla; only proportional sizing/padding is applied.
"""

from io import BytesIO
from pathlib import Path
import json
import shutil

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "branding/wassla"
WEB = ROOT / "web/assets/branding"
ADMIN = ROOT / "backend/monolith/apps/core/static/shiptrip/branding"
MOBILE = ROOT / "mobile/assets/branding"


def raster(source, target, width, *, background=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(
        url=str(source), write_to=str(target), output_width=width,
        background_color=background,
    )


def build():
    for folder in (WEB, ADMIN, MOBILE):
        folder.mkdir(parents=True, exist_ok=True)
    for variant in ("navy", "ivory"):
        name = f"wassla-primary-{variant}"
        source = SOURCE / f"01_logos/{name}.svg"
        for folder in (WEB, ADMIN):
            shutil.copyfile(source, folder / f"{name}.svg")
        # Four physical pixels per logical pixel on the largest mobile mark.
        raster(source, MOBILE / f"{name}.png", 960)
        name = f"wassla-symbol-{variant}"
        source = SOURCE / f"02_app_icon/{name}.svg"
        raster(source, MOBILE / f"{name}.png", 192)
    # An opaque supplied banner remains legible when email clients invert paper.
    raster(SOURCE / "01_logos/wassla-on-ivory.svg", WEB / "wassla-email.png", 720)
    favicon = SOURCE / "02_app_icon/favicon.svg"
    shutil.copyfile(favicon, ROOT / "web/assets/favicon.svg")
    shutil.copyfile(favicon, ADMIN / "favicon.svg")
    icon_source = SOURCE / "02_app_icon/wassla-app-icon-dark.svg"
    icon = Image.open(BytesIO(cairosvg.svg2png(url=str(icon_source), output_width=1024)))
    # iOS store icons must be opaque; retain the supplied navy beneath corners.
    opaque = Image.new("RGBA", icon.size, "#042D49")
    opaque.alpha_composite(icon.convert("RGBA"))
    icon = opaque.convert("RGB")
    icon.save(ROOT / "web/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    res = ROOT / "mobile/android/app/src/main/res"
    for density, size in {"mdpi":48,"hdpi":72,"xhdpi":96,"xxhdpi":144,"xxxhdpi":192}.items():
        icon.resize((size, size), Image.Resampling.LANCZOS).save(res / f"mipmap-{density}/ic_launcher.png")
    icons = ROOT / "mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset"
    for entry in json.loads((icons / "Contents.json").read_text())["images"]:
        size = round(float(entry["size"].split("x")[0]) * float(entry["scale"].rstrip("x")))
        icon.resize((size, size), Image.Resampling.LANCZOS).save(icons / entry["filename"])
    launch = ROOT / "mobile/ios/Runner/Assets.xcassets/LaunchImage.imageset"
    for scale in (1, 2, 3):
        suffix = "" if scale == 1 else f"@{scale}x"
        for variant in ("navy", "ivory"):
            filename = f"LaunchImage{suffix}.png" if variant == "navy" else f"LaunchImage-dark{suffix}.png"
            raster(SOURCE / f"01_logos/wassla-primary-{variant}.svg", launch / filename, 240 * scale)
    # Native Android launch bitmap at a fixed logical size on all densities.
    for variant, folder in (("navy", "drawable-nodpi"), ("ivory", "drawable-night-nodpi")):
        raster(SOURCE / f"01_logos/wassla-primary-{variant}.svg", res / folder / "wassla_launch.png", 960)
    # Android 12 masks the launch icon; pad the supplied transparent symbol
    # inside its safe central region rather than letting the OS crop the W.
    symbol = Image.open(BytesIO(cairosvg.svg2png(
        url=str(SOURCE / "02_app_icon/wassla-symbol-ivory.svg"), output_width=384,
    )))
    padded = Image.new("RGBA", (768, 768))
    padded.alpha_composite(symbol, ((768-symbol.width)//2, (768-symbol.height)//2))
    padded.save(res / "drawable-nodpi/wassla_splash_icon.png")


if __name__ == "__main__":
    build()
