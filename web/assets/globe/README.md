# ShipTrip hero geography

Made with [Natural Earth](https://www.naturalearthdata.com/). The bundled land
and country borders derive from **Natural Earth 1:50m Admin 0 Countries,
release 5.1.2**. Natural Earth describes its raster and vector data as public
domain in its [terms of use](https://www.naturalearthdata.com/about/terms-of-use/).

Pinned source:
[ne_50m_admin_0_countries.geojson](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson)

Source SHA-256:
`3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb`

## Bundled assets

- `atlas.png`: 3072 × 2048 local regional geographic texture, 121,809 bytes.
  Extent: 55°W–60°E, 0°–78°N, covering the fixed camera's entire visible cap.
  Parchment ocean, three restrained land shades, fine country borders, and
  an emerald-derived fill (`#8caa95`) for Algeria. No satellite imagery.
- `fallback.webp`: 960 × 960 transparent, locally ray-rendered perspective
  sphere, 104,902 bytes, with representative static routes. Used before
  enhancement, with JavaScript disabled, or after WebGL/context failure.
  Some image previewers expose undefined RGB in transparent WebP pixels;
  browser compositing and decoded alpha were verified independently.

The source GeoJSON is used only during asset authoring; it is not requested by
the browser. No map tile provider, runtime API, key, third-party script, or CDN
is involved. The camera is fixed, so a regional texture provides clearer
coastlines for fewer pixels than a world-sized high-resolution texture.

## Reproduction

Download the exact pinned source above. From the repository root, with Python
and Pillow available:

```sh
python tools/web/build_globe.py path/to/ne_50m_admin_0_countries.geojson
```

The script verifies the source digest, reads the camera and atlas bounds from
`web/assets/globe-math.mjs`, and writes both assets. Pillow is an asset-authoring
tool only; it is not required to serve, build, or test the public website.
No dependency was added to the site or root package manifest.

## Illustrative cities

`../globe-network.mjs` contains 23 explicit WGS84 city-centre coordinates and
EN/FR/AR labels. They are approximate centres for an ambient illustration,
not airports, meeting points, driving directions, schedules, live inventory,
or the authoritative ShipTrip matching catalogue.

| Algeria | Western Europe |
| --- | --- |
| Algiers, Oran, Constantine, Béjaïa, Jijel, Annaba, Sétif | Paris, Marseille, Lyon, Lille, Toulouse, Nice; Barcelona, Madrid, Valencia; Brussels; Amsterdam; Frankfurt, Cologne; Milan, Turin; Lisbon |

Domestic Algerian and European routes use reviewed land pairs, with inland
waypoints where needed. Flights cross between Algeria and the controlled
European destination pool. No Morocco or Tunisia city exists in the route
dataset; both countries remain visible map context. City placement is separate
from Natural Earth's country polygons and does not alter backend geography.

The sphere uses radius 1, camera distance 1.18, and look direction 38°N, 3°E.
Longitude/latitude are sampled at the actual ray/sphere intersection. Lighting
and the perspective horizon reveal curvature; routes share that projection
and are occluded by the sphere. Flight curves rise up to 0.008 radii above the
surface; roads follow the surface via their reviewed waypoints.
