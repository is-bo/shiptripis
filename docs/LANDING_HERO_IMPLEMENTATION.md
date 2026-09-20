# ShipTrip landing hero implementation — 20 September 2026

Implemented in the existing static public website. No deployment, backend
runtime, authenticated flow, database migration, payment setting, or LIVE
activation is part of this change. Pre-existing J9.4 release-document edits
are preserved.

## Implementation record

1. **Files changed.** `web/index.html`, `web/en/index.html`,
   `web/fr/index.html`, `web/ar/index.html`; new `web/assets/hero.css`,
   `hero-globe.mjs`, `globe-renderer.mjs`, `globe-math.mjs`,
   `globe-network.mjs`; `web/assets/globe/atlas.png`, `fallback.webp`,
   `README.md`; `tools/web/build_globe.py`, `globe.test.mjs`,
   `check_hero_browser.js`; `tools/check_static_web.py`;
   `.github/workflows/ci.yml`; `web/README.md`, `web/DESIGN.md`,
   `web/.impeccable/design.json`; this record and the scoped addition to
   `docs/IMPLEMENTATION_STATUS.md`.
2. **Components/styles reused.** Existing wordmark/seal, header/navigation,
   yellow and ghost buttons, focus states, local font loading, paper grain,
   route-node motif, section anchors and downstream sections. The changes to
   landing HTML are limited to hero markup and its two asset references.
3. **Typography.** Existing Fraunces, DM Sans, and Noto Sans Arabic. Arabic
   preserves real RTL layout without reversing geographic coordinates.
4. **Colors/tokens.** Existing parchment `--canvas`, navy `--text-primary`,
   emerald `--brand`/`--brand-strong`, yellow `--accent`, clay
   `--attention-print`, green `--mode-drive`, paper surfaces, border colors,
   and `--radius`. Map colors are natural, muted derivatives of this palette.
5. **Previous route logic.** The checked-in web hero was a postcard with
   dashed flight lines, animated dash offsets, endpoint nodes, a halo and a
   static plane. There was no existing web globe or moving-person component.
   Those visual techniques are adapted to projected paths. The Flutter
   `RouteTrace` precedent in `mobile/lib/design/identity.dart` informed the
   separate static/dynamic layers and tangent-oriented vehicle approach;
   no Dart code or application flow changed.
6. **Globe implementation.** Native WebGL fragment shader performs actual
   perspective ray/sphere intersections and samples geographic coordinates.
   A canvas overlay projects routes and vehicles through the same camera.
   This is not a flat map clipped to a circle or a wireframe sphere.
7. **Dependencies.** No new runtime library, engine, framework, npm package,
   or site build step. Existing Python/Pillow authors local assets; native
   Node tests need no package install. CI explicitly sets up Node 22.
8. **Geographic assets.** Natural Earth 1:50m country polygons, pinned
   release 5.1.2 and SHA-256, rendered to a local regional PNG atlas and
   transparent WebP fallback. See `web/assets/globe/README.md` for source,
   public-domain terms, camera and reproducible generation instructions.
9. **Algeria city pool.** Algiers, Oran, Constantine, Béjaïa, Jijel, Annaba,
   Sétif, each with explicit WGS84 coordinates and localized labels.
10. **Europe city pool.** Paris, Marseille, Lyon, Lille, Toulouse, Nice;
    Barcelona, Madrid, Valencia; Brussels; Amsterdam; Frankfurt, Cologne;
    Milan, Turin; Lisbon. Not every European city needs an international
    connection: several participate only in the reviewed land pairs.
11. **Journey rules.** Algeria internal = car; Western Europe internal =
    car; Algeria ↔ Europe = plane. Eight reviewed Algerian and fourteen
    European road pairs include inland waypoints where useful. All flight
    pairs cross between Algeria and a controlled European destination.
    Morocco/Tunisia are geographic context and cannot become endpoints.
12. **Random generation.** Eight desktop slots, six tablet slots, five
    mobile slots. Each has randomized direction, route, initial progress,
    duration, and replacement gap. Flights take 20–35 seconds, road journeys
    24–42 seconds, with independent 0.8–4.6-second respawn delays. Undirected
    city pairs cannot duplicate concurrently; category history and per-slot
    previous-pair exclusion prevent immediate repeats. Prefer endpoints
    with fewer current routes. Finite route pools can recur later; there is
    no repeating pre-scripted sequence.
13. **Vehicles.** One authored plane silhouette and one small top-down car.
    Both rotate along the sampled tangent. Flight paths rise slightly above
    the sphere; road paths follow the surface. No people, ferry, van, truck,
    train, emoji, icon-font, or random vehicle variants.
