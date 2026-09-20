// Run in an isolated Chromium page on /en/ after the hero is ready, e.g. pipe
// this file to `agent-browser --session <name> eval --stdin`. Run once normally
// and again after `set media reduced-motion` + reload. No runtime dependency.
(async () => {
  const passed = [];
  function check(value, label) {
    if (!value) throw new Error(label);
    passed.push(label);
  }
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function ready() {
    for (let i = 0; i < 100; i++) {
      if (document.querySelector('.hero-globe')?.classList.contains('is-ready')) return;
      await wait(50);
    }
    throw new Error('Hero did not become ready');
  }
  await ready();
  await document.fonts.ready;
  window.scrollTo({ top: 0, behavior: 'instant' });
  await wait(150);
  const figure = document.querySelector('.hero-globe');
  const journeys = figure.querySelector('.globe-journeys');
  const terrain = figure.querySelector('.globe-terrain');
  const button = figure.querySelector('.globe-pause');
  const pixels = () => journeys.toDataURL();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const first = pixels(), globe = terrain.toDataURL();
  await wait(850);
  check(reduced ? pixels() === first : pixels() !== first,
    reduced ? 'reduced motion keeps a complete static network' : 'vehicles and routes animate');
  check(terrain.toDataURL() === globe, 'terrain is not regenerated during animation');
  check(document.documentElement.scrollWidth === innerWidth, 'no horizontal page overflow');
  check(figure.querySelector('.globe-labels').textContent.includes('ALGERIA'), 'Algeria label rendered');
  check(!document.querySelector('.hero [aria-live]'), 'ambient route changes do not spam screen readers');
  if (!reduced) {
    button.click();
    check(button.getAttribute('aria-pressed') === 'true', 'pause exposes its pressed state');
    const paused = pixels();
    await wait(650);
    check(pixels() === paused, 'pause stops animation');
    button.click();
    await wait(650);
    check(pixels() !== paused, 'resume restarts animation');
    document.querySelector('#faq').scrollIntoView({ behavior: 'instant' });
    await wait(200);
    const offscreen = pixels();
    await wait(650);
    check(pixels() === offscreen, 'offscreen animation is suspended');
    window.scrollTo({ top: 0, behavior: 'instant' });
    await wait(700);
    check(pixels() !== offscreen, 'returning to the hero resumes animation');
  } else {
    check(getComputedStyle(button).display === 'none', 'unnecessary motion control hidden in reduced motion');
    const staticNetwork = pixels();
    await wait(1500);
    check(pixels() === staticNetwork, 'reduced motion does not spawn journeys');
  }
  const paths = ['/', '/en/', '/fr/', '/ar/', '/terms', '/terms/', '/privacy', '/privacy/',
    '/terms.html', '/privacy.html', '/support', '/prohibited-items',
    '/assets/globe/atlas.png', '/assets/globe/fallback.webp', '/assets/hero.css',
    '/assets/hero-globe.mjs', '/assets/globe-renderer.mjs', '/assets/globe-math.mjs', '/assets/globe-network.mjs'];
  for (const path of paths) {
    const response = await fetch(path);
    check(response.status === 200, `200 ${path}`);
    check(response.headers.get('content-security-policy')?.includes("default-src 'self'"), `CSP ${path}`);
  }
  check(performance.getEntriesByType('resource').every(entry => new URL(entry.name).origin === location.origin),
    'all runtime assets are same-origin');
  check(performance.getEntriesByType('resource').every(entry => !entry.responseStatus || entry.responseStatus < 400),
    'no failed static assets');
  window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
  check(!figure.classList.contains('is-ready') && button.hidden, 'pagehide disposes renderer and controls');
  const disposed = pixels();
  await wait(250);
  check(pixels() === disposed, 'no frames run after pagehide');
  window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
  await ready();
  check(figure.classList.contains('is-ready'), 'back-forward cache restore remounts the hero');
  // Remove while paused, so cleanup cannot rely on an animation callback.
  if (!reduced) button.click();
  figure.remove();
  await wait(100);
  check(!figure.classList.contains('is-ready') && button.hidden, 'DOM removal disposes a paused or static hero');
  return JSON.stringify({ mode: reduced ? 'reduced' : 'animated', passed, count: passed.length });
})()
