import { CITIES, JourneyNetwork, densityForWidth, featuredJourney } from './globe-network.mjs';
import { project, vector, routePoints, sampleRoute } from './globe-math.mjs';
import { createGlobeRenderer } from './globe-renderer.mjs';

const ns = 'http://www.w3.org/2000/svg';
const plane = new Path2D('M11 0 Q11.8 .8 9 1.4 L2 2 L-3 8 L-5 8 L-3 1.8 L-8 1.2 L-10 3.6 L-11 3.6 L-10 0 L-11 -3.6 L-10 -3.6 L-8 -1.2 L-3 -1.8 L-5 -8 L-3 -8 L2 -2 L9 -1.4 Q11.8 -.8 11 0 Z');
const car = new Path2D('M-7 -3.4 Q-7 -4.4 -5 -4.4 L4 -4.4 Q7 -4.4 7 -2.3 L7 2.3 Q7 4.4 4 4.4 L-5 4.4 Q-7 4.4 -7 3.4 Z');
const countryLabels = [
  [46.7, 1.9, 'FRANCE', 'FRANCE', 'فرنسا'],
  [39.8, -4.8, 'SPAIN', 'ESPAGNE', 'إسبانيا'],
  [30.8, 3.1, 'ALGERIA', 'ALGÉRIE', 'الجزائر'],
  [32.9, -6.1, 'MOROCCO', 'MAROC', 'المغرب'],
  [33.6, 9.3, 'TUNISIA', 'TUNISIE', 'تونس'],
  [42.0, 12.8, 'ITALY', 'ITALIE', 'إيطاليا'],
];

