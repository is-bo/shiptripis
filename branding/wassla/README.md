# WASSLA | Brand Identity Package

This package is a genuine SVG vector tracing of the three provided reference images.
All letterforms, Arabic lettering, W mark, and yellow cut-ins are outlined SVG paths; **no bitmap layers, external fonts, or image URLs** are required.

## Recommended assets

- `01_logos/wassla-primary-navy.svg`: logo + Arabic on transparent (for a light background).
- `01_logos/wassla-primary-ivory.svg`: logo + Arabic on transparent (for a dark background).
- `01_logos/wassla-on-navy.svg`: branded dark banner, complete with background.
- `01_logos/wassla-on-ivory.svg`: branded light banner, complete with background.
- `02_app_icon/wassla-app-icon-dark.svg`: navy square icon with dimensional white W.
- `02_app_icon/wassla-app-icon-light.svg`: inverted ivory square icon.
- `02_app_icon/wassla-symbol-*.svg`: transparent cropped W for other placements.
- `02_app_icon/favicon.svg`: website favicon.
- `03_wordmarks/`: variants without Arabic plus monochrome alternatives.
- `05_png_exports/`: rasterized convenience exports (not the design source).

## Color palette

| Token | HEX | Use |
| --- | --- | --- |
| Navy | `#042D49` | Primary brand ink, backgrounds |
| Midnight Navy | `#021E33` | Dark gradients |
| Ivory | `#F8F6F1` | Light wordmark or background |
| Yellow | `#FFCD28` | Path/notch/sweep accent |
| White | `#FFFFFF` | App icon W |

## Use notes

- Keep the yellow accent unchanged when reversing dark and light palettes.
- Use the light (`...navy.svg`) lettering on ivory or white; use the ivory lettering on navy.
- Transparent primary logos have an SVG viewBox with padding. Do not add a second background to them unless intended.
- Each SVG may be opened in Figma, Illustrator, or Inkscape to edit outlines and color fills.
- The app icon's depth is composed of vector shadow layers (editable SVG paths), **not** an embedded PNG.
- Tracing faithfully preserves the supplied stylized Latin wordmark and Arabic subtitle. Minor contour simplification is normal when recreating vector artwork from a raster reference.
