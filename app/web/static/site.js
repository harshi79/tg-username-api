/* TG Username API — shared site behaviour: dynamic base URL, copy buttons,
   live health dot. No secrets, no innerHTML with dynamic data. */
(function () {
  "use strict";

  function apiBase() {
    return window.location.origin + "/api/v1";
  }

  /* Fill every [data-base-url] element with the real, current-host base URL. */
  function paintBaseUrls() {
    var base = apiBase();
    document.querySelectorAll("[data-base-url]").forEach(function (el) {
      el.textContent = base;
    });
    document.querySelectorAll("[data-base-url-suffix]").forEach(function (el) {
      el.textContent = base + el.getAttribute("data-base-url-suffix");
    });
  }

  /* Copy buttons: <button class="copy-btn" data-copy="#target-id"> */
  function bindCopyButtons() {
    document.querySelectorAll("[data-copy]").forEach(function (btn) {
      if (btn.dataset.bound === "1") return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", function () {
        var target = document.querySelector(btn.getAttribute("data-copy"));
        if (!target) return;
        var text = target.textContent || "";
        copyText(text).then(function (ok) {
          var original = btn.textContent;
          btn.textContent = ok ? "Copied" : "Select + copy";
          btn.classList.add("copied");
          window.setTimeout(function () {
            btn.textContent = original;
            btn.classList.remove("copied");
          }, 1600);
        });
      });
    });
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(
        function () { return true; },
        function () { return fallbackCopy(text); }
      );
    }
    return Promise.resolve(fallbackCopy(text));
  }

  function fallbackCopy(text) {
    try {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "absolute";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(area);
      return ok;
    } catch (err) {
      return false;
    }
  }

  /* Live health dot in the footer (best-effort, silently ignored on failure). */
  function paintHealth() {
    var dot = document.querySelector("[data-health-dot]");
    if (!dot) return;
    fetch("/api/health", { headers: { "Accept": "application/json" } })
      .then(function (res) { dot.classList.add(res.ok ? "ok" : "down"); })
      .catch(function () { dot.classList.add("down"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    paintBaseUrls();
    bindCopyButtons();
    paintHealth();
  });
})();
