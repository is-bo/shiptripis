// Small, dependency-free enhancement for the public site.
// Content is rendered in HTML first so it remains usable without JavaScript.
document.querySelectorAll('[data-year]').forEach((node) => {
  node.textContent = String(new Date().getFullYear());
});
