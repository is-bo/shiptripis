// Perspective camera, measured in sphere radii. Close framing shows a spherical
// cap centred on the Mediterranean, rather than a distant Atlantic hemisphere.
export const CAMERA = Object.freeze({ lat: 38, lon: 3, distance: 1.18, radius: .47 });
// The fixed camera's entire visible cap fits in this atlas. A regional texture
// gives crisp coasts with fewer pixels than a high-resolution world texture.
export const ATLAS = Object.freeze({ west: -55, east: 60, south: 0, north: 78 });
const radians = Math.PI / 180;
export const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
const normalize = v => { const length = Math.hypot(...v); return v.map(n => n / length); };
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export function vector(lat, lon) {
  const phi = lat * radians, lambda = lon * radians;
  return [Math.cos(phi) * Math.sin(lambda), Math.sin(phi), Math.cos(phi) * Math.cos(lambda)];
}
export const front = vector(CAMERA.lat, CAMERA.lon);
export const east = [Math.cos(CAMERA.lon * radians), 0, -Math.sin(CAMERA.lon * radians)];
export const north = cross(front, east);

export function project(point, size) {
  const z = dot(point, front), d = CAMERA.distance;
  const scale = Math.sqrt(d * d - 1) / (d - z) * size * CAMERA.radius;
  // Ray / sphere occlusion also works for slightly elevated flight arcs.
  const relative = point.map((v, i) => v - front[i] * d);
  const length = Math.hypot(...relative), ray = relative.map(v => v / length);
  const b = d * dot(front, ray), disc = b * b - (d * d - 1);
  const firstHit = disc >= 0 ? -b - Math.sqrt(disc) : Infinity;
  return { x: size / 2 + dot(point, east) * scale,
    y: size / 2 - dot(point, north) * scale,
    visible: firstHit >= length - .00001 };
}

function slerp(a, b, t) {
  const angle = Math.acos(Math.max(-1, Math.min(1, dot(a, b))));
  if (angle < .00001) return a;
  return a.map((n, i) => (n * Math.sin((1 - t) * angle) + b[i] * Math.sin(t * angle)) / Math.sin(angle));
}

export function routePoints(journey, cities, size) {
  const start = cities[journey.from], end = cities[journey.to];
  const stops = [[start.lat, start.lon], ...journey.via, [end.lat, end.lon]].map(([lat, lon]) => vector(lat, lon));
  const lengths = stops.slice(1).map((stop, i) => Math.acos(Math.min(1, dot(stops[i], stop))));
  const total = lengths.reduce((a, b) => a + b, 0);
  const side = normalize(cross(stops[0], stops.at(-1)));
  return Array.from({ length: 81 }, (_, index) => {
    const t = index / 80;
    let remaining = t * total, segment = 0;
    while (segment < lengths.length - 1 && remaining > lengths[segment]) remaining -= lengths[segment++];
    let position = slerp(stops[segment], stops[segment + 1], remaining / lengths[segment]);
    if (journey.mode === 'plane') {
      const envelope = Math.sin(Math.PI * t);
      position = normalize(position.map((v, i) => v + side[i] * journey.bend * envelope));
      position = position.map(v => v * (1 + .008 * envelope));
    }
    return project(position, size);
  });
}

// Arc-length sampling gives cars a constant visual speed through waypoints.
export function sampleRoute(points, progress) {
  let total = 0;
  const lengths = points.slice(1).map((p, i) => {
    const length = Math.hypot(p.x - points[i].x, p.y - points[i].y);
    total += length; return length;
  });
  let distance = Math.max(0, Math.min(1, progress)) * total, index = 0;
  while (index < lengths.length - 1 && distance > lengths[index]) distance -= lengths[index++];
  const a = points[index], b = points[index + 1], t = lengths[index] ? distance / lengths[index] : 0;
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t,
    angle: Math.atan2(b.y - a.y, b.x - a.x), visible: a.visible && b.visible };
}