async function mount(figure) {
  const stage = figure.querySelector('.globe-stage');
  const canvas = figure.querySelector('.globe-journeys');
  const terrain = figure.querySelector('.globe-terrain');
  const labels = figure.querySelector('.globe-labels');
  const pauseButton = figure.querySelector('.globe-pause');
  const fromLabel = figure.querySelector('[data-journey-from]');
  const toLabel = figure.querySelector('[data-journey-to]');
  const card = figure.querySelector('.journey-card');
  const fallbackNames = [fromLabel.textContent, toLabel.textContent];
  const locale = ['en', 'fr', 'ar'].includes(document.documentElement.lang) ? document.documentElement.lang : 'en';
  const context = canvas.getContext('2d');
  if (!context) return () => {};
  const abort = new AbortController();
  let disposed = false, renderer = null, resizeObserver, intersectionObserver, removalObserver;
  let frame = 0, lastTime = 0, visible = false, userPaused = false;
  let size = 0, ratio = 1, featuredId = null, featureTime = 0;
  let network = new JourneyNetwork(window.innerWidth);
  const cache = new Map();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const tokens = getComputedStyle(figure);
  const colour = name => tokens.getPropertyValue(name).trim();
  const palette = { flight: colour('--brand'), algeria: colour('--attention-print'),
    europe: colour('--mode-drive'), paper: colour('--surface-raised'), ink: colour('--text-primary') };
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    abort.abort();
    resizeObserver?.disconnect();
    intersectionObserver?.disconnect();
    removalObserver?.disconnect();
    renderer?.dispose();
    cache.clear();
    figure.classList.remove('is-ready', 'is-static');
    fromLabel.textContent = fallbackNames[0];
    toLabel.textContent = fallbackNames[1];
    card.hidden = false;
    pauseButton.hidden = true;
  };
  // Tear down even while the atlas is in flight, and before pagehide's caller
  // has received the async mount result.
  window.addEventListener('pagehide', dispose, { signal: abort.signal });
  // Static pages normally unmount on pagehide. Also support removal while
  // paused/off-screen, when no animation callback can notice disconnection.
  removalObserver = new MutationObserver(() => { if (!figure.isConnected) dispose(); });
  removalObserver.observe(document.documentElement, { childList: true, subtree: true });
  const atlas = new Image();
  atlas.src = '/assets/globe/atlas.png';
  try { await atlas.decode(); } catch { dispose(); return dispose; }
  if (disposed || !figure.isConnected) { dispose(); return dispose; }
  renderer = createGlobeRenderer(terrain, atlas);
  if (!renderer) { dispose(); return dispose; }

  function drawLabels() {
    labels.replaceChildren();
    labels.setAttribute('viewBox', `0 0 ${size} ${size}`);
    const languageIndex = { en: 2, fr: 3, ar: 4 }[locale];
    for (const label of countryLabels) {
      const point = project(vector(label[0], label[1]), size);
      if (!point.visible) continue;
      const text = document.createElementNS(ns, 'text');
      text.textContent = label[languageIndex];
      text.setAttribute('x', point.x);
      text.setAttribute('y', point.y);
      text.setAttribute('class', label[2] === 'ALGERIA' ? 'globe-country globe-country-home' : 'globe-country');
      labels.append(text);
    }
    const sea = project(vector(38.7, 7.4), size);
    const text = document.createElementNS(ns, 'text');
    text.textContent = { en: 'Mediterranean Sea', fr: 'Mer Méditerranée', ar: 'البحر الأبيض المتوسط' }[locale];
    text.setAttribute('x', sea.x);
    text.setAttribute('y', sea.y);
    text.setAttribute('class', 'globe-sea');
    labels.append(text);
  }

  function geometry(journey) {
    if (!cache.has(journey.id)) {
      const points = routePoints(journey, CITIES, size), path = new Path2D();
      let penDown = false;
      for (const point of points) {
        if (!point.visible) { penDown = false; continue; }
        if (penDown) path.lineTo(point.x, point.y); else path.moveTo(point.x, point.y);
        penDown = true;
      }
      cache.set(journey.id, { points, path });
    }
    return cache.get(journey.id);
  }

  function draw() {
    const active = network.active;
    for (const id of cache.keys()) if (!active.some(journey => journey.id === id)) cache.delete(id);
    const featured = featuredJourney(active, featuredId, featureTime >= 13);
    card.hidden = !featured;
    if (featured && featured.id !== featuredId) {
      featuredId = featured.id;
      fromLabel.textContent = CITIES[featured.from][locale];
      toLabel.textContent = CITIES[featured.to][locale];
      featureTime = 0;
    }
    context.clearRect(0, 0, size, size);
    const compact = size < 440;
    const nodes = new Map();
    for (const journey of active) {
      const { points, path } = geometry(journey);
      const opacity = Math.min(1, journey.progress * journey.duration / 1.5,
        (1 - journey.progress) * journey.duration / 2);
      const featuredRoute = journey.id === featuredId;
      context.save();
      context.globalAlpha = opacity;
      context.strokeStyle = palette.paper;
      context.lineWidth = featuredRoute ? 4 : 3;
      context.lineCap = 'round';
      context.globalAlpha *= .5;
      context.stroke(path);
      context.globalAlpha = opacity * (featuredRoute ? .9 : .56);
      context.strokeStyle = palette[journey.category];
      context.lineWidth = journey.mode === 'plane' ? 1.25 : 1.5;
      // Adapt the incumbent flight's 7/6 dash rhythm and tracer offset. Land
      // routes retain the shorter, quieter rhythm appropriate to their scale.
      context.setLineDash(journey.mode === 'plane' ? [5, 5] : [2, 3]);
      context.lineDashOffset = -journey.progress * 32;
      context.stroke(path);
      context.setLineDash([]);
      const vehicle = sampleRoute(points, journey.progress);
      if (vehicle.visible) {
        context.globalAlpha = opacity;
        context.translate(vehicle.x, vehicle.y);
        context.rotate(vehicle.angle);
        const scale = compact ? .72 : .87;
        context.scale(scale, scale);
        context.fillStyle = palette[journey.category];
        context.strokeStyle = palette.paper;
        context.lineWidth = 2.4;
        const shape = journey.mode === 'plane' ? plane : car;
        context.stroke(shape);
        context.fill(shape);
        if (journey.mode === 'car') {
          context.fillStyle = palette.paper;
          context.fillRect(1, -2.8, 1.6, 5.6);
          context.fillRect(-4.8, -2.6, 1.2, 5.2);
        }
      }
      context.restore();
      for (const id of [journey.from, journey.to]) {
        if (!nodes.has(id) || featuredRoute) nodes.set(id, { featured: featuredRoute, opacity, category: journey.category });
      }
    }
    for (const [id, node] of nodes) {
      const city = CITIES[id], point = project(vector(city.lat, city.lon), size);
      if (!point.visible) continue;
      context.save();
      context.globalAlpha = node.opacity;
      context.strokeStyle = palette[node.category];
      context.fillStyle = palette.paper;
      context.lineWidth = 1;
      context.beginPath(); context.arc(point.x, point.y, node.featured ? 4.5 : 2.7, 0, Math.PI * 2);
      context.fill(); context.stroke();
      context.fillStyle = palette[node.category];
      context.beginPath(); context.arc(point.x, point.y, node.featured ? 2 : 1.2, 0, Math.PI * 2); context.fill();
      if (node.featured) {
        const font = locale === 'ar' ? 'Noto Sans Arabic' : 'DM Sans';
        context.font = `600 ${compact ? 10 : 12}px "${font}"`;
        context.textAlign = 'left';
        context.textBaseline = 'middle';
        context.lineWidth = 3.5;
        context.strokeStyle = palette.paper;
        context.strokeText(city[locale], point.x + 8, point.y - 7);
        context.fillStyle = palette.ink;
        context.fillText(city[locale], point.x + 8, point.y - 7);
      }
      context.restore();
    }
  }

  function canAnimate() { return !disposed && visible && !document.hidden && !reduced.matches && !userPaused; }
  function tick(time) {
    frame = 0;
    if (!figure.isConnected) { dispose(); return; }
    if (!canAnimate()) return;
    if (!lastTime) lastTime = time;
    if (time - lastTime >= 1000 / 30) {
      const elapsed = Math.min((time - lastTime) / 1000, .1);
      network.advance(elapsed);
      featureTime += elapsed;
      draw();
      lastTime = time;
    }
    frame = requestAnimationFrame(tick);
  }
  function syncMotion() {
    cancelAnimationFrame(frame);
    frame = 0;
    lastTime = 0;
    figure.classList.toggle('is-static', reduced.matches);
    pauseButton.setAttribute('aria-pressed', String(userPaused));
    pauseButton.setAttribute('aria-label', userPaused ? pauseButton.dataset.resume : pauseButton.dataset.pause);
    if (canAnimate()) frame = requestAnimationFrame(tick);
  }
  function resize() {
    if (disposed) return;
    const nextSize = stage.getBoundingClientRect().width;
    const nextRatio = Math.min(window.devicePixelRatio || 1, window.innerWidth < 600 ? 1.5 : 2);
    const density = densityForWidth(window.innerWidth).length;
    if (density !== network.slots.length) {
      network = new JourneyNetwork(window.innerWidth);
      featuredId = null;
      featureTime = 0;
      cache.clear();
    }
    if (size !== nextSize || ratio !== nextRatio) {
      size = nextSize; ratio = nextRatio;
      renderer.draw(size, ratio);
      canvas.width = canvas.height = Math.round(size * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      cache.clear();
      drawLabels();
    }
    draw();
  }
  terrain.addEventListener('webglcontextlost', event => { event.preventDefault(); dispose(); }, { signal: abort.signal });
  pauseButton.addEventListener('click', () => { userPaused = !userPaused; syncMotion(); }, { signal: abort.signal });
  reduced.addEventListener('change', syncMotion, { signal: abort.signal });
  document.addEventListener('visibilitychange', syncMotion, { signal: abort.signal });
  window.addEventListener('resize', resize, { signal: abort.signal });
  resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(stage);
  intersectionObserver = new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting;
    syncMotion();
  }, { threshold: .05 });
  intersectionObserver.observe(stage);
  resize();
  figure.classList.add('is-ready');
  pauseButton.hidden = false;
  syncMotion();
  document.fonts.ready.then(() => { if (!disposed) draw(); });
  return dispose;
}

const figure = document.querySelector('[data-hero-globe]');
if (figure) {
  let cleanup, generation = 0;
  const lifecycle = new AbortController();
  const stop = () => { generation++; cleanup?.(); cleanup = null; };
  const unmounted = new MutationObserver(() => {
    if (!figure.isConnected) {
      stop();
      lifecycle.abort();
      unmounted.disconnect();
    }
  });
  const start = () => {
    const current = ++generation;
    mount(figure).then(dispose => {
      if (current !== generation || lifecycle.signal.aborted) dispose();
      else cleanup = dispose;
    });
  };
  unmounted.observe(document.documentElement, { childList: true, subtree: true });
  start();
  window.addEventListener('pagehide', event => {
    stop();
    if (!event.persisted) { lifecycle.abort(); unmounted.disconnect(); }
  }, { signal: lifecycle.signal });
  window.addEventListener('pageshow', event => { if (event.persisted) start(); }, { signal: lifecycle.signal });
}