14. **Algeria emphasis.** Full-country muted emerald fill, stronger emerald
    country label, a central lower position, and most international routes
    touching Algerian cities. Neighboring countries remain quiet.
15. **Camera/framing.** Perspective camera looks toward 38°N, 3°E from
    1.18 sphere radii, tightly showing Western Europe, Mediterranean and
    Algeria/Maghreb. The spherical horizon remains visible. Fixed framing
    cannot drift into the Atlantic or rotate away from the corridor.
16. **Reduced motion.** The initial representative route/vehicle network
    remains still; no vehicle travel, dash motion, spawn loop, or automatic
    card cycle. The unnecessary pause control is hidden. Normal mode has
    accessible pause/resume and does not announce ambient updates.
17. **Mobile.** Copy and CTAs precede a full-width meaningful globe. Route
    count and icon size reduce; pixel ratio is capped at 1.5. Arabic mirrors
    content and arrow direction, not the Earth. A short landscape layout
    retains two columns. No measured horizontal page overflow.
18. **Performance/lifecycle.** Sphere draws only on setup/resize; geographic
    data is not reprojected every frame. Cached route geometry and a separate
    30fps-capped canvas handle motion, without a UI framework render loop.
    Animation suspends offscreen, in hidden tabs, and when paused. Timers are
    not used by the runtime; RAF, observers, listeners, GL buffers, shaders,
    and texture are released on disposal. BFCache restore remounts safely;
    DOM removal while paused also disposes. WebGL loss reveals the fallback
    and restores its matching Algiers → Paris card.
19. **Rendered verification.** Chromium/agent-browser under the production
    CSP on a local static server. Screenshots inspected: EN 1440×900,
    1024×768, 390×844, 320×640, 844×390; FR 390×844; AR 1440×900 and 390×844.
    Reduced motion and forced WebGL loss were also exercised and captured.
    Artifacts are local in `build/hero-review/`. Independent finish review:
    **ship**. Its sole fallback-transparency concern was withdrawn after
    actual browser captures proved clean alpha compositing.
20. **Checks.** Eight Node tests pass, including three one-hour seeded
    simulation runs, allowed geography/modes, density/duplicates/cooldowns,
    projection/occlusion/atlas coverage, reverse tangents, featured-route
    continuity and localized integration. Existing deployment/public routing
    suite: 40 passed. Browser harness: 54 assertions in animated mode and
    51 in reduced mode. Static assets/module links/CSP/two Caddy configurations
    check passes; JS syntax, changed Python Ruff, diff whitespace and design
    detector pass. Browser console/errors empty on the normal localized
    capture round. Axe hero audit: zero automatic violations; decorative
    text over the canvas needs manual contrast assessment and was inspected.
21. **Remaining limits.** Journeys are clearly illustrative, never claimed
    to be actual departures. Natural Earth geometry and authored road
    waypoints are not navigation-grade directions. The JavaScript/WebGL
    fallback has static routes and omits dynamic labels/vehicles. At 320×640
    and short landscape height, a short scroll reveals the rest of the
    globe/card; CTAs are visible without scrolling on portrait phones.
    Verification used emulated Chromium viewports, not physical Safari/iOS
    or Android hardware. No publication or deployment was performed.

## Review disposition

| Finding | Evidence | Result |
| --- | --- | --- |
| Fallback alpha appeared smeared in raw image preview | Forced WebGL-loss desktop and phone captures; decoded alpha has the correct sphere bounds | Withdrawn; browser rendering correct |
| Independent finish review | Main desktop/tablet/mobile/FR/AR screenshots and source | **ship** |

The documentation subagent was unavailable during closeout; the primary
agent completed the public-web design record directly. Root Flutter design
documents were not changed.

## Publication (2026-09-20)

The approved implementation commit `91753678577381daa58748cab0703583910d9e45`
was merged to `main` through PR #8, merge SHA
`5b7e3f0b5dd38c71c524165af81d390614238e2b`. Its separate PR CI passed all
six jobs. It was published unchanged in the TEST Railway release built from
`3bc2a98e69d18f9a321e566ca21203765fdf82c7` (deployment
`16b65066-aea6-412e-b93a-3d3a677371fd`, SUCCESS). `/`, `/en/`, `/fr/`,
`/ar/`, and `/assets/hero-globe.mjs` each returned HTTP 200 with the new hero.
This release kept Stripe and Chargily in TEST and DZD execution disabled.
