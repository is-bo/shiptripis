import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CITIES, ROUTES, JourneyNetwork, densityForWidth, featuredJourney } from '../../web/assets/globe-network.mjs';
import { CAMERA, ATLAS, vector, front, dot, project, routePoints, sampleRoute } from '../../web/assets/globe-math.mjs';

function seeded(seed) {
  return () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
}

test('all possible journeys obey the controlled country and transport rules', () => {
  assert.equal(Object.keys(CITIES).length, 23);
  assert.equal(Object.values(CITIES).filter(city => city.country === 'DZ').length, 7);
  const allowedCountries = new Set(['DZ', 'FR', 'ES', 'BE', 'NL', 'DE', 'IT', 'PT']);
  for (const city of Object.values(CITIES)) {
    assert.ok(allowedCountries.has(city.country));
    assert.ok(city.lat >= 35 && city.lat <= 53 && city.lon >= -10 && city.lon <= 10);
    assert.ok(city.en && city.fr && city.ar);
  }
  for (const [category, routes] of Object.entries(ROUTES)) {
    const keys = new Set();
    for (const route of routes) {
      const from = CITIES[route.from], to = CITIES[route.to];
      assert.notEqual(from.id, to.id);
      assert.ok(!keys.has(route.key));
      keys.add(route.key);
      if (category === 'flight') {
        assert.equal(route.mode, 'plane');
        assert.notEqual(from.country === 'DZ', to.country === 'DZ');
      } else {
        assert.equal(route.mode, 'car');
        assert.equal(from.country === 'DZ', category === 'algeria');
        assert.equal(to.country === 'DZ', category === 'algeria');
        const km = Math.acos(dot(vector(from.lat, from.lon), vector(to.lat, to.lon))) * 6371;
        assert.ok(km < 650, `${route.key} must stay a reasonable land journey`);
      }
    }
  }
});

test('8/6/5 route densities preserve the cross-Mediterranean majority', () => {
  for (const [width, total, flights] of [[1440, 8, 4], [1024, 6, 3], [390, 5, 3], [320, 5, 3]]) {
    const categories = densityForWidth(width);
    assert.equal(categories.length, total);
    assert.equal(categories.filter(value => value === 'flight').length, flights);
  }
});

test('long simulations stay bounded, staggered, diverse and free of duplicate pairs', () => {
  for (const width of [1440, 1024, 390]) {
    const simulation = new JourneyNetwork(width, seeded(width));
    const previous = new Map(), history = new Map(), seen = new Set();
    assert.equal(new Set(simulation.active.map(journey => journey.progress)).size, simulation.active.length);
    for (let step = 0; step < 14400; step++) {
      const active = simulation.active;
      assert.ok(active.length <= densityForWidth(width).length);
      assert.equal(new Set(active.map(journey => journey.key)).size, active.length);
      simulation.slots.forEach((slot, index) => {
        if (!slot.journey || previous.get(index) === slot.journey.id) return;
        const j = slot.journey;
        assert.notEqual(history.get(index), j.key, 'a slot must not immediately repeat its old pair');
        assert.ok(j.duration >= 20 && j.duration <= 42);
        previous.set(index, j.id);
        history.set(index, j.key);
        seen.add(j.key);
      });
      simulation.advance(.25);
    }
    assert.ok(seen.size > 60, `varied journeys at ${width}px`);
  }
});

test('seeded presentation is reproducible without imposing a fixed runtime loop', () => {
  const a = new JourneyNetwork(1440, seeded(3)), b = new JourneyNetwork(1440, seeded(3));
  assert.deepEqual(a.active, b.active);
  assert.notDeepEqual(a.active, new JourneyNetwork(1440, seeded(4)).active);
  a.advance(9); b.advance(9);
  assert.deepEqual(a.active, b.active);
});

test('featured card always follows an active journey, even between flight spawns', () => {
  const simulation = new JourneyNetwork(390, seeded(18));
  const first = featuredJourney(simulation.active, null);
  assert.equal(first.mode, 'plane');
  assert.equal(featuredJourney(simulation.active, first.id), first);
  const rotated = featuredJourney(simulation.active, first.id, true);
  assert.notEqual(rotated.id, first.id);
  const cars = simulation.active.filter(journey => journey.mode === 'car');
  assert.equal(featuredJourney(cars, first.id), cars[0]);
  assert.equal(featuredJourney([], first.id), undefined);
});

test('sphere projection has actual perspective, occlusion, and full local atlas coverage', () => {
  const centre = project(front, 700);
  assert.ok(Math.abs(centre.x - 350) < .00001 && Math.abs(centre.y - 350) < .00001);
  assert.equal(centre.visible, true);
  assert.equal(project(front.map(value => -value), 700).visible, false);
  for (let lat = -90; lat <= 90; lat += 2) {
    for (let lon = -180; lon <= 180; lon += 2) {
      const point = project(vector(lat, lon), 700);
      if (point.visible) {
        assert.ok(lat >= ATLAS.south && lat <= ATLAS.north && lon >= ATLAS.west && lon <= ATLAS.east);
        assert.ok(Math.hypot(point.x - 350, point.y - 350) <= 700 * CAMERA.radius + .001);
      }
    }
  }
  for (const city of Object.values(CITIES)) assert.equal(project(vector(city.lat, city.lon), 700).visible, true, city.id);
  for (const point of [[28, 3], [40, -4], [47, 2], [33, -6], [34, 9]]) {
    assert.equal(project(vector(...point), 700).visible, true, 'Algeria and geographic context must be visible');
  }
});

test('vehicles follow the projected endpoints and reverse their direction along the same route', () => {
  for (const routes of Object.values(ROUTES)) {
    for (const route of routes) {
      const journey = { ...route, bend: .005 };
      const points = routePoints(journey, CITIES, 700);
      for (const p of points) assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
      const start = sampleRoute(points, 0), end = sampleRoute(points, 1);
      const expectedStart = project(vector(CITIES[route.from].lat, CITIES[route.from].lon), 700);
      const expectedEnd = project(vector(CITIES[route.to].lat, CITIES[route.to].lon), 700);
      assert.ok(Math.hypot(start.x - expectedStart.x, start.y - expectedStart.y) < .001);
      assert.ok(Math.hypot(end.x - expectedEnd.x, end.y - expectedEnd.y) < .001);
      const reverse = routePoints({ ...journey, from: route.to, to: route.from, via: [...route.via].reverse(), bend: -.005 }, CITIES, 700);
      const a = sampleRoute(points, .43), b = sampleRoute(reverse, .57);
      assert.ok(Math.hypot(a.x - b.x, a.y - b.y) < .001);
      assert.ok(Math.abs(Math.abs(a.angle - b.angle) - Math.PI) < .001);
    }
  }
});

test('every localized landing ships the globe, two existing CTA anchors and a static fallback', () => {
  for (const path of ['index.html', 'en/index.html', 'fr/index.html', 'ar/index.html']) {
    const html = readFileSync(new URL(`../../web/${path}`, import.meta.url), 'utf8');
    assert.match(html, /type="module" src="\/assets\/hero-globe.mjs"/);
    assert.match(html, /class="globe-fallback" src="\/assets\/globe\/fallback.webp"/);
    assert.match(html, /class="button button-sun" href="#sender"/);
    assert.match(html, /class="button button-ghost" href="#traveler"/);
    assert.match(html, /id="sender"/);
    assert.match(html, /id="traveler"/);
    assert.doesNotMatch(html, /Next live journey|Departure today|moving-person/);
  }
});
