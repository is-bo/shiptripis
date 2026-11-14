/* Wassla operations console — the AI helper card, right after a key is made.
 *
 * Loaded only by the response that shows a new key, and only for two things:
 *
 * 1. "Copy" writes the one line on screen (`/wassla <address> <key>`) to the
 *    clipboard and says "Copied". The line is selectable text beside the
 *    button, so the page works without this file.
 * 2. The address bar is moved back to the page the admin came from. The key
 *    was rendered by a POST; without this, reloading would send that POST
 *    again and replace the key. A reload now shows the page without the key,
 *    which is what "it will not be shown again" promises.
 *
 * Nothing here stores, sends or logs the key: it is read from the text node at
 * the moment of the click and handed to the clipboard, nowhere else.
 */
(function () {
  "use strict";

  function announce(text) {
    var status = document.getElementById("st-helper-copy-status");
    if (status) status.textContent = text;
  }

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
    field.value = "";
    document.body.removeChild(field);
    return ok;
  }

  function confirmOn(button, ok) {
    var original = button.getAttribute("data-copy-original") || button.textContent;
    button.setAttribute("data-copy-original", original);
    button.textContent = ok ? "Copied" : "Press Ctrl+C";
    button.classList.toggle("is-copied", ok);
    announce(
      ok
        ? "Copied. Paste it into your assistant."
        : "Could not copy automatically. Select the line and press Ctrl+C."
    );
    window.setTimeout(function () {
      button.textContent = original;
      button.classList.remove("is-copied");
    }, 2200);
  }

  function copyFrom(button) {
    var source = document.getElementById(button.getAttribute("data-helper-copy"));
    if (!source) return;
    var text = source.textContent.trim();
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () {
          confirmOn(button, true);
        },
        function () {
          confirmOn(button, legacyCopy(text));
        }
      );
      return;
    }
    confirmOn(button, legacyCopy(text));
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-helper-copy]");
    if (!button) return;
    event.preventDefault();
    copyFrom(button);
  });

  var issued = document.querySelector("[data-helper-issued]");
  var back = issued && issued.getAttribute("data-helper-return");
  if (back && window.history && window.history.replaceState) {
    window.history.replaceState(null, "", back + "#st-ai-helper");
  }
})();
