/* ShipTrip operations console — the manual DZD payout screen.
 *
 * Loaded by that one template and nothing else, because everything here is
 * about one screen's three problems: a number that must be copied rather than
 * retyped, a bank document that must be looked at without being left on the
 * page, and a set of financial commands that must not be sent twice.
 *
 * The page works with this file absent. "View proof" is a real link to a real
 * authenticated URL and opens in a tab; the reveal panel simply stays visible
 * until the operator navigates; copy buttons are the only thing that actually
 * needs script, and they are additive — the values they copy are selectable
 * text sitting right next to them.
 *
 * Nothing here ever handles a value: `copy` reads the text node the operator is
 * already looking at, writes it to the clipboard, and confirms with the word
 * "Copied". No CCP number, key or RIP is written into a message, a URL, a data
 * attribute, an event, `console`, or anything that could be collected.
 */
(function () {
  "use strict";

  var HIDE_NOTICE =
    "The payout details were hidden automatically. Reveal them again if you " +
    "still need them.";

  function announce(text) {
    var status = document.getElementById("st-copy-status");
    if (status) status.textContent = text;
  }

  /* ---------------------------------------------------------------- copy --
   * `navigator.clipboard` needs a secure context, which the console always is
   * in deployment and is not when someone runs the app over plain http on a
   * LAN address. The fallback is the old selection trick, kept because the
   * whole point of these buttons is that a person does not retype an account
   * number, and silently doing nothing would send them back to retyping it. */
  function legacyCopy(text) {
    var field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "readonly");
    field.style.position = "fixed";
    field.style.top = "-1000px";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (error) {
      ok = false;
    }
    // Clear the value before the node leaves, so the copied string does not sit
    // in a detached element waiting for garbage collection.
    field.value = "";
    document.body.removeChild(field);
    return ok;
  }

  function confirmOn(button, label, ok) {
    var original = button.getAttribute("data-copy-original") || button.textContent;
    button.setAttribute("data-copy-original", original);
    button.textContent = ok ? "Copied" : "Press Ctrl+C";
    button.classList.toggle("is-copied", ok);
    // The announcement names the field, never its value.
    announce(ok ? "Copied the " + label + "." : "Could not copy the " + label + " automatically. Select it and press Ctrl+C.");
    window.setTimeout(function () {
      button.textContent = original;
      button.classList.remove("is-copied");
    }, 2200);
  }

  function copyFrom(button) {
    var source = document.getElementById(button.getAttribute("data-copy"));
    if (!source) return;
    var label = button.getAttribute("data-copy-label") || "value";
    // The characters on screen, with only the whitespace the template's own
    // indentation introduced removed. Account numbers are copied exactly as
    // displayed, digit for digit — they are already unformatted.
    //
    // `data-copy-exact` is the one exception, and only the amount carries it:
    // the figure is *displayed* grouped, because a human checks it by eye, and
    // is *copied* as bare digits, because a bank's amount field rejects a
    // thousands separator and rejecting it sends the operator back to typing
    // fifteen thousand six hundred by hand, which is the error this button
    // exists to prevent. The digits are identical either way.
    var text = (source.getAttribute("data-copy-exact") || source.textContent).trim();
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () {
          confirmOn(button, label, true);
        },
        function () {
          confirmOn(button, label, legacyCopy(text));
        }
      );
      return;
    }
    confirmOn(button, label, legacyCopy(text));
  }

  /* ------------------------------------------------------------- reveal --
   * The server already refuses to render these values on a GET and marks the
   * response no-store, so they cannot come back by reload, history or cache.
   * This only handles the other way a bank account gets read by the wrong
   * person: an operator walking away from an unlocked screen. */
  function armAutoHide(panel) {
    var seconds = parseInt(panel.getAttribute("data-hide-after"), 10);
    if (!seconds || seconds < 0) return;
    window.setTimeout(function () {
      var list = panel.querySelector(".st-secret-list");
      if (list) list.remove();
      var note = panel.querySelector("[data-reveal-countdown]");
      if (note) note.textContent = HIDE_NOTICE;
      panel.classList.remove("is-open");
      panel.classList.add("is-hidden");
    }, seconds * 1000);
  }

  /* ----------------------------------------------------------- evidence --
   * A lightbox rather than a tab, because comparing a cheque against the masked
   * account four centimetres above it is the entire task. The image URL is set
   * only when the dialog opens, so loading this page never fetches a document,
   * and it is cleared on close so the decrypted image is not still sitting in
   * the DOM behind whatever the operator does next. */
  function openEvidence(link) {
    var dialog = document.getElementById("st-evidence-dialog");
    var image = document.getElementById("st-evidence-image");
    if (!dialog || !image || !dialog.showModal) return false;
    var title = link.getAttribute("data-evidence-title") || "Evidence";
    document.getElementById("st-evidence-dialog-title").textContent = title;
    image.alt = title;
    image.removeAttribute("src");
    image.setAttribute("referrerpolicy", "no-referrer");
    image.src = link.href;
    dialog.showModal();
    return true;
  }

  function closeEvidence() {
    var dialog = document.getElementById("st-evidence-dialog");
    var image = document.getElementById("st-evidence-image");
    if (image) image.removeAttribute("src");
    if (dialog && dialog.open) dialog.close();
  }

  /* -------------------------------------------------------- double submit --
   * Two clicks on "Record transfer evidence" is a person being unsure, not a
   * person meaning it twice. The backend is idempotent and holds the real
   * guarantee; this removes the second request so the operator never sees a
   * refusal caused by their own first click.
   *
   * The submitter's name and value are re-added as a hidden input *before*
   * anything is disabled: these forms carry their command in a button's value,
   * and a disabled button contributes nothing to the submission. */
  function guard(form, submitter) {
    if (form.hasAttribute("data-submitting")) return;
    form.setAttribute("data-submitting", "");
    if (submitter && submitter.name) {
      var relay = document.createElement("input");
      relay.type = "hidden";
      relay.name = submitter.name;
      relay.value = submitter.value;
      form.appendChild(relay);
    }
    var buttons = form.querySelectorAll("button, input[type='submit']");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].disabled = true;
      buttons[i].classList.add("is-busy");
    }
    if (submitter) submitter.setAttribute("aria-busy", "true");
  }

  /* ------------------------------------------------------- confirmations --
   * J6.4. Reject and "ask for a correction" confirm in a small dialog. The
   * trigger is a real link (`?confirm=reject#decision`) that the server answers
   * with the same dialog already open, so the decision still works with this
   * file absent; with it, the dialog opens in place as a modal. */
  function openConfirm(trigger) {
    var dialog = document.getElementById(trigger.getAttribute("data-dialog-open"));
    if (!dialog || !dialog.showModal) return false;
    if (dialog.open) dialog.close();
    dialog.showModal();
    // Never land on the committing button: Enter should not reject. Focus the
    // acknowledgement box where there is one, otherwise Cancel.
    var first =
      dialog.querySelector("input[type='checkbox']") ||
      dialog.querySelector("[data-dialog-close]");
    if (first) first.focus();
    return true;
  }

  document.addEventListener("click", function (event) {
    var opener = event.target.closest && event.target.closest("[data-dialog-open]");
    if (opener && !(event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)) {
      if (openConfirm(opener)) event.preventDefault();
      return;
    }
    var closer = event.target.closest && event.target.closest("[data-dialog-close]");
    if (closer) {
      var host = closer.closest("dialog");
      if (host && host.open) {
        event.preventDefault();
        host.close();
        // A dialog reached by link carries `?confirm=` in the address; clear it
        // so a reload does not reopen what the operator just cancelled.
        if (window.history && window.history.replaceState && window.location.search.indexOf("confirm=") !== -1) {
          window.history.replaceState(null, "", closer.getAttribute("href"));
        }
      }
      return;
    }
    var copy = event.target.closest && event.target.closest(".st-copy");
    if (copy) {
      event.preventDefault();
      copyFrom(copy);
      return;
    }
    if (event.target.closest && event.target.closest("[data-evidence-close]")) {
      event.preventDefault();
      closeEvidence();
      return;
    }
    var link = event.target.closest && event.target.closest("[data-evidence]");
    if (link) {
      // Modifier clicks stay the browser's: someone deliberately asking for a
      // new tab gets a new tab.
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      if (openEvidence(link)) event.preventDefault();
    }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form && form.hasAttribute && form.hasAttribute("data-once")) {
      guard(form, event.submitter);
    }
  });

  // Escape dismisses a modal dialog without running the close button's handler,
  // so the image has to be cleared from the dialog closing rather than from the
  // button being pressed.
  //
  // Two listeners for one job, deliberately. `close` is the event that means
  // this, and it is bound to the dialog itself because it does not bubble and a
  // document-level listener is never called for it. But it is not guaranteed to
  // arrive: it is queued as a task, and at least one Chromium build drops it
  // entirely for a programmatic `close()`. The attribute observer cannot be
  // dropped — `open` is removed synchronously by every close path there is —
  // and clearing an already-cleared `src` twice costs nothing. Leaving a
  // decrypted bank document loaded in a hidden element costs rather more.
  var dialog = document.getElementById("st-evidence-dialog");
  if (dialog) {
    var forget = function () {
      var image = document.getElementById("st-evidence-image");
      if (image) image.removeAttribute("src");
    };
    dialog.addEventListener("close", forget);
    if (window.MutationObserver) {
      new window.MutationObserver(function () {
        if (!dialog.hasAttribute("open")) forget();
      }).observe(dialog, { attributes: true, attributeFilter: ["open"] });
    }
  }

  var panels = document.querySelectorAll("[data-reveal-panel]");
  for (var i = 0; i < panels.length; i++) armAutoHide(panels[i]);

  // A confirmation the server rendered open (reached by its link) becomes a
  // real modal once script is here, so focus and Escape behave the same way.
  var opened = document.querySelectorAll("dialog.st-confirm-dialog[open]");
  for (var j = 0; j < opened.length; j++) {
    if (opened[j].showModal) {
      opened[j].close();
      opened[j].showModal();
      var focusTarget =
        opened[j].querySelector("input[type='checkbox']") ||
        opened[j].querySelector("[data-dialog-close]");
      if (focusTarget) focusTarget.focus();
    }
  }
})();
