"""Build the local Natural Earth atlas and a real perspective-sphere fallback.

Run with the pinned 5.1.2 GeoJSON described in web/assets/globe/README.md.
Only the asset authoring step needs Pillow; the site has no dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "web/assets/globe"
SOURCE_SHA256 = "3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb"


def build(source: Path) -> None:
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError(f"Unexpected Natural Earth source SHA-256: {digest}")
    data = json.loads(raw)
    camera_module = (ROOT / "web/assets/globe-math.mjs").read_text(encoding="utf-8")
    bounds = re.search(r"ATLAS = Object.freeze\(\{ west: (-?[\d.]+), east: (-?[\d.]+), south: (-?[\d.]+), north: (-?[\d.]+)", camera_module)
    if bounds is None:
        raise ValueError("Unable to read the runtime atlas bounds")
    west, east_bound, south, north_bound = map(float, bounds.groups())
    width, height = 3072, 2048
    atlas = Image.new("RGB", (width, height), "#f4efe6")
    pen = ImageDraw.Draw(atlas)
    land = ("#e3d8bf", "#e6dcc7", "#dfd3b9")
    for index, country in enumerate(data["features"]):
        geometry = country["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        colour = "#8caa95" if country["properties"]["ADM0_A3"] == "DZA" else land[index % 3]
        for polygon in polygons:
            for ring_index, ring in enumerate(polygon):
                points = [((lon - west) / (east_bound - west) * width,
                           (north_bound - lat) / (north_bound - south) * height) for lon, lat in ring]
                pen.polygon(points, fill=colour if ring_index == 0 else "#f4efe6")
                pen.line(points, fill="#bcb6a2", width=1)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    atlas.save(OUTPUT / "atlas.png", optimize=True)

    # Keep the fallback camera in exact agreement with the runtime module.
    values = re.search(r"CAMERA = Object.freeze\(\{ lat: ([\d.]+), lon: ([\d.]+), distance: ([\d.]+), radius: ([\d.]+)", camera_module)
    if values is None:
        raise ValueError("Unable to read the runtime globe camera")
    latitude, longitude, distance, radius = map(float, values.groups())
    phi, lam = map(math.radians, (latitude, longitude))
    front = (math.cos(phi) * math.sin(lam), math.sin(phi), math.cos(phi) * math.cos(lam))
    east = (math.cos(lam), 0, -math.sin(lam))
    north = (-math.sin(phi) * math.sin(lam), math.cos(phi), -math.sin(phi) * math.cos(lam))
    light = (-.5, .7, 1)
    norm = math.sqrt(sum(v * v for v in light))
    light = tuple(v / norm for v in light)
    size = 960
    fallback = Image.new("RGBA", (size, size))
    pixels, texture = fallback.load(), atlas.load()
    focal = math.sqrt(distance * distance - 1)
    for y in range(size):
        sy = (.5 - (y + .5) / size) / radius
        for x in range(size):
            sx = ((x + .5) / size - .5) / radius
            ray_norm = math.sqrt(sx * sx + sy * sy + focal * focal)
            ray = (sx / ray_norm, sy / ray_norm, -focal / ray_norm)
            b = distance * ray[2]
            disc = b * b - (distance * distance - 1)
            if disc < 0:
                continue
            t = -b - math.sqrt(disc)
            normal = (ray[0] * t, ray[1] * t, distance + ray[2] * t)
            world = tuple(east[i] * normal[0] + north[i] * normal[1] + front[i] * normal[2] for i in range(3))
            u = (math.degrees(math.atan2(world[0], world[2])) - west) / (east_bound - west)
            v = (north_bound - math.degrees(math.asin(max(-1, min(1, world[1]))))) / (north_bound - south)
            facing = max(0, -sum(a * b for a, b in zip(normal, ray)))
            shade = .86 + .16 * sum(a * b for a, b in zip(normal, light)) - .22 * (1 - facing) ** 1.6
            rgb = texture[max(0, min(width - 1, int(u * width))), max(0, min(height - 1, int(v * height)))]
            pixels[x, y] = (*[max(0, min(255, round(c * shade))) for c in rgb], min(255, round(facing / .025 * 255)))

    # Representative static air/land network for JS-off and WebGL loss. Both
    # endpoints and intermediate surface points use the same 3D projection.
    def project(lat: float, lon: float) -> tuple[float, float]:
        phi, lam = math.radians(lat), math.radians(lon)
        point = (math.cos(phi) * math.sin(lam), math.sin(phi), math.cos(phi) * math.cos(lam))
        z = sum(a * b for a, b in zip(point, front))
        scale = focal / (distance - z) * size * radius
        return (size / 2 + sum(a * b for a, b in zip(point, east)) * scale,
                size / 2 - sum(a * b for a, b in zip(point, north)) * scale)

    pen = ImageDraw.Draw(fallback)
    routes = [((36.7538, 3.0588), (48.8566, 2.3522), "#0e5a4f"),
              ((35.6971, -.6308), (41.3874, 2.1686), "#0e5a4f"),
              ((36.365, 6.6147), (45.764, 4.8357), "#0e5a4f"),
              ((36.7538, 3.0588), (35.6971, -.6308), "#9b4318"),
              ((48.8566, 2.3522), (50.8503, 4.3517), "#1c7a6b")]
    for start, end, colour in routes:
        points = [project(start[0] + (end[0] - start[0]) * i / 80, start[1] + (end[1] - start[1]) * i / 80) for i in range(81)]
        for i in range(0, 78, 4):
            pen.line(points[i:i + 3], fill=colour, width=2)
        for px, py in (points[0], points[-1]):
            pen.ellipse((px - 4, py - 4, px + 4, py + 4), fill="#fffcf5", outline=colour, width=2)
    fallback.save(OUTPUT / "fallback.webp", lossless=True, method=6)
    print(f"Built atlas and perspective fallback from Natural Earth {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    build(parser.parse_args().source)

