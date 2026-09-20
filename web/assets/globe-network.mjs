// Illustrative city-centre coordinates, never product matching or live inventory.
// Coordinates are decimal WGS84 (latitude, longitude); see globe/README.md.
export const CITIES = Object.freeze(Object.fromEntries([
  ['algiers', 'DZ', 36.7538, 3.0588, 'Algiers', 'Alger', 'الجزائر'],
  ['oran', 'DZ', 35.6971, -0.6308, 'Oran', 'Oran', 'وهران'],
  ['constantine', 'DZ', 36.365, 6.6147, 'Constantine', 'Constantine', 'قسنطينة'],
  ['bejaia', 'DZ', 36.7559, 5.0843, 'Béjaïa', 'Béjaïa', 'بجاية'],
  ['jijel', 'DZ', 36.82, 5.7667, 'Jijel', 'Jijel', 'جيجل'],
  ['annaba', 'DZ', 36.9, 7.7667, 'Annaba', 'Annaba', 'عنابة'],
  ['setif', 'DZ', 36.1911, 5.4137, 'Sétif', 'Sétif', 'سطيف'],
  ['paris', 'FR', 48.8566, 2.3522, 'Paris', 'Paris', 'باريس'],
  ['marseille', 'FR', 43.2965, 5.3698, 'Marseille', 'Marseille', 'مرسيليا'],
  ['lyon', 'FR', 45.764, 4.8357, 'Lyon', 'Lyon', 'ليون'],
  ['lille', 'FR', 50.6292, 3.0573, 'Lille', 'Lille', 'ليل'],
  ['toulouse', 'FR', 43.6047, 1.4442, 'Toulouse', 'Toulouse', 'تولوز'],
  ['nice', 'FR', 43.7102, 7.262, 'Nice', 'Nice', 'نيس'],
  ['barcelona', 'ES', 41.3874, 2.1686, 'Barcelona', 'Barcelone', 'برشلونة'],
  ['madrid', 'ES', 40.4168, -3.7038, 'Madrid', 'Madrid', 'مدريد'],
  ['valencia', 'ES', 39.4699, -0.3763, 'Valencia', 'Valence', 'فالنسيا'],
  ['brussels', 'BE', 50.8503, 4.3517, 'Brussels', 'Bruxelles', 'بروكسل'],
  ['amsterdam', 'NL', 52.3676, 4.9041, 'Amsterdam', 'Amsterdam', 'أمستردام'],
  ['frankfurt', 'DE', 50.1109, 8.6821, 'Frankfurt', 'Francfort', 'فرانكفورت'],
  ['cologne', 'DE', 50.9375, 6.9603, 'Cologne', 'Cologne', 'كولونيا'],
  ['milan', 'IT', 45.4642, 9.19, 'Milan', 'Milan', 'ميلانو'],
  ['turin', 'IT', 45.0703, 7.6869, 'Turin', 'Turin', 'تورينو'],
  ['lisbon', 'PT', 38.7223, -9.1393, 'Lisbon', 'Lisbonne', 'لشبونة'],
].map(([id, country, lat, lon, en, fr, ar]) => [id,
  Object.freeze({ id, country, lat, lon, en, fr, ar }),
])));

const pairKey = (a, b) => [a, b].sort().join(':');
const road = (from, to, via = []) => Object.freeze({
  from, to, via, key: pairKey(from, to), mode: 'car',
});

// Reviewed land connections, with inland waypoints where a straight line would
// cut a bay. These illustrate journeys, not turn-by-turn driving directions.
const algeria = [
  road('algiers', 'oran', [[36.17, 1.33]]),
  road('algiers', 'bejaia', [[36.65, 4.05]]),
  road('algiers', 'setif', [[36.37, 3.90]]),
  road('bejaia', 'setif', [[36.43, 5.15]]),
  road('bejaia', 'jijel', [[36.69, 5.45]]),
  road('jijel', 'constantine', [[36.48, 6.22]]),
  road('constantine', 'annaba', [[36.70, 7.22]]),
  road('setif', 'constantine', [[36.17, 6.12]]),
];
const europe = [
  road('paris', 'brussels', [[50.1, 3.10]]),
  road('paris', 'lille'), road('lille', 'brussels'),
  road('lyon', 'marseille', [[44.5, 4.8]]),
  road('toulouse', 'barcelona', [[43.17, 2.99], [42.70, 2.9]]),
  road('barcelona', 'valencia', [[41.1, 1.2], [40.42, 0.30]]),
  road('madrid', 'valencia'),
  road('brussels', 'amsterdam', [[51.92, 4.48]]),
  road('brussels', 'cologne'), road('frankfurt', 'cologne'),
  road('milan', 'turin'),
  road('lyon', 'turin', [[45.18, 5.72], [45.08, 6.70]]),
  road('marseille', 'nice', [[43.45, 6.30]]),
  road('lisbon', 'madrid', [[38.88, -6.97]]),
];
// Concentrate international traffic on the Mediterranean / western corridor.
// This is a visual allowlist, not a claim that any particular flight is offered.
const flightDestinations = ['paris', 'marseille', 'lyon', 'toulouse', 'nice',
  'barcelona', 'madrid', 'valencia', 'brussels', 'milan', 'frankfurt', 'lisbon'];
