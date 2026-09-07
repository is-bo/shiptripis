/* ShipTrip operations console — whole-row and whole-card activation.
 *
 * One delegated listener for every list in the console. There is deliberately
 * no per-page script and no per-row handler: a queue can hold fifty rows, and
 * fifty listeners to do one thing is fifty chances for one page to drift from
 * the others.
 *
 * The contract is two attributes, both emitted by the server:
 *
 *   [data-row-link]      the element that stands for one record — a table row,
 *                        or a card. It is not a link and has no role of its
 *                        own; it is a surface.
 *   [data-row-primary]   the real anchor inside it, which is the actual
 *                        navigation. It keeps its href, its focusability, its
 *                        accessible name and its context menu.
 *
 * That split is the whole accessibility story. Nothing here is required for a
 * keyboard or a screen reader to reach or open a record: Tab still lands on
 * the anchor and Enter still follows it, with or without this file. What the
 * script adds is only the pointer surface over the rest of the row, which is
 * exactly the affordance a mouse user was missing.
 *
 * What must never happen, and what each guard below is for:
 *   - a checkbox, button, menu or secondary link swallowed by the row;
 *   - a navigation fired by finishing a text selection;
 *   - two navigations from one click;
 *   - a modifier click that no longer opens a new tab or window.
 */
(function () {
  "use strict";

  // Anything that has its own meaning when clicked. `label` is here because a
  // click on a label is a click on its control; `summary` because it toggles a
  // disclosure; `[data-row-primary]` because the anchor navigates on its own
  // and must not be handled twice.
  var NESTED = "a, button, input, select, textarea, label, summary, option, " +
    "[role='button'], [role='link'], [role='checkbox'], [contenteditable='true']";

  function closest(node, selector) {
    if (!node) return null;
    // A click can land on a text node in some engines.
    var element = node.nodeType === 1 ? node : node.parentElement;
    return element && element.closest ? element.closest(selector) : null;
  }

  function target(event) {
    var row = closest(event.target, "[data-row-link]");
    if (!row) return null;
    // A nested control owns its own click, including the primary anchor, which
    // the browser is already following.
    if (closest(event.target, NESTED)) return null;
    var link = row.querySelector("[data-row-primary]");
    if (!link || !link.getAttribute("href")) return null;
    return link;
  }

  // A drag that ends inside the row is someone copying a reference, not
  // someone opening the record.
  function selecting() {
    var selection = window.getSelection && window.getSelection();
    return !!selection && !selection.isCollapsed && String(selection).trim() !== "";
  }

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0) return;
    // Shift and Alt are the browser's: new window, and download.
    if (event.shiftKey || event.altKey) return;
    var link = target(event);
    if (!link || selecting()) return;
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      window.open(link.href, "_blank", "noopener");
    } else {
      window.location.assign(link.href);
    }
  });

  // Middle-click opens a row in a background tab, the way it opens a link.
  document.addEventListener("auxclick", function (event) {
    if (event.defaultPrevented || event.button !== 1) return;
    var link = target(event);
    if (!link) return;
    event.preventDefault();
    window.open(link.href, "_blank", "noopener");
  });
})();