const flights = Object.values(CITIES).filter(city => city.country === 'DZ')
  .flatMap(city => flightDestinations.map(to => Object.freeze({
    from: city.id, to, via: [], key: pairKey(city.id, to), mode: 'plane',
  })));
export const ROUTES = Object.freeze({ algeria, europe, flight: flights });
export const densityForWidth = width => width < 600
  ? ['flight', 'algeria', 'flight', 'europe', 'flight']
  : width < 1100
    ? ['flight', 'algeria', 'flight', 'europe', 'algeria', 'flight']
    : ['flight', 'algeria', 'flight', 'europe', 'flight', 'algeria', 'europe', 'flight'];

export function featuredJourney(active, previousId, rotate = false) {
  const current = active.find(journey => journey.id === previousId);
  if (current && !rotate) return current;
  return active.find(journey => journey.mode === 'plane' && journey.id !== previousId
    && journey.progress > .06 && journey.progress < .9)
    || active.find(journey => journey.mode === 'plane') || active[0];
}

export class JourneyNetwork {
  constructor(width, random = Math.random) {
    this.random = random;
    this.serial = 0;
    this.recent = { algeria: [], europe: [], flight: [] };
    this.slots = densityForWidth(width).map(category => ({ category, journey: null, wait: 0 }));
    this.slots.forEach((slot, index) => {
      this.spawn(slot);
      // Stratification plus jitter avoids a synchronized opening, even when a
      // browser supplies similar random values. No first-frame fly-in parade.
      slot.journey.progress = .08 + .74 * (index + random()) / this.slots.length;
    });
  }

  get active() { return this.slots.flatMap(slot => slot.journey ? [slot.journey] : []); }

  spawn(slot) {
    const active = this.active;
    const used = new Set(active.map(journey => journey.key));
    const degrees = new Map();
    active.forEach(({ from, to }) => [from, to].forEach(id => degrees.set(id, (degrees.get(id) || 0) + 1)));
    const recent = this.recent[slot.category];
    const available = ROUTES[slot.category].filter(route => route.key !== slot.previous
      && !used.has(route.key) && !recent.includes(route.key));
    const quiet = available.filter(route => (degrees.get(route.from) || 0) < 3 && (degrees.get(route.to) || 0) < 3);
    // Always preserve pair uniqueness and the cooldown; retry if saturated.
    const candidates = quiet.length ? quiet : available;
    if (!candidates.length) { slot.wait = 1 + this.random() * 2; return; }
    const route = candidates[Math.floor(this.random() * candidates.length)];
    slot.previous = route.key;
    const reverse = this.random() < .5;
    slot.journey = {
      ...route, id: ++this.serial, category: slot.category,
      from: reverse ? route.to : route.from, to: reverse ? route.from : route.to,
      via: reverse ? [...route.via].reverse() : route.via,
      duration: route.mode === 'plane' ? 20 + this.random() * 15 : 24 + this.random() * 18,
      progress: 0, bend: (this.random() < .5 ? -1 : 1) * (.004 + this.random() * .003),
    };
    recent.push(route.key);
    // Domestic pools are deliberately small: remember the last two on land,
    // twelve across the Mediterranean, in addition to all current pairs.
    if (recent.length > (slot.category === 'flight' ? 12 : 2)) recent.shift();
  }

  advance(seconds) {
    for (const slot of this.slots) {
      if (slot.journey) {
        slot.journey.progress += seconds / slot.journey.duration;
        if (slot.journey.progress >= 1) {
          slot.journey = null;
          slot.wait = .8 + this.random() * 3.8;
        }
      } else {
        slot.wait -= seconds;
        if (slot.wait <= 0) this.spawn(slot);
      }
    }
  }
}
